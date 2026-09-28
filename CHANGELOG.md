# Changelog

## v0.6.0-rc.17 — Useless-escape gate; sandbox image removed from the report, 2026-09-28

- **Root cause (first live Action run, QRcrafts #1, rc.16 REJECTED).** The model wrote the
  regression test with `\;`, `\,`, `\:`, `\"` inside single-quoted strings and a stray
  `\c`. JavaScript drops the backslash from these identity escapes, so the fixture and the
  expected payload were not what the model intended and no correct fix could match. The
  syntax gate passed (`\;` is legal) and the pre-fix failure was a real assertion, so the
  reproduction gate accepted the test. Two of three candidates had correct WiFi escaping
  and were rejected by the bad test; the third had a stray space in its regex.
- New gate in `typescript_test_lint.mjs`: string and template literals are scanned with
  ESLint `no-useless-escape` semantics. Meaningful escapes (`\\ \n \r \t \b \f \v \0
  \xNN \uNNNN`, the literal's own quote, and `\`` / `\${` in templates) pass. Regex
  literals and tagged templates such as `String.raw` are not scanned. Each finding is
  reported as `file:line:col` with the fix (`\\;` for a literal backslash and `;`).
- New marker `PATCHPROOF_TYPESCRIPT_LITERAL=failed`. It is reported alongside, not instead
  of, the unused-binding marker. `classify_reproduction` treats it as a protected
  non-reproduction, and the retry feedback explains the dropped backslash. This is a gate
  with exact diagnostics on the existing verifier retry budget, not automatic repair.
- The verification report (PR description and issue comment) no longer prints the
  sandbox image UUID. `proof.json` keeps image identifiers for diagnostics.
- Tests: `tests/test_string_escape_gate.py` (classification, feedback, report redaction,
  and, with `TS_LINT_NODE_MODULES`, the real rc.16 test plus valid-escape, template,
  `String.raw`, regex and combined-failure cases). Fixtures added under `tests/fixtures/`.
- No adapter, solver prompt, retry-count or sandbox-image change; no image rebuild needed.

## v0.6.0-rc.16 — Shadow Patch as a reusable GitHub Action (beta), 2026-09-28

- New root `action.yml` (composite Action). A target repository now needs one
  workflow file that checks out its code and calls
  `creatoropener/shadow-patch@v0.6.0-rc.16`; no engine file is copied into it.
  The engine runs from `github.action_path` with `--repo "$GITHUB_WORKSPACE"`, so
  `proof.json`, the report and any edits land in the target checkout only.
- Secrets are passed as inputs from the caller (composite Actions cannot read the
  `secrets` context). Each adapter has an `image-*` input wired to the same
  `CONTREE_IMAGE_<ADAPTER>` variable the engine already derives; empty inputs fall
  back to `sandbox-image`, exactly as before.
- Behaviour is otherwise identical to the rc.15 copy-install workflow: same comment,
  artifact, PR and verdict-enforcement steps. New outputs: `verdict`,
  `pull-request-url`. The PR title now reads "Shadow Patch: verified repair".
- Added `examples/action-usage/shadow-fix.yml`, `docs/ACTION.md`, and
  `tests/test_action_manifest.py` (composite type, required inputs, every adapter's
  image wiring, bash shell on every run step, no `secrets` context, and that the
  example pins the current version). Engine Checks now installs PyYAML for it.
- Verified locally: actionlint is clean on the example and on the Action's steps;
  the engine imports from a separate folder and writes evidence into a different
  working repository. No live Nebius run has been made through the Action yet.
- No adapter, prompt, sandbox image or retry logic changed; no image rebuild needed.

## v0.6.0-rc.15 — TypeScript quoting guidance for the generator; issue-scoped fixtures stay in the issue, not the engine, 2026-09-27

- With rc.14's placement and types fixes in, QRcrafts issue #1 progressed
  cleanly to the reproduction stage but every attempt still failed with
  "generated TypeScript regression failed syntax parsing." Root cause was
  the model, not the engine: one fixture value needed a literal apostrophe
  (`Pa'ss`), and the model wrote it inside a single-quoted string with an
  under-escaped backslash-then-quote sequence, closing the string early.
  Confirmed via `reproduction_feedback()` that the model already receives
  the full previous content and exact parser error each retry -- this
  wasn't a missing-feedback problem, the model needed explicit guidance on
  the escaping mechanics themselves.
- `node-typescript`'s `verifier_guidance` now explicitly covers TypeScript
  string-quoting: prefer the quote style that avoids escaping a needed
  apostrophe (`"Pa'ss"` over `'Pa\'ss'`), spells out the correct source
  sequences for a literal backslash and a literal double quote, and
  explicitly instructs the generator never to sidestep a needed character
  by rewording or dropping it from a fixture. This is general TypeScript
  guidance (applies to every node-typescript issue), not WiFi-specific.
- Deliberately did NOT hardcode WiFi's reserved-character set (`;`, `,`,
  `:`, `\`) into the general verifier, and did NOT add any post-generation
  string-replacement "repair" of escaping -- either would risk silently
  changing test inputs or expected values, or narrow a general-purpose
  adapter around one issue. Scoping which punctuation a specific
  regression should exercise belongs in that issue's own body (it already
  flows into the generation prompt as-is via `Issue.body`), not in code.
- The bounded-retry budget and the syntax gate itself are unchanged:
  `PATCHPROOF_TYPESCRIPT_PARSE=failed` still gates before candidate
  evaluation and still counts toward the retry budget like any other
  rejection -- invalid source still never counts as reproduction evidence.
- Full local suite: 64 tests, same 2 pre-existing unrelated `openai`-not-
  installed errors as every prior round.

No image rebuild or target-repo file changes beyond `runtimes.py` and
`proof.py`; this doesn't touch the sandbox toolchain.

## v0.6.0-rc.14 — match existing tests/ convention for relative imports, restore node types after tsconfig restricts them, 2026-09-27

- rc.13's runtime-resolution fix worked against a live QRcrafts rerun (no
  more "lint tooling unavailable"), which let the pipeline progress far
  enough to hit two more real, previously-masked bugs rather than a clean
  run.
- `test_path()` always placed the generated test at the target repo's
  root. QRcrafts' own real tests live in `tests/` and import via
  `'../src/...'` (`tests/qrBuilder.test.ts`); the model faithfully copied
  that exact convention in its generated test, but placement at root
  turned `'../src/utils/qrBuilder.ts'` into a path outside the repo.
  `test_path()` now accepts the repo root and places the file inside
  `tests/` -- with a leading dot on the filename -- whenever an existing
  `tests/*{suffix}` file is already there, and keeps the previous root
  placement otherwise. The leading dot keeps the hidden, still-failing
  pre-fix regression out of the target's own shell-globbed baseline
  command (e.g. `tsx --test tests/*.test.ts`); confirmed empirically that
  without it, `CI=1 npm test` sweeps the regression file into the
  *baseline* result and reports it as a failing baseline test.
- QRcrafts' tsconfig restricts `"types": ["vite/client"]`, which is
  inherited by the synthesized check-only tsconfig via `extends` and
  silently drops @types/node's ambient `node:test`/`node:assert`
  declarations, even though @types/node is installed and tsx itself
  never type-checks at all. `typescript_check.py` now reads the
  project's own `types` array (if any) and adds `"node"` to it, and
  leaves `types` untouched entirely when the project doesn't restrict it
  (e.g. file-sharing-app, which has no `types` key).
- Validated against both real targets, not just QRcrafts: replayed
  QRcrafts' actual rejected attempt at the new location -- lint,
  type-check, and execution all now pass cleanly and correctly reproduce
  the real WiFi-escaping bug, with baseline unaffected. Replayed
  file-sharing-app's actual historical `test_patchproof_issue_3.test.ts`
  (issue #3, already VERIFIED) at the new location too -- lint,
  type-check, and baseline are all unchanged, confirming zero regression
  on the flagship result.
- New tests: `test_path()`'s tests/-detection and its root-placement
  fallback; `typescript_check.py`'s types-merge and its no-op when the
  project doesn't restrict types.

No new image or target dependencies are required -- this is a pure engine
change (`proof.py`, `runtimes.py`, `patchproof_runtime/typescript_check.py`).
Replace those three files in the target repository; the sandbox image from
rc.13 is unaffected.

## v0.6.0-rc.13 — resolve the TypeScript lint step from a pinned runtime, not the target repo, 2026-09-27

- QRcrafts (TypeScript pinned to `^7.0.2`, Microsoft's native Go-based
  compiler rewrite) failed every regression attempt identically with
  "generated TypeScript lint tooling unavailable" /
  `Cannot read properties of undefined (reading 'Latest')`, before a
  single candidate was ever evaluated. TypeScript 7.0.x does not ship
  the classic JS-facing Compiler API (`ts.ScriptTarget`, etc.) until
  7.1; `typescript_test_lint.mjs` required `typescript` from the target
  repo's own `node_modules`, so any repo pinned to bare TS 7.x broke
  this step for every one of its generated tests, regardless of content.
- `typescript_test_lint.mjs` now resolves `typescript` from a fixed
  runtime location (`/opt/patchproof/node`, the same pattern already
  used for `jsdom`) via a new `PATCHPROOF_TYPESCRIPT_RUNTIME`
  environment variable, rather than from the target repository.
  `prepare-image.yml` now pins `typescript@6.0.3` (the last classic-API
  release) into that same location alongside `tsx`; the image tag moves
  to `v0.7` so this can't be served from a cached `v0.6` image.
- The existing (previously always-skipped-locally)
  `TypeScriptLintIntegrationTests` now routes through
  `PATCHPROOF_TYPESCRIPT_RUNTIME` instead of symlinking into the target
  repo's own `node_modules`, since the fix means that's never read.
- A second, separate test class (`StructuralContractTests`,
  stream/chunk-coverage contract checks) used the identical old symlink
  pattern and was missed in the first pass -- it broke in engine-checks
  CI immediately after this shipped (`Cannot find module 'typescript'`,
  9 failures) since it never set the new environment variable and the
  new default (`/opt/patchproof/node`) doesn't exist on the CI runner.
  Fixed the same way; confirmed the full local suite clean using the
  exact CI-pinned `typescript@5.6.3` in a clean environment.
- Validated by reproducing the exact QRcrafts failure organically
  (`npm install typescript@7.0.2` in a real, throwaway target repo)
  before the fix and confirming it resolves via a real pinned
  `typescript@6.0.3` after, regardless of the target's own version;
  confirmed the structural checks (unused-binding, stream contract)
  still fire correctly through the new resolution path using the real
  fixture-based integration test.

Requires a sandbox image rebuild: run "Prepare Sandbox Image" (profile
`web` or `all`) and replace `CONTREE_IMAGE_NODE_TYPESCRIPT` with the new
`v0.7` UUID before rerunning any node-typescript target. Replace
`patchproof_runtime/typescript_test_lint.mjs`,
`.github/workflows/prepare-image.yml`, and `proof.py` in the target
repository; also update `tests/test_verifier_failures.py` and
`tests/test_stream_contracts.py` in shadow-patch itself.

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
