from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from proof import (Issue, PatchProofError, classify_reproduction, extract_json_object,
                   generate_regression_with_retry, reproduction_feedback,
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
