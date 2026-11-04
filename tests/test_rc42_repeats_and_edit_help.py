"""rc.42: every failing case is visible, a repeated patch is answered with a change of approach,
and an edit that matches nothing shows the model the text it failed to copy.

CareerPilot #8 on rc.41: the verifier packed nine inputs into one loop of assertions, so the feedback named
only the first failing input; both candidates then re-sent the same one-line regex patch until the repeat
rule stopped them, and a third died on "Edit ... matched 0 locations" for a long regex line.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import proof
import runtimes
from tests import support_pipeline as pipeline
from tests.test_rc40_repair_rounds import REGRESSION, RIGHT, WRONG, project

HIDDEN = "/workspace/repo/tests/test_patchproof_issue_8.test.ts"


def tap(failing: int, passing: int = 1) -> str:
    blocks = "".join(
        f"not ok {n} - case {n}\n  ---\n  duration_ms: 1.5\n  failureType: 'testCodeFailure'\n"
        f"  error: |-\n    Expected values to be strictly equal:\n    undefined !== {n}\n"
        f"  code: 'ERR_ASSERTION'\n  name: 'AssertionError'\n  operator: 'strictEqual'\n"
        f"  stack: |-\n    TestContext.<anonymous> ({HIDDEN}:{n}:12)\n"
        f"    Test.run (node:internal/test_runner/test:796:25)\n  ...\n"
        for n in range(1, failing + 1))
    oks = "".join(f"ok {n} - fine {n}\n  ---\n  duration_ms: 1\n  ...\n" for n in range(failing + 1, failing + passing + 1))
    total = failing + passing
    return (f"PATCHPROOF_TYPESCRIPT_CHECK=passed\nTAP version 13\n{blocks}{oks}1..{total}\n# tests {total}\n"
            f"# pass {passing}\n# fail {failing}\nPATCHPROOF_TEST_HASH_AFTER=abc\n")


class FailureExcerptTests(unittest.TestCase):
    def test_every_failing_test_is_named_and_the_text_stays_bounded(self):
        text = proof.failure_excerpt(tap(9))
        self.assertTrue(text.startswith("FAILING TESTS (9):"))
        for n in range(1, 10):
            self.assertIn(f"- case {n}", text)
            self.assertIn(f"undefined !== {n}", text)
        self.assertIn("# fail 9", text)
        self.assertLessEqual(len(text), 4500)

    def test_metadata_and_frames_that_only_point_into_the_hidden_test_are_dropped(self):
        text = proof.failure_excerpt(tap(2))
        for noise in ("duration_ms", "failureType", "operator:", "code: 'ERR_ASSERTION'", "test_patchproof_",
                      "node:internal", "PATCHPROOF_"):
            self.assertNotIn(noise, text)
        self.assertNotIn("stack: |-", text)  # an empty stack heading is not left dangling

    def test_a_single_failure_has_no_list_header(self):
        text = proof.failure_excerpt(tap(1))
        self.assertNotIn("FAILING TESTS", text)
        self.assertIn("not ok 1 - case 1", text)
        self.assertIn("# fail 1", text)

    def test_a_stack_frame_in_application_source_is_kept(self):
        log = tap(1).replace(f"TestContext.<anonymous> ({HIDDEN}:1:12)",
                             "ageHours (/workspace/repo/src/age.ts:4:27)")
        self.assertIn("src/age.ts:4:27", proof.failure_excerpt(log))

    def test_no_tap_failure_falls_back_to_the_tail(self):
        self.assertEqual(proof.failure_excerpt("a\nb\nerror TS2322: nope"), "a\nb\nerror TS2322: nope")


class VerifierGuidanceTests(unittest.TestCase):
    def test_node_typescript_guidance_asks_for_one_test_per_input(self):
        adapter = runtimes.detect_runtime(project())
        self.assertEqual(adapter.id, "node-typescript")
        guidance = adapter.verifier_guidance
        self.assertIn("separate test() for each one", guidance)
        self.assertIn("never loop over inputs with assertions inside one test()", guidance)


class RepeatNoticeTests(unittest.TestCase):
    def test_temperature_rises_with_each_repeat_and_is_capped(self):
        self.assertEqual(proof.escalated_temperature(0.15, 0), 0.15)
        self.assertEqual(proof.escalated_temperature(0.15, 1), 0.4)
        self.assertEqual(proof.escalated_temperature(0.35, 2), 0.85)
        self.assertEqual(proof.escalated_temperature(0.55, 2), 0.9)

    def test_notice_names_the_problem_and_gets_firmer(self):
        first, second = proof.repeated_patch_notice(1), proof.repeated_patch_notice(2)
        self.assertIn("IDENTICAL", first)
        self.assertIn("every failing test", first)
        self.assertNotIn("clearly different approach", first)
        self.assertIn("clearly different approach", second)

    def test_three_identical_patches_end_a_candidate(self):
        self.assertEqual(proof.DUPLICATE_STOP, 3)


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class RepeatPipelineTests(unittest.TestCase):
    def run_case(self, reply):
        root = project()
        calls: list[dict] = []

        def candidate(**kwargs):
            calls.append({"feedback": kwargs.get("retry_feedback", ""), "temperature": kwargs.get("temperature")})
            return [{"path": "src/label.ts", "content": reply(len(calls), calls[-1]["feedback"])}], "scripted"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root,
            proof.Issue(1, "label(2) is wrong", "label(2) must return the lower-case word two."),
            REGRESSION % "js", candidate)
        return root, result, record, error, calls

    def test_a_repeat_is_answered_with_more_spread_and_a_firmer_notice_and_can_still_succeed(self):
        def reply(n, feedback):
            return RIGHT if "clearly different approach" in feedback else WRONG

        root, result, record, error, calls = self.run_case(reply)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(result["winner"]["candidate"], 1)
        self.assertEqual((root / "src/label.ts").read_text(), RIGHT)
        # candidate 1: first proposal, the regression round, then two identical answers before the change of approach
        self.assertEqual([call["temperature"] for call in calls[:4]], [0.15, 0.15, 0.4, 0.65])
        self.assertIn("REPAIR ROUND", calls[1]["feedback"])
        self.assertEqual(calls[3]["feedback"].count("YOUR LAST PROPOSAL WAS IDENTICAL"), 1)  # not stacked
        self.assertIn("REPAIR ROUND", calls[3]["feedback"])  # the failure output is still there
        self.assertNotIn("import assert", calls[3]["feedback"])
        # once candidate 1 has passed, the others make one proposal each, at their own base temperatures
        self.assertEqual([call["temperature"] for call in calls[4:]], [0.35, 0.55])
        self.assertEqual(len(calls), 6)

    def test_a_third_identical_patch_stops_and_is_recorded(self):
        root, result, record, error, calls = self.run_case(lambda n, feedback: WRONG)
        self.assertIsNotNone(error)
        first = record["candidates"][0]
        self.assertEqual(first["repair_stopped"], "the same patch was proposed again")
        self.assertEqual(first["repeated_patches"], 3)
        self.assertEqual(len(calls), 12)  # four proposals per candidate, three candidates


class EditHelpTests(unittest.TestCase):
    SOURCE = ("const POSTED_ABSOLUTE = /\\b(?:date\\s+posted|posted)/gi;\n"
              "const RELATIVE = /\\b(\\d{1,3})(\\+)?\\s*(minute|hour|day|week|month)s?\\s+ago\\b/gi;\n"
              "\n/** Finds the posting date. */\nexport const one = 1;\n")

    def test_an_over_escaped_snippet_is_shown_the_real_line(self):
        old = "const RELATIVE = /\\\\b(\\\\d{1,3})(\\\\+)?\\\\s*(minute|hour|day|week|month)s?\\\\s+ago\\\\b/gi;"
        self.assertNotIn(old, self.SOURCE)
        text = proof.edit_mismatch_help(self.SOURCE, old, 0)
        self.assertIn("THE CLOSEST TEXT IN THE FILE", text)
        self.assertIn("2: const RELATIVE = /\\b(\\d{1,3})(\\+)?", text)
        self.assertIn("each backslash is written as two backslashes", text)

    def test_nothing_close_gives_only_the_general_advice(self):
        text = proof.edit_mismatch_help(self.SOURCE, "completely unrelated statement();", 0)
        self.assertNotIn("THE CLOSEST TEXT", text)
        self.assertIn("character for character", text)

    def test_an_ambiguous_snippet_is_told_to_add_context(self):
        self.assertIn("surrounding lines", proof.edit_mismatch_help(self.SOURCE, "const", 2))

    def test_the_excerpt_is_bounded_and_numbered(self):
        big = "\n".join(f"line {n} " + "x" * 300 for n in range(2000)) + "\n"
        text = proof.nearest_source_lines(big, "line 1500 " + "x" * 300)
        self.assertTrue(text.startswith("1499:") or text.startswith("1498:"))
        self.assertLessEqual(len(text), 1800)

    def test_validate_candidate_carries_the_help_into_its_error(self):
        project_root = project()
        adapter = runtimes.detect_runtime(project_root)
        (project_root / "src/label.ts").write_text(self.SOURCE, encoding="utf-8")
        payload = {"summary": "x", "edits": [{"path": "src/label.ts", "old": "const RELATIVE = /\\\\b(\\\\d{1,3})/gi;",
                                              "new": "const RELATIVE = /x/gi;"}]}
        with self.assertRaises(proof.PatchProofError) as caught:
            proof.validate_candidate(payload, {"src/label.ts"}, project_root, adapter)
        message = str(caught.exception)
        self.assertIn("matched 0 locations", message)
        self.assertIn("THE CLOSEST TEXT IN THE FILE", message)
        self.assertIn("RELATIVE", message)

    def test_an_empty_edit_list_points_back_to_the_closest_text(self):
        project_root = project()
        adapter = runtimes.detect_runtime(project_root)
        with self.assertRaises(proof.PatchProofError) as caught:
            proof.validate_candidate({"summary": "x", "edits": []}, {"src/label.ts"}, project_root, adapter)
        self.assertIn("non-empty `edits` list", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
