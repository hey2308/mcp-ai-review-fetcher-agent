"""Action idea generation via a single Groq call."""

import json
import logging

from phase2.groq_client import GroqClient

logger = logging.getLogger(__name__)

ACTION_SYSTEM = """You generate product action ideas from app review themes.
Return valid JSON only:
{"action_ideas": ["...", "...", "..."]}
Rules:
- exactly 3 action ideas
- each must reference a specific Groww product surface or user flow
- each must be actionable by product/engineering teams
- no generic advice like 'improve UX'
- ground each idea in the provided theme evidence"""


def generate_action_ideas(
    client: GroqClient,
    featured_themes: list[dict],
    quotes: list[dict],
) -> list[str]:
    payload = []
    for theme_row in featured_themes:
        quote = next((q for q in quotes if q["theme"] == theme_row["name"]), None)
        payload.append(
            {
                "theme": theme_row["name"],
                "review_count": theme_row["review_count"],
                "average_sentiment": theme_row["average_sentiment"],
                "priority_score": theme_row["priority_score"],
                "quote": quote["quote"] if quote else "",
            }
        )

    user_prompt = f"Generate 3 action ideas from this evidence:\n{json.dumps(payload, ensure_ascii=False)}"
    response = client.chat_json(ACTION_SYSTEM, user_prompt, retries=1)
    ideas = response.get("action_ideas", [])
    if not isinstance(ideas, list) or len(ideas) < 3:
        raise RuntimeError(f"Expected 3 action ideas, got: {ideas}")
    return [str(i) for i in ideas[:3]]
