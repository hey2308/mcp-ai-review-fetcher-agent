# Phase 2 Evaluation — Theme Clustering & Signal Extraction

## Purpose

This document defines how to verify that the Theme Clustering & Signal Extraction phase is complete and correct. It covers what to test, how to test it, and what "pass" means for each check. Phase 2 cannot be considered complete until every check listed here is resolved.

---

## What This Phase Must Deliver

- A secondary PII scrub pass applied to all review text fields
- Every review classified into exactly one of the five predefined Groww themes
- A sentiment score per review and aggregated per theme
- Five themes ranked by priority (volume × negative sentiment)
- Three verbatim quotes, one per top-3 theme, selected from source reviews
- Three actionable product improvement ideas grounded in the top themes
- All outputs saved as `data/processed_signal.json`

---

## Automated Checks

---

### AC-2.1 — Complete Classification Coverage

**What it checks**: That every review in the input dataset (`reviews_raw.json`) has been assigned a theme label in the output.

**Condition**: Record count in `processed_signal.json` theme assignments = record count in `reviews_raw.json`. No review is missing a theme label.

**Why this matters**: Unclassified reviews are invisible to the ranking and quote extraction steps. A meaningful fraction of unclassified reviews would skew theme proportions.

**Failure action**: Identify unclassified records and re-run classification for them. If the LLM consistently fails to classify a category of review, review the theme descriptions and adjust them.

---

### AC-2.2 — Valid Theme Labels Only

**What it checks**: That all assigned theme labels belong to the allowed set of five predefined themes.

**Condition**: Every theme label in the output is one of: `"Onboarding & Account Setup"`, `"KYC & Verification"`, `"Payments & Transactions"`, `"Portfolio & Statements"`, `"Performance & App Stability"`. No `"Other"`, `"Unknown"`, or free-form labels.

**Why this matters**: Invalid labels indicate the LLM deviated from the structured output schema, meaning those reviews are uncategorised and lost to the analysis.

**Failure action**: Re-run classification for records with invalid labels, reinforcing the structured output requirement in the prompt. If any label is `"Other"`, manually review those records and assign the closest valid theme.

---

### AC-2.3 — Sentiment Score Range

**What it checks**: That all sentiment scores are valid normalised values.

**Condition**: Every review's `sentiment_score` is a float in [−1.0, +1.0] (inclusive)

**Why this matters**: Out-of-range scores indicate a calculation or LLM response error and will corrupt theme ranking.

**Failure action**: Identify out-of-range scores, clamp them to [−1.0, +1.0], and log the correction. Investigate the source of the out-of-range value.

---

### AC-2.4 — Five Themes in Output

**What it checks**: That the output contains entries for all five themes (even if some have zero reviews).

**Condition**: `processed_signal.json` contains exactly 5 theme objects in its `themes` array, one for each predefined theme.

**Why this matters**: A missing theme entry means Phase 3 and any downstream trend analysis cannot check that theme's status for the current week.

**Failure action**: Add the missing theme entry with count = 0, avg_sentiment = 0.0, and no quotes. Log that the theme had no reviews in this period.

---

### AC-2.5 — Top-3 Themes Flagged

**What it checks**: That exactly three themes are marked as "featured" (i.e., to be surfaced in the pulse note).

**Condition**: Exactly 3 theme objects in `processed_signal.json` have `"featured": true`. These must be the 3 themes with the highest priority scores.

**Why this matters**: The pulse note generator depends on the featured flag to know which themes to include.

**Failure action**: Re-run the ranking and flagging step. Verify the priority score formula is being applied correctly.

---

### AC-2.6 — Exactly 3 Quotes Extracted

**What it checks**: That one verbatim quote has been selected for each of the top 3 themes.

**Condition**: The `quotes` array in `processed_signal.json` contains exactly 3 entries, one per featured theme.

**Why this matters**: The pulse note structure requires exactly 3 quotes. More or fewer would break the note assembly step.

**Failure action**: If a theme has no reviews, it cannot contribute a quote — re-examine whether that theme should be featured. Re-run quote extraction for any theme that is missing a quote.

---

### AC-2.7 — Quotes Are Verbatim Substrings

**What it checks**: That each selected quote is a literal substring of the source review's `text` field — not paraphrased or invented.

**Condition**: For each quote Q and its source review ID, Q (after whitespace normalisation) must be a substring of the `text` field of the record with that ID in `reviews_raw.json`.

**Why this matters**: Paraphrased quotes misrepresent what users actually said. The pulse note promises "real user quotes."

