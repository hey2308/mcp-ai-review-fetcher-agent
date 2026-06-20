# Phase 1 Evaluation — Review Ingestion

## Purpose

This document defines how to verify that the Review Ingestion phase is complete and correct. It covers what to test, how to test it, and what "pass" means for each check. The phase is not considered done until every check listed here is resolved.

---

## What This Phase Must Deliver

- A clean, deduplicated, PII-free dataset of recent public Groww reviews from both the Apple App Store and Google Play Store
- All reviews within the configured 8–12 week time window
- Consistent schema across all records
- A console/log summary of ingestion results

---

## Automated Checks

These checks can and should be run programmatically against the output file `data/reviews_raw.json` immediately after each ingestion run.

---

### AC-1.1 — Minimum Review Volume

**What it checks**: That the dataset contains a meaningful number of reviews for analysis.

**Condition**: Total review count ≥ 100 (combined across both stores)

**Why this matters**: Theme clustering and ranking loses statistical significance below ~100 reviews. If fewer than 100 are returned, the weekly note may be unrepresentative.

**Failure action**: If count is between 50–99, widen the time window toward 12 weeks and re-run. If count is still below 50, log a warning and surface it in the run log — do not silently proceed.

---

### AC-1.2 — Both Stores Represented

**What it checks**: That reviews were successfully fetched from both the App Store and Play Store (not just one source).

**Condition**: At least 1 record with `store = "app_store"` AND at least 1 record with `store = "play_store"` in the output

**Why this matters**: If one store's ingestion failed silently, the analysis would be biased toward only one platform's user base.

**Failure action**: Identify which store failed and re-run ingestion for that store. Do not proceed to Phase 2 with a single-store dataset.

---

### AC-1.3 — All Records Have Required Fields

**What it checks**: That every record in the dataset conforms to the defined schema — no missing or null required fields.

**Condition**: Every record must have: `id` (non-empty string), `store` (enum value), `rating` (integer), `title` (non-empty string), `text` (non-empty string), `date` (valid ISO 8601 date)

**Why this matters**: Missing fields will cause downstream processing steps to fail or produce incorrect results.

**Failure action**: Log which records are malformed and how many. If > 5% of records are malformed, halt and investigate the parser. If < 5%, discard malformed records and proceed with a warning in the log.

---

### AC-1.4 — Rating Range Validity

**What it checks**: That all rating values are integers within the valid range for star ratings.

**Condition**: Every record's `rating` value is an integer in [1, 2, 3, 4, 5]

**Why this matters**: Ratings outside this range indicate a parsing error. Out-of-range values would corrupt sentiment scoring in Phase 2.

**Failure action**: Discard any record with an out-of-range rating; log the count of discarded records.

---

### AC-1.5 — Date Window Compliance

**What it checks**: That all reviews fall within the configured time window.

**Condition**: Every record's `date` field is within the last N weeks (where N is the configured `review_window_weeks` value from `config.yaml`)

**Boundary definition**: The window is calculated from the date the pipeline is run, not from a fixed calendar date.

**Why this matters**: Including reviews older than 12 weeks risks surfacing already-resolved issues as current concerns.

**Failure action**: Discard any out-of-window records. If more than 20% of fetched records are out of window, investigate whether the date parser is correctly reading the source timestamps.

---

### AC-1.6 — No PII Fields in Schema

**What it checks**: That no PII-carrying fields are present in any record.

**Condition**: None of the following keys exist on any record: `reviewer_name`, `user_id`, `device_model`, `os_version`, `author`, `username`, `email`

**Why this matters**: Structural PII must be removed at ingestion. If any PII field is present in the schema, it will be persisted to `reviews_raw.json` and potentially flow through to downstream artifacts.

**Failure action**: This is a hard failure. Do not save the output file. Fix the parser to exclude PII fields and re-run.

---

### AC-1.7 — No Duplicate Records

**What it checks**: That the deduplication step correctly removed all cross-store duplicates.

**Condition**: No two records in the dataset have the same hash of `(normalised_title + normalised_text)`

**Normalisation definition**: Lowercase, strip punctuation, collapse multiple whitespace characters to a single space.

**Why this matters**: Duplicate reviews inflate the count for certain themes, making them appear more prominent than they are.

**Failure action**: Run the deduplication step again. If duplicates persist, log the offending record pairs for investigation.

---

### AC-1.8 — Date Field is Parseable

