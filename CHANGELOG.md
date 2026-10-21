# Changelog

## v0.6.0-rc.39 — a transient Sandbox API failure is retried and classified as infrastructure

A file-sharing-app run on rc.38 ended with `Stage: runtime-preflight` and `ApiStatusCodeError(... GET .../sandboxes/v1/files/a26c0dde..., status=500, error='Internal Server Error')`. The file is one of the engine's own helpers (`pytest_check.py`): the SDK looks a file up by hash before uploading it, and that lookup failed on the server.

- **No retry.** `sandbox_workspace` ran its three steps once, so one transient 500 ended the run. Each step builds a new state from the previous one, so repeating it has no side effect. `sandbox_retry` now retries them twice (5 s, 15 s) when the failure is the Sandbox API's own: an `ApiStatusCodeError` with `status` 5xx, 408 or 429, or an `ApiTimeoutError` or `ContreeTransportError`. A command that fails inside the sandbox, a 4xx answer and any other exception are raised at once.
- **Wrong bucket.** `stage in BLOCKED_STAGES` made it `readiness_blocked`, which says "fix your repository". `classify_outcome` now matches the SDK's own error text (`ApiStatusCodeError(... status=5xx|408|429`, `ApiTimeoutError(`, `ContreeTransportError(`) first and records `infrastructure_error`, at any stage.
- **Version.** 0.6.0-rc.39 (`APP_VERSION`, example pin, benchmark default, README).

**Checked.** Full suite: 520 tests pass on the Node 20 CI toolchain. `tests/test_sandbox_retry.py` (15 tests): the transient predicate against the real SDK classes and look-alikes, two failures then success (delays 5 s, 15 s), three failures re-raised, 404 and bugs not retried, the whole `sandbox_workspace` surviving one 500 and stopping on three, and the live error text classified as `infrastructure_error` while a real setup error and a 403 stay `readiness_blocked`.

**Not covered.** Candidate evaluation and clean replay are not retried; a Sandbox API error inside a candidate is still recorded as that candidate failing (the run isolates candidate exceptions). No live run.

## v0.6.0-rc.38 — the root-URL refusal only applies to tests that read a resolved address

Two live runs verified after rc.37 was cut. **Tabloop #2 on rc.36** (static-web, first live success): attempts 1 and 2 read `form.action` at `https://patchproof.invalid/` and passed on the unfixed page; the model then switched to `form.getAttribute('action') === 'thank-you.html'`, which fails on the unfixed page, and all three candidates (action `/thank-you.html` to `thank-you.html`) passed clean replay. **Aegisscan #3 on rc.37** (node-typescript): one test, three candidates widening the Axios version regex to accept `0.19.2`, clean replay passed.

- **Defect in rc.37's rule.** Replaying the Tabloop success through rc.37 showed that `root_url_for_served_path_issue` would have refused it (root url, issue mentions a subpath), costing retries or the run. The root URL only hides the bug from an assertion on a *resolved* address. rc.38 refuses only when the test also reads one (`.action`, `.href`, `.src`, `.formAction`, `location.href`, `location.pathname`, ignoring assignments). Both tests that failed on rc.36 read `form.action` and are still refused; the success reads `getAttribute('action')` and is not.
- **Version.** 0.6.0-rc.38 (`APP_VERSION`, example pin, benchmark default, README). Static-web only; `node-typescript` behavior is unchanged.

**Checked.** `tests/test_static_web.py` 55 → 58 tests, including the exact rc.36 success test through the whole engine (verified, one model request) and through the validator (not refused). Full suite: 505 tests pass on the Node 20 CI toolchain.

**What the two successes are, and are not.**
- The Tabloop test pins the literal `thank-you.html`. The issue asks for "a relative path that matches the rest of the project", so a correct fix such as `./thank-you.html` would fail it. It verifies the issue's stated fix, not behavior under a subpath.
- The Aegisscan test also asserts `severity === 'HIGH'` and `cvssScore === 7.4`. The issue states neither; they presumably come from the existing rule's metadata, which the repair does not touch. A reviewer should confirm.
- Both are the author's own repositories, and both are development cases now: Tabloop #2 was run four times across three engine releases written from its failures, and Aegisscan was used for tuning in rc.22–rc.29. Neither counts toward the unseen-repository evidence the fresh set is meant to produce.
- The Tabloop success was on rc.36, not the current engine; rc.37/38 have not been run live on static-web.

## v0.6.0-rc.37 — a static-web test that cannot fail is refused and explained

The Tabloop #2 run on rc.36 (`bec7431b-proof.json`) confirmed rc.36: jsdom 24.1.3 loaded on Node v20.19.2, baseline `# tests 1`, discovery probe found, `__dirname` no longer used. All attempts then ended `test passed on the unfixed revision`.

- **Cause.** All three tests created the page with `url: 'https://patchproof.invalid/'` and asserted `form.action === 'https://patchproof.invalid/thank-you.html'`. At the host root a root-absolute action and a relative one resolve to that same string, so the unfixed page passes. The bug (a form posting to `/thank-you.html` when the site is served under a subpath) only exists under a path such as `/Tabloop/`. The adapter's own prompt said "Set url: 'https://patchproof.invalid/'", so this was the engine pushing the model into it. The rc.34 live test, which used `/Tabloop/`, was sound; rc.35 and rc.36 tests all used the root.
- **Wrong advice on retry.** The feedback for "passed on the unfixed revision" told the model to rewrite the assertion with `doesNotReject`, which has no meaning for a DOM test. The model resubmitted identical content (attempt 3 was a duplicate of attempt 2) and the run stopped on repeated output.
- **Prompt.** The static-web prompt now asks for an address on `patchproof.invalid` and says the path matters: when the issue is about where the page is served, put that path in the url.
- **New validator rule** (`runtimes.py`, `root_url_for_served_path_issue`, in `validate_generated_pins`): if the issue text mentions a subpath, sub-directory or folder, base path/URL/href, path prefix, deploy path, staging or GitHub Pages, and the test's JSDOM `url` has no path, the test is refused before any sandbox run with the replacement advice and retried. It is a heuristic on the issue's wording: a bug that needs a path but never says so is not caught, and a test that legitimately needs the root for such an issue gets a retry it does not need (three attempts in all).
- **Static-page feedback** (`proof.py`, `reproduction_feedback(..., runtime_id)`): for `static-web` the "passed on the unfixed revision" feedback now says the test never reached the defect, points at the JSDOM url or event, and drops the `doesNotReject` advice. Other runtimes are unchanged.
- **Version.** `APP_VERSION`, the example workflow pin, the benchmark default engine and the README are 0.6.0-rc.37. rc.35 and rc.36 stay as published.

**Checked.** `tests/test_static_web.py`: 33 → 55 tests. The exact test the live model wrote on rc.36 is flagged for this issue; a subpath test and an unrelated issue are not; a native pipeline run where the root-URL reply is refused before executing, the model sees the reason, and the second reply (subpath) verifies. Full suite: 502 tests pass on the Node 20 CI toolchain.

