"""rc.44: a proposal that passes more of the verifier's tests is kept as the base of the next one, a repeated patch no
longer spends a proposal, type errors show the numbered source line, and the proof lists every proposal.

CareerPilot #8 on rc.43: each proposal re-derived the whole change from the original source, so partial progress (the
"Just now" case) was thrown away; repeats and broken proposals used the shared budget so only one to three
proposals per candidate reached the verifier's tests; and the run could not be reconstructed afterwards. The scripted
cases run the real engine against the local TypeScript toolchain, as the rc.40 to rc.43 cases do.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proof
import runtimes
from tests import support_pipeline as pipeline
from tests.test_rc42_repeats_and_edit_help import tap
from tests.test_rc40_repair_rounds import project

THREE_TESTS = """import test from 'node:test';
import assert from 'node:assert/strict';
import { label } from '../src/label.%s';

test('two is spelled out in lower case', async () => {
  assert.equal(label(2), 'two');
});

test('three is spelled out in lower case', async () => {
  assert.equal(label(3), 'three');
});

test('four stays many', async () => {
  assert.equal(label(4), 'many');
});
"""

ONLY_TWO = "export const label = (n: number): string => (n === 1 ? 'one' : n === 2 ? 'two' : 'many');\n"
ONLY_THREE = "export const label = (n: number): string => (n === 1 ? 'one' : n === 3 ? 'three' : 'many');\n"
TWO_SPOILED = ("export const label = (n: number): string => "
               "(n === 1 ? 'one' : n === 2 ? 'Two' : n === 3 ? 'three' : 'many');\n")
RIGHT3 = ("export const label = (n: number): string => "
          "(n === 1 ? 'one' : n === 2 ? 'two' : n === 3 ? 'three' : 'many');\n")
BREAKS_EXISTING = ("export const label = (n: number): string => "
                   "(n === 1 ? 'ONE' : n === 2 ? 'two' : n === 3 ? 'three' : 'many');\n")
TYPE_ERROR = "export const label = (n: number): string => (n === 1 ? 'one' : 2);\n"


class HelperTests(unittest.TestCase):
    def test_tap_summary_and_failing_names(self):
        output = tap(3, 4)
        self.assertEqual(proof.tap_counts(output), (4, 7))
        self.assertEqual(proof.failing_test_names(output), ["case 1", "case 2", "case 3"])
        self.assertEqual(proof.tap_counts("no summary here"), (None, None))
        self.assertEqual(proof.failing_test_names("ok 1 - fine\n"), [])

    def test_the_switch_defaults_on_and_turns_off(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("PATCHPROOF_CUMULATIVE_REPAIR", None)
            self.assertTrue(proof.cumulative_repair_from_env())
        for value in ("0", "false", "No", "OFF"):
            with patch.dict("os.environ", {"PATCHPROOF_CUMULATIVE_REPAIR": value}):
                self.assertFalse(proof.cumulative_repair_from_env())
        with patch.dict("os.environ", {"PATCHPROOF_CUMULATIVE_REPAIR": "1"}):
            self.assertTrue(proof.cumulative_repair_from_env())

    def test_wording_switches_from_the_original_to_the_current_state(self):
        text = proof.cumulative_wording("against the ORIGINAL source and again against the original source")
        self.assertNotIn("ORIGINAL", text)
        self.assertNotIn("original source", text)
        self.assertEqual(text.count("CURRENT STATE of the patched files"), 2)

    def test_incremental_diff_shows_only_what_the_proposal_added(self):
        root = Path(tempfile.mkdtemp())
        (root / "a.ts").write_text("one\ntwo\nthree\n")
        (root / "b.ts").write_text("keep\n")
        base = [{"path": "a.ts", "content": "ONE\ntwo\nthree\n"}, {"path": "b.ts", "content": "kept\n"}]
        changes = [{"path": "a.ts", "content": "ONE\ntwo\nTHREE\n"}, {"path": "b.ts", "content": "kept\n"}]
        text = proof.incremental_diff_text(root, base, changes)
        self.assertIn("-three", text)
        self.assertIn("+THREE", text)
        self.assertNotIn("-one", text)  # the kept edit is not repeated
        self.assertNotIn("b.ts", text)  # an untouched kept file is not listed
        self.assertIn("-one", proof.incremental_diff_text(root, None, changes[:1]))

    def test_the_proposal_log_is_bounded(self):
        record: dict = {}
        proof.record_proposal(record, number=2, round_number=1, outcome="failed the type check",
                              summary="s" * 900, diff="d" * 9000, detail="x" * 900, tests_passed=None, kept=False)
        (entry,) = record["proposals"]
        self.assertEqual((len(entry["summary"]), len(entry["diff"]), len(entry["detail"])), (300, 3000, 400))
        self.assertIs(entry["kept"], False)
        self.assertNotIn("tests_passed", entry)
        self.assertEqual((entry["proposal"], entry["round"], entry["counted"]), (2, 1, True))


class FeedbackTests(unittest.TestCase):
    CHANGES = [{"path": "src/label.ts", "content": ONLY_TWO}]

    def feedback(self, improved: bool) -> str:
        return proof.cumulative_regression_feedback(
            tap(1, 2).replace("case 1", "three is spelled out"), self.CHANGES, 2, 3,
            tap(2, 1), 1, improved, 1 if improved else 2, "--- a\n+++ b\n+x\n", 2, 5)

    def test_a_kept_proposal_is_reported_as_kept(self):
        text = self.feedback(True)
        self.assertIn("REPAIR ROUND 2 of 5", text)
        self.assertIn("from 1 to 2", text)
        self.assertIn("KEPT", text)
        self.assertIn("2 of 3 of the verifier's tests", text)
        self.assertIn("CURRENT STATE of the patched files", text)
        self.assertIn("three is spelled out", text)
        self.assertNotIn("PATCHPROOF_", text)
        self.assertIn("YOUR LAST PROPOSAL", text)

    def test_a_discarded_proposal_is_reported_with_its_failing_tests(self):
        text = self.feedback(False)
        self.assertIn("DISCARDED", text)
        self.assertIn("kept patch is unchanged", text)
        self.assertIn("case 1; case 2", text)

    def test_the_feedback_is_bounded_and_has_no_credentials(self):
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "secret-key-123"}):
            text = proof.cumulative_regression_feedback(
                "x" * 50_000 + "secret-key-123", self.CHANGES, 2, 3, "y" * 50_000, 1, False, 2, "d" * 50_000, 1, 5)
        self.assertLessEqual(len(text), 12_000)
        self.assertNotIn("secret-key-123", text)

    def test_a_type_error_shows_the_numbered_source_line(self):
        compiler = ("PATCHPROOF_SOURCE_CHECK=failed\n"
                    "src/label.ts(1,50): error TS2322: Type '2' is not assignable to type 'string'.\n")
        text = proof.source_check_feedback(compiler, "--- a\n+++ b\n", [{"path": "src/label.ts", "content": TYPE_ERROR}])
        self.assertIn("SOURCE AROUND THE FAILING LINE", text)
        self.assertIn(">> 1: export const label", text)
        self.assertNotIn("PATCHPROOF_SOURCE_CHECK", text)
        plain = proof.source_check_feedback(compiler, "--- a\n+++ b\n")  # callers without the files still work
        self.assertNotIn("SOURCE AROUND", plain)

    def test_a_deep_type_error_is_found_in_a_longer_file(self):
        body = "\n".join(f"const v{n} = {n};" for n in range(1, 120)) + "\n"
        text = proof.source_excerpts("lib/recency.ts(75,16): error TS7053: Element implicitly has an 'any' type.",
                                     [{"path": "lib/recency.ts", "content": body}])
        self.assertIn(">> 75: const v75 = 75;", text)
        self.assertIn("   71: const v71", text)


class PromptTests(unittest.TestCase):
    def call(self, working_files):
        root = project()
        adapter = runtimes.detect_runtime(root)
        seen: dict = {}

        def fake(**kwargs):
            seen.update(kwargs)
            return {"summary": "x", "edits": [{"path": "src/label.ts",
                                              "old": "n === 2 ? 'two' : 'many'" if working_files else "'one' : 'many'",
                                              "new": "n === 2 ? 'two' : n === 3 ? 'three' : 'many'" if working_files
                                              else "'one' : n === 2 ? 'two' : 'many'"}]}

        with patch.object(proof, "model_json", side_effect=fake):
            changes, _ = proof.generate_candidate(
                issue=proof.Issue(1, "t", "b"), context="CTX", allowed_source_paths={"src/label.ts"}, api_key="x",
                model="m", root=root, adapter=adapter, strategy="s", temperature=0.2, retry_feedback="FB",
                working_files=working_files)
        return seen, changes

    def test_the_first_proposal_keeps_the_original_source_rule(self):
        seen, changes = self.call(None)
        self.assertIn("ORIGINAL repository source", seen["system"])
        self.assertNotIn("CURRENT STATE OF THE FILES", seen["user"])
        self.assertEqual(changes[0]["content"], ONLY_TWO)

    def test_a_kept_patch_is_shown_and_the_edits_apply_to_it(self):
        seen, changes = self.call({"src/label.ts": ONLY_TWO})
        self.assertNotIn("ORIGINAL repository source", seen["system"])
        self.assertIn("CURRENT STATE of the patched files", seen["system"])
        self.assertIn("CURRENT STATE OF THE FILES YOU HAVE ALREADY PATCHED", seen["user"])
        self.assertIn("=== src/label.ts ===\n" + ONLY_TWO, seen["user"])
        self.assertEqual(changes[0]["content"], RIGHT3)

    def test_edits_apply_to_the_kept_text_and_untouched_kept_files_stay_in_the_result(self):
        root = project()
        (root / "src/other.ts").write_text("export const other = 1;\n")
        (root / "patchproof.json").write_text(json.dumps({
            "runtime": "node-typescript", "scope": {"allowed_paths": ["src/label.ts", "src/other.ts"]}}))
        adapter = runtimes.detect_runtime(root)
        allowed = {"src/label.ts", "src/other.ts"}
        payload = {"summary": "x", "edits": [{"path": "src/other.ts", "old": "= 1;", "new": "= 2;"}]}
        changes, _ = proof.validate_candidate(payload, allowed, root, adapter, base_contents={"src/label.ts": ONLY_TWO})
        self.assertEqual({item["path"]: item["content"] for item in changes},
                         {"src/label.ts": ONLY_TWO, "src/other.ts": "export const other = 2;\n"})
        stale = {"summary": "x", "edits": [{"path": "src/label.ts", "old": "(n === 1 ? 'one' : 'many')", "new": "x"}]}
        with self.assertRaises(proof.PatchProofError) as caught:  # the original text is gone from the kept file
            proof.validate_candidate(stale, allowed, root, adapter, base_contents={"src/label.ts": ONLY_TWO})
        self.assertIn("matched 0 locations", str(caught.exception))


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class CumulativePipelineTests(unittest.TestCase):
    def run_case(self, replies, env=None):
        root = project()
        calls: list[dict] = []

        def candidate(**kwargs):
            calls.append({"feedback": kwargs.get("retry_feedback", ""), "temperature": kwargs.get("temperature"),
                          "working_files": kwargs.get("working_files")})
            return [{"path": "src/label.ts", "content": replies[min(len(calls), len(replies)) - 1]}], f"scripted {len(calls)}"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root, proof.Issue(1, "label is wrong", "label(2) and label(3) must spell the number."),
            THREE_TESTS % "js", candidate, env_extra=env)
        return root, result, record, error, calls

    def test_an_improvement_becomes_the_base_of_the_next_proposal(self):
        root, result, record, error, calls = self.run_case([ONLY_TWO, RIGHT3])
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual((root / "src/label.ts").read_text(), RIGHT3)
        self.assertIsNone(calls[0]["working_files"])
        self.assertEqual(calls[1]["working_files"], {"src/label.ts": ONLY_TWO})
        second = calls[1]["feedback"]
        self.assertIn("KEPT", second)
        self.assertIn("2 of 3 of the verifier's tests", second)
        self.assertIn("three is spelled out in lower case", second)  # the test that still fails, by name
        self.assertNotIn("import assert", second)  # never the test source
        first = record["candidates"][0]
        self.assertEqual([entry["outcome"] for entry in first["proposals"]],
                         ["failed the frozen regression", "passed the frozen regression"])
        self.assertIs(first["proposals"][0]["kept"], True)
        self.assertEqual((first["proposals"][0]["tests_passed"], first["proposals"][0]["tests_total"]), (2, 3))
        self.assertIn("+  ", first["proposals"][0]["diff"] + "+  ")  # a diff is recorded
        self.assertEqual(first["kept_patch"]["tests_passed"], 2)
        self.assertTrue(record["race"]["cumulative_repair"])
        # a candidate starts from the original; only its own earlier proposals are kept
        self.assertTrue(all(call["working_files"] is None for call in calls[2:]))

    def test_a_proposal_that_passes_no_more_tests_is_discarded(self):
        root, result, record, error, calls = self.run_case([ONLY_TWO, TWO_SPOILED, RIGHT3])
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(calls[2]["working_files"], {"src/label.ts": ONLY_TWO})  # the spoiled one is not the base
        self.assertIn("DISCARDED", calls[2]["feedback"])
        self.assertIn("two is spelled out in lower case", calls[2]["feedback"])
        first = record["candidates"][0]
        self.assertEqual([entry.get("kept") for entry in first["proposals"]], [True, False, None])
        self.assertEqual((root / "src/label.ts").read_text(), RIGHT3)

    def test_the_switch_restores_the_rc43_flow(self):
        root, result, record, error, calls = self.run_case([ONLY_TWO, RIGHT3], {"PATCHPROOF_CUMULATIVE_REPAIR": "0"})
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertTrue(all(call["working_files"] is None for call in calls))
        self.assertIn("ORIGINAL source", calls[1]["feedback"])
        self.assertNotIn("KEPT", calls[1]["feedback"])
        self.assertFalse(record["race"]["cumulative_repair"])
        self.assertNotIn("kept_patch", record["candidates"][0])

    def test_a_repeated_patch_does_not_spend_a_proposal(self):
        # Two proposals in all: under rc.43 the repeat at the last slot ended the candidate.
        root, result, record, error, calls = self.run_case([ONLY_TWO, ONLY_TWO, RIGHT3], {"PATCHPROOF_REPAIR_ROUNDS": "1"})
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual((root / "src/label.ts").read_text(), RIGHT3)
        first = record["candidates"][0]
        self.assertEqual([(entry["proposal"], entry["counted"], entry["outcome"]) for entry in first["proposals"]],
                         [(1, True, "failed the frozen regression"), (1, False, "repeated an earlier patch"),
                          (2, True, "passed the frozen regression")])
        self.assertEqual(first["repeated_patches"], 1)
        self.assertEqual(calls[2]["temperature"], 0.4)  # more spread after a repeat
        self.assertIn("IDENTICAL", calls[2]["feedback"])
        self.assertIn("KEPT", calls[2]["feedback"])  # the notice is added to the kept-patch feedback
        self.assertEqual(calls[2]["working_files"], {"src/label.ts": ONLY_TWO})

    def test_repeats_still_end_a_candidate(self):
        root, result, record, error, calls = self.run_case([ONLY_TWO])
        self.assertIsNotNone(error)
        first = record["candidates"][0]
        self.assertEqual(first["repair_stopped"], "the same patch was proposed again")
        self.assertEqual(first["repeated_patches"], proof.DUPLICATE_STOP)
        self.assertEqual([entry["counted"] for entry in first["proposals"]], [True, False, False, False])

    def test_a_proposal_that_breaks_the_existing_tests_is_logged_and_not_kept(self):
        root, result, record, error, calls = self.run_case([BREAKS_EXISTING, RIGHT3])
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        first = record["candidates"][0]
        self.assertEqual([entry["outcome"] for entry in first["proposals"]],
                         ["failed the existing tests", "passed the frozen regression"])
        self.assertIsNone(calls[1]["working_files"])  # it never reached the verifier's tests, so it is not a base
        self.assertNotIn("kept_patch", first)

    def test_a_type_error_is_logged_and_shows_the_source_line(self):
        root, result, record, error, calls = self.run_case([TYPE_ERROR, RIGHT3])
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        first = record["candidates"][0]
        self.assertEqual(first["proposals"][0]["outcome"], "failed the type check")
        self.assertIn("TS2322", first["proposals"][0]["detail"])
        self.assertIn("SOURCE AROUND THE FAILING LINE", calls[1]["feedback"])
        # (the offline run's fake API key is the letter x, which the engine redacts, hence not matching `export`)
        self.assertIn(">> 1: ", calls[1]["feedback"])
        self.assertIn("const label = (n: number): string => (n === 1 ? 'one' : 2);", calls[1]["feedback"])


if __name__ == "__main__":
    unittest.main()