**What it checks**: That all `date` values can be parsed as valid dates (not strings that happen to look like dates but contain errors).

**Condition**: Every `date` field parses successfully using ISO 8601 parsing without errors or exceptions

**Failure action**: Discard records with unparseable dates; log their count. If > 10% of records have unparseable dates, halt and investigate the date parser for that source.

---

## Manual Checks

These checks require human inspection and cannot be fully automated. They should be performed by a reviewer (ideally not the person who wrote the ingestion logic) on a sample of the output data.

---

### MC-1.1 — Content Authenticity Spot-Check

**What to do**: Open `data/reviews_raw.json` and read 10–15 randomly selected records.

**What to verify**:
- The `text` fields contain genuine, readable review content — not HTML, JSON fragments, error messages, or garbled encoding artifacts
- The reviews appear to be about the Groww app (they reference investing, stocks, mutual funds, or other Groww-specific product surfaces)
- The `title` fields, where present, make sense as review headlines

**Pass condition**: ≥ 90% of sampled records look like authentic Groww app reviews.

**Failure action**: If many records appear garbled or off-topic, the wrong app listing may have been scraped, or there is an encoding issue in the parser. Investigate before proceeding.

---

### MC-1.2 — PII Absence Spot-Check (Text Fields)

**What to do**: Read through the `title` and `text` fields of 20 randomly selected records looking for any personally identifiable information.

**What to verify**: No visible email addresses, phone numbers, full names, or account numbers in the review text.

**Pass condition**: No PII found in the sampled records.

**Failure action**: If PII is found in free-text fields, note the record IDs and ensure the Phase 2 secondary scrub is configured to catch this pattern. Consider whether the regex-based PII check in AC-1.6 needs to be extended to cover text field content (not just schema keys).

---

### MC-1.3 — Date Distribution Reasonableness

**What to do**: Look at the distribution of review dates across the dataset. A quick frequency count by week is sufficient.

**What to verify**:
- Reviews are spread across the configured time window (not all clustered in a single week)
- There is no suspicious gap (e.g., 0 reviews for 4 consecutive weeks) that might indicate a failed fetch for that period

**Pass condition**: Reviews are present across at least 6 of the 8–12 weeks in the window (gaps are acceptable for individual days, not for entire weeks).

**Failure action**: A large gap may indicate a partial fetch failure. Re-run ingestion and check if the gap persists.

---

### MC-1.4 — Store Balance Reasonableness

**What to do**: Count reviews by `store` field.

**What to verify**: Neither store accounts for more than 80% of the total dataset (a very unbalanced distribution could indicate one source is failing to return its full volume).

**Pass condition**: Both stores contribute a meaningful share (at least 20% each).

**Note**: Some imbalance is expected. Play Store may return more reviews than App Store or vice versa depending on user base distribution. This check is about detecting complete failures, not requiring exact equality.

**Failure action**: If one store contributes < 10%, investigate whether the ingestion for that store completed correctly.

---

### AC-1.9 — Minimum Review Length

**What it checks**: That very short, low-signal reviews are excluded at normalization time.

**Condition**: Every record's `text` field has at least 6 words.

**Why this matters**: Extremely short reviews add little context for downstream theme classification and quote extraction.

**Failure action**: Discard records with fewer than 6 words in `text`; log the discard count.

---

### AC-1.10 — Emoji-Free Review Content

**What it checks**: That normalized review content excludes emoji-bearing text.

**Condition**: No record contains emoji characters in `title` or `text`.

**Why this matters**: Emoji-heavy reviews reduce consistency in text normalization and can add noise to later clustering/summarization.

**Failure action**: Discard records containing emoji; log the discard count.

---

### AC-1.11 — English-Only Review Content

**What it checks**: That only English-language reviews are retained for this pipeline.

**Condition**: Every record's `title` and `text` pass the English-only filter used by ingestion.

**Why this matters**: The current theme taxonomy and prompt instructions are tuned for English analysis quality and consistency.

**Failure action**: Discard non-English records; log the discard count.

---

## Exit Gate

**Phase 1 is complete when:**

| Gate | Requirement |
|---|---|
| All 11 automated checks | Pass (or documented exception with < threshold failures) |
| All 4 manual checks | Pass |
| `data/reviews_raw.json` | Exists, readable, non-empty |
| Run log | Contains Phase 1 summary entry |

> **Do not proceed to Phase 2 until this gate is cleared.**
