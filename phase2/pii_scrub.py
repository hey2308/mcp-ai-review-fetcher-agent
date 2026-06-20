"""Regex-based PII scrub for review text fields."""

import re

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
PHONE_PATTERN = re.compile(
    r"(?:\+91[\-\s]?)?[6-9]\d{9}\b|\b\d{10,}\b"
)
ACCOUNT_PATTERN = re.compile(r"\b\d{12,16}\b")


def scrub_text(text: str) -> tuple[str, bool]:
    """Replace PII matches with [REDACTED]. Returns (scrubbed_text, had_pii)."""
    had_pii = False
    for pattern in (EMAIL_PATTERN, PHONE_PATTERN, ACCOUNT_PATTERN):
        if pattern.search(text):
            had_pii = True
        text = pattern.sub("[REDACTED]", text)
    return text, had_pii


def scrub_review(review: dict) -> tuple[dict, bool]:
    """Scrub title and text on a review copy. Returns (review, had_pii)."""
    cleaned = dict(review)
    had_pii = False
    for field in ("title", "text"):
        if field in cleaned and cleaned[field]:
            cleaned[field], found = scrub_text(str(cleaned[field]))
            had_pii = had_pii or found
    return cleaned, had_pii
