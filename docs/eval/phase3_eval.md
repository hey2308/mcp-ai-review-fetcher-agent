# Phase 3 Evaluation — Pulse Note Generation

## Purpose

This document defines how to verify that the Pulse Note Generation phase is complete and correct. The pulse note is the primary output of the entire pipeline — it is what stakeholders read, what appears in Google Docs, and what is emailed. Its quality, accuracy, and compliance with all constraints must be verified rigorously before it is published anywhere.

---

## What This Phase Must Deliver

- A structured weekly pulse note assembled from `processed_signal.json`
- The note must contain exactly three sections: Top Themes, User Voices, Action Ideas
- Each section must contain exactly the right number of items (3 themes, 3 quotes, 3 actions)
- Total word count must be ≤ 250
- All quotes must be verbatim (no paraphrasing relative to `processed_signal.json`)
- No PII must be present anywhere in the note
- The note must be saved as `data/weekly_pulse.md`

---

## Automated Checks

---

### AC-3.1 — Word Count Compliance

**What it checks**: That the full note does not exceed the 250-word limit.

**Counting method**: Count all words in the Markdown source, including heading text, theme names, quote text, and action items. Exclude Markdown syntax characters (e.g., `#`, `>`, `-`, `*`) from the word count — count only prose words.

**Condition**: `word_count(weekly_pulse.md) ≤ 250`

**Why this matters**: The 250-word limit is the definition of "pulse" vs. "report." Exceeding it means the note requires more than a quick scan to digest.

**Failure action**: Return the note to the assembler with an instruction to condense. If condensation fails after two attempts, apply programmatic truncation to the longest section (typically the action ideas or theme summaries), log the truncation, and flag for review.

---

### AC-3.2 — Section Presence

**What it checks**: That all three required sections are present in the note.

**Condition**: The note contains headings (or clearly delineated sections) for:
- Top Themes (or equivalent heading)
- User Voices (or equivalent heading)
- Action Ideas (or equivalent heading)

**Why this matters**: A missing section means the pulse note fails to deliver one of its three core promises.

**Failure action**: Identify which section is missing. Re-run note assembly with an explicit instruction that all three sections are required.

---

### AC-3.3 — Theme Count

**What it checks**: That exactly 3 themes are listed in the Top Themes section.

**Condition**: The Top Themes section contains exactly 3 theme entries.

**Why this matters**: The problem statement requires top 3 themes. More or fewer would either exceed scope or underdeliver.

**Failure action**: Re-run assembly with an explicit count constraint in the prompt.

---

### AC-3.4 — Quote Count

**What it checks**: That exactly 3 user quotes are present in the User Voices section.

**Condition**: The User Voices section contains exactly 3 blockquote blocks (lines beginning with `>` in Markdown, or equivalent formatting).

**Why this matters**: The problem statement requires 3 user quotes. Missing quotes reduce credibility; extra quotes push the note over the word limit.

**Failure action**: Re-run assembly. If the LLM consistently adds or removes quotes, add explicit count enforcement to the prompt.

---

### AC-3.5 — Action Ideas Count

**What it checks**: That exactly 3 action ideas are listed.

**Condition**: The Action Ideas section contains exactly 3 numbered items.

**Failure action**: Re-run assembly with explicit count enforcement.

---

### AC-3.6 — Quotes Match Processed Signal

**What it checks**: That the 3 quotes in the note are identical to the 3 quotes in `processed_signal.json` — no modification, paraphrasing, or substitution during note assembly.

**Condition**: For each quote Q in `weekly_pulse.md`, Q (after stripping surrounding formatting like `>`, `"`, and whitespace) must exactly match one of the 3 quotes in `processed_signal.json["quotes"]`.

**Why this matters**: Phase 2 verified that quotes are verbatim substrings of source reviews. If the assembler modifies them, that guarantee is broken and the pulse note contains invented or altered text.

**Failure action**: Hard failure. The note assembly prompt must explicitly preserve the provided quotes without any modification. Re-run with stronger instructions.

---

### AC-3.7 — PII Scan on Note Text

**What it checks**: That no PII is present anywhere in the assembled note.

**Scan scope**: Full text of `weekly_pulse.md`, including headings, theme names, quote text, and action ideas.

**PII patterns to scan for**:
- Email addresses (regex: `[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}`)
- Phone numbers (regex: `\b\d{7,}\b` and common Indian phone formats)
- Names adjacent to possessive/identifying language patterns

