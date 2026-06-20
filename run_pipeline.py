#!/usr/bin/env python3
"""Run the full Groww Weekly Pulse pipeline (Phase 5 agent orchestrator + verification)."""

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Groww Weekly Pulse — full pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Offline mode: keyword fallback, no Groq/MCP publish",
    )
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="Run through note validation only (no Google Doc / Gmail)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip post-run verification",
    )
    args = parser.parse_args()

    orch_cmd = [sys.executable, "-m", "phase5.orchestrator"]
    if args.dry_run:
        orch_cmd.append("--dry-run")
    elif args.skip_publish:
        orch_cmd.append("--skip-publish")

    print("=" * 60)
    print("Groww Weekly Pulse — Phase 5 Agent Pipeline")
    print("=" * 60)

    result = subprocess.run(orch_cmd, check=False)
    if result.returncode != 0:
        print("\nPipeline FAILED.", file=sys.stderr)
        return result.returncode

    if args.no_verify:
        print("\nPipeline completed (verification skipped).")
        return 0

    verify_cmd = [sys.executable, "-m", "phase5.verify"]
    if args.dry_run or args.skip_publish:
        verify_cmd.append("--no-publish")

    print("\n" + "=" * 60)
    print("Running Phase 5 verification...")
    print("=" * 60)

    verify_result = subprocess.run(verify_cmd, check=False)
    if verify_result.returncode != 0:
        print("\nVerification FAILED.", file=sys.stderr)
        return verify_result.returncode

    print("\nPipeline and verification completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
