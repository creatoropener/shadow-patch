# Submission text: Shadow Patch

## Project name

Shadow Patch

## Title

Shadow Patch: verified autonomous pull requests

## Tagline

Turn labelled issues into pull requests backed by independent regression testing
and clean-sandbox replay.

## Track

Coding and Agentic Engineering

## Inspiration

Code generation is only one step in fixing a bug. A proposed patch is not proof that the bug is fixed. Maintainers still need to reproduce the problem, verify that the regression test is meaningful, and ensure that the fix does not break existing behavior.

We built Shadow Patch to make this evidence part of the issue-to-PR workflow. Instead of trusting an agent's explanation, Shadow Patch requires a regression test, isolated candidate evaluation, and a clean replay before presenting a repair for human review.

## What it does

A maintainer applies the "shadow-fix" label to a GitHub issue. Shadow Patch checks the selected sandbox runtime and existing test baseline before making model calls.

A verifier model generates a regression test using the issue and original repository. Shadow Patch confirms that the test fails on the unfixed code because of an actual assertion failure. The test is then frozen and withheld from the repair models.

Three separate solver strategies propose candidate fixes. Each candidate runs in an isolated Nebius Sandbox and must pass both the existing tests and the frozen regression test. Shadow Patch selects the best passing candidate (fewest changed files, then fewest changed lines, then fastest) and replays it from a clean sandbox image.

After successful verification, the workflow opens or updates a pull request containing the code changes and verification report. If verification fails, the workflow stops without opening a new PR and comments the reason on the issue. A developer always makes the final merge decision.

One Nebius API key covers both Token Factory inference and Sandboxes, so a full run (a verifier plus three solvers) fits inside a single GitHub Actions job.

## How we built it

Shadow Patch is orchestrated in Python through GitHub Actions and is packaged as a reusable GitHub Action. It uses NVIDIA Nemotron models through Nebius Token Factory for regression-test generation and candidate repair. Our recorded development runs initially used "nvidia/Nemotron-3_5-Lightning" and later used "nvidia/nemotron-3-super-120b-a12b". We also tried "nvidia/Nemotron-3-Ultra-550b", which used too many tokens for this workload.

Nebius Sandboxes, accessed through "contree-sdk", provide isolated environments for repository setup, baseline tests, regression checks, candidate evaluation, and clean-image replay. Runtime adapters separate repository and toolchain configuration from the verification engine. For Node.js and TypeScript projects, the v0.6 engine uses an explicit, pinned "tsx" test-running contract.

We also implemented safeguards around the verification process:

Test before repair: The regression test is generated and validated against the unfixed code before candidate fixes are attempted. Hidden regression: The regression test is excluded from solver prompts, reducing the opportunity for candidates to tailor their fixes to the test. Isolated evaluation: Each candidate is tested in its own sandbox branch. Source-path restrictions: Designated protected files cannot be edited directly by the repair process. Integrity checks: Hash comparisons help verify that regression-test bytes remain unchanged. Clean replay: The winning patch is reapplied and verified from a fresh sandbox image before pull-request creation.

