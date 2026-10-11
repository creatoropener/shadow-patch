"""rc.27: a self-contained subfolder can be the project; .mts/.cts sources are editable."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtimes import RuntimeDetectionError, detect_runtime, resolve_project_root
from scope_policy import CONFIG_ROOT, load_scope
import proof
import tools.pr_files as pr_files
import hashlib
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEPS = Path(os.environ.get("TS_LINT_NODE_MODULES", "/missing"))


def repo(config: dict | None, layout: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="root-"))
    if config is not None:
        (root / "patchproof.json").write_text(json.dumps(config))
    for name, text in layout.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


PACKAGE = json.dumps({"name": "server", "scripts": {"test": "node --test"}})


class ProjectRootTests(unittest.TestCase):
    def test_default_root_is_the_checkout(self):
        root = repo(None, {"package.json": PACKAGE})
        self.assertEqual(resolve_project_root(root), root.resolve())
        self.assertEqual(detect_runtime(root).id, "node-package")

    def test_root_selects_a_subfolder_for_detection_and_install(self):
        root = repo({"root": "server"}, {"server/package.json": PACKAGE, "server/tsconfig.json": "{}",
                                         "server/pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
                                         "client/package.json": json.dumps({"name": "client"})})
        self.assertEqual(resolve_project_root(root), (root / "server").resolve())
        adapter = detect_runtime(root)
        self.assertEqual((adapter.id, adapter.package_manager), ("node-typescript", "pnpm"))

    def test_unsafe_or_missing_roots_are_refused(self):
        for value in ("../outside", "/abs", "server/../x", "./server", "missing", "server\\x"):
            with self.subTest(value=value):
                root = repo({"root": value}, {"server/package.json": PACKAGE})
                with self.assertRaises(RuntimeDetectionError):
                    resolve_project_root(root)

    def test_symlinked_root_is_refused(self):
        root = repo({"root": "link"}, {"real/package.json": PACKAGE})
        (root / "link").symlink_to(root / "real")
        with self.assertRaisesRegex(RuntimeDetectionError, "not a folder"):
            resolve_project_root(root)

    def test_workspace_projects_are_refused_not_half_supported(self):
        cases = {
            "pnpm-workspace.yaml": {"pnpm-workspace.yaml": "packages: ['server']\n", "server/package.json": PACKAGE},
            "workspaces": {"package.json": json.dumps({"workspaces": ["server"]}), "server/package.json": PACKAGE},
            "workspace dep": {"server/package.json": json.dumps({"dependencies": {"shared": "workspace:*"}})},
            "file sibling": {"server/package.json": json.dumps({"devDependencies": {"shared": "file:../shared"}})},
        }
        for name, layout in cases.items():
            with self.subTest(name=name):
                root = repo({"root": "server"}, layout)
                with self.assertRaisesRegex(RuntimeDetectionError, "workspace"):
                    detect_runtime(root)

    def test_scope_is_read_from_the_checkout_but_applied_to_the_project(self):
        root = repo({"root": "server", "scope": {"allowed_paths": ["src/a.ts"]}},
                    {"server/package.json": PACKAGE, "server/src/a.ts": "export const a = 1;\n"})
        project = resolve_project_root(root)
        token = CONFIG_ROOT.set(root.resolve())
        try:
            self.assertEqual(load_scope(project), {"allowed_paths": ["src/a.ts"]})
        finally:
            CONFIG_ROOT.reset(token)
        self.assertEqual(load_scope(project), {})  # without the checkout config the folder has none

    def test_pr_paths_are_checkout_relative_and_hash_verified(self):
        root = repo({"root": "server"}, {"server/package.json": PACKAGE, "server/src/a.ts": "export const a = 2;\n"})
        digest = hashlib.sha256(b"export const a = 2;\n").hexdigest()
        proof_doc = {"verdict": "verified", "clean_replay": {"passed": True},
                     "pr_files": [{"path": "server/src/a.ts", "sha256": digest}]}
        (root / "proof.json").write_text(json.dumps(proof_doc))
        self.assertEqual(pr_files.verified_paths(root), [":(literal)server/src/a.ts"])

    def test_typescript_module_variants_are_editable_and_context(self):
        root = repo(None, {"package.json": PACKAGE, "tsconfig.json": "{}"})
        adapter = detect_runtime(root)
        for name in ("src/a.mts", "src/b.cts", "src/c.ts", "src/d.tsx"):
            self.assertTrue(adapter.is_editable_source(Path(name)), name)
            self.assertTrue(adapter.is_context_file(Path(name)), name)
        self.assertFalse(adapter.is_editable_source(Path("README.md")))


@unittest.skipUnless((DEPS / ".bin/tsx").exists(), "requires TypeScript, @types/node and tsx")
class SubfolderPipelineTests(unittest.TestCase):
    def test_pipeline_runs_inside_a_subfolder_and_delivers_checkout_relative_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            checkout = base / "checkout"
            project = checkout / "server"
            project.mkdir(parents=True)
            def put(name, text, folder=project):
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            put("package.json", json.dumps({"type": "module", "scripts": {"test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
            put("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"NodeNext","strict":true,"allowImportingTsExtensions":true,"types":[]},"include":["src/**/*.mts"]}')
            original = "export const value = (): number => 1;\n"
            put("src/value.mts", original)
            put("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; import {value} from '../src/value.mts'; test('exists', () => assert.equal(typeof value(), 'number'));\n")
            (project / "node_modules").symlink_to(DEPS.resolve(), target_is_directory=True)
            put("patchproof.json", json.dumps({"root": "server", "runtime": "node-typescript",
                                               "scope": {"allowed_paths": ["src/value.mts"]}}), checkout)
            initial = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*")
                       if p.is_file() and "node_modules" not in p.parts}
            count = 0

            class LocalState:
                def __init__(self, files, code=0, output=""):
                    self.files, self.exit_code, self.stdout, self.stderr, self.uuid = files, code, output, "", "local"

                def apply_files(self, *, files):
                    return LocalState({**self.files, **{k.removeprefix("/workspace/repo/"): v for k, v in files.items()}})

                def run(self, *, shell, cwd, timeout, disposable):
                    nonlocal count
                    count += 1
                    directory = base / f"sandbox-{count}"
                    directory.mkdir()
                    for name, value in self.files.items():
                        target = directory / ("private/" + Path(name).name if name.startswith("/patchproof/") else name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(value)
                    (directory / "node_modules").symlink_to(DEPS.resolve(), target_is_directory=True)
                    command = shell.replace("/patchproof/candidate-policy.json", str(directory / "private/candidate-policy.json"))
                    command = command.replace("/opt/patchproof/node/node_modules/", str(DEPS.resolve()) + "/")
                    command = command.replace("/patchproof/", str(ROOT / "patchproof_runtime") + "/")
                    result = subprocess.run(command, shell=True, cwd=directory, capture_output=True, text=True, timeout=timeout,
                                            env={**os.environ, "PATCHPROOF_TYPESCRIPT_RUNTIME": str(DEPS.parent)})
                    state = LocalState(self.files, result.returncode, result.stdout + result.stderr)
                    return SimpleNamespace(wait=lambda: state)

            content = """import test from 'node:test';
