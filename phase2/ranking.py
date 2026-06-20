"""Theme aggregation, ranking, and quote shortlisting."""

import re

from phase2.pre_router import match_themes
from phase2.themes import THEMES


def aggregate_themes(
    classifications: list[dict],
    reviews_by_id: dict[str, dict],
) -> list[dict]:
    """Build theme stats for all five themes and flag top 3."""
    buckets: dict[str, list[float]] = {theme: [] for theme in THEMES}
    rating_buckets: dict[str, list[int]] = {theme: [] for theme in THEMES}

    for item in classifications:
        theme = item["theme"]
        if theme not in buckets:
            continue
        buckets[theme].append(item["sentiment_score"])
        review = reviews_by_id.get(item["review_id"])
        if review:
            rating_buckets[theme].append(int(review["rating"]))

    theme_rows = []
    for theme in THEMES:
        scores = buckets[theme]
        ratings = rating_buckets[theme]
        count = len(scores)
        avg_sentiment = sum(scores) / count if count else 0.0
        avg_rating = sum(ratings) / len(ratings) if ratings else 0.0
        priority = count * (1 - avg_sentiment)
        theme_rows.append(
            {
                "name": theme,
                "review_count": count,
                "average_sentiment": round(avg_sentiment, 4),
                "average_rating": round(avg_rating, 2),
                "priority_score": round(priority, 4),
                "featured": False,
            }
        )

    ranked = sorted(theme_rows, key=lambda t: t["priority_score"], reverse=True)
    featured_names = {t["name"] for t in ranked[:3]}
    for row in theme_rows:
        row["featured"] = row["name"] in featured_names

    return theme_rows


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def _extract_snippet(text: str, max_words: int = 35) -> str:
    """Return a verbatim substring suitable for quoting."""
    text = text.strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    snippet = " ".join(words[:max_words])
    if not text.startswith(snippet):
        idx = text.find(snippet)
        if idx >= 0:
            return text[idx : idx + len(snippet)]
    return snippet


def build_quote_candidates(
    theme: str,
    classifications: list[dict],
    reviews_by_id: dict[str, dict],
    limit: int = 8,
) -> list[dict]:
    """Deterministic shortlist of verbatim quote candidates for a theme."""
    theme_reviews = [
        c for c in classifications if c["theme"] == theme
    ]
    candidates = []
    for item in theme_reviews:
        review = reviews_by_id.get(item["review_id"])
        if not review:
            continue
        text = str(review.get("text", "")).strip()
        if _word_count(text) < 12:
            continue
        if item["sentiment_score"] > 0.2 and int(review["rating"]) > 3:
            continue
        keyword_hits = match_themes(text)
        if theme not in keyword_hits and item["sentiment_score"] > -0.1:
            continue
        snippet = _extract_snippet(text)
        if snippet not in text:
            continue
        candidates.append(
            {
                "review_id": review["id"],
                "snippet": snippet,
                "store": review.get("store", ""),
                "rating": int(review["rating"]),
                "sentiment_score": item["sentiment_score"],
            }
        )

    candidates.sort(key=lambda c: (c["sentiment_score"], -c["rating"]))
    if not candidates:
        for item in theme_reviews:
            review = reviews_by_id.get(item["review_id"])
            if not review:
                continue
            text = str(review.get("text", "")).strip()
            if _word_count(text) < 6:
                continue
            snippet = _extract_snippet(text)
            candidates.append(
                {
                    "review_id": review["id"],
                    "snippet": snippet,
                    "store": review.get("store", ""),
                    "rating": int(review["rating"]),
                    "sentiment_score": item["sentiment_score"],
                }
            )
        candidates.sort(key=lambda c: c["sentiment_score"])

    return candidates[:limit]
