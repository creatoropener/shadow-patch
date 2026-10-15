"""rc.32: table evidence, refusal feedback and stray punctuation, from the live file-sharing-app-1 run."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import spec_profile as sp

ROOT = Path(__file__).resolve().parents[1]
ISSUE = (ROOT / "bench/issues/file-sharing-app-1.md").read_text(encoding="utf-8")
HEADER = "Function Input Expected output"
SOURCE = """export function formatBytes(n: number): string { return String(n); }
export const formatSpeed = (n: number): string => formatBytes(n) + "/s";
"""
MODULES = {"lib/utils/format.ts": SOURCE}
ROWS = [
    ("e1", "formatBytes", 512, "512 B", "formatBytes 512 512 B"),
    ("e2", "formatBytes", 1024, "1.0 KB", "formatBytes 1024 1.0 KB"),
    ("e3", "formatBytes", 1536, "1.5 KB", "formatBytes 1536 1.5 KB"),
    ("e4", "formatBytes", 102400, "100 KB", "formatBytes 102400 100 KB"),
    ("e5", "formatBytes", 1048576, "1.0 MB", "formatBytes 1048576 1.0 MB"),
    ("e6", "formatBytes", 1073741824, "1.0 GB", "formatBytes 1073741824 1.0 GB"),
    ("e7", "formatSpeed", 1536, "1.5 KB/s", "formatSpeed 1536 1.5 KB/s"),
]


def spec(evidence_of):
    return {"supported": True, "module": "lib/utils/format.ts", "examples": [
        {"id": ident, "export": export, "args": [arg], "returns": ret, "evidence": evidence_of(row)}
        for ident, export, arg, ret, row in ROWS]}


def check(raw):
    return sp.validate_spec(raw, issue_text=ISSUE, modules=MODULES, source_literals=set(), partial=True)


class TableEvidenceTests(unittest.TestCase):
    def test_the_live_header_plus_row_quotation_grounds_every_example(self):
        # rc.32 and rc.33 live runs: the model quoted the column titles and then its own row, every time.
        result = check(spec(lambda row: HEADER + "\n" + row))
        self.assertTrue(result.ok)
        self.assertEqual([e.id for e in result.spec.examples], [f"e{i}" for i in range(1, 8)])
        self.assertEqual(result.rejected, [])

    def test_grounding_is_judged_on_the_row_and_the_header_is_only_context(self):
        result = check(spec(lambda row: HEADER + "\n" + row))
        third = result.spec.examples[2]
        self.assertEqual(third.span, "formatBytes 1536 1.5 KB")
        self.assertTrue(third.evidence.startswith(HEADER))  # what the model wrote is kept as written

    def test_a_value_that_is_only_in_the_header_lines_is_refused(self):
        raw = spec(lambda row: row)
        # e2 (1024 -> 1.0 KB) quotes the 512 row and then the 1536 row. The rows are not adjacent, so the first
        # line is context only and neither 1024 nor "1.0 KB" is in the passage that grounds the example.
        raw["examples"][1]["evidence"] = "formatBytes 512 512 B\nformatBytes 1536 1.5 KB"
        result = check(raw)
        self.assertIn("example e2", dict(result.rejected))
        self.assertIn("not in the quoted evidence", dict(result.rejected)["example e2"])

    def test_skipped_lines_beyond_a_short_header_are_still_refused_with_the_row_named(self):
        rows = [row for *_, row in ROWS]
        result = check(spec(lambda row: "\n".join([HEADER, rows[0], rows[1], row])))
        reasons = dict(result.rejected)
        self.assertIn("example e7", reasons)
        message = reasons["example e7"]
        self.assertIn("not next to each other", message)
        self.assertIn("One or two short header lines", message)
        self.assertIn(json.dumps("formatSpeed 1536 1.5 KB/s"), message)

    def test_a_long_header_is_not_context(self):
        long_line = "Function Input Expected output " + "x" * 120
        issue = long_line + "\nformatBytes 512 512 B\nformatBytes 1536 1.5 KB\n"
        self.assertIsNone(sp.locate_evidence_with_context(long_line + "\nformatBytes 1536 1.5 KB", issue))

    def test_a_header_must_come_before_the_row_in_the_issue(self):
        reversed_quote = "formatBytes 1536 1.5 KB\n" + HEADER
        self.assertIsNone(sp.locate_evidence_with_context(reversed_quote, ISSUE))

    def test_one_row_per_example_grounds_every_example(self):
        result = check(spec(lambda row: row))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.spec.examples), 7)
        self.assertEqual(result.rejected, [])

    def test_text_that_is_not_in_the_issue_still_gets_the_closest_line(self):
        raw = spec(lambda row: row)
        raw["examples"][1]["evidence"] = "formatBytes 1024 gives one point zero KB"
        result = check(raw)
        message = dict(result.rejected)["example e2"]
        self.assertIn("does not appear in the issue", message)
        self.assertNotIn("not next to each other", message)

    def test_a_row_is_only_suggested_when_one_line_holds_all_the_values(self):
        rows = [row for *_, row in ROWS]
        raw = spec(lambda row: "\n".join([HEADER, rows[0], rows[1], row]))
        raw["examples"][6]["returns"] = "9.9 KB/s"
        message = dict(check(raw).rejected)["example e7"]
        self.assertIn("not next to each other", message)
        self.assertNotIn("The issue line that holds", message)

    def test_the_prompt_asks_for_the_row_and_allows_column_titles(self):
        self.assertIn("ONE contiguous passage", sp.SYSTEM_PROMPT)
        self.assertIn("column\n  titles", sp.SYSTEM_PROMPT)
        self.assertIn("text in the header lines does not count", sp.SYSTEM_PROMPT)

    def test_a_top_level_evidence_field_is_told_where_it_belongs(self):
        raw = spec(lambda row: row)
        raw["evidence"] = HEADER
        result = check(raw)
        self.assertFalse(result.ok)
        self.assertIn("belongs inside each example", result.errors[0])


class StrayPunctuationTests(unittest.TestCase):
    def wrap(self, body, tail=""):
        return f"{sp.SPEC_BEGIN}\n{body}\n{sp.SPEC_END}{tail}"

    def test_a_quote_after_the_end_marker_is_dropped_and_noted(self):
        # The live shape: the model wrote the END marker as a JSON string, then closed the quote.
        notes = []
        text = f'{sp.SPEC_BEGIN}\n{{"supported": true, "examples": [{{"id": "e1"}}], "{sp.SPEC_END}"'
        value = sp.parse_spec_response(text, notes)
        self.assertEqual(value, {"supported": True, "examples": [{"id": "e1"}]})
        self.assertEqual(len(notes), 2)
        self.assertIn("stray punctuation", notes[0])
        self.assertIn("closed 1 open bracket", notes[1])

    def test_the_end_marker_written_as_a_json_string_with_a_closing_brace_is_accepted(self):
        # rc.33 live shape: ...}], "<<<END>>>"}
        notes = []
        text = f'{sp.SPEC_BEGIN}\n{{"supported": true, "examples": [{{"id": "e1"}}], "{sp.SPEC_END}"}}'
        value = sp.parse_spec_response(text, notes)
        self.assertEqual(value, {"supported": True, "examples": [{"id": "e1"}]})
        self.assertIn("stray punctuation", notes[0])

    def test_words_outside_the_block_are_still_refused(self):
        for tail in (" thanks", " \"done\"", "\n```", " }."):
            with self.subTest(tail), self.assertRaises(sp.SpecFormatError):
                sp.parse_spec_response(self.wrap('{"a": 1}', tail))
        with self.assertRaises(sp.SpecFormatError):
            sp.parse_spec_response("Here you go: " + self.wrap('{"a": 1}'))

    def test_a_clean_block_reports_nothing(self):
        notes = []
        sp.parse_spec_response(self.wrap('{"a": 1}'), notes)
        self.assertEqual(notes, [])


class RefusalFeedbackTests(unittest.TestCase):
    REFUSED = [{"example": "example e2", "reason": "example e2: the `evidence` text does not appear in the issue."},
               {"example": "example e3", "reason": "example e3: every line of the `evidence` appears in the issue, but not next to each other."}]

    def decision(self, states):
        return sp.Decision(action="retry", classification="test passed on the unfixed revision", message="No example failed.",
                           states=states, qualifying=[], pruned={})

    def test_the_retry_names_the_refused_examples_and_why(self):
        text = sp.run_feedback("{}", self.decision({"e1": "pass"}), "out", refused=self.REFUSED)
        self.assertIn("REFUSED", text)
        self.assertIn("example e2: the `evidence` text does not appear", text)
        self.assertNotIn("example e2: example e2", text)
        self.assertIn("not next to each other", text)
        self.assertIn("do not show the bug", text)

    def test_the_do_not_show_the_bug_note_only_appears_when_nothing_fails(self):
        text = sp.run_feedback("{}", self.decision({"e1": "pass", "e4": "mismatch"}), "out", refused=self.REFUSED)
        self.assertIn("REFUSED", text)
        self.assertNotIn("do not show the bug", text)

    def test_nothing_is_added_when_nothing_was_refused(self):
        text = sp.run_feedback("{}", self.decision({"e1": "pass"}), "out")
        self.assertNotIn("REFUSED", text)
        self.assertEqual(text, sp.run_feedback("{}", self.decision({"e1": "pass"}), "out", refused=[]))

    def test_static_rejections_also_carry_the_refusals(self):
        self.assertIn("REFUSED", sp.static_feedback("{}", "type-check failed", "out", refused=self.REFUSED))
        self.assertNotIn("REFUSED", sp.static_feedback("{}", "type-check failed", "out"))


if __name__ == "__main__":
    unittest.main()
