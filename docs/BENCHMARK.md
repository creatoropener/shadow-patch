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

### Development set and held-out set

- **dev** — issues the engine was already tuned on (QRcrafts #1, file-sharing-app #1, …).
  Useful for regression checks, but a good score here proves little.
- **heldout** — issues written after the engine was frozen and never used to change it.
  This is the only set that says anything about new issues.

Rules that keep it honest: decide the case list and splits before the first run;
never move a case between splits after seeing results; if a held-out case is used
to fix something, it becomes dev and needs a replacement; prefer at least one
repository the engine has never run on.

## Run it

Actions → **Benchmark** → *Run workflow*.

1. **Smoke test first:** engines `v0.6.0-rc.20`, trials `1`, cases `file-sharing-app-1`.
   Confirms secrets, checkout and reporting work before you spend a full run.
2. **Full run:** engines `v0.6.0-rc.20`, trials `3`, split `all`.
3. **Compare versions:** engines `v0.6.0-rc.19,v0.6.0-rc.20`. Both run on identical
   cases, interleaved, in one report. Older tags must accept `--issue-title` and
   `--issue-body` (rc.19 and later do).
   For rc.21 use `v0.6.0-rc.20,v0.6.0-rc.21`. `file-sharing-app-1` is the case that motivated rc.21, so it can show the fix works there but not that rc.21 is better in general; `qrcrafts-1` shows whether anything that worked before still does.

A trial takes about as long as a normal `shadow-fix` run. Two run at a time.

## Read it

The run page shows the summary table. The **report** artifact holds `results.md`,
`results.json` and `labels-needed.md`; each `trial-…` artifact holds that trial's
`proof.json`, engine logs and metadata.

Rates use only non-infra trials and come with a 95% interval. With a handful of
issues the interval is wide and trials of one issue are not independent evidence:
treat the numbers as worked examples, not statistics.

## Judging correctness

**Labels (no code needed).** Open `labels-needed.md` from the report. It lists each
distinct candidate diff once. Judge each against the issue text alone, then add it to
`bench/labels/<case>.json`:

```json
{ "0123456789abcdef": { "correct": true, "note": "escapes all five characters" } }
```

Re-running the report is not required to add labels; the next run picks them up.

**Oracle (automatic, optional).** Give a case an `oracle` in the manifest: a reference
test file you commit under `bench/oracles/`, the path to copy it to, and the command
that runs it. The workflow applies every distinct candidate diff to a clean checkout,
runs the command, and records pass or fail. An oracle that already passes on the
unfixed commit is reported as invalid and ignored. Oracles currently run on the
standard Ubuntu runner with Node 20 and Python 3.12.

```json
"oracle": {
  "setup": "npm ci",
  "test_file": "bench/oracles/qrcrafts-1.test.ts",
  "dest": "tests/bench_oracle.test.ts",
  "command": "npx tsx --test tests/bench_oracle.test.ts"
}
```

When both exist, the oracle wins and the label fills any gap.

## Known limits

- A candidate diff that cannot be applied (for example, a file without a trailing
  newline) is reported as unjudged rather than guessed.
- GitHub starts matrix jobs roughly in order, not strictly, so interleaving is best effort.
- Model output varies between identical runs; that variation is what trials measure.