These controls provide inspectable test evidence. They do not establish formal correctness or guarantee security against hostile code.

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
We benchmarked the engine at v0.6.0-rc.21. It repaired and accepted 6 of 6 trials on the
two repositories it was developed against, and 0 of 6 on two unseen repositories, where the
verifier never accepted a test. There were no false accepts. We report this gap rather than
hide it; details are in BENCHMARK.md. We then fixed verifier and static-web problems (rc.22 to
rc.39) and recorded further verified runs (Tabloop #2, Aegisscan #3, CareerPilot #3 and #5, and reruns of file-sharing-app #1 on
rc.39 and QRcrafts #1 on rc.20), all on repositories we own, so they are development results. Each is recorded in EVIDENCE.md with its proof file and run link; in CareerPilot #5 only one of three candidates was evaluated. We make no claim that
Shadow Patch generalizes to unseen repositories.

## Challenges and learning

Early runs exposed problems with inference-response parsing and repository-specific test setup. We also encountered a candidate that changed existing low-speed formatting. Although the proposed fix looked plausible, verification rejected it because it did not preserve the required behavior.

We improved validation feedback, failure-stage reporting, bounded corrections for baseline failures, and pull-request notifications. We also refined the TypeScript test contract so regression tests could run more consistently in the sandbox.

Later challenges were environmental rather than model-related. A newer jsdom crashed on load under the sandbox's Node 20, so we pinned a compatible version and now check it before any model request. Tests created at the site root could not fail for subpath bugs, so the engine now refuses them. A transient Nebius Sandbox API error ended a run, so setup steps now retry and are reported as infrastructure errors instead of repair failures. Projects whose tests ran only a named file, or whose tsconfig used project references, were blocked until we made them testable.

We learned to treat these failures as engineering feedback rather than evidence that the system works everywhere.

## What makes it distinctive

The contribution is the combination of test-before-repair, withholding the new
regression from solvers, isolated candidate evaluations, clean replay, and an
inspectable PR report. We do not claim that competing coding agents lack all
independent verification, or that these mechanisms are individually novel.

## NVIDIA Nemotron and Nebius tools used

- **NVIDIA Nemotron:** every model call. `nvidia/Nemotron-3_5-Lightning` for the first repair;
  `nvidia/nemotron-3-super-120b-a12b` for later repairs and all benchmark trials.
- **Nebius Token Factory:** the inference endpoint for the verifier and for the three solver strategies.
- **Nebius Sandboxes** (`contree-sdk`): repository setup, baseline tests, the pre-fix failure check,
  isolated candidate branches and the clean-image replay.
- **Sandbox images:** built by the Prepare Sandbox Image workflow.
- GitHub Actions orchestrates the run and opens the PR; it is not a Nebius service.
- Nothing here measures speed or cost against other platforms, so we claim no speed-up.

## How to run it

The README has the numbered steps: get Nebius credentials, build a sandbox image, prepare the
repository, add secrets and the workflow file, label an issue, read the verdict. It also has a
command-line alternative.

## Next

Our next priority is improving regression-test generation on unfamiliar repositories, particularly where nested test layouts, repository-specific module aliases, or API type-checking cause problems.

We plan to:

Evaluate more held-out issues and repositories. Add and improve runtime adapters for different languages and test frameworks. Strengthen the evidence linking each verification result to the exact source revision and test artifact. Improve isolation and defenses against hostile repository code. Add clearer execution-cost reporting and explore parallel candidate evaluation (candidates currently run one after another).

Longer term, we aim to evolve the GitHub Actions implementation into an installable GitHub App, making verification-first repairs easier for maintainers to adopt without sacrificing human review.

## Platform feedback

Sandbox snapshots and fresh-image replay made separate verification stages
practical. Setup needed clearer distinctions between model access, project
authorization, Sandbox access, and image toolchains. Bounded inference diagnostics
were essential when responses were empty or hit the output limit. These observations
come from this project's development, not a benchmark against other platforms.

Feedback on the NVIDIA models we used: `nvidia/Nemotron-3_5-Lightning` (small) repeatedly failed the
same structural rule when asked for the exact-match edit format and the verifier markers.
`nvidia/Nemotron-3-Ultra-550b` was token-hungry for this workload. `nvidia/nemotron-3-super-120b-a12b`
was the first to succeed cleanly and was used for every later repair and all benchmark trials. Reasoning
output that ended without a final answer needed explicit handling, and the model sometimes omitted a
required marker, which the engine now retries with a diagnostic. We used Token Factory inference and
Nebius Sandboxes; we did not use AI Cloud compute (Serverless Jobs, Endpoints or DevPods), so we have no
feedback on those.

## Links for the form

- Source repository (public, MIT licence): https://github.com/creatoropener/shadow-patch
- Working demonstration (generated PR and its workflow run): https://github.com/creatoropener/file-sharing-app/pull/2
- Reusable GitHub Action, pin to a tag: `creatoropener/shadow-patch@v0.6.0-rc.39` (publish the tag before submitting)
- Later repair: https://github.com/creatoropener/QRcrafts/pull/3
- Static-web repair: https://github.com/creatoropener/Tabloop/pull/3
- TypeScript repair: https://github.com/creatoropener/Aegisscan-Bug-Auditor/pull/4
- Latest TypeScript repairs (rc.39): https://github.com/creatoropener/CareerPilot/pull/4 and https://github.com/creatoropener/CareerPilot/pull/6
- Recorded run: https://github.com/creatoropener/file-sharing-app/actions/runs/35464615209
- Public video URL: https://youtu.be/p4DGtcIxLXk

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

## Development during the Submission Period

The rules ask for a written explanation when a project predates the Submission Period (opened 2026-08-26).
Shadow Patch's earliest prototypes (v0.2 CLI and v0.3 single-file workflow) are kept under `legacy/`.
The work submitted here is the v0.6 engine and everything around it, built and released as release
candidates documented in CHANGELOG.md and RELEASE.md: node-typescript, static-web and other runtime
adapters; the bounded agent mode and the specification-compiled verifier profile; the reusable GitHub
Action (`action.yml`); the benchmark harness and its results (`bench/`); sandbox retry and outcome
classification; and the run guide, evidence and submission documents. Recorded live runs in this repository
run from 2026-09-20 (file-sharing-app #1) to 2026-10-21 (rc.39).

## Requirements checklist

| Requirement | Where it is met |
| --- | --- |
| Project built with the required tools | NVIDIA Nemotron on Nebius Token Factory; Nebius Sandboxes (README, "How NVIDIA Nemotron and Nebius are used") |
| URL to a working demo or test build | Recorded run and PR in file-sharing-app (links above); `docs/demo/index.html`; the README's "Try it" section |
| Text description of features and functionality | This file, sections "What it does" and "How we built it" |
| Public repository with all source and instructions | https://github.com/creatoropener/shadow-patch; README "Run Shadow Patch step by step" |
| Open-source licence visible in the repository About section | `LICENSE` (MIT) at the repository root; check on GitHub that the About box shows "MIT license" |
| README with setup and run guidance | README, numbered Steps 1 to 8 plus a command-line alternative |
| Highlight NVIDIA Nemotron, Token Factory and other Nebius tools | README and the section above |
