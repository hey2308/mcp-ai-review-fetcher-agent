"""Phase 5 agent orchestrator — sequential tool-calling pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from phase5.config import ConfigError, load_config, validate_config
from phase5.prompt import SYSTEM_PROMPT, TOOL_SEQUENCE
from phase5.run_log import RunLogger
from phase5.tools import TOOL_HANDLERS, PipelineContext, ToolError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("phase5.orchestrator")

PUBLISH_STEPS = {"create_google_doc", "create_gmail_draft", "write_output_links"}


class AgentOrchestrator:
    """Runs the pipeline as a deterministic sequential tool loop."""

    def __init__(self, config: dict, *, offline: bool = False) -> None:
        self.config = config
        self.offline = offline
        self.ctx = PipelineContext(config=config, offline=offline)
        self.run_log = RunLogger(config)

    def run(self, steps: list[str] | None = None) -> int:
        sequence = steps or TOOL_SEQUENCE
        logger.info("Groww Weekly Pulse agent starting (run_id=%s)", self.run_log.run_id)
        logger.debug("System prompt loaded (%d chars)", len(SYSTEM_PROMPT))

        for step_name in sequence:
            handler = TOOL_HANDLERS[step_name]
            self.run_log.start_step(step_name)
            logger.info("Running tool: %s", step_name)
            try:
                summary = handler(self.ctx)
                self.run_log.complete_step(step_name, summary)
                logger.info("  ✓ %s", summary)
            except ToolError as err:
                logger.error("Tool %s failed: %s", step_name, err)
                self.run_log.fail_step(step_name, str(err))
                return 1
            except Exception as err:
                logger.error("Tool %s failed unexpectedly: %s", step_name, err)
                self.run_log.fail_step(step_name, str(err))
                return 1

        outputs = {"doc_url": self.ctx.doc_url, "draft_id": self.ctx.draft_id}
        if self.offline or (steps and not PUBLISH_STEPS.intersection(steps)):
            outputs = {"dry_run": self.offline, "skip_publish": bool(steps)}

        self.run_log.finalize(final_status="success", outputs=outputs)
        logger.info("Pipeline completed successfully.")
        if self.ctx.doc_url:
            logger.info("Doc URL: %s", self.ctx.doc_url)
        if self.ctx.draft_id:
            logger.info("Draft ID: %s", self.ctx.draft_id)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5: Run the full Groww Weekly Pulse agent pipeline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Offline keyword fallback; skip Groq and MCP publish",
    )
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="Run through validate_note only (skip Google Doc and Gmail)",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config()
        validate_config(config, offline=args.dry_run, skip_publish=args.skip_publish)
    except ConfigError as err:
        logger.error("Configuration error: %s", err)
        return 1

    if args.dry_run:
        logger.warning("DRY RUN mode — Groq calls use keyword fallback; MCP publish skipped")
        steps = [s for s in TOOL_SEQUENCE if s not in PUBLISH_STEPS]
        return AgentOrchestrator(config, offline=True).run(steps)

    if args.skip_publish:
        steps = [s for s in TOOL_SEQUENCE if s not in PUBLISH_STEPS]
        return AgentOrchestrator(config, offline=False).run(steps)

    return AgentOrchestrator(config, offline=False).run()


if __name__ == "__main__":
    sys.exit(main())
