from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtimes import detect_runtime
from proof import classify_reproduction, render_report, reproduction_feedback

FIXTURES = Path(__file__).parent / "fixtures"


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
            """import test from 'node:test';
import assert from 'node:assert/strict';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';
let output;
await assert.doesNotReject(async () => {
output = await collectBytes(readableFromBytes(input, 8).pipeThrough(transform));
});
assert.deepStrictEqual(output, expected);
""",
            "test_patchproof_issue_3.test.ts",
        )

    def test_rejects_proof_6_unused_decryption_transform(self) -> None:
        adapter = detect_runtime(self.make_project())
        faulty = (FIXTURES / "proof6_faulty_regression.test.ts").read_text(
            encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "never used: dec"):
            adapter.validate_generated_test(
                faulty, "test_patchproof_issue_3.test.ts"
            )

    def test_accepts_complete_encrypt_decrypt_pipeline(self) -> None:
        adapter = detect_runtime(self.make_project())
        complete = (FIXTURES / "proof6_corrected_regression.test.ts").read_text(
            encoding="utf-8"
        )
        adapter.validate_generated_test(
            complete, "test_patchproof_issue_3.test.ts"
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

    def test_semantic_lint_has_specific_feedback_and_classification(self) -> None:
        adapter = detect_runtime(self.make_project())
        digest = "def456"
        output = (
            "binding 'dec' is declared but never used\n"
            "PATCHPROOF_TYPESCRIPT_LINT=failed\n"
            f"PATCHPROOF_TEST_HASH_BEFORE={digest}\n"
            f"PATCHPROOF_TEST_HASH_AFTER={digest}\n"
        )
        feedback = reproduction_feedback(
            "const dec = await createDecryptionStream(key);",
            "generated TypeScript regression failed semantic lint",
            output,
        )
        self.assertIn("apply both transforms", feedback)
        reproduced, protected, classification = classify_reproduction(
            adapter, 2, output, digest
        )
        self.assertFalse(reproduced)
        self.assertTrue(protected)
        self.assertEqual(
            classification,
            "generated TypeScript regression failed semantic lint",
        )

    # --- missing node:test / node:assert imports (real generated test from proof.json) ---

    def test_rejects_generated_test_without_node_test_import(self) -> None:
        adapter = detect_runtime(self.make_project())
        source = (FIXTURES / "missing_node_test_import.test.ts").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing required imports") as raised:
            adapter.validate_generated_test(source, "test_patchproof_issue_3.test.ts")
        # `assert` is imported in this fixture; only `test` is missing.
        self.assertIn("import test from 'node:test';", str(raised.exception))
        self.assertNotIn("node:assert/strict", str(raised.exception))

    def test_accepts_same_test_once_imports_are_present(self) -> None:
        adapter = detect_runtime(self.make_project())
        source = (FIXTURES / "missing_node_test_import_corrected.test.ts").read_text(
            encoding="utf-8"
        )
        adapter.validate_generated_test(source, "test_patchproof_issue_3.test.ts")

    def test_missing_assert_import_is_reported_separately(self) -> None:
        adapter = detect_runtime(self.make_project())
        source = "import test from 'node:test';\ntest('x', () => { assert.equal(1, 1); });\n"
        with self.assertRaisesRegex(ValueError, "missing required imports") as raised:
            adapter.validate_generated_test(source, "test_patchproof_issue_3.test.ts")
        self.assertIn("import assert from 'node:assert/strict';", str(raised.exception))
        self.assertNotIn("import test from", str(raised.exception))

    def test_accepted_import_spellings(self) -> None:
        adapter = detect_runtime(self.make_project())
        for header in (
            "import test from 'node:test';\nimport assert from 'node:assert/strict';",
            'import { test } from "node:test";\nimport { strict as assert } from "node:assert";',
            "import test, { describe } from 'node:test';\nimport assert from 'node:assert';",
            "const test = require('node:test');\nconst assert = require('node:assert/strict');",
        ):
            with self.subTest(header=header):
                adapter.validate_generated_test(
                    header + "\ntest('x', () => { assert.equal(1, 1); });\n",
                    "test_patchproof_issue_3.test.ts",
                )

    def test_commented_out_import_does_not_count(self) -> None:
        adapter = detect_runtime(self.make_project())
        source = (
            "// import test from 'node:test';\n"
            "/* import assert from 'node:assert/strict'; */\n"
            "test('x', () => { assert.equal(1, 1); });\n"
        )
        with self.assertRaisesRegex(ValueError, "missing required imports"):
            adapter.validate_generated_test(source, "test_patchproof_issue_3.test.ts")

    def test_verifier_guidance_demonstrates_the_imports(self) -> None:
        adapter = detect_runtime(self.make_project())
        self.assertIn("import test from 'node:test';", adapter.verifier_guidance)
        self.assertIn("import assert from 'node:assert/strict';", adapter.verifier_guidance)

    def test_missing_import_feedback_replaces_generic_api_advice(self) -> None:
        source = (FIXTURES / "missing_node_test_import.test.ts").read_text(encoding="utf-8")
        output = (FIXTURES / "missing_node_test_import.out").read_text(encoding="utf-8")
        feedback = reproduction_feedback(
            source, "generated TypeScript regression failed API type-check", output
        )
        self.assertIn("missing import", feedback)
        self.assertIn("import test from 'node:test';", feedback)
        self.assertIn("NOT a missing @types package", feedback)
        self.assertIn("identical content fails again", feedback)
        self.assertNotIn("failed static API checking", feedback)

    def test_mixed_diagnostics_keep_both_kinds_of_feedback(self) -> None:
        output = (
            "x.test.ts(6,1): error TS2582: Cannot find name 'test'.\n"
            "x.test.ts(9,5): error TS2345: Argument of type 'string' is not assignable.\n"
            "PATCHPROOF_TYPESCRIPT_CHECK=failed"
        )
        feedback = reproduction_feedback("src", "generated TypeScript regression failed API type-check", output)
        self.assertIn("missing import", feedback)
        self.assertIn("failed static API checking", feedback)

    def test_corrected_test_is_accepted_as_assertion_failure_evidence(self) -> None:
        # TAP captured by running the corrected fixture against the unfixed issue #3 code.
        adapter = detect_runtime(self.make_project())
        output = (FIXTURES / "missing_node_test_import_corrected.tap").read_text(encoding="utf-8")
        digest = "abc123"
        output += (
            f"\nPATCHPROOF_TEST_HASH_BEFORE={digest}\nPATCHPROOF_TEST_HASH_AFTER={digest}\n"
        )
        reproduced, protected, classification = classify_reproduction(adapter, 1, output, digest)
        self.assertTrue(reproduced, classification)
        self.assertTrue(protected)


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
