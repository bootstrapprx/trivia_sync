# Trivia Contest Layer — Revised Implementation Plan

**Date:** 2026-11-06  
**Repository:** `bootstrapprx/trivia_sync`  
**Goal:** Evolve `trivia_sync` into the editorial, contest, assessment, public-distribution, and assisted-content layer for Frappe LMS without destroying existing data or bypassing review controls.

## 1. Baseline review

The repository already contains:

- QAPI REST/MCP client and paginated synchronization workers.
- QAPI catalog DocTypes, `Trivia Question`, `Texto de Apoio`, and `Trivia Sync Run`.
- AI enrichment with JSON Schema output, 1–5-star difficulty, hash-based skip behavior, and a long-queue worker.
- A System Manager dashboard with recent worker runs, AI coverage, difficulty distribution, and catalog counts.
- Six unit tests covering QAPI normalization/pagination/tree traversal and AI adapter behavior.

The baseline is not yet safe for the full contest layer because source synchronization still needs explicit ownership boundaries, stable source identity, editorial-state protection, budget enforcement, LMS projection, and publication gates. These controls must be implemented before adding public distribution or content generation.

## 2. Non-negotiable invariants

1. All changes stay in `apps/trivia_sync`; never modify Frappe, LMS, or the Aprova reference app.
2. Source import never creates LMS courses or lessons. Contest cargos link only to existing LMS records.
3. Source-owned fields, editorial fields, AI fields, and projection fields are separate. A source update may not overwrite local notes, review decisions, license decisions, or approved content without an explicit transition.
4. Every imported record has a stable source identity. Ambiguous external-ID matches are reported and never guessed.
5. Only valid, reviewed, approved, and redistribution-cleared questions can be projected to LMS or exposed publicly.
6. Published quiz versions are immutable after submissions exist. Supersession creates a new version and preserves old quizzes/submissions.
7. Paid QAPI calls require an explicit positive local budget and reserve. Scheduled paid sync remains disabled by default.
8. Public endpoints are allowlisted, fail closed, and never serialize raw DocTypes, answers, explanations, source payloads, or student/instructor data.
9. Tests are mandatory for every implementation phase. Static review alone is insufficient for data-integrity or permission-sensitive code.
10. No migration, source ingestion, AI generation, or site mutation runs without explicit site-specific authorization.

## 3. Execution strategy and gates

Implement one phase at a time. Each phase must pass its gate before the next phase begins.

### Phase 0 — Safety baseline and test harness

**Purpose:** Make the current behavior observable before changing data ownership.

**Deliverables:**

- Add test fixtures/factories for `Trivia Question`, `Trivia Sync Run`, catalog records, and fake LMS records.
- Add tests for source-owned versus editorial-owned fields.
- Add tests for permission failures and public allowlists.
- Add a static schema check that detects removed/renamed existing fields and missing DocType controller files.
- Add CI coverage reporting and keep `bench run-tests --app trivia_sync` as the authoritative suite.

**Gate:** Existing six tests remain green; new baseline tests pass; `compileall`, JSON validation, JavaScript syntax checks, and `git diff --check` pass.

### Phase 1 — Canonical contest/editorial schema

**Scope:** Contest, cargo, syllabus, exam block, and exam-question records.

**DocTypes:**

- Extend `Trivia Question`, `Concurso`, `Prova`, `Cargo`, and `Conteúdo Programático` additively.
- Create `Concurso Cargo`, `Trivia Exam Block`, and `Trivia Exam Question`.
- Add stable `source_type`, `source_id`, and `source_key` to imported records.
- Keep legacy `qcode` optional for non-QAPI sources and unique when present for QAPI.
- Add review status, review actor/time/reason, redistribution decision, license, attribution, source payload, content hash, AI freshness, and LMS projection fields.
- Add link and uniqueness validation at controller level; do not rely only on UI field settings.

**Gate:** Schema diff proves no existing field/DocType was removed or renamed; fixtures install cleanly; duplicate source identity tests pass.

### Phase 2 — Source adapters, ingestion, and spend controls

**Scope:** QAPI first; GitHub and Hugging Face only after the shared contract is stable.

**Interfaces:**

```python
class SourceAdapter:
    source_type: str
    request_cost: str
    def is_available(self) -> bool: ...
    def fetch_questions(self, filters=None, max_pages=0, budget=None): ...
```

```python
def ingest_source(source_name, filters=None, dry_run=False,
                  max_pages=0, budget=0) -> dict: ...
```

**Required behavior:**

- Source-specific normalization and stable identity.
- Idempotent upsert that updates source-owned fields only.
- Preserve editorial fields and local notes.
- Reset review approval only when evaluable content changes; mark AI enrichment stale and preserve version history.
- `qapi_max_requests_per_run` and `qapi_min_credit_reserve` are explicit settings.
- Zero max requests disables paid QAPI sync; dry-run performs no writes and reports projected cost.
- Record operator, parameters, pages, request count, budget, reserve, per-record errors, and resumable status in `Trivia Sync Run`.
- Scheduler remains off for paid sync unless explicitly enabled.

**Gate:** Mocked budget tests prove no paid call occurs when budget is zero/insufficient; re-running the same payload produces no duplicate; approved local fields survive source updates; dry-run performs no writes.

### Phase 3 — Reconciliation and syllabus versioning

**Scope:** Classification links and content-program tree ownership.

**Deliverables:**

- `reconcile_question_classification(question)` resolves exact external IDs first, then unambiguous names; ambiguous results remain unresolved.
- `sync_syllabus_tree(cargo, rows, source_version)` uses stable source paths and hashes.
- Disappeared nodes become obsolete; they are not deleted.
- Add cargo-specific coverage queries by subject, topic, review state, license state, and source.
- Add an idempotent backfill patch that reports unresolved/ambiguous counts.

