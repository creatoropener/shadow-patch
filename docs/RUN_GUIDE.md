# Run Shadow Patch on a repository: what must be true before you label the issue

Shadow Patch is not a general bug fixer. It fits one narrow shape of repository and issue, and a run on
anything else stops early or produces a result that says nothing about the engine. Two runs on repositories
that did not fit (Tabloop #1, PlanMorph #1 and #2, see section 6) were set up from the generic steps in
[ACTION.md](ACTION.md). This page is the checklist that would have stopped both before the label was
applied. Every item names the exact failure you get when it is skipped.

Start with section 1. If the issue does not fit, nothing in sections 2 to 4 will help.

## 1. Does the issue fit? (two minutes)

| The issue is about | Runtime | Verifier | Status |
| --- | --- | --- | --- |
| A TypeScript function that returns a wrong value for given inputs | `node-typescript` | `spec` | Best fit. Recorded on the engine's two development repositories. |
| TypeScript/Node behavior across several modules, testable offline with `node:test` | `node-typescript` | `freeform` (default) | Recorded on development cases. The verifier is the weak point on unseen repositories. |
| A plain JavaScript Node package (no `tsconfig.json`) | `node-package` | `freeform` | Recorded for the v0.5.5 repair only. |
| JavaScript or HTML behavior of a static site (menu toggle, form action, storage) | `static-web` | `freeform` | Works from rc.35 when the project meets the checklist in section 2 (a `node --test` script and jsdom declared). Validated offline only; no live Nebius run covers it, and it never completed one on rc.34 or earlier. Uses jsdom, so it cannot see layout. |
| CSS, layout, responsive or visual behavior | `web-playwright` (real browser) | `freeform` | Adapter exists, no live evidence. `static-web` cannot see layout: jsdom does not evaluate media queries. |
| Python, Go, Rust, Java | their own adapters | `freeform` | Experimental. |
| "Add authentication", "redesign X", or anything with no concrete input and output | none | none | Stops `needs_specification` under `spec`; under `freeform` the model writes tests that mock the code under test. |
| Code that calls a live API, an LLM or a database | none, unless the bug is in a pure function next to it | | Point the issue at that function. |

**Rule of thumb.** If you cannot finish the sentence "calling `f(<input>)` returns `<actual>` but should
return `<expected>`" from the issue text, Shadow Patch cannot prove the fix. Held-out results are in
[BENCHMARK.md](BENCHMARK.md); no generalization to unseen repositories has been shown.

## 2. Prepare the repository (`node-typescript`)

Run these under **Node 20**, which is what the sandbox runs. A newer Node hides two problems the sandbox
will hit: it runs `.ts` files natively and it expands quoted globs itself.

1. **Root manifests.** `package.json` and `tsconfig.json` at the repository root, or `"root": "<folder>"`
   in `patchproof.json`. With both present and no `patchproof.json`, `node-typescript` is chosen on its own.
2. **The project type-checks as it stands.** `npx tsc -p . --noEmit` must exit 0. The engine runs the whole
   project through the compiler before any model call; a compile error, or a typo in `tsconfig.json`, stops
   the run at `baseline-source-check` with `readiness_blocked`. (Tabloop: `"checkJs": flase`, line 29.)
3. **`npm test` runs real tests and passes.** The output must report `# tests N` with N of at least 1. A stub
   such as `echo ok && exit 0` runs nothing: readiness reports `compatibility_coverage` as unknown or
   absent, and step 4 cannot succeed.
4. **`npm test` must run the file the engine adds.** The engine writes
   `test_patchproof_issue_<n>.test.ts` into `tests/` when `tests/` already holds at least one `*.test.ts`,
   and at the repository root otherwise. `"test_directory"` in `patchproof.json` overrides both. Before any
   repair the engine plants the new test and runs your test command; the command must run it and fail on
   it, or the run stops with `Ordinary project CI did not reproduce the frozen regression`.
   Because the sandbox is Node 20, write the script so that the shell expands the glob:
   `tsx --test tests/*.test.ts` or `node --import tsx --test *.test.ts`. Do not use
   `node --test "**/*.test.ts"` (quoted, so Node 20 does not expand it) or a script that relies on native
   `.ts` support.
5. **Pin the toolchain and commit the lockfile.** `tsx` and `typescript` in `devDependencies`. The recorded
   runs used `tsx` 4.23.15 and `typescript` 5.6.3. The engine installs from the lockfile.
6. **The code under test runs offline and deterministically.** The sandbox has none of your secrets, so code
   that calls a live API fails with an error from the call, never with an assertion, and the engine counts
   that as "did not reproduce". Aim the issue at the pure function (PlanMorph: `policy.js`'s `check`, not
   `agent.js`'s `chat`).
7. **The target is TypeScript if you use `spec`.** The module must be `.ts`, `.mts` or `.cts` with an
   exported function, and its arguments and result must be JSON. `freeform` may also import `.js` files.
   `.html` is not a source file for this adapter.
8. **`patchproof.json`: set `runtime` only when detection is ambiguous, and only to what the repository
   is.** Copying `{"runtime": "node-typescript"}` into a site with no TypeScript forces the wrong adapter.
   Accepted keys: `runtime`, `test_directory`, `scope`, `root`, `known_failures`
   (see [GENERALIZATION.md](GENERALIZATION.md)).

### Check it before you spend a run

```bash
nvm use 20 && node --version        # v20.x
npm ci
npx tsc -p . --noEmit               # must exit 0
CI=1 npm test                       # must pass and print "# tests N", N >= 1

# From a checkout of this repository: plants an always-failing probe where the engine would put the
# test, requires `npm test` to run it, then imports your export the way the compiled examples do.
python3 tools/preflight_base.py --path . --module src/foo.ts --export fooFn
```

`tools/preflight_base.py` exits 0 when suitable, 1 when not, 2 when it could not check. It does not run
`tsc`, so keep that line. `python proof.py --readiness-only` goes further (it uses the real sandbox) and
stops before the first model request, but it is a command-line flag only: the Action does not expose it, and
it does not check that the image contains `typescript` (section 4).

### Static site (`static-web`, rc.35 or newer)

A plain HTML/CSS/JS site is tested in jsdom with `node:test`. The engine delivers the regression as a
`.test.mjs` file plus a small helper, so the project has to be able to run it:

1. **`patchproof.json` says `{"runtime": "static-web"}`.** A project with a `package.json` is otherwise
   detected as `node-package`. Delete any `tsconfig.json` you only added to get a runtime.
2. **`package.json` has `"test": "node --test"`.** Plain `node --test` finds `*.test.mjs` files by itself and
   passes while there are none. `node --test *.test.mjs` does not: with no matching file, Node 20 receives
   the literal pattern and fails, so the baseline fails before any model call. A script that only reads
   another folder is caught too (item 4).
3. **jsdom is declared:** `npm install --save-dev jsdom`, and commit `package.json` and the lockfile. The
   delivered test imports jsdom through `patchproof_helpers/jsdom.mjs`, which uses the project's own copy.
   Without a declaration the test would pass in the sandbox and fail on a fresh checkout, so the run stops
   first.
4. **A new `*.test.mjs` in the repository root (or `test_directory`) is run by `npm test`.** The engine plants
   an always-failing probe test there before any model request and requires `npm test` to run it. A stub
   such as `echo ok` fails this check.
5. **Pass the image.** The example workflow passes only the TypeScript image. Add
   `image-static-web: ${{ secrets.CONTREE_IMAGE_STATIC_WEB }}` (or use `sandbox-image`), built with
   **Prepare Sandbox Image** profile `web` or `all`.
6. **The issue is about behavior jsdom can show:** an attribute, a DOM change after an event, text, storage.
   Not layout, media queries, scrolling or visual state.

## 3. Write the issue the verifier can test

Say what happens, what should happen, in which file and function, and what must **not** change. Then give
every example as one block that carries all of its own values:

```markdown
`<function>` in `<path/to/file.ts>` returns the wrong value.

### Example 1
Call: `<function>(<arguments, exactly as JSON>)`
Returns: `<actual output>`
Should return: `<expected output>`

Must not change: `<behavior that is already correct>`
```

With `verifier-profile: spec`, the engine checks that:

- each example's quotation appears in the issue word for word, and is one contiguous passage (one or two
  short lines earlier in the issue, such as a table's column titles, may come first);
- every string and number the example uses, arguments included, is inside that passage;
- the arguments and results are JSON, and the target is a call-and-return function.

DOM, network, timing, files, classes and callbacks are outside what `spec` can express; an issue that
needs them stops with `needs_specification`. See [SPEC_PROFILE.md](SPEC_PROFILE.md) for the exact rules and
[QRCRAFTS-ISSUE-1.md](QRCRAFTS-ISSUE-1.md) or `bench/issues/fresh-overlaykit-1.md` for finished issues.

## 4. Configure the workflow, secrets and image

- Copy [`examples/action-usage/shadow-fix.yml`](../examples/action-usage/shadow-fix.yml) to
  `.github/workflows/shadow-fix.yml`, pinned to a reviewed tag, never a branch.
- **`agent-mode: legacy`.** `bounded` has never completed a live run. An older copy of the example workflow
  switched it on by accident, and PlanMorph #2 stopped with `budget_exhausted` before writing a test.
- **`verifier-profile`:** `spec` for an issue made of function calls with example values; leave it out
  (`freeform`) for anything else; `auto` tries `spec` and falls back to `freeform`, recording both.
  `spec` and `auto` apply to `node-typescript` only.
- **Secrets:** `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID`, a model (`NEBIUS_MODEL`), and the image below.
  Secrets are not shared between repositories.
- **The image must be the v0.7 web image or newer.** Run **Prepare Sandbox Image** (profile `web` or `all`)
  and put the UUID it prints into `CONTREE_IMAGE_NODE_TYPESCRIPT`. That image holds `typescript`,
  `tsx` and `jsdom` in `/opt/patchproof/node`. An older image has `tsx` but no `typescript` there, so every
  generated test is statically refused with `generated TypeScript lint tooling unavailable` and the run
  ends `verifier_invalid` after three identical refusals. **Readiness reports "ready" in that case**,
  because it checks `tsx` and your own `tsc`, not the engine's. The error text is the only warning.
- **Repository settings:** Actions enabled; *Settings, Actions, General, Allow GitHub Actions to create and
  approve pull requests*; `actions/checkout` with `fetch-depth: 0`.
- **Apply the exact label `shadow-fix` after the workflow is on the default branch.**

## 5. Read the result

Open `proof.json` and read `outcome.bucket`, `outcome.stage` and `error` before anything else.

| What you see | Cause | Fix |
| --- | --- | --- |
| `readiness_blocked`, stage `baseline-source-check`, "Required baseline TypeScript check is failed" | The project does not type-check. `source_check.baseline_output` names the compiler line. | Fix `tsconfig.json` or the code (item 2). |
| `readiness_blocked`, "Ordinary project CI did not reproduce the frozen regression" | `npm test` does not run the file the engine placed, or does not fail on it. | Item 4: glob, `tests/` convention, or `test_directory`. |
| `compatibility_coverage` warning, "did not report a passed-test count" | The baseline runs no tests. | Item 3. |
| `verifier_invalid`, "TypeScript lint tooling unavailable" | The sandbox image has no `typescript`. | Section 4: rebuild the image, update the secret. |
| `readiness_blocked`, stage `runtime-detection`, "A static-web project needs a test command and jsdom" | No `test` script, no `package.json`, or jsdom not declared. | Static-web checklist items 2 and 3. |
| `readiness_blocked`, stage `baseline`, "did not run a test file placed at" | `npm test` does not run a new `*.test.mjs` in that folder (a stub, or a script that reads another folder). | Static-web checklist items 2 and 4. |
| `verifier_invalid`, "Regression uses a sandbox-only dependency" | rc.34 or earlier on `static-web`: the adapter's own prompt required a sandbox path and the engine refused it. | Use rc.35 or newer. On rc.35 a model that still writes a sandbox path gets a retryable message, not a stop. |
| `verifier_invalid`, other messages | The generated test was refused before it ran; `generation_attempts[].diagnostic` says why. | Read it; usually the issue is too vague. |
| `no_reproduction`, test output shows an `error:` and no assertion | The test hit the network, a missing secret or an import it cannot load. | Item 6 or 7: aim at a pure, importable function. |
| `needs_specification` | The issue states no expected values for calls. | Section 3. |
| `spec_invalid` | The values are not quoted in the issue. `rejected_examples` lists each refusal. | Quote the values; one contiguous block per example. |
| `budget_exhausted` | Usually bounded mode. | `agent-mode: legacy`. |
| `verified`, PR on `shadow-fix/issue-<n>` | Done. | Review the diff, the frozen test and the report. Merge by hand. |

A green workflow is not evidence of a new PR. Check `pull-request-url` and the linked existing PR. Change
the one thing the table names before you re-run; re-running unchanged repeats the result.

## 6. What the first attempts got wrong

| Repository | What was wrong | What a fitting setup would look like |
| --- | --- | --- |
| Tabloop #1 (mobile "Back Home" link) | `"checkJs": flase` in `tsconfig.json`; no `.ts` files; `npm test` is `echo ... && exit 0`; `patchproof.json` forces `node-typescript`; the bug is a CSS layout problem. | Not a candidate for `node-typescript` or `static-web`. A layout bug needs `web-playwright` (unproven), a real test command and no `tsconfig.json`. |
| Tabloop #2 (root-absolute form action) | The repository was fine for the runtime. On rc.34 the model wrote a sound jsdom test, exactly as the adapter's prompt asked, and the engine refused it before it ran because it contained `/opt/patchproof/`. | Fixed in the engine in rc.35 (replayed offline, see the changelog). To run it: rc.35 pin, `"test": "node --test"`, `npm install --save-dev jsdom`, and `image-static-web` in the workflow. |
| PlanMorph #1 (ownership checks) | No concrete inputs and outputs; the first image lacked `typescript`. | Not a candidate until the issue states inputs and expected results. |
| PlanMorph #2 (eligibility) | The model tested `chat()`, which calls the Anthropic API, so every test died on `invalid x-api-key`; it also asserted a sentence that appears nowhere in the code. | Issue aimed at the pure functions in `policy.js`, with calls and expected values written out. |

A repository that fits: file-sharing-app-1 at `bf939812d176434f0b11dcdd9df4260dbd80dc8f`. `npm test` is
`tsx --test --test-reporter=tap tests/*.test.ts`, `tests/` holds a `*.test.ts`, the lockfile pins `tsx`
4.23.15 and `typescript` 5.6.3, and the target is the exported `formatBytes` in `lib/utils/format.ts`.
Its pre-run check is recorded in [CHANGELOG.md](../CHANGELOG.md).
