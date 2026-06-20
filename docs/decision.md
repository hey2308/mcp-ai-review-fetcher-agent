# Decision Log — Groww Weekly Pulse AI Agent

## Purpose

This file records significant technical and business decisions made during the design and implementation of this project. Each entry captures the context, options considered, the decision taken, and the rationale. This creates an audit trail and helps future contributors understand *why* things are the way they are.

---

## Decision Index

| ID | Title | Category | Status |
|---|---|---|---|
| D-001 | MCP-first for Google Workspace integrations | Architecture | ✅ Decided |
| D-002 | LLM-based theme clustering over traditional ML | Processing | ✅ Decided |
| D-003 | Single MCP server for both Docs and Gmail | Integration | ✅ Decided |
| D-004 | iTunes RSS + google-play-scraper for ingestion | Data | ✅ Decided |
| D-005 | Zero-shot classification with predefined theme list | Processing | ✅ Decided |
| D-006 | Drop PII at ingestion, not at generation | Privacy | ✅ Decided |
| D-007 | Sequential agent orchestration (not parallel) | Architecture | ✅ Decided |
| D-008 | Markdown as the canonical pulse note format | Output | ✅ Decided |
| D-009 | 5 fixed themes rather than dynamic theme discovery | Business | ✅ Decided |
| D-010 | Email sends as a draft, not auto-sent | Business | ✅ Decided |

---

## D-001 — MCP-first for Google Workspace integrations

**Category**: Architecture  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
The milestone requires delivering the pulse note to Google Docs and via Gmail. The standard approach would be to use Google's client libraries (`google-auth`, `googleapiclient`) directly in the agent. However, the problem statement explicitly mandates MCP-first integration.

### Options Considered
| Option | Description | Pros | Cons |
|---|---|---|---|
| A | Direct Google API (REST + OAuth) | Familiar, full control | Auth plumbing in agent code, credential management complexity |
| B | MCP server for Google Workspace | Clean separation, no auth code in agent | Requires MCP server setup, additional moving part |
| C | Third-party service (Zapier, Make.com) | Easy to set up | Not MCP, external dependency, cost |

### Decision
**Option B — MCP server.**

### Rationale
- Mandated by the problem statement ("MCP-first, not call Google APIs manually")
- Keeps authentication concerns outside agent logic — the MCP server owns credentials
- Consistent with the course's intended tooling pattern
- Scales: adding more Workspace tools (Sheets, Calendar) requires no auth changes in agent code

---

## D-002 — LLM-based theme clustering over traditional ML

**Category**: Processing  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
Reviews need to be grouped into ≤ 5 themes. Options include traditional NLP (TF-IDF + k-means), topic modelling (LDA), or LLM-based zero-shot classification.

### Options Considered
| Option | Description | Pros | Cons |
|---|---|---|---|
| A | TF-IDF + k-means | No API cost, fast | Unsupervised — theme labels need post-hoc naming, lower quality |
| B | LDA topic modelling | Principled topic discovery | Complex tuning, opaque output |
| C | LLM zero-shot classification | High quality, interpretable labels, no training data needed | API cost, latency |

### Decision
**Option C — LLM zero-shot classification.**

### Rationale
- Dataset size is small (~100–500 reviews) — LLM cost is negligible
- Zero-shot with predefined theme names produces directly usable, labelled output
- No training data or manual labelling required
- Output is interpretable and auditable in a single prompt call

---

## D-003 — Single MCP server for both Docs and Gmail

**Category**: Integration  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
We need MCP tools for both Google Docs and Gmail. Options include running separate specialised servers or a single unified workspace server.

### Options Considered
| Option | Description |
|---|---|
| A | `a-bonus/google-docs-mcp` + `GongRzhe/Gmail-MCP-Server` (two servers) |
| B | `taylorwilsdon/google_workspace_mcp` (single server, covers both) |

### Decision
**Option B — single unified MCP server (`taylorwilsdon/google_workspace_mcp`).**

### Rationale
- One OAuth consent flow for both services — simpler setup
- Single server process to manage and monitor
- Community-maintained, feature-complete for both Docs and Gmail
- Reduces configuration surface area in `mcp_config.json`

### Risk
- Single point of failure for both integrations; mitigated by Phase 4 health-check test (eval check 4.1)

---

## D-004 — iTunes RSS + google-play-scraper for ingestion

**Category**: Data  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
We need to pull public reviews without scraping behind store logins or violating ToS.

### Options Considered
| Option | Source | Login Required? | ToS Risk? |
|---|---|---|---|
| A | iTunes RSS feed | No | No — public, documented |
| B | `google-play-scraper` npm/Python | No | Low — public listing page |
| C | Third-party review aggregators | No | Medium — depends on service ToS |
| D | Manual CSV export | No | No | High effort, not automatable |

### Decision
**Option A + B — iTunes RSS for App Store, `google-play-scraper` for Play Store.**

