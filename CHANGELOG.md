# Changelog

## v0.6.0-rc.9 — generation-failure observability and repeat detection, 2026-09-25

- A rejected verifier-generation attempt (before any sandbox involvement) now
  logs to stderr: the JSON payload's field names and a 200-char prefix of
  `test_content`/`rationale` on a schema violation, or a 200-char prefix of
  `test_content` on a content-validation violation. Previously nothing about
  the model's actual output survived a generation-stage rejection anywhere.
- The rejected `PatchProofError` now carries the offending `test_content` as
  `.rejected_content` when available, for the next point below.
- When a validation diagnostic exactly repeats the immediately preceding
  attempt's diagnostic, the retry feedback now shows the model its own
  just-rejected test back verbatim with an explicit instruction to make the
  one described change, instead of appending the same paragraph a third time.
  A single occurrence is unaffected; only a genuine repeat escalates.
- Built directly from a live Issue #3 run (rc.8): two consecutive identical
  "missing async success guard" rejections followed by a schema violation on
  the third attempt. New tests reconstruct that exact sequence.

No new image or target dependencies are required. Replace `proof.py` in the
target repository (`runtimes.py` is unchanged since rc.8). Live Issue #3
acceptance is still pending.

## v0.6.0-rc.8 — missing test-runner imports, 2026-09-25

- Reject a generated TypeScript regression that calls `test` or `assert` without
  importing them (`import test from 'node:test'`, `import assert from 'node:assert/strict'`)
  before any sandbox execution. Under tsx these are not globals; the sandbox type-check
  otherwise fails with TS2582/TS2304, whose "install @types/jest" hint led the verifier
  model to resubmit the same file unchanged for the whole retry budget.
- Show the two imports in the verifier guidance instead of only naming node:test.
- When the compiler reports "Cannot find name" for `test`/`assert`, retry feedback now
  says it is a missing import (not a missing @types package) and names the exact lines;
  the generic API-signature advice is added only when other compiler errors are present.
- The path-alias validation (`'/@/'` → `'@/'`) already present in `runtimes.py` is part
  of this release. It shipped without a version bump, so earlier proof.json files carry
  `rc.7` even though they ran that check. rc.6 and rc.7 were not recorded here.
- Add fixtures from a real run: the generated test that failed with TS2582, its corrected
  form, and the TAP output showing the corrected test fails on the unfixed Issue #3 code
  with a recognised `ERR_ASSERTION`.

No new image or target dependencies are required. Replace `proof.py` and `runtimes.py` in
the target repository. Live Issue #3 acceptance is still pending.

## v0.6.0-rc.5 — stream contracts and bounded duplicate retries, 2026-09-23

- Skip duplicate regression executions and use remaining regeneration allowance
  with the original diagnosis; do not abort immediately or weaken assertion gates.
- Report generation attempts separately from actual sandbox executions, including
  validation failures and duplicate references. Existing bounded retry limits remain.
- Reject missing success guards on conventional generated TypeScript stream tests;
  the sandbox parser checks that awaited operations and consumption are inside the
  awaited async doesNotReject callback in the same test.
- Check unambiguous literal fixture coverage against explicit application chunkSize.
  Do not confuse source segmentation with application chunks or guess computed values.
- Test the actual execute control flow with mocked external services, plus parser
  checks for unrelated guards, escaped text fixtures and full/partial boundaries.

An existing rc.4 image and secrets can be reused. Live Issue #3 acceptance is still pending.

## v0.6.0-rc.4 — reproduction diagnostics and response contracts, 2026-09-22

- Explain operational Node test failures with a concrete doesNotReject pattern;
  require the complete successful application operation inside the callback,
  followed by its result assertion. Raw ERR_TEST_FAILURE remains rejected.
- Separate TypeScript parser errors, unused-binding failures and unavailable
  linter tooling so retry feedback matches the actual failure.
