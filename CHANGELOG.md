# Changelog

## v0.6.0-rc.22 — Accept real assertion failures the verifier used to refuse; stop hard-coding one repository's alias

- **Why.** The first rc.21 held-out pass (two unseen repositories, 0/6) ended before any
  repair was evaluated. Reading the saved proofs showed three engine defects, not model
  luck:
  1. A correct reproduction was refused. A test using
     `assert.rejects(p, { instanceOf: Error, message: /blocked/ })` failed because the
     application connected to 127.0.0.1 instead of refusing, which is exactly the SSRF
     defect, but node:test labelled the failure `ERR_TEST_FAILURE`, not `ERR_ASSERTION`,
     so the evidence check said "no accepted assertion evidence" (Node 20, reproduced).
  2. A correct reproduction wrapped in `describe()` was refused. Node prints a second
     `not ok` block for the parent suite while `# fail` counts one, and the parser
     required the two numbers to match.
  3. The verifier prompt told every TypeScript project it has an `@/` alias and showed
     an example from file-sharing-app. On other repositories the model copied the shape
     and invented paths.
- **What changed.** `_node_assertion_failure` allows parent-suite blocks and accepts an
  `ERR_TEST_FAILURE` leaf only when its message is one Node's assert module generates;
  an application crash still fails. The alias paragraph is now built from the repository's
  own `tsconfig.json` (or says there is no alias). The prompt tells the model to assert a
  required refusal with a regular expression and not an `instanceOf` object.
- **What did not change.** Candidate generation, replay, hashes and the type-check.
- **Evidence.** Offline only; there has been no live run of rc.22. The new tests replay
  the saved held-out outputs. Heldout-1 and heldout-2 were used to find these defects, so
  they are development cases from now on; a held-out claim needs new issues.

## v0.6.0-rc.21 — Generated Node tests must import files that exist from where they are saved

- **Why.** In three rc.20 benchmark trials on `file-sharing-app-1` (base commit
  4f8b912, runtime `node-package`) no repair was ever evaluated. The verifier replies
  parsed cleanly under the rc.20 markers, but all three generated tests imported
  `../patchproof_runtime/typescript_module.mjs` and died with `ERR_MODULE_NOT_FOUND`
  before any assertion. That repository keeps a copy of the old loader at its root and
  its own `tests/format-baseline.test.mjs` imports it with `../`. `node-package` saved
  the generated test at the repository root, where `../` leaves the repository, so the
  model copied a line that was correct for the file it was copied from and wrong for
  the file it wrote. Two trials produced byte-identical tests, so the three trials are
  about two independent samples; the failure is systematic, not noise.
- **Placement.** `node-package` now uses the same rule `node-typescript` has had since
  rc.14: when the project already has `tests/*.test.mjs`, the generated test is saved as
  `tests/.test_patchproof_issue_N.test.mjs`. The leading dot keeps the still-failing
  regression out of the project's own `tests/*.test.mjs` baseline glob, and the explicit
  path in the regression command still runs it. Without such a directory placement is
  unchanged. Imports the model copies from existing tests now resolve.
- **Import check before the sandbox.** After the existing content validation, a
  generated `node-typescript` or `node-package` test is checked for literal relative
  imports (`import ... from`, `export ... from`, side-effect `import`, and literal
  `import()` / `require()`) that point to no file when resolved from the test's
  destination. Explicit extensions, extensionless paths, `.js` naming a `.ts` source and
  `.mjs` naming a `.mts` source all count as existing, and directories are never
  rejected. A failure is an ordinary validation error: it costs one of the three
  generations, not a sandbox run, and flows through the existing retry and
  repeated-diagnosis escalation. The diagnostic states where the test will be saved,
  where each import actually resolves, and, when a file with that name exists, the
  corrected relative path.
