"""rc.21: generated Node tests must import files that exist from where they are saved.

The motivating failure (file-sharing-app-1, three rc.20 trials): the repository's own
tests/format-baseline.test.mjs imports a helper as '../patchproof_runtime/...'. The
model copied that line into a generated test that node-package saved at the repo
root, where '../' leaves the repository, so every run died with ERR_MODULE_NOT_FOUND
before any assertion.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import proof
from proof import classify_reproduction, reproduction_feedback
from runtimes import (
    describe_unresolved_imports,
    detect_runtime,
    relative_import_specifiers,
    unresolved_relative_imports,
)

# Output captured from a real rc.20 trial (file-sharing-app-1), trimmed to the
# lines that matter plus the hash markers classify_reproduction requires.
REAL_LOAD_FAILURE = """TAP version 13
# node:internal/modules/esm/resolve:283
#     throw new ERR_MODULE_NOT_FOUND(
#           ^
# Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/workspace/patchproof_runtime/typescript_module.mjs' imported from /workspace/repo/test_patchproof_issue_1.test.mjs
#   code: 'ERR_MODULE_NOT_FOUND',
not ok 1 - /workspace/repo/test_patchproof_issue_1.test.mjs
  ---
  failureType: 'testCodeFailure'
  exitCode: 1
  error: 'test failed'
  code: 'ERR_TEST_FAILURE'
  ...
1..1
# tests 1
# fail 1

PATCHPROOF_TEST_HASH_BEFORE=abc
PATCHPROOF_TEST_HASH_AFTER=abc
"""

LEGACY_TEST = """import test from 'node:test';
import assert from 'node:assert/strict';
import { loadStandaloneTypeScript } from '../patchproof_runtime/typescript_module.mjs';

const { formatBytes } = loadStandaloneTypeScript('lib/utils/format.ts');

test('formatBytes', () => {
  assert.equal(formatBytes(1024), '1.0 KB');
});
"""


def write(root: Path, relative: str, text: str = "// fixture\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ProjectCase(unittest.TestCase):
    def legacy_project(self) -> Path:
        """File-sharing-app at the pinned commit: node-package, loader copied into the repo."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write(root, "package.json", json.dumps({"scripts": {"test": "node --test tests/*.test.mjs"}}))
        write(root, "patchproof.json", json.dumps({"runtime": "node-package"}))
        write(root, "patchproof_runtime/typescript_module.mjs")
        write(root, "tests/format-baseline.test.mjs",
              "import { loadStandaloneTypeScript } from '../patchproof_runtime/typescript_module.mjs';\n")
        write(root, "lib/utils/format.ts")
        return root


class SpecifierScanTests(unittest.TestCase):
    def test_finds_static_side_effect_dynamic_and_require_forms(self) -> None:
        source = (
            "import test from 'node:test';\n"
            "import a from './a.mjs';\n"
            "import { b,\n  c } from \"../b.ts\";\n"
            "import type { T } from '../types.ts';\n"
            "export * from './re-export.js';\n"
            "import './side-effect.mjs';\n"
            "const d = await import('./d.mjs');\n"
            "const e = require('./e.cjs');\n"
            "import pkg from 'some-package';\n"
        )
        self.assertEqual(
            relative_import_specifiers(source),
            ["./a.mjs", "../b.ts", "../types.ts", "./re-export.js",
             "./side-effect.mjs", "./d.mjs", "./e.cjs"],
        )

    def test_ignores_comments_bare_specifiers_and_mid_line_text(self) -> None:
        source = (
            "// import x from './commented.mjs';\n"
            "/* import y from './block.mjs';\n   import z from './block2.mjs'; */\n"
            "const note = \"see import w from './in-string.mjs'\";\n"
            "const url = 'http://example.test'; const q = await import('./after-slashes.mjs');\n"
            "import fs from 'node:fs';\n"
        )
        self.assertEqual(relative_import_specifiers(source), [])

    def test_repeated_specifier_reported_once_in_source_order(self) -> None:
        source = "import a from './x.mjs';\nimport b from './y.mjs';\nconst c = await import('./x.mjs');\n"
        self.assertEqual(relative_import_specifiers(source), ["./x.mjs", "./y.mjs"])


