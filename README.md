# Trivia Sync

Editorial and public-exam contest tools for Frappe LMS. The app imports QAPI catalogs and questions, organizes contests, positions, and syllabus topics, requires editorial review and redistribution clearance before projecting questions to the LMS, and builds exams while preserving existing quizzes and attempts.

## Installation and setup

```bash
bench get-app https://github.com/bootstrapprx/trivia_sync --branch main
bench --site <site> install-app trivia_sync
bench --site <site> migrate
```

Open **Contest Setup** or **Trivia Sync Settings** to configure the QAPI endpoint and key. Secrets are stored as Password fields and must not be included in logs, issues, or shared shell commands. Back up an existing site before migration. The migration renames Portuguese DocTypes to ASCII English names and updates their Link fields while preserving their records; it also applies additive schema updates and legacy patches.

## Import and request budgets

QAPI may charge per request: exam listings cost 200 credits per call; other known requests cost 1. `qapi_max_requests_per_run=0` blocks paid sync. Set a credit limit and `qapi_min_credit_reserve` before running it. Dry-run estimates costs without writing records or calling paid endpoints. Paid scheduling is disabled by default; enable it only after setting a limit and reserve. Runs record the operator, parameters, requests, credits used, errors, and resume cursor. Review the available balance and filters before resuming an incomplete run through onboarding or the API.

Imports use stable source identities and update only source-owned fields. Editorial fields and local notes are preserved. A change to assessable content returns its approval to review and marks AI enrichment stale. Ambiguous exam board, organization, subject, topic, or position matches remain unlinked for manual reconciliation. Missing syllabus nodes become obsolete; they are not deleted.

## Rights, review, and LMS projection

License/attribution records and redistribution decisions are separate from editorial review. Record the license and explicitly confirm redistribution rights before projecting a question. A reviewer approves or rejects each question with a reason; AI never approves content.

Only valid questions that are editorially approved, cleared for redistribution, and have a recorded license can become `LMS Question` records. Projections are repeatable and versioned by content hash. An LMS question already used in a quiz is not changed when its source changes; a new version is created instead. Patches `v0_2` and `v0_3` additively backfill classifications and legacy LMS links. Review unresolved and ambiguous counts after migration.

## Contest positions, mock tests, and attempts

`Trivia Contest Position` links a contest, catalog position, existing LMS course, and syllabus. Imports do not create courses or lessons. Position coverage separates the full bank from eligible questions by topic, review, license, and source.

Build a `Trivia Exam` blueprint with blocks, topics, and requested counts. Assembly calculates the eligible pool first and writes no partial quiz when the pool is insufficient. Publishing requires an existing course and lesson plus write permission on the course. The active quiz is placed in lesson content without replacing unrelated blocks. Changes after submissions create a new version; old quizzes and submissions remain intact.

## Public catalog and assisted materials

The public catalog is available at `/concursos`. Only published contests linked to published LMS courses are shown. Public APIs do not expose answers, explanations, source payloads, or student data.

Lesson and study-guide recipes use approved, licensed sources. Assisted generation creates draft versions; a human must approve them before publication. Source changes make a version stale. PDFs are private by default and can be public only for a published, free course.

## Recovery and validation

Back up the site before `bench migrate`. If migration or a backfill fails, preserve logs and backups, fix the app, and rerun the idempotent migration/patch. Do not delete questions, quizzes, or attempts to work around an error. Projection failures can be retried without revoking approval. To stop paid requests, set the limit to zero and disable scheduling.

Run the app suite in the bench:

```bash
bench --site <site> run-tests --app trivia_sync
```

See [`docs/runbooks/trivia-sync-operations.md`](docs/runbooks/trivia-sync-operations.md) for recovery and publishing details.
