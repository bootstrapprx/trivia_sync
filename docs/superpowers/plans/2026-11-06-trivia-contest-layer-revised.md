# Trivia Contest Layer — Revised Implementation Plan

> **For agentic workers:** Execute each phase in order. A phase is complete only after its gate passes. This plan follows the user's revised 2026-11-06 plan.

**Goal:** Evolve `trivia_sync` into the editorial, contest, assessment, public-distribution, and assisted-content layer for Frappe LMS without destroying data or bypassing review controls.

**Architecture:** Source ingestion writes a stable editorial record in Trivia Sync. Editorial approval and confirmed redistribution rights are separate gates before a question is projected into native LMS records. LMS remains authoritative for courses, lessons, quiz attempts, and learner progress. All schemas evolve additively; imports never create courses or lessons.

**Tech Stack:** Frappe DocTypes and patches, LMS DocTypes, Python unittest/Frappe test runner, QAPI REST/MCP, Frappe background jobs, Desk/website routes, OpenAI-compatible AI adapter.

**Spec:** `docs/superpowers/specs/2026-11-06-trivia-contest-layer-design.md`

## Global Constraints

- All changes stay in `apps/trivia_sync`; do not modify Frappe, LMS, or Aprova.
- Source-owned, editorial-owned, AI-owned, and projection-owned fields remain separate.
- Every source record has stable identity; ambiguous matches are never guessed.
- Only valid, reviewed, approved, redistribution-cleared questions project to LMS or public endpoints.
- Existing fields, records, LMS links, quizzes, and submissions are preserved.
- QAPI paid calls require an explicit positive local budget and reserve; paid scheduler is off by default.
- Public endpoints use explicit allowlists and fail closed.
- No migration, source ingestion, AI generation, publication, or mutation of `trivia.localhost` without site-specific authorization.

## Review Focus

- A changed source payload invalidates only the approval that depends on evaluable content and preserves editorial notes/history.
- Reconciliation handles exact, missing, duplicate, and ambiguous external identities without guessing.
- A zero/insufficient QAPI budget causes no paid request; dry-run causes no writes.
- A low eligible question pool creates no partial exam rows.
- Quiz supersession preserves submissions and unrelated lesson content.
- Anonymous APIs never return answer keys, explanations, raw payload, or private LMS content.

---

### Task 0: Phase 0 — Safety baseline and test harness

**Files:** `trivia_sync/tests/*`, `scripts/check_schema_compatibility.py`, `docs/superpowers/fixtures/schema_baseline.json`, `.github/workflows/ci.yml`.

- [ ] Record the existing six tests and baseline behavior before refactors.
- [ ] Add reusable factories for question, run, catalog, fake LMS objects, and a disposable Frappe test site.
- [ ] Add a schema check that rejects removed/renamed current DocType fields and missing controller modules.
- [ ] Add CI coverage reporting; keep `bench --site trivia-sync-test.localhost run-tests --app trivia_sync` authoritative.
- [ ] Ownership regression tests are added with Phase 2, reviewer permission tests with Phase 4, and public allowlist tests with Phase 6, where those contracts exist. (Do not add tests that pass only because the feature is absent.)
- [ ] Gate: six existing tests plus new baseline tests pass; `compileall`, JSON checks, JS syntax, schema check, and `git diff --check` pass.

### Task 1: Phase 1 — Canonical contest/editorial schema

**Files:** Existing `Trivia Question`, `Concurso`, `Prova`, `Cargo`, `Conteúdo Programático`, LMS custom-field fixtures/hooks; new `Concurso Cargo`, `Trivia Exam Block`, and `Trivia Exam Question` DocTypes.

- [ ] Add stable `source_type`, `source_id`, `source_key`; make `qcode` optional for non-QAPI records and preserve its QAPI uniqueness/legacy value.
- [ ] Add review state/audit, redistribution decision, license/attribution, source payload/hash, AI freshness, classification links, and LMS projection identity.
- [ ] Add cargo-to-contest with existing LMS Course link; add exam block/question child records and controller-level validation/uniqueness.
- [ ] Keep all existing DocTypes/fields; add role and permission fixtures.
- [ ] Gate: schema superset check passes; fixtures install in disposable test site; duplicate source identity tests pass.

### Task 2: Phase 2 — QAPI ingestion ownership and spend controls

**Files:** `integrations/normalization.py`, `integrations/qapi_client.py`, `integrations/sync.py`, `integrations/ingestion.py`, `api.py`, settings/run DocTypes, QAPI tests.

- [ ] Extract source/editorial ownership and replace direct `_upsert` field copying with allowlisted updates.
- [ ] Add stable source identity, idempotent upsert, content-hash transition logic, local note preservation, and Frappe Version history.
- [ ] Add `qapi_max_requests_per_run`, `qapi_min_credit_reserve`; zero max disables paid sync; dry-run counts cost and writes nothing.
- [ ] Record operator, filters, page, request count/budget/reserve, per-record errors, and resumable status in `Trivia Sync Run`.
- [ ] Add tests for zero/insufficient budget, dry-run, repeat payload, source updates preserving editor fields, and content changes resetting review/AI freshness.
- [ ] Gate: mocked budget tests prove no paid request when blocked; no duplicate on repeat; dry-run no writes.
- [ ] Only after the shared adapter contract is stable, add GitHub and Hugging Face adapters to the same review queue and test source identity/license attribution.

