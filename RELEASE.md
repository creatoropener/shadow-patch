# PatchProof v0.6.0-rc.39 — a transient Sandbox API failure is retried and is not reported as a readiness block

A file-sharing-app run on rc.38 stopped at `runtime-preflight` with `ApiStatusCodeError ... GET /sandboxes/v1/files/<sha> ... status=500`: the Nebius Sandbox API failed while the engine uploaded its helper files. Nothing was wrong with the repository, the issue or the engine's logic, but the engine had no retry and the outcome said `readiness_blocked`.

rc.39 changes two things and nothing else:

- the three setup steps (workspace upload, dependency install, toolchain preflight) are retried twice, after 5 s and 15 s, when the Sandbox API answers 5xx, 408 or 429 or times out. Ordinary errors, 4xx answers and failed commands are not retried;
- a run that still ends on such an error is bucketed `infrastructure_error`, not `readiness_blocked` or a failed repair, so it does not count against the repository in a report.

Not covered: later steps (candidate evaluation, clean replay) are not retried, and a Sandbox API error there is still recorded as it was. **A new tag is needed**; the workflow pin is `creatoropener/shadow-patch@v0.6.0-rc.39`. If rc.38 is already published and a relabel works, rc.39 is optional resilience, not a fix for any other result.

---

# PatchProof v0.6.0-rc.38 — the rc.37 root-URL refusal no longer refuses a test that can fail

Two live runs verified: Tabloop #2 on **rc.36** (`1b9026a3-proof_tabloop__2_.json`, the first live `static-web` success) and Aegisscan #3 on rc.37 (`8cf46a25-proof_Aegis.json`, `node-typescript`, so unaffected by rc.37's static-web changes). Replaying the Tabloop test through rc.37 showed a false positive in the rule rc.37 added: it refused any root-URL test for an issue that mentions a subpath, including the test that verified on rc.36. That test reads the raw attribute (`form.getAttribute('action')`), which fails at the root without any URL path. rc.38 limits the refusal to tests that read a *resolved* address (`.action`, `.href`, `.src`, `location.href`), the only kind a root URL hides. The two tests that failed on rc.36 (`form.action` at the root) are still refused.

Upload and tag steps are as in the sections below, with `RC38-CHANGES.json` and the tag `v0.6.0-rc.38`. Nothing changes for `node-typescript` runs except the version string. **Freeze the engine at rc.38 for the fresh-set run** and record it.

---

## (superseded by rc.38 above) PatchProof v0.6.0-rc.37 — a test that cannot fail on the unfixed page is refused and explained

The Tabloop #2 run on rc.36 (`bec7431b-proof.json`) is the first static-web run that got everything right on the setup side: jsdom 24.1.3 loaded on Node v20.19.2 (`baseline.jsdom_probe`), the baseline was green, the probe test was found, and the generated tests ran. It ended `no_reproduction` because every test created the page at `https://patchproof.invalid/`. At the host root a root-absolute action (`/thank-you.html`) and a relative one (`thank-you.html`) resolve to the same address, so no assertion on the resolved action can fail on the unfixed page. That was the engine's doing: the adapter's prompt said to set `url: 'https://patchproof.invalid/'`. On rc.34 the model had happened to use `/Tabloop/` and got a sound test. The retry feedback also told the model to use `doesNotReject`, which means nothing for a DOM test, and it repeated the same test.

rc.37 changes only static-web:

- the prompt no longer prescribes the root URL and says the path in the url matters when the issue is about where the page is served;
- a test that creates the page at the root, for an issue that mentions a subpath, staging, base path or deploy path, is refused before it runs, with the fix, and retried;
- the feedback for "passed on the unfixed revision" on a static page now explains this instead of the `doesNotReject` advice.

No live run covers rc.37. **A new tag is needed.** Upload and tag steps are unchanged from the rc.36 section below, with `RC37-CHANGES.json` and `v0.6.0-rc.37`. Nothing needs to change in Tabloop.

**Your issue text matters here.** The rules above are triggered by words in the issue (subpath, sub-directory, base path/URL, deploy path, staging, GitHub Pages). If Tabloop #2's text does not contain one, only the prompt change applies. Add the path the form should resolve under (for example `/Tabloop/`) to the issue; see `docs/RUN_GUIDE.md` item 7.

