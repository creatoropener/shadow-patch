"""rc.43: an edit whose `old` text matches nothing exactly is matched through the slips a JSON answer makes.

CareerPilot #8 on rc.41 and rc.42: five of nine proposals ended with "Edit for lib/recency.ts matched 0 locations", on lines
full of backslashes, and the proof did not say what the model had sent. Now the error shows the model's own `old`, a single
backslash before b, f or v (a control character in JSON), doubled backslashes and drifting indentation are tolerated when they
lead to exactly one place, and a candidate gets a third try at an invalid proposal unless repair rounds are 0.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proof
import runtimes

LINE = r"if (/\b(posted|published)\s+yesterday\b/i.test(text)) candidates.push(new Date(now.getTime() - DAY_MS));"
SOURCE = ("const RELATIVE = /(\\d+)/g;\n"
          "export function f(text: string) {\n"
          "  const candidates: Date[] = [];\n"
          f"  {LINE}\n"
          "  return candidates;\n"
          "}\n")


class TolerantEditTests(unittest.TestCase):
    def test_a_single_backslash_before_b_arrives_as_a_backspace_and_is_repaired(self):
        old = LINE.replace("\\b", "\x08")
        self.assertNotIn(old, SOURCE)
        actual, new, label = proof.tolerant_edit(SOURCE, old, "X" + old)
        self.assertEqual(actual, LINE)
        self.assertEqual(new, "X" + LINE)
        self.assertIn("control characters", label)

    def test_doubled_backslashes_are_read_as_single_ones(self):
        old = LINE.replace("\\", "\\\\")
        actual, new, label = proof.tolerant_edit(SOURCE, old, "N" + old)
        self.assertEqual((actual, new), (LINE, "N" + LINE))
        self.assertIn("doubled backslashes", label)

    def test_indentation_and_trailing_spaces_are_ignored_when_one_place_matches(self):
        source = "a();\n  if (x) {\n    y();\n  }\nb();\n"
        actual, new, label = proof.tolerant_edit(source, "if (x) {\n  y();\n}", "if (z) {\n  w();\n}")
        self.assertEqual(actual, "if (x) {\n    y();\n  }")  # the file's own indentation stays in front of it
        self.assertIn("indentation", label)
        actual, _, _ = proof.tolerant_edit(source, "  if (x) {   \n    y();\n  }   \n", "N\n")
        self.assertEqual(actual, "  if (x) {\n    y();\n  }\n")

    def test_two_places_or_none_are_not_guessed(self):
        self.assertIsNone(proof.tolerant_edit("a\n  foo();\nb\n foo();\n", "foo();   ", "bar();"))
        self.assertIsNone(proof.tolerant_edit(SOURCE, "totally different();", "x"))
        self.assertIsNone(proof.tolerant_edit(SOURCE, "", "x"))


class ValidateCandidateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="rc43-"))
        (self.root / "package.json").write_text('{"type":"module"}')
        (self.root / "tsconfig.json").write_text("{}")
        (self.root / "src").mkdir()
        (self.root / "src/f.ts").write_text(SOURCE)
        self.adapter = runtimes.detect_runtime(self.root)

    def check(self, old, new):
        return proof.validate_candidate({"summary": "s", "edits": [{"path": "src/f.ts", "old": old, "new": new}]},
                                        {"src/f.ts"}, self.root, self.adapter)

    def test_an_exact_edit_has_no_notes(self):
        changes, _ = self.check(LINE, LINE.replace("yesterday", "today"))
        self.assertEqual(changes.notes, [])
        self.assertIn("today", changes[0]["content"])

    def test_a_backspace_slip_is_applied_and_noted(self):
        changes, _ = self.check(LINE.replace("\\b", "\x08"), LINE.replace("\\b", "\x08").replace("yesterday", "today"))
        self.assertEqual(len(changes.notes), 1)
        self.assertIn("edit 1 for src/f.ts matched after treating: control characters", changes.notes[0])
        content = changes[0]["content"]
        self.assertIn(r"/\b(posted|published)\s+today\b/i", content)  # the new text got the same repair
        self.assertNotIn("\x08", content)

    def test_a_mismatch_shows_what_the_model_sent_and_the_closest_real_text(self):
        old = LINE.replace("yesterday", "tomorrow") + "\n  return nothing;"
        with self.assertRaises(proof.PatchProofError) as caught:
            self.check(old, "x")
        message = str(caught.exception)
        self.assertIn("matched 0 locations", message)
        self.assertIn("YOUR `old` BEGAN", message)
        self.assertIn("tomorrow", message)
        self.assertIn("THE CLOSEST TEXT IN THE FILE", message)
        self.assertIn("yesterday", message)

    def test_a_backspace_in_the_shown_old_is_distinguishable_from_a_real_backslash_b(self):
        shown = proof.edit_mismatch_help(SOURCE, "x\x08y\\bz", 0)
        self.assertIn('"x\\by\\\\bz"', shown)  # JSON: \b is the control character, \\b is backslash then b


class GenerationAttemptTests(unittest.TestCase):
    def run_wrapper(self, side_effects, env):
        record = {"candidate": 1}
        with patch.dict(os.environ, env), patch.object(proof, "generate_candidate", side_effect=side_effects):
            try:
                return record, proof.generate_candidate_with_retry(candidate_record=record), None
            except proof.PatchProofError as error:
                return record, None, error

    def test_the_third_attempt_is_made_unless_repair_rounds_are_zero(self):
        bad = proof.PatchProofError("Edit for a.ts matched 0 locations; exactly one is required.")
        good = ([{"path": "a.ts", "content": "x"}], "ok")
        record, result, error = self.run_wrapper([bad, bad, good], {"PATCHPROOF_REPAIR_ROUNDS": "5"})
        self.assertIsNone(error)
        self.assertEqual(result, good)
        self.assertEqual(record["generation_attempts"], 3)
        self.assertEqual(len(record["generation_errors"]), 2)
        record, result, error = self.run_wrapper([bad, bad, bad], {"PATCHPROOF_REPAIR_ROUNDS": "5"})
        self.assertIn("failed three times", str(error))
        record, result, error = self.run_wrapper([bad, bad, good], {"PATCHPROOF_REPAIR_ROUNDS": "0"})
        self.assertIn("failed twice", str(error))
        self.assertEqual(record["generation_attempts"], 2)

    def test_notes_from_a_tolerated_edit_land_in_the_candidate_record(self):
        changes = proof.EditList([{"path": "a.ts", "content": "x"}])
        changes.notes = ["edit 1 for a.ts matched after treating: doubled backslashes in `old` read as single ones"]
        record, result, error = self.run_wrapper([(changes, "ok")], {"PATCHPROOF_REPAIR_ROUNDS": "5"})
        self.assertIsNone(error)
        self.assertEqual(record["edit_notes"], changes.notes)


if __name__ == "__main__":
    unittest.main()
