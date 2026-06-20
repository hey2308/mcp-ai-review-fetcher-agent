"""Automated verification for Phase 5 end-to-end pipeline."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

from phase1.verify import run_verification as verify_phase1
from phase2.verify import run_verification as verify_phase2
from phase3.verify import run_verification as verify_phase3
from phase4.verify import run_verification as verify_phase4
from phase5.prompt import TOOL_SEQUENCE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("phase5.verify")

REQUIRED_OUTPUT_FILES = [
    "data/reviews_raw.json",
    "data/processed_signal.json",
    "data/weekly_pulse.md",
    "data/run_log.json",
]

PUBLISH_OUTPUT_FILES = [
    "data/output_links.json",
]


def load_run_log(path: str = "data/run_log.json") -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data[-1] if data else None
    return data


def run_verification(*, require_publish: bool = True) -> bool:
    logger.info("Starting Phase 5 end-to-end verification...")
    results: dict[str, tuple[bool, str]] = {}

    # AC-5.3 — output files exist
    required = REQUIRED_OUTPUT_FILES + (PUBLISH_OUTPUT_FILES if require_publish else [])
    missing = [p for p in required if not os.path.exists(p)]
    ac_5_3 = len(missing) == 0
    results["AC-5.3: All Expected Output Files Exist"] = (
        ac_5_3,
        "All present." if ac_5_3 else f"Missing: {missing}",
    )

    run_log = load_run_log()
    if not run_log:
        results["AC-5.4: Run Log Contains All Steps"] = (False, "run_log.json missing or empty")
    else:
        logged_steps = {s.get("step") for s in run_log.get("steps", [])}
        expected = set(TOOL_SEQUENCE) if require_publish else set(TOOL_SEQUENCE) - {
            "create_google_doc",
            "create_gmail_draft",
            "write_output_links",
        }
        missing_steps = expected - logged_steps
        failed_steps = [
            s["step"]
            for s in run_log.get("steps", [])
            if s.get("step") in expected and s.get("status") != "success"
        ]
        ac_5_4 = not missing_steps and not failed_steps
        detail = "All steps succeeded."
        if missing_steps:
            detail = f"Missing steps: {sorted(missing_steps)}"
        elif failed_steps:
            detail = f"Failed steps: {failed_steps}"
        results["AC-5.4: Run Log Contains All Steps"] = (ac_5_4, detail)

        # AC-5.9 — runtime under 10 minutes
        started = run_log.get("started_at")
        completed = run_log.get("completed_at")
        ac_5_9 = False
        if started and completed:
            start_dt = datetime.fromisoformat(started)
            end_dt = datetime.fromisoformat(completed)
            elapsed = (end_dt - start_dt).total_seconds()
            ac_5_9 = elapsed < 600
            results["AC-5.9: Pipeline Runtime Is Reasonable"] = (
                ac_5_9,
                f"Elapsed {elapsed:.1f}s ({'under' if ac_5_9 else 'over'} 10 min limit)",
            )
        else:
            results["AC-5.9: Pipeline Runtime Is Reasonable"] = (
                False,
                "started_at/completed_at missing from run_log",
            )

        # AC-5.10 — config snapshot in run log
        config_in_log = run_log.get("config", {})
        ac_5_10 = bool(config_in_log.get("review_window_weeks"))
        results["AC-5.10: Configuration Snapshot in Run Log"] = (
            ac_5_10,
            f"review_window_weeks={config_in_log.get('review_window_weeks')}",
        )

        final_status = run_log.get("final_status") == "success"
        results["AC-5.2: Exit Status Recorded as Success"] = (
            final_status,
            run_log.get("final_status", "unknown"),
        )

    # AC-5.5 through AC-5.8 — delegate to phase verifiers
    if ac_5_3 and os.path.exists("data/reviews_raw.json"):
        results["AC-5.5: Phase 1 Checks Pass"] = (
            verify_phase1(),
            "See phase1 verify output above",
        )
    else:
        results["AC-5.5: Phase 1 Checks Pass"] = (False, "Skipped — reviews_raw.json missing")

    if ac_5_3 and os.path.exists("data/processed_signal.json"):
        results["AC-5.6: Phase 2 Checks Pass"] = (
            verify_phase2(),
            "See phase2 verify output above",
        )
    else:
        results["AC-5.6: Phase 2 Checks Pass"] = (False, "Skipped — processed_signal.json missing")

    if ac_5_3 and os.path.exists("data/weekly_pulse.md"):
        results["AC-5.7: Phase 3 Checks Pass"] = (
            verify_phase3(),
            "See phase3 verify output above",
        )
    else:
        results["AC-5.7: Phase 3 Checks Pass"] = (False, "Skipped — weekly_pulse.md missing")

    if require_publish and ac_5_3 and os.path.exists("data/output_links.json"):
        results["AC-5.8: Phase 4 Checks Pass"] = (
            verify_phase4(),
            "See phase4 verify output above",
        )
    elif require_publish:
        results["AC-5.8: Phase 4 Checks Pass"] = (False, "Skipped — output_links.json missing")
    else:
        results["AC-5.8: Phase 4 Checks Pass"] = (True, "Skipped — publish not required")

    return _log_results(results)


def _log_results(results: dict[str, tuple[bool, str]]) -> bool:
    logger.info("=== PHASE 5 VERIFICATION RESULTS ===")
    all_passed = True
    for check, (status, detail) in results.items():
        status_str = "PASS" if status else "FAIL"
        logger.info("[%s] %s — %s", status_str, check, detail)
        if not status:
            all_passed = False
    logger.info("====================================")
    if all_passed:
        logger.info("PHASE 5 VERIFICATION: ALL AUTOMATED CHECKS PASSED")
    else:
        logger.error("PHASE 5 VERIFICATION: SOME CHECKS FAILED")
    return all_passed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phase 5 verification")
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Skip Phase 4 output checks (for dry-run pipelines)",
    )
    args = parser.parse_args()
    ok = run_verification(require_publish=not args.no_publish)
    sys.exit(0 if ok else 1)
