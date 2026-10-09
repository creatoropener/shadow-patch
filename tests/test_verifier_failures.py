from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import contextlib
import io
from types import SimpleNamespace

from proof import (InferenceError, Issue, PatchProofError, RATIONALE_BEGIN,
                   RATIONALE_END, TEST_BEGIN, TEST_END, build_model_request,
                   classify_reproduction, extract_json_object,
                   generate_regression_test, generate_regression_with_retry,
                   model_json, model_text, parse_verifier_blocks,
                   repeated_failure_feedback, reproduction_feedback)
from runtimes import _node_assertion_failure, detect_runtime

FIXTURES = Path(__file__).parent / "fixtures"
LINTER = Path(__file__).resolve().parents[1] / "patchproof_runtime/typescript_test_lint.mjs"


# rc.24: node-package and static-web tests now go through the same missing-import check as
# node-typescript, so the stand-in body `test();` that these retry tests used for a
# generation that must be ACCEPTED is replaced by a minimal file that really imports `test`.
VALID_NODE_TEST = "import test from 'node:test';\ntest('x', () => {});"


def marked(test: str, rationale: str = "Regression.") -> str:
    """A well-formed verifier response in the rc.20 marker format."""
    return (f"{TEST_BEGIN}\n{test}\n{TEST_END}\n"
            f"{RATIONALE_BEGIN}\n{rationale}\n{RATIONALE_END}\n")


class SolverJsonParsingTests(unittest.TestCase):
    """Solver candidates still travel as JSON; the strict parser is unchanged."""

    def test_accepts_exact_json_and_complete_fence(self):
        payload = {"summary": "s", "edits": []}
        for text in (json.dumps(payload), "```json\n" + json.dumps(payload) + "\n```"):
            self.assertEqual(extract_json_object(text), payload)

    def test_rejects_ambiguous_or_non_object_json(self):
        for text in ('{} {}', '{} trailing', 'prefix {}', '[]', 'null',
                     '{"x":1,"x":2}', '{"x":NaN}',
                     '```json\n{}\n```\ntrailing'):
            with self.subTest(text=text), self.assertRaises(PatchProofError):
                extract_json_object(text)


