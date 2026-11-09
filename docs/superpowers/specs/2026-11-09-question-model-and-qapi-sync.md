# Unified Trivia Question Model and QAPI Sync

## Intent

Keep Trivia Sync as the QAPI intake and editorial source of truth, and Frappe LMS as the delivery and assessment system. Preserve existing question, quiz, and submission records while making the projection lossless for the supported LMS question formats.

## Goals

- Normalize QAPI question payloads without losing option order, alternatives beyond E, multiple correct answers, explanations, or supporting-text links.
- Require five options for standard Trivia `Choices`; allow a different count only with explicit authorization and a reason. Permit LMS-native non-choice types under LMS rules.
- Keep approval and redistribution gates on the Trivia source. Do not publish imported questions automatically.
- Preserve numeric AI difficulty and add a separate editor-owned 1–5 difficulty value.
- Keep source identity and immutable LMS versions for questions already used in quizzes.
- Install all Trivia-owned LMS Custom Fields on clean and existing sites, and enforce Trivia-linked question integrity through Frappe hooks without changing LMS core.
- Diagnose QAPI sync failures with endpoint-specific metrics and handle documented response/pagination shapes defensively.

## Non-goals

- Replace QAPI integration, LMS question storage, quiz rows, submissions, or historical quiz versions.
- Alter source records or call QAPI as part of code validation.
- Treat any individual QAPI question ID specially.
- Add a new app or external dependency.

## Architecture

`Trivia Question` remains the editorial record. Its JSON options remain ordered by stable letter keys; normalization retains A–Z from source data, while the native LMS projection supports A–J and rejects unsupported/over-capacity data instead of truncating it. The existing single `correct_option` stays as a compatibility field and a new JSON list represents all correct options. A server-side validation service is called by import/review/projection paths. `LMS Question` remains native and stores its existing fixed option/correctness/explanation fields; Trivia Sync projects ordered option rows into those fields and retains source identity, version hash, and metadata in Trivia-owned Custom Fields. A `doc_events` validation hook constrains only records linked to Trivia, so unrelated LMS authoring and non-choice question types keep native behavior.

Imported source data is never considered approved. Editorial state is additive to the legacy review fields for compatibility, and projection requires an approved state, redistribution clearance, recorded license/terms, valid answer mapping, and valid option cardinality. Content changes to a question already used in a quiz continue to create a new LMS version; existing quiz references and submissions remain untouched.

## Field mapping

| Meaning | Trivia source | LMS projection |
|---|---|---|
| Question | `enunciado` plus linked `Trivia Supporting Text` | Native `question` (support text included once per linked question) |
| Type | Derived `Choices` for QAPI multiple choice | Native `type` |
| Options | `options` JSON, source letters A–Z retained | Native `option_1…option_10`, in letter order; larger/unsupported sets block projection |
| Correct answers | Legacy `correct_option` plus `correct_options` JSON | Native `is_correct_1…is_correct_10` and `multiple` |
| Explanations | Existing global `explanation` | Per-option native explanation on each correct option |
| Marks | Existing exam-question row where specified, otherwise 1 | Native `marks` |
| Difficulty | AI-owned existing `ai_difficulty_stars`; new editor-owned numeric difficulty | Existing AI metadata plus separate editorial difficulty Custom Field |
| Editorial/licensing/source identity | Existing Trivia fields | Trivia-owned LMS Custom Fields where needed for traceability and LMS-side validation |

## Validation and transitions

- QAPI import stores the full payload and detected option count; malformed choices remain unapproved and cannot be projected.
- A standard Trivia choice question has exactly five non-empty options and one or more correct options that exist in the option map.
- A non-five count may be approved only with `allow_variable_options` and a non-empty `exception_reason`; supported LMS ceiling is ten choices. The importer retains excess source alternatives for review rather than trimming them.
- A Trivia-linked LMS choice question is checked again on every insert/update. Native LMS questions without Trivia identity and native non-choice types are not subject to the five-option rule.
- Editorial states are `Imported`, `Pending Review`, `In Review`, `Pending Approval`, `Approved`, `Published`, `Rejected`, and `Archived`. Legacy `review_status` stays readable and is updated when approval/rejection changes.
- Projection is idempotent by stable source identity and content hash. Existing quiz-linked versions are never mutated.

## QAPI sync investigation

Test endpoint method wiring and representative payloads offline first. A live pull is not part of schema migration or automated tests. If executed later, it must be an explicit questions-only pull sized to the configured budget and use the existing source key for upsert; no question ID is excluded or specially handled.

## Risks and compatibility

- Existing QAPI payload formats may carry undocumented option or answer shapes; raw payloads remain stored so normalization can be revised and existing records reparsed without a new external call.
- Existing records retain their IDs and fields. Migration adds fields and backfills counts/state only; it does not delete or rename questions, quizzes, or attempts.
- The live site could not be inspected from this sandbox because MariaDB socket access is denied. Bench migrations and site integration tests therefore require a later run in the operational bench.