---

## (superseded by rc.37 above) PatchProof v0.6.0-rc.36 — a jsdom that cannot load is caught before any model request

The Tabloop #2 run on rc.35 (`eef15ec1-proof.json`) got further than any static-web run before it: tests discovered, baseline green, three generated tests. Then all three died inside the project's own jsdom. The lockfile had resolved **jsdom 30**, whose `undici` 8 dependency reads `zlib.createZstdDecompress` when it loads; the sandbox runs Node 20, which does not have it. The run spent three model requests on a failure that no test could have avoided. The setup instructions in `docs/RUN_GUIDE.md` and this file said `npm install --save-dev jsdom`, which installs the newest jsdom, so the cause was partly the guide. rc.36 fixes the engine and the guide. No live run covers rc.36. **A new tag is needed.** rc.35 stays as published; do not move it.

## Upload

1. Extract **shadow-patch-fresh-set-and-run-guide.zip** into the root of **shadow-patch**, preserving paths. It is cumulative (fresh-set tooling, run guide, rc.35 and rc.36) and replaces the earlier zips. `RC38-CHANGES.json` lists every file with its hash and its hash in the uploaded rc.34 tree.
2. Commit to `main`, let **Engine Checks** finish, then publish the tag `v0.6.0-rc.36`, and use `creatoropener/shadow-patch@v0.6.0-rc.36` in the workflow.

## For Tabloop, right now (works with the rc.35 tag too)

The run does not depend on the new engine to get past this crash. Pin the project's jsdom:

```
npm install --save-dev jsdom@24.1.3
git add package.json package-lock.json && git commit -m "Pin jsdom to a version that loads on Node 20"
```

Check under Node 20 that `node -e "require('jsdom')"` prints nothing, and that `CI=1 npm test` still passes. With rc.36 the engine runs the same check in the sandbox before the model is called and says what to change if it fails.

What rc.36 also changes: a generated test that uses `__dirname`, `__filename` or `require` (all three live tests did) is sent back to the model once with the replacement (`new URL('./index.html', import.meta.url)`), and the prompt now says so up front. Without this a correctly pinned run would still have stopped on `ReferenceError: __dirname is not defined`.

## What to send back

`proof.json` and `engine-stderr.txt`. `baseline.jsdom_probe` in the proof records the jsdom and Node versions the engine saw.

---

## (superseded by rc.36 above) PatchProof v0.6.0-rc.35 — the static-web adapter can complete a run

rc.35 is rc.34 plus one fix, for one adapter. Tabloop #2 showed that `static-web` could never finish a run: its prompt required a sandbox-only jsdom path and the engine refused any test containing it, and its baseline never ran a test. Details and the offline evidence are in `CHANGELOG.md`. No live run covers rc.35. **A new tag is needed** (the engine changed), and it is the one the fresh-set run should record.

## Upload

1. Extract **shadow-patch-fresh-set-and-run-guide.zip** into the root of **shadow-patch**, preserving paths. It is cumulative: it contains the fresh-set tooling, the run guide and the rc.35 change, so it replaces the earlier zips. `RC35-CHANGES.json` lists every file with its hash and its hash in the uploaded rc.34 tree.
2. Commit to `main`, let **Engine Checks** finish (it now also installs jsdom and exposes it at `/opt/patchproof/node`), then publish the tag `v0.6.0-rc.36`.
3. Nothing changes for `node-typescript` repositories except the version in the workflow pin: `creatoropener/shadow-patch@v0.6.0-rc.36`.

## To run a static site (Tabloop)

The repository needs four things, all small. `docs/RUN_GUIDE.md` has the reasoning.

