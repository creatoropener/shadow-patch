# rc.19 installation and validation

This cumulative changed-files package includes the supplied rc.18 fix plus the
rc.19 initial-verifier prompt change. Apply it to the complete rc.17 or rc.18
shadow-patch repository, preserving paths. It is not a standalone installation.
The review base was creatoropener/shadow-patch commit 4f4372e.

1. Copy these files into shadow-patch and commit. Run Engine Checks.
2. Publish a new v0.6.0-rc.19 tag on that commit; do not move published tags.
3. In QRcrafts, set the Action reference to creatoropener/shadow-patch@v0.6.0-rc.19.
   The complete example caller is examples/action-usage/shadow-fix.yml.
4. Add docs/QRCRAFTS-ISSUE-1.md's behavior clarification to Issue #1. Review the
   payload examples as literal runtime text, not JavaScript string literals.
5. Keep the compatible image and existing secrets. No image rebuild is required.
6. On an unfixed target revision with a passing baseline, remove and reapply
   shadow-fix. Inspect accepted pre-fix assertion evidence, three evaluations,
   unchanged accepted test hash, successful clean replay, and the PR workflow.
   If the repair is already merged, use a controlled unfixed fixture revision
   rather than reverting the live application merely to rerun a demonstration.

Validation: 83 Python tests passed, including TypeScript integration tests with
TypeScript 5.6.3; 2 Node helper tests passed. Python compilation, JavaScript
syntax checks and git diff --check passed. No live Nebius run was performed.
These are local checks, not confirmation of the remote GitHub Engine Checks run.

New tests inspect the initial/retry model request and confirm non-TypeScript
prompts are unaffected. They also confirm generated content still passes through
adapter validation. No assertion acceptance rule, retry budget, solver prompt or
sandbox isolation behavior was changed by rc.19.

The README/CHANGELOG/example version references and release checksum manifest
are updated. RELEASE_FILES.sha256 covers the complete overlaid checkout, not just
the files in this archive; verify it after installation into the complete repo.
