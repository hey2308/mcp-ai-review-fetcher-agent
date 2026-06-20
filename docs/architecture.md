# Architecture — Groww Weekly Pulse AI Agent

## 1. System Overview

### What This System Does
The Groww Weekly Pulse AI Agent is an automated pipeline that converts raw, unstructured public mobile-app reviews (Apple App Store + Google Play Store) into a concise, structured weekly intelligence note for product and business teams. The note is then delivered through two Google Workspace surfaces — a Google Doc (readable, shareable) and a Gmail draft (actionable, sendable) — without any manual steps once the pipeline is triggered.

### Core Design Philosophy
- **Privacy-first**: PII is removed at the earliest possible point in the pipeline (ingestion), not just before output
- **MCP-first**: All Google Workspace interactions happen through MCP (Model Context Protocol) servers — there is no bespoke OAuth or REST client code inside the agent
- **LLM as reasoning engine, not glue**: The LLM is used for tasks it is genuinely good at (semantic classification, summarisation, action generation). Deterministic tasks (deduplication, field filtering, word count) are handled by conventional logic
- **Single source of truth per step**: Each pipeline stage emits one clean, well-defined output artifact that the next stage consumes — no side channels, no shared mutable state
- **Reproducibility**: Every run is logged with timestamps and inputs so that any weekly note can be traced back to the exact reviews it was derived from

---

## 2. High-Level Architecture Diagram

```
╔══════════════════════════════════════════════════════════════════════════╗
║                         AGENT ORCHESTRATOR                               ║
║           (LLM-driven, sequential tool-calling loop)                     ║
║                                                                          ║
║  System prompt → encodes task, constraints, tool list, output schema     ║
╚══════╦═══════════════════════════════════════════════════╦═══════════════╝
       ║                                                   ║
       ▼                                                   ▼
╔══════════════════╗                           ╔══════════════════════════╗
║  DATA INGESTION  ║                           ║    MCP SERVER LAYER      ║
║  LAYER           ║                           ║                          ║
║                  ║                           ║  ┌──────────────────┐    ║
║  ┌─────────────┐ ║                           ║  │ Google Docs MCP  │    ║
║  │ App Store   │ ║                           ║  │ (create / update │    ║
║  │ (iTunes RSS)│ ║                           ║  │  document)       │    ║
║  └──────┬──────┘ ║                           ║  └────────┬─────────┘    ║
║         │        ║                           ║           │              ║
║  ┌─────────────┐ ║                           ║  ┌──────────────────┐    ║
║  │ Play Store  │ ║                           ║  │ Gmail MCP        │    ║
║  │ (public API)│ ║                           ║  │ (create draft)   │    ║
║  └──────┬──────┘ ║                           ║  └────────┬─────────┘    ║
╚═════════╬════════╝                           ╚═══════════╬══════════════╝
          ║                                               ║
          ▼                                               ▼
╔══════════════════╗                           ╔══════════════════════════╗
║  PROCESSING      ║                           ║  GOOGLE WORKSPACE        ║
║  LAYER           ║                           ║                          ║
║                  ║                           ║  • Google Doc            ║
║  • Deduplication ║                           ║    (Pulse Document)      ║
║  • PII Scrub     ║                           ║  • Gmail Draft           ║
║  • Theme         ║                           ║    (Draft Email)         ║
║    Clustering    ║                           ╚══════════════════════════╝
║  • Sentiment     ║
║    Scoring       ║
║  • Theme Ranking ║
║  • Quote         ║
║    Extraction    ║
║  • Action Ideas  ║
╚════════╦═════════╝
         ║
         ▼
╔══════════════════╗
║  PULSE NOTE      ║
║  GENERATOR       ║
║                  ║
║  • Structured    ║
║    Markdown note ║
║  • ≤250 words    ║
║  • Top 3 themes  ║
║  • 3 quotes      ║
║  • 3 actions     ║
╚══════════════════╝
```

---

## 3. Detailed Layer Descriptions

### Layer 1 — Data Ingestion

**Purpose**: Acquire all publicly available reviews for Groww within the target time window, normalise them into a consistent schema, and strip any PII before anything is persisted to disk.

#### 3.1.1 Sources