| Where | Change |
| --- | --- |
| `patchproof.json` | `{"runtime": "static-web"}` |
| `package.json` | `"scripts": {"test": "node --test"}` (not `node --test *.test.mjs`: on Node 20 that fails while no test file exists) |
| `package.json` | `npm install --save-dev jsdom@24.1.3` (not a bare `npm install --save-dev jsdom`: jsdom 30 and newer need Node 22), and commit `package.json` and `package-lock.json` |
| `tsconfig.json` | delete it, or keep it correct: `"checkJs": flase` made `tsc` fail in the first Tabloop run, and with `static-web` selected explicitly nothing needs it |
| workflow | add `image-static-web: ${{ secrets.CONTREE_IMAGE_STATIC_WEB }}` under `uses:`, with a `CONTREE_IMAGE_STATIC_WEB` secret from **Prepare Sandbox Image** (profile `web` or `all`) |

Before labeling the issue, run `CI=1 npm test` under Node 20: it should pass and report `# tests 0`. The engine checks the same thing in the sandbox and stops with `readiness_blocked` before any model request if it fails.

## What to send back

`proof.json` and `engine-stderr.txt`. If it verifies, the pull request contains the fix, `test_patchproof_issue_<n>.test.mjs` and `patchproof_helpers/jsdom.mjs`. If it stops before inference, `outcome.detail` names what to change. If the model writes a test that does not reproduce, that is new information about the model, not about this fix.

---

# After rc.34 — manifest update, no new tag: file-sharing-app-1 gets a base whose `npm test` discovers a TypeScript test

The rc.34 engine is unchanged and stays current. This update changes `bench/manifest.json` (the pin for `file-sharing-app-1`), one test, three docs and the checksum list. The benchmark workflow takes its manifest from the ref it is started on and its engine from the tag, so **no new tag is needed**.

Why: the rc.34 run of file-sharing-app-1 passed the specification stage and stopped at the ordinary-CI discovery gate. At the old pin (`4f8b912`) the project's `npm test` runs only `tests/*.test.mjs`, so a `.ts` regression is never run by ordinary CI. The new pin (`bf93981`) has the same buggy `lib/utils/format.ts` and an `npm test` of `tsx --test tests/*.test.ts`. A local simulation under Node 20.19.2 showed the gate's check passing there (6 expected failures, with markers, from `npm test`) and a corrected function turning all 10 tests green. No live run has covered it yet.

## Upload

1. Extract **shadow-patch-manifest-pin-changed-files.zip** into the root of **shadow-patch**, preserving paths. Files: `bench/manifest.json`, `tests/test_bench_harness.py`, `docs/BATCH2.md`, `docs/BENCHMARK.md`, `CHANGELOG.md`, `RELEASE.md`, `RELEASE_FILES.sha256`.
2. Commit to `main` (or a branch, then run **Engine Checks**).
3. Before running anything, check `bench/manifest.json` on GitHub: the `file-sharing-app-1` case must show `"base_commit": "bf939812d176434f0b11dcdd9df4260dbd80dc8f"`, and `heldout-3` must either be complete (`"repo": "owner/name"`, not a URL) or back to `"TODO/TODO"` / `"TODO"`. The zip ships the manifest as it is in this working tree; if you edited `heldout-3` on GitHub after rc.34, merge that edit by hand instead of overwriting the file.

## Next live run

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.34 |
| trials | 1 |
| split | dev |
| cases | file-sharing-app-1 |
| agent_mode | legacy |
| verifier | spec |

Send back `proof.json` and `engine-stderr.txt`. If the discovery gate passes, the run goes on to candidate repair for the first time since rc.25, so a failure there is new information, not a regression of the specification stage. If it verifies, run qrcrafts-1 and file-sharing-app-1 together before any held-out case.

---

# PatchProof v0.6.0-rc.34 — a table's column titles in front of a row are accepted, and refused specifications are logged

rc.34 is rc.33 plus the fix for the fourth live specification run. qrcrafts-1 verified on `spec`. file-sharing-app-1 failed again: the rc.33 feedback named the exact row to quote and the model quoted column titles plus the row anyway, then moved `evidence` to the top level three times. The engine now accepts one or two short title lines in front of a row and grounds every value on the row alone, drops JSON punctuation after the END marker, explains a top-level `evidence`, and logs the model's text for every refused specification.

## Install the engine update

1. Extract **shadow-patch-rc34-changed-files.zip** into the root of your **shadow-patch** repository on top of rc.33, preserving paths (none deleted; `RC34-CHANGES.json` lists the files with hashes).
2. Commit on a review branch and run **Engine Checks**.
3. Publish **v0.6.0-rc.34** from the reviewed commit.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.34.zip** into the target root.

