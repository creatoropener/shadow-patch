"""rc.45: the engine states the numbered groups of a regular expression the solver changed, the solver can answer in
plain text instead of JSON, and its reasoning can be switched on.

CareerPilot #8 on rc.44: none of eight proposals made a single new test pass. Five changed the RELATIVE pattern and left
the code that reads its groups unchanged or numbered wrongly (`match[3] ?? match[5]` for a unit that is group 6; one
pattern began `(?!\\d)(\\d{1,3})`, which can never match), and two were damaged by JSON escaping (`\\\\s` written into a
regular expression, an opening `/` lost). The patches below are rebuilt from that proof's diffs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import proof
import runtimes
from tests import support_pipeline as pipeline
from tests.test_rc40_repair_rounds import REGRESSION, RIGHT, project

ORIGINAL = """const UNIT_MS: Record<string, number> = { minute: 60000, hour: 3600000, day: 86400000 };
const RELATIVE = /\\b(\\d{1,3})(\\+)?\\s*(minute|hour|day)s?\\s+ago\\b/gi;

export function findPostedDate(text: string, now: Date): Date | null {
  const candidates: Date[] = [];
  for (const match of text.matchAll(RELATIVE)) {
    const amount = Number(match[1]) + (match[2] ? 1 : 0);
    candidates.push(new Date(now.getTime() - amount * UNIT_MS[match[3].toLowerCase()]));
  }
  if (/\\b(posted|published)\\s+(just\\s+now|today)\\b/i.test(text)) candidates.push(now);
  return candidates[0] ?? null;
}
"""


def patched(old: str, new: str) -> str:
    assert old in ORIGINAL
    return ORIGINAL.replace(old, new)


# cand 1, proposal 2 (rc.44): a second alternative whose groups are numbered 4 to 6, read as 3 and 5
TWO_ALTERNATIVES = patched(
    "const RELATIVE = /\\b(\\d{1,3})(\\+)?\\s*(minute|hour|day)s?\\s+ago\\b/gi;",
    "const RELATIVE = /(?!\\d)(\\d{1,3})(\\+)?\\s*(minute|hour|day)s?\\s+ago\\b|\\b(\\d{1,3})(\\+)?\\s*(min|h|d)\\b/gi;"
).replace(
    "const amount = Number(match[1]) + (match[2] ? 1 : 0);",
    "const amount = Number(match[1] ?? match[3]) + (match[2] ?? match[4] ? 1 : 0);\n    const unit = match[3] ?? match[5];")


def repo(original: str = ORIGINAL) -> Path:
    root = Path(tempfile.mkdtemp(prefix="rc45-"))
    (root / "lib").mkdir()
    (root / "lib/recency.ts").write_text(original)
    return root


class RegexLiteralTests(unittest.TestCase):
    def test_literals_get_their_line_name_and_flags_and_comments_and_division_are_skipped(self):
        text = ("// const NOT = /nope/;\n"
                "const AGE = /\\b(\\d+)\\s*d\\b/gi;\n"
                "const half = total / 2 / 3;\n"
                "if (/^\\d{4}$/.test(value)) return;\n"
                "const parts = text.split(/[,;]\\s*/);\n")
        found = proof.regex_literals(text)
        self.assertEqual([(entry["line"], entry["name"], entry["source"], entry["flags"]) for entry in found], [
            (2, "AGE", "\\b(\\d+)\\s*d\\b", "gi"),
            (4, None, "^\\d{4}$", ""),
            (5, None, "[,;]\\s*", ""),
        ])

    def test_groups_are_numbered_like_javascript_numbers_them(self):
        groups, ranges = proof.regex_groups("(?:^|\\s)(a|(b))(?<year>\\d{4})(?=x)(?!y)(?<!z)[(]\\(([)])")
        self.assertEqual([(number, text) for number, text, _ in groups],
                         [(1, "(a|(b))"), (2, "(b)"), (3, "(?<year>\\d{4})"), (4, "([)])")])
        self.assertEqual(ranges, [(1, 4)])

    def test_top_level_alternatives_own_their_groups(self):
        _, ranges = proof.regex_groups("(a)(b)|(c)|d")
        self.assertEqual(ranges, [(1, 2), (3, 3)])
        _, ranges = proof.regex_groups("x(a|b)y")
        self.assertEqual(ranges, [(1, 1)])  # an alternation inside a group is not a top-level alternative


class RegexReviewTests(unittest.TestCase):
    def review(self, content: str) -> str:
        return proof.regex_review(repo(), [{"path": "lib/recency.ts", "content": content}])

    def test_the_group_map_names_each_group_and_what_the_code_reads(self):
        text = self.review(TWO_ALTERNATIVES)
        self.assertIn("REGULAR EXPRESSIONS YOUR PATCH ADDED OR CHANGED", text)
        self.assertIn("RELATIVE = /", text)
        for group in ("1 = (\\d{1,3})", "3 = (minute|hour|day)", "4 = (\\d{1,3})", "6 = (min|h|d)"):
            self.assertIn(group, text)
        self.assertIn("top-level alternatives own groups 1-3, 4-6", text)
        self.assertIn("reads group(s) 1, 2, 3, 4, 5", text)
        self.assertIn("groups the code never reads: 6", text)  # the unit of the second alternative

    def test_a_pattern_that_can_never_match_is_named(self):
        text = self.review(TWO_ALTERNATIVES)
        self.assertIn("can never match", text)
        self.assertIn("(?!\\d)(\\d", text)
        self.assertIn("(?<!\\d)", text)

    def test_reading_a_group_the_pattern_does_not_have_is_flagged(self):
        text = self.review(patched("const amount = Number(match[1])", "const amount = Number(match[7])"))
        # nothing changed in the pattern, so there is nothing to review
        self.assertEqual(text, "")
        text = self.review(patched("(minute|hour|day)s?", "(minute|hour)s?").replace("match[2]", "match[5]"))
        self.assertIn("PROBLEM: it reads group 5 but the pattern has only 3", text)

    def test_a_doubled_backslash_in_a_regular_expression_is_flagged(self):
        text = self.review(patched("/\\b(posted|published)\\s+(just\\s+now|today)\\b/i",
                                   "/\\b(posted|published)\\\\s+(just\\s+now|today)\\\\b/i"))
        self.assertIn("is two backslashes", text)
        self.assertIn("\\\\s", text)

    def test_an_unchanged_regular_expression_and_other_languages_give_nothing(self):
        self.assertEqual(self.review(ORIGINAL), "")
        root = repo()
        self.assertEqual(proof.regex_review(root, [{"path": "lib/x.py", "content": "r = /(a)/"}]), "")
        self.assertEqual(proof.regex_review(root, None), "")

    def test_the_text_is_bounded_and_goes_first(self):
        many = ORIGINAL + "".join(f"const R{n} = /(a{n})(b)(c)\\s*{'(x)' * 12}/g;\n" for n in range(30))
        self.assertLessEqual(len(self.review(many)), 1810)
        wrapped = proof.with_regex_review("OLD FEEDBACK", repo(), [{"path": "lib/recency.ts", "content": TWO_ALTERNATIVES}])
        self.assertTrue(wrapped.startswith("REGULAR EXPRESSIONS"))
        self.assertTrue(wrapped.endswith("OLD FEEDBACK"))
        self.assertEqual(proof.with_regex_review("OLD", repo(), [{"path": "lib/recency.ts", "content": ORIGINAL}]), "OLD")


BROKEN_REGEX = ("const PAIR = /(?!\\d)(\\d)/;\n"
                "export const label = (n: number): string => (n === 2 ? 'two' : 'many');\n")


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class RegexReviewPipelineTests(unittest.TestCase):
    def test_feedback_after_a_failed_proposal_carries_the_group_map(self):
        root = project()
        calls: list[str] = []

        def candidate(**kwargs):
            calls.append(kwargs.get("retry_feedback", ""))
            return [{"path": "src/label.ts", "content": BROKEN_REGEX if len(calls) == 1 else RIGHT}], "scripted"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root, proof.Issue(1, "label(2) is wrong", "label(2) must be two."),
            REGRESSION % "js", candidate)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        second = calls[1]
        self.assertTrue(second.startswith("REGULAR EXPRESSIONS YOUR PATCH ADDED OR CHANGED"))
        self.assertIn("PAIR = /(?!\\d)(\\d)/", second)
        self.assertIn("can never match", second)
        self.assertIn("1 = (\\d)", second)


EDIT_ANSWER = """Here is the change.
```
<<<PATCHPROOF_SUMMARY>>>
Accept a/an and compact units.
Keep the existing behavior.
<<<PATCHPROOF_FILE lib/recency.ts>>>
<<<PATCHPROOF_OLD>>>
const RELATIVE = /\\b(\\d{1,3})(\\+)?\\s*(minute|hour|day)s?\\s+ago\\b/gi;
<<<PATCHPROOF_NEW>>>
const RELATIVE = /(?<!\\d)(\\d{1,3}|an?)(\\+)?\\s*(minute|hour|day)s?\\s+ago\\b/gi;
<<<PATCHPROOF_END>>>

<<<PATCHPROOF_FILE lib/recency.ts>>>
<<<PATCHPROOF_OLD>>>
    const amount = Number(match[1]) + (match[2] ? 1 : 0);
<<<PATCHPROOF_NEW>>>
    const amount = (/^an?$/i.test(match[1]) ? 1 : Number(match[1])) + (match[2] ? 1 : 0);
<<<PATCHPROOF_END>>>
```
"""


class EditBlockTests(unittest.TestCase):
    def test_a_fenced_answer_with_prose_gives_the_same_payload_as_json(self):
        payload = proof.parse_edit_blocks(EDIT_ANSWER)
        self.assertEqual(payload["summary"], "Accept a/an and compact units. Keep the existing behavior.")
        self.assertEqual(len(payload["edits"]), 2)
        first = payload["edits"][0]
        self.assertEqual(first["path"], "lib/recency.ts")
        self.assertIn("/\\b(\\d{1,3})(\\+)?\\s*(minute", first["old"])  # one backslash, as in the file
        self.assertNotIn("\\\\", first["old"] + first["new"])
        self.assertEqual(payload["edits"][1]["old"], "    const amount = Number(match[1]) + (match[2] ? 1 : 0);")  # indentation kept

    def test_the_edits_apply_exactly_with_no_tolerance_needed(self):
        root = repo()
        adapter = runtimes.detect_runtime(project())
        changes, summary = proof.validate_candidate(
            proof.parse_edit_blocks(EDIT_ANSWER), {"lib/recency.ts"}, root, adapter, edit_format="blocks")
        self.assertEqual(changes.notes, [])
        self.assertEqual(changes.format, "blocks")
        content = changes[0]["content"]
        self.assertIn("(?<!\\d)(\\d{1,3}|an?)", content)
        self.assertIn("/^an?$/i.test(match[1])", content)
        self.assertNotIn("\x08", content)

    def test_an_empty_new_text_deletes_and_windows_line_endings_work(self):
        text = ("<<<PATCHPROOF_FILE a.ts>>>\r\n<<<PATCHPROOF_OLD>>>\r\nx\r\ny\r\n<<<PATCHPROOF_NEW>>>\r\n<<<PATCHPROOF_END>>>\r\n")
        self.assertEqual(proof.parse_edit_blocks(text)["edits"], [{"path": "a.ts", "old": "x\ny", "new": ""}])

    def test_malformed_answers_say_what_is_wrong(self):
        for text, fragment in (
            ("I could not find a fix.", "holds no edit block"),
            ("<<<PATCHPROOF_FILE a.ts>>>\n<<<PATCHPROOF_OLD>>>\nx\n<<<PATCHPROOF_NEW>>>\ny\n", "ended inside an edit block"),
            ("<<<PATCHPROOF_FILE a.ts>>>\nconst x = 1;\n", "the next line must be <<<PATCHPROOF_OLD>>>"),
        ):
            with self.assertRaises(proof.PatchProofError) as caught:
                proof.parse_edit_blocks(text)
            self.assertIn(fragment, str(caught.exception))

    def test_reasoning_before_the_answer_is_dropped(self):
        answer = "<<<PATCHPROOF_FILE a.ts>>>\n<<<PATCHPROOF_OLD>>>\nx\n<<<PATCHPROOF_NEW>>>\ny\n<<<PATCHPROOF_END>>>"
        for raw in (f"<think>try x</think>\n{answer}", f"I will think.\nMore thinking.\n</think>\n{answer}"):
            self.assertEqual(proof.parse_edit_blocks(raw)["edits"][0]["new"], "y")

    def test_escape_tolerances_are_for_json_only(self):
        content = "const R = /\\b(\\d+)\\s*d/;\n"
        doubled = "const R = /\\\\b(\\\\d+)\\\\s*d/;"
        self.assertIn("doubled backslashes", proof.tolerant_edit(content, doubled, "x")[2])
        self.assertIsNone(proof.tolerant_edit(content, doubled, "x", escape_slips=False))
        root = repo(content)
        adapter = runtimes.detect_runtime(project())
        payload = {"summary": "s", "edits": [{"path": "lib/recency.ts", "old": doubled, "new": "x"}]}
        with self.assertRaises(proof.PatchProofError) as caught:
            proof.validate_candidate(payload, {"lib/recency.ts"}, root, adapter, edit_format="blocks")
        self.assertIn("Nothing is escaped in this format", str(caught.exception))
        self.assertNotIn("JSON", str(caught.exception))


class EditFormatChoiceTests(unittest.TestCase):
    def test_auto_picks_plain_text_for_backslash_heavy_code(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PATCHPROOF_EDIT_FORMAT", None)
            self.assertEqual(proof.solver_edit_format("x" * 500), "json")
            self.assertEqual(proof.solver_edit_format("\\" * (proof.BLOCKS_BACKSLASH_THRESHOLD - 1)), "json")
            self.assertEqual(proof.solver_edit_format("\\" * proof.BLOCKS_BACKSLASH_THRESHOLD), "blocks")
            self.assertEqual(ORIGINAL.count("\\"), 10)
            self.assertEqual(proof.solver_edit_format(ORIGINAL * 4), "blocks")
            self.assertEqual(proof.solver_edit_format(ORIGINAL), "json")

    def test_the_setting_overrides_and_is_checked(self):
        with patch.dict(os.environ, {"PATCHPROOF_EDIT_FORMAT": "json"}):
            self.assertEqual(proof.solver_edit_format("\\" * 500), "json")
        with patch.dict(os.environ, {"PATCHPROOF_EDIT_FORMAT": "Blocks"}):
            self.assertEqual(proof.solver_edit_format(""), "blocks")
        with patch.dict(os.environ, {"PATCHPROOF_EDIT_FORMAT": "yaml"}), self.assertRaises(proof.PatchProofError):
            proof.solver_edit_format("")


class GenerateCandidateFormatTests(unittest.TestCase):
    def call(self, fmt: str, text_reply: str = "", json_reply: dict | None = None, thinking: str = "0"):
        root = repo()
        adapter = runtimes.detect_runtime(project())
        seen: dict = {}

        def fake_text(**kwargs):
            seen["text"] = kwargs
            return text_reply

        def fake_json(**kwargs):
            seen["json"] = kwargs
            return json_reply

        env = {"PATCHPROOF_EDIT_FORMAT": fmt, "PATCHPROOF_SOLVER_THINKING": thinking}
        with patch.object(proof, "model_text", side_effect=fake_text), \
                patch.object(proof, "model_json", side_effect=fake_json), patch.dict(os.environ, env):
            record: dict = {"candidate": 1}
            changes, summary = proof.generate_candidate_with_retry(
                candidate_record=record, issue=proof.Issue(1, "t", "b"), context="CTX",
                allowed_source_paths={"lib/recency.ts"}, api_key="k", model="m", root=root, adapter=adapter,
                strategy="s", temperature=0.2)
        return seen, changes, summary, record

    def test_blocks_mode_asks_for_plain_text_and_applies_the_edits(self):
        seen, changes, summary, record = self.call("blocks", EDIT_ANSWER)
        self.assertNotIn("json", seen)
        system = seen["text"]["system"]
        self.assertIn("<<<PATCHPROOF_OLD>>>", system)
        self.assertNotIn("Return only JSON", system)
        self.assertIn("a backslash is ONE backslash", system)
        self.assertNotIn("requested JSON object", system)
        self.assertNotIn("thinking", seen["text"])
        self.assertEqual(record["edit_format"], "blocks")
        self.assertTrue(summary.startswith("Accept a/an"))
        self.assertIn("an?", changes[0]["content"])

    def test_json_mode_is_the_rc44_prompt(self):
        payload = {"summary": "s", "edits": [{"path": "lib/recency.ts", "old": "(match[2] ? 1 : 0)", "new": "(match[2] ? 2 : 0)"}]}
        seen, changes, _, record = self.call("json", json_reply=payload)
        self.assertNotIn("text", seen)
        self.assertIn("Return only JSON", seen["json"]["system"])
        self.assertEqual(record["edit_format"], "json")

    def test_a_malformed_plain_text_answer_is_retried_with_the_reason(self):
        root = repo()
        adapter = runtimes.detect_runtime(project())
        replies = iter(["no blocks here", EDIT_ANSWER])
        feedback: list[str] = []

        def fake_text(**kwargs):
            feedback.append(kwargs["user"])
            return next(replies)

        with patch.object(proof, "model_text", side_effect=fake_text), patch.dict(
                os.environ, {"PATCHPROOF_EDIT_FORMAT": "blocks"}):
            record: dict = {"candidate": 1}
            proof.generate_candidate_with_retry(
                candidate_record=record, issue=proof.Issue(1, "t", "b"), context="CTX",
                allowed_source_paths={"lib/recency.ts"}, api_key="k", model="m", root=root, adapter=adapter,
                strategy="s", temperature=0.2)
        self.assertEqual(len(feedback), 2)
        self.assertIn("holds no edit block", feedback[1])
        self.assertEqual(len(record["generation_errors"]), 1)

    def test_thinking_is_passed_only_when_switched_on(self):
        seen, *_ = self.call("blocks", EDIT_ANSWER, thinking="1")
        self.assertIs(seen["text"]["thinking"], True)
        seen, *_ = self.call("blocks", EDIT_ANSWER, thinking="0")
        self.assertNotIn("thinking", seen["text"])


class SolverThinkingTests(unittest.TestCase):
    NEMOTRON = "nvidia/nemotron-3-super-120b-a12b"

    def test_the_request_silences_reasoning_unless_thinking_is_asked_for(self):
        quiet = proof.build_model_request(model=self.NEMOTRON, system="s", user="u", temperature=0.3, max_tokens=12000)
        self.assertIs(quiet["extra_body"]["chat_template_kwargs"]["enable_thinking"], False)
        loud = proof.build_model_request(model=self.NEMOTRON, system="s", user="u", temperature=0.3, max_tokens=12000,
                                         thinking=True)
        self.assertIs(loud["extra_body"]["chat_template_kwargs"]["enable_thinking"], True)
        other = proof.build_model_request(model="some/model", system="s", user="u", temperature=0.3, max_tokens=12000,
                                          thinking=True)
        self.assertNotIn("extra_body", other)

    def test_the_switch(self):
        for value, expected in (("1", True), ("true", True), ("On", True), ("0", False), ("false", False), ("", False)):
            with patch.dict(os.environ, {"PATCHPROOF_SOLVER_THINKING": value}):
                self.assertIs(proof.solver_thinking_from_env(), expected)

    def test_reasoning_that_only_has_a_closing_tag_is_dropped(self):
        self.assertEqual(proof._strip_reasoning("Let me think about it.\n</think>\nthe answer"), "the answer")
        self.assertEqual(proof._strip_reasoning("<think>a</think>\n<think>b</think>\nfinal"), "final")
        self.assertEqual(proof._strip_reasoning("  plain answer  "), "plain answer")
        with self.assertRaises(proof.PatchProofError):
            proof._strip_reasoning("<think>never closed")

    def test_a_thinking_request_gets_a_larger_budget_and_a_longer_timeout(self):
        created: dict = {}

        class Client:
            chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: created.setdefault("request", kwargs) and SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                    content="the answer", refusal=None, reasoning_content=None))],
                usage=SimpleNamespace(completion_tokens=5, completion_tokens_details={"reasoning_tokens": 3}))))

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        def make(**kwargs):
            created["client"] = kwargs
            return Client()

        with patch("openai.OpenAI", side_effect=make), patch.dict(os.environ, {"NEBIUS_MAX_TOKENS": "12000"}):
            self.assertEqual(proof.model_text(api_key="k", model=self.NEMOTRON, system="s", user="u", temperature=0.2,
                                              thinking=True), "the answer")
        self.assertEqual(created["request"]["max_tokens"], proof.SOLVER_THINKING_MIN_TOKENS)
        self.assertEqual(created["client"]["timeout"], 900.0)
        created.clear()
        with patch("openai.OpenAI", side_effect=make), patch.dict(os.environ, {"NEBIUS_MAX_TOKENS": "12000"}):
            proof.model_text(api_key="k", model=self.NEMOTRON, system="s", user="u", temperature=0.2)
        self.assertEqual(created["request"]["max_tokens"], 12000)
        self.assertEqual(created["client"]["timeout"], 300.0)


if __name__ == "__main__":
    unittest.main()
