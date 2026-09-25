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

from proof import (InferenceError, Issue, PatchProofError, build_model_request,
                   classify_reproduction, extract_json_object,
                   generate_regression_test, generate_regression_with_retry,
                   model_json, repeated_failure_feedback, reproduction_feedback,
                   validate_verifier_payload)
from runtimes import _node_assertion_failure, detect_runtime

FIXTURES = Path(__file__).parent / "fixtures"
LINTER = Path(__file__).resolve().parents[1] / "patchproof_runtime/typescript_test_lint.mjs"


class VerifierPayloadTests(unittest.TestCase):
    def test_accepts_exact_json_and_complete_fence(self):
        payload = {"test_content": "test();", "rationale": "Regression."}
        for text in (json.dumps(payload), "```json\n" + json.dumps(payload) + "\n```"):
            self.assertEqual(validate_verifier_payload(extract_json_object(text)),
                             ("test();", "Regression."))

    def test_rejects_ambiguous_or_non_object_json(self):
        for text in ('{} {}', '{} trailing', 'prefix {}', '[]', 'null',
                     '{"x":1,"x":2}', '{"x":NaN}',
                     '```json\n{}\n```\ntrailing'):
            with self.subTest(text=text), self.assertRaises(PatchProofError):
                extract_json_object(text)

    def test_requires_separate_nonempty_string_fields(self):
        for payload in (None, [], {"test_content": "source"},
                        {"test_content": "source", "rationale": None},
                        {"test_content": 1, "rationale": "reason"},
                        {"test_content": "source", "rationale": " "},
                        {"test_content": "source", "rationale": "reason", "extra": 1}):
            with self.subTest(payload=payload), self.assertRaises(PatchProofError):
                validate_verifier_payload(payload)

    def test_schema_rejection_retries_with_actionable_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            with patch('proof.model_json', side_effect=[
                {"test_content": "test();"},
                {"test_content": "test();", "rationale": "Expected behavior."},
            ]) as model:
                content, rationale = generate_regression_with_retry(
                    issue=Issue(3, "Round trip", "Preserve input"), context="",
                    api_key="unused", model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.mjs")
                self.assertEqual(content, "test();\n")
                self.assertEqual(rationale, "Expected behavior.")
                self.assertIn("Keep rationale outside test_content",
                              model.call_args.kwargs["user"])


class GenerationDiagnosticLoggingTests(unittest.TestCase):
    """rc.9: a rejected generation-stage attempt used to leave no trace of what
    the model actually returned. These reproduce the real proof.json #3 run
    (schema violation on the third attempt) and check the fix directly."""

    def make_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            yield detect_runtime(root)

    def test_schema_violation_logs_all_returned_keys(self):
        # Mirrors the real attempt 3: an extra field alongside the two required ones.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            payload = {"test_content": "test();", "rationale": "Regression.",
                      "notes": "unexpected extra field"}
            buffer = io.StringIO()
            with patch('proof.model_json', return_value=payload), \
                 contextlib.redirect_stderr(buffer), \
                 self.assertRaises(PatchProofError):
                generate_regression_test(
                    issue=Issue(3, "t", "b"), context="", api_key="unused",
                    model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.mjs")
            logged = buffer.getvalue()
            self.assertIn("Verifier payload rejected", logged)
            self.assertIn("'test_content'", logged)
            self.assertIn("'rationale'", logged)
            self.assertIn("'notes'", logged)

    def test_content_violation_logs_prefix_and_attaches_it_to_the_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text('{"scripts":{"test":"node --test"}}')
            (root / "tsconfig.json").write_text("{}\n")
            adapter = detect_runtime(root)
            bad_source = (FIXTURES / "missing_node_test_import.test.ts").read_text(encoding="utf-8")
            payload = {"test_content": bad_source, "rationale": "Round trip."}
            buffer = io.StringIO()
            with patch('proof.model_json', return_value=payload), \
                 contextlib.redirect_stderr(buffer), \
                 self.assertRaises(PatchProofError) as raised:
                generate_regression_test(
                    issue=Issue(3, "t", "b"), context="", api_key="unused",
                    model="unused", adapter=adapter,
                    test_path="test_patchproof_issue_3.test.ts")
            logged = buffer.getvalue()
            self.assertIn("Verifier test_content rejected", logged)
            self.assertIn(bad_source[:50], logged)
            self.assertEqual(raised.exception.rejected_content, bad_source)


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
            with patch('proof.model_json', side_effect=[
                {"test_content": "test();"},
                {"test_content": "test();", "rationale": "Expected behavior."},
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
            with patch('proof.model_json', side_effect=[
                {"test_content": missing_guard_source_1, "rationale": "r1"},
                {"test_content": missing_guard_source_2, "rationale": "r2"},
                {"test_content": valid_source, "extra": "field"},
            ]) as model:
                with self.assertRaises(PatchProofError) as raised:
                    generate_regression_with_retry(
                        issue=Issue(3, "t", "b"), context="", api_key="unused",
                        model="unused", adapter=adapter,
                        test_path="test_patchproof_issue_3.test.ts")
            self.assertIn("test_content and rationale as separate JSON",
                          str(raised.exception))
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
        self.assertIn("separate JSON string fields", feedback)
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
            (root / "node_modules").symlink_to(Path(os.environ['TS_LINT_NODE_MODULES']).resolve(),
                                              target_is_directory=True)
            for fixture, marker, code in cases:
                with self.subTest(fixture=fixture):
                    (root / "generated.test.ts").write_text((FIXTURES / fixture).read_text())
                    run = subprocess.run(["node", str(LINTER), "generated.test.ts"],
                                         cwd=root, text=True, capture_output=True, timeout=30)
                    output = run.stdout + run.stderr
                    self.assertEqual(run.returncode, code, output)
                    self.assertIn(marker, output)
                    if "PARSE" in marker:
                        self.assertNotIn("PATCHPROOF_TYPESCRIPT_LINT=failed", output)


if __name__ == '__main__':
    unittest.main()
