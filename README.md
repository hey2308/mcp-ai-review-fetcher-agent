# Groww Weekly Pulse AI Agent

Automated weekly pipeline that ingests public App Store and Play Store reviews for Groww, analyses them into themes, generates a concise pulse note, and publishes to Google Docs and Gmail via an MCP server.

## Prerequisites

- **Python 3.11+**
- **Groq API key** — [console.groq.com/keys](https://console.groq.com/keys) (Phase 2 theme classification)
- **MCP server** — [khyati-mcp-server](https://khyati-mcp-server.onrender.com/) with Google OAuth configured (Phase 4 publish)
- **Google Doc** — create a Doc and copy its ID into `config.yaml`

## Quick Start

```bash
# 1. Clone and enter the project
cd Milestone3

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure secrets
copy .env.example .env       # Windows
# cp .env.example .env       # macOS/Linux
# Edit .env and set GROQ_API_KEY=your_key

# 5. Edit config.yaml (see Configuration below)

# 6. Run the full pipeline
python run_pipeline.py
```

## Configuration

All runtime parameters live in `config.yaml`:

| Parameter | Purpose |
|---|---|
| `review_window_weeks` | Weeks of reviews to fetch (default: 10) |
| `app_store_id` | Groww App Store ID |
| `play_store_package` | Groww Play Store package name |
| `max_words` | Pulse note word limit (250) |
| `email_alias` | Gmail draft recipient |
| `mcp_server_url` | MCP server endpoint |
| `google_doc_id` | Target Google Doc ID for weekly append |
| `llm_model` | Groq model (`llama-3.3-70b-versatile`) |

Groq throttling and batch settings (`llm_batch_size`, `llm_max_rpm`, etc.) are also in `config.yaml`.

### Environment variable overrides

These env vars **override** `config.yaml` when set (local `.env` or GitHub Actions / Render):

| Env var | Overrides | GitHub |
|---|---|---|
| `GROQ_API_KEY` | (required for live runs) | **Secret** |
| `MCP_SERVER_URL` | `mcp_server_url` | Secret |
| `EMAIL_ALIAS` | `email_alias` | Secret |
| `GOOGLE_DOC_ID` | `google_doc_id` | Secret |

You can keep defaults in `config.yaml` and only set env vars in CI, or remove the publish keys from `config.yaml` and supply them entirely via env.

## Running the Pipeline

### Full run (production)

```bash
python run_pipeline.py
```

Runs all 13 agent tools: ingest → process → generate note → publish to Google Doc + Gmail draft → verify.

### Dry run (no API costs, no publish)

```bash
python run_pipeline.py --dry-run
```

Uses keyword fallback instead of Groq; skips MCP publish. Useful for testing the pipeline locally.

### Skip publish only

```bash
python run_pipeline.py --skip-publish
```

Runs with Groq but stops before Google Doc / Gmail steps.

### Run orchestrator directly

```bash
python -m phase5.orchestrator
python -m phase5.verify
```

### Individual phases (legacy)

```bash
python -m phase1.ingest && python -m phase1.verify
python -m phase2.process && python -m phase2.verify
python -m phase3.generate && python -m phase3.verify
python -m phase4.publish && python -m phase4.verify
```

## Outputs

After a successful run, check:

| File | Contents |
|---|---|
| `data/reviews_raw.json` | Clean, deduplicated reviews |
| `data/processed_signal.json` | Themes, quotes, action ideas |
| `data/weekly_pulse.md` | Weekly pulse note (≤250 words) |
| `data/output_links.json` | Google Doc URL + Gmail draft ID |
| `data/run_log.json` | Full execution trace (13 steps) |

**Google Doc** — pulse appended to the Doc configured in `google_doc_id`.

**Gmail** — draft created in the MCP-connected account (not auto-sent).

## Weekly Automation (GitHub Actions)

Production scheduling runs on **GitHub Actions** — not Render.

| Trigger | When |
|---|---|
| **Schedule** | Every Monday 06:00 UTC |
| **Manual** | Actions → Weekly Groww Pulse → Run workflow |

Configure in **Settings → Secrets and variables → Actions → Secrets**:

| Name | Type |
|---|---|
| `GROQ_API_KEY` | Secret |
| `GOOGLE_DOC_ID` | Secret |
| `MCP_SERVER_URL` | Secret |
| `EMAIL_ALIAS` | Secret |

See [Deployment Plan](docs/deployment_plan.md) for full setup.

## Architecture

```
Phase 5 Agent Orchestrator (run_pipeline.py)
    │
    ├── fetch_app_store_reviews / fetch_play_store_reviews
    ├── merge_and_deduplicate → scrub_and_validate
    ├── classify_themes → score_and_rank_themes
    ├── extract_quotes → generate_actions
    ├── assemble_pulse_note → validate_note
    └── create_google_doc → create_gmail_draft → write_output_links
```

See `docs/architecture.md` and `docs/implementation_plan.md` for full details.

## Troubleshooting

| Error | Fix |
|---|---|
| `GROQ_API_KEY is required` | Add key to `.env` or set environment variable |
| `Missing google_doc_id` | Set `google_doc_id` in `config.yaml` |
| MCP `invalid_grant: Token expired` | Re-authenticate OAuth on the MCP server |
| `MCP server missing required tools` | Confirm server is running at `mcp_server_url` |
| Phase 2 token budget exceeded | Reduce `review_window_weeks` or wait for Groq daily reset |

## Project Structure

```
Milestone3/
├── phase1/          # Review ingestion
├── phase2/          # Theme clustering (Groq)
├── phase3/          # Pulse note generation
├── phase4/          # MCP publish (Docs + Gmail)
├── phase5/          # Agent orchestrator + verification
├── data/            # Pipeline outputs
├── docs/            # Architecture, plan, eval criteria
├── config.yaml      # Runtime configuration
├── run_pipeline.py  # Single-command entry point
└── .github/workflows/weekly-pulse.yml
```

## Documentation

- [Architecture](docs/architecture.md)
- [Implementation Plan](docs/implementation_plan.md)
- [Deployment Plan (Render)](docs/deployment_plan.md)
- [Phase 5 Evaluation](docs/eval/phase5_eval.md)
