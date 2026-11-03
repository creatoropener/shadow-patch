"""rc.41: one proposal budget for every kind of failure, and feedback that shows the failing line.

CareerPilot #8 on rc.40: the verifier was fine, but all three candidates died at the existing-test
stage (one correction allowed) before the regression rounds could start. In every attempt the model
changed a regular expression and never the lines that read its groups; the log tail it was shown
did not even contain the failing test.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import proof
from tests import support_pipeline as pipeline

TAP = """TAP version 13
# Subtest: first old test
not ok 1 - first old test
  ---
  duration_ms: 0.4
  location: '/workspace/repo/tests/old.test.ts:3:1'
  error: "Cannot read properties of undefined (reading 'toLowerCase')"
  name: 'TypeError'
  stack: |-
    ageHours (/workspace/repo/src/age.ts:4:27)
    TestContext.<anonymous> (/workspace/repo/tests/old.test.ts:5:10)
    Test.run (node:internal/test_runner/test:796:25)
    node:internal/process/task_queues:140:7
  ...
""" + "".join(f"ok {n} - passing {n}\n  ---\n  duration_ms: 1\n  ...\n" for n in range(2, 100)) + """1..59
# tests 59
# pass 58
# fail 1
PATCHPROOF_TEST_HASH_AFTER=abc
"""

CHANGES = [{"path": "src/age.ts", "content": "line1\nline2\nline3\nconst unit = m[2].toLowerCase();\nline5\nline6\n"}]


class ExcerptTests(unittest.TestCase):
    def test_failure_excerpt_keeps_the_failure_even_when_it_is_far_from_the_tail(self):
        self.assertGreater(len(TAP), 4000)
        self.assertNotIn("not ok 1", TAP[-4000:])  # what rc.40 would have sent
        text = proof.failure_excerpt(TAP)
        self.assertIn("not ok 1 - first old test", text)
        self.assertIn("reading 'toLowerCase'", text)
        self.assertIn("src/age.ts:4:27", text)
        self.assertIn("# fail 1", text)
        self.assertNotIn("passing 30", text)
        self.assertNotIn("node:internal", text)
        self.assertNotIn("PATCHPROOF_", text)

    def test_failure_excerpt_falls_back_to_the_tail_without_tap_failures(self):
        self.assertEqual(proof.failure_excerpt("a\nb\nerror TS2322: nope"), "a\nb\nerror TS2322: nope")

    def test_source_excerpt_shows_the_patched_line_the_stack_names(self):
        text = proof.source_excerpts(TAP, CHANGES)
        self.assertIn("src/age.ts around line 4", text)
        self.assertIn(">> 4: const unit = m[2].toLowerCase();", text)
        self.assertIn("   3: line3", text)

    def test_source_excerpt_ignores_tests_unknown_files_and_bad_lines(self):
        self.assertEqual(proof.source_excerpts("at /workspace/repo/tests/old.test.ts:5:10", CHANGES), "")
        self.assertEqual(proof.source_excerpts("at /workspace/repo/src/other.ts:2:1", CHANGES), "")
        self.assertEqual(proof.source_excerpts("at /workspace/repo/src/age.ts:99:1", CHANGES), "")
        self.assertEqual(proof.source_excerpts(TAP, None), "")

    def test_feedback_carries_hint_failure_excerpt_and_diff_but_not_markers(self):
        text = proof.baseline_repair_feedback(TAP, "--- a\n+++ b\n", CHANGES)
        for needle in ("BASELINE FAILURES", "not ok 1 - first old test", "SOURCE AROUND THE FAILING LINE",
                       "match[n]", "PREVIOUS PROPOSAL DIFF"):
            self.assertIn(needle, text)
        self.assertNotIn("PATCHPROOF_", text)
        self.assertLessEqual(len(text), 12_000)


AGE = """const RE = /(\\d+)(h|d)\\b/gi;
export function ageHours(text: string): number | null {
  let best: number | null = null;
  for (const m of text.matchAll(RE)) {
    const unit = m[2].toLowerCase();
    const hours = Number(m[1]) * (unit === 'd' ? 24 : 1);
    best = best === null || hours > best ? hours : best;
  }
  return best;
}
"""
SHIFTED = AGE.replace("/(\\d+)(h|d)\\b/gi", "/(^|\\s)(\\d+)(h|d|w)\\b/gi")  # adds a group: m[1] is now the prefix
ALTERNATION = AGE.replace("/(\\d+)(h|d)\\b/gi", "/(\\d+)(h|d)\\b|(\\d+)(w)\\b/gi")  # '2w' leaves m[2] undefined
CORRECT = (AGE.replace("/(\\d+)(h|d)\\b/gi", "/(\\d+)(h|d|w)\\b/gi")
           .replace("(unit === 'd' ? 24 : 1)", "(unit === 'w' ? 168 : unit === 'd' ? 24 : 1)"))
REGRESSION = """import test from 'node:test';
import assert from 'node:assert/strict';
import { ageHours } from '../src/age.js';

