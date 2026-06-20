"""Phase 4 orchestrator: publish pulse note via MCP server."""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from phase4.mcp_client import McpClient, McpServerError, doc_url_from_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("publish")


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_week_of(pulse_text: str) -> str:
    match = re.search(r"Week of (\d{4}-\d{2}-\d{2})", pulse_text)
    if match:
        return match.group(1)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_run_log(run_id: str, started_at: str, steps: list, final_status: str) -> None:
    os.makedirs("data", exist_ok=True)
    log_path = "data/run_log.json"
    log_data = {
        "run_id": run_id,
        "phase": 4,
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

    logger.info("Starting Phase 4 run %s", run_id)

    config = load_config()
    mcp_url = config.get("mcp_server_url", "https://khyati-mcp-server.onrender.com")
    email_alias = config.get("email_alias", "")
    google_doc_id = config.get("google_doc_id") or os.environ.get("GOOGLE_DOC_ID", "")

    pulse_path = "data/weekly_pulse.md"
    if not os.path.exists(pulse_path):
        logger.error("Missing %s — run Phase 3 first", pulse_path)
        steps.append({"step": "load_pulse", "status": "failure", "error_message": "Missing weekly_pulse.md"})
        write_run_log(run_id, started_at, steps, "failure")
        return

    with open(pulse_path, "r", encoding="utf-8") as f:
        pulse_text = f.read().strip()

    if not google_doc_id:
        logger.error(
            "google_doc_id not set in config.yaml (or GOOGLE_DOC_ID env). "
            "Create a Google Doc and paste its ID into config."
        )
        steps.append(
            {
                "step": "validate_config",
                "status": "failure",
                "error_message": "Missing google_doc_id",
            }
        )
        write_run_log(run_id, started_at, steps, "failure")
        return

    if not email_alias:
        logger.error("email_alias not set in config.yaml")
        steps.append({"step": "validate_config", "status": "failure", "error_message": "Missing email_alias"})
        write_run_log(run_id, started_at, steps, "failure")
        return

    client = McpClient(mcp_url)

    # Health check
    try:
        health = client.health_check()
        tools = client.list_tools()
        tool_names = {t.get("name") for t in tools}
        required = {"append_to_doc", "create_email_draft"}
        if not required.issubset(tool_names):
            raise McpServerError(f"Missing tools on MCP server. Found: {tool_names}")
        steps.append(
            {
                "step": "mcp_health_check",
                "status": "success",
                "output_summary": f"Server reachable: {health.get('message', 'ok')}",
            }
        )
    except Exception as err:
        logger.error("MCP health check failed: %s", err)
        steps.append({"step": "mcp_health_check", "status": "failure", "error_message": str(err)})
        write_run_log(run_id, started_at, steps, "failure")
        return

    week_of = extract_week_of(pulse_text)
    doc_url = doc_url_from_id(google_doc_id)

    # Append pulse to Google Doc
    doc_header = f"\n\n---\n## Groww Weekly Pulse — Week of {week_of}\n"
    doc_content = doc_header + pulse_text

    try:
        doc_result = client.append_to_doc(google_doc_id, doc_content)
        logger.info("Appended pulse to Google Doc %s", google_doc_id)
        steps.append(
            {
                "step": "append_to_doc",
                "status": "success",
                "output_summary": doc_result.get("message", "Content appended"),
            }
        )
    except Exception as err:
        logger.error("append_to_doc failed: %s", err)
        steps.append({"step": "append_to_doc", "status": "failure", "error_message": str(err)})
        write_run_log(run_id, started_at, steps, "failure")
        return

    # Create Gmail draft
    subject = f"[Groww Weekly Pulse] Week of {week_of}"
    email_body = (
        f"{pulse_text}\n\n"
        f"---\n"
        f"Full pulse document: {doc_url}\n"
    )

    try:
        draft_result = client.create_email_draft(email_alias, subject, email_body)
        draft_id = draft_result.get("draft_id", "")
        if not draft_id:
            raise McpServerError(f"No draft_id in response: {draft_result}")
        logger.info("Gmail draft created: %s", draft_id)
        steps.append(
            {
                "step": "create_email_draft",
                "status": "success",
                "output_summary": f"Draft ID: {draft_id}",
            }
        )
    except Exception as err:
        logger.error("create_email_draft failed: %s", err)
        steps.append({"step": "create_email_draft", "status": "failure", "error_message": str(err)})
        write_run_log(run_id, started_at, steps, "failure")
        return

    week_id = datetime.now(timezone.utc).strftime("%G-W%V")
    output_links = {
        "week": week_id,
        "week_of": week_of,
        "doc_id": google_doc_id,
        "doc_url": doc_url,
        "draft_id": draft_id,
        "email_to": email_alias,
        "email_subject": subject,
        "mcp_server_url": mcp_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pulse_source": pulse_path,
        "content_appended_chars": len(doc_content),
    }

    os.makedirs("data", exist_ok=True)
    output_path = "data/output_links.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_links, f, indent=2)

    logger.info("Phase 4 complete. Saved %s", output_path)
    logger.info("Doc URL: %s", doc_url)
    logger.info("Draft ID: %s", draft_id)

    steps.append({"step": "save_output_links", "status": "success", "output_summary": f"Wrote {output_path}"})
    write_run_log(run_id, started_at, steps, "success")


if __name__ == "__main__":
    main()
