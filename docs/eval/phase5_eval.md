# Phase 5 Evaluation — Agent Orchestration & End-to-End

## Purpose

This document defines how to verify that the Agent Orchestration phase is complete and that the full pipeline works correctly as an integrated system. Phase 5 is the final gate: it validates not just individual components (covered in Phases 1–4) but the entire system's coherence, reliability, and usability when run end-to-end.

---

## What This Phase Must Deliver

- A single-command trigger that runs the entire pipeline from raw review fetch to Google Doc + Gmail Draft
- All Phase 1–4 outputs produced correctly within a single run
- A structured execution log (`data/run_log.json`) covering all steps
- Correct behaviour when the pipeline is run on different days (different outputs, not cached)
- Sufficient documentation for a new developer to set up and run the pipeline independently

---

## Automated Checks

These checks validate the system-level behaviour of the pipeline and are run after a full end-to-end run completes.

---

### AC-5.1 — Pipeline Completes Without Manual Intervention

**What it checks**: That triggering the pipeline with a single command results in full completion without requiring the operator to provide any input, make any decision, or intervene at any step.

**Condition**: From trigger to completion, the pipeline runs autonomously. The operator does not type anything, click anything, or respond to any prompt during the run.

**Why this matters**: The value of an agent pipeline is automation. If it requires human intervention mid-run, it is not an agent — it is a semi-automated script.

**Failure action**: Identify which step required manual intervention and remove that dependency. Common causes: prompts asking for OAuth confirmation mid-run (should have been handled during MCP server setup), missing config values that require input at runtime (move all to `config.yaml`).

---

### AC-5.2 — Exit Code 0 on Success

**What it checks**: That the pipeline process exits with a standard success exit code when it completes without errors.

**Condition**: The pipeline process exits with code 0.

**Why this matters**: Exit code conventions allow the pipeline to be integrated into scripts, CI systems, or schedulers that check for success/failure.

**Failure action**: Ensure all exception handlers catch errors, log them, and exit with a non-zero code explicitly. Ensure successful completion always exits with 0 explicitly (not relying on default process termination).

---

### AC-5.3 — All Expected Output Files Exist After Run

**What it checks**: That all intermediate and final output artifacts are present after a successful run.

**Condition**: All of the following files exist after the run:
- `data/reviews_raw.json`
- `data/processed_signal.json`
- `data/weekly_pulse.md`
- `data/output_links.json`
- `data/run_log.json`

**Why this matters**: Missing output files indicate a step completed partially or silently failed.

**Failure action**: Identify which file is missing and trace back to the step that should have produced it. Check the run log for that step's status.

---

### AC-5.4 — Run Log Contains All Steps

**What it checks**: That the execution log records every step of the pipeline.

**Condition**: `data/run_log.json` contains an entry for each of the following steps:
- `fetch_app_store_reviews`
- `fetch_play_store_reviews`
- `merge_and_deduplicate`
- `scrub_and_validate`
- `classify_themes`
- `score_and_rank_themes`
- `extract_quotes`
- `generate_actions`
- `assemble_pulse_note`
- `validate_note`
- `create_google_doc`
- `create_gmail_draft`
- `write_output_links`

**Condition**: Every step entry has `"status": "success"`.

**Why this matters**: The run log is the audit trail. Incomplete logs make it impossible to diagnose failures. Steps with non-success status indicate silent failures.

**Failure action**: If a step is missing from the log, the logging call was not reached (the step failed before it could log). Trace back to the previous successful step and investigate the failure. If a step has `"status": "failure"`, investigate the error message in that log entry.

---

### AC-5.5 — All Phase 1 Checks Pass on Run Output

**What it checks**: That the `reviews_raw.json` produced in this end-to-end run passes all automated checks from `phase1_eval.md`.

**Condition**: All 8 automated checks from Phase 1 pass when applied to `reviews_raw.json` from this run.

**Why this matters**: An end-to-end run must produce quality output at every stage, not just at the final stage. Running Phase 1 checks again confirms the ingestion step works correctly in the integrated pipeline (not just in isolation).

**Failure action**: Re-run the Phase 1 automated checks in isolation to determine which check is failing. Fix the ingestion step and re-run the full pipeline.

---

### AC-5.6 — All Phase 2 Checks Pass on Run Output

**What it checks**: That the `processed_signal.json` produced in this run passes all automated checks from `phase2_eval.md`.

**Condition**: All 9 automated checks from Phase 2 pass when applied to `processed_signal.json` from this run.

**Failure action**: Same approach as AC-5.5 — run Phase 2 checks in isolation.

---

### AC-5.7 — All Phase 3 Checks Pass on Run Output

**What it checks**: That the `weekly_pulse.md` produced in this run passes all automated checks from `phase3_eval.md`.

**Condition**: All 9 automated checks from Phase 3 pass when applied to `weekly_pulse.md` from this run.

**Failure action**: Same approach as above.

---

### AC-5.8 — All Phase 4 Checks Pass on Run Output

**What it checks**: That the Google Doc and Gmail Draft produced in this run pass all automated checks from `phase4_eval.md`.

**Condition**: All 9 automated checks from Phase 4 pass, verified against the `output_links.json` from this run.

**Failure action**: Same approach as above.

---

### AC-5.9 — Pipeline Runtime Is Reasonable

**What it checks**: That the pipeline completes in a reasonable amount of time for a weekly batch process.