test('weeks are understood', async () => {
  assert.equal(ageHours('Listed 2w'), 336);
});
"""


def project() -> Path:
    root = Path(tempfile.mkdtemp(prefix="rc41-"))
    put = lambda name, text: pipeline.write(root, name, text)
    put("package.json", json.dumps({"type": "module", "scripts": {
        "test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
    put("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"ESNext","moduleResolution":"Bundler",'
                         '"strict":true,"types":[],"noEmit":true},"include":["src/**/*.ts"]}')
    put("src/age.ts", AGE)
    put("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; "
        "import {ageHours} from '../src/age.js'; "
        "test('days', () => assert.equal(ageHours('Posted 3d'), 72)); "
        "test('none', () => assert.equal(ageHours('nothing here'), null));\n")
    put("patchproof.json", json.dumps({"runtime": "node-typescript", "scope": {"allowed_paths": ["src/age.ts"]}}))
    (root / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
    return root


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class SharedBudgetPipelineTests(unittest.TestCase):
    def run_case(self, reply, env=None):
        root = project()
        calls: list[str] = []

        def candidate(**kwargs):
            feedback = kwargs.get("retry_feedback", "")
            calls.append(feedback)
            return [{"path": "src/age.ts", "content": reply(len(calls), feedback)}], "scripted proposal"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root,
            proof.Issue(1, "weeks are not understood", "ageHours('Listed 2w') must return 336."),
            REGRESSION, candidate, env_extra=env)
        return root, result, record, error, calls

    def test_a_candidate_is_repaired_across_baseline_and_regression_failures_from_the_failing_line(self):
        def reply(n, feedback):
            if "REPAIR ROUND" in feedback:
                return CORRECT
            if "BASELINE FAILURES" in feedback:
                return ALTERNATION
            return SHIFTED

        root, result, record, error, calls = self.run_case(reply)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        first = result["candidates"][0]
        self.assertTrue(first["passed"])
        self.assertEqual(result["winner"]["candidate"], 1)
        self.assertEqual((root / "src/age.ts").read_text(), CORRECT)
        # proposal 1 broke an existing test (baseline), proposal 2 passed it and failed the regression
        self.assertEqual(len(first["repair_rounds"]), 1)
        self.assertEqual(first["repair_rounds"][0]["stage"], "regression")
        baseline_feedback = calls[1]
        self.assertIn("BASELINE FAILURES", baseline_feedback)
        self.assertIn("not ok", baseline_feedback)
        regression_feedback = calls[2]
        self.assertIn("REPAIR ROUND", regression_feedback)
        self.assertIn("SOURCE AROUND THE FAILING LINE", regression_feedback)
        self.assertIn(">> 5:     const unit = m[2].toLowerCase();", regression_feedback)
        for text in (baseline_feedback, regression_feedback):
            self.assertNotIn("import assert", text)  # the frozen test's source never goes back
            self.assertNotIn("PATCHPROOF_", text)

    def test_zero_keeps_the_rc39_single_correction(self):
        def reply(n, feedback):
            return ALTERNATION if "BASELINE FAILURES" in feedback else SHIFTED

        root, result, record, error, calls = self.run_case(reply, env={"PATCHPROOF_REPAIR_ROUNDS": "0"})
        self.assertIsNotNone(error)
        # two proposals per candidate (one correction), then the regression is evaluated once and that is all
        self.assertEqual(len(calls), 6)
        self.assertTrue(all("repair_rounds" not in item for item in record["candidates"]))


if __name__ == "__main__":
    unittest.main()
