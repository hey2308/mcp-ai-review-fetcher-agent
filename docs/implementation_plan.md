# Implementation Plan — Groww Weekly Pulse AI Agent

## Overview

This document is the phase-wise build plan for the Groww Weekly Pulse AI Agent. The agent takes raw, public mobile-app reviews for Groww from the Apple App Store and Google Play Store, processes them into a structured weekly intelligence note, and delivers that note via Google Docs and Gmail — using MCP (Model Context Protocol) servers for all Google Workspace interactions.

The plan is divided into five sequential phases. Each phase has a clearly defined scope, set of activities, expected inputs and outputs, risks, and a link to its evaluation criteria. **A phase must be fully completed and evaluated before the next phase begins.**

> Evaluation criteria for each phase live in `docs/eval/phase[N]_eval.md`.

---

## Phase Summary

| Phase | Name | Core Deliverable | Depends On | Status |
|---|---|---|---|---|
| 1 | Review Ingestion | Clean, PII-free review dataset | Nothing | ✅ Complete |
| 2 | Theme Clustering & Signal Extraction | Structured signal (themes, quotes, actions) | Phase 1 output | ✅ Implemented |
| 3 | Pulse Note Generation | Weekly pulse note (≤250 words, Markdown) | Phase 2 output | ✅ Implemented |
| 4 | MCP Integration | Google Doc + Gmail draft created | Phase 3 output + MCP server | ✅ Implemented |
| 5 | Agent Orchestration & End-to-End | Single-command pipeline run | All prior phases | ✅ Implemented |