class VerifierMarkerParserTests(unittest.TestCase):
    def test_accepts_well_formed_response(self):
        self.assertEqual(parse_verifier_blocks(marked("test();")),
                         ("test();", "Regression."))

    def test_source_is_byte_exact_with_no_escape_layer(self):
        # The point of the transport: backslashes, quotes, control-character
        # text and template literals reach the test file untouched.
        source = (
            "import test from 'node:test';\n"
            "const a = 'x\\;y\\,z';\n"
            "const b = String.raw`C:\\path\\n \\r\\n \"q\" ${1}`;\n"
            "const c = \"tab\\there\";\n"
        )
        test, _ = parse_verifier_blocks(marked(source))
        self.assertEqual(test, source)
        # A JSON round trip would have needed a second layer of escaping.
        self.assertNotEqual(json.dumps(source)[1:-1], source)

    def test_accepts_rationale_first_and_blank_lines_between_blocks(self):
        text = (f"\n{RATIONALE_BEGIN}\nWhy.\n{RATIONALE_END}\n\n\n"
                f"{TEST_BEGIN}\ntest();\n{TEST_END}\n")
        self.assertEqual(parse_verifier_blocks(text), ("test();", "Why."))

    def test_accepts_crlf_after_begin_marker_and_reasoning_prefix(self):
        text = "<think>plan</think>\n" + marked("test();").replace("\n", "\r\n")
        self.assertEqual(parse_verifier_blocks(text), ("test();", "Regression."))

    def test_preserves_internal_indentation_and_blank_lines(self):
        source = "test('a', () => {\n\n    nested();\n\n});"
        test, _ = parse_verifier_blocks(marked(source))
        self.assertEqual(test, source)

    def test_rejects_every_missing_marker(self):
        good = marked("test();")
        for marker in (TEST_BEGIN, TEST_END, RATIONALE_BEGIN, RATIONALE_END):
            with self.subTest(marker=marker):
                with self.assertRaises(PatchProofError) as raised:
                    parse_verifier_blocks(good.replace(marker, "", 1))
                self.assertIn(marker, str(raised.exception))
                self.assertIn("exactly once", str(raised.exception))

    def test_rejects_every_duplicated_marker(self):
        good = marked("test();")
        for marker in (TEST_BEGIN, TEST_END, RATIONALE_BEGIN, RATIONALE_END):
            with self.subTest(marker=marker), self.assertRaises(PatchProofError) as raised:
                parse_verifier_blocks(good + marker + "\n")
            self.assertIn("found 2", str(raised.exception))

    def test_rejects_marker_text_inside_the_source(self):
        with self.assertRaises(PatchProofError):
            parse_verifier_blocks(marked(f"const s = '{TEST_END}';"))

    def test_rejects_swapped_nested_and_interleaved_blocks(self):
        cases = {
            "end before begin": f"{TEST_END}\nx\n{TEST_BEGIN}\n{RATIONALE_BEGIN}\nr\n{RATIONALE_END}",
            "nested": f"{TEST_BEGIN}\n{RATIONALE_BEGIN}\nr\n{RATIONALE_END}\nx\n{TEST_END}",
            "interleaved": f"{TEST_BEGIN}\nx\n{RATIONALE_BEGIN}\n{TEST_END}\nr\n{RATIONALE_END}",
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(PatchProofError):
                parse_verifier_blocks(text)

    def test_rejects_text_outside_the_blocks(self):
        for text in ("Here is the test:\n" + marked("test();"),
                     marked("test();") + "Hope this helps.",
                     marked("test();").replace(f"{TEST_END}\n", f"{TEST_END}\nnote\n")):
            with self.subTest(text=text[:30]), self.assertRaises(PatchProofError) as raised:
                parse_verifier_blocks(text)
            self.assertIn("outside the marked blocks", str(raised.exception))

    def test_rejects_markdown_fenced_source_and_empty_blocks(self):
        for text in (marked("```ts\ntest();\n```"), marked(""), marked("test();", " "),
                     json.dumps({"test_content": "x", "rationale": "y"})):
            with self.subTest(text=text[:30]), self.assertRaises(PatchProofError):
                parse_verifier_blocks(text)

    def test_unclosed_reasoning_is_not_an_answer(self):
        with self.assertRaises(PatchProofError):
            parse_verifier_blocks("<think>never closes " + marked("test();"))

    def test_malformed_response_retries_with_actionable_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            with patch('proof.model_text', side_effect=[
                json.dumps({"test_content": "test();", "rationale": "r"}),
                marked(VALID_NODE_TEST, "Expected behavior."),
            ]) as model:
                content, rationale = generate_regression_with_retry(
                    issue=Issue(3, "Round trip", "Preserve input"), context="",
                    api_key="unused", model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.mjs")
                self.assertEqual(content, VALID_NODE_TEST + "\n")
                self.assertEqual(rationale, "Expected behavior.")
                retry_user = model.call_args.kwargs["user"]
                self.assertIn("exactly once", retry_user)
                self.assertIn(TEST_BEGIN, retry_user)


class GenerationDiagnosticLoggingTests(unittest.TestCase):
    """rc.9: a rejected generation-stage attempt used to leave no trace of what
    the model actually returned. These reproduce the real proof.json #3 run
    (schema violation on the third attempt) and check the fix directly."""

    def make_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            yield detect_runtime(root)

    def test_malformed_response_logs_head_and_tail_preview(self):
        # Mirrors the earlier real rc.9 case (a response the parser rejects):
        # the run log must show what the model actually returned.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            raw = "PREAMBLE_TEXT\n" + marked("test();") + "TRAILING_NOTE"
            buffer = io.StringIO()
            with patch('proof.model_text', return_value=raw), \
                 contextlib.redirect_stderr(buffer), \
                 self.assertRaises(PatchProofError):
                generate_regression_test(
                    issue=Issue(3, "t", "b"), context="", api_key="unused",
                    model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.mjs")
            logged = buffer.getvalue()
            self.assertIn("Verifier response rejected", logged)
            self.assertIn("outside the marked blocks", logged)
            self.assertIn("PREAMBLE_TEXT", logged)
            self.assertIn("TRAILING_NOTE", logged)

    def test_preview_is_bounded_for_huge_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            raw = "A" * 300 + "MIDDLE" + "Z" * 300
            buffer = io.StringIO()
            with patch('proof.model_text', return_value=raw), \
                 contextlib.redirect_stderr(buffer), \
                 self.assertRaises(PatchProofError):
                generate_regression_test(
                    issue=Issue(3, "t", "b"), context="", api_key="unused",
                    model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.mjs")
            logged = buffer.getvalue()
            self.assertNotIn("MIDDLE", logged)
            self.assertIn("len=606", logged)

    def test_content_violation_logs_prefix_and_attaches_it_to_the_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            (root / "tsconfig.json").write_text("{}\n")
            adapter = detect_runtime(root)
            bad_source = (FIXTURES / "missing_node_test_import.test.ts").read_text(encoding="utf-8")
            raw = marked(bad_source, "Round trip.")
            buffer = io.StringIO()
            with patch('proof.model_text', return_value=raw), \
                 contextlib.redirect_stderr(buffer), \
                 self.assertRaises(PatchProofError) as raised:
                generate_regression_test(
                    issue=Issue(3, "t", "b"), context="", api_key="unused",
                    model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.ts")
            logged = buffer.getvalue()
            self.assertIn("Verifier test_content rejected", logged)
            self.assertIn(bad_source[:50], logged)
            self.assertEqual(raised.exception.rejected_content, bad_source.replace("file:///patchproof/web_streams.mjs", "./patchproof_helpers/web_streams.mjs"))


class NemotronFamilyDetectionTests(unittest.TestCase):
    """rc.11: an exact-string allowlist needed a perfect-casing guess for
    every new Nemotron sibling tried (Nano, Lightning, and Ultra have each
    used a different capitalization/format). Matching on the family name
    instead means the next one tried -- e.g. a Super tier -- is covered
    without hardcoding its exact id first, and without a silent miss."""

    def test_known_models_are_still_recognised_regardless_of_casing(self):
        for model in (
            "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
            "NVIDIA/nvidia-nemotron-3-nano-30b-a3b",
            "nvidia/Nemotron-3_5-Lightning",
            "nvidia/NEMOTRON-3_5-LIGHTNING",
            "nvidia/Nemotron-3-Ultra-550b-a55b",
        ):
            with self.subTest(model=model):
                request = build_model_request(
                    model=model, system="s", user="u", temperature=0.1,
                    max_tokens=12000)
                self.assertEqual(
                    request["extra_body"]["chat_template_kwargs"]["enable_thinking"],
                    False)

    def test_an_untried_nemotron_sibling_is_covered_without_a_code_change(self):
        # A plausible next model (exact id unconfirmed) still gets the toggle.
        request = build_model_request(
            model="nvidia/Nemotron-3-Super-120b-a12b", system="s", user="u",
            temperature=0.25, max_tokens=12000)
        self.assertEqual(
            request["extra_body"]["chat_template_kwargs"]["enable_thinking"], False)
        self.assertEqual(request["temperature"], 0.25)  # no tuning history: unchanged
        self.assertNotIn("top_p", request)

    def test_tuned_overrides_still_apply_regardless_of_casing(self):
        lightning = build_model_request(
            model="NVIDIA/NEMOTRON-3_5-LIGHTNING", system="s", user="u",
            temperature=0.1, max_tokens=12000)
        self.assertEqual(lightning["temperature"], 1.0)
        self.assertEqual(lightning["top_p"], 0.95)

        nano = build_model_request(
            model="nvidia/nvidia-nemotron-3-nano-30b-a3b", system="s", user="u",
            temperature=0.1, max_tokens=12000)
        self.assertEqual(nano["temperature"], 0.0)
        self.assertNotIn("top_p", nano)

    def test_a_non_nemotron_model_is_untouched(self):
        request = build_model_request(
            model="deepseek-ai/DeepSeek-V3.2", system="s", user="u",
            temperature=0.42, max_tokens=12000)
        self.assertNotIn("extra_body", request)
        self.assertEqual(request["temperature"], 0.42)


class TruncatedResponseLoggingTests(unittest.TestCase):
    """rc.11: a response rejected for finish_reason=length was discarded
    with no trace of its actual content. Built from a real Issue #3 run
    where a non-reasoning-budget answer alone used the full 32,000-token
    ceiling (final_chars=36,470) and still didn't finish."""

    class _FakeChoice:
        def __init__(self, content, finish_reason):
            self.finish_reason = finish_reason
            self.message = SimpleNamespace(content=content, refusal=None,
                                           reasoning_content=None)

    class _FakeResponse:
        def __init__(self, content, finish_reason):
            self.choices = [TruncatedResponseLoggingTests._FakeChoice(content, finish_reason)]
            self.usage = SimpleNamespace(
                completion_tokens=32000,
                completion_tokens_details={"reasoning_tokens": 0})

    class _FakeClient:
        def __init__(self, response):
            self._response = response
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            return self._response

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def test_length_rejection_logs_head_and_tail_of_what_was_generated(self):
        long_content = "A" * 300 + "MIDDLE" + "Z" * 300
        response = self._FakeResponse(long_content, "length")
        buffer = io.StringIO()
        with patch("openai.OpenAI", return_value=self._FakeClient(response)), \
             patch.dict(os.environ, {"NEBIUS_MAX_TOKENS": "32000"}), \
             contextlib.redirect_stderr(buffer), \
             self.assertRaises(InferenceError) as raised:
            model_json(api_key="x", model="nvidia/Nemotron-3-Ultra-550b-a55b",
                      system="s", user="u", temperature=0.1)
        logged = buffer.getvalue()
        self.assertIn("Truncated response preview", logged)
        self.assertIn("A" * 200, logged)
        self.assertIn("Z" * 200, logged)
        self.assertNotIn("MIDDLE", logged)  # only head/tail are shown, not the middle
        self.assertIn("Review NEBIUS_MAX_TOKENS", str(raised.exception))

    def test_short_truncated_content_logs_without_a_separate_tail(self):
        response = self._FakeResponse("short", "length")
        buffer = io.StringIO()
        with patch("openai.OpenAI", return_value=self._FakeClient(response)), \
             patch.dict(os.environ, {"NEBIUS_MAX_TOKENS": "12000"}), \
             contextlib.redirect_stderr(buffer), \
             self.assertRaises(InferenceError):
            model_json(api_key="x", model="some/model", system="s", user="u",
                      temperature=0.1)
        self.assertIn("head[0:200]='short'", buffer.getvalue())


class RepeatedFailureEscalationTests(unittest.TestCase):
    """rc.9: an identical diagnosis twice in a row now shows the model its own
    rejected content instead of repeating the same paragraph a third time."""

    def test_helper_includes_diagnosis_and_verbatim_previous_content(self):
        feedback = repeated_failure_feedback("some diagnosis", "const x = 1;")
        self.assertIn("second attempt in a row", feedback)
        self.assertIn("some diagnosis", feedback)
        self.assertIn("const x = 1;", feedback)

    def test_helper_without_content_still_names_the_repeat(self):
        feedback = repeated_failure_feedback("some diagnosis", None)
        self.assertIn("second attempt in a row", feedback)
        self.assertNotIn("```", feedback)

    def test_first_failure_is_not_treated_as_a_repeat(self):
        # Single occurrence of a diagnosis (the existing rc.8 schema test's shape)
        # must not trigger escalation -- only a second, identical one does.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            with patch('proof.model_text', side_effect=[
                f"{TEST_BEGIN}\ntest();\n{TEST_END}\n",
                marked(VALID_NODE_TEST, "Expected behavior."),
            ]) as model:
                generate_regression_with_retry(
                    issue=Issue(3, "Round trip", "Preserve input"), context="",
                    api_key="unused", model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.mjs")
                second_call_user = model.call_args_list[1].kwargs["user"]
                self.assertNotIn("second attempt in a row", second_call_user)

    def test_real_run_shape_two_identical_then_a_different_diagnosis(self):
        # Reconstructs proof.json's actual sequence: the same missing-success-guard
        # violation twice (different content, same rule), then an unrelated schema
        # violation. Verifies the SECOND call is escalated with the FIRST call's
        # own rejected content, and the THIRD call is not (its diagnosis differs).
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            (root / "tsconfig.json").write_text("{}\n")
            adapter = detect_runtime(root)
            missing_guard_source_1 = (
                "import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
                "import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';\n"
                "test('a', async () => {\n"
                "  const encoded = await collectBytes(readableFromBytes(input, 8).pipeThrough(forward));\n"
                "  const decoded = await collectBytes(readableFromBytes(encoded, 8).pipeThrough(inverse));\n"
                "  assert.deepStrictEqual(decoded, input);\n"
                "});\n"
            )
            missing_guard_source_2 = missing_guard_source_1.replace("test('a'", "test('b'")
            valid_source = (
                "import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
                "import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';\n"
                "test('c', async () => {\n"
                "  await assert.doesNotReject(async () => {\n"
                "    const encoded = await collectBytes(readableFromBytes(input, 8).pipeThrough(forward));\n"
                "    const decoded = await collectBytes(readableFromBytes(encoded, 8).pipeThrough(inverse));\n"
                "    assert.deepStrictEqual(decoded, input);\n"
                "  });\n"
                "});\n"
            )
            with patch('proof.model_text', side_effect=[
                marked(missing_guard_source_1, "r1"),
                marked(missing_guard_source_2, "r2"),
                f"{TEST_BEGIN}\n{valid_source}\n{TEST_END}\n",  # rationale block missing
            ]) as model:
                with self.assertRaises(PatchProofError) as raised:
                    generate_regression_with_retry(
                        issue=Issue(3, "t", "b"), context="", api_key="unused",
                        model="unused", adapter=adapter,
                        test_path="test_patchproof_issue_3.test.ts")
            self.assertIn(f"marker {RATIONALE_BEGIN} exactly once", str(raised.exception))
            second_call_user = model.call_args_list[1].kwargs["user"]
            self.assertNotIn("second attempt in a row", second_call_user)
            third_call_user = model.call_args_list[2].kwargs["user"]
            self.assertIn("second attempt in a row", third_call_user)
            self.assertIn("doesNotReject", third_call_user)
            # The concrete example shown back is attempt 2's own content, not attempt 1's.
            self.assertIn("test('b'", third_call_user)
            self.assertNotIn("test('a'", third_call_user)


class ModelRequestThinkingToggleTests(unittest.TestCase):
    """rc.10: nvidia/Nemotron-3-Ultra-550b-a55b joined the engine's model
    lineup and, unlike the two smaller Nemotron models already special-cased
    here, was not told to keep its reasoning off. On a retry it spent 11,161
    of a 12,000-token budget on hidden reasoning and was rejected on
    finish_reason=length with almost nothing left for the actual answer."""

    def test_ultra_550b_gets_thinking_disabled(self):
        request = build_model_request(
            model="nvidia/Nemotron-3-Ultra-550b-a55b", system="s", user="u",
            temperature=0.1, max_tokens=12000)
        self.assertEqual(
            request["extra_body"]["chat_template_kwargs"]["enable_thinking"], False)

    def test_ultra_550b_temperature_is_left_to_the_caller(self):
        # No prior tuning history for this model exists (unlike its two
        # siblings below); only its runaway reasoning is being addressed.
        request = build_model_request(
            model="nvidia/Nemotron-3-Ultra-550b-a55b", system="s", user="u",
            temperature=0.37, max_tokens=12000)
        self.assertEqual(request["temperature"], 0.37)
        self.assertNotIn("top_p", request)

    def test_existing_lightning_and_nano_overrides_are_unchanged(self):
        lightning = build_model_request(
            model="nvidia/Nemotron-3_5-Lightning", system="s", user="u",
            temperature=0.1, max_tokens=12000)
        self.assertEqual(lightning["temperature"], 1.0)
        self.assertEqual(lightning["top_p"], 0.95)
        self.assertEqual(
            lightning["extra_body"]["chat_template_kwargs"]["enable_thinking"], False)

        nano = build_model_request(
            model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", system="s", user="u",
            temperature=0.1, max_tokens=12000)
        self.assertEqual(nano["temperature"], 0.0)
        self.assertNotIn("top_p", nano)
        self.assertEqual(
            nano["extra_body"]["chat_template_kwargs"]["enable_thinking"], False)

    def test_an_unlisted_model_gets_no_overrides(self):
        request = build_model_request(
            model="some/other-model", system="s", user="u",
            temperature=0.42, max_tokens=12000)
        self.assertNotIn("extra_body", request)
        self.assertEqual(request["temperature"], 0.42)

    def test_request_always_carries_the_given_messages_and_budget(self):
        request = build_model_request(
            model="nvidia/Nemotron-3-Ultra-550b-a55b", system="sys prompt",
            user="user prompt", temperature=0.1, max_tokens=12000)
        self.assertEqual(request["messages"],
                         [{"role": "system", "content": "sys prompt"},
                          {"role": "user", "content": "user prompt"}])
        self.assertEqual(request["max_tokens"], 12000)


class ReproductionFailureTests(unittest.TestCase):
    def test_proof7_operational_failures_remain_rejected_with_specific_feedback(self):
        for attempt in (1, 3):
            output = (FIXTURES / f"proof7_attempt{attempt}.tap").read_text()
            self.assertFalse(_node_assertion_failure(output))
            feedback = reproduction_feedback(
                (FIXTURES / f"proof7_attempt{attempt}.test.ts").read_text(),
                "test failed without accepted assertion evidence", output)
            self.assertIn("await assert.doesNotReject(async ()", feedback)
            self.assertIn("before the final assertion ran", feedback)
            self.assertIn("Keep imports and unrelated setup outside", feedback)

    def test_parse_diagnostic_does_not_claim_unused_bindings(self):
        output = (FIXTURES / "proof7_attempt2.tap").read_text().replace(
            "PATCHPROOF_TYPESCRIPT_LINT=failed", "PATCHPROOF_TYPESCRIPT_PARSE=failed")
        feedback = reproduction_feedback("source", "syntax failure", output)
        self.assertIn("syntax error", feedback)
        self.assertIn("between the test markers", feedback)
        self.assertNotIn("JSON string fields", feedback)
        self.assertNotIn("constructed a value but never used", feedback)
        digest = output.split("PATCHPROOF_TEST_HASH_BEFORE=")[1].splitlines()[0]
        reproduced, protected, reason = classify_reproduction(None, 2, output, digest)
        self.assertEqual((reproduced, protected), (False, True))
        self.assertIn("syntax parsing", reason)

    def test_tooling_failure_does_not_claim_unused_binding(self):
        feedback = reproduction_feedback("source", "tooling failure",
                                         "PATCHPROOF_TYPESCRIPT_LINT=unavailable")
        self.assertIn("tooling/setup failure", feedback)
        self.assertNotIn("constructed a value but never used", feedback)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_real_node_tap_rejects_raw_domexception_accepts_explicit_assertion(self):
        template = """
import test from 'node:test';
import assert from 'node:assert/strict';
const operation = async () => { throw new DOMException('Operation failed', 'OperationError'); };
test('operation should succeed', async () => { BODY });
"""
        for body, accepted in (("await operation();", False),
                               ("await assert.doesNotReject(async () => { await operation(); });", True)):
            run = subprocess.run(["node", "--test-reporter=tap", "--input-type=module", "-"],
                                 input=template.replace("BODY", body), text=True,
                                 capture_output=True, timeout=15)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertEqual(_node_assertion_failure(run.stdout), accepted, run.stdout)


@unittest.skipUnless(os.environ.get("TS_LINT_NODE_MODULES"),
                     "Set TS_LINT_NODE_MODULES to installed TypeScript node_modules")
class TypeScriptLintIntegrationTests(unittest.TestCase):
    def test_actual_parser_distinguishes_syntax_unused_and_valid_source(self):
        cases = (
            ("proof7_attempt2.test.ts", "PATCHPROOF_TYPESCRIPT_PARSE=failed", 2),
            ("proof6_faulty_regression.test.ts", "PATCHPROOF_TYPESCRIPT_LINT=failed", 2),
            ("proof6_corrected_regression.test.ts", "PATCHPROOF_TYPESCRIPT_LINT=passed", 0),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{}')
            # Deliberately no root/node_modules: the linter must never resolve
            # `typescript` from the target repo. PATCHPROOF_TYPESCRIPT_RUNTIME
            # points it at a real installed TypeScript instead, the same way
            # prepare-image.yml's pinned /opt/patchproof/node does in prod.
            runtime_root = Path(directory) / "_patchproof_runtime"
            (runtime_root).mkdir()
            (runtime_root / "package.json").write_text('{}')
            (runtime_root / "node_modules").symlink_to(Path(os.environ['TS_LINT_NODE_MODULES']).resolve(),
                                              target_is_directory=True)
            env = {**os.environ, "PATCHPROOF_TYPESCRIPT_RUNTIME": str(runtime_root)}
            for fixture, marker, code in cases:
                with self.subTest(fixture=fixture):
                    (root / "generated.test.ts").write_text((FIXTURES / fixture).read_text())
                    run = subprocess.run(["node", str(LINTER), "generated.test.ts"],
                                         cwd=root, text=True, capture_output=True, timeout=30,
                                         env=env)
                    output = run.stdout + run.stderr
                    self.assertEqual(run.returncode, code, output)
                    self.assertIn(marker, output)
                    if "PARSE" in marker:
                        self.assertNotIn("PATCHPROOF_TYPESCRIPT_LINT=failed", output)


if __name__ == '__main__':
    unittest.main()


class VerifierTransportTests(unittest.TestCase):
    """rc.20: the verifier reply is plain text, so the endpoint must never be
    asked for JSON mode (it would fight the marker format), while solver
    candidates keep JSON mode."""

    class _Client:
        def __init__(self, content, finish_reason="stop"):
            self.calls = []
            self._response = SimpleNamespace(
                choices=[SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content, refusal=None,
                                            reasoning_content=None))],
                usage=SimpleNamespace(completion_tokens=10,
                                      completion_tokens_details={"reasoning_tokens": 0}))
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            self.calls.append(kwargs)
            return self._response

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def run_call(self, function, content, **extra):
        client = self._Client(content, **extra)
        with patch("openai.OpenAI", return_value=client), \
             contextlib.redirect_stderr(io.StringIO()):
            result = function(api_key="x", model="some/model", system="s",
                              user="u", temperature=0.1)
        return result, client

    def test_model_text_returns_raw_text_and_never_requests_json_mode(self):
        raw = marked("const a = 'x\\;y';")
        result, client = self.run_call(model_text, raw)
        self.assertEqual(result, raw)
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("response_format", client.calls[0])

    def test_model_json_still_requests_json_mode(self):
        result, client = self.run_call(model_json, '{"summary": "s", "edits": []}')
        self.assertEqual(result, {"summary": "s", "edits": []})
        self.assertEqual(client.calls[0]["response_format"], {"type": "json_object"})

    def test_empty_text_response_is_an_inference_failure_without_repeat_requests(self):
        client = self._Client("   ")
        with patch("openai.OpenAI", return_value=client), \
             contextlib.redirect_stderr(io.StringIO()), \
             self.assertRaises(InferenceError):
            model_text(api_key="x", model="some/model", system="s", user="u",
                       temperature=0.1)
        self.assertEqual(len(client.calls), 1)

    def test_truncated_text_response_names_text_not_json(self):
        client = self._Client("partial", finish_reason="length")
        with patch("openai.OpenAI", return_value=client), \
             contextlib.redirect_stderr(io.StringIO()), \
             self.assertRaises(InferenceError) as raised:
            model_text(api_key="x", model="some/model", system="s", user="u",
                       temperature=0.1)
        self.assertIn("final text is not accepted", str(raised.exception))

    def test_malformed_marker_text_is_not_swallowed_as_an_inference_failure(self):
        # A structurally bad reply reaches the caller intact so the retry loop
        # can return a specific diagnostic instead of aborting the run.
        result, _ = self.run_call(model_text, "no markers at all")
        with self.assertRaises(PatchProofError) as raised:
            parse_verifier_blocks(result)
        self.assertNotIsInstance(raised.exception, InferenceError)
