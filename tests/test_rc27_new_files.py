"""rc.27: bounded repairs may create new source files, only in folders the maintainer declared."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import proof
from agent_budget import Limits, RunBudget
from agent_loop import AgentSession
from context_tools import RepositorySnapshot
from runtimes import detect_runtime
from scope_policy import check_paths, validate_scope
from tests import support_pipeline as pipeline

SCOPE = {"new_file_dirs": ["src/util"]}


def project(config=None):
    root = Path(tempfile.mkdtemp(prefix="newfiles-"))
    put = lambda name, text: pipeline.write(root, name, text)
    put("package.json", json.dumps({"type": "module", "scripts": {"test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
    put("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"NodeNext","strict":true,"allowImportingTsExtensions":true,"types":[],"noEmit":true},"include":["src/**/*.ts"]}')
    put("src/value.ts", "export const value = (): number => 1;\n")
    put("src/util/seed.ts", "export const seed = 7;\n")
    put("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; import {value} from '../src/value.ts'; test('number', () => assert.equal(typeof value(), 'number'));\n")
    put("patchproof.json", json.dumps({"runtime": "node-typescript", "scope": config or SCOPE}))
    return root


class ScopeRuleTests(unittest.TestCase):
    def test_new_file_dirs_validation(self):
        self.assertEqual(validate_scope(SCOPE), SCOPE)
        for bad in ([], "src", ["../x"], ["/abs"], [".hidden"], ["a", "a"], ["a"] * 6, [""], ["src\\\\x"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_scope({"new_file_dirs": bad})

    def test_check_paths_allows_creation_only_inside_declared_folders(self):
        root = project()
        check_paths(root, [{"path": "src/util/two.ts", "content": "x"}], SCOPE)
        for path in ("src/other/two.ts", "two.ts", "src/utility/two.ts"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "scope_failed"):
                check_paths(root, [{"path": path, "content": "x"}], SCOPE)
        with self.assertRaisesRegex(ValueError, "scope_failed"):
            check_paths(root, [{"path": "src/util/two.ts", "content": "x"}], {})  # no declaration, no new files


class CreationToolTests(unittest.TestCase):
    def setUp(self):
        self.root = project()
        self.adapter = detect_runtime(self.root)
        self.snapshot = RepositorySnapshot(self.root, self.adapter, proof.EXCLUDED_DIRS, proof.PROTECTED_NAMES, proof.is_protected_path)
        self.tools = self.snapshot.tools(self.snapshot.editable, ["src/util"])

    def create(self, path, content="export const two = (): number => 2;\n"):
        return self.tools.prepare_creation(path, content, self.adapter)

    def test_valid_creation_is_readable_and_editable_in_the_same_session(self):
        changes = self.create("src/util/two.ts")
        self.assertEqual([c["path"] for c in changes], ["src/util/two.ts"])
        self.tools.accept(changes)
        read = self.tools.invoke({"action": "read", "path": "src/util/two.ts"})
        self.assertEqual(read["lines"][0]["text"], "export const two = (): number => 2;")
        edited = self.tools.prepare_edits([{"path": "src/util/two.ts", "old": "=> 2;", "new": "=> 3;"}], self.adapter)
        self.assertIn("=> 3;", edited[0]["content"])

    def test_refusals(self):
        cases = {
            "outside folder": ("src/value2.ts", "scope_failed"),
            "traversal": ("src/util/../../x.ts", "scope_failed"),
            "hidden": ("src/util/.secret.ts", "scope_failed"),
            "test path": ("src/util/two.test.ts", "scope_failed"),
            "wrong extension": ("src/util/two.json", "scope_failed"),
            "generated dir": ("src/util/node_modules/x.ts", "scope_failed"),
            "existing file": ("src/util/seed.ts", "already exists"),
        }
        for name, (path, message) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                self.create(path)
        with self.assertRaisesRegex(ValueError, "non-empty"):
            self.create("src/util/empty.ts", "   ")
        with self.assertRaisesRegex(ValueError, "200000"):
            self.create("src/util/big.ts", "// " + "x" * 200_001)

    def test_existing_but_unlisted_file_on_disk_is_not_replaced(self):
        (self.root / "src/util/data.ts").write_text("export const hidden = 1;\n")  # exists, not in a stale snapshot
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.create("src/util/data.ts")

    def test_at_most_three_new_files(self):
        for index in range(3):
            self.tools.accept(self.create(f"src/util/f{index}.ts", f"export const f{index} = {index};\n"))
        with self.assertRaisesRegex(ValueError, "at most three"):
            self.create("src/util/f3.ts")

    def test_disabled_without_a_declaration(self):
        tools = self.snapshot.tools(self.snapshot.editable)
        with self.assertRaisesRegex(ValueError, "not enabled"):
            tools.prepare_creation("src/util/two.ts", "export const two = 2;\n", self.adapter)

    def test_verifier_cannot_create_and_solver_prompt_advertises_the_tool_only_when_declared(self):
        def session(role, scope):
            return AgentSession(role=role, snapshot=self.snapshot, allowed_paths=self.snapshot.editable, adapter=self.adapter,
                                issue_text="x", scope=scope, model_call=lambda *a: {"action": "finish", "summary": "s"},
                                run_check=lambda *a: {"passed": True}, validate_changes=lambda c: None,
                                budget=RunBudget(Limits()), record={}, max_steps=4)
        self.assertIn('"action":"create"', session("solver", SCOPE).system)
        self.assertNotIn('"action":"create"', session("solver", {}).system)
        verifier = session("verifier", SCOPE)
        verifier.model_call = lambda *a: next(iter([{"action": "create", "path": "src/util/a.ts", "content": "export const a = 1;\n"}, {"action": "finish", "summary": "s"}]))
        sequence = iter([{"action": "create", "path": "src/util/a.ts", "content": "export const a = 1;\n"},
                         {"action": "finish", "summary": "s"}])
        verifier.model_call = lambda *a: next(sequence)
        verifier.run()
        self.assertIn("read-only", json.dumps(verifier.events[0]["observation"]))


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class BoundedPipelineTests(unittest.TestCase):
    TEST = """import test from 'node:test';
