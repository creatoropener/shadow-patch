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
