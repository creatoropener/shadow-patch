# Demo: 2 minutes 50 seconds

Target a 2:50 recording, leaving ten seconds below the three-minute limit.
Use the green run and PR below as recorded evidence. Do not claim that a replay
of screens is a new live model run. The included MP4 is a silent walkthrough cut
with captions; this script supplies narration and a plan for a final screen recording.

## Screen order and narration

| Time | Screen | Narration |
| --- | --- | --- |
| 0:00–0:20 | Evidence viewer: Overview | "This is Shadow Engineer. A maintainer labels a bug, and an agent prepares a pull request with verification evidence. The question is not only whether a patch looks plausible. Can we show that it fixes the reported behavior?" |
| 0:20–0:45 | Issue #1 and recorded reproduction | "Here, file sizes and transfer speeds showed fragments of JavaScript instead of readable units. PatchProof generated a regression before any repair was proposed. It ran that test against the original code and confirmed an assertion failure. This is recorded evidence from the completed run." |
| 0:45–1:15 | Evidence viewer: Candidates | "Three repair strategies ran sequentially in separate Nebius sandbox branches. The solver could read the existing tests, but not the new verifier test. Candidate two missed the space in one point zero K B. The hidden regression rejected it. Candidates one and three passed; candidate one was selected." |
| 1:15–1:45 | Evidence viewer: Replay | "Passing once was not the finish. PatchProof applied the selected repair and the same frozen test in a fresh sandbox. Three baseline tests and two regression tests passed. The test hash matched at the recorded checkpoints. This is specific evidence for this repair, not a promise of complete correctness." |
| 1:45–2:15 | Actual GitHub green run | "This is the real GitHub Actions run. It finished successfully and produced the verification artifact. NVIDIA Nemotron supplied the verifier and repair outputs through Nebius Token Factory. Repository commands and tests ran in Nebius Sandboxes. GitHub Actions coordinated the process." |
| 2:15–2:50 | Actual PR #2, then Sources | "The result is this pull request, with the source change, a regression test, and its report. Rerunning the same issue updates this PR instead of creating a duplicate. A human still reviews and merges it. Our demonstrated scope is one TypeScript utility bug. Shadow Engineer makes the evidence available where maintainers already work." |

Read at a relaxed pace and leave pauses for the screen to be understood. Do not
use the older report's candidate-2 winner or its single-regression count when
showing the newer green run, which selected candidate 1 and has two regression tests.

## Capture plan

1. Open the issue, the successful workflow, PR #2, and `docs/demo/index.html` in
   separate tabs. Record at 1920×1080 if available; hide unrelated tabs and bookmarks.
2. Start with the viewer's Overview tab. It is a read-only evidence presentation,
   not a simulated live agent console. Keep its "recorded evidence" label visible.
3. Show the issue's expected values and the report's real pre-fix failure. Use
   candidate and replay tabs to make the decision and recorded assertions legible.
4. Switch to actual GitHub for the green status and PR. Show the source diff and
   generated regression if you can fit them without rushing.
5. Finish with the source links and human-review boundary. Do not merge or label
   issues just to manufacture activity for a recording.

For a fresh live capture, use a separate demonstration repository based on the
documented unfixed revision and current installation. Applying the label calls
Nebius and consumes its normal resources. Capture that run only when intended;
do not present the silent walkthrough as such a run.

## Bug specification for reproduction

Title: File sizes and transfer speeds display JavaScript text instead of readable units

The exports in `lib/utils/format.ts` return literal expression fragments for
values at or above 1024 bytes. Use 1024-based units, one decimal place below 100
units and no decimals from 100 upward. Preserve unrelated behavior.

| Function | Input | Expected |
| --- | ---: | --- |
| formatBytes | 512 | `512 B` |
| formatBytes | 1024 | `1.0 KB` |
| formatBytes | 1536 | `1.5 KB` |
| formatBytes | 102400 | `100 KB` |
| formatBytes | 1048576 | `1.0 MB` |
| formatBytes | 1073741824 | `1.0 GB` |
| formatSpeed | 1536 | `1.5 KB/s` |

No browser, uploads or storage backend are needed for this utility case. The
existing short-duration ETA behavior must remain intact; broader ETA formatting
is a separate issue. The independent verifier must load the actual source.

## Before publication

Remove the historical bytecode files from the actual PR branch, upload this release
to the main repository, add narration or a final screen recording, check its length,
then upload the final video publicly and add its URL to the submission. These
external publication steps are not represented as completed by the local package.
