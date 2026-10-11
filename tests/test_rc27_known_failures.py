"""rc.27: a repository whose own suite already fails can be repaired when the failures are declared."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import proof
from runtimes import RuntimeDetectionError, detect_runtime
from tests import support_pipeline as pipeline
from patchproof_runtime import known_failures as kf

SOURCE_TEST = """import test, { describe, it } from 'node:test';
import assert from 'node:assert/strict';
test('ok one', () => {});
test('legacy: broken thing', () => { assert.equal(1, 2); });
describe('suite', () => { it('nested legacy failure', () => { throw new Error('boom'); }); it('nested ok', () => {}); });
test('new breakage', () => { assert.equal('a', 'b'); });
test('name with # hash', () => { assert.equal(1, 3); });
"""


def tap(source: str) -> tuple[int, str]:
    directory = Path(tempfile.mkdtemp())
    (directory / "a.test.mjs").write_text(source)
    result = subprocess.run(["node", "--test", "--test-reporter=tap", "a.test.mjs"], cwd=directory,
                            capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


@unittest.skipUnless(shutil.which("node"), "requires node")
class WrapperTests(unittest.TestCase):
    def test_leaf_failures_are_listed_once_and_parent_suites_are_ignored(self):
        _, output = tap(SOURCE_TEST)
        self.assertEqual(kf.failing_tests(output),
                         ["legacy: broken thing", "nested legacy failure", "new breakage", "name with # hash"])

    def test_only_declared_failures_are_accepted(self):
        code, output = tap(SOURCE_TEST)
        known = {"legacy: broken thing", "nested legacy failure", "name with # hash"}
        status, verdict = kf.decide(code, output, known)
        self.assertEqual((status, verdict["status"], verdict["new_failures"]), (1, "failed", ["new breakage"]))
        status, verdict = kf.decide(code, output, known | {"new breakage"})
        self.assertEqual((status, verdict["status"]), (0, "passed"))

    def test_a_clean_run_and_an_unaccountable_failure(self):
        self.assertEqual(kf.decide(0, "# pass 3\n# fail 0\n", {"x"})[0], 0)
        self.assertEqual(kf.decide(1, "Error: cannot find module\n", {"x"})[0], 1)
        # exit status never becomes 0 when the output cannot be trusted
        self.assertEqual(kf.decide(7, "# fail 2\nnot ok 1 - only one\n", {"only one"})[0], 7)

    def test_command_line_passes_output_through_and_prints_a_last_line_verdict(self):
        directory = Path(tempfile.mkdtemp())
        (directory / "a.test.mjs").write_text(SOURCE_TEST)
        names = base64.b64encode(json.dumps(["legacy: broken thing"]).encode()).decode()
        result = subprocess.run([sys.executable, str(Path(proof.__file__).parent / "patchproof_runtime/known_failures.py"),
                                 names, "node --test --test-reporter=tap a.test.mjs"],
                                cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not ok 4 - new breakage", result.stdout)
        self.assertEqual(proof.ordinary_status(result.stdout)["status"], "failed")


class ConfigTests(unittest.TestCase):
    def project(self, config):
        root = Path(tempfile.mkdtemp())
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
        (root / "patchproof.json").write_text(json.dumps(config))
        return root

    def test_declared_failures_wrap_the_ordinary_command(self):
        adapter = detect_runtime(self.project({"known_failures": ["b", "a"]}))
        self.assertEqual(adapter.known_failures, ("b", "a"))
        self.assertIn("python /patchproof/known_failures.py", adapter.baseline_command)
        self.assertIn("CI=1 npm test", adapter.baseline_command)

    def test_bad_lists_and_unsupported_runtimes_are_refused(self):
        for value in ([], "legacy", [""], ["a", "a"], ["x" * 301], ["line\nbreak"], [1], ["n"] * 51):
            with self.subTest(value=value), self.assertRaises(RuntimeDetectionError):
                detect_runtime(self.project({"known_failures": value}))
        with self.assertRaisesRegex(RuntimeDetectionError, "node:test"):
            root = Path(tempfile.mkdtemp())
            (root / "requirements.txt").write_text("pytest\n")
            (root / "pytest.ini").write_text("[pytest]\n")
            (root / "tests").mkdir()
            (root / "tests/test_a.py").write_text("def test_a(): pass\n")
            (root / "patchproof.json").write_text(json.dumps({"runtime": "python-pytest", "known_failures": ["x"]}))
            detect_runtime(root)

    def test_undeclared_config_is_still_rejected(self):
        with self.assertRaises(RuntimeDetectionError):
            detect_runtime(self.project({"known_failure": ["a"]}))


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class PipelineTests(unittest.TestCase):
    def build(self, declared):
        base = Path(tempfile.mkdtemp())
        checkout = base / "checkout"
        checkout.mkdir()
        w = lambda name, text: pipeline.write(checkout, name, text)
        w("package.json", json.dumps({"type": "module", "scripts": {"test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
        w("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"NodeNext","strict":true,"allowImportingTsExtensions":true,"types":[]},"include":["src/**/*.ts"]}')
        w("src/value.ts", "export const value = (): number => 1;\n")
        w("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; import {value} from '../src/value.ts'; test('value is a number', () => assert.equal(typeof value(), 'number'));\n")
        w("tests/legacy.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; test('legacy: removed feature', () => assert.equal(1, 2));\n")
        config = {"runtime": "node-typescript"}
        if declared is not None:
            config["known_failures"] = declared
        w("patchproof.json", json.dumps(config))
        (checkout / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
        return base, checkout

    TEST = """import test from 'node:test';
