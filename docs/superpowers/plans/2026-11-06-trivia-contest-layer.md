# Trivia Contest Layer Implementation Plan

> **For agentic workers:** This plan is executed task by task in this session. Tasks use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `trivia_sync` as the editorial, contest, assessment, public distribution, and assisted content layer for Frappe LMS.

**Architecture:** Trivia Sync owns contest metadata, source ingestion, review state, syllabus, blueprints, and content recipes. Approved questions and published assessments project into native LMS records; courses, lessons, enrollments, quizzes, submissions, and learner progress remain owned by LMS. Existing data is migrated additively, with no destructive changes.

**Tech Stack:** Frappe DocTypes, fixtures, whitelisted Python APIs, Frappe background jobs, LMS DocTypes, existing requests-based QAPI and AI clients, Desk pages/workspaces.

**Spec:** `docs/superpowers/specs/2026-11-06-trivia-contest-layer-design.md`

## Global Constraints

- Do not edit Frappe, LMS, or the Aprova reference app; all implementation stays in `apps/trivia_sync`.
- Do not create LMS courses or lessons during source import; each contest cargo links to existing LMS course/lesson records.
- Keep source payload, stable source IDs, editorial notes, and version history; never delete catalog records that have downstream links.
- Only reviewed, valid, and redistribution-cleared questions project into LMS Question or public responses.
- Never modify quiz composition after submissions exist; preserve old quizzes and submissions when superseding a version.
- QAPI paid calls require a positive local run budget; paid scheduling is off by default.
- Public responses are allowlisted and exclude answers, explanations, raw source payloads, student data, and instructor-only content.
- Tests are not added or run in this execution unless separately requested; use static review and `git diff --check` for code changes.

## Review Focus

- Source updates to approved question content must reset editorial approval while preserving local notes and the previous Frappe Version.
- Reconciliation must not guess when an external ID maps to multiple catalog records.
- A generated exam must fail atomically when eligible approved question count is below the blueprint requirement.
- Replacing a quiz must remove only its own active lesson placement and preserve all prior submissions.
- Public endpoints must fail closed and must not serialize full DocTypes or raw payloads.

---

### Task 1: Canonical contest and editorial schema

**Files:**
- Modify: `trivia_sync/trivia_sync/doctype/trivia_question/trivia_question.json`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_concurso/trivia_concurso.json`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_prova/trivia_prova.json`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_cargo/trivia_cargo.json`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_conteudo/trivia_conteudo.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_concurso_cargo/__init__.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_concurso_cargo/trivia_concurso_cargo.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_concurso_cargo/trivia_concurso_cargo.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_exam_block/__init__.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_exam_block/trivia_exam_block.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_exam_block/trivia_exam_block.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_exam_question/__init__.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_exam_question/trivia_exam_question.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_exam_question/trivia_exam_question.py`
- Modify: `trivia_sync/fixtures/custom_field.json`
- Modify: `trivia_sync/hooks.py`

**Interfaces:**
- Contest cargo links one `Concurso`, an optional catalog `Cargo`, and one existing `LMS Course`.
- `Trivia Question` stores review state, review audit, redistribution decision, source type/ID/license/attribution, linked catalog records, linked `Conteúdo Programático` topics, and its projected LMS Question ID.
- `Trivia Question.source_key` is the unique stable key `{source_type}:{source_id}` and becomes the future autoname; existing `qcode` remains optional, unique for QAPI when present, and unchanged for legacy rows.
- Exam blocks store ordered selection rules; exam question rows store a unique question per exam, order, and marks.

- [ ] Extend existing DocTypes additively; retain legacy text fields and current external IDs.
- [ ] Add `source_key`, make `qcode` optional for non-QAPI sources, and keep `qcode` uniqueness for QAPI; migrate existing names and LMS links without renaming saved records.
- [ ] Add required link/unique constraints and validation for parent-child contest and exam relationships.
- [ ] Add unique `LMS Question.trivia_source_key` plus projection fields and fixture filters without changing LMS source files; retain `trivia_qcode` for legacy QAPI links.
- [ ] Add role/permission fixtures for sync operator, editor, reviewer, and read-only operational roles.
- [ ] Inspect the final schema diff and confirm no existing field or DocType is removed or renamed.

### Task 2: Shared multi-source ingestion and spend controls

**Files:**
- Create: `trivia_sync/integrations/sources/base.py`
- Create: `trivia_sync/integrations/sources/qapi.py`
- Create: `trivia_sync/integrations/sources/github_questions.py`
- Create: `trivia_sync/integrations/sources/huggingface.py`
- Create: `trivia_sync/integrations/ingestion.py`
- Modify: `trivia_sync/integrations/normalization.py`
- Modify: `trivia_sync/integrations/qapi_client.py`
- Modify: `trivia_sync/integrations/sync.py`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_sync_settings/trivia_sync_settings.json`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_sync_run/trivia_sync_run.json`
- Modify: `trivia_sync/api.py`