### Rationale
- Both are public, no authentication required
- Complies with problem statement constraint ("public review exports only")
- Automatable and programmatic — no manual steps
- iTunes RSS is an official Apple-documented endpoint

### Constraint
iTunes RSS returns only the most recent ~500 reviews — sufficient for the 8–12 week window for an app of Groww's review volume.

---

## D-005 — Zero-shot classification with predefined theme list

**Category**: Processing  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
How should themes be defined — discovered dynamically from the data or fixed upfront?

### Options Considered
| Option | Description | Pros | Cons |
|---|---|---|---|
| A | Dynamic discovery (LLM suggests themes from data) | Adaptive, no prior knowledge needed | Non-deterministic, themes change week-to-week (hard to track trends) |
| B | Fixed predefined theme list | Stable, comparable across weeks | Needs upfront domain knowledge of Groww |

### Decision
**Option B — fixed predefined themes.**

### Themes Chosen for Groww
1. Onboarding & Account Setup
2. KYC & Verification
3. Payments & Transactions
4. Portfolio & Statements
5. Performance & App Stability

### Rationale
- Enables week-over-week trend comparison (same theme labels across runs)
- Themes derived from domain knowledge of Groww's core product surfaces
- Reviewable and adjustable by product stakeholders without touching code (can move to `config.yaml`)

---

## D-006 — Drop PII at ingestion, not at generation

**Category**: Privacy  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
PII could be removed at multiple stages: at ingestion (before saving), at processing, or at generation time (before writing to Docs/Gmail).

### Decision
**Remove PII as early as possible — at the ingestion layer — with a secondary LLM scrub pass at processing.**

### Rationale
- Privacy-by-design: minimise how long PII exists in any intermediate artifact
- Reduces risk of PII leaking into `reviews_raw.json`, logs, or downstream processing
- LLM scrub pass catches embedded PII in free-text fields that structural field removal misses
- Belt-and-suspenders approach: structural removal (field drop) + semantic removal (LLM scan)

---

## D-007 — Sequential agent orchestration (not parallel)

**Category**: Architecture  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
The agent could orchestrate pipeline steps in parallel (e.g., run App Store and Play Store ingestion simultaneously) or sequentially.

### Decision
**Sequential orchestration for the primary pipeline.** Parallelism only within ingestion (two store fetches can run concurrently).

### Rationale
- Each phase depends on the output of the prior — parallelism across phases is not possible
- Sequential execution makes debugging and logging straightforward
- For this scale (hundreds of reviews, one weekly run) throughput is not a bottleneck
- Parallelism within ingestion (App Store + Play Store fetched concurrently) is a simple optimisation with clear boundaries

---

## D-008 — Markdown as the canonical pulse note format

**Category**: Output  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
The pulse note could be authored as plain text, HTML, or Markdown before being written to Google Docs via MCP.

### Decision
**Markdown as the canonical intermediate format; MCP server renders it into Google Doc structure.**

### Rationale
- Markdown is human-readable in raw form (useful for debugging and `weekly_pulse.md` artifact)
- Google Docs MCP server can accept Markdown and format it correctly
- Decouples note generation (LLM produces Markdown) from delivery format (Docs/email)
- Easy to diff and version-control in `data/weekly_pulse.md`

---

## D-009 — 5 fixed themes rather than allowing ≥ 5

**Category**: Business  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
The constraint says "maximum 5 themes." We could implement exactly 5 always, or allow the count to vary up to 5 based on data.

### Decision
**Always produce exactly 5 theme buckets at clustering, then surface only the top 3 in the pulse note.**

### Rationale
- Consistent schema across weeks makes tracking easier (no missing theme categories)
- Low-volume themes still exist in `processed_signal.json` for stakeholders who want them
- The pulse note highlights only top 3 — keeping the one-pager focused and scannable
- Matches the problem statement: "max 5 themes" for clustering, "top 3" for the note

---

## D-010 — Email sends as a draft, not auto-sent

**Category**: Business  
**Date**: 2026-06-13  
**Status**: ✅ Decided

### Context
The problem statement says "draft an email." We could auto-send, create a draft, or prompt the user.

### Decision
**Create a Gmail draft only — never auto-send.**

### Rationale
- Problem statement explicitly says "draft" — respects the stated requirement
- Human review before sending is a safety control; the agent should not send email autonomously
- Reduces risk of accidentally emailing wrong recipients or sending a bad note
- Reviewer can personalise subject line or add context before sending

---

## How to Add a New Decision

Copy the template below and append it to this file:

```markdown
## D-XXX — [Short Decision Title]

**Category**: [Architecture / Processing / Integration / Data / Privacy / Business / Output]
**Date**: YYYY-MM-DD
**Status**: 🔲 Pending / ✅ Decided / 🔄 Revisited

### Context
[Why is this decision needed? What is the problem or trade-off?]

### Options Considered
| Option | Description | Pros | Cons |
|---|---|---|---|
| A | ... | ... | ... |
| B | ... | ... | ... |

### Decision
[Which option was chosen?]

### Rationale
[Why this option over the others?]
```
