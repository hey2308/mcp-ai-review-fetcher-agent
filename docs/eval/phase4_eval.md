# Phase 4 Evaluation — MCP Integration (Google Docs + Gmail)

## Purpose

This document defines how to verify that the MCP Integration phase is complete and correct. Phase 4 is where the pipeline's outputs become visible in real Google Workspace products. Every verification here requires confirming that the MCP layer worked correctly and that the correct content appears in the correct places — without any direct Google API calls in the agent code.

---

## What This Phase Must Deliver

- A running MCP server (`taylorwilsdon/google_workspace_mcp`) verified as reachable
- A Google Doc created in the user's Drive, titled correctly, with content matching `weekly_pulse.md`
- A Gmail draft created in the user's Drafts folder, addressed to the configured alias, with the pulse note in the body and a link to the Google Doc
- `data/output_links.json` containing the doc URL and draft ID
- Zero instances of direct Google API client code in the agent's MCP-facing logic

---

## Automated Checks

---

### AC-4.1 — MCP Server Reachability

**What it checks**: That the MCP server process is running and accepting connections before any Workspace operations are attempted.

**Condition**: A lightweight MCP tool call (e.g., list documents with limit=1) completes successfully with a valid response (no connection error, no timeout)

**Timing**: This check must be the first action taken in Phase 4. If it fails, all subsequent steps are skipped.

**Why this matters**: Attempting to create documents or drafts against an unreachable MCP server would produce confusing errors. Failing fast with a clear message is preferable.

**Failure action**: Check that the MCP server process is running. Check `mcp_config.json` for the correct endpoint URL. Start the server if it is not running and re-run the health check.

---

### AC-4.2 — Google Doc Creation Success

**What it checks**: That the MCP `create_document` tool call returns a successful response.

**Condition**: The tool call returns a response containing a non-empty `document_id` and a non-empty `document_url` field. No error is returned.

**Why this matters**: A failure here means the pulse note was not published and the pipeline's primary delivery mechanism failed.

**Failure action**: Inspect the MCP server logs for the specific Google API error. Common causes: OAuth token expired (MCP server should handle refresh automatically — if not, re-run the OAuth consent flow), insufficient Drive permissions (check that the Google Cloud project has Drive API enabled), or the document content is malformed.

---

### AC-4.3 — Google Doc Title Matches Expected Pattern

**What it checks**: That the created document has the correct title.

**Condition**: The document title returned by the MCP server (or fetched via `get_document`) matches the pattern `Groww Weekly Pulse — Week of [YYYY-MM-DD]` where the date is the Monday of the current week.

**Why this matters**: A correctly titled document is findable and identifiable. An incorrect title (e.g., from a stale template or a prompt that generated a different title) makes the document harder to find and archive.

**Failure action**: If the title doesn't match, it may mean the title was generated dynamically by the LLM rather than using the exact configured pattern. Enforce the title format explicitly in the tool call arguments.

---

### AC-4.4 — Google Doc Content Matches Pulse Note

**What it checks**: That the content of the created Google Doc matches the content of `data/weekly_pulse.md`.

**How to check**: Retrieve the document content via the MCP `get_document` tool. Strip Google Docs formatting metadata and compare the plain text against the content of `weekly_pulse.md` (allowing for whitespace and line-break normalisation differences introduced by the Markdown-to-Docs conversion).

**Condition**: The retrieved document content matches `weekly_pulse.md` content with ≥ 95% text similarity (minor formatting differences from Markdown rendering are acceptable; missing sections or truncated content are not).

**Why this matters**: The Google Doc is the primary shared artifact. If its content doesn't match the intended pulse note, the team is reading different content than what was verified in Phase 3.

**Failure action**: If content is truncated, the MCP tool may have a content length limit — investigate the server's `create_document` tool documentation. If content is malformed, check how the Markdown-to-Docs conversion is handled by the MCP server.

---

### AC-4.5 — Doc URL Is Recorded in Output Links

**What it checks**: That the Google Doc URL is persisted in `data/output_links.json`.

**Condition**: `output_links.json` exists, is valid JSON, and contains a `doc_url` field with a non-empty string that begins with `https://docs.google.com/`.

**Why this matters**: The Gmail draft body and any external references to the pulse note depend on this URL being recorded correctly.

**Failure action**: If the file is missing or the URL is absent, check the step that writes `output_links.json`. If the MCP server didn't return a URL, check AC-4.2 first.

---

### AC-4.6 — Gmail Draft Creation Success

**What it checks**: That the MCP `create_draft` tool call returns a successful response.

**Condition**: The tool call returns a response containing a non-empty `draft_id` field. No error is returned.

**Why this matters**: A failure here means the team won't receive the pulse note via email, and the pipeline's email delivery is broken.

**Failure action**: Inspect the MCP server logs. Common causes: Gmail API not enabled in the Google Cloud project, insufficient Gmail scope in the OAuth consent, or malformed draft content (e.g., invalid recipient address format).

