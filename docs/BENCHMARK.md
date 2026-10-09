# Benchmark

A repeatable way to answer one question: **how often does the engine produce a
correct repair that it also accepts?** The live runs so far are single examples;
this runs the same cases several times and, optionally, two engine versions side
by side. Everything happens from the GitHub website (Actions tab).

## What it measures

The engine's own VERIFIED verdict is not treated as the answer, because a generated
test can be wrong in either direction (rc.16, rc.17 and rc.19 rejected fixes that a
bad test could not tell apart). Each trial is also judged by something the engine
never saw: a reference test (`oracle`) or a recorded human judgement (`label`).

| Outcome | Meaning |
| --- | --- |
| Correct and accepted | Engine said VERIFIED and the winning repair is correct. **The headline number.** |
| False accept | Engine said VERIFIED but the winning repair is wrong. |
| False reject | Engine rejected the run although one of its candidates was correct. |
| Rejected, no repair | Rejected and every candidate was wrong (or none was produced). |
| Verifier failed | No repair was ever evaluated because the generated test was never accepted. rc.20 targets this. |
| Verified / rejected, unjudged | Depends on a repair nobody has judged yet. Not counted as a success. |
| Infra (excluded) | Blocked baseline, timeout, inference outage, missing proof. Re-run these. |

## One-time setup

In the **shadow-patch** repository: Settings → Secrets and variables → Actions.
Secrets are per repository, so the ones your target repositories use must exist here too.

| Name | Where | Needed for |
| --- | --- | --- |
| `NEBIUS_API_KEY`, `NEBIUS_PROJECT_ID` | Secret | Always |
| `CONTREE_IMAGE_NODE_TYPESCRIPT` / `CONTREE_IMAGE_NODE_PACKAGE` | Secret | Cases using that adapter |
| `NEBIUS_MODEL` | Variable | Always (same model as your normal runs) |
| `BENCH_TOKEN` | Secret | Only if a target repository is private (read access to contents) |

### If a trial reports "CONTREE_IMAGE is missing"

The engine needs a sandbox image UUID, and GitHub secrets are not shared between
repositories, so shadow-patch needs its own. Use the adapter-specific secret when you
have one (`CONTREE_IMAGE_NODE_PACKAGE` for file-sharing-app, `CONTREE_IMAGE_NODE_TYPESCRIPT`
for QRcrafts), or a single shared `CONTREE_IMAGE`. If you no longer have the UUID, run
**Prepare Sandbox Image** in shadow-patch (`all` covers every adapter) and copy the UUID
it prints into the secret. A blocked trial like this stops in under a second and costs
nothing, and the report lists it as an infrastructure failure, not a result.

## Fill in the cases

`bench/manifest.json` lists the cases. Each needs three things:

1. **`base_commit`** — the full 40-character SHA of a commit where the bug still
   exists. Pin it **before** merging any fix (for QRcrafts #1, before merging PR #3).
   To get it: open the repository, click *Commits*, open the commit, and copy the
   full SHA from the address bar. A short SHA is rejected on purpose.
2. **`issue.title`** — the exact issue title.
3. **`bench/issues/<case>.md`** — the exact issue body. Open the file on GitHub,
   press the pencil, paste the body copied from the issue, and delete the placeholder line.

The text is frozen so every trial and every engine sees identical input. If you edit
the real issue later, the benchmark keeps using the frozen copy.

A case that still contains `TODO` or `<<` placeholders cannot be run; the planning
step lists what is missing.

### Optional: replace the commit's `patchproof.json` (`patchproof_config`)

A pinned commit carries whatever `patchproof.json` the repository had then, and an old
one can name a runtime that cannot do the job. `file-sharing-app` at 4f8b912 pins
`node-package`, which treats only `.js` files as editable source, while the bug is in
`lib/utils/format.ts`. Under that pin the engine verified the bug but rejected every
candidate for touching a "protected or unknown file", whichever engine version ran.

Add a `patchproof_config` object to the case and the harness writes it over the
checkout's `patchproof.json` just before each trial:

```json
"patchproof_config": { "runtime": "node-typescript" }
```

- It accepts `runtime`, `test_directory`, and `scope`. The current file-sharing case protects `formatEta` and limits edits to `lib/utils/format.ts`. Older engines may not understand `scope`; compare using an explicitly versioned compatible protocol.
- The file is **replaced, not merged**; `{}` removes the pin so the engine auto-detects.
- Each trial's `meta.json` records the object and the hash of the file it replaced, and
  the report's "Read before quoting" section names every case that used one.
- It is a deliberate deviation from the repository at that commit. Only compare trials
  that used the same override; results from before one was added measure a different
  configuration. Use it to correct a stale setup, never to make a case easier.
- Cases without the field are untouched.

### Development set and held-out set

- **dev** — issues the engine was already tuned on (QRcrafts #1, file-sharing-app #1, …).
  Useful for regression checks, but a good score here proves little.
- **heldout** — issues written after the engine was frozen and never used to change it.
  This is the only set that says anything about new issues.

Rules that keep it honest: decide the case list and splits before the first run;
preserve historical split membership in the original protocol; if a held-out case is used
to fix something, it becomes dev and needs a replacement; prefer at least one
repository the engine has never run on.

## Run it

Actions → **Benchmark** → *Run workflow*.

1. **After publishing the reviewed rc.25 tag:** engines `v0.6.0-rc.25`, trials `1`, split `dev`, cases `qrcrafts-1,file-sharing-app-1`.
2. Inspect every proof and proposed diff before increasing the budget.
3. The two new held-out placeholders are unselected. Do not select `all` or `heldout` until an independent set, reference repairs and oracles are validated, then freeze a separate protocol. Current rc.25 development cases do not measure generalization.

The supplied rc.24 manifest is preserved byte-for-byte at `bench/protocols/rc24-as-supplied.json`; `development-v2.json` records the new development protocol. rc.20/rc.21 result tables below remain historical evidence. Each new trial stores its manifest, case, issue body, engine commit, run id, exit status and proof digest. Reports refuse to pool different protocol/manifest snapshots.

A trial takes about as long as a normal `shadow-fix` run. Two run at a time.

## Read it

The run page shows the summary table. The **report** artifact holds `results.md`,
`results.json` and `labels-needed.md`; each `trial-…` artifact holds that trial's
`proof.json`, engine logs and metadata.

Reports show operational success over all attempts, plus conditional non-infra rates with a 95% interval. With a handful of
issues the interval is wide and trials of one issue are not independent evidence:
treat the numbers as worked examples, not statistics.

## Judging correctness

**Labels (no code needed).** Open `labels-needed.md` from the report. It lists each
distinct candidate diff once. Judge each against the issue text alone, then add it to
`bench/labels/<case>.json`:

```json
{ "<full 64-character exact UTF-8 patch SHA-256>": { "correct": true, "case_sha256": "<from trial meta.json>", "note": "escapes all five characters and respects scope" } }
```

Re-run the report to apply new labels. Legacy 16-character normalized hashes are retained as historical records but are not used for new exact hashes. Do not pad or truncate hashes to migrate labels; review the original patch bytes and case snapshot, then label the exact new digest.

**Oracle (automatic, optional).** Give a case an `oracle` in the manifest: a reference
test file you commit under `bench/oracles/`, the path to copy it to, and the command
that runs it. The workflow applies every distinct candidate diff to a clean checkout,
runs the command, and records pass or fail. An oracle that already passes on the
unfixed commit is reported as invalid and ignored. The unfixed run must produce recognized assertion evidence, and a separately supplied known-correct reference patch must pass with a positive test count before any candidate can be judged. Runtime/import crashes do not validate an oracle. Oracles currently run on the
standard Ubuntu runner with Node 20 and Python 3.12.

```json
"oracle": {
  "setup": "npm ci",
  "test_file": "bench/oracles/qrcrafts-1.test.ts",
  "dest": "tests/bench_oracle.test.ts",
  "command": "node --import tsx --test --test-reporter=tap tests/bench_oracle.test.ts",
  "failure_evidence": "node-test",
  "reference_patch": "bench/oracles/qrcrafts-1.reference.diff"
}
```

When both exist, the oracle wins and the label fills any gap.

## Known limits

- A candidate diff that cannot be applied (for example, a file without a trailing
  newline) is reported as unjudged rather than guessed.
- GitHub starts matrix jobs roughly in order, not strictly, so interleaving is best effort.
- Model output varies between identical runs; that variation is what trials measure.


## Recorded results (October 2026)

Engine versions: v0.6.0-rc.20 and v0.6.0-rc.21 (historical frozen evaluation, not the current engine).
Model for every trial: `nvidia/nemotron-3-super-120b-a12b`. Three trials per case
and engine. Trials of one case are not independent. Intervals are 95% Wilson.
Labels are hand-judged against the issue text and stored in `bench/labels/`; they are
not an independent oracle.

### Development split

| Engine | Case | Correct and accepted |
| --- | --- | --- |
| rc.20 | file-sharing-app-1 | 3/3 |
| rc.20 | qrcrafts-1 | 3/3 |
| rc.21 | file-sharing-app-1 | 3/3 |
| rc.21 | qrcrafts-1 | 3/3 |

Each engine: **6/6** (61%-100%). No false accepts and no false rejects. Every winning
repair was judged correct. `file-sharing-app-1` runs with `patchproof_config` set to
`node-typescript`, because its pinned commit selects `node-package`, which cannot edit
the TypeScript file. The two engines are not distinguishable on these cases. rc.21
needed more than one verifier generation in 2 of its 6 trials (rc.20: 0 of 6);
the sample is too small to call that a regression.

### Held-out split (rc.21 only)

| Case | Repository / adapter | Correct and accepted | Why it stopped |
| --- | --- | --- | --- |
| heldout-1 | Aegisscan-Bug-Auditor, `node-typescript` | 0/3 | verifier failed: generated TypeScript failed the API type-check (1 trial); test failed without accepted assertion evidence (2 trials) |
| heldout-2 | Tabloop, `static-web` (Experimental) | 0/3 | verifier failed: in the trial inspected, the test reproduced the real defect (form action resolved to `/thank-you.html` instead of `/Tabloop/thank-you.html`) but was rejected because it was wrapped in `describe`, so the engine saw two failed blocks for one failure |

Held-out total: **0/6** (0%-39%). No false accepts; no repair was evaluated, so no
unverified patch was proposed. Only two held-out cases were run, so read these as
examples. A planned third held-out case (Tabloop, mobile "Back home" link) was
replaced by the Aegisscan SSRF case before any run and was never run.

### Reported separately

- **dev-3 (Aegisscan #2, redirect handling): 0/3, verifier failed** (generated
  TypeScript failed the API type-check in all three trials). Its issue text asks the
  engine to re-invoke `validateUrlForSsrf`, a helper that does not exist at the pinned
  base commit, so this is more likely an invalid case than evidence about the engine.
  It is excluded from the headline development number.
- **First held-out pass, Aegisscan:** all six trials were infrastructure failures: the
  repository's own dependencies could not be installed (npm `ERESOLVE`, `esbuild`
  `^0.25.0` against a `vite` peer range). The repository was re-pinned to a commit that
  changes only `package.json` and adds a lockfile, with no source changes, and the
  cases were re-run. The re-run is the one reported above.

The engine was not changed after the held-out cases were written.
