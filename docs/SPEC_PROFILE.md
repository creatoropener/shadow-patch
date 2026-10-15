# rc.30: readiness, a stricter verifier gate, and specification-compiled tests

rc.30 changes how the engine decides it has a test worth trusting, and how a run is described when it
stops. It is locally validated only; no live Nebius run covers it. The free-form verifier is still the
default, so an unchanged workflow behaves as it did on rc.29 apart from the new records listed under
"Always on".

The constraint behind the design: the test problem has to be solved **without a person approving the
test**. A human still decides whether to merge the pull request. Nothing in rc.30 asks a maintainer to
bless a generated test.

## Always on

| Change | What you see |
| --- | --- |
| **Readiness report.** Before any model request the engine summarizes what it knows: project root, runtime, install, test command, discovered test counts, required checks, specific blockers. | `readiness` in `proof.json` and a *Readiness* section in the report. A baseline that ran **zero tests** is recorded as `compatibility_coverage: absent`: nothing in the project's own suite protects behavior, which weakens what "ordinary CI passed" means. |
| **Outcome bucket.** Every run is assigned one bucket from its own evidence. | `outcome.bucket` (see the table below) and, for non-verified runs without one, a `stop_reason`. |
| **Verifier execution gate.** A test that never ran (syntax error, lint, type-check, unresolved import) no longer uses up one of the three execution attempts, and the engine stops a model that sends the same rejected output three times in a row. | `attempts[].static_rejection` and `counts_toward_limit`; the stop message says how many identical or statically refused outputs it saw. |
| **Precise parse diagnostics.** Syntax failures in a generated test come back to the model with the line, a caret and, for an unterminated string, the usual cause. Plain JavaScript tests get a `node --check` step before they run. | The next verifier prompt contains the offending line. |
| **Readiness-only run.** `python proof.py --readiness-only ...` runs everything up to the first model request and stops. | Verdict `ready`; exit code 0; no inference spent. |

## The specification profile (opt in)

Set `verifier-profile` on the Action, `PATCHPROOF_VERIFIER` in the environment, or `verifier` on the
Benchmark workflow:

| Value | Meaning |
| --- | --- |
| `freeform` (default) | The model writes the regression test, as in every release before rc.30. |
| `spec` | The model writes a **specification**; the engine writes and checks the test. If the issue cannot be expressed, the run stops with `needs_specification`. Never falls back. |
| `auto` | Try `spec`; on `unsupported`, an ungroundable specification, or two rounds that did not reproduce the issue, fall back to `freeform`. The fallback and its reason are recorded. |

`spec` and `auto` apply to the `node-typescript` runtime only. Any other runtime stops with
`blocked_setup` (`spec`) or falls back (`auto`).

### What the model returns

Data, not code, between `<<<PATCHPROOF_SPEC_BEGIN>>>` and `<<<PATCHPROOF_SPEC_END>>>`:

```json
{"supported": true, "module": "src/utils/qrBuilder.ts",
 "examples": [
   {"id": "e1", "export": "buildContent",
    "args": [{"type": "wifi", "security": "WPA", "ssid": "Cafe;Guest", "password": "pass:word"}],
    "returns": "WIFI:T:WPA;S:Cafe\\;Guest;P:pass\\:word;;",
    "evidence": "- Security: WPA\n- SSID: `Cafe;Guest`\n- Password: `pass:word`\n\nExact expected payload ... WIFI:T:WPA;S:Cafe\\;Guest;P:pass\\:word;;"}]}
```

`{"supported": false, "reason": "..."}` is a correct answer when the issue states no expected results for
calls (network, DOM, timing, files, behavior described only in words).

### What the engine checks before anything runs

- The module is an editable, non-test `.ts`/`.mts`/`.cts` file from the repository, and each `export`
  really is exported there (as a callable; classes and enums are refused). If the engine's export scan
  cannot be complete (`export *`, destructured exports, CommonJS), the check is deferred to the compiler.
- `evidence` is found in the issue text, word for word; only whitespace may differ. A miss names the
  closest issue line.
- **Every expected string and number must appear in that example's own evidence**, so a value cannot be
  invented or computed, and a value taken from a different line is refused. Numbers match by value.
- Argument strings must be in the evidence or already be string literals somewhere in the repository
  source (a type tag such as `"wifi"`).
- `throws: true` needs failure language in the evidence (throw, reject, error, invalid, ...).
- Integers beyond 2^53, unknown fields, duplicate ids, more than 12 examples, more than 8 arguments, and
  two different expectations for the same call are refused.
- **Examples are judged one by one (rc.31).** An example the issue does not support is refused and left
  out; the specification stands if at least one example passes every check, and `rejected_examples` in
  the proof says which were refused and why. Problems with the specification as a whole (wrong module,
  unknown top-level field, invalid JSON, nothing grounded) still fail it and go back to the model. Before
  rc.31 one invented example sank the whole specification.
- **Column titles in front of a row (rc.34).** A quotation is one contiguous passage, except that one or two
  short lines (at most 120 characters) found earlier in the issue may come first, such as a table's column
  titles. Every string and number of the example must be in the passage after them; a value that is only in
  the titles is refused. The proof keeps what the model wrote in `evidence` and the grounding passage in
  `issue_span`. Skipped lines inside the passage, more than two leading lines or lines out of order are still
  refused, and the refusal names the issue line that holds the example's values when one does. rc.33 refused
  titles plus a distant row outright and asked the model to quote the row alone; the live model did not.