**Not covered.** No live run on rc.37. This does not make the model write a correct test; it removes one way the engine itself steered it wrong and one refusal that taught it nothing. The valid-test rate on static pages is still unmeasured.

## v0.6.0-rc.36 — a jsdom that cannot load is caught before any model request

The first live `static-web` run on rc.35 (Tabloop #2, `eef15ec1-proof.json`) passed everything rc.35 added (runtime detected, `npm ci`, baseline `# tests 1`, discovery probe found) and ended `no_reproduction` after three identical failures. Every generated test died at load time, inside the project's jsdom:

```
node_modules/undici/lib/interceptor/decompress.js:78
  zstd: createZstdDecompress.bind(null, ...)
TypeError: Cannot read properties of undefined (reading 'bind')
```

- **Cause, reproduced.** The project's lockfile had resolved jsdom 30, which depends on undici 8; undici 8 reads `zlib.createZstdDecompress` on load, and Node 20.19.2 (the sandbox's Node) has no such function. Reproduced here with a clean `npm install jsdom@30.1.3` under Node 20.19.2: same stack, same line. jsdom 24.1.3, 25, 26, 27, 28.1.0 and 29.1.1 load on Node 20; 30.0.0 and 30.1.3 do not (jsdom 30 declares Node `^22.22.2 || ^24.15.0 || >=26`). I could not reproduce it with any undici 7.x.
- **The guide caused it.** `docs/RUN_GUIDE.md`, `RELEASE.md` and the validator messages said `npm install --save-dev jsdom`, which installs the newest jsdom. rc.35 testing used jsdom 24.1.3 only (the sandbox copy), so the replay never met the version a real project would resolve. That was the gap.
- **A second defect hid behind it.** All three generated tests read the page with `path.resolve(__dirname, '..')`. In an ES module `__dirname` is not defined, and `..` from the repository root is the wrong folder anyway. With a loadable jsdom the run would have stopped on `ReferenceError`, again reported only as "failed without accepted assertion evidence".
- **New check before inference** (`proof.py`, `STATIC_WEB_JSDOM_PROBE`): in the sandbox, from the repository, load `jsdom` and construct a `JSDOM`. On failure the run stops with `readiness_blocked` (stage `baseline`, `before_inference` true) and a message naming the installed jsdom version, the Node version and the fix (`npm install --save-dev jsdom@24.1.3`). A jsdom that is declared but missing after `npm ci` is reported separately; this closes the "declared but never installed" limit listed under rc.35. The result is recorded in `baseline.jsdom_probe` (`loaded`, `jsdom_version`, `node_version`, `detail`).
- **No silent fallback.** The helper (`patchproof_runtime/jsdom.mjs`) still uses the sandbox copy only when the project has no jsdom at all, and still lets a broken project jsdom fail loudly. Falling back would make the sandbox pass on a jsdom that a Node 20 CI cannot load, which is exactly the sandbox/checkout difference the helper exists to remove.
- **ES-module globals** (`runtimes.py`, `commonjs_globals_used`): a static-web test that uses `__dirname`, `__filename` or `require` without defining them is refused by the validator with the replacement (`fs.readFileSync(new URL('./index.html', import.meta.url), 'utf8')`) and retried; the prompt says so up front. All three live tests are caught by it.
- **Guidance pinned.** Every instruction, message and doc now says `npm install --save-dev jsdom@24.1.3`.
- **Version.** `APP_VERSION`, the example workflow pin, the benchmark default engine and the README are 0.6.0-rc.36. rc.35 stays as published.

**Checked.** `tests/test_static_web.py` grows from 33 to 47 tests: the probe command against a fake jsdom that throws the exact undici error, a working one, a missing one and a throwing constructor, run under real Node; native pipeline runs where a broken jsdom stops before the first model request and buckets as `readiness_blocked`, where a working jsdom is recorded, and where a `__dirname` test gets a retry and then verifies. The probe command was also run on real installs under Node 20.19.2 (30.1.3 fails; 24.1.3 and 28.1.0 pass).

**Not covered.** No live Nebius run on rc.36. The sandbox's Node 20.19.2 is taken from the Tabloop proof (`preflight_output`); if the image changes, the probe reports whatever Node it finds. jsdom 24.1.3 was tested against the Tabloop page only. The model can still write a test that is wrong in other ways; this release only removes two failures that were not the model's.

## v0.6.0-rc.35 — the static-web adapter can complete a run (and nothing else changes)

Tabloop #2 on rc.34 was the first `static-web` run with a correct setup, and it showed that the adapter could never complete one. The model followed the adapter's own prompt, which required `createRequire('/opt/patchproof/node/package.json')('jsdom')`, and `support_files` in `proof.py` then raised `Regression uses a sandbox-only dependency` for any test containing `/opt/patchproof/`. That error is a plain `PatchProofError`, outside the retry loop, so the run ended with `attempts: []` and the test never executed. Behind it was a second defect: the adapter's baseline, `node /patchproof/static_web_check.mjs index.html`, is a syntax check that runs no test file, so the ordinary-CI discovery gate (rc.25) had nothing that could run and fail the frozen test. The earlier "held-out 0/3 on static-web" result is consistent with this, but those runs were not re-read.

- **A portable jsdom loader.** `patchproof_runtime/jsdom.mjs` is delivered beside the test as `patchproof_helpers/jsdom.mjs`, the same way the Web Streams helper is. It uses the repository's own `jsdom` first, then the copy preinstalled in the sandbox image, and otherwise fails with "add it with `npm install --save-dev jsdom`". It lets exactly one thing differ between the sandbox and a fresh checkout: where jsdom comes from. The prompt now asks for `import { JSDOM } from './patchproof_helpers/jsdom.mjs';`.
- **The legacy loader line is rewritten, not refused.** Generation turns the exact rc.34 statement (any spacing, with or without the semicolon) into that import before validation and hashing, so a model that still writes it is accepted. Any other sandbox path in a static-web test is now a retryable validator message that includes the replacement line, not a run-ending error. The old check in `support_files` stays as a backstop for every adapter.
- **The baseline runs the project's tests.** When `package.json` has a `test` script, the static-web baseline is the syntax check followed by `CI=1 <manager> test`, and dependencies are installed first, as for `node-package`. Without a test script it stays the syntax check alone.
- **Two checks before any model request.** (1) `static_web_project_problems`: a `package.json` with a `test` script and a declared `jsdom` (dependencies, devDependencies or optionalDependencies). Without a declaration a delivered test would pass in the sandbox and fail on a fresh checkout. This stops at `runtime-detection`, before the sandbox starts. (2) A discovery probe: an always-failing `test_patchproof_probe.test.mjs` is planted where the generated test will go, and `npm test` must run it. A stub script (`echo ok`) or a script that reads another folder stops at `baseline` with `readiness_blocked` and an actionable message, and `proof.json` records `baseline.discovery_probe`. Both are `readiness_blocked` with `before_inference: true`; no tokens are spent.
- **Recommended script: `"test": "node --test"`.** Found while testing: `node --test *.test.mjs` fails on Node 20 while no matching file exists (the shell passes the literal pattern), so a site with no tests would fail its own baseline. Plain `node --test` finds `*.test.mjs` itself and passes with zero tests. The messages and `docs/RUN_GUIDE.md` say so.
- **Other adapters.** The static-web branches are all gated on `adapter.id == "static-web"`. The shared code that changed is `support_files` (same helper names for Web Streams, plus jsdom) and the version string. The `node-typescript` pipeline tests, which run real `tsc`, `tsx` and `node:test`, pass.
- **Version.** `APP_VERSION`, the example workflow pin, the benchmark default engine and the README are 0.6.0-rc.35. A behavior change under the old name would make rc.34 evidence unreadable.
- `tools/export_target.py` ships the helper; `.github/workflows/engine-checks.yml` installs jsdom, exposes it at `/opt/patchproof/node` (where the image keeps it) and syntax-checks the helper.

