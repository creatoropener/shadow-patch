from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtimes import detect_runtime
from proof import render_report


class NodeTypeScriptContractTests(unittest.TestCase):
    def make_project(self, *, explicit: bool = False) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"test": "tsx --test tests/*.test.ts"}}),
            encoding="utf-8",
        )
        (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        if explicit:
            (root / "patchproof.json").write_text(
                json.dumps({"runtime": "node-typescript"}), encoding="utf-8"
            )
        return root

    def test_detects_typescript_project_without_custom_loader(self) -> None:
        adapter = detect_runtime(self.make_project())
        self.assertEqual(adapter.id, "node-typescript")
        self.assertEqual(adapter.test_path(3), "test_patchproof_issue_3.test.ts")
        self.assertIn("/opt/patchproof/node/node_modules/.bin/tsx", adapter.regression_command("x.test.ts"))

    def test_explicit_typescript_runtime_is_supported(self) -> None:
        adapter = detect_runtime(self.make_project(explicit=True))
        self.assertEqual(adapter.id, "node-typescript")

    def test_rejects_retired_loader(self) -> None:
        adapter = detect_runtime(self.make_project())
        with self.assertRaisesRegex(ValueError, "retired TypeScript loader"):
            adapter.validate_generated_test(
                "import { loadStandaloneTypeScript } from './patchproof_runtime/typescript_module.mjs';",
                "test_patchproof_issue_3.test.ts",
            )

    def test_web_stream_test_must_use_engine_helpers(self) -> None:
        adapter = detect_runtime(self.make_project())
        with self.assertRaisesRegex(ValueError, "Web Streams regressions"):
            adapter.validate_generated_test(
                "const source = new ReadableStream(); source.pipeThrough(transform);",
                "test_patchproof_issue_3.test.ts",
            )

    def test_accepts_engine_web_stream_helpers(self) -> None:
        adapter = detect_runtime(self.make_project())
        adapter.validate_generated_test(
            """import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';
const output = await collectBytes(readableFromBytes(input, 8).pipeThrough(transform));
""",
            "test_patchproof_issue_3.test.ts",
        )


class ReportContractTests(unittest.TestCase):
    def test_preflight_failure_is_presented_as_blocked(self) -> None:
        report = render_report(
            {
                "verdict": "blocked",
                "stage": "runtime-preflight",
                "error": "tsx is unavailable",
                "issue": {"number": 3, "title": "Example"},
                "runtime": {},
                "sandbox": {},
                "candidates": [],
            }
        )
        self.assertIn("⚠️ BLOCKED", report)
        self.assertIn("## Blocking reason", report)
        self.assertIn("Stage: `runtime-preflight`", report)


if __name__ == "__main__":
    unittest.main()
