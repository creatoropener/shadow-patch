"""rc.43: a patched file that no longer parses is sent back as a correction request instead of ending the candidate.

CareerPilot #8 on rc.42: the third proposal of candidate 2 wrapped the body of a loop in `if (match[1]) {` and dropped
the closing brace. The scope/interference check reported parser diagnostics and the candidate ended with three of its six
proposals unspent. The scripted cases run the real engine against the local TypeScript toolchain, as the rc.40 cases do.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import proof
from tests import support_pipeline as pipeline
from tests.test_rc40_repair_rounds import REGRESSION, RIGHT, project

BROKEN = "export const label = (n: number): string => (n === 1 ? 'one' : n === 2 ? 'two' : 'many';\n"  # missing ')'


class ExcerptTests(unittest.TestCase):
    def test_the_changed_region_is_numbered_from_the_patched_text_and_bounded(self):
        root = Path(tempfile.mkdtemp())
        before = "\n".join(f"line {n}" for n in range(1, 101)) + "\n"
        (root / "a.ts").write_text(before)
        after = before.replace("line 50\n", "line 50\nextra A\nextra B\n")
        text = proof.changed_region_excerpt(root, [{"path": "a.ts", "content": after}])
        self.assertIn("a.ts as patched, lines 47 to 56", text)
        self.assertIn("51: extra A", text)
        self.assertIn("52: extra B", text)
        self.assertNotIn("line 20", text)
        wide = proof.changed_region_excerpt(root, [{"path": "a.ts", "content": "x\n" * 300}], max_lines=40)
        self.assertLessEqual(len(wide.splitlines()), 41)

    def test_feedback_names_the_problem_and_carries_the_diff_without_credentials(self):
        root = Path(tempfile.mkdtemp())
        (root / "a.ts").write_text("export const a = 1;\n")
        changes = [{"path": "a.ts", "content": "export const a = (1;\n"}]
        text = proof.syntax_repair_feedback(
            "Candidate scope/interference check failed or unavailable: Error: a.ts: candidate has parser diagnostics",
            proof.unified_diff_text(root, changes), root, changes)
        for needle in ("no longer parses", "closing brace", "YOUR PATCHED FILE AROUND THE CHANGE", "1: export const a = (1;",
                       "PREVIOUS PROPOSAL DIFF"):
            self.assertIn(needle, text)
        self.assertLessEqual(len(text), 12_000)


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class SyntaxFeedbackPipelineTests(unittest.TestCase):
    def run_case(self, reply, env=None):
        root = project()
        calls: list[str] = []

        def candidate(**kwargs):
            feedback = kwargs.get("retry_feedback", "")
            calls.append(feedback)
            return [{"path": "src/label.ts", "content": reply(len(calls), feedback)}], "scripted proposal"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root,
            proof.Issue(1, "label(2) is wrong", "label(2) must return the lower-case word two."),
            REGRESSION % "js", candidate, env_extra=env)
        return root, result, record, error, calls

    def test_a_syntax_error_is_corrected_from_the_feedback_and_the_candidate_wins(self):
        root, result, record, error, calls = self.run_case(
            lambda n, feedback: RIGHT if "no longer parses" in feedback else BROKEN)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        # every candidate repairs its own syntax error the same way, so which one wins is a matter of speed
        self.assertIn(result["winner"]["candidate"], (1, 2, 3))
        self.assertEqual((root / "src/label.ts").read_text(), RIGHT)
        self.assertIn("YOUR PATCHED FILE AROUND THE CHANGE", calls[1])
        self.assertNotIn("import assert", calls[1])  # the frozen test's source never goes back
        first = result["candidates"][0]
        self.assertEqual(len(first["syntax_errors"]), 1)
        self.assertIn("candidate has parser diagnostics", first["syntax_errors"][0]["message"])

    def test_zero_keeps_the_earlier_behaviour_of_ending_the_candidate(self):
        root, result, record, error, calls = self.run_case(
            lambda n, feedback: RIGHT if "no longer parses" in feedback else BROKEN, env={"PATCHPROOF_REPAIR_ROUNDS": "0"})
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 3)  # one proposal per candidate
        self.assertTrue(all("syntax_errors" not in item for item in record["candidates"]))
        self.assertIn("parser diagnostics", record["candidates"][0]["error"])

    def test_a_scope_violation_is_still_fatal(self):
        def reply(n, feedback):
            return RIGHT

        root = project()
        calls: list[str] = []

        def candidate(**kwargs):
            calls.append(kwargs.get("retry_feedback", ""))
            return [{"path": "tests/existing.test.ts", "content": "// edited\n"}], "tries to edit a test"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root,
            proof.Issue(1, "label(2) is wrong", "label(2) must return the lower-case word two."),
            REGRESSION % "js", candidate)
        self.assertIsNotNone(error)
        self.assertTrue(all("no longer parses" not in text for text in calls))


if __name__ == "__main__":
    unittest.main()
