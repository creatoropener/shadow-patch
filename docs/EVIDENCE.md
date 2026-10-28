# Recorded evidence and provenance

## Primary demonstration: green workflow

- Target: creatoropener/file-sharing-app, issue #1, file-size and speed formatting.
- [Workflow 35464615209](https://github.com/creatoropener/file-sharing-app/actions/runs/35464615209).
- Run source commit: `4f8b91276c8339e84097b33ea6ec85dbf13c4d67`.
- [PR #2](https://github.com/creatoropener/file-sharing-app/pull/2), captured head:
  `355c5464c9dd3d467dd25c884c52256b43693d1f`.
- [Captured PR proof](evidence/green-run-v0.5.5.json) and
  [GitHub run metadata](evidence/github-run-35464615209.json).
- Retrieved on 2026-09-20. The report was downloaded from the PR branch; the PR
  can change after this capture. The preserved bytes and checksums are authoritative
  for this package, not future live PR content.

| Gate | Recorded result |
| --- | --- |
| Initial baseline | 3 passed |
| Independent reproduction | Accepted assertion failure, attempt 1 |
| Candidate 1 | Passed; selected winner |
| Candidate 2 | Rejected: `1.0KB` did not equal `1.0 KB` |
| Candidate 3 | Passed |
| Clean replay | 3 baseline tests + 2 regression tests passed |
| Frozen regression | Hash unchanged at recorded checkpoints |
| Workflow | Success, 1 minute 46 seconds for this recorded run |

The two passing strategies can produce equivalent patches. Do not present them
as statistically independent solutions. Counts refer to registered tests, not
the number of assertions or whole-application coverage.

## Later repairs on the v0.6 engine

These repairs ran on `nvidia/nemotron-3-super-120b-a12b`. Links not yet supplied are
marked below as needed or to be added; none has been invented.

### file-sharing-app #3 (v0.6.0-rc.12, `node-typescript`)

- Defect: in `lib/crypto/stream-cipher.ts`, `ivFrom(seed, index)` mixed a random
  per-stream IV seed into every chunk's AES-GCM IV, but the seed was never
  transmitted, so every peer-to-peer chunk failed its auth-tag check.
- Reproduction and generation succeeded on attempt 1, with no retries.
- Selected repair: embeds the 12-byte seed in every frame and updates all three sites
  (encoder transform, encoder flush, decoder read). Trade-off: the seed is repeated
  per frame. The two rejected candidates patched only `transform()`.
- Links: [workflow run 36181596969](https://github.com/creatoropener/file-sharing-app/actions/runs/36181596969)
  (Shadow Fix workflow, triggered by labelling issue #3, success, 2 min 4 s, 2026-09-25, run source
  commit `bf93981`, artifact `patchproof-issue-3`) and
  [PR #4](https://github.com/creatoropener/file-sharing-app/pull/4) (branch `shadow-fix/issue-3`, merged
  on 2026-09-26; head commit `357ef0b664d3cba60abc99775bd553f6acd4d786`). The PR was opened under the
  project's earlier name, so its title says "Shadow Engineer".

### QRcrafts #1 (`node-typescript`)

- Defect: `buildContent` in `src/utils/qrBuilder.ts` did not escape the WiFi reserved
  characters `;` `,` `:` `\` and `"`.
- rc.15 run: candidates 1 and 3 passed (one file, four lines each) and candidate 3
  was selected on elapsed time (11.256 s against 11.606 s). Candidate 2 failed because
  its shared escape pattern omitted the double quote. Clean replay passed with an
  unchanged regression hash.
- Later Action runs on rc.16, rc.17 and rc.19 were rejected; the first verified run
  through the Action was rc.20, which updated [PR #3](https://github.com/creatoropener/QRcrafts/pull/3)
  in place. These runs are the reason the benchmark exists.
- Links: [PR #3](https://github.com/creatoropener/QRcrafts/pull/3), PR head commit
  `38c102e461db073bee884e45507a147fc14d87a2`. rc.20 run:
  [workflow run 36553142474](https://github.com/creatoropener/QRcrafts/actions/runs/36553142474)
  (`shadow-fix-caller.yml`, triggered by labelling issue #1, success, 1 min 59 s, 2026-09-29, run source
  commit `8d21aa8faca48df31dd9010fb210f6697fff24b8`, artifact `patchproof-issue-1`). The rc.15 workflow
  run URL is not yet linked.
- Proof (rc.20 run): [verified-qrcrafts-1-rc20.json](evidence/verified-qrcrafts-1-rc20.json) (model
  `nvidia/nemotron-3-super-120b-a12b`, verdict `verified`; this file uses the older proof layout, so it has
  no run id or PR file list). Existing suite 1 test passed. The regression test has three cases: two failed
  on the unfixed code and one ordinary-credentials case passed, accepted on attempt 1. All three candidates
  passed (5, 4 and 5 changed lines); candidate 2 won on fewest lines. This differs from the rc.15 run, where
  candidate 3 won. Clean replay passed 1 baseline test plus 3 regression tests. The engine version is taken
  from the proof file; the run page does not state it.

### file-sharing-app #1 rerun on rc.39 (`node-typescript`, `freeform`, via the Action)

- Target: creatoropener/file-sharing-app, issue #1, the same defect as the primary demonstration above.
  The run updated [PR #2](https://github.com/creatoropener/file-sharing-app/pull/2) in place, so PR #2 no
  longer shows the v0.5.5 captured head `355c5464…`; its head commit is now
  `500e6fbb9e2c23bf407b1aad7bd4c1f5f4aa43bd`.
- [Workflow run 39594141041](https://github.com/creatoropener/file-sharing-app/actions/runs/39594141041):
  Shadow Fix workflow, triggered by labelling issue #1, success, 2 min 35 s, 2026-10-21, run source commit
  `551072c0b39a241e4887499b1ea8bf86393875f9`, artifact `patchproof-issue-1`.
- Result: verdict `verified`; candidate 1 won with a two-line change in `lib/utils/format.ts`; the PR
  carries that file plus `tests/test_patchproof_issue_1.test.ts`; clean replay passed.
- Caveats: `formatEta` is untouched by design (protected scope; the issue covers sizes and speeds only).
  The spec verifier profile did not work on this case, so the run used `freeform`. Project-owned
  repository: a development case.
- Proof: [verified-file-sharing-app-1-rc39.json](evidence/verified-file-sharing-app-1-rc39.json) (run id
  `417af8e847a647139ef4fd0abe614e5e`, model `nvidia/nemotron-3-super-120b-a12b`, verdict `verified`).
  Existing suite 3 tests passed; the regression test (7 assertions) was accepted on attempt 1, failing on the
  unfixed code because raw `v.toFixed(...)` text appeared where `1.0 KB` was expected. All three candidates
  passed (each one file, two lines; 18.3 s, 18.6 s, 18.8 s) and candidate 1 won. Clean replay passed 3
  baseline tests plus 1 regression test (4 tests run). Scope: allowed path `lib/utils/format.ts`, protected
  symbol `formatEta` unchanged. Delivered files: `lib/utils/format.ts` and
  `tests/test_patchproof_issue_1.test.ts`. The three candidates are near-identical, so they are not
  independent solutions. The earlier v0.5.5 run above and this rc.39 run are separate results; do not mix
  their counts.

### Tabloop #2 (v0.6.0-rc.36, `static-web`, `freeform`)

- Target: creatoropener/Tabloop, issue [#2](https://github.com/creatoropener/Tabloop/issues/2),
  "Root-Absolute Form Action Breaks Subpath / Staging Deploys". [PR #3](https://github.com/creatoropener/Tabloop/pull/3).
- Commits: `34a6cfd30d9c430e5bbb66e1b7e9260919fa8f11` (run source commit) and
  `2f007b98d3e86d1c1de45124c0e6befcb72a6783` (PR head commit).
- [Workflow run 39258986618](https://github.com/creatoropener/Tabloop/actions/runs/39258986618): Shadow Fix workflow, triggered by labelling issue #2, success, 1 min 48 s, 2026-10-19. The run page shows the run source commit above.
- Proof: [verified-tabloop-2-rc36.json](evidence/verified-tabloop-2-rc36.json) (run id
  `8add048e88da48b583038dfec116692c`, model `nvidia/nemotron-3-super-120b-a12b`, verdict `verified`).
- Gates recorded: existing suite 1 test passed; jsdom 24.1.3 loaded on Node v20.19.2 before any
  model request; the planted discovery probe was found by `npm test`. The verifier needed three
  executions: the first two tests passed on the unfixed page and were refused, the third produced an
  accepted assertion failure (`'/thank-you.html'` against `'thank-you.html'`). All three candidates
  passed; candidate 1 won (one file, two lines, 9.265 s). Clean replay passed 1 baseline test plus
  1 regression test with an unchanged regression hash.
- Repair: `index.html` form action `/thank-you.html` changed to `thank-you.html`.
- Caveats: the frozen test asserts `getAttribute('action') === 'thank-you.html'`, which is narrower than
  the issue (`./thank-you.html` would fail it). The three candidates made the same change, so they are not
  independent solutions. This is the first live `static-web` success; earlier attempts on rc.34, rc.35 and
  an earlier rc.36 run did not verify. The repository is owned by the project, so this is a development
  case, not generalization evidence.

### Aegisscan #3 (v0.6.0-rc.37, `node-typescript`, `freeform`)

- Target: creatoropener/Aegisscan-Bug-Auditor, issue
  [#3](https://github.com/creatoropener/Aegisscan-Bug-Auditor/issues/3), "SAST dependency scan misses
  vulnerable Axios versions with normal semver". [PR #4](https://github.com/creatoropener/Aegisscan-Bug-Auditor/pull/4).
- Commits: `044a3ecbd7b5f4586d7b3193cd403d9ebc657567` (run source commit) and
  `50805a0b22c1e0e2dc66818b70b16853c21ab83d` (PR head commit).
- [Workflow run 39312812930](https://github.com/creatoropener/Aegisscan-Bug-Auditor/actions/runs/39312812930): Shadow Fix workflow, triggered by labelling issue #3, success, 2 min 19 s, 2026-10-19, artifact `patchproof-issue-3`. The run page shows the run source commit above.
- Proof: [verified-aegisscan-3-rc37.json](evidence/verified-aegisscan-3-rc37.json) (run id
  `5be20ecc786845a9a52cb6309b628b32`, model `nvidia/nemotron-3-super-120b-a12b`, verdict `verified`).
- Gates recorded: existing suite 5 tests passed; reproduction accepted on attempt 1 (type check and
  lint passed, then an assertion failure `Expected Axios vulnerability finding`). All three candidates
  passed, each one file and two lines; candidate 2 won on elapsed time (18.967 s against 19.237 s and
  19.661 s). Clean replay passed with an unchanged regression hash. Delivered files: `src/server/sastEngine.ts`
  and `tests/test_patchproof_issue_3.test.ts`.
- Repair: the Axios version regex in `src/server/sastEngine.ts` now matches versions with a patch
  component such as `0.19.2`.
- Caveats: the regression also asserts severity `HIGH` and `cvssScore` 7.4, values the issue does not
  state; they come from the existing rule metadata and are unverified against the issue. The three
  candidates are near-identical. Project-owned repository: a development case.

### CareerPilot #3 (v0.6.0-rc.39, `node-typescript`, `freeform`)

- Target: creatoropener/CareerPilot, issue [#3](https://github.com/creatoropener/CareerPilot/issues/3),
  "scoreJob gives no location credit when the preferred location is written as 'City, Country'
  (e.g. 'Mumbai, India')". [PR #4](https://github.com/creatoropener/CareerPilot/pull/4).
- Commits: `027af55cc7742ca5bf99ec595b80a8bbeae8e3c2` (PR head commit, as supplied) and `cbd41d7ca6f68940f6b0df871ecea678d140994e` (run source commit shown on the run page).
- [Workflow run 40124574385](https://github.com/creatoropener/CareerPilot/actions/runs/40124574385): Shadow Patch
  workflow, triggered by labelling issue #3, success, 2 min 13 s, 2026-10-24, artifact `patchproof-issue-3`.
- Proof: [verified-careerpilot-3-rc39.json](evidence/verified-careerpilot-3-rc39.json) (run id
  `b5c0b105dcd343a9a5ea9d35da8d4ac7`, model `nvidia/nemotron-3-super-120b-a12b`, verdict `verified`).
- Gates recorded: readiness ready; existing suite 2 tests passed; the regression test (four cases) was
  accepted on attempt 1 as an assertion failure. All three candidates were evaluated and passed, each one
  file (`src/lib/matcher.ts`) and six changed lines (21.2 s, 17.9 s, 18.5 s); candidate 2 won on elapsed
  time. Clean replay passed 2 baseline tests plus 4 regression tests. Delivered files: `src/lib/matcher.ts`
  and `tests/test_patchproof_issue_3.test.ts`.
- Repair: location scoring now also matches the city part when the preferred location contains a comma.
- Caveats: the repository needed setup before the first successful run (a `tsconfig.json` fix, a
  `patchproof.json` scope and a test glob that did not match the baseline tests), so earlier attempts did not
  reach inference. The three candidates are near-identical. Project-owned repository: a development case.

### CareerPilot #5 (v0.6.0-rc.39, `node-typescript`, `freeform`)

- Target: creatoropener/CareerPilot, issue [#5](https://github.com/creatoropener/CareerPilot/issues/5),
  `findPostedDate` trusted the provider date over contradicting "Posted N days ago" text.
  [PR #6](https://github.com/creatoropener/CareerPilot/pull/6).
- Commits: `080781f9007faf4345474cd3c6837bbe112b9174` (PR head commit, as supplied) and `fd287306991bf0751c1dc2029d65660fba930bcf` (run source commit shown on the run page).
- [Workflow run 40221260992](https://github.com/creatoropener/CareerPilot/actions/runs/40221260992): Shadow Patch
  workflow, triggered by labelling issue #5, success, 2 min 6 s, 2026-10-25, artifact `patchproof-issue-5`.
- Proof: [verified-careerpilot-5-rc39.json](evidence/verified-careerpilot-5-rc39.json) (run id
  `419b3eea87624093bf98f640df3ba95f`, model `nvidia/nemotron-3-super-120b-a12b`, verdict `verified`).
- Gates recorded: existing suite 4 tests passed; the regression test was accepted on attempt 1 (unfixed
  code returned `'api'` where `'text'` was expected). Three candidates were attempted but **only one was
  evaluated**: candidates 1 and 2 failed at generation (their edits matched no location in the file, twice
  each) and candidate 3 passed (`lib/recency.ts`, 21 changed lines, 21.7 s) and won. Clean replay passed 4
  baseline tests plus 1 regression test. Delivered files: `lib/recency.ts` and
  `tests/test_patchproof_issue_5.test.ts`.
- Repair: collect all date evidence and return the oldest valid date.
- Caveats: this is a single-candidate result, so it shows the verification gates, not agreement between
  strategies. The regression test includes a "30+ days" case whose semantics come from the verifier model's
  reading of the issue; review it before merging. Project-owned repository: a development case.

## Benchmark results

Development 6/6 on rc.20 and on rc.21; held-out 0/6 on rc.21, with no false accepts.
Tables, caveats and the infrastructure re-run are in [BENCHMARK.md](BENCHMARK.md).

## Earlier runs, kept separate

| Local evidence file | Origin | What it shows |
| --- | --- | --- |
| `rejected-v0.5.4.json` | User-uploaded proof(1).json | Baseline passed; verifier reproduced; candidate 1 broke `512 B/s`; candidates 2/3 failed proposal validation; overall rejection |
| `verified-v0.5.5.json` | User-uploaded proof(2).json | Three candidates passed; candidate 2 selected; replay passed 3 baseline + 1 regression; later notification failed in the workflow |
| `green-run-v0.5.5.json` | Captured PR branch report after rerun | Two of three candidates passed; candidate 1 selected; 3 baseline + 2 regression replay; green workflow linked above |

The first successful proof and the later green workflow are not interchangeable.
This distinction explains why the earlier chat report named candidate 2, while
the current PR names candidate 1. Do not mix their counts in a pitch.

## Visual evidence

- `screenshots/02-github-run.jpg`: unaltered browser capture of the actual successful run.
- `screenshots/03-github-pr.jpg`: unaltered browser capture of the actual PR report.

Open [the evidence viewer](demo/index.html) locally. It makes no network requests
unless you follow a source link, and cannot start a run, modify a PR, or merge it.
Its HTML was statically reviewed; the cloud browser does not permit local-file
navigation, so no browser-rendering validation of this optional viewer is claimed.

## Presentation and cleanup

The historical PR includes two generated `.pyc` files. The consolidated workflow
prevents new runner bytecode and the new ignore rules exclude it. The already
committed binaries still need removal on the PR branch before merge. They have
not been silently removed from the captured file list or screenshots.

The proof includes sandbox UUIDs and ordinary diagnostic output, not API keys.
Check the final recording for credentials and unrelated private tabs before
publishing. No synthetic result has been inserted into a historical report.