| Store | Endpoint / Method | Auth Required | Format |
|---|---|---|---|
| Apple App Store | iTunes RSS customer reviews feed | None (public) | JSON / XML |
| Google Play Store | Public Play Store review API / scraper | None (public) | JSON |

The Apple RSS feed is an official, documented Apple endpoint that returns the most recent reviews for any publicly listed app. The Play Store reviews are accessed via a public-facing scraper that reads the same data visible to any unauthenticated user browsing the store.

#### 3.1.2 Time Window Filtering
- Only reviews with a `date` field within the last **8–12 weeks** (configurable) are retained
- Reviews outside this window are discarded at parse time — they never enter the dataset
- The exact window boundaries are stored in `config.yaml` so they can be adjusted without touching logic

#### 3.1.3 Schema Normalisation
Both stores return data in different shapes. After ingestion, every review is mapped to a common schema:

```
Review {
  id        : string   (store-specific review ID, used for dedup)
  store     : enum     ("app_store" | "play_store")
  rating    : integer  (1–5)
  title     : string   (review headline)
  text      : string   (review body)
  date      : date     (ISO 8601)
}
```

All other fields returned by the source (reviewer display name, device model, OS version, helpfulness votes, developer response) are **not included** in the schema and are discarded at parse time.

In addition to schema normalization, ingestion applies quality filters before persistence:
- Minimum review length: at least 6 words in `text`
- Emoji exclusion: reject reviews containing emojis in `title` or `text`
- Language filter: keep English-only reviews

#### 3.1.4 PII Handling at Ingestion
- **Structural PII** (reviewer name, user ID, device identifier) — dropped by not mapping these fields into the schema
- **Embedded PII** (names, emails, phone numbers written inside the review text) — flagged and stripped by a secondary LLM scrub pass in the Processing Layer

#### 3.1.5 Deduplication
Because the same user sometimes posts identical or near-identical reviews on both stores, a deduplication pass removes records where the hash of `(normalised_title + normalised_text)` matches an existing record. The first-seen record is kept; the duplicate is discarded.

---

### Layer 2 — Processing

**Purpose**: Transform the raw, deduplicated review dataset into structured signal — themed clusters, sentiment scores, ranked quotes, and action ideas — ready for the pulse note generator.

**LLM provider**: Phase 2 uses **Groq** with model `llama-3.3-70b-versatile`. Calls are budgeted against the model's free-tier limits and must not be issued per-review.

| Limit | Value | Pipeline guardrail |
|---|---|---|
| Requests per minute | 30 | Throttle to **≤ 24 RPM** (2.5 s minimum between calls) |
| Requests per day | 1,000 | One full run uses **~32 requests** — well within daily cap |
| Tokens per minute | 12,000 | Pause when rolling 60 s token sum exceeds **10,000** |
| Tokens per day | 100,000 | Pre-flight estimate must stay **≤ 90,000**; halt if exceeded |

**Dataset cap**: Phase 2 processes at most **1,000 reviews** per run (most recent first if Phase 1 output is larger). This keeps token usage predictable while the pipeline is being built.

#### 3.2.0 Groq-Aware Call Strategy (Hybrid Pipeline)

To stay within Groq limits, Phase 2 uses a **hybrid** design: deterministic logic first, Groq only where needed, and **one batched Groq call per chunk** instead of one call per review.

```
reviews_raw.json (≤ 1,000 records)
        │
        ▼
┌───────────────────────┐
│ Regex PII scrub       │  ← no Groq calls
└───────────┬───────────┘
            ▼
┌───────────────────────┐
│ Keyword pre-router    │  ← no Groq calls; high-confidence single-theme hits
└───────────┬───────────┘
            ▼
┌───────────────────────┐
│ Groq batch classify   │  ← ~28 batched calls (20 reviews each)
│ + sentiment adjust    │     combined in one JSON response per batch
└───────────┬───────────┘
            ▼
┌───────────────────────┐
│ Deterministic ranking │  ← no Groq calls
└───────────┬───────────┘
            ▼
┌───────────────────────┐
│ Groq quote pick (×3)  │  ← 3 calls; LLM picks from pre-shortlisted candidates
└───────────┬───────────┘
            ▼
┌───────────────────────┐
│ Groq action ideas (×1)│  ← 1 call on top-3 theme summary only
└───────────┬───────────┘
            ▼
   processed_signal.json
```

