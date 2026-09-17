# PatchProof / Shadow Engineer — v0.2.0

PatchProof verifies candidate fixes. Shadow Engineer remains the optional repair
layer. This release adds external Git commit verification to the original demo.

## Status

- Local end-to-end verification works for pytest and Node's built-in test runner.
- Base/head commits, patch content, locked tests and policy are hashed.
- Direct test edits and changes outside an application-file allowlist are blocked.
- Tests can be supplied separately or drafted from base files through Token Factory.
- JSON and Markdown reports record exact commits, case identities and replay outcomes.
- SDK 0.3.6 construction has been checked against the installed package. Live Nebius
  authentication, inference and VM execution have **not** been validated.
- No QR-code repository has been received or tested. No PR/comment is posted.

## Install

Python 3.11+ and Git are required. Node 24 is needed for Node fixtures/tests.

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Run the external-commit demo

```bash
python -m shadow_engineer.demo_external --output artifacts/python-demo
python -m shadow_engineer.demo_external --runtime node-test --output artifacts/node-demo
python -m unittest discover -s tests -v
```

Each demo creates a disposable real Git repository with the known shipping fixture,
locks its test before creating candidate commits, and evaluates those commits.
Expected: `flawed rejected`, `corrected passed-checks`.
Open `VERIFICATION_REPORT.md` and `proof.json` under each candidate's output directory.
Use a new directory each run; reports and locks are never silently overwritten.
Each demo also saves fixture.bundle, preserving the exact Git commits named in its
reports. Restore it with `git clone /path/to/fixture.bundle fixture-repo`.

These are authored fixtures, not the QR project and not AI-generated repairs.
Local execution uses temporary directories, not Nebius VMs. The external verification
CLI exposes only the Nebius provider, so it does not silently execute arbitrary
repository code on the orchestrator.

The older demo remains available with `python -m shadow_engineer.cli demo`.
It uses the simpler v0.1 policy, not the external repository workflow.

## External repository workflow

Read [docs/EXTERNAL_REPOSITORY.md](docs/EXTERNAL_REPOSITORY.md) for commands.

1. Inspect a full base commit SHA without executing repository code.
2. Draft or supply a separate regression and review its expected behaviour.
3. Lock the test, issue, existing test-file list and writable source-file list.
4. Retain the printed lock digest in verifier-controlled configuration.
5. Verify a descendant candidate commit on a prepared Nebius image.
6. Review the report; a future PR integration must compare current base/head SHAs
   before attaching it or deciding a status check.

`passed-checks` means the observed gates passed. It is not a correctness proof,
a security certificate or permission to auto-merge.

## Gates

Baseline passes → locked regression fails on base → regression passes on head
→ existing suite passes → combined suite passes → fresh combined replay passes.

Test identities must match. Empty/malformed/duplicate evidence, skips, errors,
changed inputs, timeouts and replay failures prevent acceptance. Each cloud stage
starts from the same immutable prepared image.

## Scope

- Maximum 1000 tracked files / 10 MiB. Symlinks and submodules are unsupported.
- Source deletions, new application files and mode changes are currently rejected.
- Dirty/untracked worktree files are ignored; snapshots come from Git objects.
- Test files and writable application files must be explicitly selected.
- pytest and node:test are supported. Jest, Vitest, TypeScript builds and browser
  automation need a repository-specific adapter. HTML detection is only an inventory hint.
- Dependencies must already exist in a clean image; no repository install script
  runs automatically. Node dependencies requiring local node_modules need a prepared
  resolution strategy before this narrow runner can support them.
- Cloud input files are read-only and the test child drops to an unprivileged UID.
  Live enforcement is untested; an image that cannot provide it fails closed.
- Malicious code can still manipulate in-process assertions or fabricate reports.
  File hashes and read-only files do not establish independent ground truth.
- No signed attestations, automatic image preparation, webhooks, repository download,
  PR posting or fix generation are included in the external workflow.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) and [docs/QR_TEST_PLAN.md](docs/QR_TEST_PLAN.md).

## Code map

| Module | Role |
|---|---|
| repository.py | Git snapshots, path policy, lock and patch checks |
| regression_author.py | NVIDIA test drafting from selected base files |
| external_proof.py | Verification gates and reports |
| execution_harness.py | Fixed commands, timeout, input checks and evidence |
| external_runners.py | Trusted local fixture / Nebius provider |
| patchproof_cli.py | Inspect, draft-test, lock and verify commands |
| demo_external.py | Shipping fixture in a disposable Git repository |

## References

- [Nebius SDK commands](https://docs.tokenfactory.nebius.com/sandboxes/sdk/python_sdk/running-commands)
- [Token Factory inference](https://docs.tokenfactory.nebius.com/quickstart)
- [Node test runner](https://nodejs.org/api/test.html)
- [Hackathon rules](https://nebiusglobalaihackathon.devpost.com/rules)

The installed `contree-sdk==0.3.6` takes ContreeConfig/IAMAuth directly, unlike the
client constructor in our earlier prototype. This version is pinned and its
construction was smoke-tested without network calls. Live cloud validation is pending.
