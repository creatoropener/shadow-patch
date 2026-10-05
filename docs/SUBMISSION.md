# Submission draft

## Project name

Shadow Engineer

## Title

Shadow Engineer — Verified Autonomous PR Resolver

## Tagline

Turn labelled issues into pull requests backed by independent regression testing
and clean-sandbox replay.

## Track

Coding and Agentic Engineering

## Inspiration

Code generation is only one step in fixing a bug. Maintainers still need to
reproduce the problem, check what a patch changes, and decide whether its tests
are meaningful. We built Shadow Engineer to make that evidence part of the
issue-to-PR workflow rather than leave it as a claim in an agent's summary.

## What it does

A maintainer applies `shadow-fix` to an issue. PatchProof first checks the selected
sandbox runtime and existing baseline, then generates a regression from the issue
and original repository and confirms that it fails with an actual assertion on
the unfixed code. Separate solver calls then produce
three candidate repairs. Each runs in an isolated Nebius sandbox branch and must
pass existing tests plus the frozen regression. The winning patch is replayed
from a clean image before the workflow opens or updates a PR. Merge remains a
human decision.

## How we built it

The orchestrator is Python running in GitHub Actions. It uses NVIDIA Nemotron
through Nebius Token Factory inference; the first recorded repair used
`nvidia/Nemotron-3_5-Lightning` and the later repairs and the benchmark used
`nvidia/nemotron-3-super-120b-a12b`. Nebius Sandboxes execute repository bootstrap,
tests, isolated candidate evaluations and clean replay. Runtime adapters separate
application language, test framework and image selection. The first recorded repair
used the earlier Node adapter and a loader for a standalone TypeScript utility.
The v0.6 engine replaces that narrow loader with an explicit pinned `tsx` contract,
and two further repairs were recorded on it.

The verifier test is created before repair and excluded from solver prompts.
Source-path restrictions block direct edits to protected files. Hash checks
compare regression bytes before and after execution. Existing baseline failures
can inform one bounded correction, but hidden-regression results never feed back
to a solver. These controls provide specific test evidence, not formal correctness
or a security guarantee against hostile code.

## Demonstrated result

In creatoropener/file-sharing-app, file sizes and speeds displayed literal
JavaScript fragments instead of readable units. The recorded green run evaluated
three candidates, rejected one that produced `1.0KB` without the required space,
and selected candidate 1 from the two passing candidates. Clean replay passed
three baseline tests and two regression tests. The workflow updated PR #2 and
finished successfully. This demonstrates one TypeScript utility repair, not
whole-application or universal multi-language correctness.

Two later repairs on the v0.6 engine are recorded in EVIDENCE.md: a cryptographic
IV-seed bug in file-sharing-app (#3) and WiFi QR escaping in QRcrafts (#1, PR #3).
We then froze the engine at v0.6.0-rc.21 and benchmarked it. It repaired and accepted
6 of 6 trials on the two repositories it was developed against, and 0 of 6 on two
unseen repositories, where the verifier never accepted a test. There were no false
accepts. We report this gap rather than hide it; details are in BENCHMARK.md.

## Challenges and learning

Early runs failed during inference response parsing and test setup. Later, a
candidate broke existing low-speed formatting; the verifier correctly refused
the repair. We added actionable validation feedback, protected baseline-only
corrections, and clearer failure-stage reports. A notification tried to reread a
report after PR creation; the corrected workflow links the PR directly. Python
bytecode is now prevented on the runner and ignored by the repository.

## What makes it distinctive

The contribution is the combination of test-before-repair, withholding the new
regression from solvers, isolated candidate evaluations, clean replay, and an
inspectable PR report. We do not claim that competing coding agents lack all
independent verification, or that these mechanisms are individually novel.

## Next

Fix the verifier failures seen on unseen repositories (nested tests, repository-specific
alias guidance, API type-checking), re-measure on new held-out issues, demonstrate
more repositories and runtimes, record stronger commit-bound evidence,
improve hostile-code defenses and cost reporting, then turn the Actions MVP into
an installable GitHub App. Candidate evaluation is currently sequential.

## Platform feedback

Sandbox snapshots and fresh-image replay made separate verification stages
practical. Setup needed clearer distinctions between model access, project
authorization, Sandbox access, and image toolchains. Bounded inference diagnostics
were essential when responses were empty or hit the output limit. These observations
come from this project's development, not a benchmark against other platforms.

## Links for the form

- Source repository: https://github.com/creatoropener/shadow-patch
- Working demonstration: https://github.com/creatoropener/file-sharing-app/pull/2
- Later repair: https://github.com/creatoropener/QRcrafts/pull/3
- Recorded run: https://github.com/creatoropener/file-sharing-app/actions/runs/35464615209
- Public video URL: add after uploading the final recording to YouTube.

The source repository must receive this consolidated release before submission.
The video included in the delivery is a recorded-evidence walkthrough cut, not a
new inference run. Use the narration and capture plan in DEMO.md to finish the
public demo with footage of the actual workflow/modules in use.

## Submission requirements checked 2026-09-20

The rules request a working demo/test build, a public repository with an open-source
license and setup instructions, a public YouTube demonstration shorter than three
minutes, a track selection, and feedback on the required tools. The application
must use Nebius and an NVIDIA open model. Explain significant development during
the event if the project predates it. Deadline shown: October 30, 2026, 10:00 a.m.
Pacific. Recheck before sending. Source: [official rules](https://nebiusglobalaihackathon.devpost.com/rules).

The engine's existing MIT license is preserved. Confirm the entrant's own dates
and eligibility rather than inferring them from this draft. No submission or
public video upload has been made by this packaging step.
