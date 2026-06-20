"""Phase 3 orchestrator: assemble and save weekly pulse note."""

import argparse
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from phase3.assembler import assemble_note, count_words
from phase3.validator import (
    scan_pii,
    validate_quotes_match_signal,
    validate_structure,
    validate_theme_names,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("generate")


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_reviews_for_signal(signal: dict, reviews_path: str = "data/reviews_raw.json") -> list[dict]:
    with open(reviews_path, "r", encoding="utf-8") as f:
        all_reviews = json.load(f)
    classified_ids = {c["review_id"] for c in signal.get("classifications", [])}
    matched = [r for r in all_reviews if r["id"] in classified_ids]
    return matched if matched else all_reviews


def write_run_log(run_id: str, started_at: str, steps: list, final_status: str) -> None:
    os.makedirs("data", exist_ok=True)
    log_path = "data/run_log.json"
    log_data = {
        "run_id": run_id,
        "phase": 3,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "final_status": final_status,
        "steps": steps,
    }
    runs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                runs = json.load(f)
                if isinstance(runs, dict):
                    runs = [runs]
        except Exception:
            runs = []
    runs.append(log_data)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2)


def main() -> None:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    steps: list[dict] = []

    logger.info("Starting Phase 3 run %s", run_id)

    signal_path = "data/processed_signal.json"
    if not os.path.exists(signal_path):
        logger.error("Missing %s — run Phase 2 first", signal_path)
        steps.append({"step": "load_signal", "status": "failure", "error_message": "Missing processed_signal.json"})
        write_run_log(run_id, started_at, steps, "failure")
        return

    config = load_config()
    max_words = int(config.get("max_words", 250))

    with open(signal_path, "r", encoding="utf-8") as f:
        signal = json.load(f)

    steps.append({"step": "load_signal", "status": "success", "output_summary": f"Loaded {signal_path}"})

    reviews = load_reviews_for_signal(signal)
    steps.append(
        {
            "step": "load_reviews",
            "status": "success",
            "output_summary": f"Loaded {len(reviews)} reviews for period metadata",
        }
    )

    note = assemble_note(signal, reviews, max_words=max_words)
    word_count = count_words(note)
    logger.info("Assembled note: %d words (limit %d)", word_count, max_words)
    steps.append(
        {
            "step": "assemble_note",
            "status": "success",
            "output_summary": f"Note assembled with {word_count} words",
        }
    )

    ok, msg = validate_structure(note)
    if not ok:
        logger.error("Structure validation failed: %s", msg)
        steps.append({"step": "validate_structure", "status": "failure", "error_message": msg})
        write_run_log(run_id, started_at, steps, "failure")
        return
    steps.append({"step": "validate_structure", "status": "success", "output_summary": msg})

    featured = [t for t in signal.get("themes", []) if t.get("featured")]
    ok, msg = validate_theme_names(note, featured)
    if not ok:
        logger.error("Theme name validation failed: %s", msg)
        steps.append({"step": "validate_themes", "status": "failure", "error_message": msg})
        write_run_log(run_id, started_at, steps, "failure")
        return
    steps.append({"step": "validate_themes", "status": "success", "output_summary": msg})

    ok, msg = validate_quotes_match_signal(note, signal.get("quotes", []))
    if not ok:
        logger.error("Quote validation failed: %s", msg)
        steps.append({"step": "validate_quotes", "status": "failure", "error_message": msg})
        write_run_log(run_id, started_at, steps, "failure")
        return
    steps.append({"step": "validate_quotes", "status": "success", "output_summary": msg})

    if word_count > max_words:
        logger.error("Word count %d exceeds limit %d", word_count, max_words)
        steps.append(
            {
                "step": "validate_word_count",
                "status": "failure",
                "error_message": f"{word_count} words exceeds {max_words}",
            }
        )
        write_run_log(run_id, started_at, steps, "failure")
        return
    steps.append(
        {
            "step": "validate_word_count",
            "status": "success",
            "output_summary": f"{word_count} words within limit",
        }
    )

    pii_hits = scan_pii(note)
    if pii_hits:
        logger.error("PII detected in note: %s", pii_hits[:3])
        steps.append({"step": "pii_scan", "status": "failure", "error_message": f"PII found: {pii_hits[:3]}"})
        write_run_log(run_id, started_at, steps, "failure")
        return
    steps.append({"step": "pii_scan", "status": "success", "output_summary": "No PII detected"})

    os.makedirs("data", exist_ok=True)
    output_path = "data/weekly_pulse.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(note)

    logger.info("Phase 3 complete. Saved %s (%d words)", output_path, word_count)
    steps.append({"step": "save_output", "status": "success", "output_summary": f"Wrote {output_path}"})
    write_run_log(run_id, started_at, steps, "success")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 3: Pulse note generation")
    parser.parse_args()
    main()