**Interfaces:**
- `SourceAdapter`: `is_available() -> bool`, `fetch_questions(filters, max_pages)`, source identity, authentication and request cost metadata.
- `ingest_source(source_name, filters=None, dry_run=False, max_pages=0, budget=0) -> dict` normalizes every record into `Trivia Question` and reports fetched, created, updated, duplicate, pending, invalid, and failed counts.
- QAPI adapter refuses paid sync unless local request budget is positive and respects its reserve; GitHub and Hugging Face adapters record license/attribution and enter the same review queue.

- [ ] Implement stable source identity and source-specific normalization for QAPI, GitHub, and Hugging Face.
- [ ] Make source upsert idempotent; update source-owned fields only and preserve editorial fields.
- [ ] Reset approval only when evaluable content changes; preserve Frappe Version history and mark AI enrichment stale.
- [ ] Add dry-run and local QAPI request-budget enforcement; keep paid scheduler disabled by default.
- [ ] Use explicit settings `qapi_max_requests_per_run` and `qapi_min_credit_reserve`; zero max requests disables paid sync.
- [ ] Record run parameters, operator, pagination, per-record errors, and resumable status in `Trivia Sync Run`.
- [ ] Keep source imports in editorial DocTypes; do not project pending questions into LMS.

### Task 3: Classification reconciliation and syllabus versioning

**Files:**
- Create: `trivia_sync/integrations/reconciliation.py`
- Modify: `trivia_sync/integrations/sync.py`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_conteudo/trivia_conteudo.json`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_concurso/trivia_concurso.py`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_concurso_cargo/trivia_concurso_cargo.py`
- Create: `trivia_sync/patches/v0_2/backfill_contest_relations.py`
- Modify: `trivia_sync/patches.txt`

**Interfaces:**
- `reconcile_question_classification(question) -> dict` resolves only unambiguous external ID/name matches and reports unresolved or ambiguous links.
- `sync_syllabus_tree(cargo, rows, source_version) -> dict` matches stable source paths, versions source text, and marks disappeared nodes obsolete without deletion.

- [ ] Reconcile existing Banca, Órgão, Cargo, Matéria, Assunto, Concurso, Prova and Conteúdo Programático records.
- [ ] Add cargo-specific syllabus hierarchy and stable source paths, hashes, versions and obsolete state.
- [ ] Backfill existing Trivia Question links by exact external IDs; leave ambiguous items for manual resolution.
- [ ] Add coverage queries by contest cargo, subject, topic, and editorial review state.
- [ ] Keep the patch idempotent and report unresolved counts without changing unrelated LMS records.

### Task 4: Editorial review and LMS Question projection

**Files:**
- Modify: `trivia_sync/api.py`
- Modify: `trivia_sync/integrations/lms_questions.py`
- Modify: `trivia_sync/integrations/ai_enricher.py`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_question/trivia_question.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_question/trivia_question_list.js`
- Modify: `trivia_sync/public/js/trivia_sync_settings.js`

**Interfaces:**
- `review_question(question_name: str, decision: str, reason: str = "") -> dict` accepts only `approved` or `rejected`, enforces reviewer permission, records actor/time/reason, and queues projection after approval.
- `sync_lms_question(source) -> str` validates supported question type, answer, source redistribution approval, and is idempotent by `source_key`/content hash; for legacy QAPI rows it also resolves `trivia_qcode`.

- [ ] Add reviewer actions and visible state/error information to the editorial list and form.
- [ ] Validate single choice, true/false, multiple-correct and text-passage types against installed LMS Question capabilities; leave unsupported forms pending with a reason.
- [ ] Project approved, redistribution-cleared questions only; map answer explanations, support text, relationships, and AI metadata.
- [ ] Make projection failures retryable without reverting editorial approval or losing source data.
- [ ] Backfill legacy LMS Questions with `trivia_qcode` to Trivia Question as pending; leave unrelated LMS questions untouched.
- [ ] Ensure AI enrichment refreshes the editorial record and projection only after approval; never approves content.

### Task 5: Blueprint assembly and LMS quiz lifecycle

**Files:**
- Modify: `trivia_sync/trivia_sync/doctype/trivia_prova/trivia_prova.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_prova/trivia_prova.py`
- Create: `trivia_sync/integrations/exams.py`
- Modify: `trivia_sync/api.py`
- Modify: `trivia_sync/integrations/lms_questions.py`

**Interfaces:**
- `build_simulado(prova_name: str) -> dict` selects only approved/licensed and compatible questions, validates pool sufficiency before any writes, then creates ordered exam rows.
- `publish_prova(prova_name: str, lesson_name: str) -> dict` validates cargo-course-lesson consistency, creates an LMS Quiz and child questions, and merges its native placement into the selected lesson.
- Exam state transitions are `Draft -> Ready -> Published -> Superseded/Archived`; published exams with submissions cannot be edited in place.