**Gate:** Fixtures cover exact, missing, and ambiguous matches; backfill can be run twice without changing the second result; obsolete nodes remain queryable.

### Phase 4 — Editorial review and LMS Question projection

**Interfaces:**

```python
def review_question(question_name: str, decision: str, reason: str = "") -> dict: ...
def sync_lms_question(source) -> str: ...
```

**Required behavior:**

- Accept only `approved` or `rejected` decisions with reviewer permission.
- Record actor, timestamp, reason, and transition history.
- Validate supported LMS question types, answer shape, support text, source license, and redistribution approval.
- Project approved questions idempotently by `source_key` and content hash.
- Keep projection failures retryable without reverting editorial approval.
- Backfill legacy `LMS Question.trivia_qcode` records to pending local questions without touching unrelated LMS data.
- AI enrichment never approves content; changed AI data becomes eligible for projection only after review rules are satisfied.

**Gate:** Tests prove pending/rejected/unlicensed questions never project; projection is idempotent; failures preserve source and approval records; legacy links are additive.

### Phase 5 — Blueprint assembly and LMS quiz lifecycle

**Interfaces:**

```python
def build_simulado(prova_name: str) -> dict: ...
def publish_prova(prova_name: str, lesson_name: str) -> dict: ...
```

**Required behavior:**

- Validate cargo, course, lesson, syllabus topics, supported types, license, review state, and requested count.
- Calculate eligible pool before any write and fail atomically with missing criteria when insufficient.
- Preserve question order, marks, and exam version.
- Use native installed LMS placement APIs; never replace unrelated lesson content.
- `Draft -> Ready -> Published -> Superseded/Archived` transitions are explicit.
- Published exams with submissions cannot be edited in place.
- Supersession removes only the old exam's active placement while preserving old quiz/submissions.

**Gate:** Transaction tests prove insufficient pools create no rows; duplicate questions are rejected; supersession preserves old attempts and unrelated lesson content.

### Phase 6 — Public contest catalog and safe access

**Scope:** Frappe website routes and allowlisted APIs only after Phase 4/5.

**Required behavior:**

- Add publication state/date and curated public summary fields.
- Require published contest plus public/accessible LMS course for every public lookup.
- Return explicit DTOs, not serialized DocTypes.
- Exclude answers, explanations, raw payloads, private source fields, student data, and instructor-only content.
- Draft/private/mismatched records return not found or an empty result.

**Gate:** Anonymous and logged-in endpoint tests verify allowlists and fail-closed behavior; unpublished and mismatched records are unreachable.

### Phase 7 — Methodologies, lesson recipes, AI materials, and PDF

**Scope:** Only after editorial and publication controls are live.

**Deliverables:**

- Methodology/activity templates.
- Lesson and apostila recipe DocTypes with version, source hash, model, provenance, and approval state.
- `generate_lesson_material(recipe_name, level)` for `mais`, `180`, and `360`; output remains draft.
- `publish_lesson_material(recipe_name, level)` requires human approval and linked-course permission.
- `export_apostila(recipe_name, levels)` exports approved versions to a Frappe File with correct visibility.

**Gate:** Tests prove generated drafts cannot publish automatically, stale source hashes require regeneration, and private/public file permissions match the linked course policy.

### Phase 8 — Workspace, dashboard, runbooks, and release review

**Dashboard additions:**

- Pending review count and age.
- Failed/pending LMS projections.
- Source sync state, last run, request budget, reserve, and resumable page.
- Syllabus coverage and eligible question counts by contest cargo.
- Existing worker/AI metrics remain available.

**Workspace navigation:** Contest, Contest Cargo, Syllabus, Review Queue, Approved Bank, Exams/Simulados, Content Recipes, and Sync Runs, with role-aware shortcuts.

**Documentation:** Update README/runbooks for budgets, licenses, review/projection flow, backfill, quiz supersession, public publishing, PDF permissions, rollback, and operational recovery.

**Gate:** Full static review, all unit/integration tests, schema validation, JS checks, `git diff --check`, and a reviewed file-by-file diff. Do not run site migrations or ingestion as part of this code-only phase.

## 4. Refactoring priorities from the current baseline

These are the first code changes, before implementing the full plan:

1. Extract source-field ownership and editorial-field ownership into a shared mapping used by QAPI sync and future adapters.
2. Replace direct `_upsert` field copying with an allowlisted source-field update function.
3. Add `source_key` and content-hash transition logic before adding review buttons or LMS projection.
4. Move all run accounting into a shared run-context helper so QAPI and AI workers record identical metadata.
5. Add explicit permission checks to dashboard actions and future reviewer/projection APIs.
6. Keep the current dashboard, but extend its metrics only through server-side aggregate DTOs; never expose full DocTypes.
7. Preserve the current QAPI/AI tests and add regression tests before each refactor.

## 5. Definition of done

A phase is complete only when:

- Its interfaces exist and are documented.
- Its tests cover success, duplicate/idempotent retry, invalid input, permission failure, and partial failure.
- No existing DocType field or legacy LMS link was removed or renamed.
- No raw secrets, source payloads, answers, or private content leak through public responses/logs.
- The relevant budget and transaction invariants are proven by tests.
- `bench run-tests --app trivia_sync`, JSON/Python/JS validation, and `git diff --check` pass.
- Site-specific migrations, ingestion, AI generation, and publication are explicitly authorized and executed separately from code delivery.
