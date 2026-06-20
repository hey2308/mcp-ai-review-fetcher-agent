"""Structured execution logging for the Phase 5 pipeline."""

import json
import os
import uuid
from datetime import datetime, timezone


class RunLogger:
    """Writes progressive step entries to data/run_log.json."""

    LOG_PATH = "data/run_log.json"

    def __init__(self, config: dict) -> None:
        self.run_id = str(uuid.uuid4())
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.config_snapshot = {
            key: config.get(key)
            for key in [
                "review_window_weeks",
                "max_themes",
                "pulse_themes_displayed",
                "max_words",
                "email_alias",
                "mcp_server_url",
                "llm_provider",
                "llm_model",
                "max_reviews_to_process",
            ]
        }
        self.steps: list[dict] = []
        self.outputs: dict = {}

    def start_step(self, step: str) -> dict:
        entry = {
            "step": step,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.steps.append(entry)
        return entry

    def complete_step(self, step: str, output_summary: str) -> None:
        entry = self._find_step(step)
        entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        entry["status"] = "success"
        entry["output_summary"] = output_summary
        self._flush()

    def fail_step(self, step: str, error_message: str) -> None:
        entry = self._find_step(step)
        entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        entry["status"] = "failure"
        entry["error_message"] = error_message
        self._flush(final_status="failure")

    def finalize(self, final_status: str = "success", outputs: dict | None = None) -> None:
        if outputs:
            self.outputs = outputs
        self._flush(final_status=final_status)

    def _find_step(self, step: str) -> dict:
        for entry in reversed(self.steps):
            if entry["step"] == step:
                return entry
        raise KeyError(f"Step not found in log: {step}")

    def _flush(self, final_status: str | None = None) -> None:
        os.makedirs("data", exist_ok=True)
        log_data: dict = {
            "run_id": self.run_id,
            "phase": 5,
            "started_at": self.started_at,
            "config": self.config_snapshot,
            "steps": self.steps,
        }
        if final_status:
            log_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            log_data["final_status"] = final_status
            if self.outputs:
                log_data["outputs"] = self.outputs
        with open(self.LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)
