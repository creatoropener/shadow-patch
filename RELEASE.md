# PatchProof v0.6.0-rc.25 — audit fixes

Prepared from the supplied rc.24 repository. This is a local engineering update, not a published tag or a new Nebius benchmark result.

## What changed

- TypeScript configuration is resolved by the target compiler with `--showConfig`, preserving JSONC, inherited options and project ambient declarations. Required source checks report passed, failed or unavailable; unavailable checks cannot authorize a repair.
- Regression tests use discoverable filenames. Byte-stream helpers and declarations are copied into the PR beside the test. Legacy helper imports are normalized before the test is frozen and hashed. The ordinary target test command must reproduce the frozen test before candidates are generated.
- `scope.allowed_paths` and `scope.protected_symbols` make declared boundaries eligibility requirements. The Node AST guard rejects introduced assertion/runtime mutations, including common aliases. Unconfigured scope is explicitly reported as unrestricted.
- A passing eligible candidate can reach clean replay even if another strategy cannot generate a patch. All three attempts and their individual failures remain in the race record.
- Pytest evidence records actual exception types and test phases. Runtime errors containing the text `AssertionError` no longer count as reproduction. Simple constant aliases in message matchers are checked, contradictory wording guidance is removed, and checker exceptions do not silently pass.
- The context budget no longer stops discovery at the first oversized block, and file eligibility is separate from the rendered context.
- Benchmark patches use exact UTF-8 bytes and full SHA-256. New trials quarantine old proof files, record fresh identities and proof digests, preserve protocol snapshots, and reject inconsistent success/exit evidence. Oracles require a recognized assertion on the base and a passing reference repair with positive test counts.
- Reports preserve recorded split membership and refuse to pool different protocols. Former held-out issues are development cases. Historical artifacts remain untouched; two fresh held-out placeholders remain unselected.
- PR workflows stage only the verified file manifest, after checking every delivered file hash.

## Install into shadow-patch

1. Extract `shadow-patch-rc25-changed-files.zip` into the **shadow-patch repository root**, preserving paths. It contains changed and new files only. No source files need deleting. Keep your target projects' dependencies and secrets separate.
2. Commit on a review branch and run **Engine Checks**. The workflow installs its compiler/test dependencies; it makes no model or sandbox calls.
3. Review the diff, then publish/tag `v0.6.0-rc.25` when ready. The example reusable Action references that tag; it will not resolve until you publish it. A commit SHA can be used instead for an unpublished trial.
4. For a copy-installed target, use the separate `patchproof-target-v0.6.0-rc.25.zip`, or regenerate it with:

   ```bash
   python tools/export_target.py --output ../patchproof-target-v0.6.0-rc.25.zip
   ```

   The new `scope_policy.py`, `tools/pr_files.py`, and runtime helpers are required. Copy the whole installer, not just `proof.py` and `runtimes.py`.
5. Existing v0.7 web/all images already contain the classic TypeScript API and tsx. No image recipe change is required by this update; runtime helpers are uploaded by the engine on each run. Older images without those tools must be refreshed. The target still needs its own working compiler, Node type definitions and ordinary test dependencies.

## Scope configuration

The benchmark now applies this policy to **file-sharing formatting issue #1 only**:

```json
{
  "runtime": "node-typescript",
  "scope": {
    "allowed_paths": ["lib/utils/format.ts"],
    "protected_symbols": {"lib/utils/format.ts": ["formatEta"]}
  }
}
```

Paths are exact repository-relative files. Protected symbols are named top-level JS/TS declarations or Python functions/classes. They are checked against the original source; Python decorators are included. `test_directory` can select a nonstandard generated-test directory.

A repository's policy applies to every issue it runs. Do not leave the formatting-only policy in place when running crypto issue #3; supply an appropriate policy for that task. These declarations constrain source edits. They do not prove every indirect behavioral effect: retain adjacent compatibility tests and human review. The fixture checks ETA behavior as well as the changed function.

## Validation and remaining work

Validation passed: **244 Python tests, zero skips, and 2 Node helper tests**. Python compilation, JavaScript syntax checks, diff whitespace checks, and the two-case development plan also passed. The release evidence contains the complete local test log. The tests include a real TypeScript compiler/Node pipeline with JSONC inheritance, restricted ambient types, a global declaration file, a protected adjacent function, an isolated generation failure, clean replay, and an exported tree that passes ordinary `npm test` without sandbox mounts. Model and ConTree calls in that fixture are substituted locally.

The local toolchain is Python 3.12.14, Node 24.19.0, TypeScript 5.6.3 and tsx 4.20.6. GitHub Engine Checks remains on Node 20. No remote inference, Nebius execution, PR creation, tag publication or deployment was performed during this update.

Known boundaries:

- TypeScript project-reference graphs are explicitly unavailable in this profile; an owning-project adapter is still needed. The native TypeScript 7 CLI has not been exercised locally.
- Discovery verifies the adapter's ordinary target test command, not every job in an arbitrary CI workflow. The Node assertion classifier expects TAP. Configure a Node-test-compatible command such as `node --import tsx --test --test-reporter=tap tests/*.test.ts` where appropriate.
- A static-web regression that depends on engine-only jsdom cannot be exported as a verified PR until the target has a portable dependency/test harness. This now blocks visibly.
- The interference check detects common AST forms; it is not a security boundary against arbitrary hostile JavaScript or Python. Message-pin checking is also bounded, not general semantic analysis.
- New exact-hash reports do not reuse short normalized legacy labels. Review the raw diff and record a full hash plus the trial's `case_sha256`.
- No fresh unseen set has been selected, independently judged or frozen. The current manifest is development-only; the placeholders deliberately block held-out execution. Generalization remains unproven.

After Engine Checks passes in GitHub, the next controlled live check is one trial each on `qrcrafts-1` and `file-sharing-app-1`, split `dev`, using the reviewed rc.25 revision. Keep the proof artifacts and review both the proposed patch and final target CI. Increase the budget only after diagnosing those results. Bounded repository investigation and the independent unseen pilot remain subsequent audit batches.
