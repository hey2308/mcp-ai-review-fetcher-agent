"""Sentiment scoring utilities."""

import re


def rating_to_base_sentiment(rating: int) -> float:
    """Map 1-5 star rating to [-1.0, +1.0] linear scale."""
    rating = max(1, min(5, int(rating)))
    return (rating - 3) / 2.0


def clamp_sentiment(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def final_sentiment(rating: int, adjustment: float) -> float:
    adjustment = max(-0.2, min(0.2, float(adjustment)))
    return clamp_sentiment(rating_to_base_sentiment(rating) + adjustment)


def truncate_words(text: str, max_words: int) -> str:
    words = re.findall(r"\S+", text)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])