## Next live run

Repeat file-sharing-app-1 on rc.34:

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.34 |
| trials | 1 |
| split | dev |
| cases | file-sharing-app-1 |
| agent_mode | legacy |
| verifier | spec |

Send back `proof.json` and `engine-stderr.txt`. Read `regression_test.spec`: `examples[]` (`evidence` against `issue_span`), `pre_fix_states`, `rejected_examples`. If it verifies, run qrcrafts-1 and file-sharing-app-1 together before any held-out case.

## Validation

See docs/evidence/rc34-local/. No live run covers rc.34.

---

# PatchProof v0.6.0-rc.33 notes (superseded by rc.34 above; its install and run steps no longer apply)

rc.33 is rc.32 plus the fix for the third live specification run (file-sharing-app-1, `verifier=spec`). The rc.32 bracket repair worked on the live blocks. The run then failed because the model quoted every table example as the header line plus its row; only e1 sat directly under the header, so six of seven examples were refused as not being one passage of the issue. The one survivor already passes on the unfixed code, so nothing reproduced. The retry prompt never listed the refusals, so the model repeated itself until the budget ran out.

What changes: retry prompts list the refused examples and why; the refusal for non-adjacent lines says to quote just the row and names the issue line that holds the example's values; the prompt says the same up front; quotes and commas alone after the END marker are dropped. The grounding rule is unchanged.

## Install the engine update

1. Extract **shadow-patch-rc33-changed-files.zip** into the root of your **shadow-patch** repository on top of rc.32, preserving paths (none deleted; `RC33-CHANGES.json` lists the files with hashes).
2. Commit on a review branch and run **Engine Checks**.
3. Publish **v0.6.0-rc.33** from the reviewed commit.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.33.zip** into the target root.

## Next live run

Repeat file-sharing-app-1 on rc.33:

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.33 |
| trials | 1 |
| split | dev |
| cases | file-sharing-app-1 |
| agent_mode | legacy |
| verifier | spec |

Send back `proof.json` and `engine-stderr.txt`. Read `regression_test.spec`: `attempts[]` (`refused_examples`, `json_repaired`), `rejected_examples`, `pre_fix_states`, `examples`. If it verifies, run qrcrafts-1 and file-sharing-app-1 together before any held-out case.

## Validation

See docs/evidence/rc33-local/. No live run covers rc.33.

---

# PatchProof v0.6.0-rc.32 notes (superseded by rc.33 above; its install and run steps no longer apply)

rc.32 is rc.31 plus the fix for the second live specification run. On rc.31, qrcrafts-1 under `verifier=spec` succeeded. file-sharing-app-1 stopped `spec_invalid`: the model's three examples were fine, but it ended the block with `], "` and the END marker, never closing the object, and sent the identical text three times because the error message talked about backslashes. The engine now closes brackets left open at the very end of a block (never adding or changing a value; every example is still grounded in the issue) and records `json_repaired`. Error messages say "not closed" when that is the problem. The manifest error for a malformed `repo` shows the value.

## Install the engine update

1. Extract **shadow-patch-rc32-changed-files.zip** into the root of your **shadow-patch** repository on top of rc.31, preserving paths (none deleted; `RC32-CHANGES.json` lists the files with hashes).
2. **Check `bench/manifest.json` before committing.** Engine Checks failed on your `heldout-3` edit because its `repo` is not in `owner/name` form (for example `owner/name`, not a URL or a half-typed value). The zip does not touch the manifest. Either set `heldout-3` completely or put back `"repo": "TODO/TODO"` and `"base_commit": "TODO"`.
3. Commit on a review branch and run **Engine Checks**.
4. Publish **v0.6.0-rc.32** from the reviewed commit.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.32.zip** into the target root.

## Next live run

Repeat file-sharing-app-1 on rc.32:

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.32 |
| trials | 1 |
| split | dev |
| cases | file-sharing-app-1 |
| agent_mode | legacy |
| verifier | spec |

Send back `proof.json` and `engine-stderr.txt`. Read `regression_test.spec`: `attempts[].json_repaired`, `status`, `rejected_examples`, `pre_fix_states`. Run the held-out cases only after `spec` has worked on the dev cases.