**Condition**: Zero regex matches across all PII patterns.

**Why this matters**: The pulse note is published to Google Docs and emailed — any PII at this stage is being actively distributed.

**Failure action**: Hard failure. Do not save or publish the note. Identify the source of the PII (likely in a quote) and return to Phase 2 to select a different quote.

---

### AC-3.8 — Theme Names Match Processed Signal

**What it checks**: That the theme names in the note match the theme names in `processed_signal.json` — they should not be reworded or abbreviated.

**Condition**: Each theme name in the note's Top Themes section matches (case-insensitively, stripped of Markdown formatting) a theme name from the `featured: true` themes in `processed_signal.json`.

**Why this matters**: Renamed themes make it impossible to trace the note back to the source signal, and may confuse readers familiar with the canonical theme names.

**Failure action**: Re-run assembly with the canonical theme names explicitly provided in the prompt (not just the processed signal JSON — spell them out).

---

### AC-3.9 — Output File Exists and Is Non-Empty

**What it checks**: That the note was successfully saved.

**Condition**: `data/weekly_pulse.md` exists, has file size > 0, and is readable.

**Failure action**: Re-run the save step. Check for file system permission issues.

---

## Manual Checks

---

### MC-3.1 — End-to-End Readability

**What to do**: Read the entire note from top to bottom as if you are a product manager seeing it for the first time.

**Time allowed**: The note should be fully readable and comprehensible in under 2 minutes.

**What to verify**:
- The note flows naturally and logically from themes → evidence → actions
- The language is clear and professional (not jargon-heavy, not overly casual)
- The note makes sense without any prior context about the source reviews

**Pass condition**: The note can be understood and acted upon in under 2 minutes by someone unfamiliar with the underlying data.

**Failure action**: If the note is confusing or poorly structured, identify the specific section that fails and re-run assembly with a more detailed formatting instruction for that section.

---

### MC-3.2 — Action Ideas Are Traceable to Themes

**What to do**: For each of the 3 action ideas, identify which theme it corresponds to and verify the connection is clear.

**What to verify**: A reader could connect each action idea to its theme without being told which is which. The action ideas should feel like natural consequences of the stated themes and quotes.

**Pass condition**: All 3 action ideas are clearly traceable to a theme and grounded in the evidence presented.

**Failure action**: If an action idea seems disconnected from the themes, flag it and request regeneration with a stricter grounding instruction.

---

### MC-3.3 — Quotes Are Impactful and Self-Contained

**What to do**: Read each of the 3 quotes in isolation (as if you encountered them with no surrounding context).

**What to verify**:
- Each quote conveys a meaningful user experience or pain point on its own
- The quote does not require surrounding context from the original review to be understood
- The quote is not too long (should be readable in 5–10 seconds)

**Pass condition**: All 3 quotes are impactful, self-contained, and appropriately concise.

**Failure action**: If a quote fails this check, return to Phase 2 quote extraction and select a better candidate for the affected theme.

---

### MC-3.4 — Tone and Appropriateness

**What to do**: Assess the overall tone of the note.

**What to verify**:
- The note is neutral and analytical, not defensive or alarmist
- Themes and issues are described factually, not with editorial judgment
- The action ideas are constructive, not reactive
- The note would be appropriate to share with a senior stakeholder or in a team meeting without editing

**Pass condition**: The tone is professional, balanced, and stakeholder-appropriate.

**Failure action**: If the tone is off (too negative, too dismissive, too informal), adjust the assembler prompt to specify the expected tone explicitly.

---

### MC-3.5 — No Invented Content

**What to do**: Spot-check the note's theme summaries and action ideas against `processed_signal.json`.

**What to verify**: The theme summaries accurately reflect the theme's review count and sentiment. No statistics or claims appear in the note that don't have a traceable basis in the processed signal.

**Pass condition**: All factual claims in the note (counts, themes, characterisations) correspond to data in `processed_signal.json`.

**Failure action**: If invented statistics or claims are found, add explicit instructions to the assembly prompt to use only the provided data and not generate new statistics.

---

## Exit Gate

**Phase 3 is complete when:**

| Gate | Requirement |
|---|---|
| All 9 automated checks | Pass |
| All 5 manual checks | Pass |
| `data/weekly_pulse.md` | Exists, readable, ≤ 250 words |
| Run log | Contains Phase 3 summary entry |

> **Do not proceed to Phase 4 until this gate is cleared.**
