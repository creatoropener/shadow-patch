# The fresh set: how cases are chosen and checked before a run

The engine is frozen at rc.34. The fresh set exists to say something about issues the engine has never seen.
Nothing here changes the engine; it changes which cases are in the manifest and how they are vetted.

## What a case must satisfy

A case has to survive five checks, in this order. A case that fails one is out, however good the bug is.

1. **A real bug in someone's repository (or an unfixed bug in one of yours), at an unfixed commit.** The base is the
   parent of the commit that fixed it. Full 40-character SHA.
2. **The runtime is `node-typescript`.** `package.json` and `tsconfig.json` at the root (or `root` in
   `patchproof_config`). The spec profile only covers this runtime.
3. **The base's own `npm test` discovers a `.ts` test on Node 20.** The benchmark image is
   `python:3.12-slim-trixie` plus apt `nodejs`, which is Node 20. Node 22 runs `.ts` files natively and expands
   `node --test "glob"` itself; Node 20 does neither, so a project whose test script depends on that is not
   discoverable here. Where the script's glob does not reach the engine's default location, the case sets
   `patchproof_config.test_directory`.
4. **The target is an exported TypeScript function with JSON arguments and a JSON result, and the test loader can
   import it.** Classes, DOM, network and timing are out of the spec profile's reach.
5. **Every value the examples need is written in the issue, inside one contiguous passage per example**, including
   argument strings (`validate_spec` refuses an argument string that is neither in the quoted passage nor a string
   literal in the source).

Checks 2 to 4 are automated by `tools/preflight_base.py`; check 5 and the correctness of the expected values by
`tools/verify_case_spec.py`.

## The two tools

```
PATH=<node20>/bin:$PATH python3 tools/preflight_base.py --repo owner/name --commit FULL_SHA \
    --module src/x.ts --export fn [--export other] [--test-directory test]
```

Installs with `npm ci --ignore-scripts` (or `npm install` without a lockfile, as the engine does), runs the
project's baseline, plants a probe test that always fails and requires its marker in the output, then plants a
passing test that imports the export the way the compiled examples do (`.js`, `.ts`, bare). It refuses to run
under a Node other than 20 unless `--allow-other-node` is given. Verdicts: `suitable`, `not_suitable`,
`could_not_check` (install or clone failed).

```
python3 tools/verify_case_spec.py --issue bench/issues/X.md --spec spec.json --base DIR --fixed DIR \
    --module src/x.ts [--test-directory test]
```

`spec.json` is what the model would return. The tool validates it against the issue with the engine's own
`validate_spec`, compiles the test with `compile_test`, runs the project's `npm test` on the base (examples that
fail on their own assertion are reproduction; examples that pass are guards) and on the upstream fixed commit
(every example must pass). If an example fails on the fix, the issue text is wrong, not the fix.

## Current state

| Case | Repo | Status |
| --- | --- | --- |
| `fresh-overlaykit-1` | Hailong-am/openapi-overlaykit (external) | preflight suitable; offline oracle check: e1-e3 fail on base, e1-e4 pass at the fix. Not run through the engine yet. |

`bench/manifest.json` still has `protocol_status: development`. The harness refuses to select a `heldout` case
until the protocol is frozen, so freezing (a new `protocol_id`, `protocol_status: frozen`) is the last step, after
the case list is final.

### Looked at and ruled out (so nobody re-checks them)

| Candidate | Why it is out |
| --- | --- |
| ipregistry-javascript `isError` (base b103c1f) | Passes discovery, fails the import probe: its loader is ts-node/esm on a CommonJS package and no import style loads `src/errors.ts`. |
| marcqualie/denvig, sebs/gurkencheck | Tests need Node 22 (native `.ts`, quoted-glob expansion). Under Node 20 the baseline is red (exit 9 and 1). Not confirmed on any Node 22 image either (denvig's baseline was red there too). |
| webpro-nl/unbash | `pnpm` 11 cannot install under Node 20, and `parse()` returns a whole AST, which no issue would write out as an expected value. |
| friedemannsommer/lcov-parser, jvpdls/seo-tools, DASPRiD/nested-search-params | `npm test` globs do not reach a `*.test.ts` in any default location (`.spec.ts`, `tests/**` expanded by sh, or `tsx --test` with no arguments finding 0 tests on Node 20). |
| xddq/schema2typebox, tamtamchik/json-deep-sort | Test script at the bug's base is jest; later commits moved to tsx. |
| subunit-money, bc3, cel-es, evatr | The buggy code is a class method or an unexported function. |
| PlanMorph (heldout-3, heldout-4) | Logic is in `.js` files; the spec profile needs a `.ts` module. |

A Node 22 image might unlock more repos of this kind (it is untested here beyond one probe), but the engine's TAP parsing and the rc.20 to
rc.34 evidence were all produced on Node 20, so that is an infrastructure decision, not a case-selection one.
