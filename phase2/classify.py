"""Batched Groq theme classification and sentiment adjustment."""

import json
import logging

from phase2.groq_client import GroqClient
from phase2.sentiment import final_sentiment, truncate_words
from phase2.themes import THEMES, THEME_DESCRIPTIONS

logger = logging.getLogger(__name__)

CLASSIFY_SYSTEM = """You classify mobile app reviews into exactly one predefined theme.
Return valid JSON only with this shape:
{"results": [{"review_id": "...", "theme": "...", "sentiment_adjustment": 0.0}]}
Rules:
- theme must be one of the allowed themes exactly as written
- sentiment_adjustment is a float in [-0.2, 0.2]
- one result per review_id in the input
- never use Other or Unknown labels"""


def _theme_block() -> str:
    lines = []
    for theme in THEMES:
        lines.append(f"- {theme}: {THEME_DESCRIPTIONS[theme]}")
    return "\n".join(lines)


def classify_batch(
    client: GroqClient,
    reviews: list[dict],
    text_max_words: int,
) -> list[dict]:
    """Classify a batch of reviews via one Groq call."""
    payload = []
    for review in reviews:
        combined = f"{review.get('title', '')} {review.get('text', '')}".strip()
        payload.append(
            {
                "review_id": review["id"],
                "rating": review["rating"],
                "text": truncate_words(combined, text_max_words),
            }
        )

    user_prompt = (
        f"Allowed themes:\n{_theme_block()}\n\n"
        f"Classify each review:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    response = client.chat_json(CLASSIFY_SYSTEM, user_prompt, retries=1)
    results = response.get("results", response) if isinstance(response, dict) else response
    if not isinstance(results, list):
        raise RuntimeError(f"Unexpected classification response: {response}")

    by_id = {r["id"]: r for r in reviews}
    classified = []
    for item in results:
        review_id = str(item.get("review_id", ""))
        theme = item.get("theme", "")
        if theme not in THEMES:
            raise RuntimeError(
                f"Invalid theme '{theme}' for review {review_id}"
            )
        review = by_id.get(review_id)
        if not review:
            continue
        adjustment = float(item.get("sentiment_adjustment", 0.0))
        classified.append(
            {
                "review_id": review_id,
                "theme": theme,
                "sentiment_score": final_sentiment(review["rating"], adjustment),
                "source": "groq",
            }
        )

    if len(classified) != len(reviews):
        missing = {r["id"] for r in reviews} - {c["review_id"] for c in classified}
        raise RuntimeError(f"Classification missing review IDs: {missing}")

    return classified