- **Refusals are fed back (rc.33).** The retry prompt lists the examples the engine refused and why, so the
  model sees what it lost and not only the survivors. The proof keeps the latest specification's refusals
  in `rejected_examples` and counts them per attempt in `refused_examples`.
- **Unclosed blocks (rc.32).** A block that is complete except for its end (the examples are closed, then
  a stray quote or comma, then the END marker) has its closing brackets added: one dangling quote, one
  trailing comma and the open `]`/`}` only, never a value. A value cut off in the middle is not repaired.
  The repaired block is validated like any other, and the attempt records `json_repaired`. JSON punctuation
  alone (quotes, commas, semicolons, colons, braces, brackets) outside the markers (rc.33, rc.34) is dropped
  the same way; letters, digits and fences are not.
- **Backslashes.** The issue shows one backslash; JSON text spells it with two. A value that decodes to
  the wrong number of backslashes no longer appears in the evidence and is refused with a message
  explaining the JSON rule. Escaping was a recurring free-form failure (the useless-escape gate of
  rc.17 and rc.18 exists for it); here the check happens before any test runs.

### What the engine writes

A deterministic test: imports from the module's real path (`.js` specifier first, then `.ts`, then
bare, changing only on a module-resolution error and without another model call), arguments and expected
values serialized by a JSON encoder (ASCII only, so no hand escaping), and one assertion per example:

```ts
assert.deepStrictEqual(await buildContent({...}), "WIFI:T:WPA;...", "PATCHPROOF_EXAMPLE e1 VALUE");
```

The header comment carries the SHA-256 of the specification. The generated test then goes through the
same lint, type-check, protected-run and ordinary-CI discovery as a free-form test.

### What counts as reproducing the issue

The engine reads the TAP result **per example**:

| State | Meaning |
| --- | --- |
| `mismatch` | The example's own assertion failed on a returned value. This is evidence of the bug. |
| `pass` | The unfixed code already returns the expected value. It stays as a guard. |
| `error` | The call threw, the module did not load, or an assertion inside the application failed. Never evidence. |
| `missing` | No result for the example. Never accepted. |

The run is accepted only when at least one example is a `mismatch` and no example is `missing`.
Examples that `error` are dropped and the test is recompiled without them, with no model call and
without using an execution attempt; if nothing is left, the round fails. If the examples that fail
change between two runs of the same specification, it is refused as non-deterministic. Import errors,
syntax errors, missing dependencies and unexpected exceptions never qualify.

The accepted specification and the compiled test are frozen (`frozen_test_sha256`) before the solver
starts; the existing protected-run hash markers still apply.

## Outcome buckets

| Bucket | Where the run stopped | Counts as an evaluated repair |
| --- | --- | --- |
| `verified` | Repair verified and replayed | yes |
| `readiness_blocked` | Setup, baseline, readiness, or ordinary-CI discovery of the frozen test | no |
| `needs_specification` | The issue states no expected results for calls | no |
| `spec_invalid` | A specification could not be made valid, or the model repeated the same refused one | no |
| `verifier_invalid` | Generated tests never ran (static rejections) | no |
| `no_reproduction` | Tests ran and none reproduced the issue | no |
| `repair_invalid` | No candidate reached regression | no |
| `repair_failed` | Candidates reached regression and failed it | yes |
| `replay_failed` | Clean-room replay failed | yes |
| `delivery_blocked` | Delivery check refused the result | no |
| `budget_exhausted` | A run budget ran out | no |
| `infrastructure_error` | Inference or sandbox failed | no |

## Reading benchmark results

The Benchmark report now has three views that must be read together:

1. **Solved, of all non-infrastructure trials.** `needs_specification` and `spec_invalid` stay in the
   denominator: a case the profile cannot express is a case the engine did not solve.
2. **Coverage.** How many `spec`/`auto` trials produced a grounded specification at all.
3. **Repair success among runs that reached an evaluated repair.** Conditional by construction; it says
   nothing about runs that stopped earlier, so it is never quoted alone.

Each trial row shows its bucket and the verifier profile used (`spec→freeform` after a fallback). Mixed
verifier profiles for one engine are refused, like mixed execution profiles. Runs that stopped at
readiness are excluded from the rates as before but now carry a `readiness_blocked` bucket and a
warning, because that can be the repository rather than the harness.

## Limits

- The expected values are as correct as the issue is. The engine proves they are *quoted*, not that the
  issue is right.
- A handful of calls cannot protect all unrelated behavior. Examples that pass on the unfixed code guard
  what they exercise, nothing more.
- Call-and-return functions only. SSRF and network behavior, DOM and static-web cases (heldout-1 and
  heldout-2), timing, and file-system behavior are outside the profile.
- A function whose arguments or results are not JSON (class instances, callbacks, streams, `Date`, `NaN`)
  cannot be expressed.
- The engine cannot tell an expected value from the actual one inside a single quoted sentence. An
  example that quotes the buggy output as "expected" passes on the unfixed code and is rejected as not
  reproducing; an example that quotes a value the fix will not produce fails after the fix and costs the
  repair, not the verdict.
- No live run covers rc.34. Live `spec` runs so far: qrcrafts-1 (verified on rc.31); file-sharing-app-1 stopped on an unclosed JSON block on rc.31 and, after rc.32 closed it, on table quotations the model would not change (rc.33 told it and it did not comply; rc.34 accepts column titles in front of a row). rc.33 verified qrcrafts-1.

## Not built

A mode in which a maintainer approves the specification or test is not part of rc.30. If it is added, it
must be a separately labeled mode, and its results must never be pooled with, or reported as, the
unattended numbers.
