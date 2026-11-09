# Trivia Question Model and QAPI Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve question content and answer behavior from QAPI intake through reviewed, versioned LMS projection.

**Architecture:** Keep the Trivia and LMS DocTypes separate. Trivia owns editorial state and source data; a tested conversion layer maps ordered alternatives and correct-answer sets into native LMS fields, with a hook guarding Trivia-linked LMS records.

**Tech Stack:** Frappe DocTypes/patches, Python, unittest/Frappe tests; existing JSON fixtures and `doc_events` hooks.

**Spec:** `docs/superpowers/specs/2026-11-09-question-model-and-qapi-sync.md`

## Global Constraints

- Never delete or rename existing questions, quizzes, submissions, or identifiers.
- Standard Trivia choice questions require exactly five non-empty options; exceptions require explicit authorization and a reason.
- Keep native LMS non-choice formats and unrelated native questions working.
- Keep QAPI raw payloads and source identities; use idempotent upserts and do not special-case any question ID.
- Never project an unapproved or uncleared question.
- No external QAPI call during tests, migration, or local verification.

## Review Focus

- QAPI payload uses an array of alternatives with non-sequential explicit letters: preserve letter order and answer identity.
- QAPI represents multiple correct answers as a list/object: preserve every correct answer and LMS `multiple` scoring.
- A 4/6-option question arrives without exception metadata: retain it for review but block approval/projection.
- A Trivia-linked LMS question is edited directly: reject invalid cardinality even outside the projection API.
- A changed question already referenced by a quiz: create a version and preserve old quiz/submission references.

### Task 1: Normalize question options and answer sets

**Files:**
- Modify `trivia_sync/integrations/normalization.py`
- Modify `trivia_sync/tests/test_qapi.py`
- Modify `trivia_sync/trivia_sync/doctype/trivia_question/trivia_question.json`

**Interfaces:**
- Produces `normalize_question(row)` with options keyed A–J, `correct_option` as legacy first answer, `correct_options` as JSON array, and `detected_option_count`.

- [ ] Add failing cases for A–J, sparse letters, multiple correct answers, and supported legacy payload aliases.
- [ ] Run `python3 -m unittest trivia_sync.tests.test_qapi` from `apps/trivia_sync`; confirm expected failures.
- [ ] Implement minimum normalization and add additive DocType fields.
- [ ] Rerun the targeted unit test and existing normalization/QAPI cases.

### Task 2: Enforce option, exception, difficulty, and editorial gates

**Files:**
- Modify `trivia_sync/doctype/trivia_question/trivia_question.json` and `.py`
- Modify `trivia_sync/integrations/editorial.py`
- Modify `trivia_sync/api.py`
- Modify `trivia_sync/tests/test_editorial.py`

**Interfaces:**
- Produces server-side validation for standard five-option questions and authorized 2–10-option exceptions; records explicit editorial transitions while keeping legacy review fields synchronized.

- [ ] Add failing validation and transition tests, including missing answers/reasons and out-of-range difficulty.
- [ ] Run `python3 -m unittest trivia_sync.tests.test_editorial` and observe the expected failures.
- [ ] Implement validation, editable numeric difficulty, detected count, exception fields, and gated state transitions.
- [ ] Rerun the targeted editorial tests.

### Task 3: Make LMS projection lossless and guarded

**Files:**
- Modify `trivia_sync/integrations/lms_questions.py`
- Modify `trivia_sync/hooks.py`
- Modify `trivia_sync/fixtures/custom_field.json`
- Modify `trivia_sync/tests/test_editorial.py`

**Interfaces:**
- Projection fills native options in order, marks all correct answers, preserves explanations/marks/difficulty/licensing/source identity, and remains idempotent.
- LMS hook rejects invalid Trivia-linked `Choices` on every save without affecting unrelated LMS questions.

- [ ] Add failing projection tests for variable option count, multi-answer correctness, explanation order, metadata, and versioned quiz references; add hook tests.
- [ ] Run targeted editorial tests and confirm failures are at the missing behavior.
- [ ] Implement conversion and LMS validation hook; ensure every shipped fixture is included by the fixture filter.
- [ ] Rerun targeted editorial tests.

### Task 4: Repair sync response handling and migrate existing records

**Files:**
- Modify `trivia_sync/integrations/sync.py`
- Modify `trivia_sync/integrations/normalization.py`
- Add `trivia_sync/patches/v0_5/question_integrity_fields.py`
- Modify `trivia_sync/patches.txt`
- Modify `trivia_sync/tests/test_qapi.py`

**Interfaces:**
- Pagination and row extraction accept the documented list/object forms without treating malformed responses as successful empty pages.
- Patch adds/backfills fields and derives option counts/state without changing record identity or linked LMS/quizzes.

- [ ] Add failing tests for supported response wrappers, pagination aliases, malformed payloads, and additive backfill behavior.
- [ ] Run targeted QAPI and patch tests; confirm expected failures.
- [ ] Implement defensive response handling and idempotent field backfill; do not perform a live pull.
- [ ] Rerun QAPI, patch, ownership, exam, and LMS quiz regression tests.

### Task 5: Verify and document the end-to-end contract

**Files:**
- Modify `README.md` and the Trivia Sync operational runbook if needed.
- Review all modified integration, hook, fixture, patch, and test files.

- [ ] Run the Trivia Sync test suite and applicable LMS quiz tests in this bench.
- [ ] Run Python compile and `git diff --check` for the affected repositories.
- [ ] Verify the diff does not include the pre-existing user changes except where explicitly retained.
- [ ] Record that site migration/live QAPI verification is unavailable if the sandbox socket/network restrictions remain.

