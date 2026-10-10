# PatchProof v0.6.0-rc.26 — Batch 2

This release implements the first bounded investigation/repair profile for a single Node/TypeScript package. It builds on the reviewed rc.25 code. The implementation is locally validated; a live Nebius benchmark is the next gate.

## What changed

- Repository inventory, paginated file listing, literal search, lexical symbol lookup and line-ranged reads let the model inspect files beyond its initial context.
- An independent read-only verifier investigates APIs before generating the frozen regression. Each solver starts with its own history and source overlay; hidden-test output never becomes solver feedback.
- Solvers can edit previously read, allowed source files and request ordinary baseline, TypeScript and declared build checks. They can correct compiler/test failures within the same session. Existing file/symbol scope and interference checks validate edits before execution.
- Shared budgets cover tool actions, actual HTTP requests including retries, tokens, sandbox commands and elapsed time. An optional inference dollar cap uses explicit operator-supplied prices. Sandbox charges are separate.
- Atomic progress files record separate histories, pending actions, native diagnostics, source and engine hashes, and request accounting. Stop reasons distinguish setup, specification, budget and verification failures. Checkpoints are diagnostic; automatic resume is not implemented.
- Benchmark evidence records execution mode and budgets. Reports reject mixed profiles for the same engine and requested/actual mode mismatches. Budget and specification stops stay in the failure denominator.

The ordinary-CI discovery gate, frozen verifier, candidate eligibility checks, clean replay and verified-file delivery manifest from rc.25 remain required. The default execution mode remains **legacy**; enable **bounded** explicitly.

## Install the engine update

1. Extract **shadow-patch-rc26-changed-files.zip** into the root of your rc.25 **shadow-patch engine repository**, preserving paths. Review existing local changes before overwriting a changed file. No files require deletion. The archive includes a file/hash manifest; its baseline commit identifies the local reviewed snapshot, not a published GitHub commit.
2. Commit the update on a review branch and run **Engine Checks**. It installs pinned test dependencies and makes no model or sandbox calls. The included evidence was run locally on Node 24; this GitHub gate also checks Node 20.
3. After checks pass, use the reviewed commit SHA for the benchmark, or publish **v0.6.0-rc.26** when ready. The example Action reference requires that tag to exist; no tag has been published by this work.

For targets that copy engine files, extract **patchproof-target-v0.6.0-rc.26.zip** into the target root. It contains 22 engine/workflow files plus installation instructions. Copy every file, including the new **agent_budget.py**, **context_tools.py** and **agent_loop.py**; copying only proof.py leaves an incomplete installation. Review target workflow customizations when merging the copied workflows. To regenerate the installer:

~~~bash
python tools/export_target.py --output ../patchproof-target-v0.6.0-rc.26.zip
~~~

Enable the copied workflow with repository variable **PATCHPROOF_AGENT_MODE=bounded**. For the composite Action, pass **agent-mode: bounded**. For CLI runs, export the same environment variable. Other runtimes still use legacy.

## Next live run

Start **Benchmark** from the branch containing this harness/workflow with:

| Input | Value |
| --- | --- |
| engines | Your reviewed rc.26 commit SHA, or v0.6.0-rc.26 after publishing it |
| trials | 1 |
| split | dev |
| cases | qrcrafts-1 |
| agent_mode | bounded |

Keep the previous model and per-call token setting. Use one solver session and the default shared limits initially: 40 actions, 32 HTTP requests, 250000 accounted tokens, 64 sandbox commands and 1800 seconds. A tool reply has a 4000-token completion cap. See [docs/BATCH2.md](docs/BATCH2.md) for configuration and accounting details.

Download the trial artifact and report. Review proof.json, verification-report.md, the exact candidate diff, mode/budget metadata and the independent verdict. A new diff needs its own full SHA-256 label tied to the recorded case identity. Previous labels apply only to the identical bytes and case snapshot. Confirm the delivered patch/test passes ordinary target CI before expanding the run.

**File-sharing is still a target setup prerequisite:** complete the rc.25 review's mixed .mjs/.ts ordinary-test discovery fix, commit only that CI/dependency/config setup while preserving the unfixed application source, and pin the new base/protocol before adding file-sharing-app-1. The rc.26 engine cannot make an undiscovered generated test count as CI evidence. The supplied manifest, base commits, labels and unselected held-out placeholders are not overwritten by this changed-files package.

## Validation and boundaries

Final local validation: **259 Python tests, zero skips, and 2 Node helper tests**. Python compilation, JavaScript helper syntax, workflow/Action YAML parsing, whitespace checks and the one-case development plan passed. See docs/evidence/rc26-local/ for logs and toolchain details. Package verification checks the exported installation and the changed-file overlay against the prepared tree.

The native fixtures use real TypeScript, tsx and Node checks. They find a repair file outside the initial map, observe a real wrong-API compiler error, read the missing type, correct the source, pass frozen-test and clean-replay gates, and run the delivered ordinary npm test. A separate failing fixture confirms that hidden-test failure causes no solver retry or local source delivery. Model responses and ConTree transport are substituted locally. No live inference or Nebius benchmark was run for rc.26.

This profile supports existing dependencies and at most ten existing source files per repair. It does not yet support monorepo orchestration, TypeScript project references, browser interaction, automatic dependency/config migration, new-file repairs or checkpoint resume. The deadline is checked at operation boundaries with capped call timeouts; provider transport/queue latency may return late. Static interference checks remain bounded checks, not a security proof.

The live trial will test whether the model selects useful actions and the current provider executes the flow successfully. Generalization still requires Batch 3: independently selected fresh cases, reference repairs/oracles, a frozen protocol and held-out evaluation.