**Checked.** `tests/test_static_web.py` (new, 33 tests): adapter and validator unit tests, the helper under real Node (repository copy wins, sandbox fallback, clear error, unrelated errors not swallowed), and native pipeline runs with the real jsdom and `node:test`. The central one feeds **the exact test the live model wrote on rc.34** (from the Tabloop #2 proof) through the whole engine with a scripted model: it is canonicalized, reproduces on the unfixed page, a candidate that makes the form action relative passes regression, the clean replay passes, the verdict is `verified`, and `pr_files` is the fix, the frozen test and the helper. A stub script, a script that misses the folder, no `package.json` and a missing jsdom declaration each stop before any model request. Separately, the delivered files were replayed by hand on a copy of the real Tabloop repository under Node 20.19.2: baseline `# tests 0` and exit 0; with the test planted, the unfixed page fails with `actual 'https://patchproof.invalid/thank-you.html'` against `expected '.../Tabloop/thank-you.html'`; with `action="thank-you.html"` it passes, and the form action is the only difference. Two rc.24 tests that asserted the old loader line now assert the new one.

**Not covered.** No live Nebius run. The image's jsdom (24.1.3) is only the fallback; a project's own jsdom may be a different version. jsdom still cannot test layout. The model can still write a bad test; the engine's existing gates (import check, wording pins, reproduction, discovery) apply as before. The 0/3 held-out figure for static-web predates this release and is not updated. A project that declares jsdom but never installs it in CI (no lockfile, bootstrap skipped) is not detected beyond the declaration check.

## After v0.6.0-rc.34 — `docs/RUN_GUIDE.md`: the run instructions are now specific to what the engine supports (no engine change, no new tag)

The Tabloop #1 and PlanMorph #1/#2 runs were set up from `docs/ACTION.md`, whose "Prepare the target repository" step was five lines. It did not say that the project must type-check, that `npm test` must run a test the engine adds, that the sandbox's Node 20 does not expand quoted globs, that the code under test must run offline, that `patchproof.json` must name the runtime the repository really uses, or that an older sandbox image has no `typescript`. Each of those produced a run that stopped before saying anything about the engine: Tabloop at `baseline-source-check` (`"checkJs": flase`), PlanMorph at `verifier_invalid` (image without `typescript`, readiness still "ready") and then `no_reproduction` (every test died on a live Anthropic API call).

- **`docs/RUN_GUIDE.md`** (new): a fit table for the issue (which runtime, which verifier, what evidence exists), an eight-item repository checklist with the failure each item prevents, a pre-run command block (Node 20, `tsc`, `npm test`, `tools/preflight_base.py`), an issue template matching the spec profile's grounding rules, workflow and image settings, a symptom-to-fix table keyed on `outcome.bucket`/`stage`/`error`, and the three failed setups with what a fitting one looks like.
- **`docs/ACTION.md`** step 4 now points to it and carries the short version. **`README.md`** links it from the install section.
- **Found by the next run (Tabloop #2, `static-web`): the static-web adapter cannot complete a run.** The adapter's verifier guidance requires `createRequire('/opt/patchproof/node/package.json')('jsdom')` (rc.24 made the import check demand exactly that line), and `support_files` in `proof.py` raises "Regression uses a sandbox-only dependency" for any test containing `/opt/patchproof/`. Reproduced with the proof's test and with the guidance line alone. Separately, the adapter's baseline is `node /patchproof/static_web_check.mjs <entry>`, a syntax check that runs no test file, so the ordinary-CI discovery gate has nothing that could run and fail the frozen test. Both are read from the code; only the first was executed. The guide said not to use `static-web` until fixed; rc.35 (above) is that fix.
- Not changed: the engine, the example workflow, the readiness check. Readiness still reports "ready" on an image without `typescript`; that gap is documented, not fixed.

## After v0.6.0-rc.34 — fresh-set tooling and the first fresh case (no engine change, no new tag)

- **`tools/preflight_base.py`.** Checks a base commit before a run is spent on it, under Node 20 (the benchmark image's Node; it refuses another major unless told otherwise): runtime detection, the project's own baseline (green and non-empty), the ordinary-CI discovery gate with a planted failing probe, and an import probe that imports the target export the way the compiled examples do. It would have flagged the file-sharing-app-1 pin problem in rc.26, and it flags cases that discover tests but cannot load the module (ipregistry-javascript).
- **`tools/verify_case_spec.py`.** Offline oracle check with no model: validates a hand-written specification against the issue with the engine's own validator, compiles the test, and runs it on the base (reproduction) and on the upstream fixed commit (must pass).
- **`bench/manifest.json`: `fresh-overlaykit-1`** (Hailong-am/openapi-overlaykit, external, held-out split, base `553a949`, `test_directory: test`). Verified with both tools under Node 20.19.2. The protocol is still `development`; freezing is a separate step once the case list is final.
- **`docs/FRESH_SET.md`** records the selection checks, the tools, and the candidates already ruled out and why. Only this one external case passed every check so far.
- No engine file changed; the engine stays v0.6.0-rc.34.

## After v0.6.0-rc.34 — example workflow: `agent-mode` is `legacy` again (no engine change, no new tag)

`examples/action-usage/shadow-fix.yml` had shipped with `agent-mode: bounded` switched on since rc.26, under the comment "Enable only for the Node/TypeScript Batch 2 profile". A repository that copied the file ran bounded mode without choosing it. PlanMorph issue #2 did: the bounded verifier read `server.js` lines 116-120 four times in a row (steps 5-8 of its 8-step allocation) and stopped with `budget_exhausted` before writing any test; only 52,029 of 250,000 tokens were used. Bounded mode has never completed a live run, and every verified run so far used legacy mode.

- The example now sets `agent-mode: legacy` and carries a commented `# verifier-profile: spec` line. It still pins rc.34.
- The same run showed two limits that are not engine faults. The Node/TypeScript adapter does not list `.html` as source, so `public/index.html`, where the reported `post()` helper lives, was not in the repository map (10 files, no `public/`). And PlanMorph's `npm test` is `node --import tsx --test`, which found 0 tests on Node 20, so ordinary CI would not have discovered a `.ts` regression either.
- Not changed: the engine, the bounded verifier's repeated-read behaviour, and the adapter's file types.

## After v0.6.0-rc.34 — manifest only, no new tag: file-sharing-app-1 is pinned to a commit whose own `npm test` discovers a TypeScript regression

The fifth live specification run (rc.34, `verifier=spec`) stopped file-sharing-app-1 at the ordinary-CI discovery gate, not at the specification. The specification stage worked: seven examples were grounded in the issue's table, six of them failed on the unfixed code, and the reproduction was accepted. The run then stopped with `readiness_blocked` / `blocked_setup`, "Ordinary project CI did not reproduce the frozen regression", because at the pinned base `4f8b912` the project's `npm test` is `node --test --test-reporter=tap tests/*.test.mjs`. The node-typescript adapter writes a `.ts` regression, and with no `.ts` file in `tests/` it writes it at the repository root, so `npm test` never runs it. The gate was added in rc.25. The mismatch was written down in docs/BATCH2.md since rc.26 and was not raised when the case was re-run on later releases. The recorded v0.5.5 run did not hit it because it used the `node-package` runtime with a root-level `.mjs` regression and predates the gate.

- **New pin.** `bench/manifest.json` pins `file-sharing-app-1` to `bf939812d176434f0b11dcdd9df4260dbd80dc8f`, the last commit before the issue #3 repair was merged. `lib/utils/format.ts` is byte-identical to the one at `4f8b912` (the file has one commit in its history), so the issue, the scope (`lib/utils/format.ts`, `formatEta` protected) and the frozen issue text are unchanged. Its `package.json` runs `tsx --test --test-reporter=tap tests/*.test.ts`, its lockfile contains tsx 4.23.15 and typescript 5.6.3, and `tests/format-baseline.test.ts` exists, so the adapter places the regression in `tests/` and ordinary CI discovers it.
- **Checked outside the engine.** The tree at `bf93981` was extracted and installed with `npm ci --ignore-scripts` under Node 20.19.2 (the sandbox's version). With the seven-example regression that rc.34 compiled from the proof (compiled by `spec_profile.compile_test` for `tests/test_patchproof_issue_1.test.ts`), `CI=1 npm test` ran 10 tests: the 3 baseline tests and `e1` passed, `e2`–`e7` failed with `ERR_ASSERTION` and their `PATCHPROOF_EXAMPLE` markers. With `formatBytes` corrected to return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`, all 10 passed. This is a local simulation of the gate's check, not a live run.
- **Not covered.** Candidate repair, regression, clean replay and delivery have not run on this pin since the gate was added. rc.20/rc.21 trials and the recorded v0.5.5 evidence were taken at `4f8b912` and are not comparable; the recorded evidence files are unchanged. Changing the manifest changes the benchmark protocol id.
- **Tests.** `tests/test_bench_harness.py` asserted that the pin equals the v0.5.5 run commit. It now asserts the new pin, that the recorded evidence still names `4f8b912`, and that the case keeps the evidence's issue title and the node-typescript runtime.
- **Engine Checks fix.** `CliTests.test_validate_and_unready_plan_exit_codes` asserted that `validate --ready` on the shipped manifest exits 1 because the held-out cases were placeholders. Once `heldout-3` and `heldout-4` were filled in, the command correctly exited 0 and the assertion failed (441 of 442 tests passed in CI). The assertion now expects 1 only while some case still carries a `TODO` or `<<` placeholder and 0 otherwise; the temporary-manifest part of the same test still covers the placeholder case. Checked against a copy of the manifest with both held-out cases filled in: `validate --ready` exits 0.
- No engine file changed; the engine stays v0.6.0-rc.34 and no tag is needed.

## v0.6.0-rc.34 — A table's column titles in front of a row are accepted (and ignored for grounding), the END marker written as a JSON string is tolerated, and every refused specification is logged with the model's own text

The fourth live specification run (rc.33, `verifier=spec`, legacy mode) had two outcomes. qrcrafts-1 was verified end to end on the specification profile: the engine kept one grounded example and refused a second one whose quotation was not in the issue, the compiled test failed on the unfixed code with an assertion on the returned payload, all three candidate repairs passed regression, and the clean replay passed. file-sharing-app-1 stopped `spec_invalid` after six model requests.

The file-sharing-app-1 run disproved the rc.33 premise. rc.33 told the model, per example, that its quotation (column titles plus the example's own row) was not one passage, and named the exact row to quote. The model sent the same header-plus-row quotations again, so only e1 survived and passed on the unfixed code. When the run asked for another specification the model changed shape and put a single `evidence` field at the top level of the object, which the format does not allow; it sent that three times with identical output and the repeat guard stopped the run. The first request of each round also ended `"<<<PATCHPROOF_SPEC_END>>>"}`, the marker written as the last JSON string followed by a closing brace, which the rc.33 punctuation allowance did not cover because it excluded braces. A prompt or a message that the model does not act on is not a fix, so rc.34 changes what the engine accepts, without changing what grounds a value.

- **Column titles in front of a row.** A quotation may now begin with one or two short lines (at most 120 characters each) that appear earlier in the issue than the rest of the quotation; the remainder must still be one contiguous passage, and every string and number of the example must be in that remainder. The leading lines are context only: a value that appears only in them is refused, so nothing is easier to ground than before, and the proof shows what was quoted (`evidence`) next to the passage that grounded it (`issue_span`). This reverses the rc.33 rule that a header plus a distant row is refused outright. A longer gap (more than two lines set aside, lines out of order, or skipped lines inside the passage) is still refused with the rc.33 message, now saying that a short header may come first, and still naming the issue line that holds the example's values.
- **JSON punctuation outside the markers is dropped.** If the only text outside the markers is quotes, commas, semicolons, colons, braces or brackets, it is ignored and the attempt records `ignored stray punctuation outside the marked block`. Any letter or digit, a Markdown fence or other text there is still refused.
- **A top-level `evidence` field is explained.** The refusal says that `evidence` belongs inside each example.
- **Every refused specification is logged.** A specification refused for any reason, not only invalid JSON, now writes the model's bounded head and tail to the engine log, so a repeated refusal can be read instead of guessed (this run's second-half responses could not be seen).
- Tests: examples built on the real file-sharing-app-1 issue (header plus row grounds all seven examples; the header's own values do not ground anything; the long-gap, long-header and wrong-order cases are still refused; the prompt wording; the top-level hint), the `"…END…"}` ending, and a native pipeline in which every example is quoted with the column titles and the run verifies on the first request. 442 Python tests (7 new), zero skips, and 2 Node helper tests. All run with real tsc, tsx and node:test.
- Not changed: the grounding of every expected and argument value, the limits, the number of attempts, the repeat guard, the frozen test, replay, delivery and every default.
- Limits, stated plainly. Whether the model now completes file-sharing-app-1 is not known; no live run covers rc.34. Context lines are real issue text, so a header can be quoted as support for a value only through the remainder, never through itself. A model that answers with a different malformed shape each time still ends `spec_invalid`.

## v0.6.0-rc.33 — The model is told which examples were refused, a table row is quoted as a row, and a quote after the END marker is dropped

The third live specification run (rc.32, `verifier=spec`, legacy mode, file-sharing-app-1) ended `no_reproduction` after five model requests and one executed test. The rc.32 repair did what it was written for: both blocks that ended `], "` were closed, and the proof records `json_repaired` on those attempts. The run failed one step later. The issue states its examples as a plain-text table (a header line, `Function Input Expected output`, then seven rows). For every example the model quoted the header line followed by that example's own row. For e1 the row sits directly under the header, so the quotation was one passage and was accepted. For e2 to e7 the rows in between made it two separated pieces, so those six examples were refused as "not in the issue", correctly under the rule that a quotation is one passage, and the specification stood on e1 alone: `formatBytes(512)` returning `512 B`, which the unfixed code already does. It could not reproduce anything.

Nothing told the model. The retry prompt carried the surviving specification (one example) and its state (`pass`), not the six refusals, so the model had no way to learn that its quotations were the problem; it sent the same specification twice, the engine skipped the duplicate executions as designed, and the verifier retry budget ran out. The same model also wrote the END marker as if it were a JSON string and closed a quote after it on the first request of each round, which cost two further requests because text outside the block is refused.

- **Refusals go back to the model.** Every retry prompt for a specification run (no reproduction, or a test that would not compile or load) now lists the examples the engine refused and the reason for each, says they never ran, and asks for them again with a single contiguous quotation. When none of the remaining examples fails on the unfixed code it adds that they do not show the bug and the ones that do may be among the refused. Only the refusals of the latest specification are kept in the proof; an earlier specification's refusals are no longer left behind when a later one has none. Each validated attempt records `refused_examples`, the number it dropped.
- **A table row is quoted as a row.** When every line of a quotation is in the issue but the lines are not adjacent, the refusal now says so, tells the model to copy only the single row or item and not the header, and names the issue line that holds the example's own values when exactly the strings and numbers it uses are on one line (for e3: `formatBytes 1536 1.5 KB`). The prompt gives the same rule up front. The grounding rule itself is unchanged: a quotation must still be one passage of the issue, and the engine does not rewrite evidence for the model.
- **Quotes and commas outside the block are ignored.** If the only text outside the markers is quote, comma or semicolon characters, they are dropped and the attempt records it in `json_repaired` (for example "ignored stray punctuation outside the marked block"). Words, a Markdown fence or a brace outside the block are still refused.
- Tests: new unit tests built on the real file-sharing-app-1 issue (the header-plus-row quotation keeps one example and refuses six with the row named; one row per example grounds all seven; the suggestion is only made when one line holds the values), parse tests for the trailing quote, feedback tests, and two native pipelines (the live shape with a trailing quote is verified with one request; a spliced quotation that leaves only a passing example is retried with the refusal in the prompt and then verified, with no stale refusals in the proof). 435 Python tests (15 new), zero skips, and 2 Node helper tests. All run with real tsc, tsx and node:test.
- Not changed: the validator's grounding rules and limits, the number of attempts, the repeat guard, the frozen test, replay, delivery and every default.
- Limits, stated plainly. Whether this model now quotes the row when told is not known; no live run covers rc.33. A model that ignores the feedback is still stopped by the retry budget, and a specification that is all refusals still ends `spec_invalid`. The engine does not accept a header line plus a distant row as one quotation, by design.

## v0.6.0-rc.32 — A specification block that is complete except for its closing bracket is closed instead of refused, and a JSON error says what is actually wrong

The second live specification run (rc.31, `verifier=spec`, legacy mode) went two ways. qrcrafts-1 succeeded: the partial validation added in rc.31 did what it was written for. file-sharing-app-1 stopped `spec_invalid` before any test was compiled, after three specification attempts that were byte-for-byte the same 1,172-character response (450 completion tokens each time, although the request temperature is 0.1). The model had written every example correctly, closed the `examples` list with `]`, and then, instead of closing the object with `}`, wrote `, "` and the END marker. The marker ended the block, so the text the engine parsed finished with an opening quote that never closed. The engine's message said "Unterminated string" and then explained how to write backslashes, which had nothing to do with the problem, so the model had no way to learn what to change and sent the same text again; the repeat guard stopped the run on the third copy, as designed.

- **Closing brackets are added when, and only when, nothing else is wrong.** If a block fails to parse, the engine looks at the end of the text. It may remove one dangling quote that opens an empty string and one trailing comma, and it appends the `]` and `}` still open. It never adds or changes a value, never touches the middle of the text, and gives up when a value is cut off mid-string, when brackets are mismatched, when more than four are open, or when the repaired text still does not parse. The repaired block then goes through exactly the same validation as any other: every expected value and argument is still grounded in quoted issue text, example by example. The proof records it as `json_repaired` on the attempt (in `regression_test.spec.attempts` and `generation_attempts`) and the engine prints one line saying what it did, so a repaired run is never indistinguishable from a clean one.
- **The JSON error names the likely cause.** The backslash explanation is now given only when the parser reported an invalid escape or control character. An unterminated string or a block that ends at a quote or comma gets "the block looks unfinished or not closed: finish the examples list with ] and close the object with }, with nothing between that } and the END marker". Other failures get a short generic hint. The message no longer reads "starting at at line".
- **Manifest errors show the value.** `repo must look like owner/name` now prints the offending value. This came from Engine Checks failing on a half-filled `heldout-3` entry: three tests (the shipped-manifest check, the file-sharing pin check, and the CLI exit-code check) fail on any case whose `repo` is not `owner/name`, even one that is not selected, because structural problems are always reported. A placeholder case must keep `TODO/TODO`, or be filled in completely.
- Tests: new parser tests (the exact live shape, a missing bracket alone, a valid block never reported as repaired, values cut off in the middle refused, an unclosed block not explained as a backslash problem) and two native pipelines (the live shape with three grounded examples is repaired with a single model request and verified; a repaired block with an invented example still refuses that example). The Node and Python suites were re-run in full.
- Not changed: the validator and its limits, the number of attempts, the repeat guard, the frozen test, replay and delivery, and every default. A repaired block cannot say more than the model wrote.
- Limits. The repair covers one failure shape, a block that is complete except for its end. A model that sends different invalid JSON, or the same invalid JSON in the middle of a value, still ends `spec_invalid`. Models that ignore the retry feedback and repeat themselves are still stopped at three identical outputs. No live run covers rc.32.

## v0.6.0-rc.31 — One invented example no longer sinks a specification, JSON errors show where they are, and recorded tool versions line up

The first live run of the specification profile on rc.30 (qrcrafts-1, `verifier=spec`, legacy mode) ended `spec_invalid` after three specification attempts, 41 seconds and no executed test. The proof shows why: attempt 1 was not valid JSON (the engine's message gave a column number but no context), attempt 2 quoted evidence that is not in the issue, and attempt 3 added an example (`OfficeNetwork` / `SecretPassword123`) whose values the issue never gives. The issue states two payloads; the model added a third for "ordinary credentials must keep working". The engine was right to refuse that example, but it refused the whole specification, including the two examples that were fine. The legacy freeform smoke on rc.30 was reported passing, so the default path is not affected.

- Specification examples are now validated one at a time. An example that is not grounded in the issue is left out and recorded in `regression_test.spec.rejected_examples` with its reason; the specification stands if at least one example passes every check. Every example that remains has passed every check, so this asserts less, never something unquoted. Problems with the specification as a whole (wrong module, unknown top-level field, invalid JSON, no grounded example) still fail it and go back to the model.
- The prompt tells the model to use only examples whose input and result are both written in the issue, not to invent values for behavior described in words, and that an invented example is discarded.
- A JSON parse error now shows the text around the failure, so a stray quote or backslash can be found.
- Provenance fix: newer `tsx` prints two lines (`tsx v4.23.15` then `node v20.19.2`), which shifted every recorded tool version by one (the proof listed node as 9.2.0 and tsc as `tsx`'s node). The two-line banner is now read correctly; the raw lines were always kept.
- Tests: 413 Python tests (5 new), zero skips, and 2 Node helper tests. They include a native pipeline where the model returns two grounded examples plus an invented third and the run is verified with the invented one recorded as refused, partial-mode unit tests (kept, recorded, nothing grounded, wrong module), the JSON context test, and the two-line tsx banner.
- Not changed: strict validation remains available (`partial=False`), all gates on the remaining examples, the frozen test, replay, delivery, and every default. Limits: whether the model now produces a specification that passes, and whether the repair then verifies, is unproven; no live run covers rc.31.

## v0.6.0-rc.30 — The engine says what it knows before it spends inference, stops a verifier that repeats itself, and can write the test from a specification quoted from the issue

rc.29 ended with one question that no amount of plumbing could answer: the weak link in every run is the regression test the model writes for a repository it has never seen. Escaping, import paths, runner conventions and expected values the issue never stated are where unfamiliar projects fail, and a human approving the test was ruled out (the test problem has to be solved without anyone in the loop; a person still decides whether to merge the pull request). rc.30 works on that in five steps, in the order they were reviewed. Everything is locally validated; no live run covers it.

- **Readiness before inference.** Every proof now carries a `readiness` summary: project root, runtime, install, test command, discovered test counts, required checks and specific blockers, each with the change that would clear it. A baseline that ran zero tests is recorded as `compatibility_coverage: absent`, because "ordinary CI passed" then means nothing about existing behavior. `python proof.py --readiness-only` runs everything up to the first model request and stops with verdict `ready`.
- **Outcome buckets.** Every run is assigned one bucket from its own evidence (`verified`, `readiness_blocked`, `needs_specification`, `spec_invalid`, `verifier_invalid`, `no_reproduction`, `repair_invalid`, `repair_failed`, `replay_failed`, `delivery_blocked`, `budget_exhausted`, `infrastructure_error`). A run that stops without one of the older stop reasons now gets the matching legacy `stop_reason` filled in. Only `verified`, `repair_failed` and `replay_failed` count as an evaluated repair.
- **Verifier execution gate.** A generated test that never ran (syntax error, lint, type-check, unresolved import) no longer uses up one of the three execution attempts; it has its own allowance of three. A model that sends the same rejected output three times in a row stops the run with its own message instead of spending the rest of the budget. Parse failures come back with the offending line, a caret and, for an unterminated string, the usual cause. Plain JavaScript tests get a `node --check` step before they run, in a form that keeps the protected-run hash markers. Attempt records carry `static_rejection` and `counts_toward_limit`, and the report's attempts table shows which attempts counted.
- **Specification-compiled tests (opt in).** `verifier-profile: spec` (Action), `PATCHPROOF_VERIFIER=spec` or the Benchmark workflow's `verifier` input asks the model for data instead of code: a module, exported functions, JSON arguments, the result the issue requires, and the issue text that supports each example. The engine checks that the quotation is really in the issue, that every expected string and number is in that example's own quotation, that booleans, null and empty values are stated in words or literals, that argument strings are quoted or already used in the source, and that a `throws` example has failure language behind it. It writes the test itself from a fixed template (imports from the module's real path, values serialized by a JSON encoder, fixed assertion messages), tries the `.js`, `.ts` and bare import styles on a module-resolution error without another model call, and decides per example from the TAP result: only an example whose own assertion fails on a returned value counts as the bug; an example that throws is dropped and the test recompiled; a passing example stays as a guard. The accepted specification and compiled test are frozen before the solver starts. `auto` tries this first and falls back to the free-form verifier, recording why; `spec` stops with `needs_specification` instead. The default stays `freeform`, so nothing changes unless it is set. See docs/SPEC_PROFILE.md.
- **Benchmark report.** The harness records the requested verifier profile, refuses to pool engines that ran different ones, and rejects a trial whose engine ignored it. The report now shows the solve rate over all non-infrastructure trials (stops for specification stay in the denominator), the coverage of the specification profile, the repair success among runs that reached an evaluated repair, one column per outcome bucket, and the bucket and verifier profile of every trial. Trials from engines older than rc.30 show `not recorded` instead of a guessed bucket.
- Changed behavior to know about: three identical rejected verifier outputs in a row now stop with "repeated the same rejected output" where rc.29 reported an exhausted retry budget (one existing test updated for the message), and the verifier's JavaScript regression command now starts with `node --check`.
- New engine modules: `outcomes.py` and `spec_profile.py`. They are listed in the engine file set, the install export, the Engine Checks compile step and the protected names, so a repair cannot edit them.
- Found by probing the finished validator and fixed before release: an expected `false`, `null`, `""`, `[]` or `{}` was accepted with no tie to the issue; a one-character quotation passed; an object key named `__proto__` would have changed meaning in the compiled literal; a reserved word was accepted as an export name; and a run that stopped inside the specification step lost its status, so its bucket could not be `spec_invalid`.
- Tests: 408 Python tests (99 new), zero skips, and 2 Node helper tests. They include native pipelines (real TypeScript, tsx and the Node test runner, scripted model) for a grounded specification that is compiled, reproduced and repaired; an erroring example that is dropped and the test recompiled without a model call; an ungrounded value refused before any run; a JSON backslash mistake returned with the escaping rule; `needs_specification` and `spec_invalid` stops that never request a repair; automatic fallback after an unsupported answer and after two rounds that did not reproduce; and a fallback run that then fails and is not blamed on the specification.
- Limits, stated plainly. The expected values are as correct as the issue is; the engine proves they are quoted, not that the issue is right. A value can be grounded by an incidental occurrence of a short token. Object keys are not checked. A handful of calls cannot protect all unrelated behavior. The profile covers call-and-return functions with JSON values on `node-typescript`; network, DOM, timing and file-system issues (heldout-1 and heldout-2 among them) stay on the free-form path or stop with `needs_specification`. No live run covers rc.30: the next step is a legacy `qrcrafts-1` smoke, and only after it a `spec` run. A maintainer-approval mode is not built; if it is, it must be a separately labeled mode.

## v0.6.0-rc.29 — A solver that sends edits in the wrong shape is told exactly what is wrong, and stops repeating it

The first live run of rc.28 (qrcrafts-1, bounded mode) got through setup and the verifier test (valid on attempt 1), then ended `budget_exhausted` at candidate evaluation with no candidate evaluated. The solver read the file correctly and proposed a plausible edit, but put `path` on the action instead of inside the edit. The tool answered "Each edit requires exactly path, old, new." without saying which key was wrong, and the model resent the identical edit 22 times (steps 3 to 24, about 228 output tokens each) until its 24-step allocation ended. It was reported as budget exhaustion although the cause was a tool-format error.

- The edit error now names the edit number and the missing or unexpected key and shows the exact shape, with `path` inside every edit.
- When an edit has no `path` and the action carries one, that path is used for the edit that lacks one. It never overrides an edit's own path, is still checked against the allowed source files, and the observation carries a note.
- An identical action that is rejected with an identical error twice gets "already rejected, do not resend it" appended. A solver that does it a third time stops with `candidate_invalid` for that candidate only; other candidates and the run continue. Verifier investigations are warned but never stopped by this rule.
- Not changed: budgets and their limits, the hidden test, eligibility, replay.
- Four new tests (one a native pipeline using the wrong-shape edit); 309 Python tests, zero skips. No live run covers rc.29. Unverified: whether Nemotron follows the clearer error.

## v0.6.0-rc.28 — A stray Bun lockfile no longer blocks a project that has one supported lockfile

The first live run of rc.27 (qrcrafts-1, bounded mode) stopped at runtime detection, before any inference: "Multiple package-manager lockfiles found (npm, bun)". QRcrafts has `package-lock.json` and a Bun lockfile, and every release up to rc.26 installed it with npm, so rc.27 turned a working case into an infrastructure failure.

- Bun cannot be selected (it is unsupported), so a Bun lockfile beside exactly one supported lockfile no longer makes the choice ambiguous. The supported tool is used and `runtime.package_manager.notes` in proof.json records that the Bun lockfile was ignored.
- Unchanged: two supported lockfiles (npm and Yarn, say) stop the run; a Bun lockfile alone stops the run; a `packageManager` field decides first; Bun in `packageManager` is refused.
- One new test; 305 Python tests. No live run covers rc.28.

## v0.6.0-rc.27 — Project support: package managers, project folder, declared failures, new files, provenance

Built from the audit's generalization table. Local validation only: 304 Python tests (45 new) and 2 Node helper tests; no live run covers these paths. See docs/GENERALIZATION.md.

- Install and test with the project's own package manager: `packageManager` or the lockfile selects npm, pnpm, Yarn Classic or Yarn Berry, with frozen lockfile installs and install scripts disabled. Conflicting lockfiles, a missing lockfile for the declared tool, Bun and Yarn Plug'n'Play stop with a specific message instead of installing with a different tool. Real lockfiles of all four managers were installed and tested locally.
- `root` in patchproof.json treats a self-contained subfolder as the project. Scope, test placement and install follow it, evidence stays at the repository root, and PR paths carry the folder prefix. Workspace packages are refused.
- `.mts` and `.cts` are editable and visible context for the TypeScript adapter.
- `known_failures` lists tests that already fail on the base commit. The ordinary command passes only when those are the sole failures (node:test TAP, exact names), so a new failure or a broken passing test still blocks. A candidate cannot hide behind the list.
- `scope.new_file_dirs` lets a bounded repair create up to three new source files under declared, existing folders. Verifier sessions stay read-only, legacy mode refuses the option, and created files go through the same type check, interference check, frozen regression, clean replay and delivery hash check.
- Proofs record the engine version and file hashes, project manifests and lockfiles, archive hash, package-manager command and sandbox toolchain versions in both modes.
- Not changed: the frozen verifier, ordinary-CI discovery, clean replay, budgets, and every default. Unverified: `npm install -g pnpm|yarn` inside the apt-based sandbox image.

## v0.6.0-rc.26 — Bounded Node/TypeScript investigation and debugging

- Add opt-in repository list/read/search/symbol tools and independent verifier/solver histories.
- Allow cumulative validated source edits and ordinary baseline/typecheck/build feedback before the hidden gate. Default to one bounded solver session; retain legacy mode.
- Share step, HTTP request, token, command and deadline limits across the run; add optional operator-priced inference cost caps and atomic evidence checkpoints.
- Record source provenance, pending actions, usage and stop reasons. Deduplicate final patches and refuse delivery over source changed during the run.
- Record benchmark execution profiles; keep budget/specification stops in the denominator and reject mixed profiles for one engine.
- Offline fixtures use native compiler/tests and substituted inference/transport. Live model quality and Nebius behavior require the controlled follow-up run. See docs/BATCH2.md.

## v0.6.0-rc.25 — Audit fixes for verification, delivery and benchmark evidence

- Resolve TypeScript JSONC/extends and retain ambient declarations; required checks fail closed when unavailable.
- Freeze visible test paths and portable support files, verify ordinary test discovery before repair, replay the final tree, and stage only hash-verified PR files.
- Add explicit file/symbol scope and Node assertion/runtime interference checks. Allow a passing eligible branch to replay despite another branch's generation failure.
- Replace Python substring reproduction evidence with runner exception types; check simple matcher constants; keep the source-file inventory independent of context truncation.
- Use exact full patch hashes, fresh trial outputs, protocol snapshots, digest checks, and baseline/reference-valid oracle evidence. Preserve historical results and keep new held-out placeholders unselected.
- Local validation only. No new Nebius success rate, published tag or generalization result. See RELEASE.md for installation, supported boundaries and the next controlled check.

## v0.6.0-rc.24 — Refuse unsound verifier tests before they run; give a repair that does not compile one correction

- **Why.** The rc.23 benchmark run (heldout-1 and heldout-2, three trials each; both are
  development cases now, because rc.22 and rc.23 were tuned on them) ended 1 of 6 correct and
  accepted, with no false accepts, against 0 of 6 on rc.21. The saved proofs show two verifier
  defects and one solver defect that a prompt rule could not reach:
  1. **heldout-1: every accepted test matched wording the issue never states.** Trial 1 pinned
     `/blocked/`; trial 2 pinned `/Invalid URL: http:\/\/127.0.0.1/`; trial 3 pinned
     `/SSRF protection: Target host resolves to a disallowed IP address/`; the rc.22 smoke had
     pinned `/Invalid target: resolves to disallowed IP address/`. The rc.23 prompt rule changed
     nothing visible. Trial 1 rejected a correct repair because its message starts "Blocked request
     to internal IP address" with a capital B and the test wanted `/blocked/`; trial 2's test
     demanded a message no reasonable repair would produce, and every candidate also failed the
     type check before the test mattered; trial 3's test imported `scanSiteUrl` from
     `@/src/services/api` instead of the scanning code, so its "reproduction" was `Failed to
     parse URL from /api/scan/site`, a relative fetch URL, not the SSRF defect.
  2. **heldout-2 (static-web): all six executed generations across trials 1 and 3 called
     `describe()` or `it()` without importing them**, and two of them also imported `jsdom` by
     name, which cannot resolve outside the sandbox image. node:test reports `ReferenceError` as a generic
     `test failed`, so the model heard only "without accepted assertion evidence", swapped
     `describe` for `it` and back, and never added the import. The pre-execution import check
     existed for node-typescript only.
  3. **heldout-1 solver: seven of the nine candidate repairs failed the repository's own type
     check.** Five put `await` inside a non-async function and four used `dns.ADDRCONFIG`, which
     `dns/promises` does not export (two did both). Each was rejected without a second chance;
     one of them behaved correctly apart from that constant.
- **What changed.**
  1. *Import check for every node:test adapter* (`runtimes.py`: `missing_node_test_imports`,
     `imports_bare_jsdom`). node-package and static-web generated tests now go through the same
     pre-execution check as node-typescript, and the check looks at which names the file actually
     calls: importing `test` no longer excuses an unimported `describe`. The diagnostic gives the
     exact import line. On static-web a bare `jsdom` import is refused with the exact
     `createRequire('/opt/patchproof/node/package.json')('jsdom')` line. `proof.py` adds a specific
     diagnosis for `ReferenceError: describe|it|test|before|after|beforeEach|afterEach|assert is
     not defined` in the retry feedback, for any test that still reaches the sandbox.
  2. *Wording-pin gate* (`runtimes.py`: `ungrounded_message_pins`,
     `RuntimeAdapter.validate_generated_pins`, called from `generate_regression_test`). The
     generated test is read for regex or string literals used to match an error message
     (`assert.rejects` and `assert.throws` with a regex or a `message:` property,
     `assert.match`/`strictEqual` on `.message`, `/re/.test(x.message)`, `x.message.includes`,
     `startsWith`, `endsWith`, `==`). Each literal is reduced to its wording (regex operators, class
     names, error codes and fragments under three letters are dropped) and must appear in the
     issue title or body. A miss is an ordinary validation failure that costs one generation; the
     diagnostic says to assert the refusal without a message matcher and to tell it apart from the
     unfixed failure by its effect, for example a local listener whose connection count must stay
     0, or by the rejection not being the unfixed network error. Applies to every `node-test`
     adapter. Any exception inside the heuristic is ignored (it fails open).
  3. *Compile check for TypeScript candidates* (`patchproof_runtime/typescript_source_check.py`,
     `proof.py`). Before the first candidate the unmodified project is type-checked once with its
     own compiler (the same program `tsc --noEmit` builds). Only if that passes, each candidate
     whose ordinary baseline passed and that changed a TypeScript file is type-checked again with
     its repair applied and before the hidden regression is added. A failure gets the same single
     correction a failed baseline gets, with the compiler's diagnostics and the candidate's own diff
     as feedback; a second failure rejects the candidate at stage `source-check`. A check that
     cannot run (compiler missing, references-only tsconfig, timeout) counts as a pass and never
     rejects anything. The proof records `source_check` (enabled, baseline exit code) and, per
     candidate, `source_check_attempts`. The whole project is checked, not only the changed
     files, because ambient declarations exist only in the whole program. Registered in
     `tools/export_target.py`, the sandbox helper list and `engine-checks.yml`.
- **Evidence.** All from the saved rc.23 proofs and the pinned repositories; no live run yet.
  - The three heldout-1 accepted tests are refused by the pin gate while the rest of the
    validator accepts them; the six heldout-2 executions are refused before any sandbox run with
    the right import line (`tests/test_rc24_evidence.py`, fixtures `tests/fixtures/rc24_*`).
  - On the pinned Aegisscan commit the unmodified project passes the check, and 7 of the 9
    heldout-1 candidate diffs fail it with TS1308, TS2339 or TS18046; the two that compile are
    the correct repair and an import-only non-repair. QRcrafts at its pinned commit (TypeScript
    7.0.2) and file-sharing-app at its pinned commit also pass the project check.
  - Verdicts of the old validators on the 14 recorded fixtures are unchanged.
  - `tests/test_rc24_candidate_check.py` drives `proof.execute()` against a scripted fake sandbox:
    a failing candidate gets one correction and can win, a second failure rejects it, a project
    that fails its own check switches the gate off, a check that cannot run never rejects, and
    nothing about the hidden test reaches a solver. Disabling the gate or leaking the test into
    the feedback makes those tests fail.
- **What did not change.** The assertion-evidence check, hashing, candidate selection, clean
  replay, the solver and verifier prompts, and every non-TypeScript runtime's candidate flow.
  The bounded test-revision round discussed after rc.23 was not built.
- **Honest limits.**
  - The pin gate is a heuristic on source text. It also refuses a legitimate matcher on library
    or runtime wording the issue does not quote (for example `/Unexpected token/`); the model is
    told to drop the matcher, which costs one generation. It reads only the forms listed above.
  - It does not detect a test that exercises the wrong module, or one that could never pass after
    a correct fix and carries no message pin (heldout-2 trial 3 resolved `form.action`, which jsdom
    already makes absolute, against a base URL).
  - A repair that compiles is not thereby correct; the check removes one way for a correct repair
    to be lost, not the need for the hidden test. It applies to node-typescript only, and only
    when the unmodified project passes its own type check.
  - rc.24 has not been run live. heldout-1 and heldout-2 are development cases; a generalization
    claim needs new issues written before the engine version sees them.

## v0.6.0-rc.23 — Verifier tests must not pin wording or the unfixed value

- **Why.** The rc.22 smoke run (heldout-1, heldout-2, one trial each) finally got past
  the verifier: both tests were accepted and candidates were evaluated. Both runs were
  then rejected although a correct repair existed, because the accepted test was
  over-specified:
  1. heldout-1 asserted an invented message, `/Invalid target: resolves to disallowed IP
     address/`, that the issue never states. All three candidates failed on wording; the
     one that rejects every required address range (verified by hand against the pinned
     repository) was among them.
  2. heldout-2 asserted that the form's current `action` is `/thank-you.html` as a
     sanity check before checking the repaired behaviour. The correct repair changes
     that attribute, so the correct repair failed the test.
- **What changed.** One paragraph in the shared verifier prompt for every runtime: pin
  only what the issue states; do not assert an exact message or wording unless the
  issue gives it; do not assert the current value of the thing being repaired; when the
  unfixed code also fails but for a different reason, tell them apart by the behaviour
  the issue requires, for example a side effect that must not happen.
- **What did not change.** The assertion-evidence check, replay, candidate selection and
  hashing. This is a prompt change only. There has been no live run of rc.23.
- **Honest limit.** A prompt rule lowers the rate of over-specified tests; it does not
  prove their absence. If false rejects remain, the next step is one bounded test-revision
  round after all candidates fail, flagged in the proof.

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