**Per-run Groq budget (1,000 reviews, worst case)**:

| Step | Requests | Est. tokens |
|---|---|---|
| Classify + sentiment (batched) | ~28 | ~84,000 |
| Quote selection (top 3 themes) | 3 | ~6,000 |
| Action idea generation | 1 | ~4,000 |
| **Total** | **~32** | **~94,000** |

Token savings levers baked into the design:
- **Truncate review text** sent to Groq to the first 50 words (classification only; full text retained locally for verbatim quote verification)
- **Pre-route** reviews with unambiguous keyword matches to a theme without calling Groq (~35–45% of records based on current dataset profiling)
- **Combine** theme classification and sentiment adjustment in a single batched JSON response (halves request count vs. separate passes)
- **Regex-only PII scrub** in Phase 2 — no per-review LLM scrub pass

#### 3.2.1 PII Scrub Pass (Secondary)
Even after field-level PII removal at ingestion, free-text fields (`title`, `text`) can contain embedded PII. Phase 2 applies a **regex-based scrub** (emails, phone numbers, account-number patterns) and replaces matches with `[REDACTED]`. This avoids spending Groq tokens on a dedicated per-review LLM scrub pass. Records that fail the regex scan are flagged in the run log for manual review.

#### 3.2.2 Theme Classification

Reviews not assigned by the keyword pre-router are classified into exactly one of five predefined themes using **batched zero-shot Groq classification** (not one call per review):

| Theme | What It Covers |
|---|---|
| Onboarding & Account Setup | First-run experience, registration, account activation, app navigation for new users |
| KYC & Verification | Document upload, video verification, rejection reasons, re-submission loops |
| Payments & Transactions | Fund transfers, SIP setup, order execution, payment failures, UPI issues |
| Portfolio & Statements | P&L display, holdings view, statement downloads, tax documents |
| Performance & App Stability | App crashes, slow load times, UI glitches, login issues, battery usage |

Each Groq batch call receives:
- Up to 20 reviews (id, rating, truncated title + text)
- The list of five themes with descriptions
- Instructions to return structured JSON: `{ review_id, theme, sentiment_adjustment }` per review

The keyword pre-router handles reviews with a single unambiguous theme keyword hit (e.g. "kyc", "withdraw", "crash") without calling Groq.

#### 3.2.3 Sentiment Scoring
Each review is assigned a **sentiment score** on a normalised scale of −1.0 (strongly negative) to +1.0 (strongly positive):
- **Base score** (deterministic): derived from star rating — 1★ → −1.0, 3★ → 0.0, 5★ → +1.0 (linear interpolation)
- **Text adjustment** (Groq, batched with classification): a small delta in [−0.2, +0.2] returned in the same batch JSON response
- **Final score** = base + adjustment, clamped to [−1.0, +1.0]

This two-component score handles cases like a 4-star review that expresses a sharp complaint about a specific feature, without a separate Groq call per review.

#### 3.2.4 Theme Ranking
Themes are ranked using a weighted formula:

```
Theme Score = Review Count × (1 − Average Sentiment)
```

A high score means many reviews AND predominantly negative sentiment — these are the themes most in need of attention. The top 3 themes by this score are surfaced in the pulse note.

#### 3.2.5 Quote Extraction
For each of the top 3 themes:
- **Deterministic shortlist**: programmatically select up to 8 candidate snippets (negative-leaning, ≥ 12 words, theme-keyword overlap)
- **One Groq call per theme** (3 calls total): Groq picks the best index from the shortlist — it does not write new text
- The selected snippet must be **verbatim text** from the source review — no paraphrasing, no merging of sentences
- Post-selection verification confirms the quote is a substring of the source review

#### 3.2.6 Action Idea Generation
A **single Groq call** receives the top 3 themes, their quotes, review counts, and average sentiment, and generates 3 concrete product action ideas. Each action idea must:
- Reference a specific product area or user flow
- Be actionable by a product or engineering team
- Be grounded in the theme evidence (not generic advice)

---

### Layer 3 — Pulse Note Generator

**Purpose**: Assemble the structured weekly note from the processed signal, enforce all constraints (word count, structure, PII-free), and emit the canonical Markdown artifact.

#### 3.3.1 Note Structure

