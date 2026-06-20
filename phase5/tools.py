"""Tool registry — each pipeline step as a named tool with clear input/output contracts."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from phase1.app_store import fetch_app_store_reviews
from phase1.ingest import get_review_hash, validate_record
from phase1.play_store import fetch_play_store_reviews
from phase2.actions import generate_action_ideas
from phase2.classify import classify_batch
from phase2.groq_client import GroqBudgetExceeded, GroqClient
from phase2.pii_scrub import scrub_review
from phase2.pre_router import best_keyword_theme, pre_route_review
from phase2.process import cap_reviews, estimate_run_tokens
from phase2.quotes import select_quote_for_theme
from phase2.ranking import aggregate_themes, build_quote_candidates
from phase2.sentiment import final_sentiment
from phase3.assembler import assemble_note, count_words
from phase3.generate import load_reviews_for_signal
from phase3.validator import (
    scan_pii,
    validate_quotes_match_signal,
    validate_structure,
    validate_theme_names,
)
from phase4.mcp_client import McpClient, McpServerError, doc_url_from_id
from phase4.publish import extract_week_of

logger = logging.getLogger("phase5.tools")


class ToolError(Exception):
    """Raised when a pipeline tool fails."""


@dataclass
class PipelineContext:
    config: dict
    offline: bool = False
    app_store_reviews: list[dict] = field(default_factory=list)
    play_store_reviews: list[dict] = field(default_factory=list)
    merged_reviews: list[dict] = field(default_factory=list)
    clean_reviews: list[dict] = field(default_factory=list)
    scrubbed_reviews: list[dict] = field(default_factory=list)
    classifications: list[dict] = field(default_factory=list)
    theme_rows: list[dict] = field(default_factory=list)
    featured_themes: list[dict] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)
    action_ideas: list[str] = field(default_factory=list)
    processed_signal: dict = field(default_factory=dict)
    pulse_note: str = ""
    doc_url: str = ""
    draft_id: str = ""
    email_subject: str = ""
    groq_client: GroqClient | None = None
    reviews_by_id: dict[str, dict] = field(default_factory=dict)
    original_review_count: int = 0
    dedup_count: int = 0


def _cutoff_date(config: dict) -> datetime:
    weeks = int(config.get("review_window_weeks", 10))
    return datetime.now(timezone.utc) - timedelta(weeks=weeks)


def fetch_app_store_reviews_tool(ctx: PipelineContext) -> str:
    app_id = ctx.config.get("app_store_id", "1404871703")
    weeks = int(ctx.config.get("review_window_weeks", 10))
    ctx.app_store_reviews = fetch_app_store_reviews(app_id, weeks)
    return f"{len(ctx.app_store_reviews)} reviews fetched from App Store"


def fetch_play_store_reviews_tool(ctx: PipelineContext) -> str:
    package = ctx.config.get("play_store_package", "com.nextbillion.groww")
    weeks = int(ctx.config.get("review_window_weeks", 10))
    ctx.play_store_reviews = fetch_play_store_reviews(package, weeks)
    return f"{len(ctx.play_store_reviews)} reviews fetched from Play Store"


def merge_and_deduplicate_tool(ctx: PipelineContext) -> str:
    merged = ctx.app_store_reviews + ctx.play_store_reviews
    unique: list[dict] = []
    seen: set[str] = set()
    dedup = 0
    for review in merged:
        h = get_review_hash(review["title"], review["text"])
        if h in seen:
            dedup += 1
            continue
        seen.add(h)
        unique.append(review)
    ctx.merged_reviews = unique
    ctx.dedup_count = dedup
    return f"Merged {len(merged)} raw reviews, removed {dedup} duplicates, {len(unique)} unique"


def scrub_and_validate_tool(ctx: PipelineContext) -> str:
    cutoff = _cutoff_date(ctx.config)
    validated: list[dict] = []
    discarded = 0
    for review in ctx.merged_reviews:
        ok, _reason = validate_record(review, cutoff)
        if not ok:
            discarded += 1
            continue
        validated.append(review)
    ctx.clean_reviews = validated
    os.makedirs("data", exist_ok=True)
    with open("data/reviews_raw.json", "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)
    return f"Validated {len(validated)} clean reviews ({discarded} discarded), saved reviews_raw.json"


def _offline_action_ideas(featured: list[dict], quotes: list[dict]) -> list[str]:
    ideas = []
    for theme_row in featured:
        quote = next((q for q in quotes if q["theme"] == theme_row["name"]), None)
        snippet = quote["quote"][:80] if quote else "recent user feedback"
        ideas.append(
            f"Address {theme_row['name']} pain points highlighted in reviews "
            f'(e.g. "{snippet}") with a focused fix in the corresponding Groww flow.'
        )
    return ideas[:3]


def classify_themes_tool(ctx: PipelineContext) -> str:
    max_reviews = int(ctx.config.get("max_reviews_to_process", 1000))
    reviews, original = cap_reviews(ctx.clean_reviews, max_reviews)
    ctx.original_review_count = original

    scrubbed: list[dict] = []
    pii_flagged = 0
    for review in reviews:
        cleaned, had_pii = scrub_review(review)
        if had_pii:
            pii_flagged += 1
        scrubbed.append(cleaned)
    ctx.scrubbed_reviews = scrubbed
    ctx.reviews_by_id = {r["id"]: r for r in scrubbed}

    pre_routed: list[dict] = []
    groq_queue: list[dict] = []
    for review in scrubbed:
        theme = pre_route_review(review)
        if theme:
            pre_routed.append(
                {
                    "review_id": review["id"],
                    "theme": theme,
                    "sentiment_score": final_sentiment(review["rating"], 0.0),
                    "source": "keyword",
                }
            )
        else:
            groq_queue.append(review)

    batch_size = int(ctx.config.get("llm_batch_size", 20))
    text_max_words = int(ctx.config.get("llm_text_max_words", 50))
    groq_classified: list[dict] = []

    if ctx.offline:
        for review in groq_queue:
            theme = best_keyword_theme(review)
            groq_classified.append(
                {
                    "review_id": review["id"],
                    "theme": theme,
                    "sentiment_score": final_sentiment(review["rating"], 0.0),
                    "source": "keyword_fallback",
                }
            )
        ctx.classifications = pre_routed + groq_classified
        return (
            f"Classified {len(ctx.classifications)} reviews "
            f"(pre-routed={len(pre_routed)}, offline fallback={len(groq_classified)}, pii_flagged={pii_flagged})"
        )

    ctx.groq_client = GroqClient(
        model=ctx.config.get("llm_model", "llama-3.3-70b-versatile"),
        max_rpm=int(ctx.config.get("llm_max_rpm", 24)),
        max_tpm=int(ctx.config.get("llm_max_tpm", 10000)),
        max_tokens_per_run=int(ctx.config.get("llm_max_tokens_per_run", 90000)),
    )
    estimated = estimate_run_tokens(len(groq_queue), batch_size)
    try:
        ctx.groq_client.preflight_check(estimated)
    except GroqBudgetExceeded as err:
        raise ToolError(str(err)) from err

    for i in range(0, len(groq_queue), batch_size):
        batch = groq_queue[i : i + batch_size]
        groq_classified.extend(classify_batch(ctx.groq_client, batch, text_max_words))

    ctx.classifications = pre_routed + groq_classified
    batches = (len(groq_queue) + batch_size - 1) // batch_size if groq_queue else 0
    return (
        f"Classified {len(ctx.classifications)} reviews "
        f"(pre-routed={len(pre_routed)}, groq={len(groq_classified)} in {batches} batches)"
    )


def score_and_rank_themes_tool(ctx: PipelineContext) -> str:
    ctx.theme_rows = aggregate_themes(ctx.classifications, ctx.reviews_by_id)
    ctx.featured_themes = [t for t in ctx.theme_rows if t["featured"]]
    ctx.featured_themes.sort(key=lambda t: t["priority_score"], reverse=True)
    summary = ", ".join(f"{t['name']} ({t['review_count']})" for t in ctx.featured_themes[:3])
    return f"Ranked {len(ctx.theme_rows)} themes; top: {summary}"


def extract_quotes_tool(ctx: PipelineContext) -> str:
    quotes: list[dict] = []
    if ctx.offline:
        for theme_row in ctx.featured_themes:
            candidates = build_quote_candidates(
                theme_row["name"], ctx.classifications, ctx.reviews_by_id
            )
            if not candidates:
                continue
            chosen = candidates[0]
            review = ctx.reviews_by_id[chosen["review_id"]]
            snippet = chosen["snippet"]
            if snippet not in review["text"]:
                snippet = review["text"][:200].strip()
            quotes.append(
                {
                    "theme": theme_row["name"],
                    "review_id": chosen["review_id"],
                    "quote": snippet,
                    "store": chosen["store"],
                    "rating": chosen["rating"],
                }
            )
    else:
        if not ctx.groq_client:
            raise ToolError("Groq client not initialized for quote selection")
        for theme_row in ctx.featured_themes:
            quote = select_quote_for_theme(
                ctx.groq_client,
                theme_row["name"],
                ctx.classifications,
                ctx.reviews_by_id,
            )
            if quote:
                quotes.append(quote)

    if len(quotes) != 3:
        raise ToolError(f"Expected 3 quotes, got {len(quotes)}")
    ctx.quotes = quotes
    return "Selected 3 verbatim quotes for featured themes"


def generate_actions_tool(ctx: PipelineContext) -> str:
    if ctx.offline:
        ctx.action_ideas = _offline_action_ideas(ctx.featured_themes, ctx.quotes)
    else:
        if not ctx.groq_client:
            raise ToolError("Groq client not initialized for action generation")
        ctx.action_ideas = generate_action_ideas(ctx.groq_client, ctx.featured_themes, ctx.quotes)

    week_id = datetime.now(timezone.utc).strftime("%G-W%V")
    client = ctx.groq_client
    ctx.processed_signal = {
        "week": week_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviews_input_total": ctx.original_review_count,
        "reviews_processed": len(ctx.scrubbed_reviews),
        "classifications": ctx.classifications,
        "themes": ctx.theme_rows,
        "quotes": ctx.quotes,
        "action_ideas": ctx.action_ideas,
        "groq_usage": {
            "requests": client.total_requests if client else 0,
            "estimated_tokens": client.total_tokens if client else 0,
            "offline_mode": ctx.offline,
        },
    }
    os.makedirs("data", exist_ok=True)
    with open("data/processed_signal.json", "w", encoding="utf-8") as f:
        json.dump(ctx.processed_signal, f, indent=2)
    return f"Generated {len(ctx.action_ideas)} action ideas, saved processed_signal.json"


def assemble_pulse_note_tool(ctx: PipelineContext) -> str:
    max_words = int(ctx.config.get("max_words", 250))
    reviews = load_reviews_for_signal(ctx.processed_signal)
    ctx.pulse_note = assemble_note(ctx.processed_signal, reviews, max_words=max_words)
    os.makedirs("data", exist_ok=True)
    with open("data/weekly_pulse.md", "w", encoding="utf-8") as f:
        f.write(ctx.pulse_note)
    words = count_words(ctx.pulse_note)
    return f"Assembled pulse note ({words} words), saved weekly_pulse.md"


def validate_note_tool(ctx: PipelineContext) -> str:
    max_words = int(ctx.config.get("max_words", 250))
    note = ctx.pulse_note
    checks: list[tuple[str, bool, str]] = []

    ok, msg = validate_structure(note)
    checks.append(("structure", ok, msg))
    if not ok:
        raise ToolError(f"Note structure invalid: {msg}")

    featured = [t for t in ctx.processed_signal.get("themes", []) if t.get("featured")]
    ok, msg = validate_theme_names(note, featured)
    checks.append(("themes", ok, msg))
    if not ok:
        raise ToolError(f"Theme validation failed: {msg}")

    ok, msg = validate_quotes_match_signal(note, ctx.processed_signal.get("quotes", []))
    checks.append(("quotes", ok, msg))
    if not ok:
        raise ToolError(f"Quote validation failed: {msg}")

    words = count_words(note)
    if words > max_words:
        raise ToolError(f"Word count {words} exceeds limit {max_words}")
    checks.append(("word_count", True, f"{words} words within limit"))

    pii_hits = scan_pii(note)
    if pii_hits:
        raise ToolError(f"PII detected in note: {pii_hits[:3]}")
    checks.append(("pii", True, "No PII detected"))

    return f"All note checks passed ({words} words)"


def create_google_doc_tool(ctx: PipelineContext) -> str:
    mcp_url = ctx.config.get("mcp_server_url", "").rstrip("/")
    google_doc_id = ctx.config.get("google_doc_id", "")
    client = McpClient(mcp_url)

    health = client.health_check()
    tools = client.list_tools()
    tool_names = {t.get("name") for t in tools}
    if not {"append_to_doc", "create_email_draft"}.issubset(tool_names):
        raise ToolError(f"MCP server missing required tools. Found: {tool_names}")

    week_of = extract_week_of(ctx.pulse_note)
    ctx.doc_url = doc_url_from_id(google_doc_id)
    doc_header = f"\n\n---\n## Groww Weekly Pulse — Week of {week_of}\n"
    doc_content = doc_header + ctx.pulse_note

    result = client.append_to_doc(google_doc_id, doc_content)
    return f"Appended pulse to Google Doc ({result.get('message', 'ok')})"


def create_gmail_draft_tool(ctx: PipelineContext) -> str:
    mcp_url = ctx.config.get("mcp_server_url", "").rstrip("/")
    email_alias = ctx.config.get("email_alias", "")
    client = McpClient(mcp_url)

    week_of = extract_week_of(ctx.pulse_note)
    ctx.email_subject = f"[Groww Weekly Pulse] Week of {week_of}"
    email_body = f"{ctx.pulse_note}\n\n---\nFull pulse document: {ctx.doc_url}\n"

    result = client.create_email_draft(email_alias, ctx.email_subject, email_body)
    ctx.draft_id = result.get("draft_id", "")
    if not ctx.draft_id:
        raise ToolError(f"No draft_id in MCP response: {result}")
    return f"Gmail draft created (ID: {ctx.draft_id})"


def write_output_links_tool(ctx: PipelineContext) -> str:
    week_of = extract_week_of(ctx.pulse_note)
    week_id = datetime.now(timezone.utc).strftime("%G-W%V")
    google_doc_id = ctx.config.get("google_doc_id", "")
    mcp_url = ctx.config.get("mcp_server_url", "")

    output_links = {
        "week": week_id,
        "week_of": week_of,
        "doc_id": google_doc_id,
        "doc_url": ctx.doc_url,
        "draft_id": ctx.draft_id,
        "email_to": ctx.config.get("email_alias", ""),
        "email_subject": ctx.email_subject,
        "mcp_server_url": mcp_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pulse_source": "data/weekly_pulse.md",
        "content_appended_chars": len(ctx.pulse_note) + 80,
    }
    os.makedirs("data", exist_ok=True)
    path = "data/output_links.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output_links, f, indent=2)
    return f"Wrote {path}"


TOOL_HANDLERS: dict[str, Any] = {
    "fetch_app_store_reviews": fetch_app_store_reviews_tool,
    "fetch_play_store_reviews": fetch_play_store_reviews_tool,
    "merge_and_deduplicate": merge_and_deduplicate_tool,
    "scrub_and_validate": scrub_and_validate_tool,
    "classify_themes": classify_themes_tool,
    "score_and_rank_themes": score_and_rank_themes_tool,
    "extract_quotes": extract_quotes_tool,
    "generate_actions": generate_actions_tool,
    "assemble_pulse_note": assemble_pulse_note_tool,
    "validate_note": validate_note_tool,
    "create_google_doc": create_google_doc_tool,
    "create_gmail_draft": create_gmail_draft_tool,
    "write_output_links": write_output_links_tool,
}
