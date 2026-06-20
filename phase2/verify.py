"""Automated verification for Phase 2 output."""

import json
import logging
import os
import re
from datetime import datetime, timezone

import yaml

from phase2.themes import THEMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("verify")

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
PHONE_PATTERN = re.compile(r"\b\d{7,}\b")


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


SKIP_PII_KEYS = {
    "review_id",
    "id",
    "week",
    "generated_at",
    "source",
    "store",
    "name",
    "theme",
    "status",
}


def _scan_pii_in_obj(obj, key: str | None = None) -> list[str]:
    hits = []
    if isinstance(obj, dict):
        for k, value in obj.items():
            hits.extend(_scan_pii_in_obj(value, k))
    elif isinstance(obj, list):
        for value in obj:
            hits.extend(_scan_pii_in_obj(value, key))
    elif isinstance(obj, str):
        if key in SKIP_PII_KEYS:
            return hits
        if EMAIL_PATTERN.search(obj) or PHONE_PATTERN.search(obj):
            hits.append(obj[:80])
    return hits


def run_verification() -> bool:
    logger.info("Starting automated verification for Phase 2 output...")

    signal_path = "data/processed_signal.json"
    reviews_path = "data/reviews_raw.json"

    if not os.path.exists(signal_path):
        logger.error("FAIL: Missing %s", signal_path)
        return False
    if not os.path.exists(reviews_path):
        logger.error("FAIL: Missing %s", reviews_path)
        return False

    with open(signal_path, "r", encoding="utf-8") as f:
        signal = json.load(f)
    with open(reviews_path, "r", encoding="utf-8") as f:
        raw_reviews = json.load(f)

    config = load_config()
    max_reviews = int(config.get("max_reviews_to_process", 1000))
    expected_processed = min(len(raw_reviews), max_reviews)

    classifications = signal.get("classifications", [])
    themes = signal.get("themes", [])
    quotes = signal.get("quotes", [])
    action_ideas = signal.get("action_ideas", [])
    reviews_by_id = {r["id"]: r for r in raw_reviews}

    results: dict[str, tuple[bool, str]] = {}

    # AC-2.1
    ac_2_1 = len(classifications) == expected_processed
    results["AC-2.1: Complete Classification Coverage"] = (
        ac_2_1,
        f"classifications={len(classifications)}, expected_processed={expected_processed}",
    )

    # AC-2.2
    invalid_labels = [
        c for c in classifications if c.get("theme") not in THEMES
    ]
    ac_2_2 = len(invalid_labels) == 0
    results["AC-2.2: Valid Theme Labels Only"] = (
        ac_2_2,
        "All labels valid." if ac_2_2 else f"Invalid labels: {len(invalid_labels)}",
    )

    # AC-2.3
    bad_sentiment = [
        c
        for c in classifications
        if not (-1.0 <= float(c.get("sentiment_score", 99)) <= 1.0)
    ]
    ac_2_3 = len(bad_sentiment) == 0
    results["AC-2.3: Sentiment Score Range [-1, 1]"] = (
        ac_2_3,
        "All sentiment scores valid." if ac_2_3 else f"Out of range: {len(bad_sentiment)}",
    )

    # AC-2.4
    theme_names = {t.get("name") for t in themes}
    ac_2_4 = len(themes) == 5 and theme_names == set(THEMES)
    results["AC-2.4: Five Themes in Output"] = (
        ac_2_4,
        f"themes={len(themes)}" if not ac_2_4 else "Exactly 5 themes present.",
    )

    # AC-2.5
    featured = [t for t in themes if t.get("featured")]
    ranked = sorted(themes, key=lambda t: t.get("priority_score", 0), reverse=True)
    top3_names = {t["name"] for t in ranked[:3]}
    featured_names = {t["name"] for t in featured}
    ac_2_5 = len(featured) == 3 and featured_names == top3_names
    results["AC-2.5: Top-3 Themes Flagged"] = (
        ac_2_5,
        f"featured={len(featured)}" if not ac_2_5 else "Top 3 correctly flagged.",
    )

    # AC-2.6
    ac_2_6 = len(quotes) == 3
    results["AC-2.6: Exactly 3 Quotes Extracted"] = (
        ac_2_6,
        f"quotes={len(quotes)}",
    )

    # AC-2.7
    quote_failures = []
    for quote in quotes:
        review = reviews_by_id.get(quote.get("review_id", ""))
        if not review:
            quote_failures.append(quote.get("review_id"))
            continue
        q_norm = _normalize_whitespace(quote.get("quote", ""))
        text_norm = _normalize_whitespace(review.get("text", ""))
        if q_norm not in text_norm:
            quote_failures.append(quote.get("review_id"))
    ac_2_7 = len(quote_failures) == 0
    results["AC-2.7: Quotes Are Verbatim Substrings"] = (
        ac_2_7,
        "All quotes verbatim." if ac_2_7 else f"Failed review IDs: {quote_failures[:3]}",
    )

    # AC-2.8
    ac_2_8 = isinstance(action_ideas, list) and len(action_ideas) == 3
    results["AC-2.8: Exactly 3 Action Ideas Generated"] = (
        ac_2_8,
        f"action_ideas={len(action_ideas) if isinstance(action_ideas, list) else 'invalid'}",
    )

    # AC-2.9
    pii_hits = _scan_pii_in_obj(signal)
    ac_2_9 = len(pii_hits) == 0
    results["AC-2.9: No PII in Processed Signal"] = (
        ac_2_9,
        "No PII detected." if ac_2_9 else f"PII hits: {pii_hits[:3]}",
    )

    logger.info("=== VERIFICATION RESULTS ===")
    all_passed = True
    for check, (status, detail) in results.items():
        status_str = "PASS" if status else "FAIL"
        logger.info("[%s] %s - %s", status_str, check, detail)
        if not status:
            all_passed = False
    logger.info("=============================")

    if all_passed:
        logger.info("VERIFICATION COMPLETED: ALL AUTOMATED CHECKS PASSED!")
    else:
        logger.error("VERIFICATION COMPLETED: SOME AUTOMATED CHECKS FAILED.")

    return all_passed


if __name__ == "__main__":
    run_verification()
