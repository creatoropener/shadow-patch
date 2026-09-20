# Implementation milestones

## 0.2 update — external repository readiness (delivered)

Immutable base/head intake, separately drafted tests, locks, source allowlists,
pytest/Node adapters, case identity checks and reports are implemented. The SDK
constructor is corrected and pinned. 26 local tests pass; cloud calls remain unvalidated.
The QR repository URL/ZIP is still needed. See EXTERNAL_REPOSITORY.md and QR_TEST_PLAN.md.
Live account validation and GitHub publication below remain outstanding.

## M1 — Verification foundation (delivered)

Executable seeded Python/pytest demo, candidate rejection, fresh replay,
JSON/Markdown evidence, negative tests and cloud integration preview.
Local validation: eight unit tests pass; candidate three passes real pytest gates.

## M2 — Live Nebius integration

Configure account endpoint, immutable Python/pytest base and available NVIDIA model.
Validate SDK versions/imports, authentication and transport lifecycle; pin dependencies.
Add bounded remote operation polling, cancellation, run budgets and retention cleanup.
Capture base image UUID, model ID, token use and execution resource metrics in evidence.
Reject malformed model output with a bounded repair attempt. Make separate test and
patch calls, validate test intent, and retain exact accepted inputs for replay.
Acceptance: a real model-generated fix fails on original and passes in clean Nebius
branches and replay; logs show actual model and sandbox identifiers.

## M3 — GitHub issue to draft PR

Create a GitHub App with narrowly scoped repository access. Add HMAC-validated
`issues.labeled` webhook intake for `shadow-fix`; allowlist a seeded repository.
Use SQLite-backed jobs for the solo demo, delivery-ID deduplication, issue/base-SHA
locking, bounded retry and persistent status. Never execute work inside a webhook request.
Mint short-lived installation tokens only on the orchestrator. Clone public source
at an immutable commit; prepare a reusable sandbox checkpoint without credentials.
Publish the exact verified source plus locked regression test to a branch and open
a draft PR with evidence. Recheck base SHA, detect an existing branch/PR before retries,
and refuse stale evidence. Never auto-merge. A timeout must not create a duplicate PR.
Acceptance: label once, receive one verified PR; duplicate delivery produces no duplicate job.

## M4 — Demo and submission

Add a compact run page showing reproduce / candidates / replay / PR states using
real persisted events. Add a rejected-fix example. Record a video under three minutes.
Publish code and setup instructions, provide a working test build, and explain exactly
where NVIDIA inference and Nebius branch execution are used. Validate current submission
deadline and eligibility directly before submitting.

## Inputs required next

- Repository URL for the new project and chosen seeded demo repository.
- Nebius Sandbox access, endpoint and prepared image identifier.
- Available NVIDIA model ID and API key configured as a secret, not pasted into chat.
- GitHub App ID, installation ID, private key and webhook secret when wiring M3.
