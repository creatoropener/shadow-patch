# v0.2.0 validation — 2026-09-16

Environment: Python 3.12.14, Node 24.19.0, pytest 9.1.1, Git 2.51.1.

- `python -m unittest discover -s tests -v`: 26 tests passed, zero skipped.
- Python external-commit demo: flawed rejected; corrected passed-checks.
- Node external-commit demo: flawed rejected; corrected passed-checks.
- Both corrected demos passed all six stages including combined fresh replay.
- Negative checks cover altered locks, candidate test edits, changed test identities,
  missing/invalid/skipped/duplicate evidence, replay failure, unsafe paths and symlinks.
- Worktree modifications were excluded from commit snapshots.
- Mocked inference tests confirm only selected base files enter the draft prompt,
  with no candidate context; null model output is rejected.
- CLI command parser loaded and exposed inspect/draft-test/lock/verify.
- Installed contree-sdk 0.3.6 successfully constructed a config, client, image
  reference and execution request without network calls. The old constructor failed
  against this installed package and has been replaced.

Sample reports, exact input locks and fixture Git bundles are under
examples/external_demo/python and examples/external_demo/node. These are authored
shipping examples, not the user's QR repository.

Not validated: real inference/model quality, cloud auth, remote sandbox execution,
cloud UID separation, egress limits, automatic GitHub comments/PR status, browser
QR rendering/export/decoding, or arbitrary repository compatibility. Local fixture
tests deliberately do not change OS users. No hackathon-ready deployment is claimed.
