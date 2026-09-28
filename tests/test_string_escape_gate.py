"""rc.17: the useless-escape gate, its feedback, and the report's image redaction."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import proof
from proof import classify_reproduction, render_report, reproduction_feedback

FIXTURES = Path(__file__).parent / "fixtures"
LINTER = Path(__file__).resolve().parents[1] / "patchproof_runtime/typescript_test_lint.mjs"
HASH = "0309a6fe5a940bdef18ac2a80ba275d3104d97e24d9177498ff51766753ffa6a"


def _with_hash(body: str) -> str:
    return (f"{body}\nPATCHPROOF_TEST_HASH_BEFORE={HASH}\n"
            f"PATCHPROOF_TEST_HASH_AFTER={HASH}\n")


class EscapeFeedbackTests(unittest.TestCase):
    output = _with_hash("t.ts:25:43: useless string escape\nPATCHPROOF_TYPESCRIPT_LITERAL=failed")

    def test_classification_is_a_protected_non_reproduction(self):
        reproduced, protected, reason = classify_reproduction(None, 2, self.output, HASH)
        self.assertEqual((reproduced, protected), (False, True))
        self.assertIn("string-escape lint", reason)

    def test_feedback_explains_the_dropped_backslash_without_other_diagnoses(self):
        feedback = reproduction_feedback("SRC", "generated TypeScript regression failed string-escape lint",
                                         self.output)
        self.assertIn("silently drops", feedback)
        self.assertIn("TWO backslashes", feedback)
        self.assertIn("do not weaken or drop the assertion", feedback)
        self.assertNotIn("constructed a value but never used", feedback)
        self.assertNotIn("syntax error", feedback)


class ReportRedactionTests(unittest.TestCase):
    def test_report_never_shows_sandbox_image_ids(self):
        proof_data = {
            "verdict": "rejected", "model": "m", "issue": {"number": 1, "title": "t"},
            "runtime": {"id": "node-typescript", "display_name": "Node", "application_languages": ["TypeScript"],
                        "test_runtime": "node-test"},
            "sandbox": {"base_image": "bd36d428-4d86-49f8-a270-635c3d00a4d3"},
            "regression_test": {"path": "tests/x.test.ts"}, "candidates": [], "error": "e",
        }
        report = render_report(proof_data)
        self.assertNotIn("bd36d428", report)
        self.assertNotIn("Sandbox image", report)
        self.assertIn("Regression test: `tests/x.test.ts`", report)


@unittest.skipUnless(os.environ.get("TS_LINT_NODE_MODULES"),
                     "Set TS_LINT_NODE_MODULES to installed TypeScript node_modules")
class EscapeGateIntegrationTests(unittest.TestCase):
    def lint(self, fixture: str):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}")
            runtime = root / "_rt"
            runtime.mkdir()
            (runtime / "package.json").write_text("{}")
            (runtime / "node_modules").symlink_to(Path(os.environ["TS_LINT_NODE_MODULES"]).resolve(),
                                                  target_is_directory=True)
            (root / "generated.test.ts").write_text((FIXTURES / fixture).read_text())
            run = subprocess.run(["node", str(LINTER), "generated.test.ts"], cwd=root, text=True,
                                 capture_output=True, timeout=30,
                                 env={**os.environ, "PATCHPROOF_TYPESCRIPT_RUNTIME": str(runtime)})
            return run.returncode, run.stdout + run.stderr

    def test_real_rc16_qrcrafts_test_is_rejected_with_positions(self):
        code, output = self.lint("rc16_qrcrafts_useless_escapes.test.ts")
        self.assertEqual(code, 2, output)
        self.assertIn("PATCHPROOF_TYPESCRIPT_LITERAL=failed", output)
        self.assertNotIn("PATCHPROOF_TYPESCRIPT_LINT=passed", output)
        self.assertIn("'\\;' evaluates to ';'", output)
        self.assertIn("'\\c' evaluates to 'c'", output)
        self.assertIn("generated.test.ts:25:", output)

    def test_meaningful_escapes_templates_string_raw_and_regex_pass(self):
        code, output = self.lint("rc17_escapes_corrected.test.ts")
        self.assertEqual(code, 0, output)
        self.assertIn("PATCHPROOF_TYPESCRIPT_LINT=passed", output)
        self.assertNotIn("LITERAL", output)

    def test_escape_and_unused_binding_are_both_reported(self):
        code, output = self.lint("rc17_escapes_and_unused.test.ts")
        self.assertEqual(code, 2, output)
        self.assertIn("PATCHPROOF_TYPESCRIPT_LITERAL=failed", output)
        self.assertIn("PATCHPROOF_TYPESCRIPT_LINT=failed", output)
        self.assertIn("'unusedHelper' is declared but never used", output)

    def test_existing_valid_fixtures_are_not_flagged(self):
        for fixture in ("proof6_corrected_regression.test.ts", "proof8_regression.test.ts"):
            with self.subTest(fixture=fixture):
                code, output = self.lint(fixture)
                self.assertNotIn("LITERAL", output)


if __name__ == "__main__":
    unittest.main()