- **Specific feedback for a module that still fails to load.** `ERR_MODULE_NOT_FOUND`
  and `Cannot find module/package` output now gets its own classification ("generated
  test could not load a module") and a diagnosis that says it is a wrong import path or
  missing dependency, not evidence about the bug. Before, the same output received the
  advice meant for an operation that throws before the assertion, which for this failure
  was wrong and made the model wrap the same imports in `assert.doesNotReject`. A
  TypeScript `TS2307` is handled the same way. When the missing module is imported by
  application code and not by the test, the feedback keeps a hint to load it inside an
  awaited `assert.doesNotReject` callback so the defect still produces an assertion.
- **Prompt.** The `node-package` verifier guidance now says that relative paths resolve
  from the directory of the required filename, which may differ from where the existing
  tests live.
- **Scope and limits.** The check is static and conservative: it reads only literal
  relative specifiers, ignores bare names, `node:` built-ins and the `@/` alias, never
  inspects directory contents, and skips a specifier it cannot parse with confidence,
  because wrongly rejecting a valid test is worse than letting the sandbox report a bad
  one. It looks at the checked-out working tree, not the sandbox image. Path arguments
  passed to helper functions (for example `loadStandaloneTypeScript('lib/utils/format.ts')`)
  are not checked.
- **Evidence.** Offline only; there has been no live run of rc.21. Replaying the three
  recorded rc.20 tests at the new location against the repository at 4f8b912 gives an
  accepted `ERR_ASSERTION` failure on the unfixed code in all three, and all three pass
  with the recorded PR #2 fix. At the old location the new check rejects all three with
  the corrected path. The two distinct recorded QRcrafts tests produce no
  false positive. `file-sharing-app-1` motivated this change, so a pass there shows the
  fix works for that case, not that rc.21 is better in general; compare
  `v0.6.0-rc.20,v0.6.0-rc.21` and read `qrcrafts-1` as the check that nothing regressed.
- Tests: `tests/test_import_resolution.py` (30 cases). `action.yml` is unchanged.
  `README.md` and `examples/action-usage/shadow-fix.yml` now pin `v0.6.0-rc.21`.

## Unreleased — Benchmark harness (no engine change)

- **Per-case runtime override (`patchproof_config`).** A manifest case may now carry
  an object that the harness writes over the checkout's `patchproof.json` before each
  trial. Found by the first rc.21 smoke test on `file-sharing-app-1`: the verifier now
  passed, but all three candidates were rejected before evaluation because the pinned
  commit's `patchproof.json` selects `node-package`, which cannot edit the TypeScript
  file that holds the bug. The case now overrides it with `{"runtime": "node-typescript"}`.
  The object is validated like the engine's own file, recorded in each trial's
  `meta.json` with the hash of what it replaced, and named in the report's "Read before
  quoting" section. Earlier trials of that case (rc.20 t1-t3, rc.21 smoke) used the old
  pin and are not comparable. No engine file changed. See `docs/BENCHMARK.md`.
- Adds a manual **Benchmark** workflow (`.github/workflows/benchmark.yml`) and a
  standard-library harness (`bench/harness.py`) that runs one or more engine tags
  over a fixed case list, several trials each, without commenting on issues or
  opening pull requests. See `docs/BENCHMARK.md`.
- Every trial is classified against something the engine never saw: a per-case
  reference test (oracle) or a recorded label keyed by candidate diff. This separates
  correct accepts from false accepts, and false rejects (a correct candidate refused
  because of a bad generated test) from real failures, which the engine's own
  verdict cannot do.
- Verifier-stage failures (no repair ever evaluated) are reported separately so the
  effect of the rc.20 transport change is visible on its own.
- Cases are frozen in `bench/manifest.json` with issue text stored verbatim, a full
  base commit SHA, and a `dev` or `heldout` split; unfinished cases refuse to run.
- `APP_VERSION` is unchanged and no new tag is required. The harness is not part of
  the files exported to target repositories.

## v0.6.0-rc.20 — Verifier output as marked plain text instead of JSON

- **Why.** In the rc.16, rc.17 and rc.19 live QRcrafts #1 runs the generated regression
  test was the failing part, not the candidate repairs. The verifier returned source
  code inside a JSON string field, which stacked JSON escaping (`\\`, `\"`, `\n`) on
  top of TypeScript's own. The escaping mistakes seen in those tests fit a model
  confusing the two layers, but that is not proven to be the only cause. This change
  removes the avoidable layer for the verifier only; the planned benchmark will show
  how much it matters.
- Verifier reply format: test source between `<<<PATCHPROOF_TEST_BEGIN>>>` and
  `<<<PATCHPROOF_TEST_END>>>`, rationale between the `RATIONALE` markers. Markers are
  used instead of Markdown fences because TypeScript template literals use backticks.
- `parse_verifier_blocks` is strict: every marker exactly once, no swapped, nested or
  interleaved blocks, nothing but whitespace outside the blocks, no fenced or empty
  test block. Only the newline that delimits each marker is removed, so the source
  reaches the adapter byte for byte.
- Parse failures are `PatchProofError` with an actionable diagnostic, so the existing
  three-generation retry loop (and its repeated-diagnosis escalation) handles them.
  They are no longer collapsed into an `InferenceError` that aborts the run.
- `model_json` is split into a shared `_infer` plus `model_json` (solver, unchanged
  behavior) and `model_text` (verifier). `model_text` never sends `response_format`,
  since JSON mode would fight the marker format.
- Prompt wording that referred to JSON fields or `test_content` is updated in the
  verifier system and user prompts and in the parser-failure retry feedback. The
  TypeScript string guidance now says the source has no transport escaping.
- Unchanged: solver candidates still use JSON edits, retry counts, runtime adapters,
  sandbox image, lint and reproduction gates.
- Tests: marker parser (byte-exact escapes, every missing and duplicated marker,
  ordering, outside text, fences, empty blocks), transport (no JSON mode for text,
  JSON mode kept for solver, empty and truncated replies), and the updated retry and
  logging tests. All 13 existing TypeScript fixtures round-trip byte-exact. Live
  Nebius acceptance is pending.

## v0.6.0-rc.19 — First-attempt TypeScript string guidance

- Apply string-value guidance before the first TypeScript generation and every retry.
- Distinguish control characters, literal backslashes, source newlines and JSON transport escaping.
- Prefer String.raw for suitable backslash-heavy values without changing expected behavior.
- Preserve rc.18 lint fixes, bounded retries, test protection and acceptance gates.
- Include QRcrafts issue clarification as documentation, not a supplied regression.
- Live Nebius acceptance remains pending.

## v0.6.0-rc.18 — Useless-escape gate no longer fires on quote escapes; better retry guidance, 2026-09-28

- **What rc.17 showed (QRcrafts #1, second live Action run).** The new gate fired on the
  model's first two generations and the run was rejected before any candidate was
  evaluated. The only escapes it flagged were `\"` inside single-quoted strings. That
  sequence evaluates to the quote character the author meant, so the flag was a false
  positive, and the diagnostic (which only offered "write two backslashes") pointed the
  model the wrong way; generation 2 over-escaped further and generation 3 repeated it.
- Fix: a backslash before any quote character (`"`, `'`, `` ` ``) is no longer gated.
  The gate still catches escapes that silently drop an intended literal backslash
  (`\;`, `\,`, `\:`, `\c`, ...), including the real rc.16 test.
- The diagnostic now offers both remedies: remove the backslash if only the bare
  character is wanted, or write two backslashes for a literal backslash. The retry
  feedback also recommends `String.raw` for fixtures and expected values that contain
  literal backslashes, and warns against adding characters or extra escaping the issue
  does not ask for. This text is sent only after the gate fires, so first-generation
  prompts and other runtimes are unchanged.
- Offline check (no sandbox): both rc.17 generated tests were run against the real
  QRcrafts code with a correct escaping fix applied and still failed. Generation 1
  mixed up real CR/LF characters with their escaped text; generation 2 over-escaped
  the expected payload. So the tests were unsound, not the repairs. A `String.raw`
  version of the same test failed on the buggy code and passed on the correct fix.
- Not detectable by the engine: an expected value that is internally consistent
  but disagrees with the issue (for example CR/LF handling). The issue text is the
  contract; see docs/ACTION.md.
- Tests: quote-only-escape fixture (the real rc.17 generation 1) now passes the gate,
  `String.raw` fixture passes, rc.16's test is still rejected, and diagnostics are
  asserted. No adapter, solver prompt, retry-count or image change; no image rebuild.

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
