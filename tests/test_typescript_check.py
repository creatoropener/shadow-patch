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

        def fake_run(command, **kwargs):
            config_path = Path(command[command.index("--project") + 1])
            captured.update(json.loads(config_path.read_text(encoding="utf-8")))
            self.assertEqual(kwargs["cwd"], root)
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
        self.assertEqual(list(root.glob(".patchproof-tsconfig-*.json")), [])
        self.assertEqual(list(root.glob(".patchproof-runtime-*.d.ts")), [])


if __name__ == "__main__":
    unittest.main()
