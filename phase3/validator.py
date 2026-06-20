"""Validation helpers for Phase 3 pulse note."""

import re

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)
PHONE_PATTERN = re.compile(r"\b\d{7,}\b")

SECTION_THEMES = re.compile(r"###\s*Top Themes", re.IGNORECASE)
SECTION_VOICES = re.compile(r"###\s*User Voices", re.IGNORECASE)
SECTION_ACTIONS = re.compile(r"###\s*Action Ideas", re.IGNORECASE)
THEME_ENTRY = re.compile(r"^\d+\.\s+\*\*.+\*\*", re.MULTILINE)
BLOCKQUOTE = re.compile(r"^>\s*.+", re.MULTILINE)
ACTION_ITEM = re.compile(r"^\d+\.\s+.+", re.MULTILINE)


def normalize_quote(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r'^"|"$', "", text)
    if " — " in text:
        text = text.split(" — ", 1)[0]
    return re.sub(r"\s+", " ", text).strip()


def validate_structure(note: str) -> tuple[bool, str]:
    if not SECTION_THEMES.search(note):
        return False, "Missing Top Themes section"
    if not SECTION_VOICES.search(note):
        return False, "Missing User Voices section"
    if not SECTION_ACTIONS.search(note):
        return False, "Missing Action Ideas section"

    theme_count = len(THEME_ENTRY.findall(note))
    if theme_count != 3:
        return False, f"Expected 3 theme entries, found {theme_count}"

    quote_count = len(BLOCKQUOTE.findall(note))
    if quote_count != 3:
        return False, f"Expected 3 blockquotes, found {quote_count}"

    actions_section = note.split("### Action Ideas")[-1]
    action_count = len(ACTION_ITEM.findall(actions_section))
    if action_count != 3:
        return False, f"Expected 3 action items, found {action_count}"

    return True, "Structure valid"


def validate_quotes_match_signal(note: str, signal_quotes: list[dict]) -> tuple[bool, str]:
    blockquotes = BLOCKQUOTE.findall(note)
    if len(blockquotes) != 3:
        return False, "Wrong blockquote count"

    signal_texts = {normalize_quote(q["quote"]) for q in signal_quotes}
    for bq in blockquotes:
        note_quote = normalize_quote(bq)
        if not any(note_quote == sq or note_quote in sq or sq in note_quote for sq in signal_texts):
            return False, f"Quote mismatch: {note_quote[:60]}..."
    return True, "Quotes match processed signal"


def validate_theme_names(note: str, featured_themes: list[dict]) -> tuple[bool, str]:
    featured_names = {t["name"].lower() for t in featured_themes if t.get("featured")}
    for name in featured_names:
        if name not in note.lower():
            return False, f"Featured theme not found in note: {name}"
    return True, "Theme names present"


def scan_pii(note: str) -> list[str]:
    hits = []
    for pattern in (EMAIL_PATTERN, PHONE_PATTERN):
        for match in pattern.finditer(note):
            hits.append(match.group())
    return hits