import assert from 'node:assert/strict';
import { value } from '../src/value.ts';
test('value is two', () => { assert.equal(value(), 2); });
"""

    def run_case(self, declared, candidate_value="2"):
        base, checkout = self.build(declared)
        candidate = lambda **k: ([{"path": "src/value.ts", "content": f"export const value = (): number => {candidate_value};\n"}], "fix")
        result, record, error = pipeline.run_engine(base, checkout, checkout, proof.Issue(1, "Wrong value", "value() must be 2."),
                                                    self.TEST, candidate)
        return result, record, error, checkout

    def test_declared_failure_does_not_block_repair_and_is_recorded(self):
        result, record, error, checkout = self.run_case(["legacy: removed feature"])
        self.assertIsNone(error, json.dumps(record, indent=2, default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        observed = result["baseline"]["known_failures"]["observed"]
        self.assertEqual((observed["status"], observed["known_failures"]), ("passed", ["legacy: removed feature"]))
        self.assertTrue(result["regression_test"]["ordinary_ci"]["discovered"])
        self.assertEqual((checkout / "src/value.ts").read_text(), "export const value = (): number => 2;\n")

    def test_without_a_declaration_the_failing_baseline_still_blocks(self):
        result, record, error, _ = self.run_case(None)
        self.assertIsNotNone(error)
        self.assertIn("Baseline command failed", str(error))

    def test_an_undeclared_failure_still_blocks(self):
        result, record, error, _ = self.run_case(["some other test"])
        self.assertIsNotNone(error)
        self.assertIn("Baseline command failed", str(error))
        self.assertEqual(record["baseline"]["known_failures"]["observed"]["new_failures"], ["legacy: removed feature"])

    def test_a_candidate_that_breaks_a_passing_test_is_rejected(self):
        # value() returns a string: the regression's equality still fails, and the existing
        # 'value is a number' test now fails too, an undeclared failure.
        result, record, error, _ = self.run_case(["legacy: removed feature"], candidate_value="'2'")
        self.assertIsNotNone(error)
        self.assertEqual(record["candidates"][0]["stage"], "baseline")


if __name__ == "__main__":
    unittest.main()
