# Compatibility policy

PatchProof does not treat the presence of an adapter as proof that every project
using that language is supported. A runtime combination moves through three states:

| State | Meaning |
| --- | --- |
| Recorded | At least one linked Nebius run reproduced a real defect, evaluated all candidates, replayed the winner, and produced a PR |
| Release candidate | Deterministic runtime contract and local engine checks exist; a linked Nebius acceptance run is still required |
| Experimental | Adapter code exists, but no current acceptance evidence is claimed |

## Current matrix

| Combination | State | Boundary |
| --- | --- | --- |
| Historical Node + standalone TypeScript utility loader (v0.5.5) | Recorded | One import-light formatting utility only; retained as historical evidence |
| Node 20 + pinned TypeScript + pinned tsx + node:test (v0.6) | Release candidate | Conventional package root with `package.json`, `tsconfig.json`, locked dependencies, project-aware generated-test type checking and a passing repository baseline |
| Python + pytest | Experimental | Conventional root environment and deterministic pytest suite |
| Static web + node:test/jsdom | Experimental | Offline HTML/CSS/JavaScript behavior supported by the adapter's DOM harness |
| Python Playwright, Java, Maven, Gradle, Go and Rust | Experimental | Conventional layouts described in `runtimes.py`; no current-release live acceptance evidence |

## Promotion gate

A combination is not described as recorded support until its acceptance run has:

1. Passed image/runtime preflight and the original repository baseline.
2. Produced an independent pre-fix assertion failure—not a syntax, import or setup failure.
3. Completed all three isolated candidate evaluations.
4. Selected at least one candidate that passed baseline plus the frozen regression.
5. Passed clean replay with unchanged regression hashes.
6. Produced a green workflow and reviewable pull request linked from the evidence.

Unsupported layouts should stop at detection or preflight with an actionable
`BLOCKED` report. They must not be presented as failed application repairs or
silently downgraded to another adapter.
