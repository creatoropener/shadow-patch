from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtimes import detect_runtime
from proof import classify_reproduction, render_report, reproduction_feedback


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
        command = adapter.regression_command("x.test.ts")
        self.assertIn("python /patchproof/typescript_check.py", command)
        self.assertLess(command.index("typescript_check.py"), command.index("/tsx "))
        self.assertIn("./node_modules/.bin/tsc --version", adapter.preflight_command)

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

    def test_rejects_typescript_contract_bypasses(self) -> None:
        adapter = detect_runtime(self.make_project())
        for bypass in (
            "const key = value as any;",
            "const key = value as unknown as CryptoKey;",
            "// @ts-ignore\nconst key = value;",
            "// @ts-expect-error\nconst key = value;",
        ):
            with self.subTest(bypass=bypass), self.assertRaisesRegex(
                ValueError, "Do not bypass TypeScript API contracts"
            ):
                adapter.validate_generated_test(
                    bypass, "test_patchproof_issue_3.test.ts"
                )

    def test_retry_feedback_corrects_green_bug_confirmation(self) -> None:
        feedback = reproduction_feedback(
            "await assert.rejects(roundTrip);",
            "test passed on the unfixed revision",
            "# pass 1",
        )
        self.assertIn("intended post-fix behavior", feedback)
        self.assertIn("doesNotReject", feedback)

    def test_retry_feedback_explains_typescript_contract_errors(self) -> None:
        feedback = reproduction_feedback(
            "const output = await collectBytes(stream); output.pipeThrough(transform);",
            "test infrastructure exited with code 2",
            "error TS2339\nPATCHPROOF_TYPESCRIPT_CHECK=failed",
        )
        self.assertIn("failed static API checking", feedback)
        self.assertIn("collectBytes returns Uint8Array", feedback)

    def test_typescript_type_error_has_specific_classification(self) -> None:
        adapter = detect_runtime(self.make_project())
        digest = "abc123"
        output = (
            "error TS2345\nPATCHPROOF_TYPESCRIPT_CHECK=failed\n"
            f"PATCHPROOF_TEST_HASH_BEFORE={digest}\n"
            f"PATCHPROOF_TEST_HASH_AFTER={digest}\n"
        )
        reproduced, protected, classification = classify_reproduction(
            adapter, 2, output, digest
        )
        self.assertFalse(reproduced)
        self.assertTrue(protected)
        self.assertEqual(
            classification,
            "generated TypeScript regression failed API type-check",
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
