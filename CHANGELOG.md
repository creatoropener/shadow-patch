# Changelog

## v0.6.0-rc.12 — record rejected candidates' actual diffs, 2026-09-25

- First real run to reach `candidate-evaluation`: the regression test
  validated and correctly reproduced Issue #3 on the first attempt
  (`nvidia/nemotron-3-super-120b-a12b`, `reasoning_tokens=0` throughout,
  confirming rc.10/rc.11 hold for this model too). All three candidates
  correctly targeted `stream-cipher.ts` with the right general idea and
  still failed -- but nothing about what any of them actually proposed
  was recoverable: `proof.json` kept only `changed_files` (paths) and a
  line count, never the content. Same shape of blind spot as rc.9
  (validation rejections) and rc.11 (truncated responses), one stage
  further into the pipeline where nothing had reached until now.
- Added `unified_diff_text`, and every candidate record (passed or
  rejected) now carries a real unified diff of what it proposed against
  the original file. Application source only, never test or secret
  content, so the full diff is kept rather than truncated.
- The existing baseline-retry feedback had its own inline copy of this
  same diff-building logic; it now calls the shared helper instead.
- New tests: `unified_diff_text` directly, plus a full run through
  `proof.execute()` with three independently mocked candidate proposals,
  confirming each rejected candidate's record carries its own distinct,
  correctly-attributed diff rather than a shared or stale one.

No new image or target dependencies are required. Replace `proof.py` in
the target repository (`runtimes.py` is unchanged since rc.8). Live Issue #3
acceptance is still pending -- this release only makes a rejection
diagnosable, not the fix itself.

## v0.6.0-rc.11 — family-wide Nemotron detection, truncated-response logging, 2026-09-25

- rc.10 is confirmed working: a live run against `nvidia/Nemotron-3-Ultra-550b-a55b`
  showed `reasoning_tokens=0`, matching Lightning's earlier behavior. Silencing
  its hidden reasoning genuinely works through Nebius Token Factory.
- Raising `NEBIUS_MAX_TOKENS` to 32,000 (a workflow config change, not this
  release) did not fix the underlying problem: the same run's *visible* answer
  alone used the full 32,000-token budget (`final_chars=36470`) and still hit
  `finish_reason=length` without completing. What the model was actually
  generating was invisible to us -- `model_json` discarded the content on a
  length rejection without logging even a prefix, the same blind spot rc.9
  fixed for validation-stage rejections but not for this earlier, network-level
  one. Fixed: a length rejection now logs the first and last 200 characters of
  what was generated, which is usually enough to tell "a legitimate but long
  answer" apart from a repeating/degenerate pattern.
- Replaced the exact-string Nemotron allowlist in `build_model_request` with
  a family-wide match (`"nemotron" in model.lower()`). The three models tried
  so far have each used a different id casing/format (`NVIDIA-Nemotron-3-Nano-30B-A3B`,
  `Nemotron-3_5-Lightning`, `Nemotron-3-Ultra-550b-a55b`), and an exact
  allowlist means every new sibling risks a silent, un-noticed miss if its
  id doesn't match hardcoded casing exactly. The two models with an actual
  tuning history (Lightning's temperature/top_p, Nano's temperature) keep
  their specific overrides via a normalized (lowercased) comparison; any
  other Nemotron model only gets its reasoning silenced.
- Nebius Token Factory's Nemotron-3 lineup (per NVIDIA's own listing) also
  includes a "Super" 120B tier between the Nano/Lightning models tried so far
  and the 550B Ultra model -- smaller and reportedly faster than Ultra, with
  no observed reliability issues of its own yet since it hasn't been tried
  against this issue. The new family-wide match covers it (or any other
  Nemotron sibling) without needing its exact id added here first.

No new image or target dependencies are required. Replace `proof.py` in the
target repository (`runtimes.py` is unchanged since rc.8). Live Issue #3
acceptance is still pending.

## v0.6.0-rc.10 — silence reasoning for Nemotron-3-Ultra-550b-a55b, 2026-09-25

- Add `nvidia/Nemotron-3-Ultra-550b-a55b` to the set of models sent
  `chat_template_kwargs.enable_thinking: False`, matching its two smaller
  siblings already special-cased here. NVIDIA's own model card confirms this
  model supports the identical toggle. Unlike those two, its temperature is
  left as the caller's value rather than overridden -- there is no prior
  tuning history for it to justify a guess.
- `model_json`'s request-building is extracted into `build_model_request`,
  a pure function, so these per-model overrides are unit-tested directly
  instead of only through a live inference call.
- Built from a real Issue #3 run on this model: attempt 1 produced an
  otherwise well-formed regression test (correct imports, correctly wrapped
  in `assert.doesNotReject`) with a single missing `)` closing
  `new Uint8Array(`, correctly caught by the sandbox's real compiler at
  `43:2`. Attempt 2's retry spent 11,161 of the 12,000-token
  `NEBIUS_MAX_TOKENS` budget on hidden reasoning and was rejected on
  `finish_reason=length` before writing a final answer. This release only
  addresses the reasoning-budget cause; the syntax typo itself needed no
  engine change -- the sandbox already caught it precisely, with a usable
  diagnostic, exactly as designed.
- **Not changed, and worth doing separately:** `NEBIUS_MAX_TOKENS` is a
  GitHub Actions repo variable/secret, not engine code. This model's
  documented max output is far above the engine's 32,000-token ceiling;
  raising the configured budget (e.g. toward that ceiling) is a config
  change on the target repo, independent of this release, and is not
  guaranteed to be sufficient on its own without the fix above.
- Whether `enable_thinking: False` is honored through Nebius Token
  Factory specifically for this model is unverified from this environment
  (no network path to the inference endpoint here); the next real run is
  the actual test.

No new image or target dependencies are required. Replace `proof.py` in the
target repository (`runtimes.py` is unchanged since rc.8). Live Issue #3
acceptance is still pending.

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
