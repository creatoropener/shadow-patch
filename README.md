# Shadow Engineer

**Verified Autonomous PR Resolver — powered by PatchProof.**

Version 0.1.0 is the executable verification foundation, not yet a deployed GitHub App.
Public name: Shadow Engineer. Workflow label: `shadow-fix`. Verification engine: PatchProof.

## Run the working demo

Use Python 3.11 or newer. From this directory:

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -e .
python -m shadow_engineer.cli demo
python -m unittest discover -s tests -v
```

Expected demo result: `verified`, winner `3`, three candidates evaluated.
Open `artifacts/PR_EVIDENCE.md` for the report and `artifacts/proof.json` for logs,
test counts, execution IDs and content hashes. Reports are overwritten on rerun;
use `--output artifacts/run-2` to retain another run.

The bundled bug mishandles tag whitespace, empty strings and case-insensitive
duplicates. Inputs and candidate fixes are scripted in local demo mode. Tests
really execute; outcomes are not mocked. Every test execution uses a new temporary
directory. This is not VM isolation and is only for the included trusted fixture.

## Implemented

- Passing baseline required before repair starts.
- Regression must fail on the original implementation; collection errors do not qualify.
- Up to three candidates evaluated in order; first verified candidate wins.
- Candidate edits restricted to existing application Python files; test edits rejected.
- Regression pass, suite pass and separate fresh replay required.
- Missing evidence, skips, empty suites and replay failures reject the patch.
- Structured evidence and Markdown report; no invented passing test counts.
- Optional Token Factory inference adapter with separate test/patch prompts.
- Optional Contree execution adapter using the same clean base image for each branch.

## Cloud demo — integration preview

This path is implemented against the linked documentation but has **not been
live-tested**. The local demo does not satisfy the hackathon's runtime model requirement.
Do not submit it as evidence of Nebius execution.

```bash
python -m pip install -e '.[cloud]'
```

Set these environment variables in your shell or deployment secret manager:

| Variable | Value |
|---|---|
| `NEBIUS_API_KEY` | Your Token Factory / sandbox credential |
| `NEBIUS_MODEL` | Exact available `nvidia/...` model ID from your account |
| `CONTREE_BASE_URL` | Sandbox endpoint supplied by Nebius |
| `CONTREE_IMAGE` | Immutable prepared image UUID with Python and pytest installed |

Then run:

```bash
python -m shadow_engineer.cli cloud-demo --output artifacts/cloud-run
```

Use a prepared image with no embedded credentials or unrelated files. The cloud
runner forks each execution from that same image; it never promotes a candidate's
filesystem into the replay. Dependency setup, image import and cloud retention
management are currently manual. Record the image UUID and dependency versions
with live demo evidence. Cloud SDK dependencies are deliberately not presented as
a tested lockfile; pin them after the first integration test.

Inference occurs through Token Factory on the orchestrator. Generated code is sent
to Contree for execution. API keys are not sent to the execution harness. A new
test is generated in a separate model call without proposed patches in its context.
This provides role separation, not independent ground truth.

## Project structure

```text
shadow_engineer/proof.py     Verification gates and provider contract
shadow_engineer/runners.py   Local fixture and Nebius adapters
shadow_engineer/model.py     NVIDIA inference via Token Factory
shadow_engineer/fixture.py   Seeded bug, regression and candidate patches
shadow_engineer/cli.py       Demo commands and evidence reports
tests/test_proof.py          Negative and positive verification tests
docs/ROADMAP.md              Next milestones and acceptance criteria
docs/THREAT_MODEL.md         Current trust boundaries and deployment blockers
```

## Current boundaries

No webhook server, GitHub authentication, repository clone, durable job queue,
automatic PR creation, browser dashboard or deployment is included in 0.1.0.
The core supports a small file map and a fixed pytest command, not arbitrary repos.
It requires a green existing baseline and does not repair already failing suites.
The checks establish observed test outcomes; they cannot prove correctness.
Generated code can manipulate tests or reports at runtime. See the threat model
before extending this prototype beyond a controlled demonstration repository.

## References checked for this release

- [Hackathon rules](https://nebiusglobalaihackathon.devpost.com/rules)
- [Token Factory quickstart](https://docs.tokenfactory.nebius.com/quickstart)
- [Nebius SWE sandboxes](https://docs.tokenfactory.nebius.com/sandboxes/swe-agents)
- [Contree setup](https://docs.tokenfactory.nebius.com/sandboxes/sdk/python_sdk/getting-started)
- [Contree command execution](https://docs.tokenfactory.nebius.com/sandboxes/sdk/python_sdk/running-commands)

Before submission, demonstrate an actual NVIDIA model call on Nebius, publish the
repository with its license, and record the live issue-to-PR flow.