import assert from 'node:assert/strict';
import { value } from '../src/value.mts';
test('value is two', () => { assert.equal(value(), 2); });
"""
            reply = f"{proof.TEST_BEGIN}\n{content}\n{proof.TEST_END}\n{proof.RATIONALE_BEGIN}\nFix it.\n{proof.RATIONALE_END}"
            sdk = SimpleNamespace(images=SimpleNamespace(use=lambda *a, **k: object()))
            env = {"NEBIUS_API_KEY": "x", "NEBIUS_PROJECT_ID": "x", "NEBIUS_MODEL": "x", "CONTREE_IMAGE": "x"}
            with patch.dict(os.environ, env), patch.object(proof, "create_sandbox_client", return_value=sdk), \
                    patch.object(proof, "sandbox_workspace", side_effect=lambda *a, **k: LocalState(initial)), \
                    patch.object(proof, "model_text", return_value=reply), \
                    patch.object(proof, "generate_candidate",
                                 side_effect=lambda **k: ([{"path": "src/value.mts", "content": original.replace("1", "2")}], "two")):
                record = {"candidates": []}
                try:
                    result = proof.execute(checkout, proof.Issue(1, "Wrong value", "value() must return 2."), record)
                except proof.PatchProofError as error:
                    self.fail(str(error) + "\n" + json.dumps(record, indent=2, default=str))
            self.assertEqual(result["verdict"], "verified")
            self.assertEqual(result["project_root"], "server")
            self.assertEqual(result["engine"]["app_version"], proof.APP_VERSION)
            self.assertIn("runtimes.py", result["engine_provenance"])
            self.assertIn("server/package.json", result["project_inputs"])
            self.assertIn("patchproof.json", result["project_inputs"])
            self.assertEqual(len(result["archive_sha256"]), 64)
            self.assertIn("toolchain", result["runtime"])
            self.assertEqual(result["runtime"]["package_manager"]["name"], "npm")
            self.assertTrue(all(item["path"].startswith("server/") for item in result["pr_files"]), result["pr_files"])
            self.assertEqual((project / "src/value.mts").read_text(), original.replace("1", "2"))
            self.assertFalse((project / "proof.json").exists())
            (checkout / "proof.json").write_text(json.dumps(result))
            self.assertTrue(all(path.startswith(":(literal)server/") for path in pr_files.verified_paths(checkout)))
            self.assertEqual(subprocess.run(["npm", "test"], cwd=project, capture_output=True, text=True, timeout=60).returncode, 0)


if __name__ == "__main__":
    unittest.main()