import assert from 'node:assert/strict';
import { value } from '../src/value.ts';
test('value is two', () => { assert.equal(value(), 2); });
"""

    def run_case(self, scope, solver_actions, mode="bounded"):
        root = project(scope)
        (root / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
        queue = list(solver_actions)

        def model_json(*, api_key, model, system, user, temperature):
            if "independent verifier" in system:
                return {"action": "finish", "summary": "value() lives in src/value.ts"}
            return queue.pop(0)

        base = Path(tempfile.mkdtemp())
        return root, *pipeline.run_engine(base, root, root, proof.Issue(1, "Wrong value", "value() must return 2."),
                                          self.TEST, None, mode=mode, model_json=model_json)

    ACTIONS = [
        {"action": "read", "path": "src/value.ts"},
        {"action": "create", "path": "src/util/two.ts", "content": "export const two = (): number => 2;\n"},
        {"action": "edit", "edits": [{"path": "src/value.ts", "old": "export const value = (): number => 1;",
                                      "new": "import { two } from './util/two.ts';\nexport const value = (): number => two();"}]},
        {"action": "finish", "summary": "Use a helper for the constant."},
    ]

    def test_repair_that_needs_a_new_file_is_verified_and_delivered(self):
        root, result, record, error = self.run_case(SCOPE, self.ACTIONS)
        self.assertIsNone(error, json.dumps(record, indent=2, default=str)[:4000])
        self.assertEqual(result["verdict"], "verified")
        self.assertTrue((root / "src/util/two.ts").is_file())
        delivered = {item["path"] for item in result["pr_files"]}
        self.assertIn("src/util/two.ts", delivered)
        self.assertIn("src/value.ts", delivered)
        self.assertIn("/dev/null", result["candidates"][0]["diff"])
        self.assertEqual(subprocess.run(["npm", "test"], cwd=root, capture_output=True, text=True, timeout=60).returncode, 0)

    def test_creation_outside_the_declared_folder_is_refused_and_nothing_is_delivered(self):
        actions = [{"action": "read", "path": "src/value.ts"},
                   {"action": "create", "path": "src/elsewhere/two.ts", "content": "export const two = (): number => 2;\n"},
                   {"action": "finish", "summary": "gave up"}]
        root, result, record, error = self.run_case(SCOPE, actions)
        self.assertIsNotNone(error)
        events = record["agent_sessions"]["solvers"][0]["events"]
        self.assertIn("scope_failed", json.dumps(events))
        self.assertFalse((root / "src/elsewhere").exists())
        self.assertEqual((root / "src/value.ts").read_text(), "export const value = (): number => 1;\n")

    def test_legacy_mode_refuses_a_scope_that_allows_new_files(self):
        root, result, record, error = self.run_case(SCOPE, [], mode="legacy")
        self.assertIsNotNone(error)
        self.assertIn("bounded", str(error))

    def test_a_declared_folder_must_exist(self):
        root, result, record, error = self.run_case({"new_file_dirs": ["src/missing"]}, [])
        self.assertIsNotNone(error)
        self.assertIn("not an existing folder", str(error))


if __name__ == "__main__":
    unittest.main()