## Validation

See docs/evidence/rc32-local/. No live run covers rc.32.

---

# PatchProof v0.6.0-rc.31 notes (superseded by rc.32 above; its install and run steps no longer apply)

rc.31 is rc.30 plus the fix for the first live specification run (qrcrafts-1, `verifier=spec`): the model added a third example with values the issue never gives, and that one example made the engine refuse the whole specification, including the two grounded ones. Examples are now judged one by one: an ungrounded example is left out and recorded in `regression_test.spec.rejected_examples`, and the specification stands if at least one example passes every check. The prompt now says to use only examples written in the issue, JSON parse errors show the text around the failure, and the recorded tool versions are no longer shifted by newer tsx's two-line banner. Nothing else changes; rc.30 is described below.

## Install the engine update

1. Extract **shadow-patch-rc31-changed-files.zip** into the root of your **shadow-patch** repository on top of rc.30, preserving paths (none deleted; `RC31-CHANGES.json` lists the files with hashes).
2. Commit on a review branch and run **Engine Checks**.
3. Publish **v0.6.0-rc.31** from the reviewed commit. The Benchmark workflow checks the engine out from this tag, and the example Action reference needs it to exist.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.31.zip** into the target root (it includes `outcomes.py` and `spec_profile.py`).

## Next live run

Repeat the specification run on the same case, with everything else equal to the rc.30 smoke:

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.31 |
| trials | 1 |
| split | dev |
| cases | qrcrafts-1 |
| agent_mode | legacy |
| verifier | spec |

Send back the trial's `proof.json` and `engine-stderr.txt`. Read `regression_test.spec`: `status`, `rejected_examples`, `examples`, `pre_fix_states`, `dropped_examples`, `frozen_test_sha256`. Run the held-out cases only after `spec` works on the development cases.

## Validation

**413 Python tests, zero skips, and 2 Node helper tests**, plus Python compilation and JavaScript syntax checks. Logs: docs/evidence/rc31-local/. No live run covers rc.31.

---

# PatchProof v0.6.0-rc.30 notes (feature description; its install and run steps are superseded by rc.31's above)

rc.30 is rc.29 plus the five steps of the test-quality review. Locally validated only: no live run covers it. The free-form verifier is still the default, so an unchanged workflow behaves as it did on rc.29 apart from the new records and the stop rules below.

## What changed

- **Readiness before inference.** `proof.json` and the report carry a readiness summary (root, runtime, install, test command, discovered test counts, required checks, specific blockers). A baseline that ran zero tests is recorded as absent compatibility coverage. `python proof.py --readiness-only ...` stops before the first model request with verdict `ready`.
- **Outcome buckets.** Every run gets one bucket from its own evidence (verified, readiness_blocked, needs_specification, spec_invalid, verifier_invalid, no_reproduction, repair_invalid, repair_failed, replay_failed, delivery_blocked, budget_exhausted, infrastructure_error).
- **Verifier execution gate.** A generated test that never ran (syntax, lint, type-check, unresolved import) no longer uses one of the three execution attempts; it has its own allowance of three. The same rejected output three times in a row stops the run with its own message. Syntax failures come back with the line and a caret. Plain JavaScript tests get a `node --check` step.
- **Specification-compiled tests (opt in).** `verifier-profile: spec` or `auto` (Action), `PATCHPROOF_VERIFIER` (variable), or the Benchmark workflow's `verifier` input. The model returns a specification quoted from the issue; the engine validates it, writes the test, decides per example which ones show the bug, and freezes the result before the solver starts. Default `freeform`. `node-typescript` only. Details and limits: [docs/SPEC_PROFILE.md](docs/SPEC_PROFILE.md).
- **Benchmark report.** Verifier profile recorded and never pooled; solve rate, coverage and conditional repair success shown together; one column per bucket; `needs_specification` stays in the denominator.
- New engine files **outcomes.py** and **spec_profile.py**. Copy them with the rest.

Not changed: the frozen verifier rule, ordinary-CI discovery, clean replay, delivery hashes, budgets, the bounded loop and every default.

