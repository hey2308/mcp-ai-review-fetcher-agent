"""Agent system prompt and tool registry definitions for the Groww Weekly Pulse pipeline."""

SYSTEM_PROMPT = """You are a weekly review analysis agent for Groww.

Your job is to fetch public App Store and Play Store reviews, analyse them into themes,
generate a concise weekly pulse note, and publish it to Google Docs and Gmail using
the tools available to you.

## Constraints
- No PII in any output artifact.
- Maximum 5 theme clusters; surface the top 3 in the pulse note.
- Pulse note must be at most 250 words.
- Gmail creates a draft only — never send email automatically.
- If any tool returns an error, log the failure and halt immediately. Do not skip steps.

## Expected tool sequence
1. fetch_app_store_reviews
2. fetch_play_store_reviews
3. merge_and_deduplicate
4. scrub_and_validate
5. classify_themes
6. score_and_rank_themes
7. extract_quotes
8. generate_actions
9. assemble_pulse_note
10. validate_note
11. create_google_doc
12. create_gmail_draft
13. write_output_links

## Final output
After all steps succeed, output_links.json must contain doc_url and draft_id.
"""

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "fetch_app_store_reviews",
        "description": "Fetches reviews from the Apple iTunes RSS feed for the configured app.",
        "input": "review_window_weeks from config",
        "output": "raw App Store review records",
    },
    {
        "name": "fetch_play_store_reviews",
        "description": "Fetches reviews from the Google Play Store public API.",
        "input": "review_window_weeks from config",
        "output": "raw Play Store review records",
    },
    {
        "name": "merge_and_deduplicate",
        "description": "Combines both review sets and removes duplicates by content hash.",
        "input": "app_store + play_store review lists",
        "output": "unified deduplicated review list",
    },
    {
        "name": "scrub_and_validate",
        "description": "Validates schema, filters short/emoji/non-English reviews, saves reviews_raw.json.",
        "input": "merged review list",
        "output": "clean validated review list",
    },
    {
        "name": "classify_themes",
        "description": "PII-scrubs reviews and classifies each into a predefined theme (keyword + Groq).",
        "input": "clean reviews, theme list",
        "output": "classified reviews",
    },
    {
        "name": "score_and_rank_themes",
        "description": "Aggregates sentiment per theme and ranks by priority score.",
        "input": "classified reviews",
        "output": "ranked theme data",
    },
    {
        "name": "extract_quotes",
        "description": "Selects one verbatim quote per featured theme.",
        "input": "ranked themes + reviews",
        "output": "quote list (3 quotes)",
    },
    {
        "name": "generate_actions",
        "description": "Generates actionable product ideas from top themes and quotes.",
        "input": "featured themes + quotes",
        "output": "action ideas + processed_signal.json",
    },
    {
        "name": "assemble_pulse_note",
        "description": "Builds the Markdown weekly pulse note from processed signal.",
        "input": "processed signal + reviews metadata",
        "output": "weekly_pulse.md text",
    },
    {
        "name": "validate_note",
        "description": "Checks structure, themes, quotes, word count, and PII in the pulse note.",
        "input": "pulse note text",
        "output": "validation result",
    },
    {
        "name": "create_google_doc",
        "description": "MCP: appends the pulse note to the configured Google Doc.",
        "input": "note text, doc ID",
        "output": "doc URL",
    },
    {
        "name": "create_gmail_draft",
        "description": "MCP: creates a Gmail draft with the pulse note (does not send).",
        "input": "note text, doc URL, recipient",
        "output": "draft ID",
    },
    {
        "name": "write_output_links",
        "description": "Persists doc URL, draft ID, and run metadata to output_links.json.",
        "input": "doc URL, draft ID",
        "output": "file path",
    },
]

TOOL_SEQUENCE: list[str] = [t["name"] for t in TOOL_DEFINITIONS]
