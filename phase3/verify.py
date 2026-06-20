"""Automated verification for Phase 3 output."""

import json
import logging
import os
import re

import yaml

from phase3.assembler import count_words
from phase3.validator import (
    normalize_quote,
    scan_pii,
    validate_quotes_match_signal,
    validate_structure,
    validate_theme_names,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("verify")

BLOCKQUOTE = re.compile(r"^>\s*.+", re.MULTILINE)


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_verification() -> bool:
    logger.info("Starting automated verification for Phase 3 output...")

    note_path = "data/weekly_pulse.md"
    signal_path = "data/processed_signal.json"

    if not os.path.exists(note_path):
        logger.error("FAIL: Missing %s", note_path)
        return False
    if not os.path.exists(signal_path):
        logger.error("FAIL: Missing %s", signal_path)
        return False

    with open(note_path, "r", encoding="utf-8") as f:
        note = f.read()
    with open(signal_path, "r", encoding="utf-8") as f:
        signal = json.load(f)

    config = load_config()
    max_words = int(config.get("max_words", 250))
    featured = [t for t in signal.get("themes", []) if t.get("featured")]
    quotes = signal.get("quotes", [])

    results: dict[str, tuple[bool, str]] = {}

    wc = count_words(note)
    results["AC-3.1: Word Count Compliance"] = (
        wc <= max_words,
        f"{wc} words (limit {max_words})",
    )

    ok, msg = validate_structure(note)
    results["AC-3.2: Section Presence"] = (ok, msg if ok else msg)

    theme_count = len(re.findall(r"^\d+\.\s+\*\*.+\*\*", note, re.MULTILINE))
    results["AC-3.3: Theme Count (3)"] = (
        theme_count == 3,
        f"Found {theme_count} themes",
    )

    quote_count = len(BLOCKQUOTE.findall(note))
    results["AC-3.4: Quote Count (3)"] = (
        quote_count == 3,
        f"Found {quote_count} blockquotes",
    )

    actions_section = note.split("### Action Ideas")[-1] if "### Action Ideas" in note else ""
    action_count = len(re.findall(r"^\d+\.\s+.+", actions_section, re.MULTILINE))
    results["AC-3.5: Action Ideas Count (3)"] = (
        action_count == 3,
        f"Found {action_count} actions",
    )

    ok, msg = validate_quotes_match_signal(note, quotes)
    results["AC-3.6: Quotes Match Processed Signal"] = (ok, msg)

    pii_hits = scan_pii(note)
    results["AC-3.7: PII Scan on Note Text"] = (
        len(pii_hits) == 0,
        "No PII." if not pii_hits else f"PII hits: {pii_hits[:3]}",
    )

    ok, msg = validate_theme_names(note, featured)
    results["AC-3.8: Theme Names Match Processed Signal"] = (ok, msg)

    file_ok = os.path.exists(note_path) and os.path.getsize(note_path) > 0
    results["AC-3.9: Output File Exists and Non-Empty"] = (
        file_ok,
        "File present." if file_ok else "Missing or empty file",
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
