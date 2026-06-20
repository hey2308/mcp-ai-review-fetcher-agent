"""Markdown pulse note assembly from processed_signal.json."""

import re
from datetime import datetime

STORE_LABELS = {
    "play_store": "Play Store",
    "app_store": "App Store",
}


def sentiment_summary(theme_name: str, avg_sentiment: float) -> str:
    """One-line theme summary from average sentiment."""
    if avg_sentiment <= -0.3:
        return f"Users report serious frustration with {theme_name.lower()}."
    if avg_sentiment <= 0.0:
        return f"Negative feedback dominates {theme_name.lower()} this period."
    if avg_sentiment <= 0.3:
        return f"Mixed sentiment on {theme_name.lower()} — pain points remain."
    return f"Mostly positive tone on {theme_name.lower()}, with some complaints."


def _monday_of_week(iso_dt: str) -> str:
    dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    monday = dt.date()
    return monday.strftime("%Y-%m-%d")


def compute_period(reviews: list[dict]) -> tuple[str, str]:
    """Return (start_date, end_date) ISO date strings from review list."""
    dates = sorted(r.get("date", "") for r in reviews if r.get("date"))
    if not dates:
        today = datetime.now().strftime("%Y-%m-%d")
        return today, today
    start = datetime.fromisoformat(dates[0].replace("Z", "+00:00")).strftime("%Y-%m-%d")
    end = datetime.fromisoformat(dates[-1].replace("Z", "+00:00")).strftime("%Y-%m-%d")
    return start, end


def _truncate_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;") + "..."


def assemble_note(
    signal: dict,
    reviews: list[dict],
    max_words: int = 250,
) -> str:
    """Build the weekly pulse note markdown from Phase 2 signal."""
    week = signal.get("week", datetime.now().strftime("%G-W%V"))
    review_count = signal.get("reviews_processed", len(reviews))
    generated_at = signal.get("generated_at", datetime.now().isoformat())
    week_of = _monday_of_week(generated_at)

    period_start, period_end = compute_period(reviews)

    featured = [t for t in signal.get("themes", []) if t.get("featured")]
    featured.sort(key=lambda t: t.get("priority_score", 0), reverse=True)

    quotes = signal.get("quotes", [])
    quotes_by_theme = {q["theme"]: q for q in quotes}
    action_ideas = list(signal.get("action_ideas", []))

    lines = [
        f"## Groww Weekly Pulse — Week of {week_of}",
        f"### Period: {period_start} to {period_end} | Reviews Analysed: {review_count}",
        "",
        "---",
        "",
        "### Top Themes",
    ]

    for i, theme in enumerate(featured[:3], start=1):
        summary = sentiment_summary(theme["name"], theme["average_sentiment"])
        lines.append(
            f"{i}. **{theme['name']}** — {theme['review_count']} reviews, "
            f"avg. rating {theme['average_rating']} ⭐"
        )
        lines.append(f"   {summary}")
        lines.append("")

    lines.extend(["---", "", "### User Voices"])

    for theme in featured[:3]:
        quote = quotes_by_theme.get(theme["name"])
        if not quote:
            continue
        store = STORE_LABELS.get(quote.get("store", ""), quote.get("store", "Store"))
        text = quote["quote"].strip().strip('"')
        lines.append(f'> "{text}" — {store}, {quote["rating"]}⭐')
        lines.append("")

    lines.extend(["---", "", "### Action Ideas"])

    for i, idea in enumerate(action_ideas[:3], start=1):
        lines.append(f"{i}. {idea.strip()}")

    note = "\n".join(lines).strip() + "\n"
    return enforce_word_limit(note, max_words)


def count_words(text: str) -> int:
    """Count prose words per phase3 eval (exclude markdown syntax)."""
    cleaned = text
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^>\s?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^---\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*+", "", cleaned)
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    return len(re.findall(r"[A-Za-z0-9']+", cleaned))


def enforce_word_limit(note: str, max_words: int) -> str:
    """Trim action ideas and theme summaries to fit word limit; preserve quotes."""
    if count_words(note) <= max_words:
        return note

    sections = note.split("### Action Ideas")
    if len(sections) != 2:
        return _truncate_note_fallback(note, max_words)

    head, actions_block = sections
    actions = [
        line for line in actions_block.strip().splitlines()
        if re.match(r"^\d+\.\s+", line.strip())
    ]

    for words_per_action in (25, 18, 12, 8):
        trimmed_actions = []
        for i, line in enumerate(actions[:3], start=1):
            body = re.sub(r"^\d+\.\s+", "", line.strip())
            trimmed_actions.append(f"{i}. {_truncate_to_words(body, words_per_action)}")
        candidate = head + "### Action Ideas\n\n" + "\n".join(trimmed_actions) + "\n"
        if count_words(candidate) <= max_words:
            return candidate

    return _truncate_note_fallback(note, max_words)


def _truncate_note_fallback(note: str, max_words: int) -> str:
    """Last resort: truncate action ideas section word-by-word."""
    lines = note.splitlines()
    result = []
    for line in lines:
        result.append(line)
        if count_words("\n".join(result)) > max_words:
            result.pop()
            break
    while count_words("\n".join(result)) > max_words and result:
        result.pop()
    return "\n".join(result).strip() + "\n"