### Task 3: Phase 3 — Reconciliation and syllabus versioning

**Files:** `integrations/reconciliation.py`, `integrations/sync.py`, `Conteúdo Programático`/`Concurso Cargo` controllers/DocTypes, `patches/v0_2/backfill_contest_relations.py`, `patches.txt`.

- [ ] Resolve classification by exact external ID first, then unique normalized name; preserve ambiguous/unmatched items for manual reconciliation.
- [ ] Implement `sync_syllabus_tree(cargo, rows, source_version)` using stable paths/hashes, version changes, and obsolete state without deletion.
- [ ] Add cargo-specific coverage by subject/topic/review/license/source.
- [ ] Add additive, idempotent backfill and unresolved/ambiguous report.
- [ ] Gate: exact/missing/ambiguous fixtures pass; patch twice leaves the second result unchanged; obsolete nodes remain queryable.

### Task 4: Phase 4 — Editorial review and LMS Question projection

**Files:** `api.py`, `integrations/lms_questions.py`, `integrations/ai_enricher.py`, `Trivia Question` controller/list JS, LMS custom-field fixtures/hooks.

- [ ] Implement `review_question(question_name, decision, reason="")`; accept only approved/rejected, enforce reviewer permission, record actor/time/reason/history.
- [ ] Validate question type, alternatives, answer, support text, source license, and explicit redistribution approval.
- [ ] Project only valid, reviewed, approved, redistribution-cleared questions idempotently by `source_key` and content hash.
- [ ] Keep projection failures retryable without losing source or approval records.
- [ ] Backfill legacy `LMS Question.trivia_qcode` links to pending Trivia Questions; do not touch unrelated LMS Questions.
- [ ] Ensure AI never approves; changed AI output is projected only under review rules.
- [ ] Gate: pending/rejected/unlicensed records never project; repeat projection is idempotent; failures preserve state; legacy links are additive.

### Task 5: Phase 5 — Blueprint assembly and LMS quiz lifecycle

**Files:** `Prova`/exam child DocTypes/controllers, `integrations/exams.py`, `api.py`, LMS placement integration.

- [ ] Validate cargo/course/lesson/topic/type/license/review/count before writing.
- [ ] Build eligible pool first; fail atomically with missing criteria if insufficient.
- [ ] Preserve order, marks, and exam version; reject duplicate question rows.
- [ ] Publish through native `Course Lesson` assessment placement without replacing unrelated content.
- [ ] Prevent in-place edits after submissions; supersede to a new quiz and preserve previous attempts.
- [ ] Gate: transaction tests prove no rows for insufficient pool, reject duplicates, preserve old attempts and unrelated lesson content.

### Task 6: Phase 6 — Public contest catalog and safe access

**Files:** `public.py`, `templates/pages/concursos.py`, `templates/pages/concursos.html`, public JS/CSS, hooks, `Concurso` publication fields.

- [ ] Add publication state/date and curated summary fields.
- [ ] Require published contest plus public/accessible LMS course on every lookup.
- [ ] Return explicit DTO allowlists; omit answers, explanations, raw payload, private source fields, student data, and instructor content.
- [ ] Draft/private/mismatched records return not-found/empty.
- [ ] Gate: anonymous and authenticated endpoint tests prove allowlists and fail-closed behavior.

### Task 7: Phase 7 — Methodologies, lesson recipes, AI materials, PDF

**Files:** methodology, lesson-recipe, apostila-recipe DocTypes/controllers; `integrations/learning_content.py`; AI adapter/API/hooks.

- [ ] Add methodology/activity templates and versioned lesson/apostila recipes with source hash/model/provenance/approval.
- [ ] Implement `generate_lesson_material(recipe_name, level)` for `mais`, `180`, `360`; output remains draft.
- [ ] Implement `publish_lesson_material(recipe_name, level)` requiring human approval and linked-course permission.
- [ ] Implement `export_apostila(recipe_name, levels)` using approved versions and correct File visibility.
- [ ] Gate: generated drafts cannot auto-publish, stale hashes require regeneration, file access matches course policy.

### Task 8: Phase 8 — Workspace, dashboard, runbooks, release review

**Files:** workspace/dashboard, run DocType, README/runbooks, CI.

- [ ] Add pending-review age, LMS projection failures, source run/budget/resume, syllabus coverage, and eligible question metrics.
- [ ] Add role-aware workspace links for contests, cargos, syllabus, review queue, approved bank, exams, content recipes, and runs.
- [ ] Document budgets, source rights, review/projection, backfill, supersession, public access, PDF visibility, rollback, and recovery.
- [ ] Run the complete unit/integration suite, schema/JSON/Python/JS checks, and `git diff --check`; perform file-by-file review.
- [ ] Do not migrate or ingest into the user's existing site as part of code delivery.