```
## Groww Weekly Pulse — Week of [DATE]
### Period: [start date] to [end date] | Reviews Analysed: [N]

---

### Top Themes
1. **[Theme Name]** — [review count] reviews, avg. rating [X.X] ⭐
   [One-line summary of the dominant sentiment for this theme]

2. **[Theme Name]** — [review count] reviews, avg. rating [X.X] ⭐
   [One-line summary]

3. **[Theme Name]** — [review count] reviews, avg. rating [X.X] ⭐
   [One-line summary]

---

### User Voices
> "[Verbatim quote 1]" — [Store], [Rating]⭐

> "[Verbatim quote 2]" — [Store], [Rating]⭐

> "[Verbatim quote 3]" — [Store], [Rating]⭐

---

### Action Ideas
1. [Specific, grounded action tied to Theme 1]
2. [Specific, grounded action tied to Theme 2]
3. [Specific, grounded action tied to Theme 3]
```

#### 3.3.2 Constraints Enforced
- **Word count**: The full note must be ≤ 250 words. Counted after generation; if exceeded, the LLM is asked to condense with the current text as context
- **No PII**: The assembled note is scanned with the same PII regex used in processing
- **Verbatim quotes**: Each quote is verified to be a substring of its source review text
- **Section completeness**: All three sections (Top Themes, User Voices, Action Ideas) must be present

---

### Layer 4 — MCP Server Layer

**Purpose**: Provide the agent with tool interfaces to interact with Google Docs and Gmail, without any OAuth client code, token management, or REST construction inside the agent itself.

#### 3.4.1 What MCP Is (in this context)

MCP (Model Context Protocol) is a standard that allows AI agents to call tools exposed by a server process. The server handles all the plumbing (authentication, HTTP, rate limiting) and exposes simple named tools that the agent can invoke by name with structured arguments.

In this system, the MCP server acts as a secure proxy between the agent and Google Workspace APIs. The agent never touches OAuth tokens or raw HTTP — it calls HTTP tool endpoints like `append_to_doc` and `create_email_draft`.

#### 3.4.2 MCP Server: `khyati-mcp-server` (Render)

