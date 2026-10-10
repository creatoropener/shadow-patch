# Batch 2: bounded Node/TypeScript investigation

rc.26 adds an opt-in investigation and repair loop around the existing verification pipeline. It is a local implementation release, pending live evaluation. It does not establish a new success rate.

## Enable the profile

For a CLI or copied-engine installation, set `PATCHPROOF_AGENT_MODE=bounded`. The copied workflow reads a repository variable with that name. For the composite Action, pass `agent-mode: bounded`. Without this setting, `legacy` retains the previous generation flow. Bounded mode explicitly rejects runtimes other than `node-typescript`.

The first controlled benchmark is one `qrcrafts-1` development trial with the rc.26 engine, `agent_mode=bounded`, one solver session, and the existing model/token limit. The workflow defaults to this case only. Complete file-sharing's normal-CI TypeScript setup and pin its new unfixed base before including `file-sharing-app-1`; changing the engine does not fix that target's discovery mismatch.

## What the loop does

The engine builds an immutable inventory before generating the verifier. The model receives a small initial map and can use paginated `list`, literal `search`, lexical `symbols`, and line-ranged `read` actions to inspect files outside that map. Source hashes identify the exact text observed. The inventory skips credentials in dotfiles, symlink traversal, engine helpers, benchmark files and legacy archives. Existing ordinary tests are readable compatibility requirements and are never editable.

The verifier has a read-only session. It investigates APIs and reports findings to the existing regression generator. If reproduction fails, only the verifier can inspect its own diagnostics and continue within its remaining allocation. The final regression must still reproduce an assertion failure, remain unchanged, and be discovered by ordinary target CI before a solver starts.

Each solver starts with a fresh history and source overlay from the original snapshot. The solver can make exact-match edits to allowed existing source files, after reading the current file. Edits are cumulative within that session. File/symbol scope and the existing Node interference policy run before edited source executes. The solver can request named `baseline`, `typecheck`, and declared `build` checks. These execute in branches of the pre-verifier sandbox; their output can inform a correction. Arbitrary shell, dependency installation, new source files and test edits are not model tools.

`finish` requires a nonempty patch plus passing ordinary baseline and TypeScript checks on the latest edit. PatchProof then independently rechecks the submitted candidate and evaluates the frozen hidden regression once. Hidden results never return to a solver. Identical final source patches are deduplicated across solver sessions. An eligible winner must pass clean replay and the existing exact-file delivery checks before the local checkout changes.

## Limits

These limits apply to bounded mode and are shared across verifier generation, HTTP retries, all solver sessions, sandbox preparation, verification, and replay where applicable.

| Environment variable | Default | Meaning |
| --- | ---: | --- |
| `PATCHPROOF_AGENT_CANDIDATES` | 1 | Independent solver sessions; 1–3, sharing one budget |
| `PATCHPROOF_MAX_AGENT_STEPS` | 40 | Total investigation/repair actions |
| `PATCHPROOF_MAX_MODEL_REQUESTS` | 32 | Actual HTTP requests, including retries and verifier generation |
| `PATCHPROOF_MAX_TOTAL_TOKENS` | 250000 | Total accounted input + output tokens |
| `PATCHPROOF_MAX_SANDBOX_COMMANDS` | 64 | All wrapped sandbox commands, including policy and replay checks |
| `PATCHPROOF_MAX_RUN_SECONDS` | 1800 | Run deadline checked at operation boundaries |
| `PATCHPROOF_MAX_COST_USD` | unset | Optional inference dollar cap |
| `PATCHPROOF_INPUT_USD_PER_MILLION` | unset | Operator-supplied input price |
| `PATCHPROOF_OUTPUT_USD_PER_MILLION` | unset | Operator-supplied output price |

The verifier receives at most 8 tool actions in total, including reinvestigation; each solver receives at most 24. A tool-action reply is capped at 4000 completion tokens, or the lower configured `NEBIUS_MAX_TOKENS`. Regression generation keeps the configured per-call completion limit. All calls still count toward the shared request/token budget.

Before each HTTP request, the engine reserves UTF-8 prompt bytes plus overhead and the maximum completion tokens as a conservative token allowance. Provider-reported usage replaces that reservation when available. Failed calls and responses without usage retain their full reservation. This may stop earlier than a tokenizer-aware estimate; it prevents unknown usage from becoming free retries. An unexpected provider usage overrun is recorded and stops further work.

No provider price is guessed. A dollar cap requires both prices and fails setup if either is absent. Cost accounting is inference-only; sandbox billing is not covered. Passing a dollar cap in legacy mode is rejected. Request and command timeouts are capped by remaining time, but this is not a hard external cancellation service: backend queue/transport latency may delay return, and the engine stops at the next boundary. The surrounding CI timeout remains relevant.

## Checkpoints and reasons

`proof.json` and `verification-report.md` are written atomically as progress changes. The proof records separate role histories, pending actions, source inventory and archive hashes, read/edit hashes, native diagnostic output, and a per-request token/cost ledger. Checkpoints support diagnosis after interruption; automatic resume is not implemented. The original archive, not a checkpoint containing hidden tests, remains the solver's source.

Structured reasons include `blocked_setup`, `needs_specification`, `budget_exhausted`, `candidate_invalid`, and `verification_failed`. A run that exhausts search budget after finding a passing candidate may still replay it if command/time allowance remains. Otherwise it stops with the budget reason. The benchmark keeps budget/specification stops in the failure denominator and rejects a report mixing modes or budgets for the same engine. Requested/actual mode mismatches are invalid evidence. Source scope errors remain in the tool/candidate diagnostics.

## Validation and current boundaries

Native fixtures use the real TypeScript compiler, tsx loader, Node test runner, scope checks, frozen regression, and clean replay. They demonstrate a repair file outside the initial map, a wrong API member diagnosed by the compiler, a corrected source edit after reading its type, successful ordinary target CI, and a hidden failure that causes no solver retry or delivery. Model responses and ConTree transport are substituted in these offline fixtures. A transport-retry test separately verifies request accounting through the actual inference wrapper.

This validates the control flow and local execution contracts. It does not measure whether Nemotron chooses good actions on unfamiliar repositories or establish Nebius API compatibility for a live trace. Run GitHub Engine Checks on Node 20, then the controlled live benchmark and independent diff review before expanding scope.

The bounded profile currently supports one Node/TypeScript package and its existing dependencies. Inventory is limited to 10000 text files/64 MB, with a 1 MB per-file limit; oversized files are reported as skipped and are not editable. Reads return up to 200 lines/8000 characters; lexical symbol search is not a language server. Monorepo orchestration, TypeScript project references, browser interaction, automatic dependency/config migration, new-file repairs, and autonomous checkpoint resume remain outside this profile. Existing other runtime adapters remain available in legacy mode. Browser tools should be added when a browser defect is selected and a testable execution contract is available.

The benchmark manifest is not retuned by this release. Preserve current base commits, prior snapshots and unselected held-out placeholders. Batch 3 still requires fresh independent cases, reference repairs/oracles and a frozen protocol.
