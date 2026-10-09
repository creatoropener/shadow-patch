"""rc.24: the verifier gates built from the rc.23 benchmark proofs.

Every fixture named rc24_heldout* is a test the model really generated in the rc.23 run
(heldout-1 trials 1 to 3, heldout-2 trials 1 and 3), saved byte for byte from the proofs.
The gates must refuse each of them, and must leave correct tests alone.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import proof
import runtimes
from patchproof_runtime import typescript_source_check as source_check

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
HELDOUT_1_ISSUE = (ROOT / "bench/issues/heldout-1.md").read_text(encoding="utf-8")
HELDOUT_2_ISSUE = (ROOT / "bench/issues/heldout-2.md").read_text(encoding="utf-8")


def adapter_for(runtime: str, files: dict[str, str]) -> runtimes.RuntimeAdapter:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return runtimes.detect_runtime(root)


def typescript_adapter() -> runtimes.RuntimeAdapter:
    return adapter_for("node-typescript", {
        "package.json": json.dumps({"name": "x", "scripts": {"test": "tsx --test tests/*.test.ts"}}),
        "tsconfig.json": "{}\n", "patchproof.json": '{"runtime": "node-typescript"}\n',
        "src/a.ts": "export const a = 1;\n",
    })


def static_adapter() -> runtimes.RuntimeAdapter:
    return adapter_for("static-web", {"index.html": "<html><body></body></html>\n"})


class RecordedHeldout1TestsPinInventedWording(unittest.TestCase):
    CASES = {
        "rc24_heldout1_t1_pins_blocked.test.ts": "/blocked/",
        "rc24_heldout1_t2_pins_invalid_url.test.ts": "Invalid URL",
        "rc24_heldout1_t3_pins_ssrf_message.test.ts": "SSRF protection: Target host resolves",
    }

    def test_the_issue_never_states_any_of_the_pinned_wording(self):
        lowered = HELDOUT_1_ISSUE.lower()
        for fragment in ("blocked", "invalid url", "ssrf protection: target host",
                         "invalid target: resolves to disallowed"):
            self.assertNotIn(fragment, lowered)

    def test_every_recorded_accepted_test_is_refused(self):
        adapter = typescript_adapter()
        for name, shown in self.CASES.items():
            with self.subTest(name):
                content = (FIX / name).read_text(encoding="utf-8")
                # Nothing else in the validator objected: the new gate is what catches them.
                adapter.validate_generated_test(content, "tests/.test_patchproof_issue_1.test.ts")
                with self.assertRaisesRegex(ValueError, "never states") as caught:
                    adapter.validate_generated_pins(content, HELDOUT_1_ISSUE)
                self.assertIn(shown, str(caught.exception))

    def test_the_diagnostic_tells_the_model_what_to_do_instead(self):
        content = (FIX / "rc24_heldout1_t1_pins_blocked.test.ts").read_text(encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            typescript_adapter().validate_generated_pins(content, HELDOUT_1_ISSUE)
        message = str(caught.exception)
        for phrase in ("no regex, string or `message:` matcher", "assert.rejects(promise)",
                       "'connection' events", "ECONNREFUSED"):
            self.assertIn(phrase, message)

    def test_a_behavioural_test_of_the_same_bug_passes_both_gates(self):
        adapter = typescript_adapter()
        content = (
            "import test from 'node:test';\n"
            "import assert from 'node:assert/strict';\n"
            "import http from 'node:http';\n"
            "import { runDastSiteScan } from '../src/server/dastEngine';\n\n"
            "test('a loopback target is refused before any connection is made', async () => {\n"
            "  let connections = 0;\n"
            "  const server = http.createServer((_request, response) => { response.end('ok'); });\n"
            "  server.on('connection', () => { connections += 1; });\n"
            "  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));\n"
            "  const { port } = server.address() as { port: number };\n"
            "  try {\n"
            "    await assert.rejects(runDastSiteScan(`http://127.0.0.1:${port}`));\n"
            "  } finally {\n"
            "    await new Promise((resolve) => server.close(resolve));\n"
            "  }\n"
            "  assert.equal(connections, 0);\n"
            "});\n"
        )
        adapter.validate_generated_test(content, "tests/.test_patchproof_issue_1.test.ts")
        adapter.validate_generated_pins(content, HELDOUT_1_ISSUE)


class PinGateTable(unittest.TestCase):
    ISSUE = ("The scan must reject the target. It should fail with the message Invalid target: "
             "private address. The error code ERR_BLOCKED may also be used.")
    FLAGGED = {
        "rejects with an ungrounded regex": "await assert.rejects(p, /Host is forbidden/);",
        "rejects with message regex": "await assert.rejects(p, { message: /nope nope/ });",
        "rejects with message string": "await assert.rejects(p, { message: 'Totally invented' });",
        "rejects with name and message": "await assert.rejects(p, { name: 'Error', message: /invented words/ });",
        "throws with regex": "assert.throws(() => f(), /invented words here/);",
        "regex test on message": "assert.ok(/forbidden host/.test(err.message));",
        "assert.match on message": "assert.match(err.message, /forbidden host/);",
        "strictEqual on message": "assert.strictEqual(err.message, 'forbidden host');",
        "message.includes": "assert.ok(err.message.includes('forbidden host'));",
        "template literal message": "await assert.rejects(p, { message: `forbidden host` });",
        "regex operators removed": "await assert.rejects(p, /^Error: [A-Z]+ \\d+ forbidden words$/);",
        "one ungrounded alternative": "await assert.rejects(p, /Invalid target|invented words/);",
    }
    ALLOWED = {
        "no matcher at all": "await assert.rejects(p);",
        "error class only": "assert.throws(() => f(), TypeError);",
        "error code only": "await assert.rejects(p, { code: 'ERR_INVENTED' });",
        "predicate function": "await assert.rejects(p, (e) => e instanceof Error && !/ECONNREFUSED/.test(e.message));",
        "negated regex": "assert.ok(!/ECONNREFUSED|ENOTFOUND/.test(err.message));",
        "code names are not wording": "assert.ok(/ECONNREFUSED/.test(err.message));",
        "wording the issue states": "await assert.rejects(p, /Invalid target/);",
        "wording the issue states, other case": "await assert.rejects(p, /invalid TARGET: private address/i);",
        "string the issue states": "await assert.rejects(p, { message: 'Invalid target: private address' });",
        "match on something that is not a message": "assert.match(output, /forbidden host/);",
        "equality on something that is not a message": "assert.strictEqual(result.value, 'forbidden host');",
        "negated includes": "assert.ok(!err.message.includes('forbidden host'));",
        "doesNotMatch": "assert.doesNotMatch(err.message, /forbidden host/);",
        "fewer than three letters": "await assert.rejects(p, /ab/);",
        "a test name is not a matcher": "test('SSRF protection: rejects internal IP', async () => {});",
        "a variable is not a literal": "await assert.rejects(p, expected);",
    }

    def found(self, line: str) -> list[str]:
        return runtimes.ungrounded_message_pins(
            "import assert from 'node:assert/strict';\n" + line, self.ISSUE)

    def test_ungrounded_matchers_are_found(self):
        for name, line in self.FLAGGED.items():
            with self.subTest(name):
                self.assertTrue(self.found(line), line)

    def test_everything_else_is_left_alone(self):
        for name, line in self.ALLOWED.items():
            with self.subTest(name):
                self.assertEqual(self.found(line), [], line)

    def test_an_unavailable_wording_check_cannot_accept_a_test(self):
        adapter = typescript_adapter()
        with patch.object(runtimes, "ungrounded_message_pins", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                adapter.validate_generated_pins("await assert.rejects(p, /x y z/);", "issue")

    def test_python_tests_are_not_gated(self):
        adapter = adapter_for("python-pytest", {
            "pyproject.toml": "[project]\nname='x'\n", "pkg/mod.py": "x = 1\n",
            "tests/test_a.py": "def test_a():\n    assert True\n",
        })
        self.assertEqual(adapter.test_runtime, "pytest")
        adapter.validate_generated_pins("with pytest.raises(ValueError, match='invented words'): pass", "issue")


class RecordedHeldout2TestsMissImports(unittest.TestCase):
    def test_every_recorded_execution_is_refused_before_a_sandbox_run(self):
        adapter = static_adapter()
        expected = {
            "rc24_heldout2_t1_a1.test.mjs": "import { describe, it } from 'node:test';",
            "rc24_heldout2_t1_a2.test.mjs": "import { describe, it } from 'node:test';",
            "rc24_heldout2_t1_a3.test.mjs": "import { it } from 'node:test';",
            "rc24_heldout2_t3_a1.test.mjs": "import { describe, it } from 'node:test';",
            "rc24_heldout2_t3_a2.test.mjs": "import { it } from 'node:test';",
            "rc24_heldout2_t3_a3.test.mjs": "import { describe, it } from 'node:test';",
        }
        for name, line in expected.items():
            with self.subTest(name):
                content = (FIX / name).read_text(encoding="utf-8")
                with self.assertRaises(ValueError) as caught:
                    adapter.validate_generated_test(content, "test_patchproof_issue_2.test.mjs")
                self.assertIn("Add exactly: " + line, str(caught.exception))
                self.assertIn("not evidence about the bug", str(caught.exception))

    def test_a_bare_jsdom_import_gets_the_exact_loader_line(self):
        adapter = static_adapter()
        for name in ("rc24_heldout2_t1_a1.test.mjs", "rc24_heldout2_t3_a1.test.mjs"):
            with self.subTest(name):
                content = (FIX / name).read_text(encoding="utf-8")
                with self.assertRaises(ValueError) as caught:
                    adapter.validate_generated_test(content, "test_patchproof_issue_2.test.mjs")
                self.assertIn(
                    "createRequire('/opt/patchproof/node/package.json')('jsdom')", str(caught.exception))

    def test_the_same_test_with_its_imports_added_is_accepted(self):
        adapter = static_adapter()
        content = (FIX / "rc24_heldout2_t1_a3.test.mjs").read_text(encoding="utf-8")
        fixed = "import { it } from 'node:test';\n" + content
        adapter.validate_generated_test(fixed, "test_patchproof_issue_2.test.mjs")
        adapter.validate_generated_pins(fixed, HELDOUT_2_ISSUE)

    def test_node_package_tests_get_the_same_check(self):
        adapter = adapter_for("node-package", {
            "package.json": json.dumps({"name": "x", "scripts": {"test": "node --test"}}),
            "lib/a.js": "module.exports = 1;\n",
        })
        self.assertEqual(adapter.id, "node-package")
        with self.assertRaisesRegex(ValueError, "Add exactly: import \\{ it \\} from 'node:test';"):
            adapter.validate_generated_test("it('x', () => {});\n", "test_patchproof_issue_2.test.mjs")


class ReferenceErrorFeedback(unittest.TestCase):
    CLASSIFICATION = "test failed without accepted assertion evidence"

    def test_it_is_not_defined_names_the_missing_import(self):
        content = (FIX / "rc24_heldout2_t1_a3.test.mjs").read_text(encoding="utf-8")
        output = (FIX / "rc24_heldout2_t1_a3.tap").read_text(encoding="utf-8")
        self.assertIn("ReferenceError: it is not defined", output)
        feedback = proof.reproduction_feedback(content, self.CLASSIFICATION, output)
        self.assertIn("ENGINE DIAGNOSIS: `it` is not defined at runtime", feedback)
        self.assertIn("Add exactly: import { it } from 'node:test';", feedback)
        self.assertIn("not evidence about the bug", feedback)

    def test_describe_is_not_defined_names_the_missing_import(self):
        content = (FIX / "rc24_heldout2_t3_a3.test.mjs").read_text(encoding="utf-8")
        output = (FIX / "rc24_heldout2_t3_a3.tap").read_text(encoding="utf-8")
        feedback = proof.reproduction_feedback(content, self.CLASSIFICATION, output)
        self.assertIn("`describe` is not defined", feedback)
        self.assertIn("import { describe, it } from 'node:test';", feedback)

    def test_it_falls_back_when_the_file_already_imports_what_it_calls(self):
        content = "import { it } from 'node:test';\nit('x', () => { assert.ok(1); });\n"
        feedback = proof.reproduction_feedback(
            content, self.CLASSIFICATION, "ReferenceError: assert is not defined")
        self.assertIn("import assert from 'node:assert/strict';", feedback)

    def test_other_failures_do_not_get_this_diagnosis(self):
        feedback = proof.reproduction_feedback("x", self.CLASSIFICATION, "AssertionError: nope")
        self.assertNotIn("is not defined at runtime", feedback)


class ImportCheckTable(unittest.TestCase):
    ASSERT_STRICT = "import assert from 'node:assert/strict';"
    CASES = {
        "default test and default assert":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "test('a', () => { assert.ok(1); });", []),
        "named describe and it, strict as assert":
            ("import { describe, it } from 'node:test';\nimport { strict as assert } from 'node:assert';\n"
             "describe('x', () => { it('y', () => { assert.ok(1); }); });", []),
        "nothing imported":
            ("describe('x', () => { it('y', () => { assert.ok(1); }); });",
             ["import { describe, it } from 'node:test';", "import assert from 'node:assert/strict';"]),
        "test imported but describe called":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "describe('x', () => { test('y', () => { assert.ok(1); }); });",
             ["import { describe } from 'node:test';"]),
        "commonjs destructure":
            ("const { test } = require('node:test');\nconst assert = require('node:assert/strict');\n"
             "test('a', () => { assert.ok(1); });", []),
        "commonjs describe and it":
            ("const { describe, it } = require('node:test');\nconst assert = require('assert');\n"
             "describe('a', () => { it('b', () => { assert.ok(1); }); });", []),
        "namespace import":
            ("import * as nt from 'node:test';\nimport assert from 'node:assert';\n"
             "nt.test('a', () => { assert.ok(1); });", []),
        "dynamic import":
            ("const { test } = await import('node:test');\n"
             "const assert = (await import('node:assert/strict')).default;\n"
             "test('a', () => { assert.ok(1); });", []),
        "subtests through t.test":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "test('a', async (t) => { await t.test('b', () => { assert.ok(1); }); });", []),
        "own helper named it":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "function it(x) { return x; }\ntest('a', () => { assert.ok(it(1)); });", []),
        "it( inside a string":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "test('a', () => { assert.ok(true, 'make it(now)'); });", []),
        "it( inside a comment":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "// it(should work)\ntest('a', () => { assert.ok(1); });", []),
        "it( inside a template literal":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "test('a', () => { const s = `do it(${1})`; assert.ok(s); });", []),
        "test.only":
            ("import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "test.only('a', () => { assert.ok(1); });", []),
        "named assert function":
            ("import test from 'node:test';\nimport { ok } from 'node:assert/strict';\n"
             "test('a', () => { ok(1); });", []),
        "hook not imported":
            ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
             "before(() => {});\ntest('a', () => { assert.ok(1); });", ["import { before } from 'node:test';"]),
        "assert not imported":
            ("import test from 'node:test';\ntest('a', () => { assert.ok(1); });",
             ["import assert from 'node:assert/strict';"]),
    }

    def test_table(self):
        for name, (source, expected) in self.CASES.items():
            with self.subTest(name):
                self.assertEqual(runtimes.missing_node_test_imports(source), expected)

    def test_bare_jsdom_detection(self):
        self.assertTrue(runtimes.imports_bare_jsdom("import { JSDOM } from 'jsdom';"))
        self.assertTrue(runtimes.imports_bare_jsdom("const { JSDOM } = require('jsdom');"))
        self.assertFalse(runtimes.imports_bare_jsdom(
            "createRequire('/opt/patchproof/node/package.json')('jsdom')"))
        self.assertFalse(runtimes.imports_bare_jsdom("// import x from 'jsdom'"))

    def test_node_typescript_now_also_refuses_describe_without_its_import(self):
        content = ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
                   "describe('x', () => { test('y', () => { assert.ok(1); }); });\n")
        with self.assertRaisesRegex(ValueError, "Add exactly: import \\{ describe \\} from 'node:test';"):
            typescript_adapter().validate_generated_test(content, "tests/.t.test.ts")


class SourceCheckHelperTests(unittest.TestCase):
    def project(self, tsconfig: str = "{}\n") -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / "tsconfig.json").write_text(tsconfig, encoding="utf-8")
        compiler = root / "node_modules/.bin/tsc"
        compiler.parent.mkdir(parents=True)
        compiler.write_text("placeholder\n", encoding="utf-8")
        return root

    def run_main(self, root: Path, arguments: list[str], fake):
        previous = Path.cwd()
        try:
            os.chdir(root)
            with patch.object(source_check.subprocess, "run", side_effect=fake):
                return source_check.main(["typescript_source_check.py", *arguments])
        finally:
            os.chdir(previous)

    def test_the_generated_config_extends_the_project_and_is_removed_afterwards(self):
        root = self.project('{"compilerOptions": {"types": ["vite/client"]}}\n')
        seen: dict = {}

        def fake(command, **kwargs):
            self.assertEqual(kwargs["cwd"], root)
            if "--showConfig" in command:
                return type("Result", (), {"returncode": 0, "stdout": (root / "tsconfig.json").read_text()})()
            config = Path(command[command.index("--project") + 1])
            seen.update(json.loads(config.read_text(encoding="utf-8")))
            return type("Result", (), {"returncode": 0})()

        self.assertEqual(self.run_main(root, ["--project"], fake), 0)
        self.assertEqual(seen["extends"], "./tsconfig.json")
        # Whole project: the config adds neither files nor include, so the project's own apply.
        self.assertNotIn("files", seen)
        self.assertNotIn("include", seen)
        self.assertNotIn("types", seen["compilerOptions"])  # source checks retain the project contract
        self.assertTrue(seen["compilerOptions"]["noEmit"])
        self.assertFalse(seen["compilerOptions"]["composite"])
        self.assertEqual(list(root.glob(".patchproof-source-tsconfig-*.json")), [])

    def test_a_project_without_a_types_list_keeps_its_default(self):
        root = self.project("{}\n")
        self.assertNotIn("types", source_check.check_options({}))

    def test_a_compiler_failure_is_exit_one_and_everything_else_is_exit_two(self):
        root = self.project()
        failing = lambda command, **kwargs: type("Result", (), {"returncode": 0, "stdout": "{}"})() if "--showConfig" in command else type("Result", (), {"returncode": 2})()
        self.assertEqual(self.run_main(root, ["--project"], failing), 1)
        for bad in ([], ["src/a.ts"], ["--", "src/a.ts"], ["--project", "src/a.ts"]):
            with self.subTest(bad):
                self.assertEqual(self.run_main(root, bad, failing), 2)

        def slow(command, **kwargs):
            raise source_check.subprocess.TimeoutExpired(command, 1)

        self.assertEqual(self.run_main(root, ["--project"], slow), 2)

    def test_a_missing_compiler_or_config_means_the_check_is_unavailable(self):
        root = self.project()
        (root / "node_modules/.bin/tsc").unlink()
        self.assertEqual(self.run_main(root, ["--project"], lambda *a, **k: None), 2)
        root = self.project()
        (root / "tsconfig.json").unlink()
        self.assertEqual(self.run_main(root, ["--project"], lambda *a, **k: None), 2)

    def test_a_references_only_root_config_declines_to_run(self):
        root = self.project('{"files": [], "references": [{"path": "./tsconfig.app.json"}]}\n')
        result = type("Result", (), {"returncode": 0, "stdout": (root / "tsconfig.json").read_text()})()
        self.assertEqual(self.run_main(root, ["--project"], lambda *a, **k: result), 2)


@unittest.skipUnless(os.environ.get("TS_LINT_NODE_MODULES"),
                     "Set TS_LINT_NODE_MODULES to installed TypeScript node_modules")
class SourceCheckWithARealCompiler(unittest.TestCase):
    def project(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        (root / "src").mkdir()
        (root / "src/ok.ts").write_text("export const ok: number = 1;\n", encoding="utf-8")
        (root / "node_modules").symlink_to(
            Path(os.environ["TS_LINT_NODE_MODULES"]).resolve(), target_is_directory=True)
        return root

    def invoke(self, root: Path):
        import subprocess
        import sys
        return subprocess.run(
            [sys.executable, str(ROOT / "patchproof_runtime/typescript_source_check.py"), "--project"],
            cwd=root, capture_output=True, text=True, check=False)

    def test_a_valid_project_passes_and_an_await_outside_async_fails_with_the_diagnostic(self):
        root = self.project()
        ok = self.invoke(root)
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "PATCHPROOF_SOURCE_CHECK=passed"))
        (root / "src/bad.ts").write_text(
            "export const bad = () => { await Promise.resolve(); };\n", encoding="utf-8")
        bad = self.invoke(root)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("TS1308", bad.stdout)
        self.assertIn("src/bad.ts", bad.stdout)
        self.assertIn("PATCHPROOF_SOURCE_CHECK=failed", bad.stderr)
        self.assertEqual(list(root.glob(".patchproof-source-tsconfig-*.json")), [])

    def test_an_edit_that_breaks_a_caller_in_another_file_is_caught(self):
        root = self.project()
        (root / "src/use.ts").write_text(
            "import { ok } from './ok';\nexport const doubled: number = ok * 2;\n", encoding="utf-8")
        self.assertEqual(self.invoke(root).returncode, 0)
        (root / "src/ok.ts").write_text("export const ok: string = 'one';\n", encoding="utf-8")
        broken = self.invoke(root)
        self.assertEqual(broken.returncode, 1)
        self.assertIn("src/use.ts", broken.stdout)

    def test_ambient_module_declarations_are_part_of_the_program(self):
        root = self.project()
        (root / "src/globals.d.ts").write_text("declare module '*.css';\n", encoding="utf-8")
        (root / "src/page.ts").write_text("import './page.css';\nexport const page = 1;\n", encoding="utf-8")
        self.assertEqual(self.invoke(root).returncode, 0)


class CandidateFeedbackTests(unittest.TestCase):
    def test_feedback_carries_compiler_output_and_the_diff_and_nothing_else(self):
        feedback = proof.source_check_feedback(
            "src/a.ts(3,5): error TS1308: await is only allowed\nPATCHPROOF_SOURCE_CHECK=failed",
            "--- src/a.ts\n+++ src/a.ts\n+  await x;",
        )
        self.assertIn("TS1308", feedback)
        self.assertNotIn("PATCHPROOF_SOURCE_CHECK=", feedback)
        self.assertIn("PREVIOUS PROPOSAL DIFF", feedback)
        self.assertIn("make the enclosing function async", feedback)
        self.assertIn("ran before any hidden test", feedback)

    def test_credentials_are_redacted_from_the_feedback(self):
        with patch.dict(os.environ, {"NEBIUS_API_KEY": "sekrit-key"}):
            feedback = proof.source_check_feedback("error sekrit-key", "diff")
        self.assertNotIn("sekrit-key", feedback)


if __name__ == "__main__":
    unittest.main()
