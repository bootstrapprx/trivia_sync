# Trivia Sync Operations

## QAPI sync

1. Configure the base URL and key in Contest Setup. Do not put the key in shell arguments, tickets, or logs.
2. Set `qapi_max_requests_per_run` to the total credit budget and `qapi_min_credit_reserve` to the balance that must remain available. Exam listings cost 200 credits per request; other known requests cost 1. A zero limit disables paid requests.
3. Run a dry-run to review filters and estimated cost. Dry-run does not write data or consume paid requests.
4. Enable scheduling only after reviewing the budget, frequency, and reserve. Review `Trivia Sync Run` for the operator, parameters, pages, requests, failures, and resume cursor.
5. If a run stops, fix the cause, check the balance and filters again, then resume from the saved cursor. Replaying the same payload is idempotent.

## Review, licensing, and projection

- Treat source, license, attribution, and redistribution permission as separate records. Keep redistribution blocked when rights are unknown.
- Review content and metadata; record approval or rejection with a reason. Changes to assessable content require another review.
- Project only after format validation, editorial approval, licensing, and explicit redistribution clearance. Projection failures can be retried without removing the editorial decision.
- Backfills `v0_2` and `v0_3` are additive. After migration, review unresolved and duplicate links before making manual corrections.

## Exams and supersession

Before publishing, verify the contest position, LMS course and lesson, topics, eligible question count, and question rights. If the pool is insufficient, complete classification and review before retrying. To change an exam with submissions, build and publish a new version. The previous version, its attempts, and unrelated lesson content are preserved.

## Public publishing and PDFs

- Publish a contest only after reviewing its summary and linked public course. `/concursos` returns allowlisted editorial fields only.
- Never add answers, explanations, source payloads, or student data to the public DTO.
- AI materials start as drafts. Review provenance and version before approval; changed sources require regeneration and a new approval.
- Keep PDFs private for private, unpublished, or paid courses. A file may be public only when its course is published and free.

## Rollback and recovery

1. Back up the site and check available disk space before updating code or schema.
2. If migration or a patch fails, do not remove tables, questions, quizzes, files, or submissions. Save the traceback and stop workers or scheduling if repeated paid requests are possible.
3. Fix the app, rerun `bench --site <site> migrate`, and verify patch state. App backfills must remain idempotent.
4. If restoration is needed, restore the verified backup on an isolated site first. Check questions, LMS links, quizzes, and submissions before replacing the operational site.
5. To stop spending immediately, set the QAPI limit to zero and disable scheduling. This does not delete imported data.

## Pre-release checks

```bash
bench --site <site> run-tests --app trivia_sync
```

Also validate DocType/fixture JSON, Python compilation, JavaScript syntax, additive schema compatibility, and `git diff --check`. Site migration, ingestion, AI generation, and publication must be authorized and run separately for each site.
