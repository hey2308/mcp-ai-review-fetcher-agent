# Deployment Plan — Groww Weekly Pulse on Render

## Purpose

This document describes how to deploy and operate the Groww Weekly Pulse AI Agent on [Render](https://render.com). It covers service topology, environment configuration, scheduling, verification, and operational runbooks.

---

## 1. Deployment Overview

The system has two deployable components:

| Component | Render service type | Role | Status |
|---|---|---|---|
| **khyati-mcp-server** | Web Service | Google Docs + Gmail proxy (OAuth, MCP tools) | Already deployed |
| **groww-weekly-pulse** | Cron Job | Weekly review ingestion → analysis → publish | To deploy |

External dependencies (not hosted on Render):

| Dependency | Purpose |
|---|---|
| Groq API | Phase 2 theme classification (`llama-3.3-70b-versatile`) |
| Apple iTunes RSS | App Store review ingestion |
| Google Play Store API | Play Store review ingestion |
| Google Cloud OAuth | Managed by MCP server (Docs + Gmail scopes) |

### Architecture on Render

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              RENDER                                      │
│                                                                          │
│  ┌──────────────────────────┐      ┌─────────────────────────────────┐  │
│  │  khyati-mcp-server       │      │  groww-weekly-pulse (Cron Job)  │  │
│  │  Web Service             │◄─────│  Mon 06:00 UTC                  │  │
│  │                          │ HTTP │  python run_pipeline.py         │  │
│  │  GET  /                  │      │                                 │  │
│  │  POST /append_to_doc     │      │  Reads config.yaml from repo    │  │
│  │  POST /create_email_draft│      │  Uses GROQ_API_KEY (env secret) │  │
│  └────────────┬─────────────┘      └──────────────┬──────────────────┘  │
│               │ OAuth                              │                       │
└───────────────┼────────────────────────────────────┼───────────────────────┘
                │                                    │
                ▼                                    ▼
        Google Workspace                    Groq API + App/Play stores
        (Doc append + Gmail draft)          (reviews + classification)
```

### Recommended deployment model

| Layer | Where to run | Why |
|---|---|---|
| MCP server | **Render Web Service** | Must be reachable over HTTPS for OAuth and tool calls |
| Weekly pipeline | **Render Cron Job** *or* **GitHub Actions** | Batch job; no always-on server needed |
| Artifact storage | **Git repo** (GitHub Actions) or **ephemeral** (Render Cron) | Render Cron disks are wiped after each run |

> **Current setup:** GitHub Actions runs the pipeline weekly and commits `data/` artifacts back to the repo. Render hosts only the MCP server. You can keep this split or move scheduling entirely to Render — both options are documented below.

---

## 2. Prerequisites

Complete these before deploying:

### 2.1 Accounts and access

- [ ] [Render](https://render.com) account (GitHub-connected)
- [ ] [Groq](https://console.groq.com) API key
- [ ] Google Cloud project with OAuth 2.0 credentials (for MCP server)
- [ ] GitHub repository with this codebase pushed

### 2.2 One-time Google setup

1. Create a **Google Doc** for weekly pulse append.
2. Copy the Doc ID from the URL:  
   `https://docs.google.com/document/d/<DOC_ID>/edit`
3. Set `google_doc_id` in `config.yaml`.
4. Deploy and authenticate the MCP server (Section 3).

### 2.3 Local smoke test

Before deploying to Render, confirm the pipeline works locally:

```bash
python run_pipeline.py --dry-run    # No Groq/MCP cost
python run_pipeline.py                # Full run against live MCP server
python -m phase5.verify
```

---

## 3. Deploy MCP Server (Web Service)

The MCP server is a separate repository: [hey2308/khyati-mcp-server](https://github.com/hey2308/khyati-mcp-server).

**Production URL:** `https://khyati-mcp-server.onrender.com`

### 3.1 Create the Web Service

1. Render Dashboard → **New** → **Web Service**
2. Connect the `khyati-mcp-server` repository
3. Configure:

| Setting | Value |
|---|---|
| **Name** | `khyati-mcp-server` |
| **Region** | Same region as Cron Job (e.g. Oregon) |
| **Branch** | `main` |
| **Runtime** | Python 3 |
| **Build command** | `pip install -r requirements.txt` |
| **Start command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Starter (recommended for production) or Free |

### 3.2 Environment variables (MCP server)

Set these in Render → Service → **Environment**:

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | OAuth client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Yes | `https://<your-mcp-service>.onrender.com/oauth2callback` |
| `TOKEN_PATH` | Optional | Path to persisted refresh token on disk |

> OAuth tokens on Render free tier are lost on redeploy unless stored in a **Persistent Disk** or external secret store. Use a Render disk mount or re-authenticate after each deploy on free tier.

### 3.3 Google Cloud OAuth configuration

In [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials:

1. Create OAuth 2.0 Client (Web application).
2. Add authorized redirect URI:  
   `https://khyati-mcp-server.onrender.com/oauth2callback`
3. Enable APIs: **Google Docs API**, **Gmail API**.
4. Complete OAuth consent flow once via the MCP server's auth endpoint.

### 3.4 Verify MCP server

```bash
curl https://khyati-mcp-server.onrender.com/
curl https://khyati-mcp-server.onrender.com/tools
```

Expected tools: `append_to_doc`, `create_email_draft`.

Update `config.yaml` in the pipeline repo:

```yaml
mcp_server_url: "https://khyati-mcp-server.onrender.com"
```

### 3.5 Cold-start mitigation

Render free-tier Web Services spin down after ~15 minutes of inactivity. The first request after idle may take 30–60 seconds.

The pipeline already performs an MCP health check before publish (`create_google_doc` tool). If cold starts cause timeouts:

- Upgrade MCP server to **Starter** plan (always on), or
- Add a warm-up step at the start of the Cron Job (see Section 4.5).

---

## 4. Deploy Weekly Pipeline (Cron Job)

Deploy the pipeline from **this repository** (`Milestone3`) as a Render Cron Job.

### 4.1 Create the Cron Job

1. Render Dashboard → **New** → **Cron Job**
2. Connect the `Milestone3` GitHub repository
3. Configure:

| Setting | Value |
|---|---|
| **Name** | `groww-weekly-pulse` |
| **Region** | Same as MCP server |
| **Branch** | `main` |
| **Runtime** | Python 3 |
| **Build command** | `pip install -r requirements.txt` |
| **Start command** | `python run_pipeline.py --no-verify` |
| **Schedule** | `0 6 * * 1` (every Monday 06:00 UTC) |
| **Plan** | Starter recommended (45 min timeout, more CPU) |

> Use `--no-verify` in Cron to avoid failing the job on AC-1.2 when App Store returns zero reviews. Run verification manually after deploy or from CI.

For verification in production Cron:

```bash
python run_pipeline.py && python -m phase5.verify
```

### 4.2 Environment variables (pipeline)

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key for Phase 2 classification |
| `PYTHONUNBUFFERED` | Recommended | `1` — flush logs immediately |

All other settings come from `config.yaml` committed in the repo (`google_doc_id`, `email_alias`, `mcp_server_url`, etc.).

**Do not commit secrets.** Only `GROQ_API_KEY` should be a Render secret.

### 4.3 Optional: override config via env

If you need environment-specific values without changing `config.yaml`, extend the pipeline to read overrides (future enhancement):

| Variable | Overrides |
|---|---|
| `GOOGLE_DOC_ID` | `google_doc_id` in config |
| `MCP_SERVER_URL` | `mcp_server_url` in config |
| `EMAIL_ALIAS` | `email_alias` in config |

> Phase 4 `publish.py` already supports `GOOGLE_DOC_ID` from environment as a fallback.

### 4.4 Example `render.yaml` (Blueprint)

Add this file to the repo root to deploy both services via Infrastructure-as-Code:

```yaml
services:
  # Weekly pipeline — Cron Job
  - type: cron
    name: groww-weekly-pulse
    runtime: python
    region: oregon
    plan: starter
    schedule: "0 6 * * 1"
    buildCommand: pip install -r requirements.txt
    startCommand: python run_pipeline.py --no-verify
    envVars:
      - key: GROQ_API_KEY
        sync: false
      - key: PYTHONUNBUFFERED
        value: "1"

  # MCP server — deploy from khyati-mcp-server repo separately
  # (included here for reference; use the MCP server's own render.yaml)
```

Deploy via: Render Dashboard → **Blueprints** → Connect repo → Apply.

### 4.5 Optional warm-up script

Add to the start command if MCP cold starts cause publish failures:

```bash
curl -sf https://khyati-mcp-server.onrender.com/ && python run_pipeline.py
```

### 4.6 Artifact persistence on Render

Render Cron Job filesystem is **ephemeral**. After each run, `data/*.json` and `weekly_pulse.md` are discarded unless you:

| Strategy | How |
|---|---|
| **GitHub Actions (current)** | Workflow commits artifacts to the repo after each run |
| **Render Cron only** | Rely on Google Doc + Gmail draft as durable outputs; skip artifact retention |
| **External storage** | Upload `data/` to S3/GCS at end of run (not implemented) |

**Recommendation:** Keep GitHub Actions for artifact versioning, or use Render Cron if Google Doc + Gmail are sufficient audit trails.

---

## 5. Scheduling Options

| Option | Schedule | Artifact commit | Best for |
|---|---|---|---|
| **GitHub Actions** (current) | `0 6 * * 1` Mon 06:00 UTC | Yes — pushes to repo | Audit trail, free CI minutes |
| **Render Cron Job** | Same cron expression | No (ephemeral disk) | All-in-Render stack |
| **Both** | Same time (avoid!) | Duplicate runs | Not recommended |

Manual triggers:

- **GitHub:** Actions → Weekly Groww Pulse → Run workflow
- **Render:** Cron Job → **Trigger Run**

---

## 6. Deployment Checklist

### Pre-deploy

- [ ] `config.yaml` has valid `google_doc_id`, `email_alias`, `mcp_server_url`
- [ ] `GROQ_API_KEY` set in Render Cron Job secrets
- [ ] MCP server OAuth completed and token persisted
- [ ] Local full run succeeded (`python run_pipeline.py`)
- [ ] MCP health check returns 200 (`GET /`)

### Deploy MCP server

- [ ] Web Service created and deployed
- [ ] OAuth redirect URI matches Render URL
- [ ] `/tools` lists `append_to_doc` and `create_email_draft`

### Deploy pipeline Cron Job

- [ ] Cron Job created from Milestone3 repo
- [ ] Schedule set to `0 6 * * 1`
- [ ] `GROQ_API_KEY` configured
- [ ] Manual **Trigger Run** succeeds

### Post-deploy verification

- [ ] `data/run_log.json` shows all 13 steps with `"status": "success"` (if inspecting logs)
- [ ] Google Doc has new appended section for current week
- [ ] Gmail draft visible in Drafts folder
- [ ] Render Cron Job logs show exit code 0
- [ ] Run `python -m phase5.verify` locally against committed artifacts (if using GitHub Actions)

---

## 7. Monitoring and Operations

### 7.1 Render dashboards

| What to watch | Where |
|---|---|
| Cron Job run history | Render → groww-weekly-pulse → **Logs** |
| MCP server uptime | Render → khyati-mcp-server → **Metrics** |
| Failed runs | Render → Cron Job → failed run entries |

### 7.2 Log signals

| Log line | Meaning |
|---|---|
| `Pipeline completed successfully` | Full run OK |
| `Tool classify_themes failed` | Groq API key, rate limit, or budget issue |
| `MCP health check failed` | Server down, cold start timeout, or OAuth expired |
| `invalid_grant: Token expired` | Re-authenticate MCP server OAuth |
| `GROQ_API_KEY is required` | Missing Render secret |

### 7.3 Alerts (recommended)

Configure Render notifications (email/Slack) for:

- Cron Job run failure
- MCP Web Service deploy failure or health check failure

---

## 8. Rollback Plan

| Scenario | Action |
|---|---|
| Bad pipeline deploy | Render → Cron Job → **Rollback** to previous deploy |
| Bad MCP deploy | Rollback MCP Web Service; re-run OAuth if tokens lost |
| Bad pulse content | Do not send Gmail draft; append is additive in Doc — add correction manually |
| Groq outage | Wait and re-trigger run; or use `--dry-run` locally for testing only |
| OAuth revoked | Re-complete OAuth on MCP server; trigger pipeline manually |

---

## 9. Cost Estimate (Render)

| Service | Free tier | Starter (~$7/mo each) |
|---|---|---|
| MCP Web Service | Spins down when idle; cold starts | Always on, no cold start |
| Cron Job | 750 hrs/mo shared; 30 min max/run | 45 min max/run, dedicated resources |

Groq API costs are separate (free tier: 30 RPM, 1K RPD for `llama-3.3-70b-versatile`). One weekly run ≈ 20 Groq requests, well within free limits.

---

## 10. Security

| Item | Guidance |
|---|---|
| `GROQ_API_KEY` | Render secret only; never commit to git |
| Google OAuth tokens | Stored on MCP server only; agent never sees them |
| `config.yaml` | Safe to commit (Doc ID and email alias are not secrets) |
| Gmail | Draft-only — pipeline never sends email automatically |
| PII | Stripped at ingestion; no PII in output artifacts |

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Cron Job exits 1 immediately | Missing `GROQ_API_KEY` | Add secret in Render env |
| MCP timeout on publish | Cold start on free tier | Warm-up curl or upgrade plan |
| `invalid_grant` on append/draft | OAuth token expired | Re-auth MCP server |
| Empty App Store reviews | iTunes RSS returned 0 | Expected intermittently; Play Store data still valid |
| Cron succeeds but no Doc update | Wrong `google_doc_id` | Verify ID in `config.yaml` |
| Duplicate weekly runs | GitHub Actions + Render Cron both active | Disable one scheduler |

---

## 12. Related Documentation

| Document | Contents |
|---|---|
| [architecture.md](architecture.md) | System layers, MCP flow, data artifacts |
| [implementation_plan.md](implementation_plan.md) | Phase 4 MCP setup, weekly scheduler |
| [eval/phase5_eval.md](eval/phase5_eval.md) | End-to-end verification criteria |
| [README.md](../README.md) | Local setup and run commands |
| [decision.md](decision.md) | D-001 MCP-first, D-010 draft-only email |

---

## 13. Deployment Timeline

| Step | Duration | Owner |
|---|---|---|
| Google Cloud OAuth + Doc setup | 30 min | Developer |
| MCP server deploy on Render | 15 min | Developer |
| MCP OAuth authentication | 10 min | Developer |
| Pipeline local smoke test | 10 min | Developer |
| Cron Job deploy on Render | 10 min | Developer |
| Manual trigger + verification | 15 min | Developer |
| **Total (first deploy)** | **~1.5 hours** | |

Subsequent deploys (code changes only): ~5 minutes via Render auto-deploy on git push.
