# Torben Email Hygiene Review Validator ADLC Scope

## Feature

`TORBEN-HYGIENE-REVIEW-VALIDATOR`

Make the Torben live-profile verifier prove that the weekly Gmail hygiene review is actually completing, not just that its cron script exists and compiles.

## Intent

The weekly hygiene review previously timed out before producing candidates. The live-profile verifier already checks script presence, compile status, cron errors, and several backend artifacts, but it did not validate the weekly hygiene review action artifact. This feature adds that missing productionization gate while preserving the approval boundary: the weekly review may stage recommendations, but it must not write to Gmail or perform external mutations.

## Acceptance Criteria

- If `torben_email_hygiene_review.py` is enabled, `torben-live-profile-verify` validates `state/torben-email-hygiene-review-actions-latest.json`.
- Missing, unreadable, stale, future-dated, malformed, or task-mismatched review artifacts fail live-profile verification.
- Review artifacts fail validation if they report `gmail_writes > 0` or `external_mutations > 0`.
- Review artifacts fail validation if `diagnostics.recommendation_count` does not match the actual recommendation list.
- LLM review fallback is surfaced as verifier warning metadata, but does not fail the run while the review completed and remained non-mutating.
- Validation is covered by unit tests and a live Torben profile canary.

## Work Items

- `THRV-001`: Add this ADLC scope artifact.
- `THRV-002`: Add hygiene review artifact health to `hermes_cli.signal_coo.live_profile_verify`.
- `THRV-003`: Add tests for fresh artifact pass, stale failure, mutation failure, and recommendation-count mismatch.
- `THRV-004`: Deploy the verifier to the repo and live Torben profile.
- `THRV-005`: Run compile, focused tests, full live-profile verifier tests, live Torben verifier canary, and `graphify update .`.

## Out Of Scope

- Changing hygiene recommendation scoring.
- Making deterministic LLM fallback a hard failure.
- Running Gmail cleanup mutations.
- Publishing or committing changes.