Hosted at `https://khyati-mcp-server.onrender.com/`. A lightweight FastAPI server ([source](https://github.com/hey2308/khyati-mcp-server)) that exposes MCP-style HTTP tools for Google Docs and Gmail. OAuth credentials are stored and managed on the server — not in the agent.

| Tool | Endpoint | Purpose |
|---|---|---|
| Health check | `GET /` | Verify server is running |
| List tools | `GET /tools` | Discover available tools |
| Append to Doc | `POST /append_to_doc` | Append pulse note to an existing Google Doc |
| Create draft | `POST /create_email_draft` | Create Gmail draft (not sent) |

The agent configures a reusable `google_doc_id` in `config.yaml`. Each weekly run appends the new pulse note to that document.

#### 3.4.3 Google Docs Tool Flow

```
Agent calls: append_to_doc(doc_id, content)
    │
    ▼
MCP Server receives POST /append_to_doc
    │
    ▼
MCP Server authenticates with Google Docs API (server-side OAuth)
    │
    ▼
Google Docs API appends content to the configured document
    │
    ▼
MCP Server returns { status: "success", document_id }
    │
    ▼
Agent constructs doc_url and stores in output_links.json
```

The appended content includes the pulse note header: `Groww Weekly Pulse — Week of [YYYY-MM-DD]`

#### 3.4.4 Gmail Tool Flow

```
Agent calls: create_email_draft(to, subject, body)
    │
    ▼
MCP Server receives POST /create_email_draft
    │
    ▼
MCP Server authenticates with Gmail API (server-side OAuth)
    │
    ▼
Gmail API creates a draft in the user's Drafts folder, returns draft ID
    │
    ▼
MCP Server returns { status: "success", draft_id } to agent
    │
    ▼
Agent stores draft_id in output_links.json
```

The draft is **not sent automatically**. A human must open Gmail and send it. This is intentional — see `decision.md` D-010.

#### 3.4.5 Authentication Architecture

```
Google Cloud Console
  └── OAuth 2.0 Client ID + Client Secret
         └── credentials.json
                └── Stored in MCP server directory (outside agent code)
                       └── MCP server handles token refresh, scope management
                              └── Agent sees only: tool names + results
```

The agent has no knowledge of OAuth scopes, token expiry, or the Google Cloud project. All credential management is the MCP server's responsibility.

---

### Layer 5 — Agent Orchestrator

**Purpose**: The top-level controller that sequences all pipeline steps, manages tool calls, handles errors, and logs execution state.

#### 3.5.1 Orchestration Pattern

The agent uses a **sequential tool-calling loop** driven by an LLM:

```
System Prompt (task + constraints + tool list + output schema)
    │
    ▼
Step 1: Call ingestion tools → receive raw reviews
    │
    ▼
Step 2: Call processing tools → receive processed signal
    │
    ▼
Step 3: Call pulse generation tool → receive Markdown note
    │
    ▼
Step 4: Call MCP Docs tool → receive Google Doc URL
    │
    ▼
Step 5: Call MCP Gmail tool → receive Draft ID
    │
    ▼
Step 6: Emit final summary + write output_links.json
```

Each step only begins after the previous step's output is validated. If any step fails, the agent logs the failure and halts — it does not silently skip steps.

#### 3.5.2 Agent Configuration

All runtime parameters are stored in `config.yaml`, not in agent code:

| Parameter | Purpose | Example Value |
|---|---|---|
| `review_window_weeks` | How many weeks of reviews to fetch | `10` |
| `max_themes` | Maximum number of theme clusters | `5` |
| `pulse_themes_displayed` | How many themes appear in the note | `3` |
| `max_words` | Word limit for the pulse note | `250` |
| `email_alias` | Gmail draft recipient | `team-alias@example.com` |
| `mcp_server_url` | MCP server endpoint | `https://khyati-mcp-server.onrender.com` |
| `google_doc_id` | Target Google Doc ID for weekly append | (user-configured) |
| `llm_provider` | LLM API provider for Phase 2 | `groq` |
| `llm_model` | Groq model for Phase 2 processing | `llama-3.3-70b-versatile` |
| `max_reviews_to_process` | Cap on reviews entering Phase 2 | `1000` |
| `llm_batch_size` | Reviews per Groq classification batch | `20` |
| `llm_text_max_words` | Words of review text sent to Groq (truncated) | `50` |
| `llm_max_rpm` | Request throttle (stay under Groq 30 RPM limit) | `24` |
| `llm_max_tpm` | Token throttle per rolling minute | `10000` |
| `llm_max_tokens_per_run` | Pre-flight token budget halt threshold | `90000` |

#### 3.5.3 Logging
Every step is logged to `data/run_log.json` with:
- Step name
- Start and end timestamps
- Input artifact path
- Output artifact path or value
- Status (success / failure)
- Error message (if failure)

This log is the audit trail for any given weekly run.

#### 3.5.4 Weekly Scheduler (GitHub Actions)

Production runs are triggered automatically **once per week** via GitHub Actions (`.github/workflows/weekly-pulse.yml`):

```
Cron: every Monday 06:00 UTC
        │
        ▼
  run_pipeline.py  (Phase 5 orchestrator)
        │
        ├── ingest → process → generate → publish
        │
        ▼
  Commit data/ artifacts back to repository (on success)
```

| Property | Value |
|---|---|
| Schedule | `0 6 * * 1` (Mondays 06:00 UTC) |
| Manual trigger | `workflow_dispatch` (Run workflow in GitHub UI) |
| Entry point | `run_pipeline.py` |
| Required secret | `GROQ_API_KEY` (repository secret) |
| MCP / Docs config | `config.yaml` (`mcp_server_url`, `google_doc_id`, `email_alias`) |

The scheduler invokes `run_pipeline.py`, which runs the Phase 5 agent orchestrator and verification.

---

## 4. Data Flow & Artifact Map

```
[Public App Store Reviews]  [Public Play Store Reviews]
          │                           │
          └──────────┬────────────────┘
                     ▼
          ┌──────────────────────┐
          │  reviews_raw.json    │  ← deduplicated, PII-free
          └──────────┬───────────┘
                     ▼
          ┌──────────────────────┐
          │ processed_signal.json│  ← themes, quotes, actions
          └──────────┬───────────┘
                     ▼
          ┌──────────────────────┐
          │  weekly_pulse.md     │  ← structured ≤250-word note
          └──────┬───────────────┘
                 │
    ┌────────────┴────────────┐
    ▼                         ▼
[Google Doc]            [Gmail Draft]
    │                         │
    └────────────┬────────────┘
                 ▼
        ┌─────────────────┐
        │ output_links.json│  ← doc URL + draft ID
        └─────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │   run_log.json  │  ← execution trace
        └─────────────────┘
```

---

## 5. System Boundaries & Constraints

### What This System Does NOT Do
- It does **not** scrape reviews from behind store logins or require any app store account credentials
- It does **not** store review data beyond the current run's working files
- It does **not** send emails autonomously — only drafts are created
- It does **not** include any PII in any output artifact
- It does **not** call Google APIs directly — all Workspace interactions go through the MCP layer

### External Dependencies
| Dependency | Type | Required For | Failure Mode |
|---|---|---|---|
| Apple iTunes RSS | Public HTTP | App Store ingestion | Retry 3× then halt with error |
| Play Store API | Public HTTP | Play Store ingestion | Retry 3× then halt with error |
| Groq LLM API (`llama-3.3-70b-versatile`) | Authenticated HTTP | Phase 2 processing (batched classification, quote selection, actions) | Throttle on RPM/TPM; halt if daily token budget exceeded; no fallback model |
| GitHub Actions | CI scheduler | Weekly automated pipeline run | Fails if `GROQ_API_KEY` secret missing or MCP OAuth expired |
| MCP Server (local) | Local process | Google Docs + Gmail | Halt with error if unreachable |
| Google Cloud OAuth | MCP-managed | Docs + Gmail auth | MCP server handles refresh |

---

## 6. Key Design Decisions Summary

> Full rationale for each decision is in `decision.md`.

| Decision | Choice Made | Why |
|---|---|---|
| Google Workspace integration | MCP server (not direct API) | Mandated; removes auth complexity from agent |
| Theme clustering approach | LLM zero-shot (not k-means/LDA) | Small dataset, high quality, no training data needed |
| MCP server selection | Single unified server (google_workspace_mcp) | One OAuth flow covers both Docs + Gmail |
| Review sources | iTunes RSS + Play Store public API | Public, no login, automatable, ToS-compliant |
| Theme definition | Fixed predefined list of 5 | Enables week-over-week trend comparison |
| PII removal timing | At ingestion (earliest possible) | Privacy-by-design; prevents PII entering any artifact |
| Orchestration style | Sequential (not parallel across phases) | Each phase depends on prior; simplifies debugging |
| Pulse note format | Markdown (canonical intermediate) | Human-readable artifact; MCP formats for Docs |
| Email delivery | Draft only (not auto-send) | Human review required; safety control |

---

## 7. Target Folder Structure

```
Milestone3/
├── docs/
│   ├── problemStatement.md
│   ├── architecture.md          ← this file
│   ├── implementation_plan.md
│   ├── decision.md
│   └── eval/
│       ├── phase1_eval.md
│       ├── phase2_eval.md
│       ├── phase3_eval.md
│       ├── phase4_eval.md
│       └── phase5_eval.md
├── data/
│   ├── reviews_raw.json
│   ├── processed_signal.json
│   ├── weekly_pulse.md
│   ├── output_links.json
│   └── run_log.json
├── phase1/
│   ├── app_store.py
│   ├── play_store.py
│   ├── ingest.py
│   └── verify.py
├── phase2/
│   ├── themes.py
│   ├── pii_scrub.py
│   ├── pre_router.py
│   ├── groq_client.py
│   ├── sentiment.py
│   ├── classify.py
│   ├── ranking.py
│   ├── quotes.py
│   ├── actions.py
│   ├── process.py
│   └── verify.py
├── phase3/
│   ├── assembler.py
│   ├── validator.py
│   ├── generate.py
│   └── verify.py
├── phase4/
│   ├── mcp_client.py
│   ├── publish.py
│   └── verify.py
├── phase5/
│   ├── prompt.py
│   ├── config.py
│   ├── tools.py
│   ├── orchestrator.py
│   ├── run_log.py
│   └── verify.py
├── .github/
│   └── workflows/
│       └── weekly-pulse.yml
├── mcp_config.json
├── run_pipeline.py
├── config.yaml
└── requirements.txt
```