**Failure action**: If any quote fails this check, return to the quote extraction step and re-select a verbatim snippet for the affected theme.

---

### AC-2.8 — Exactly 3 Action Ideas Generated

**What it checks**: That the output contains exactly three action ideas.

**Condition**: The `action_ideas` array in `processed_signal.json` has exactly 3 string entries.

**Failure action**: Re-run action generation. If the LLM returns more than 3, keep the first 3. If fewer than 3, re-prompt.

---

### AC-2.9 — No PII in Processed Signal

**What it checks**: That the secondary PII scrub was effective and no PII remains in any field of `processed_signal.json`.

**Condition**: A PII regex scan over all string fields in `processed_signal.json` returns zero matches. PII patterns include: email addresses, phone numbers (7+ digit sequences), name-like capitalized word pairs adjacent to identifying context.

**Why this matters**: The processed signal flows directly into the pulse note. Any PII here will appear in the Google Doc and Gmail draft.

**Failure action**: Hard failure. Re-run the PII scrub, identify which records contained embedded PII, and investigate why the scrub missed them.

---

## Manual Checks

---

### MC-2.1 — Classification Quality Spot-Check

**What to do**: Take a random sample of 25 reviews from `reviews_raw.json` and manually verify their assigned theme label in `processed_signal.json`.

**What to verify**: The assigned theme label is the most appropriate one for each review's content.

**Pass condition**: ≥ 20 out of 25 (80%) are correctly labelled by human judgment.

**Failure action**: If accuracy is below 80%, review the theme descriptions in the classification prompt. Common failure modes: KYC and Onboarding reviews being confused (both relate to account setup), Performance and Payments reviews being confused (both can involve slow/failed transactions). Adjust theme descriptions to better differentiate and re-run.

---

### MC-2.2 — Action Ideas Are Specific and Grounded

**What to do**: Read all 3 action ideas and assess their quality.

**What to verify**:
- Each action idea references a specific Groww product surface or user flow (not generic advice like "improve UX")
- Each action idea can be traced back to one of the top 3 themes
- The ideas are actionable by a product or engineering team (not observations or complaints)
- The ideas are distinct from each other (not variations of the same suggestion)

**Pass condition**: All 3 action ideas are specific, grounded, and actionable.

**Failure action**: If one or more action ideas are too vague, re-prompt with explicit instructions to be specific and reference the supporting quote/theme.

---

### MC-2.3 — Theme Ranking Makes Intuitive Sense

**What to do**: Review the priority score ranking of all 5 themes.

**What to verify**:
- The top-ranked theme has noticeably more reviews and/or more negative sentiment than the bottom-ranked themes
- The ranking feels aligned with what a product manager scanning the reviews would intuitively identify as the biggest pain points

**Pass condition**: The ranking order feels defensible and aligns with intuitive reading of the dataset.

**Failure action**: If the ranking seems wrong (e.g., a theme with 5 reviews but very negative sentiment ranks above a theme with 50 reviews), review the priority score formula. It may need to be adjusted to weight volume more heavily relative to sentiment.

---

### MC-2.4 — Quote Representativeness

**What to do**: Read all 3 selected quotes and assess whether they are good representatives of their respective themes.

**What to verify**:
- Each quote clearly relates to the theme it represents
- The quote is specific enough to be meaningful (not just "this app is bad")
- The quote is concise enough to be readable in the pulse note context (ideally 1–3 sentences)

**Pass condition**: All 3 quotes are thematically accurate, specific, and appropriately concise.

**Failure action**: Return to quote extraction and select a better candidate for the failing theme.

---

### MC-2.5 — PII Absence Spot-Check

**What to do**: Read through all quotes and action ideas looking for any personally identifiable information.

**What to verify**: No names, contact details, account references, or device identifiers appear in any of the extracted quotes or generated action ideas.

**Pass condition**: No PII found in sampled content.

**Failure action**: If PII is found in a quote, replace it with a different quote from the same theme. If PII is found in an action idea (unusual but possible), regenerate that action idea.

---

## Exit Gate

**Phase 2 is complete when:**

| Gate | Requirement |
|---|---|
| All 9 automated checks | Pass |
| All 5 manual checks | Pass |
| `data/processed_signal.json` | Exists, readable, valid JSON, matches schema |
| Zero `"Other"` theme labels | Confirmed |
| Run log | Contains Phase 2 summary entry |

> **Do not proceed to Phase 3 until this gate is cleared.**