> **Weekly automation:** A GitHub Actions scheduler (`.github/workflows/weekly-pulse.yml`) runs Phases 1–4 every Monday via `run_pipeline.py`. See [Weekly Scheduler](#weekly-scheduler-github-actions) below.

---

## Phase 1 — Review Ingestion

### Objective

Establish a reliable, repeatable process for fetching recent public Groww reviews from both stores, normalising them into a consistent schema, and producing a clean dataset that is completely free of personal information — ready for analysis.

This phase has no LLM involvement. It is entirely about data acquisition, normalisation, and sanitisation.

### Scope

**In scope:**
- Fetching reviews from the Apple App Store via the iTunes RSS feed
- Fetching reviews from the Google Play Store via a public-facing scraper/API
- Applying a time-window filter (last 8–12 weeks, configurable)
- Normalising both data sources into a single unified review schema
- Applying normalization quality filters (minimum 6 words, English-only text, no emojis)
- Removing PII at the structural level (by not mapping PII fields)
- Cross-store deduplication
- Saving the cleaned dataset

**Out of scope:**
- Any semantic analysis, classification, or summarisation of reviews (Phase 2)
- Removing PII embedded in free text (handled in Phase 2 as a secondary scrub)
- Any Google Workspace interactions

### Context & Rationale

Reviews on the App Store and Play Store are publicly accessible to any user who visits the store listing without an account. Fetching them programmatically via official or well-established public endpoints is within the platform's terms of service, provided no login credentials are used and the fetch rate is reasonable.

Groww's App Store listing ID and Play Store package name are publicly visible on the store pages and in the URLs, so no privileged access is needed to identify the correct endpoints.

The 8–12 week window was chosen to provide enough volume for meaningful theme clustering while remaining relevant to the current product state. Reviews older than 12 weeks are likely to reflect product states, features, or issues that have since been resolved.

### Activities

#### A. Identify Data Sources
- Locate Groww's App Store app ID (visible in the App Store URL) and confirm the Play Store package name (`com.nextbillion.groww` or similar)
- Construct the correct iTunes RSS endpoint URL for the App Store reviews feed
- Identify and validate the correct Play Store data source (scraper library or public endpoint)
- Confirm that both endpoints return reviews without requiring authentication

#### B. Define the Target Schema
Before writing any ingestion logic, define and document the exact schema that all reviews must conform to after ingestion:

| Field | Type | Source | Description |
|---|---|---|---|
| `id` | string | Store-specific | Unique review identifier (for dedup) |
| `store` | enum | Derived | `"app_store"` or `"play_store"` |
| `rating` | integer | Review | Star rating, 1–5 |
| `title` | string | Review | Review headline |
| `text` | string | Review | Full review body |
| `date` | ISO 8601 date | Review | Date the review was posted |

All other fields from the raw response are discarded at parse time.

#### C. App Store Ingestion
- Fetch pages from the iTunes RSS endpoint
- The RSS feed returns reviews in reverse-chronological order, paginated (typically up to 500 reviews across 10 pages)
- Parse and map each result to the target schema
- Apply the date-window filter immediately after parsing (discard reviews outside the window)

#### D. Play Store Ingestion
- Fetch reviews using the chosen public Play Store data source
- Apply the same date-window filter
- Map to the same schema as App Store reviews, with `store = "play_store"`

#### E. Cross-Store Deduplication
Some users post identical or near-identical reviews on both platforms. To prevent the same review from influencing theme counts twice:
- Compute a normalisation of each review's `title` and `text` (lowercase, strip punctuation, collapse whitespace)
- Hash the concatenated normalised string
- Discard any record whose hash has already been seen; keep the first occurrence

#### F. Dataset Validation
Before saving, validate:
- Every record conforms to the schema (all required fields present, correct types)
- All dates are within the configured window
- Every review text has at least 6 words
- Review `title` and `text` contain no emojis
- Review `title` and `text` pass English-only filter
- No PII fields (reviewer name, user ID, device) are present
- No duplicate hashes remain

#### G. Save Output
Save the validated, deduplicated dataset as a structured JSON file: `data/reviews_raw.json`

Include a brief ingestion summary (total records per store, date range covered, dedup count) in the console output and in the run log.

### Inputs
- Public Apple App Store iTunes RSS endpoint for Groww
- Public Google Play Store review data source for Groww
- `config.yaml` — time window configuration

### Outputs
- `data/reviews_raw.json` — the clean, deduplicated, PII-free review dataset
- Console/log summary of ingestion results

### Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| App Store RSS returns fewer than 100 reviews in the window | Medium | Widen window up to 12 weeks if needed; log a warning if count is still low |
| Play Store scraper blocked or rate-limited | Low–Medium | Add delay between requests; retry with exponential backoff |
| Date parsing inconsistencies between stores | Medium | Normalise all dates to ISO 8601 immediately at parse; log any unparseable dates |
| Reviews in non-English languages dominate the sample | Low | Note this in the run log; Phase 2 LLM can handle multilingual input |

### Exit Criteria
> Full criteria in `docs/eval/phase1_eval.md`

- ≥ 100 reviews in the output dataset (combined across both stores)
- All records within the configured date window
- Zero PII fields present in any record
- No duplicate records

---

## Phase 2 — Theme Clustering & Signal Extraction

### Objective

Transform the flat review dataset from Phase 1 into structured, actionable signal by: scrubbing any embedded PII from review text, classifying every review into one of five predefined themes, scoring themes by volume and sentiment, extracting the most representative verbatim quotes, and generating three concrete action ideas for the product team.

This phase is the analytical core of the pipeline. All Phase 2 LLM reasoning happens here via **Groq** (`llama-3.3-70b-versatile`), using a hybrid design that minimises API calls and stays within rate limits.

### Scope

**In scope:**
- Capping input to the most recent **1,000 reviews** from `reviews_raw.json`
- Regex-based PII scrub on free-text fields (no per-review LLM scrub)
- Deterministic keyword pre-routing for high-confidence theme assignment
- Batched Groq theme classification + sentiment adjustment (combined in one JSON response per batch)
- Sentiment scoring per review and aggregation per theme
- Theme ranking by a volume × sentiment formula
- Verbatim quote selection (one per top theme) via deterministic shortlist + 3 Groq pick calls
- Action idea generation via a single Groq call grounded in top themes
- Request/token throttling and pre-flight budget checks against Groq limits

**Out of scope:**
- Generating the final pulse note (Phase 3)
- Any Google Workspace interactions (Phase 4)
- Processing more than 1,000 reviews per run (deferred until limits are upgraded)

### Context & Rationale

#### Groq Rate Limits & Call Budget

The chosen Groq model (`llama-3.3-70b-versatile`) has the following limits:

| Limit | Value |
|---|---|
| Requests per minute | 30 |
| Requests per day | 1,000 |
| Tokens per minute | 12,000 |
| Tokens per day | 100,000 |

A naive per-review approach (PII scrub + classify + sentiment = 3 calls × 1,000 reviews) would require **3,000 requests** and far exceed the daily token cap. Phase 2 is therefore designed as a **hybrid pipeline** that keeps a full run to approximately **32 Groq requests** and **~94,000 tokens**.

#### Why Hybrid (Deterministic + Batched Groq)?
The review dataset is capped at 1,000 records per run. Traditional unsupervised approaches (k-means, LDA) still require post-hoc labelling. Zero-shot Groq classification against a predefined theme list produces directly usable output — but only if calls are batched and pre-routing reduces the volume sent to the API. Profiling of the current `reviews_raw.json` (441 records) shows:
- Rating spread is usable for sentiment (37% 1★, 41% 5★)
- Keyword pre-routing can assign ~35–45% of reviews without Groq
- Median review length is 19 words — truncation to 50 words for Groq payloads preserves classification signal while saving tokens
- Top recurring terms (`trading`, `update`, `charges`, `customer support`, `option trading`) align well with the fixed theme taxonomy

#### Why Fixed Themes?
Five predefined themes (rather than discovering themes dynamically each run) provide week-over-week comparability. If the themes were dynamic, a "KYC issues" spike in week 3 and week 7 might be assigned different labels, making trend tracking impossible. Fixed themes allow product teams to track whether a theme is improving or worsening over time.

The five themes for Groww are:
| Theme | Product Surface |
|---|---|
| Onboarding & Account Setup | Registration, first login, app navigation |
| KYC & Verification | Document upload, video KYC, verification status |
| Payments & Transactions | Fund transfers, SIP, orders, UPI, payment failures |
| Portfolio & Statements | Holdings display, P&L, statements, tax documents |
| Performance & App Stability | Crashes, slow load, UI bugs, login failures |

### Activities

#### A. Input Cap & Preparation
Before any Groq calls:
- Load `data/reviews_raw.json`
- If record count exceeds `max_reviews_to_process` (1,000), keep only the **most recent** reviews by `date`
- Log the cap applied (original count → capped count) in the run log

#### B. Regex PII Scrub (No Groq)
Phase 1 removed PII fields structurally. Phase 2 applies a **regex-only scrub** to catch embedded PII in free text:
- Scan `title` and `text` for email addresses, phone numbers, and account-number patterns
- Replace matches with `[REDACTED]` — no Groq call required
- Flag any record where PII patterns are detected for manual review in the run log

#### C. Keyword Pre-Router (No Groq)
Before calling Groq, assign themes deterministically where confidence is high:
- Each review is checked against a keyword map per theme (e.g. `kyc` → KYC & Verification, `withdraw`/`upi` → Payments, `crash`/`hang` → Performance)
- If exactly one theme matches, assign directly — no Groq call
- If zero or multiple themes match, queue the review for Groq batch classification
- Expected pre-route rate: ~35–45% based on current dataset profiling

#### D. Batched Groq Classification + Sentiment
Remaining reviews are sent to Groq in batches of `llm_batch_size` (default: 20):
- Each review payload includes: `id`, `rating`, truncated `title` + `text` (first `llm_text_max_words` = 50 words)
- One Groq call per batch returns structured JSON for all reviews in the batch:
  ```json
  [{ "review_id": "...", "theme": "...", "sentiment_adjustment": 0.0 }]
  ```
- Base sentiment is computed deterministically from rating; `sentiment_adjustment` (−0.2 to +0.2) comes from Groq
- Final sentiment = base + adjustment, clamped to [−1.0, +1.0]
- Retry once on malformed JSON; on second failure, halt the run

**Throttle rules** (enforced between every Groq call):
- Minimum **2.5 s** between requests (≤ 24 RPM, under the 30 RPM limit)
- Pause if rolling 60 s token usage exceeds **10,000 TPM** (under the 12K limit)
- Pre-flight check: estimated total tokens must be ≤ **90,000** before starting; halt if exceeded

#### E. Theme Aggregation & Ranking
For each of the five themes:
- Count total reviews assigned to this theme
- Compute average sentiment score across all reviews in the theme
- Compute the **theme priority score**: `count × (1 − average_sentiment)` — higher score = more reviews + more negative sentiment = higher priority

Themes are sorted by priority score descending. The top 3 themes are designated as the "featured themes" for the pulse note.

#### F. Quote Extraction (Deterministic Shortlist + 3 Groq Calls)
For each of the top 3 themes:
- **Deterministic shortlist**: programmatically select up to 8 candidate snippets from classified reviews (negative-leaning, ≥ 12 words, theme-keyword overlap)
- **One Groq call per theme**: Groq receives the shortlist and returns the index of the best quote — it does not write new text
- The selected snippet must be a literal substring of the source review's `text` or `title` field
- Post-selection verification confirms verbatim match against the full (untruncated) source text

#### G. Action Idea Generation (1 Groq Call)
A single Groq call receives the top 3 themes (names, counts, sentiment, quotes) and generates 3 product action ideas:
- Each action must be specific to a Groww product surface or user flow
- Each action must be grounded in the review evidence (trace back to a theme and quote)
- Actions are written in the style of a product recommendation, not a generic observation

### Groq Call Budget Per Run

| Step | Groq calls | Est. tokens | Notes |
|---|---|---|---|
| Keyword pre-router | 0 | 0 | Handles ~35–45% of reviews |
| Regex PII scrub | 0 | 0 | No LLM |
| Classify + sentiment (batched) | ~28 | ~84,000 | 20 reviews/batch, ~550 reviews after pre-route |
| Quote selection | 3 | ~6,000 | 1 call per featured theme |
| Action ideas | 1 | ~4,000 | Single summary call |
| **Total** | **~32** | **~94,000** | Under 1K RPD and 100K TPD limits |

### Inputs
- `data/reviews_raw.json` (from Phase 1; capped at 1,000 most recent records)
- Groq API access (`GROQ_API_KEY` environment variable)
- `config.yaml` — theme definitions, Groq model, batch size, throttle limits, review cap

### Outputs
- `data/processed_signal.json` — structured object containing:
  - Week identifier
  - All 5 themes with: review count, average sentiment, priority score, and top quote
  - Top 3 themes (by priority score) flagged
  - 3 action ideas

### Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Groq daily token limit exceeded | Medium | Pre-flight token estimate; cap at 1,000 reviews; truncate text to 50 words; batch + pre-route to ~32 calls |
| Groq RPM/TPM throttling mid-run | Medium | Enforce 2.5 s inter-request delay; pause on rolling TPM > 10K; log throttle events |
| LLM misclassifies reviews into wrong themes | Medium | Keyword pre-router for clear cases; spot-check 20 reviews manually during evaluation |
| One theme receives 0 reviews (no signal) | Low | Acceptable; that theme simply ranks last. Surface it as "no issues reported" |
| Action ideas are too vague or generic | Medium | Evaluation check M2.2 explicitly rejects vague actions; re-prompt if needed |
| LLM fails to return structured JSON | Low | JSON schema in prompt; retry once per batch; halt on second failure |
| Keyword pre-router assigns wrong theme | Low | Only single-hit reviews are pre-routed; ambiguous/multi-hit reviews go to Groq |

### Exit Criteria
> Full criteria in `docs/eval/phase2_eval.md`

- All reviews classified; zero `"Other"` labels in final output
- ≤ 5 distinct theme labels used
- 3 verbatim quotes extracted, each confirmed as a substring of source text
- 3 action ideas generated, each specific to a product area

### How to Run

```bash
# Install dependencies (once)
pip install -r requirements.txt

# Set Groq API key in .env (recommended)
copy .env.example .env          # Windows (once)
# cp .env.example .env          # Linux/macOS (once)
# Then edit .env and set: GROQ_API_KEY=your_key_here

# Run Phase 2 (Groq-backed)
python -m phase2.process

# Verify output
python -m phase2.verify

# Offline test mode (no Groq calls; keyword fallback only)
python -m phase2.process --offline
```

---

## Phase 3 — Pulse Note Generation

### Objective

Assemble the processed signal from Phase 2 into a polished, scannable, stakeholder-ready weekly pulse note that meets all formatting, length, and content constraints. The note is the canonical human-readable output of the pipeline — it is what appears in the Google Doc and in the Gmail email body.

### Scope

**In scope:**
- Assembling the structured note from `processed_signal.json`
- Enforcing the ≤ 250-word constraint
- Validating all three required sections are present
- Confirming quotes are verbatim
- Performing a final PII scan
- Saving the canonical pulse note

**Out of scope:**
- Sending the note anywhere (Phase 4)

### Context & Rationale

The pulse note is the primary deliverable for the end audience — product managers, team leads, and leadership. Its design priorities are:
- **Scannability**: Should be digestible in under 2 minutes
- **Actionability**: Every section is oriented toward a decision or action, not just information
- **Credibility**: Real user quotes (verbatim, attributed to store and rating) ground the analysis in reality
- **Portability**: Markdown as the source format means it renders correctly in Google Docs, email, Slack, and any note-taking tool

The 250-word limit is not arbitrary — it is what fits on one screen without scrolling, which is the threshold for "pulse" rather than "report."

### Activities

#### A. Assemble the Note Draft
Using the structured data in `processed_signal.json`, the LLM (or a template-driven assembler) constructs the note following the defined structure:
- Header with week identifier and review count
- Top 3 Themes section: each theme name, review count, average rating, one-line sentiment summary
- User Voices section: three verbatim quote blocks, each attributed (store, rating)
- Action Ideas section: three numbered recommendations

The note is assembled in Markdown. The LLM is given the processed signal as structured input and the note template as a formatting guide. It is instructed to use the pre-selected quotes verbatim, not to generate new quotes.

#### B. Word Count Enforcement
After generation, the note is word-counted. If it exceeds 250 words:
- The note is returned to the LLM with the instruction to condense it while preserving all three sections, all three quotes, and all three actions
- Up to two condensation attempts are made. If still over 250 words after two attempts, the longest section is truncated programmatically
- The final word count is logged

#### C. Structural Validation
The note is parsed to verify:
- All three sections are present (Top Themes, User Voices, Action Ideas)
- Exactly 3 themes are listed
- Exactly 3 quotes are present (in blockquote format)
- Exactly 3 action items are present

#### D. Quote Verbatim Check
Each quote in the assembled note is checked against `processed_signal.json` to confirm it is identical to the quote extracted in Phase 2 (which was itself verified as a verbatim substring of the source review). This prevents any generation drift where the LLM might paraphrase a quote during note assembly.

#### E. Final PII Scan
The complete note text is scanned with a PII detection regex suite covering: email addresses, phone numbers, common name patterns, and financial account number formats. Any match causes the note generation to fail — the pipeline halts and logs the PII location for manual review.

#### F. Save Output
Save the validated note as `data/weekly_pulse.md`. This file is the input to Phase 4.

### Inputs
- `data/processed_signal.json` (from Phase 2)
- LLM API (for assembly and condensation)
- Note structure template (from `config.yaml` or a template file)

### Outputs
- `data/weekly_pulse.md` — the validated, constraint-compliant pulse note

### Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Note exceeds 250 words after two condensation attempts | Low | Programmatic truncation of longest section as fallback |
| LLM paraphrases a verbatim quote during assembly | Medium | Explicit instruction in prompt + post-generation quote check |
| Note structure is malformed (missing section) | Low | Structural validation catches this; re-generation attempted once |
| PII detected in assembled note | Very Low | Pipeline halts; source review flagged for manual review |

### Exit Criteria
> Full criteria in `docs/eval/phase3_eval.md`

- Note is ≤ 250 words
- All 3 sections present with correct counts (3 themes, 3 quotes, 3 actions)
- All quotes confirmed verbatim (substring match against processed signal)
- No PII detected in note text

### How to Run

```bash
# Run Phase 3 (template assembly from processed_signal.json)
python -m phase3.generate

# Verify output
python -m phase3.verify
```

---

## Phase 4 — MCP Integration (Google Docs + Gmail)

### Objective

Deliver the pulse note to both Google Workspace surfaces — a Google Doc (for sharing and archiving) and a Gmail draft (for team distribution) — using the MCP server layer exclusively. No Google API calls are to appear in the agent's logic.

### Scope

**In scope:**
- Setting up and verifying the MCP server ([khyati-mcp-server](https://github.com/hey2308/khyati-mcp-server) on Render)
- Appending the pulse note to a configured Google Doc via MCP `append_to_doc`
- Creating the Gmail draft via MCP `create_email_draft`
- Recording output links

**Out of scope:**
- Running or triggering MCP server setup automatically (this is a one-time manual setup)
- Sending the email (draft only)
- Any processing or note changes (Phase 3)

### Context & Rationale

#### Why Not Call Google APIs Directly?
Direct Google API integration requires the agent to manage OAuth 2.0 credentials, handle token refresh, construct authenticated HTTP requests, and parse raw API responses. This is significant plumbing that the problem statement explicitly forbids — and that MCP servers are designed to abstract away.

With an MCP server in place, the agent's interaction with Google Workspace is reduced to named tool calls with structured arguments. The server handles the entire authentication lifecycle. This is cleaner, more maintainable, and aligned with the project's course tooling patterns.

#### MCP Server: `khyati-mcp-server` (Render)

Hosted at `https://khyati-mcp-server.onrender.com/`. This server exposes HTTP tool endpoints (MCP-style) for Google Docs and Gmail. OAuth credentials are managed on the server — the agent never calls Google APIs directly.

| Endpoint | Method | Payload | Purpose |
|---|---|---|---|
| `/` | GET | — | Health check |
| `/tools` | GET | — | List available tools |
| `/append_to_doc` | POST | `{ doc_id, content }` | Append pulse note to an existing Google Doc |
| `/create_email_draft` | POST | `{ to, subject, body }` | Create Gmail draft (not sent) |

> **Note:** This MCP server appends to an existing Google Doc (configured via `google_doc_id` in `config.yaml`), rather than creating a new document. Create a blank Google Doc once, copy its ID from the URL, and reuse it for weekly runs.

#### B. Pre-Run Health Check
At the start of each pipeline run, before calling any Docs or Gmail tools:
- The agent calls `GET /` and `GET /tools` to verify the MCP server is running
- If this check fails, the pipeline halts immediately with a clear error message

#### C. Google Doc Update via MCP
Once the health check passes and the pulse note is available:
- The agent calls `POST /append_to_doc` with:
  - `doc_id`: from `google_doc_id` in `config.yaml`
  - `content`: the full text of `weekly_pulse.md` (with week header)
- The agent constructs `doc_url` as `https://docs.google.com/document/d/{doc_id}/edit`
- The agent stores `doc_id` and `doc_url` in `data/output_links.json`

#### D. Gmail Draft Creation via MCP
- The agent calls `POST /create_email_draft` with:
  - `to`: the email alias from `config.yaml`
  - `subject`: `[Groww Weekly Pulse] Week of [YYYY-MM-DD]`
  - `body`: the pulse note text followed by a link to the Google Doc
- The MCP server creates the draft in Gmail Drafts and returns a `draft_id`
- The draft is **not sent** — it remains in Drafts for human review

#### E. Output Logging
After both MCP tool calls succeed:
- `data/output_links.json` is written with:
  - `doc_id` and `doc_url` for the Google Doc
  - `draft_id` for the Gmail draft
  - `created_at` timestamp
  - `week` identifier

### Inputs
- `data/weekly_pulse.md` (from Phase 3)
- Running MCP server (local)
- `config.yaml` — email alias, MCP server URL
- Google Cloud OAuth credentials (managed by MCP server, not by agent)

### Outputs
- Google Doc in the user's Drive, titled and populated with the pulse note
- Gmail draft in the user's Drafts folder
- `data/output_links.json` — document URL and draft ID

### Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| MCP server not running when pipeline starts | Medium | Pre-run health check (Activity B) catches this immediately |
| OAuth token expired / revoked | Low | MCP server handles automatic token refresh; if revoked, re-run OAuth consent flow |
| Google Doc created but content is malformed | Low | Post-creation verification via MCP `get_document` tool |
| Gmail draft not appearing in Drafts | Low | Verify draft ID is valid after creation; log any MCP error responses |
| Google Cloud API quotas exceeded | Very Low | Default quotas are generous for one weekly run; log any 429 responses from MCP server |

### Exit Criteria
> Full criteria in `docs/eval/phase4_eval.md`

- MCP pre-run health check passes
- Google Doc created with correct title and content matching `weekly_pulse.md`
- Gmail draft created and visible in Drafts folder
- `output_links.json` contains valid `doc_url` and `draft_id`
- Zero direct Google API client calls in the agent code path

### How to Run

```bash
# 1. Create a Google Doc and copy its ID from the URL into config.yaml:
#    google_doc_id: "YOUR_DOC_ID"

# 2. Publish pulse note via MCP server
python -m phase4.publish

# 3. Verify output
python -m phase4.verify
```

---

## Weekly Scheduler (GitHub Actions)

### Objective

Automate the weekly Groww Pulse pipeline so fresh reviews are fetched, analysed, and published without manual intervention.

### Schedule

| Trigger | When |
|---|---|
| **Cron** | Every **Monday at 06:00 UTC** (`0 6 * * 1`) |
| **Manual** | `workflow_dispatch` — run anytime from GitHub Actions tab |

### What Each Run Does

1. **Phase 1** — Fetch latest public reviews → `data/reviews_raw.json`
2. **Phase 2** — Groq theme classification + signal → `data/processed_signal.json`
3. **Phase 3** — Assemble pulse note → `data/weekly_pulse.md`
4. **Phase 4** — Append to Google Doc + create Gmail draft via MCP → `data/output_links.json`
5. **Commit** — Push updated `data/` artifacts back to the repository (on success)

Entry point: `run_pipeline.py` (runs all phases + verifiers sequentially).

### GitHub Repository Setup

Add this **repository secret** in GitHub → Settings → Secrets and variables → Actions:

| Secret | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | Phase 2 Groq API access |

Ensure `config.yaml` contains valid values for:

- `google_doc_id` — target Google Doc for weekly append
- `mcp_server_url` — `https://khyati-mcp-server.onrender.com`
- `email_alias` — Gmail draft recipient

The MCP server's Google OAuth token must remain valid (re-auth on server if `invalid_grant` errors occur).

> Full Render deployment guide: [deployment_plan.md](deployment_plan.md)

### Workflow File

`.github/workflows/weekly-pulse.yml`

### How to Run Manually

**Locally:**
```bash
python run_pipeline.py
```

**GitHub:** Actions → Weekly Groww Pulse → Run workflow

---

## Phase 5 — Agent Orchestration & End-to-End Integration

### Objective

Wire all four prior phases into a single, coherent agent pipeline that runs from start to finish with a single trigger, produces all expected outputs, handles errors gracefully, and provides a clear execution log.

### Scope

**In scope:**
- Defining the full agent system prompt and tool registry
- Sequential orchestration of Phases 1–4 as tool calls
- Configuration-driven behaviour (all parameters from `config.yaml`)
- Structured execution logging
- Error handling and graceful failure modes
- Documentation of how to run the pipeline

**Out of scope:**
- Scheduling or automation of recurring runs (handled by [Weekly Scheduler](#weekly-scheduler-github-actions))
- A user interface or dashboard

### Context & Rationale

The five phases were built independently, each with its own well-defined inputs and outputs. Phase 5 is about connecting them into a reliable, observable system that behaves the same way every time it is triggered and makes its state transparent through logs.

The agent orchestrator is an LLM with a system prompt that describes the full task, the constraints (PII, word limit, theme cap), and the list of tools available to it. The LLM drives the sequence of tool calls, making it easy to add or reorder steps in future without restructuring hardcoded logic.

### Activities

#### A. Define the Agent System Prompt
The system prompt is the single document that tells the LLM what it is trying to achieve and how. It must encode:

- **Goal**: "You are a weekly review analysis agent for Groww. Your job is to fetch reviews, analyse them, generate a pulse note, and publish it to Google Docs and Gmail using the tools available to you."
- **Constraints**: No PII in any output. Maximum 5 themes. Top 3 themes in the pulse note. Note must be ≤ 250 words. Gmail creates a draft only — do not send.
- **Tool list**: Names and descriptions of all available tools (ingestion, processing, note generation, MCP Docs, MCP Gmail)
- **Output schema**: What the final state should look like (`output_links.json` contents)
- **Step sequence**: The expected order of tool calls (the LLM follows this unless a tool returns an error)

#### B. Define the Tool Registry
All agent capabilities are registered as named tools with clear input/output contracts:

| Tool Name | What It Does | Input | Output |
|---|---|---|---|
| `fetch_app_store_reviews` | Fetches reviews from iTunes RSS | week window | raw reviews |
| `fetch_play_store_reviews` | Fetches reviews from Play Store | week window | raw reviews |
| `merge_and_deduplicate` | Combines + deduplicates both review sets | two review lists | unified list |
| `scrub_and_validate` | Removes PII, validates schema | review list | clean review list |
| `classify_themes` | LLM zero-shot classification | clean reviews, theme list | classified reviews |
| `score_and_rank_themes` | Aggregates sentiment, ranks themes | classified reviews | ranked theme data |
| `extract_quotes` | Selects verbatim quotes per theme | ranked theme data, reviews | quotes |
| `generate_actions` | LLM-generates action ideas | top themes + quotes | action ideas |
| `assemble_pulse_note` | Builds the Markdown note | processed signal | pulse note text |
| `validate_note` | Checks constraints, PII, structure | pulse note text | validation result |
| `create_google_doc` | MCP: creates Doc with note | note text, title | doc URL |
| `create_gmail_draft` | MCP: creates draft with note | note text, doc URL, recipient | draft ID |
| `write_output_links` | Saves output_links.json | doc URL, draft ID | file path |

#### C. Orchestration Logic
The agent calls tools in the defined sequence. After each tool call:
- If the tool returns a success response, the agent proceeds to the next step
- If the tool returns an error, the agent logs the error, halts, and outputs a clear failure message identifying which step failed and what the error was
- The agent does not retry automatically (retries are handled within individual tools where appropriate)

The sequence is:
```
fetch_app_store_reviews
fetch_play_store_reviews
    → merge_and_deduplicate
    → scrub_and_validate
    → classify_themes
    → score_and_rank_themes
    → extract_quotes
    → generate_actions
    → assemble_pulse_note
    → validate_note
    → create_google_doc
    → create_gmail_draft
    → write_output_links
```

#### D. Configuration Management
All pipeline parameters are read from `config.yaml` at startup. The agent never uses hardcoded values. Parameters include:

| Parameter | Purpose |
|---|---|
| `review_window_weeks` | Number of weeks of reviews to fetch |
| `max_themes` | Maximum theme count for clustering |
| `pulse_themes_displayed` | Themes surfaced in the note |
| `max_words` | Word cap for the pulse note |
| `email_alias` | Gmail draft recipient |
| `mcp_server_url` | MCP server endpoint |
| `llm_provider` | LLM API provider for Phase 2 (`groq`) |
| `llm_model` | Groq model for Phase 2 (`llama-3.3-70b-versatile`) |
| `max_reviews_to_process` | Cap on reviews entering Phase 2 (1,000) |
| `llm_batch_size` | Reviews per Groq classification batch (20) |
| `llm_text_max_words` | Truncation limit for text sent to Groq (50) |
| `llm_max_rpm` | Request throttle per minute (24) |
| `llm_max_tpm` | Token throttle per rolling minute (10,000) |
| `llm_max_tokens_per_run` | Pre-flight token budget halt threshold (90,000) |

#### E. Execution Logging
A structured run log (`data/run_log.json`) is written progressively throughout the run:

```json
{
  "run_id": "...",
  "started_at": "...",
  "config": { ... },
  "steps": [
    {
      "step": "fetch_app_store_reviews",
      "started_at": "...",
      "completed_at": "...",
      "status": "success",
      "output_summary": "142 reviews fetched"
    },
    ...
  ],
  "completed_at": "...",
  "final_status": "success",
  "outputs": {
    "doc_url": "...",
    "draft_id": "..."
  }
}
```

#### F. End-to-End Testing
Before the pipeline is considered complete:
1. **Dry run**: Run the pipeline with a small, known dataset (e.g., 20 manually curated reviews) to validate the pipeline produces the correct outputs without LLM costs for a full dataset
2. **Full run**: Run the pipeline with real, live reviews for the current week
3. **Verification**: After the full run, manually verify the Google Doc and Gmail Draft are correct
4. **Re-run test**: Run the pipeline again the following day to confirm it produces a different (updated) note reflecting the current week's data

#### G. Documentation
Write a `README.md` at the project root describing:
- Prerequisites (MCP server setup, LLM API key, Google Cloud credentials)
- How to configure `config.yaml`
- How to run the pipeline (single command)
- Where to find outputs (`data/` directory, Google Drive, Gmail Drafts)
- Troubleshooting common errors

### Inputs
- All outputs from Phases 1–4 (as produced within the same run)
- `config.yaml`
- Running MCP server
- LLM API access

### Outputs
- End-to-end pipeline execution producing: `reviews_raw.json`, `processed_signal.json`, `weekly_pulse.md`, Google Doc, Gmail Draft, `output_links.json`, `run_log.json`

### Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM agent calls tools in wrong order | Low | Sequential system prompt is explicit about order; validated in dry run |
| Pipeline partially completes and leaves inconsistent state | Medium | Run log records each step's status; partial runs are identifiable and re-runnable from the last successful step |
| Configuration error (wrong email alias, wrong window) | Medium | Configuration is validated at startup before any tools are called |
| MCP server goes offline mid-run | Low | Pre-run health check; Phase 4 tools handle MCP errors and halt gracefully |

### Exit Criteria
> Full criteria in `docs/eval/phase5_eval.md`

- Pipeline runs end-to-end with a single command with no manual intervention
- All Phase 1–4 exit criteria are satisfied within one run
- `run_log.json` contains entries for all steps with `"status": "success"`
- Google Doc and Gmail Draft verified after the run
- README provides sufficient instructions for a new developer to run the pipeline independently

### Implementation Notes

| Component | Location |
|---|---|
| System prompt + tool registry | `phase5/prompt.py` |
| Config validation | `phase5/config.py` |
| Tool implementations | `phase5/tools.py` |
| Sequential orchestrator | `phase5/orchestrator.py` |
| Execution logging | `phase5/run_log.py` |
| End-to-end verification | `phase5/verify.py` |
| Single-command entry point | `run_pipeline.py` |
| Developer documentation | `README.md` |

Run with: `python run_pipeline.py` (full) or `python run_pipeline.py --dry-run` (offline test).

---

## Cross-Phase Dependencies

```
Phase 1 ──► reviews_raw.json
                  │
                  ▼
            Phase 2 ──► processed_signal.json
                              │
                              ▼
                        Phase 3 ──► weekly_pulse.md
                                          │
                                          ▼
                                    Phase 4 ──► Google Doc + Gmail Draft
                                                        │
                                                        ▼
                                                  Phase 5 (wires all above
                                                  into single agent loop)
```

Each arrow represents a hard dependency. A phase cannot begin until the previous phase's output artifact exists and has passed its evaluation criteria.

---

## Target Folder Structure

```
Milestone3/
├── docs/
│   ├── problemStatement.md
│   ├── architecture.md
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
