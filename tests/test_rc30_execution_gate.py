"""rc.30: static rejections do not use execution attempts; repeated invalid output stops the run."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import proof
from runtimes import detect_runtime
from tests import support_pipeline as pipeline


class RepeatGuardTests(unittest.TestCase):
    def test_counts_only_consecutive_repeats(self):
        guard = proof.RepeatGuard(limit=3)
        self.assertEqual([guard.note("a"), guard.note("a"), guard.note("b"), guard.note("b"), guard.note("b")], [1, 2, 1, 2, 3])
        self.assertTrue(guard.exceeded())

    def test_signature_ignores_positions_and_digits_but_not_the_mistake(self):
        one = proof.diagnostic_signature("generated TypeScript regression failed syntax parsing",
                                         "tests/t.ts:12:5: Unterminated string literal.\nPATCHPROOF_TYPESCRIPT_PARSE=failed")
        two = proof.diagnostic_signature("generated TypeScript regression failed syntax parsing",
                                         "tests/t.ts:40:9: Unterminated string literal.\nPATCHPROOF_TYPESCRIPT_PARSE=failed")
        other = proof.diagnostic_signature("generated TypeScript regression failed syntax parsing",
                                           "tests/t.ts:12:5: Variable declaration expected.\nPATCHPROOF_TYPESCRIPT_PARSE=failed")
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)


class SyntaxDiagnosticTests(unittest.TestCase):
    SOURCE = "import test from 'node:test';\ntest('x', () => {\n  const s = 'abc;\n});\n"

    def test_typescript_parser_lines_are_located_in_the_source(self):
        output = "tests/t.ts:3:13: Unterminated string literal.\nPATCHPROOF_TYPESCRIPT_PARSE=failed"
        text = proof.describe_syntax_errors(self.SOURCE, output)
        self.assertIn("line 3, column 13: Unterminated string literal.", text)
        self.assertIn("3:   const s = 'abc;", text)
        self.assertIn("^", text)
        self.assertIn("check the quoting", text)

    def test_node_check_output_is_located_too(self):
        output = "/work/tests/t.mjs:3\n  const s = ;\n            ^\n\nSyntaxError: Unexpected token ';'\n    at checkSyntax\n"
        text = proof.describe_syntax_errors("a\nb\n  const s = ;\n", output)
        self.assertIn("line 3: Unexpected token ';'", text)
        self.assertIn("3:   const s = ;", text)

    def test_nothing_is_added_when_no_parser_line_is_present(self):
        self.assertEqual(proof.describe_syntax_errors("x", "AssertionError: boom"), "")

    def test_feedback_for_a_parse_failure_carries_the_located_error(self):
        output = "tests/t.ts:3:13: Unterminated string literal.\nPATCHPROOF_TYPESCRIPT_PARSE=failed"
        feedback = proof.reproduction_feedback(self.SOURCE, "generated TypeScript regression failed syntax parsing", output)
        self.assertIn("line 3, column 13", feedback)
        self.assertIn("before any test ran", feedback)

    def test_js_parse_marker_is_a_static_rejection(self):
        adapter = SimpleNamespace(is_regression_failure=lambda *a: False)
        digest = "0" * 64
        output = f"x\nPATCHPROOF_JS_PARSE=failed\nPATCHPROOF_TEST_HASH_BEFORE={digest}\nPATCHPROOF_TEST_HASH_AFTER={digest}\n"
        self.assertEqual(proof.classify_reproduction(adapter, 2, output, digest),
                         (False, True, "generated JavaScript regression failed syntax parsing"))


class JavaScriptSyntaxGateTests(unittest.TestCase):
    """node-package and static-web tests are parsed before they run."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jsgate-"))
        (self.root / "package.json").write_text(json.dumps({"type": "module", "scripts": {"test": "node --test"}}))
        self.adapter = detect_runtime(self.root)
        self.assertEqual(self.adapter.id, "node-package")

    def run_wrapped(self, content):
        path = self.adapter.test_path(1, root=self.root)
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

        class Local:
            def run(self_inner, *, shell, cwd, timeout, disposable):
                done = subprocess.run(shell, shell=True, cwd=self.root, capture_output=True, text=True, executable="/bin/bash")
                state = SimpleNamespace(exit_code=done.returncode, stdout=done.stdout, stderr=done.stderr, uuid="local")
                return SimpleNamespace(wait=lambda: state)

        result = proof.run_protected_tests(Local(), path, self.adapter.regression_command(path))
        return result, proof.text_output(result), proof.sha256_text(content)

    def test_syntax_error_stops_before_the_test_runs_and_keeps_the_hash_markers(self):
        content = "import test from 'node:test';\nconst x = ;\ntest('a', () => {});\n"
        result, output, digest = self.run_wrapped(content)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("PATCHPROOF_JS_PARSE=failed", output)
        self.assertIn("SyntaxError", output)
        reproduced, protected, classification = proof.classify_reproduction(self.adapter, result.exit_code, output, digest)
        self.assertEqual((reproduced, protected), (False, True))  # integrity markers survived the early stop
        self.assertEqual(classification, "generated JavaScript regression failed syntax parsing")
        self.assertIn("line 2", proof.describe_syntax_errors(content, output))

    def test_valid_file_still_runs_and_an_assertion_failure_is_still_accepted(self):
        content = ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
                   "test('a', () => { assert.equal(1, 2); });\n")
        result, output, digest = self.run_wrapped(content)
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn("PATCHPROOF_JS_PARSE", output)
        self.assertEqual(proof.classify_reproduction(self.adapter, result.exit_code, output, digest),
                         (True, True, "accepted assertion failure reproduced the issue"))


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class StaticRejectionPipelineTests(unittest.TestCase):
    HEAD = "import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport { value } from '../src/value.ts';\n"
    SYNTAX_A = "import test from 'node:test';\ntest('a', () => {\n  const = 1;\n});\n"
    SYNTAX_B = "import test from 'node:test';\ntest('a', () => {\n  foo(1, ;\n});\n"
    PASSES_1 = HEAD + "test('a', () => { assert.equal(value(), 1); });\n"
    PASSES_2 = HEAD + "test('a', () => { assert.equal(typeof value(), 'number'); });\n"
    GOOD = HEAD + "test('value is two', () => { assert.equal(value(), 2); });\n"

    def project(self):
        base = Path(tempfile.mkdtemp())
        checkout = base / "checkout"
        checkout.mkdir()
        w = lambda name, text: pipeline.write(checkout, name, text)
        w("package.json", json.dumps({"type": "module", "scripts": {"test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
        w("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"NodeNext","strict":true,"allowImportingTsExtensions":true,"types":[],"noEmit":true},"include":["src/**/*.ts"]}')
        w("src/value.ts", "export const value = (): number => 1;\n")
        w("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; import {value} from '../src/value.ts'; test('number', () => assert.equal(typeof value(), 'number'));\n")
        w("patchproof.json", json.dumps({"runtime": "node-typescript"}))
        (checkout / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
        return base, checkout

    def run_sequence(self, sources):
        base, checkout = self.project()
        queue = list(sources)
        calls = []

        def model_text(**kwargs):
            calls.append(kwargs)
            source = queue.pop(0) if queue else sources[-1]
            return (f"{proof.TEST_BEGIN}\n{source}\n{proof.TEST_END}\n"
                    f"{proof.RATIONALE_BEGIN}\nChecks value().\n{proof.RATIONALE_END}")

        candidate = lambda **k: ([{"path": "src/value.ts", "content": "export const value = (): number => 2;\n"}], "fix")
        result, record, error = pipeline.run_engine(base, checkout, checkout, proof.Issue(1, "Wrong value", "value() must return 2."),
                                                    "unused", candidate, model_text=model_text)
        return result, record, error, calls

    def test_static_rejections_do_not_use_up_the_three_execution_attempts(self):
        # Two refused tests, two executed non-reproductions, then a reproducing test: five rounds.
        # Before rc.30 this stopped after three.
        result, record, error, calls = self.run_sequence(
            [self.SYNTAX_A, self.SYNTAX_B, self.PASSES_1, self.PASSES_2, self.GOOD])
        self.assertIsNone(error, json.dumps(record["regression_test"]["attempts"], default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        attempts = result["regression_test"]["attempts"]
        self.assertEqual([a["static_rejection"] for a in attempts], [True, True, False, False, False])
        self.assertEqual([a["counts_toward_limit"] for a in attempts], [False, False, True, True, True])
        self.assertEqual(len(calls), 5)

    def test_syntax_feedback_shows_the_offending_line_to_the_next_attempt(self):
        result, record, error, calls = self.run_sequence([self.SYNTAX_B, self.GOOD])
        self.assertIsNone(error)
        feedback = calls[1]["user"]
        self.assertIn("ENGINE DIAGNOSIS: The parser rejected the submitted source before any test ran", feedback)
        self.assertIn("3:   foo(1, ;", feedback)

    def test_three_identical_refusals_stop_the_run_with_its_own_bucket(self):
        result, record, error, calls = self.run_sequence([self.SYNTAX_A])
        self.assertIsNotNone(error)
        self.assertIn("repeated the same rejected output 3 times", str(error))
        self.assertEqual(len(calls), 3)  # the fourth request is never made
        record["error"] = str(error)
        proof.finalize_proof(record)
        self.assertEqual(record["outcome"]["bucket"], "verifier_invalid")
        self.assertEqual(record["stop_reason"], "verification_failed")
        self.assertFalse(record["outcome"]["evaluated_repair"])

    def test_three_different_refusals_end_on_the_static_allowance(self):
        distinct = [self.SYNTAX_A, self.SYNTAX_B,
                    "import test from 'node:test';\ntest('a', () => {\n  let = ;\n  if (\n});\n"]
        result, record, error, calls = self.run_sequence(distinct)
        self.assertIsNotNone(error)
        self.assertIn("refused by static checks 3 times", str(error))
        record["error"] = str(error)
        proof.finalize_proof(record)
        self.assertEqual(record["outcome"]["bucket"], "verifier_invalid")

    def test_three_executed_non_reproductions_still_end_the_run(self):
        throws = "import test from 'node:test';\ntest('a', () => { throw new Error('boom'); });\n"
        result, record, error, calls = self.run_sequence([self.PASSES_1, throws, self.PASSES_2])
        self.assertIsNotNone(error)
        self.assertIn("retry budget exhausted", str(error))
        record["error"] = str(error)
        proof.finalize_proof(record)
        self.assertEqual(record["outcome"]["bucket"], "no_reproduction")


if __name__ == "__main__":
    unittest.main()
