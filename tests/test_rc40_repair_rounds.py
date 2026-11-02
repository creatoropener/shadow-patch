"""rc.40: a failed frozen regression earns more proposals; generated tests get portable imports.

The pipeline cases run the real engine offline against the local TypeScript toolchain with a
scripted solver, exactly as the rc.27 and rc.30 pipeline tests do.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import outcomes
import proof
from tests import support_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]

RIGHT = "export const label = (n: number): string => (n === 1 ? 'one' : n === 2 ? 'two' : 'many');\n"
WRONG = "export const label = (n: number): string => (n === 1 ? 'one' : n === 2 ? 'Two' : 'many');\n"
WRONG_AGAIN = "export const label = (n: number): string => (n === 1 ? 'one' : n === 2 ? 'TWO' : 'many');\n"
REGRESSION = """import test from 'node:test';
import assert from 'node:assert/strict';
import { label } from '../src/label.%s';

test('two is spelled out in lower case', async () => {
  assert.equal(label(2), 'two');
});
"""


def project(allow_ts_extensions: bool = False) -> Path:
    root = Path(tempfile.mkdtemp(prefix="rc40-"))
    put = lambda name, text: pipeline.write(root, name, text)
    options = '"allowImportingTsExtensions":true,' if allow_ts_extensions else ""
    put("package.json", json.dumps({"type": "module", "scripts": {
        "test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
    put("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"ESNext","moduleResolution":"Bundler",'
                         '"strict":true,' + options + '"types":[],"noEmit":true},"include":["src/**/*.ts"]}')
    put("src/label.ts", "export const label = (n: number): string => (n === 1 ? 'one' : 'many');\n")
    put("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; "
        "import {label} from '../src/label.js'; test('one', () => assert.equal(label(1), 'one'));\n")
    put("patchproof.json", json.dumps({"runtime": "node-typescript", "scope": {"allowed_paths": ["src/label.ts"]}}))
    (root / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
    return root


class FeedbackTextTests(unittest.TestCase):
    def test_feedback_has_the_failure_but_not_engine_markers_or_credentials(self):
        output = ("PATCHPROOF_TYPESCRIPT_CHECK=passed\nTAP version 13\nnot ok 1 - two\n  error: |-\n"
                  "    Expected values to be strictly equal:\n    'Two' !== 'two'\n"
                  "PATCHPROOF_TEST_HASH_AFTER=abc\nsecret-key-123")
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "secret-key-123"}):
            text = proof.regression_repair_feedback(output, "--- a\n+++ b\n", 2, 3)
        self.assertIn("REPAIR ROUND 2 of 3", text)
        self.assertIn("'Two' !== 'two'", text)
        self.assertNotIn("PATCHPROOF_", text)
        self.assertNotIn("secret-key-123", text)
        self.assertIn("PREVIOUS PROPOSAL DIFF", text)

    def test_feedback_is_bounded(self):
        text = proof.regression_repair_feedback("x" * 50_000, "d" * 50_000, 1, 3)
        self.assertLessEqual(len(text), 12_000)

    def test_ts5097_gets_a_specific_diagnosis(self):
        output = ("tests/t.test.ts(3,32): error TS5097: An import path can only end with a '.ts' extension "
                  "when 'allowImportingTsExtensions' is enabled.")
        feedback = proof.reproduction_feedback("x", "generated TypeScript regression failed API type-check", output,
                                               "node-typescript")
        self.assertIn("ENGINE DIAGNOSIS: TS5097", feedback)
        self.assertIn(".js", feedback)

    def test_rounds_setting(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PATCHPROOF_REPAIR_ROUNDS", None)
            self.assertEqual(proof.repair_rounds_from_env(), 3)
        for value, expected in (("0", 0), ("5", 5)):
            with patch.dict(os.environ, {"PATCHPROOF_REPAIR_ROUNDS": value}):
                self.assertEqual(proof.repair_rounds_from_env(), expected)
        for bad in ("6", "-1", "many"):
            with patch.dict(os.environ, {"PATCHPROOF_REPAIR_ROUNDS": bad}), self.assertRaises(Exception):
                proof.repair_rounds_from_env()


class ImportExtensionTests(unittest.TestCase):
    SOURCE = ("import { a } from '../lib/recency.ts';\nimport b from \"./x/y.tsx\";\n"
              "const m = await import('../lib/z.mts');\nimport t from 'node:test';\nimport p from 'pkg/foo.ts';\n")

    def test_relative_ts_imports_become_js_and_packages_are_left_alone(self):
        root = project()
        text, notes = proof.canonicalize_ts_import_extensions(self.SOURCE, root)
        self.assertIn("'../lib/recency.js'", text)
        self.assertIn('"./x/y.js"', text)
        self.assertIn("'../lib/z.mjs'", text)
        self.assertIn("'pkg/foo.ts'", text)  # not a relative import
        self.assertIn("'node:test'", text)
        self.assertEqual(len(notes), 3)

    def test_a_project_that_allows_ts_extensions_is_left_alone(self):
        root = project(allow_ts_extensions=True)
        text, notes = proof.canonicalize_ts_import_extensions(self.SOURCE, root)
        self.assertEqual((text, notes), (self.SOURCE, []))

    def test_already_portable_imports_are_unchanged(self):
        source = "import { a } from '../lib/recency.js';\nimport b from './b';\n"
        self.assertEqual(proof.canonicalize_ts_import_extensions(source, project()), (source, []))


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class RepairRoundPipelineTests(unittest.TestCase):
    def run_case(self, replies, *, extension="js", env=None):
        """replies: callable(call_number, retry_feedback) -> file text for src/label.ts."""
        root = project()
        calls: list[str] = []

        def candidate(**kwargs):
            feedback = kwargs.get("retry_feedback", "")
            calls.append(feedback)
            return [{"path": "src/label.ts", "content": replies(len(calls), feedback)}], "scripted proposal"

        result, record, error = pipeline.run_engine(
            Path(tempfile.mkdtemp()), root, root,
            proof.Issue(1, "label(2) is wrong", "label(2) must return the lower-case word two."),
            REGRESSION % extension, candidate, env_extra=env)
        return root, result, record, error, calls

    def test_a_proposal_that_fails_the_regression_is_repaired_from_its_failure_output(self):
        root, result, record, error, calls = self.run_case(
            lambda n, feedback: RIGHT if "REPAIR ROUND" in feedback else WRONG)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        first = result["candidates"][0]
        self.assertTrue(first["passed"])
        self.assertEqual(first["repair_round"], 1)
        self.assertEqual(len(first["repair_rounds"]), 1)
        self.assertEqual(first["repair_rounds"][0]["stage"], "regression")
        self.assertIn("'Two'", first["repair_rounds"][0]["output"])
        self.assertEqual(result["winner"]["repair_round"], 1)
        self.assertEqual((root / "src/label.ts").read_text(), RIGHT)
        # the round-2 feedback shows the failure but never the hidden test's source
        feedback = next(item for item in calls if "REPAIR ROUND" in item)
        self.assertIn("'Two'", feedback)
        self.assertNotIn("import assert", feedback)
        self.assertNotIn("PATCHPROOF_", feedback)
        # once a candidate has passed, the others spend no repair rounds
        self.assertEqual(sum("REPAIR ROUND" in item for item in calls), 1)
        for later in result["candidates"][1:]:
            self.assertNotIn("repair_rounds", later)
        report = proof.render_report(result)
        self.assertIn("were given the failure output of the verifier's regression test", report)

    def test_the_same_patch_twice_stops_the_candidate(self):
        root, result, record, error, calls = self.run_case(lambda n, feedback: WRONG)
        self.assertIsNotNone(error)
        self.assertEqual((root / "src/label.ts").read_text(), "export const label = (n: number): string => (n === 1 ? 'one' : 'many');\n")
        first = record["candidates"][0]
        self.assertEqual(first["repair_stopped"], "the same patch was proposed again")
        self.assertEqual(len(calls), 6)  # two proposals for each of three candidates, not four
        self.assertEqual(outcomes.classify_outcome(record)["bucket"], "repair_failed")

    def test_the_round_limit_is_respected_and_zero_restores_rc39(self):
        sequence = [WRONG, WRONG_AGAIN]
        root, result, record, error, calls = self.run_case(
            lambda n, feedback: WRONG if n % 2 else WRONG_AGAIN, env={"PATCHPROOF_REPAIR_ROUNDS": "1"})
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 6)
        self.assertEqual(len(record["candidates"][0]["repair_rounds"]), 1)
        self.assertEqual(record["race"]["repair_rounds_allowed"], 1)
        root, result, record, error, calls = self.run_case(
            lambda n, feedback: RIGHT if "REPAIR ROUND" in feedback else WRONG, env={"PATCHPROOF_REPAIR_ROUNDS": "0"})
        self.assertIsNotNone(error)  # nothing is repaired from feedback any more
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("repair_rounds" not in item for item in record["candidates"]))

    def test_a_generated_test_importing_dot_ts_is_normalised_and_the_run_proceeds(self):
        root, result, record, error, calls = self.run_case(
            lambda n, feedback: RIGHT if "REPAIR ROUND" in feedback else WRONG, extension="ts")
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertIn("../src/label.js", result["regression_test"]["content"])
        self.assertNotIn("label.ts", result["regression_test"]["content"])
        normalized = result["regression_test"]["generation_attempts"][0]["normalized"]
        self.assertIn("../src/label.ts -> ../src/label.js", normalized[0])


class ActionWiringTests(unittest.TestCase):
    def test_input_is_declared_and_passed_to_the_engine(self):
        text = (ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  repair-rounds:\n(?:    .*\n)*?    default: '3'")
        self.assertIn("PATCHPROOF_REPAIR_ROUNDS: ${{ inputs.repair-rounds }}", text)
        workflow = (ROOT / ".github/workflows/shadow-fix.yml").read_text(encoding="utf-8")
        self.assertIn("PATCHPROOF_REPAIR_ROUNDS: ${{ vars.PATCHPROOF_REPAIR_ROUNDS || '3' }}", workflow)
        self.assertTrue(re.search(r'APP_VERSION = "0\.6\.0-rc\.40"', (ROOT / "proof.py").read_text()))


if __name__ == "__main__":
    unittest.main()
