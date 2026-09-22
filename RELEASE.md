# v0.6.0-rc.5 engineering handoff

## Purpose

This release candidate preserves the assertion gates and rc.4 diagnostics. It adds
structural stream-success and literal chunk-coverage checks. Duplicate generations
consume the existing retry allowance without repeated sandbox execution or immediate
abort. The report separates generations from executions, and records validation
failures as well as duplicates. Engine Checks exercise the actual orchestrator loop
with mocked external services and run the real TypeScript parser.

For an existing rc.4 installation with passing preflight and baseline, update the
engine files only. Reuse the image UUID, secrets and target dependencies. The image
preparation steps below apply to first-time installations or incompatible images.

The v0.5.5 green run remains the recorded live evidence. Do not present v0.6 as
validated until file-sharing Issue #3 reproduces, evaluates all three candidates,
and passes clean replay.

## Canonical workflow

Make engine changes in `creatoropener/shadow-patch`, review them through a branch,
and export the target installer from that revision:

```bash
python3 tools/export_target.py --output ../patchproof-target-v0.6.0-rc.5.zip
```

Copy the exported files into a target repository. Do not independently edit
`proof.py` or `runtimes.py` in the target; that causes the two repositories to
drift. Repository-specific files such as `package.json`, lockfiles, baseline tests
and `patchproof.json` remain owned by the target.

## Acceptance sequence

1. Merge the reviewed release-candidate changes into `shadow-patch`.
2. Export the target installer and update `file-sharing-app` from it.
3. Pin `tsx` and `typescript` in the target's `devDependencies`, update its lockfile,
   and confirm its ordinary baseline command uses `tsx` for `.test.ts` files.
4. Run **Prepare Sandbox Image** with profile `web` and save the returned UUID as
   `CONTREE_IMAGE_NODE_TYPESCRIPT` in the target repository.
5. Remove and reapply `shadow-fix` to Issue #3 once. Inspect the report before
   retrying; do not spend repeated model/sandbox calls on the same configuration.
6. Require: accepted pre-fix assertion, three evaluated candidates, at least one
   passing candidate, matching test hashes, clean replay, green workflow, and PR.
7. If all gates pass, bump `APP_VERSION` and documentation from `0.6.0-rc.5` to
   `0.6.0`, tag the release, and keep the new proof artifact as acceptance evidence.

## Local checks

The repository provides `Engine Checks` for Python compilation, runtime contract
tests, Node assertion/TAP checks, TypeScript parser integration and JavaScript
helper syntax. To include the parser integration locally, set TS_LINT_NODE_MODULES
to a node_modules directory containing typescript@5.6.3 before running unittest.
These checks do not call a model or a
Nebius Sandbox and do not replace the Issue #3 acceptance run.

Checksums for tracked source, documentation, evidence and media are recorded in
`RELEASE_FILES.sha256` and must be regenerated whenever tracked files change.
