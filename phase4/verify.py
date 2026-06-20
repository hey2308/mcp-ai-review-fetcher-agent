"""Automated verification for Phase 4 MCP integration output."""

import json
import logging
import os
import re
from pathlib import Path

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("verify")


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def grep_no_google_api_in_phase4() -> tuple[bool, str]:
    phase4_dir = Path(__file__).resolve().parent
    import_pattern = re.compile(r"^\s*(import|from)\s+google", re.MULTILINE)
    hits = []
    for py_file in phase4_dir.glob("*.py"):
        if py_file.name == "verify.py":
            continue
        text = py_file.read_text(encoding="utf-8")
        if import_pattern.search(text):
            hits.append(f"{py_file.name}: google import")
        if "googleapis.com" in text:
            hits.append(f"{py_file.name}: googleapis.com")
    return len(hits) == 0, "No direct Google API usage." if not hits else f"Found: {hits}"


def run_verification() -> bool:
    logger.info("Starting automated verification for Phase 4 output...")

    config = load_config()
    links_path = "data/output_links.json"
    pulse_path = "data/weekly_pulse.md"
    mcp_url = config.get("mcp_server_url", "https://khyati-mcp-server.onrender.com").rstrip("/")

    results: dict[str, tuple[bool, str]] = {}

    # AC-4.1
    try:
        r = requests.get(f"{mcp_url}/", timeout=30)
        tools_r = requests.get(f"{mcp_url}/tools", timeout=30)
        ac_4_1 = r.status_code == 200 and tools_r.status_code == 200
        results["AC-4.1: MCP Server Reachability"] = (
            ac_4_1,
            f"health={r.status_code}, tools={tools_r.status_code}",
        )
    except Exception as e:
        results["AC-4.1: MCP Server Reachability"] = (False, str(e))

    if not os.path.exists(links_path):
        for key in [
            "AC-4.2: Google Doc Append Success",
            "AC-4.5: Doc URL Recorded",
            "AC-4.6: Gmail Draft Creation Success",
            "AC-4.8: Draft ID Recorded",
        ]:
            results[key] = (False, "output_links.json missing — run phase4.publish first")
        results["AC-4.9: No Direct Google API Client Usage"] = grep_no_google_api_in_phase4()
        _log_results(results)
        return False

    with open(links_path, "r", encoding="utf-8") as f:
        links = json.load(f)

    doc_id = links.get("doc_id", "")
    doc_url = links.get("doc_url", "")
    draft_id = links.get("draft_id", "")

    # AC-4.2 — append success implied by output_links presence + doc_id
    ac_4_2 = bool(doc_id) and bool(doc_url)
    results["AC-4.2: Google Doc Append Success"] = (
        ac_4_2,
        f"doc_id={doc_id[:12]}..." if doc_id else "missing doc_id",
    )

    # AC-4.3 — title pattern in pulse note (server appends; title is in content)
    title_ok = False
    if os.path.exists(pulse_path):
        with open(pulse_path, "r", encoding="utf-8") as f:
            pulse = f.read()
        title_ok = bool(re.search(r"Groww Weekly Pulse — Week of \d{4}-\d{2}-\d{2}", pulse))
    results["AC-4.3: Pulse Title Pattern in Note"] = (
        title_ok,
        "Title pattern found in weekly_pulse.md" if title_ok else "Title pattern missing",
    )

    # AC-4.4 — content was sourced from weekly_pulse.md
    content_ok = links.get("pulse_source") == pulse_path and os.path.exists(pulse_path)
    if content_ok:
        with open(pulse_path, "r", encoding="utf-8") as f:
            pulse_len = len(f.read())
        appended = links.get("content_appended_chars", 0)
        content_ok = appended >= pulse_len
    results["AC-4.4: Doc Content Sourced from Pulse Note"] = (
        content_ok,
        f"appended_chars={links.get('content_appended_chars', 0)}",
    )

    # AC-4.5
    ac_4_5 = doc_url.startswith("https://docs.google.com/")
    results["AC-4.5: Doc URL Recorded"] = (ac_4_5, doc_url if ac_4_5 else f"Invalid URL: {doc_url}")

    # AC-4.6
    ac_4_6 = bool(draft_id)
    results["AC-4.6: Gmail Draft Creation Success"] = (ac_4_6, f"draft_id={draft_id}" if ac_4_6 else "missing")

    # AC-4.7
    expected_to = config.get("email_alias", "")
    actual_to = links.get("email_to", "")
    ac_4_7 = actual_to == expected_to
    results["AC-4.7: Gmail Draft Recipient Correct"] = (
        ac_4_7,
        f"to={actual_to}, expected={expected_to}",
    )

    # AC-4.8
    ac_4_8 = bool(draft_id)
    results["AC-4.8: Draft ID Recorded"] = (ac_4_8, "Present" if ac_4_8 else "Missing")

    # AC-4.9
    results["AC-4.9: No Direct Google API Client Usage"] = grep_no_google_api_in_phase4()

    return _log_results(results)


def _log_results(results: dict[str, tuple[bool, str]]) -> bool:
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