## Install the engine update

1. Extract **shadow-patch-rc30-changed-files.zip** into the root of your **shadow-patch** repository, preserving paths, on top of rc.29 (none deleted; `RC30-CHANGES.json` lists the files with hashes). If you are on an earlier release, apply the intermediate zips first.
2. Commit on a review branch and run **Engine Checks**. It installs pinned test dependencies and makes no model or sandbox calls (it also checks Node 20; the included evidence ran locally on Node 22).
3. Publish **v0.6.0-rc.30** from the reviewed commit. The Benchmark workflow checks the engine out from this tag, and the example Action reference needs it to exist.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.30.zip** into the target root. Copy every file, including the new **outcomes.py** and **spec_profile.py**. Regenerate it with:

~~~bash
python tools/export_target.py --output ../patchproof-target-v0.6.0-rc.30.zip
~~~

## Next live run

Order matters, and nothing below has been run.

1. **Legacy smoke first.** It checks that rc.30 did not disturb the path that is known to work.

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.30 |
| trials | 1 |
| split | dev |
| cases | qrcrafts-1 |
| agent_mode | legacy |
| verifier | freeform |

2. **Then the specification profile on the same case** (`verifier` = `spec`, everything else equal). The `qrcrafts-1` issue text contains both payloads exactly, which is what the profile needs; read `regression_test.spec` in the proof: status, examples, `pre_fix_states`, `dropped_examples`, `frozen_test_sha256`.
3. **Only then fresh cases.** Choose the held-out issues before running anything on rc.30, keep any case used to tune the engine out of the held-out split, run once, and quote coverage next to the solve rate. `heldout-3` and `heldout-4` are still placeholders in the manifest.

## Validation and boundaries

Final local validation: **408 Python tests, zero skips, and 2 Node helper tests**, plus Python compilation and JavaScript syntax checks. The new tests include native pipelines (real TypeScript, tsx, Node test runner; scripted model and substituted sandbox) for the specification path, the execution gate and the readiness-only run. Logs: docs/evidence/rc30-local/.

Not verified: any live model behaviour on the specification path (the prompt, how often Nemotron produces a specification the engine accepts, how often an issue is expressible at all); the Engine Checks workflow on Node 20 for rc.27 to rc.30; `npm install -g pnpm|yarn` inside the sandbox image; the known-failure path against a real project's runner output. The expected values are as correct as the issue is; the engine proves they are quoted, not that the issue is right.

---

# Earlier release notes (rc.29, rc.28, rc.27)

The install and run steps above replace the ones below. The rest is kept as history.

# PatchProof v0.6.0-rc.29 — project support, lockfile fix, edit-shape fix

rc.29 is rc.28 plus one fix from its first live run (qrcrafts-1, bounded). Setup and the verifier test passed, but the solver put `path` on the edit action instead of inside each edit, was told only "Each edit requires exactly path, old, new", and resent the identical edit 22 times until its 24 steps ran out. Now: the error names the missing or unexpected key and shows the correct shape; a `path` on the action fills an edit that has none (the path is still scope-checked, and the result carries a note); and a solver that resends the same rejected action a third time is stopped as `candidate_invalid` (only that solver session; other sessions and the run continue) instead of burning its allocation as `budget_exhausted`. The verifier is warned on repeats but never stopped by this rule. The rest of this page describes rc.27/rc.28, which rc.29 contains.

# PatchProof v0.6.0-rc.28 — project support, lockfile fix

rc.28 is rc.27 plus one fix found by the first live attempt. rc.27 refused any repository with two lockfiles, which blocked QRcrafts (`package-lock.json` plus a Bun lockfile) before any model call; rc.20 to rc.26 installed it with npm. A Bun lockfile beside exactly one supported lockfile (npm, pnpm or Yarn) is now ignored, the supported tool is used, and the proof records a warning in `runtime.package_manager.notes`. Two supported lockfiles (for example npm and Yarn) still stop the run, Bun alone is still refused, and a `packageManager` field still decides. The rest of this page describes rc.27, which rc.28 contains.

