# Deployment Plan — Groww Weekly Pulse

## Purpose

This document describes how to deploy and operate the Groww Weekly Pulse AI Agent in production:

- **GitHub Actions** — weekly scheduler and pipeline runner (this repo)
- **Render** — MCP server only (Google Docs + Gmail proxy)

Repository: [hey2308/mcp-ai-review-fetcher-agent](https://github.com/hey2308/mcp-ai-review-fetcher-agent)

---

## 1. Deployment Overview

| Component | Platform | Role |
|---|---|---|
| **Weekly pipeline scheduler** | GitHub Actions | Runs `run_pipeline.py` every Monday; commits `data/` artifacts |
| **khyati-mcp-server** | Render Web Service | OAuth + MCP tools (`append_to_doc`, `create_email_draft`) |

External dependencies (not hosted by you):

| Dependency | Purpose |
|---|---|
| Groq API | Phase 2 theme classification |
| Apple iTunes RSS | App Store review ingestion |
| Google Play Store API | Play Store review ingestion |
| Google Cloud OAuth | Managed by MCP server |

### Production architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         GITHUB (this repo)                                │
│                                                                           │
│  .github/workflows/weekly-pulse.yml                                       │
│       │  cron: Mon 06:00 UTC  +  workflow_dispatch                        │
│       ▼                                                                   │
│  run_pipeline.py  ──►  phase5 orchestrator (13 tools)                     │
│       │                    │                                              │
│       │                    ├── Groq API                                     │
│       │                    ├── App Store / Play Store                       │
│       │                    └── MCP server (HTTPS) ──────────────┐         │
│       ▼                                                           │         │
│  git commit data/*.json + weekly_pulse.md                         │         │
└───────────────────────────────────────────────────────────────────┼─────────┘
                                                                    │
┌───────────────────────────────────────────────────────────────────▼─────────┐
│                              RENDER                                        │
│  khyati-mcp-server (Web Service)                                           │
│    GET  /   GET /tools   POST /append_to_doc   POST /create_email_draft   │
│         └── Google OAuth ──► Google Doc append + Gmail draft               │
└────────────────────────────────────────────────────────────────────────────┘
```

### Design decisions

| Concern | Choice | Why |
|---|---|---|
| Scheduler | **GitHub Actions** | Free CI minutes, artifact commit to repo, no extra Render service |
| MCP / Google auth | **Render Web Service** | Must be always-reachable over HTTPS for OAuth |
| Secrets | GitHub Secrets + Variables | `GROQ_API_KEY` and publish config never in git |
| Non-secrets | `config.yaml` in repo | App IDs, Groq limits, review window |

---

## 2. Prerequisites

### 2.1 Accounts

- [ ] GitHub account with repo pushed: [mcp-ai-review-fetcher-agent](https://github.com/hey2308/mcp-ai-review-fetcher-agent)
- [ ] [Groq](https://console.groq.com) API key
- [ ] [Render](https://render.com) account (MCP server only)
- [ ] Google Cloud project (OAuth for MCP server)

### 2.2 One-time Google setup

1. Create a **Google Doc** for weekly pulse append.
2. Copy Doc ID from URL: `https://docs.google.com/document/d/<DOC_ID>/edit`
3. Store Doc ID in GitHub Secret `GOOGLE_DOC_ID` (or local `.env`).

### 2.3 Local smoke test

Before enabling the scheduler:

```bash
python run_pipeline.py --dry-run     # No Groq/MCP cost
python run_pipeline.py                 # Full run
python -m phase5.verify
```

---

## 3. Deploy GitHub Actions Scheduler

The scheduler is defined in `.github/workflows/weekly-pulse.yml` and runs automatically once deployed with secrets configured.

### 3.1 Workflow behaviour

| Trigger | When |
|---|---|
| **Schedule** | Every Monday 06:00 UTC (`0 6 * * 1`) |
| **Manual** | Actions → **Weekly Groww Pulse** → **Run workflow** |

Each run:

1. Checks out the repo
2. Installs Python 3.11 + dependencies
3. Warms up the MCP server (handles Render cold starts)
4. Runs `python run_pipeline.py --no-verify`
5. Commits updated `data/` artifacts back to `main`

> Verification runs as a separate non-blocking step so intermittent App Store empty results (AC-1.2) do not prevent artifact commits.

### 3.2 Configure GitHub Secrets and Variables

Go to **Settings → Secrets and variables → Actions** on the repo.

**Secrets** (encrypted):

| Name | Required | Example |
|---|---|---|
| `GROQ_API_KEY` | Yes | From [console.groq.com/keys](https://console.groq.com/keys) |
| `GOOGLE_DOC_ID` | Yes | `1Vxf5vjn_cg3O1oYU8l22C26A3kIceMBUsOtMzjCaA6E` |

**Variables** (plain text, not sensitive):

| Name | Required | Example |
|---|---|---|
| `MCP_SERVER_URL` | Yes | `https://khyati-mcp-server.onrender.com` |
| `EMAIL_ALIAS` | Yes | `team-alias@example.com` |

These env vars override `config.yaml` at runtime (see `phase5/config.py`).

### 3.3 Enable workflow permissions

Ensure the repo allows Actions to push commits:

1. **Settings → Actions → General**
2. **Workflow permissions** → **Read and write permissions**
3. Save

Required for the artifact commit step after each successful run.

### 3.4 Manual test run

1. Open **Actions** tab
2. Select **Weekly Groww Pulse**
3. Click **Run workflow** → **Run workflow**
4. Watch logs; confirm:
   - Pipeline step exits 0
   - New commit appears on `main` with `data/` updates
   - Google Doc appended + Gmail draft created

### 3.5 Workflow file reference

```yaml
# .github/workflows/weekly-pulse.yml
on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

jobs:
  weekly-pulse:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Warm up MCP server
        run: curl -sf --retry 3 --retry-delay 10 "${MCP_SERVER_URL%/}/"
        env:
          MCP_SERVER_URL: ${{ vars.MCP_SERVER_URL }}
      - name: Run weekly pipeline
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          MCP_SERVER_URL: ${{ vars.MCP_SERVER_URL }}
          EMAIL_ALIAS: ${{ vars.EMAIL_ALIAS }}
          GOOGLE_DOC_ID: ${{ secrets.GOOGLE_DOC_ID }}
        run: python run_pipeline.py --no-verify
      - name: Verify pipeline output
        continue-on-error: true
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          MCP_SERVER_URL: ${{ vars.MCP_SERVER_URL }}
          EMAIL_ALIAS: ${{ vars.EMAIL_ALIAS }}
          GOOGLE_DOC_ID: ${{ secrets.GOOGLE_DOC_ID }}
        run: python -m phase5.verify
      - name: Commit weekly artifacts
        if: success()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/reviews_raw.json data/processed_signal.json data/weekly_pulse.md data/output_links.json data/run_log.json
          git diff --staged --quiet || git commit -m "Weekly pulse run $(date -u +%Y-%m-%d)"
          git push
```

---

## 4. Deploy MCP Server on Render

The MCP server lives in a **separate repo**: [hey2308/khyati-mcp-server](https://github.com/hey2308/khyati-mcp-server).

**Production URL:** `https://khyati-mcp-server.onrender.com`

### 4.1 Create Web Service

1. Render Dashboard → **New** → **Web Service**
2. Connect `khyati-mcp-server` repository
3. Configure:

| Setting | Value |
|---|---|
| **Name** | `khyati-mcp-server` |
| **Runtime** | Python 3 |
| **Build command** | `pip install -r requirements.txt` |
| **Start command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Starter recommended (avoids cold starts) |

### 4.2 MCP environment variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth client secret |
| `GOOGLE_REDIRECT_URI` | Yes | `https://khyati-mcp-server.onrender.com/oauth2callback` |

Complete OAuth once via the MCP server's auth flow. Re-auth if you see `invalid_grant`.

### 4.3 Verify MCP server

```bash
curl https://khyati-mcp-server.onrender.com/
curl https://khyati-mcp-server.onrender.com/tools
```

Set `MCP_SERVER_URL` GitHub variable to this URL.

### 4.4 Cold-start note

Free-tier Render services spin down when idle. The GitHub Actions workflow includes an MCP warm-up step before each run. If publish still times out, upgrade the MCP service to **Starter**.

---

## 5. Deployment Checklist

### GitHub (scheduler)

- [ ] Repo pushed to GitHub
- [ ] Secret `GROQ_API_KEY` set
- [ ] Secret `GOOGLE_DOC_ID` set
- [ ] Variable `MCP_SERVER_URL` set
- [ ] Variable `EMAIL_ALIAS` set
- [ ] Workflow permissions: read and write
- [ ] Manual workflow run succeeds
- [ ] `data/` commit appears on `main`

### Render (MCP only)

- [ ] Web Service deployed and healthy
- [ ] OAuth completed
- [ ] `/tools` returns `append_to_doc`, `create_email_draft`

### Post-deploy verification

- [ ] Google Doc has new weekly section
- [ ] Gmail draft in Drafts folder
- [ ] `data/run_log.json` shows 13 steps with `"status": "success"`
- [ ] `data/output_links.json` has valid `doc_url` and `draft_id`

---

## 6. Monitoring and Operations

### 6.1 GitHub Actions

| What to watch | Where |
|---|---|
| Run history | Actions → Weekly Groww Pulse |
| Failed runs | Red X on workflow run; expand failed step logs |
| Artifact commits | Commits by `github-actions[bot]` on `main` |

### 6.2 Render (MCP)

| What to watch | Where |
|---|---|
| Service uptime | Render → khyati-mcp-server → Metrics |
| OAuth errors | MCP server logs |

### 6.3 Log signals

| Log line | Meaning |
|---|---|
| `Pipeline completed successfully` | Orchestrator finished |
| `Tool classify_themes failed` | Groq key, rate limit, or budget issue |
| `MCP health check failed` | Server down, cold start, or OAuth expired |
| `GROQ_API_KEY is required` | Missing GitHub secret |
| `No artifact changes to commit` | Run succeeded but data unchanged |

### 6.4 Notifications

Enable GitHub notifications for workflow failures:

**Settings → Notifications → Actions** — email on failed workflows.

---

## 7. Rollback Plan

| Scenario | Action |
|---|---|
| Bad pipeline code | Revert commit on `main`; re-run workflow |
| Bad pulse content | Do not send Gmail draft; Doc append is additive |
| Groq outage | Wait and manually trigger workflow |
| MCP OAuth expired | Re-auth on Render MCP server; re-run workflow |
| Wrong secrets | Update GitHub Secrets/Variables; re-run workflow |

---

## 8. Cost Estimate

| Service | Cost |
|---|---|
| GitHub Actions | Free tier: 2,000 min/month (private repos); ~5–10 min/week ≈ 40 min/month |
| Render MCP Web Service | Free (cold starts) or ~$7/mo Starter |
| Groq API | Free tier sufficient (~20 requests/week) |

---

## 9. Security

| Item | Guidance |
|---|---|
| `GROQ_API_KEY` | GitHub Secret only |
| `GOOGLE_DOC_ID`, `EMAIL_ALIAS` | GitHub Secret / Variable — not in git |
| `.env` | Local only; listed in `.gitignore` |
| `config.yaml` | Safe to commit (non-secret tuning params) |
| Google OAuth tokens | MCP server only; agent never sees them |
| Gmail | Draft-only — never auto-sent |

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow not running on schedule | GitHub disables cron on inactive repos | Manual trigger; push a commit to re-enable |
| `Resource not accessible by integration` | Missing write permissions | Enable read/write workflow permissions |
| Push step fails | Branch protection blocking bot | Allow GitHub Actions to push to `main` |
| `GROQ_API_KEY is required` | Secret missing | Add secret in repo settings |
| MCP timeout | Render cold start | Warm-up step runs automatically; upgrade MCP plan |
| `invalid_grant` | OAuth expired | Re-auth MCP server |
| Verify step yellow/warning | AC-1.2 App Store empty | Expected sometimes; Play Store data still valid |
| No Doc update | Wrong `GOOGLE_DOC_ID` | Fix secret and re-run |

---

## 11. Local development vs production

| Setting | Local | GitHub Actions |
|---|---|---|
| Secrets | `.env` file | GitHub Secrets + Variables |
| Scheduler | Manual `python run_pipeline.py` | Cron Mon 06:00 UTC |
| Artifacts | Written to `data/` | Committed to repo |
| MCP URL | `MCP_SERVER_URL` in `.env` | `vars.MCP_SERVER_URL` |

Copy `.env.example` to `.env` for local runs:

```bash
copy .env.example .env   # Windows
```

---

## 12. Related Documentation

| Document | Contents |
|---|---|
| [architecture.md](architecture.md) | System layers, MCP flow |
| [implementation_plan.md](implementation_plan.md) | Weekly scheduler details |
| [eval/phase5_eval.md](eval/phase5_eval.md) | End-to-end verification |
| [README.md](../README.md) | Quick start |
| [decision.md](decision.md) | MCP-first, draft-only email |

---

## 13. Deployment Timeline

| Step | Duration |
|---|---|
| Push repo to GitHub | 5 min |
| Configure Secrets + Variables | 10 min |
| MCP server on Render (if not already live) | 15 min |
| MCP OAuth | 10 min |
| Local smoke test | 10 min |
| Manual GitHub Actions test run | 10 min |
| **Total (first deploy)** | **~1 hour** |

Subsequent code changes deploy automatically on push to `main`; the scheduler picks up the latest code on the next run.