---

### AC-4.7 — Gmail Draft Recipient Is Correct

**What it checks**: That the draft is addressed to the correct recipient as configured in `config.yaml`.

**How to check**: After creation, retrieve the draft metadata via the MCP `get_draft` tool (or equivalent) and verify the `To` field.

**Condition**: The `To` field in the draft metadata matches the `email_alias` value from `config.yaml` exactly.

**Why this matters**: An incorrect recipient could result in the pulse note being sent to the wrong person.

**Failure action**: The recipient address is passed as a tool argument — verify it is being read correctly from `config.yaml` and passed correctly to the MCP tool.

---

### AC-4.8 — Draft ID Is Recorded in Output Links

**What it checks**: That the Gmail draft ID is persisted in `data/output_links.json`.

**Condition**: `output_links.json` contains a `draft_id` field with a non-empty string.

**Failure action**: Check the step that writes `output_links.json`. Re-run if the field is missing.

---

### AC-4.9 — No Direct Google API Client Usage in Agent Code

**What it checks**: That the agent's MCP-facing code does not import or call Google API client libraries directly.

**How to check**: Static analysis / grep of the agent's source files for imports of: `google.auth`, `googleapiclient`, `google.oauth2`, `httplib2` (when used for Google auth), or direct `requests.get/post` calls to `*.googleapis.com` endpoints.

**Condition**: Zero matches found in the agent's MCP integration code paths.

**Why this matters**: This is a core constraint of the project — "MCP-first, not call Google APIs manually." Direct API calls in the agent code undermine the entire MCP abstraction.

**Failure action**: If any direct Google API calls are found in the agent code, they must be removed and replaced with the appropriate MCP tool call.

---

## Manual Checks

---

### MC-4.1 — Open and Read the Google Doc

**What to do**: Open the Google Doc URL from `output_links.json` in a browser.

**What to verify**:
- The document opens without access errors (it is accessible to the authenticated account)
- The document title is correct (`Groww Weekly Pulse — Week of [date]`)
- The document content matches what is in `weekly_pulse.md` — all three sections are present, all quotes are correct, all action ideas are present
- The document is readable and well-formatted (headings render as headings, quotes are visually distinct)

**Pass condition**: The document is accessible, correctly titled, correctly formatted, and matches the verified pulse note from Phase 3.

**Failure action**: If the document is inaccessible, check sharing settings (MCP server may have created the doc with restricted access by default — adjust if needed). If content is missing or malformed, investigate the MCP server's Markdown-to-Docs conversion.

---

### MC-4.2 — Open Gmail Drafts and Verify the Draft

**What to do**: Open Gmail in a browser and navigate to the Drafts folder.

**What to verify**:
- A draft exists with the subject line `[Groww Weekly Pulse] Week of [date]`
- The draft is addressed to the correct alias
- The draft body contains the full pulse note text
- The draft body contains a working link to the Google Doc
- The draft is in Drafts (not in Sent — it should not have been sent automatically)

**Pass condition**: The draft is visible in Drafts, correctly addressed, and contains the expected content.

**Failure action**: If the draft is missing, check AC-4.6 first. If the draft was sent rather than saved, this is a serious error — investigate the MCP tool used (ensure `create_draft` was called, not `send_email`).

---

### MC-4.3 — MCP Server Logs Show Tool Calls

**What to do**: Review the MCP server's logs for the run period.

**What to verify**:
- The logs show at least two tool invocations: one for `create_document` (or equivalent) and one for `create_draft` (or equivalent)
- The log entries show successful completion (HTTP 200 or equivalent success status from the Google API)
- There are no unexpected error entries (rate limits, auth failures that resolved after retry, etc.)

**Pass condition**: MCP server logs confirm both tool calls completed successfully.

**Failure action**: If the logs show failures that were not reflected in the agent's error handling, investigate why errors were silently swallowed. Improve error propagation from the MCP server to the agent.

---

### MC-4.4 — Doc Link in Gmail Draft Is Clickable and Correct

**What to do**: In the Gmail draft, click or open the Google Doc link included in the email body.

**What to verify**: The link navigates to the correct Google Doc (same document as verified in MC-4.1).

**Pass condition**: Link works and opens the correct document.

**Failure action**: If the link is broken or points to a different document, check how the doc URL is being included in the draft body.

---

## Exit Gate

**Phase 4 is complete when:**

| Gate | Requirement |
|---|---|
| All 9 automated checks | Pass |
| All 4 manual checks | Pass |
| `data/output_links.json` | Exists, valid JSON, contains `doc_url` and `draft_id` |
| Google Doc | Accessible, correct title, correct content |
| Gmail draft | Visible in Drafts, correct recipient, correct content |
| Run log | Contains Phase 4 summary entry with doc URL and draft ID |

> **Do not proceed to Phase 5 until this gate is cleared.**