rc.27 builds on the reviewed rc.26 bounded profile (see [docs/BATCH2.md](docs/BATCH2.md)). It widens which Node/TypeScript projects the engine can set up and repair, and records exactly what ran. The implementation is locally validated; a live Nebius run of these paths is the next gate.

## What changed

- **Package managers.** The install tool comes from `packageManager` or the lockfile: npm, pnpm, Yarn Classic or Yarn Berry, with frozen installs and scripts disabled. Conflicting or missing lockfiles, Bun and Yarn Plug'n'Play stop with a message rather than installing with another tool.
- **Project folder.** `root` in `patchproof.json` selects a self-contained subfolder such as `server/`. Workspace packages are refused. PR paths carry the folder prefix.
- **`.mts` / `.cts`** sources are editable for the TypeScript adapter.
- **Known failures.** `known_failures` lists tests that already fail; the ordinary command passes only when those are the sole failures (node:test TAP, exact names).
- **New files.** `scope.new_file_dirs` lets a bounded repair create up to three source files in declared existing folders.
- **Provenance.** Every proof records engine version and file hashes, manifests and lockfiles, archive hash, package-manager command and sandbox toolchain versions.

The frozen verifier, ordinary-CI discovery, clean replay, delivery hashes, budgets and all defaults are unchanged. Details and limits: [docs/GENERALIZATION.md](docs/GENERALIZATION.md).

## Install the engine update

1. If rc.28 is already in your **shadow-patch** repository, extract **shadow-patch-rc29-changed-files.zip** into its root, preserving paths (none deleted; `RC29-CHANGES.json` lists the files with hashes). If you are on rc.27, extract the rc.28 zip first, then the rc.29 zip. If you are on rc.26, extract the rc.27, rc.28 and rc.29 zips in that order.
2. Commit on a review branch and run **Engine Checks**. It installs pinned test dependencies and makes no model or sandbox calls (it also checks Node 20; the included evidence ran locally on Node 22).
3. Publish **v0.6.0-rc.29** from the reviewed commit. The Benchmark workflow checks the engine out from this tag, and the example Action reference needs it to exist.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.29.zip** into the target root (23 engine and workflow files plus install notes). Copy every file, including the new **patchproof_runtime/known_failures.py**. Regenerate it with:

~~~bash
python tools/export_target.py --output ../patchproof-target-v0.6.0-rc.29.zip
~~~

## Next live run

The rc.26 smoke in [docs/BATCH2.md](docs/BATCH2.md) still comes first: it is the first live evidence for the bounded loop, and rc.27 changes none of its defaults. With the new tag:

| Input | Value |
| --- | --- |
| engines | v0.6.0-rc.29 |
| trials | 1 |
| split | dev |
| cases | qrcrafts-1 |
| agent_mode | bounded |

Consider repository variable `PATCHPROOF_MAX_TOTAL_TOKENS=600000` for this first run; each late solver step reserves tens of thousands of accounted tokens before real usage replaces the reservation. Keep the previous model and per-call token setting.

The new options need a target that uses them. Before relying on any of them, run one development case with the option set and read the proof: `runtime.package_manager` and `runtime.toolchain` for a pnpm or Yarn project, `baseline.known_failures` for declared failures, `project_root` and `pr_files` for a subfolder, and the solver's `create` action and candidate diff for new files.

## Validation and boundaries

Final local validation: **304 Python tests, zero skips, and 2 Node helper tests**, plus Python compilation and JavaScript syntax checks. The 45 new tests include native pipelines (real TypeScript, tsx, Node test runner, policy scripts; scripted model and substituted sandbox) for a subfolder project with `.mts` sources, a repository with a declared failing test, and a repair that creates a helper file, and a real install of npm, pnpm, Yarn Classic and Yarn Berry lockfiles. Logs: docs/evidence/rc27-local/.

Not verified: `npm install -g pnpm|yarn` inside the apt-based sandbox image; any live model behaviour with the `create` action; the known-failure path against a real project's runner output; TypeScript project references and monorepo workspaces (refused). The static interference check remains a bounded guard, not a security proof.

Generalization to unfamiliar issues still requires Batch 3: independently selected cases, reference repairs and oracles, a frozen protocol, and a held-out run. The manifest, base commits, labels and unselected held-out placeholders are not changed by this package.
