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

These two repairs ran on `nvidia/nemotron-3-super-120b-a12b`. Their run and PR links
are marked below where they still need to be added; none has been invented.

### file-sharing-app #3 (v0.6.0-rc.12, `node-typescript`)

- Defect: in `lib/crypto/stream-cipher.ts`, `ivFrom(seed, index)` mixed a random
  per-stream IV seed into every chunk's AES-GCM IV, but the seed was never
  transmitted, so every peer-to-peer chunk failed its auth-tag check.
- Reproduction and generation succeeded on attempt 1, with no retries.
- Selected repair: embeds the 12-byte seed in every frame and updates all three sites
  (encoder transform, encoder flush, decoder read). Trade-off: the seed is repeated
  per frame. The two rejected candidates patched only `transform()`.
- Links: [workflow run URL needed] and [PR URL needed].

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
- Links: [rc.15 workflow run URL needed] and [rc.20 workflow run URL needed].

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
- `visuals/01-verification.png`, `04-candidates.png`, `05-replay.png`,
  `06-sources.png` and `07-reproduction.png`: evidence cards rendered from the
  captured green-run proof. They are explicitly labelled recorded evidence;
  they are not screenshots of GitHub or new executions.

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