**Condition**: Total elapsed time from trigger to completion is < 10 minutes (as recorded in `run_log.json`'s `started_at` and `completed_at` fields).

**Why this matters**: A weekly pipeline that takes over 10 minutes for ~500 reviews suggests a performance problem (unbounded LLM calls, no rate limiting, excessive API round trips) that should be identified and addressed.

**Failure action**: Review the `run_log.json` step timings to identify which step is the bottleneck. Common causes: classifying reviews one-by-one instead of in batches, excessive retry loops, or slow MCP tool calls.

---

### AC-5.10 — Configuration Is the Sole Source of Runtime Parameters

**What it checks**: That changing a value in `config.yaml` (without changing any other file) correctly changes the pipeline's behaviour.

**How to test**:
1. Change `review_window_weeks` from 10 to 8 in `config.yaml`
2. Re-run the pipeline
3. Verify that `reviews_raw.json` contains only reviews from the last 8 weeks

**Condition**: The pipeline correctly uses the updated config value without any other changes.

**Why this matters**: If parameters are hardcoded in the pipeline logic, changing the config has no effect — which defeats the purpose of the config file and makes the pipeline inflexible.

**Failure action**: Audit all places in the pipeline where runtime parameters are used and ensure they are all read from `config.yaml` at runtime, not set as constants.

---

## Manual Checks

---

### MC-5.1 — Two Runs Produce Different Outputs

**What to do**: Run the pipeline once, record the output. Wait 24 hours (or simulate a different week by adjusting the date window in config). Run the pipeline again.

**What to verify**:
- The two runs produce different `reviews_raw.json` files (different review sets or at least different date stamps)
- The two runs produce different `weekly_pulse.md` files (different themes, quotes, or actions reflecting the different review periods)
- Neither run produces a copy of the other's output (the pipeline is not caching or reusing stale data)

**Pass condition**: Both runs complete successfully and produce meaningfully different outputs.

**Failure action**: If both runs produce identical outputs, investigate whether the pipeline is re-using cached intermediate files from the previous run instead of re-fetching and re-processing. Clear intermediate files between runs and re-test.

---

### MC-5.2 — New Developer Can Run the Pipeline from README Alone

**What to do**: Give the README to someone who has not been involved in building the pipeline (a colleague, peer, or mentor). Ask them to set up and run the pipeline using only the README as a guide. Observe any points where they get stuck or need to ask questions.

**What to verify**:
- They can set up the MCP server following the documented steps without additional help
- They can configure `config.yaml` correctly
- They can trigger the pipeline and produce a successful run
- They can locate the outputs (Google Doc URL, Gmail draft) without being told where to look

**Pass condition**: The new developer completes a full successful run using only the README, with zero clarifying questions to the original developer.

**Failure action**: Document every point where the new developer got stuck. Update the README to address those gaps. Re-test with the same or a different new developer until no clarifying questions are needed.

---

### MC-5.3 — Full Run Outputs Are Stakeholder-Ready

**What to do**: After a full pipeline run, review the complete set of outputs as if you are the product team receiving them.

**What to verify**:
- The Google Doc is well-formatted, readable, and correctly titled
- The Gmail draft is professionally worded and ready to send (would not need editing before sending)
- The pulse note accurately represents the current week's review signal
- The action ideas are genuinely useful to a product team

**Pass condition**: The outputs are of stakeholder-ready quality — they could be shared with a product manager or leadership without further editing.

**Failure action**: If any output is not stakeholder-ready, identify the specific quality issue (formatting, content accuracy, tone) and trace it back to the phase responsible. Fix the generating step and re-run.

---

### MC-5.4 — Error Handling Produces Clear Messages

**What to do**: Simulate two types of failure:
1. Stop the MCP server before the pipeline reaches Phase 4 and trigger a full run
2. Provide an invalid LLM API key in the config and trigger a full run

**What to verify**:
- In both cases, the pipeline fails with a clear, specific error message identifying what went wrong (not a generic Python traceback or an opaque error code)
- The pipeline fails at the correct step (not 3 steps later)
- The run log records the failure with the error message and the step at which it occurred
- The pipeline does not partially complete and leave inconsistent output files from a failed run

**Pass condition**: Both simulated failures produce clear error messages, fail at the expected step, and leave the system in a clean state.

**Failure action**: Improve error messages and error handling for the cases that produced confusing output.

---

### MC-5.5 — Pipeline Is Repeatable on the Same Day

**What to do**: Run the pipeline twice in the same day (within a few hours of each other).

**What to verify**:
- Both runs complete successfully
- The second run overwrites (or versions) the output files rather than failing due to file conflicts
- The two runs produce very similar (not necessarily identical) outputs, since the review dataset is the same within a short time period
- Two separate Google Docs are created (not one doc being edited twice)

**Pass condition**: Both runs complete without errors and produce independent outputs.

**Failure action**: If the second run fails due to file conflicts, add output file overwrite logic. If the second run creates a duplicate doc with the same name, consider adding a unique run ID or timestamp to the doc title.

---

## Exit Gate

**Phase 5 (and the project) is complete when:**

| Gate | Requirement |
|---|---|
| All 10 automated checks | Pass |
| All 5 manual checks | Pass |
| All Phase 1–4 exit gates | Satisfied within a single end-to-end run |
| `data/run_log.json` | All steps present with `"status": "success"` |
| Google Doc | Accessible, stakeholder-ready |
| Gmail draft | In Drafts, stakeholder-ready |
| README | Sufficient for a new developer to run independently |

> **The project is complete when this exit gate is fully cleared.**

---

## Final Project Checklist

Before declaring the project complete, confirm all of the following:

- [ ] Phase 1 exit gate cleared
- [ ] Phase 2 exit gate cleared
- [ ] Phase 3 exit gate cleared
- [ ] Phase 4 exit gate cleared
- [ ] Phase 5 exit gate cleared
- [ ] `decision.md` updated with any decisions made during Phase 5
- [ ] README written and tested with a new developer
- [ ] All output files present and verified
- [ ] No PII found in any output artifact
- [ ] MCP server confirmed as the only path to Google Workspace (no direct API calls)
