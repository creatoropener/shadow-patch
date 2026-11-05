"""rc.43: a verifier test whose date literal is not a valid date can never pass, so it is rejected before it is frozen.

CareerPilot #8 on rc.42: the first of thirteen generated tests used new Date('2026-10-24T10:00:00:00Z'), an Invalid Date.
Every candidate fails such a test however correct it is; the engine only checked that the test failed on the unfixed code.
The fixtures are the real generated test and the same file with that one literal corrected.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import proof
import runtimes
from tests.test_string_escape_gate import HASH, LINTER, _with_hash

FIXTURES = Path(__file__).parent / "fixtures"


class DateGateFeedbackTests(unittest.TestCase):
    output = _with_hash("t.ts:6:20: the date literal '2026-10-24T10:00:00:00Z' is not a valid date\n"
                        "PATCHPROOF_TYPESCRIPT_DATE=failed")

    def test_classification_is_a_protected_non_reproduction(self):
        reproduced, protected, reason = proof.classify_reproduction(None, 2, self.output, HASH)
        self.assertEqual((reproduced, protected), (False, True))
        self.assertIn("invalid date literal", reason)

    def test_feedback_says_what_to_change_and_keeps_the_literal_diagnostic(self):
        feedback = proof.reproduction_feedback("SRC", "generated TypeScript regression has an invalid date literal",
                                               self.output)
        self.assertIn("evaluates to Invalid Date", feedback)
        self.assertIn("2026-10-24T10:00:00.000Z", feedback)
        self.assertIn("is not a valid date", feedback)  # the lint's own line is in the execution output
        self.assertNotIn("silently drops", feedback)

    def test_guidance_asks_for_full_iso_dates(self):
        adapter = runtimes.detect_runtime(self._project())
        self.assertIn("full ISO form", adapter.verifier_guidance)

    def _project(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="rc43-"))
        (root / "package.json").write_text('{"type":"module"}')
        (root / "tsconfig.json").write_text("{}")
        return root


@unittest.skipUnless(os.environ.get("TS_LINT_NODE_MODULES"),
                     "Set TS_LINT_NODE_MODULES to installed TypeScript node_modules")
class DateGateIntegrationTests(unittest.TestCase):
    def lint_text(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}")
            runtime = root / "_rt"
            runtime.mkdir()
            (runtime / "package.json").write_text("{}")
            (runtime / "node_modules").symlink_to(Path(os.environ["TS_LINT_NODE_MODULES"]).resolve(),
                                                  target_is_directory=True)
            (root / "generated.test.ts").write_text(text)
            run = subprocess.run(["node", str(LINTER), "generated.test.ts"], cwd=root, text=True,
                                 capture_output=True, timeout=30,
                                 env={**os.environ, "PATCHPROOF_TYPESCRIPT_RUNTIME": str(runtime)})
            return run.returncode, run.stdout + run.stderr

    def test_the_real_rc42_test_is_rejected_at_the_line_of_the_bad_date(self):
        code, output = self.lint_text((FIXTURES / "rc43_careerpilot8_invalid_now.test.ts").read_text())
        self.assertEqual(code, 2, output)
        self.assertIn("PATCHPROOF_TYPESCRIPT_DATE=failed", output)
        self.assertNotIn("PATCHPROOF_TYPESCRIPT_LINT=passed", output)
        self.assertIn("'2026-10-24T10:00:00:00Z' is not a valid date", output)
        self.assertIn("generated.test.ts:6:", output)
        self.assertEqual(output.count("is not a valid date"), 1)  # the other twelve literals are fine

    def test_the_same_file_with_the_literal_corrected_passes(self):
        code, output = self.lint_text((FIXTURES / "rc43_careerpilot8_valid_now.test.ts").read_text())
        self.assertEqual(code, 0, output)
        self.assertIn("PATCHPROOF_TYPESCRIPT_LINT=passed", output)
        self.assertNotIn("DATE", output)

    def test_only_iso_looking_direct_literals_are_checked(self):
        source = "\n".join([
            "import test from 'node:test';",
            "test('x', () => {",
            "  const a = new Date('2026-13-45T00:00:00Z');",      # invalid ISO-looking: flagged
            "  const b = Date.parse('2026-10-24T25:00:00Z');",    # invalid ISO-looking: flagged
            "  const c = new Date('not a date');",                # not ISO-looking: left alone
            "  const d = new Date(`2026-10-24T10:00:00Z`);",      # valid
            "  const e = new Date(someValue);",                   # not a literal: left alone
            "  const f = new Date('2026-10-24 10:00:00');",       # valid for V8's legacy parser
            "  console.log(a, b, c, d, e, f);",
            "});", ""])
        code, output = self.lint_text(source.replace("someValue", "'2026-10-24'.toString()"))
        self.assertEqual(code, 2, output)
        self.assertEqual(output.count("is not a valid date"), 2, output)
        self.assertIn("generated.test.ts:3:", output)
        self.assertIn("generated.test.ts:4:", output)


if __name__ == "__main__":
    unittest.main()