- [ ] Add official exam/simulado type, duration, date, source PDF, state, course/lesson and LMS Quiz links.
- [ ] Validate block topics belong to the selected contest cargo and prevent duplicate exam questions.
- [ ] Implement blueprint filters for cargo, syllabus topics, board, difficulty, tags and requested count.
- [ ] Fail before writes when question pool is insufficient; return missing criteria and eligible counts.
- [ ] Place quizzes through the installed `Course Lesson` native content/assessment interface without replacing other content.
- [ ] On supersession, remove only the old quiz's active placement, preserve quiz/submissions, and prevent new attempts through native support or the smallest compatible app hook.

### Task 6: Public contest catalog and safe content access

**Files:**
- Create: `trivia_sync/public.py`
- Create: `trivia_sync/templates/pages/concursos.py`
- Create: `trivia_sync/templates/pages/concursos.html`
- Create: `trivia_sync/public/js/trivia_public_contests.js`
- Create: `trivia_sync/public/css/trivia_public_contests.css`
- Modify: `trivia_sync/hooks.py`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_concurso/trivia_concurso.json`

**Interfaces:**
- Public list/detail endpoints return allowlisted contest, cargo, edital, syllabus summary, published course and released assessment metadata only.
- Every public lookup requires contest publication and a public/accessible LMS course; unconfigured or mismatched state returns not found/empty.

- [ ] Add explicit publication state/date and curated public summary fields.
- [ ] Return field-by-field responses; exclude raw payload, source answers, explanations, student data, private/instructor content.
- [ ] Build public contest listing/detail using Frappe website routing and LMS course pages, no separate frontend application.
- [ ] Confirm draft/private contest, course, lesson, assessment and instructor content are not reachable through public routes.

### Task 7: Methodologies, lesson recipes, AI materials, and PDF output

**Files:**
- Create: `trivia_sync/trivia_sync/doctype/trivia_metodologia/__init__.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_metodologia/trivia_metodologia.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_metodologia/trivia_metodologia.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_aula_recipe/__init__.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_aula_recipe/trivia_aula_recipe.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_aula_recipe/trivia_aula_recipe.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_apostila_recipe/__init__.py`
- Create: `trivia_sync/trivia_sync/doctype/trivia_apostila_recipe/trivia_apostila_recipe.json`
- Create: `trivia_sync/trivia_sync/doctype/trivia_apostila_recipe/trivia_apostila_recipe.py`
- Create: `trivia_sync/integrations/learning_content.py`
- Modify: `trivia_sync/integrations/ai_enricher.py`
- Modify: `trivia_sync/api.py`
- Modify: `trivia_sync/hooks.py`

**Interfaces:**
- `generate_lesson_material(recipe_name: str, level: str) -> dict` accepts `mais`, `180`, or `360`, stores a versioned draft and source hash, and does not publish.
- `publish_lesson_material(recipe_name: str, level: str) -> dict` requires human approval and permission to the linked course/lesson.
- `export_apostila(recipe_name: str, levels: list[str]) -> str` generates a Frappe File from approved recipe versions only.

- [ ] Model reusable methodology/activity templates, duration, required flag and prompt guidance.
- [ ] Generate level-specific material from approved syllabus topics, questions and source data; keep outputs in draft with model/hash/provenance.
- [ ] Require reviewer approval for each generated level and publish only to the linked existing LMS lesson.
- [ ] Generate PDF from approved levels and store it as a private/public File according to LMS access policy.
- [ ] Keep public APIs and files scoped to published course access; do not expose instructor-only content.

### Task 8: Workspace, dashboard, runbooks, and end-to-end static review

**Files:**
- Modify: `trivia_sync/trivia_sync/workspace/concursos/concursos.json`
- Modify: `trivia_sync/trivia_sync/page/trivia_sync_dashboard/trivia_sync_dashboard.js`
- Modify: `trivia_sync/public/css/trivia_sync_dashboard.css`
- Modify: `trivia_sync/trivia_sync/doctype/trivia_sync_run/trivia_sync_run.json`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-11-06-trivia-contest-layer-design.md`

**Interfaces:**
- Workspace navigation exposes Contest, Contest Cargo, Syllabus, Review Queue, Approved Bank, Exams/Simulados, Content Recipes, and Sync Runs.
- Dashboard reports pending review, failed LMS projection, source sync state/budget, syllabus coverage and eligible question counts by cargo.

- [ ] Add workspace shortcuts and role-aware dashboard actions for the defined workflows.
- [ ] Document QAPI paid budget behavior, source license review, approval/projection flow, backfill, quiz supersession, public publishing and PDF permissions.
- [ ] Perform a code/spec coverage review, inspect all changed files, and run `git diff --check`.
- [ ] Do not execute migration, source ingestion, AI generation, or site changes without explicit site-specific authorization.
