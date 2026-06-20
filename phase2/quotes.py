"""Quote selection via deterministic shortlist + Groq index pick."""

import json
import logging

from phase2.groq_client import GroqClient
from phase2.ranking import build_quote_candidates

logger = logging.getLogger(__name__)

QUOTE_SYSTEM = """You pick the best user quote index for a product pulse note.
Return valid JSON only: {"selected_index": 0}
Rules:
- choose the index (0-based) of the most specific, representative negative quote
- do not rewrite or invent text; only return an index present in the list"""


def select_quote_for_theme(
    client: GroqClient,
    theme: str,
    classifications: list[dict],
    reviews_by_id: dict[str, dict],
) -> dict | None:
    candidates = build_quote_candidates(theme, classifications, reviews_by_id)
    if not candidates:
        return None

    indexed = [
        {
            "index": i,
            "snippet": c["snippet"],
            "rating": c["rating"],
            "sentiment_score": c["sentiment_score"],
        }
        for i, c in enumerate(candidates)
    ]
    user_prompt = (
        f"Theme: {theme}\n"
        f"Candidates:\n{json.dumps(indexed, ensure_ascii=False)}\n"
        "Pick the best index."
    )

    try:
        response = client.chat_json(QUOTE_SYSTEM, user_prompt, retries=1)
        selected_index = int(response.get("selected_index", 0))
    except Exception as err:
        logger.warning(
            "Groq quote pick failed for theme '%s': %s; using deterministic fallback",
            theme,
            err,
        )
        selected_index = 0

    if selected_index < 0 or selected_index >= len(candidates):
        selected_index = 0

    chosen = candidates[selected_index]
    review = reviews_by_id[chosen["review_id"]]
    snippet = chosen["snippet"]
    if snippet not in review["text"]:
        snippet = review["text"][:200].strip()

    return {
        "theme": theme,
        "review_id": chosen["review_id"],
        "quote": snippet,
        "store": chosen["store"],
        "rating": chosen["rating"],
    }