- Require one unambiguous JSON object and separate non-empty test_content and
  rationale fields. Reject duplicate keys, trailing data and malformed payloads;
  never silently strip metadata from generated source.
- Add fixtures from proof(7), actual Node TAP assertion tests, and pinned
  TypeScript parser integration checks in Engine Checks.

No new image or target dependencies are required for an already working rc.3
installation. This is not a new live acceptance result; Issue #3 still needs to
pass all verification gates before promoting v0.6.0.

## v0.6.0-rc.3 — semantic verifier hardening, 2026-09-22

- Reject generated TypeScript regressions with initialized bindings that never
  participate in the asserted behavior, both before sandbox execution and through
  a target-TypeScript AST check inside the sandbox.
- Require Web Streams round-trip regressions to connect every forward and inverse
  transform before collecting and asserting the final output.
- Give the verifier up to three bounded generation attempts with targeted semantic
  feedback when an incomplete test pipeline is rejected.
- Require solver proposals that modify binary framing to audit allocation sizes,
  offsets, producer/consumer symmetry, and normal/final emission paths.
- Add the exact faulty regression from the prior Issue #3 run and a corrected
  encrypt-to-decrypt fixture as local contract tests.

This remains a release candidate. The Issue #3 Nebius acceptance run is still the
promotion gate for final v0.6.0 support.

## v0.6.0-rc.2 — verifier contract hardening, 2026-09-22

- Type-check every generated `node-typescript` regression and its imported
  application modules against the target's own `tsconfig.json` before execution.
- Reject generated tests that hide API mismatches with TypeScript suppression or
  `any` casts.
- Require regressions to assert intended post-fix behavior rather than treating
  the current defect as an expected success.
- Retry a generated test that passes on the unfixed revision with explicit semantic
  feedback instead of stopping immediately.
- Add targeted retry diagnostics for invalid stream composition and Web Crypto key
  wrapper misuse while preserving conservative assertion-only reproduction evidence.

This remains a release candidate. The Issue #3 Nebius acceptance run is still the
promotion gate for final v0.6.0 support.

## v0.6.0-rc.1 — TypeScript runtime hardening, 2026-09-21

- Add an explicit `node-typescript` adapter using pinned `tsx` and normal project imports.
- Add the `CONTREE_IMAGE_NODE_TYPESCRIPT` workflow secret and v0.6 web image tag.
- Check image capabilities and the existing baseline before requesting verifier inference.
- Report configuration, runtime, repository-analysis and baseline failures as
  `BLOCKED` rather than incorrectly describing them as rejected repairs.
- Add engine-owned Web Streams byte-source/collection helpers and reject generated
  stream tests that bypass the deterministic plumbing.
- Auto-detect package roots with `tsconfig.json` as `node-typescript`.
- Add runtime contract CI and expose the failure stage in rejected reports.
- Retire the custom standalone TypeScript source loader from current installations.

This is a release candidate. The historical v0.5.5 green run remains the recorded
verification evidence until the file-sharing Issue #3 acceptance run completes.

## v0.5.5 — consolidated submission release, 2026-09-20

- Bring the demonstrated issue-to-PR engine into creatoropener/shadow-patch.
- Include runtime adapters, all required helpers, and the standalone TypeScript loader.
- Preserve existing tests as solver context while withholding the generated regression.
- Retry invalid proposals with validation feedback; omit redundant unchanged edits
  but reject proposals without a net source change.
- Allow one baseline correction per candidate without hidden-regression feedback.
- Preserve three candidate evaluations, protected regression checks and clean replay.
- Include the corrected PR notification and Python bytecode prevention/ignore rules.
- Add setup, architecture, evidence, screenshots, demo and submission materials.
- Move the previous v0.2 implementation and documentation intact to `legacy/v0.2/`.

This consolidation does not claim a new live run. The attached v0.5.5 report and
linked GitHub runs document the earlier demonstrated target execution.

Earlier prototype history: [legacy changelog](legacy/v0.2/CHANGELOG.md).
