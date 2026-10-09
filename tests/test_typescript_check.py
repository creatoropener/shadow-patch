from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from patchproof_runtime.typescript_check import checked_target, main


class TypeScriptCheckTests(unittest.TestCase):
    def make_project(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        (root / "sample.test.ts").write_text("export {};\n", encoding="utf-8")
        compiler = root / "node_modules" / ".bin" / "tsc"
        compiler.parent.mkdir(parents=True)
        compiler.write_text("placeholder\n", encoding="utf-8")
        return root

    def test_rejects_path_outside_repository(self) -> None:
        root = self.make_project()
        with self.assertRaisesRegex(ValueError, "relative .ts"):
            checked_target("../outside.test.ts", root)

    def test_generates_project_config_and_cleans_temporary_files(self) -> None:
        root = self.make_project()
        captured: dict = {}
        commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            commands.append(command)
            self.assertEqual(kwargs["cwd"], root)
            if "--showConfig" in command:
                return type("Result", (), {"returncode": 0, "stdout": (root / "tsconfig.json").read_text()})()
            if command[0] == "node":
                self.assertTrue(command[1].endswith("typescript_test_lint.mjs"))
                return type("Result", (), {"returncode": 0})()
            config_path = Path(command[command.index("--project") + 1])
            captured.update(json.loads(config_path.read_text(encoding="utf-8")))
            return type("Result", (), {"returncode": 0})()

        previous = Path.cwd()
        try:
            os.chdir(root)
            with patch(
                "patchproof_runtime.typescript_check.subprocess.run",
                side_effect=fake_run,
            ):
                self.assertEqual(main(["typescript_check.py", "sample.test.ts"]), 0)
        finally:
            os.chdir(previous)

        self.assertEqual(captured["extends"], "./tsconfig.json")
        self.assertEqual(captured["files"][0], "sample.test.ts")
        self.assertEqual(len(commands), 3)
        self.assertEqual(list(root.glob(".patchproof-tsconfig-*.json")), [])
        self.assertEqual(list(root.glob(".patchproof-runtime-*.d.ts")), [])

    def capture_generated_types(self, root: Path) -> object:
        # QRcrafts (a Vite project) restricts "types" to ["vite/client"] in
        # its own tsconfig.json. That restriction is inherited via `extends`
        # and silently drops @types/node's ambient node:test/node:assert
        # declarations for this check-only pass -- even though @types/node
        # is installed and tsx itself doesn't care. Every generated
        # regression imports 'node:test', so this must keep whatever the
        # project already restricted "types" to and add "node" to it.
        captured: dict = {}

        def fake_run(command, **kwargs):
            if "--showConfig" in command:
                return type("Result", (), {"returncode": 0, "stdout": (root / "tsconfig.json").read_text()})()
            if command[0] == "node":
                return type("Result", (), {"returncode": 0})()
            config_path = Path(command[command.index("--project") + 1])
            captured.update(json.loads(config_path.read_text(encoding="utf-8")))
            return type("Result", (), {"returncode": 0})()

        previous = Path.cwd()
        try:
            os.chdir(root)
            with patch(
                "patchproof_runtime.typescript_check.subprocess.run",
                side_effect=fake_run,
            ):
                self.assertEqual(main(["typescript_check.py", "sample.test.ts"]), 0)
        finally:
            os.chdir(previous)
        return captured["compilerOptions"].get("types")

    def test_adds_node_to_a_restricted_types_array_without_dropping_it(self) -> None:
        root = self.make_project()
        (root / "tsconfig.json").write_text(
            json.dumps({"compilerOptions": {"types": ["vite/client"]}}), encoding="utf-8"
        )
        self.assertEqual(self.capture_generated_types(root), ["vite/client", "node"])

    def test_leaves_types_untouched_when_project_does_not_restrict_it(self) -> None:
        # file-sharing-app's tsconfig has no "types" key at all, so every
        # @types/* package (including @types/node) is already included by
        # TypeScript's own default behavior. Adding our own "types" override
        # here would needlessly *narrow* that back down -- so this must be a
        # no-op in that case, not just an addition.
        root = self.make_project()
        self.assertIsNone(self.capture_generated_types(root))

    def test_stops_before_typecheck_when_semantic_lint_fails(self) -> None:
        root = self.make_project()
        previous = Path.cwd()
        try:
            os.chdir(root)
            with patch(
                "patchproof_runtime.typescript_check.subprocess.run",
                side_effect=lambda command, **k: type("Result", (), {"returncode": 0, "stdout": "{}"})() if "--showConfig" in command else type("Result", (), {"returncode": 2})(),
            ) as run:
                self.assertEqual(main(["typescript_check.py", "sample.test.ts"]), 2)
        finally:
            os.chdir(previous)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(list(root.glob(".patchproof-tsconfig-*.json")), [])


if __name__ == "__main__":
    unittest.main()
