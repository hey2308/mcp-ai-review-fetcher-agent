"""Deterministic keyword pre-routing for high-confidence theme assignment."""

from phase2.themes import THEME_KEYWORDS, THEMES


def _normalize(text: str) -> str:
    return text.lower()


def match_themes(text: str) -> list[str]:
    """Return list of themes whose keywords appear in text."""
    normalized = _normalize(text)
    matched = []
    for theme in THEMES:
        keywords = THEME_KEYWORDS.get(theme, [])
        if any(kw in normalized for kw in keywords):
            matched.append(theme)
    return matched


def count_theme_hits(text: str) -> dict[str, int]:
    """Count keyword hits per theme."""
    normalized = _normalize(text)
    hits = {}
    for theme in THEMES:
        count = sum(1 for kw in THEME_KEYWORDS.get(theme, []) if kw in normalized)
        if count:
            hits[theme] = count
    return hits


def pre_route_review(review: dict) -> str | None:
    """
    Assign theme if exactly one keyword theme matches.
    Returns theme name or None if ambiguous / no match.
    """
    combined = f"{review.get('title', '')} {review.get('text', '')}"
    matches = match_themes(combined)
    if len(matches) == 1:
        return matches[0]
    return None


def best_keyword_theme(review: dict, default: str = "Performance & App Stability") -> str:
    """Assign theme with highest keyword hit count; ties go to default."""
    combined = f"{review.get('title', '')} {review.get('text', '')}"
    hits = count_theme_hits(combined)
    if not hits:
        return default
    max_count = max(hits.values())
    leaders = [theme for theme, count in hits.items() if count == max_count]
    if len(leaders) == 1:
        return leaders[0]
    return default