class ResolutionTests(ProjectCase):
    def test_reproduces_the_rc20_failure_at_the_root_and_suggests_the_fix(self) -> None:
        root = self.legacy_project()
        problems = unresolved_relative_imports(
            LEGACY_TEST, "test_patchproof_issue_1.test.mjs", root
        )
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["specifier"], "../patchproof_runtime/typescript_module.mjs")
        self.assertIsNone(problems[0]["resolved"])  # leaves the repository
        self.assertEqual(
            problems[0]["suggestions"], ["./patchproof_runtime/typescript_module.mjs"]
        )
        message = describe_unresolved_imports(problems, "test_patchproof_issue_1.test.mjs")
        self.assertIn("the repository root", message)
        self.assertIn("outside the repository", message)
        self.assertIn("'./patchproof_runtime/typescript_module.mjs'", message)

    def test_same_import_resolves_from_the_tests_directory(self) -> None:
        root = self.legacy_project()
        self.assertEqual(
            unresolved_relative_imports(
                LEGACY_TEST, "tests/.test_patchproof_issue_1.test.mjs", root
            ),
            [],
        )

    def test_suggestion_is_computed_from_the_tests_directory_too(self) -> None:
        root = self.legacy_project()
        problems = unresolved_relative_imports(
            "import a from './patchproof_runtime/typescript_module.mjs';\n",
            "tests/.test_patchproof_issue_1.test.mjs", root,
        )
        self.assertEqual(problems[0]["resolved"], "tests/patchproof_runtime/typescript_module.mjs")
        self.assertEqual(
            problems[0]["suggestions"], ["../patchproof_runtime/typescript_module.mjs"]
        )

    def test_invented_helper_gets_a_do_not_import_message(self) -> None:
        root = self.legacy_project()
        problems = unresolved_relative_imports(
            "import h from '../helpers/made-up.mjs';\n", "tests/.t.test.mjs", root
        )
        self.assertEqual(problems[0]["suggestions"], [])
        self.assertIn("do not import it", describe_unresolved_imports(problems, "tests/.t.test.mjs"))

    def test_extension_conventions_are_not_false_positives(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write(root, "src/utils/qrBuilder.ts")
        write(root, "src/types.ts")
        write(root, "src/lib/index.ts")
        write(root, "src/data.json")
        write(root, "src/esm/thing.mts")
        source = (
            "import a from '../src/utils/qrBuilder.ts';\n"   # explicit .ts (QRcrafts)
            "import b from '../src/types';\n"                  # extensionless
            "import c from '../src/utils/qrBuilder.js';\n"     # .js naming a .ts source
            "import d from '../src/lib';\n"                    # directory index
            "import e from '../src/data.json';\n"
            "import f from '../src/esm/thing.mjs';\n"          # .mjs naming a .mts source
        )
        self.assertEqual(
            unresolved_relative_imports(source, "tests/.test_patchproof_issue_1.test.ts", root), []
        )

    def test_missing_file_with_a_wrong_extension_is_reported(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write(root, "src/utils/qrBuilder.ts")
        problems = unresolved_relative_imports(
            "import a from '../src/utils/qrBuilder.py';\n", "tests/.t.test.ts", root
        )
        self.assertEqual([p["specifier"] for p in problems], ["../src/utils/qrBuilder.py"])

    def test_suggestions_skip_node_modules_and_hidden_directories(self) -> None:
        root = self.legacy_project()
        write(root, "node_modules/pkg/patchproof_runtime/typescript_module.mjs")
        write(root, ".cache/patchproof_runtime/typescript_module.mjs")
        problems = unresolved_relative_imports(
            "import a from '../nope/patchproof_runtime/typescript_module.mjs';\n",
            "tests/.t.test.mjs", root,
        )
        self.assertEqual(
            problems[0]["suggestions"], ["../patchproof_runtime/typescript_module.mjs"]
        )


class PlacementTests(ProjectCase):
    def test_node_package_uses_tests_directory_when_the_project_has_one(self) -> None:
        root = self.legacy_project()
        adapter = detect_runtime(root)
        self.assertEqual(adapter.id, "node-package")
        self.assertEqual(
            adapter.test_path(1, root=root), "tests/.test_patchproof_issue_1.test.mjs"
        )

    def test_node_package_keeps_root_placement_without_a_matching_tests_directory(self) -> None:
        root = self.legacy_project()
        (root / "tests" / "format-baseline.test.mjs").unlink()
        write(root, "tests/notes.txt")
        adapter = detect_runtime(root)
        self.assertEqual(adapter.test_path(1, root=root), "test_patchproof_issue_1.test.mjs")
        self.assertEqual(adapter.test_path(1), "test_patchproof_issue_1.test.mjs")

    def test_dot_prefixed_file_is_outside_the_projects_own_glob(self) -> None:
        # The project's baseline is the shell glob `tests/*.test.mjs`; a leading dot
        # keeps the still-failing hidden regression out of it.
        import glob
        root = self.legacy_project()
        adapter = detect_runtime(root)
        write(root, adapter.test_path(1, root=root))
        matched = {Path(p).name for p in glob.glob(str(root / "tests" / "*.test.mjs"))}
        self.assertEqual(matched, {"format-baseline.test.mjs"})

    def test_explicit_path_command_still_runs_the_dot_prefixed_file(self) -> None:
        root = self.legacy_project()
        adapter = detect_runtime(root)
        path = adapter.test_path(1, root=root)
        self.assertIn(path, adapter.regression_command(path))

    def test_node_package_guidance_explains_where_relative_paths_start(self) -> None:
        root = self.legacy_project()
        guidance = detect_runtime(root).verifier_guidance
        self.assertIn("directory that will contain the required filename", guidance)


class AdapterValidationTests(ProjectCase):
    def test_node_package_rejects_unresolvable_import_before_any_sandbox_run(self) -> None:
        root = self.legacy_project()
        adapter = detect_runtime(root)
        with self.assertRaisesRegex(ValueError, "do not point to any file"):
            adapter.validate_generated_imports(
                LEGACY_TEST, "test_patchproof_issue_1.test.mjs", root
            )
        adapter.validate_generated_imports(
            LEGACY_TEST, "tests/.test_patchproof_issue_1.test.mjs", root
        )

    def test_other_adapters_are_not_checked(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write(root, "requirements.txt")
        adapter = detect_runtime(root)
        self.assertEqual(adapter.id, "python-pytest")
        adapter.validate_generated_imports("import a from '../nope.mjs';\n", "t.py", root)


def model_reply(source: str) -> str:
    return (
        f"{proof.TEST_BEGIN}\n{source}\n{proof.TEST_END}\n"
        f"{proof.RATIONALE_BEGIN}\nExercise the reported behavior.\n{proof.RATIONALE_END}\n"
    )


class GenerationIntegrationTests(ProjectCase):
    issue = SimpleNamespace(number=1, title="Sizes show template text", body="Expected 1.0 KB")

    def generate(self, root: Path, replies: list[str], *, with_root: bool = True):
        adapter = detect_runtime(root)
        path = adapter.test_path(1, root=root)
        attempts: list[dict] = []
        with patch.object(proof, "model_text", side_effect=replies) as model:
            try:
                result = proof.generate_regression_with_retry(
                    issue=self.issue, context="CONTEXT", api_key="unused", model="unused",
                    adapter=adapter, test_path=path, generation_attempts=attempts,
                    root=root if with_root else None,
                )
            except proof.PatchProofError as error:
                return None, attempts, model, error
        return result, attempts, model, None

    def test_a_bad_import_costs_a_generation_not_a_sandbox_run(self) -> None:
        root = self.legacy_project()
        # Place the test at the root, the rc.20 layout, to reproduce the trial.
        adapter = detect_runtime(root)
        bad_then_good = [model_reply(LEGACY_TEST),
                         model_reply(LEGACY_TEST.replace("'../patchproof_runtime", "'./patchproof_runtime"))]
        with patch.object(type(adapter), "test_path", return_value="test_patchproof_issue_1.test.mjs"):
            attempts: list[dict] = []
            with patch.object(proof, "model_text", side_effect=bad_then_good) as model:
                content, _ = proof.generate_regression_with_retry(
                    issue=self.issue, context="CONTEXT", api_key="unused", model="unused",
                    adapter=adapter, test_path="test_patchproof_issue_1.test.mjs",
                    generation_attempts=attempts, root=root,
                )
        self.assertIn("'./patchproof_runtime/typescript_module.mjs'", content)
        self.assertEqual([a["status"] for a in attempts], ["validation_failed", "validated"])
        self.assertIn("outside the repository", attempts[0]["diagnostic"])
        self.assertEqual(model.call_count, 2)
        retry_prompt = model.call_args_list[1].kwargs["user"]
        self.assertIn("Test-generation validation error", retry_prompt)
        self.assertIn("./patchproof_runtime/typescript_module.mjs", retry_prompt)

    def test_repeated_identical_failure_escalates_with_the_rejected_source(self) -> None:
        root = self.legacy_project()
        adapter = detect_runtime(root)
        replies = [model_reply(LEGACY_TEST)] * 3
        with patch.object(proof, "model_text", side_effect=replies) as model:
            with self.assertRaises(proof.PatchProofError):
                proof.generate_regression_with_retry(
                    issue=self.issue, context="CONTEXT", api_key="unused", model="unused",
                    adapter=adapter, test_path="test_patchproof_issue_1.test.mjs", root=root,
                )
        self.assertEqual(model.call_count, 3)
        third_prompt = model.call_args_list[2].kwargs["user"]
        self.assertIn("second attempt in a row", third_prompt)
        self.assertIn("loadStandaloneTypeScript", third_prompt)  # its own rejected source

    def test_new_placement_lets_the_copied_import_through(self) -> None:
        root = self.legacy_project()
        result, attempts, model, error = self.generate(root, [model_reply(LEGACY_TEST)])
        self.assertIsNone(error)
        self.assertEqual([a["status"] for a in attempts], ["validated"])
        self.assertEqual(model.call_count, 1)

    def test_without_a_root_the_check_is_skipped(self) -> None:
        root = self.legacy_project()
        adapter = detect_runtime(root)
        with patch.object(proof, "model_text", return_value=model_reply(LEGACY_TEST)):
            content, _ = proof.generate_regression_test(
                issue=self.issue, context="CONTEXT", api_key="unused", model="unused",
                adapter=adapter, test_path="test_patchproof_issue_1.test.mjs",
            )
        self.assertIn("../patchproof_runtime", content)


class LoadFailureFeedbackTests(unittest.TestCase):
    adapter = SimpleNamespace(
        id="node-package", test_runtime="node-test",
        is_regression_failure=lambda exit_code, output: exit_code == 1 and "ERR_ASSERTION" in output,
    )

    def test_module_load_failure_gets_its_own_classification(self) -> None:
        self.assertEqual(
            classify_reproduction(self.adapter, 1, REAL_LOAD_FAILURE, "abc"),
            (False, True, "generated test could not load a module"),
        )

    def test_feedback_names_the_path_and_drops_the_misleading_advice(self) -> None:
        feedback = reproduction_feedback(
            LEGACY_TEST, "generated test could not load a module", REAL_LOAD_FAILURE
        )
        self.assertIn("/workspace/patchproof_runtime/typescript_module.mjs", feedback)
        self.assertIn("wrong import path", feedback)
        self.assertIn("recompute", feedback)
        self.assertNotIn("doesNotReject", feedback)
        self.assertNotIn("dynamic import", feedback)  # the importer is the test itself

    def test_same_output_under_the_old_classification_no_longer_misfires(self) -> None:
        feedback = reproduction_feedback(
            LEGACY_TEST, "test failed without accepted assertion evidence", REAL_LOAD_FAILURE
        )
        self.assertNotIn("doesNotReject", feedback)

    def test_a_plain_throw_before_the_assertion_keeps_the_existing_advice(self) -> None:
        output = ("not ok 1 - x\n  code: 'ERR_TEST_FAILURE'\n  error: 'boom'\n"
                  "PATCHPROOF_TEST_HASH_BEFORE=abc\nPATCHPROOF_TEST_HASH_AFTER=abc\n")
        self.assertEqual(
            classify_reproduction(self.adapter, 1, output, "abc"),
            (False, True, "test failed without accepted assertion evidence"),
        )
        feedback = reproduction_feedback(
            "t", "test failed without accepted assertion evidence", output
        )
        self.assertIn("doesNotReject", feedback)

    def test_a_real_assertion_failure_is_still_accepted(self) -> None:
        output = ("not ok 1\n  code: 'ERR_ASSERTION'\nPATCHPROOF_TEST_HASH_BEFORE=abc\n"
                  "PATCHPROOF_TEST_HASH_AFTER=abc\n")
        self.assertEqual(
            classify_reproduction(self.adapter, 1, output, "abc")[0:2], (True, True)
        )

    def test_missing_module_inside_application_code_hints_at_a_dynamic_import(self) -> None:
        output = ("Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/workspace/repo/lib/gone.mjs' "
                  "imported from /workspace/repo/lib/app.mjs\n")
        feedback = reproduction_feedback("t", "generated test could not load a module", output)
        self.assertIn("dynamic import", feedback)
        self.assertIn("assert.doesNotReject", feedback)

    def test_missing_package_is_a_dependency_message(self) -> None:
        output = ("Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'left-pad' imported from "
                  "/workspace/repo/test_patchproof_issue_1.test.mjs\n")
        feedback = reproduction_feedback("t", "generated test could not load a module", output)
        self.assertIn("missing dependency", feedback)
        self.assertIn("package.json", feedback)

    def test_typescript_unresolved_module_gets_module_advice_not_api_advice(self) -> None:
        output = ("PATCHPROOF_TYPESCRIPT_CHECK=failed\n"
                  "tests/.t.test.ts(3,22): error TS2307: Cannot find module '../src/nope.ts' "
                  "or its corresponding type declarations.\n")
        feedback = reproduction_feedback("t", "generated TypeScript regression failed API type-check", output)
        self.assertIn("wrong import path", feedback)
        self.assertNotIn("re-reading the repository's actual", feedback)

    def test_typescript_mixed_errors_keep_the_api_advice(self) -> None:
        output = ("PATCHPROOF_TYPESCRIPT_CHECK=failed\n"
                  "tests/.t.test.ts(3,22): error TS2307: Cannot find module '../src/nope.ts'.\n"
                  "tests/.t.test.ts(9,5): error TS2345: Argument of type 'string' is not assignable.\n")
        feedback = reproduction_feedback("t", "generated TypeScript regression failed API type-check", output)
        self.assertIn("wrong import path", feedback)
        self.assertIn("re-reading the repository's actual", feedback)


if __name__ == "__main__":
    unittest.main()
