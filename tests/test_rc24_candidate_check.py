"""rc.24: a TypeScript candidate that does not compile gets one correction.

These tests drive proof.execute() end to end against a scripted fake Sandbox, so they cover
the wiring that unit tests cannot: the project check before any candidate, the compile check
after a candidate's ordinary baseline, the single correction, the proof fields, and the rule
that nothing about the hidden regression ever reaches a solver.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import proof
from runtimes import RuntimeAdapter, detect_runtime

HIDDEN = "HIDDEN_REGRESSION_ASSERTION_7f3a"
TEST_PATH = "tests/.test_patchproof_issue_7.test.ts"
SOURCE = "src/a.ts"
PROJECT_OK = "PATCHPROOF_SOURCE_CHECK=passed"
DIAGNOSTIC = "src/a.ts(3,5): error TS1308: 'await' expressions are only allowed within async functions"

VERIFIER_REPLY = (
    f"{proof.TEST_BEGIN}\n"
    "import test from 'node:test';\n"
    "import assert from 'node:assert/strict';\n"
    "import { value } from '../src/a.ts';\n"
    f"test('{HIDDEN}', () => {{ assert.equal(value(), 2); }});\n"
    f"{proof.TEST_END}\n{proof.RATIONALE_BEGIN}\nvalue() must return 2.\n{proof.RATIONALE_END}\n"
)

TAP_FAIL = (
    "TAP version 13\nnot ok 1 - case\n  ---\n  duration_ms: 1\n  failureType: 'testCodeFailure'\n"
    "  error: |-\n    Expected values to be strictly equal:\n  code: 'ERR_ASSERTION'\n  ...\n"
    "1..1\n# tests 1\n# suites 0\n# pass 0\n# fail 1\n# cancelled 0\n# skipped 0\n# todo 0\n"
)
TAP_PASS = "TAP version 13\nok 1 - case\n1..1\n# tests 1\n# suites 0\n# pass 1\n# fail 0\n"


class FakeState:
    """A Sandbox state: a file map plus the result of the last command run on it."""

    def __init__(self, world, files, code=0, stdout="", stderr="", uuid="image-0"):
        self.world, self.files = world, files
        self.exit_code, self.stdout, self.stderr, self.uuid = code, stdout, stderr, uuid

    def apply_files(self, *, files):
        return FakeState(self.world, {**self.files, **files})

    def run(self, *, shell, cwd, timeout, disposable):
        state = self

        class Operation:
            def wait(self_inner):
                return state.world.respond(state, shell)

        return Operation()


class World:
    """Scripted responses; records every command with whether the hidden test was present."""

    def __init__(self, *, project_exit=0, candidate_exit=None, baseline_exit=0):
        self.project_exit, self.candidate_exit, self.baseline_exit = (
            project_exit, candidate_exit, baseline_exit,
        )
        self.commands: list[tuple[str, bool]] = []
        self.counter = 0
        self.project_calls = 0

    def source(self, state):
        return state.files.get(f"/workspace/repo/{SOURCE}", b"").decode()

    def respond(self, state, shell):
        self.counter += 1
        has_test = f"/workspace/repo/{TEST_PATH}" in state.files
        kind = "other"
        code, out, err = 0, "", ""
        if "typescript_source_check.py --project" in shell:
            # The first call runs on the unmodified repository; later calls are candidates.
            self.project_calls += 1
            first = self.project_calls == 1
            kind = "project" if first else "candidate-check"
            if first:
                code = self.project_exit
                out = PROJECT_OK if code == 0 else DIAGNOSTIC
                err = "" if code == 0 else "PATCHPROOF_SOURCE_CHECK=failed"
            elif self.candidate_exit is not None:
                code = self.candidate_exit
                err = "PATCHPROOF_SOURCE_CHECK=unavailable: missing tsc"
            elif "BROKEN" in self.source(state):
                code, out, err = 1, DIAGNOSTIC, "PATCHPROOF_SOURCE_CHECK=failed"
            else:
                code, out = 0, PROJECT_OK
        elif "sha256sum" in shell:
            kind = "regression"
            body = state.files[f"/workspace/repo/{TEST_PATH}"]
            import hashlib
            digest = hashlib.sha256(body).hexdigest()
            fixed = "FIXED" in self.source(state)
            code, out = (0, TAP_PASS) if fixed else (1, TAP_FAIL)
            out += f"\nPATCHPROOF_TEST_HASH_BEFORE={digest}\nPATCHPROOF_TEST_HASH_AFTER={digest}\n"
        else:
            kind = "baseline"
            code, out = self.baseline_exit, "# tests 1\n# pass 1\n# fail 0\n"
        self.commands.append((kind, has_test))
        return FakeState(self, state.files, code, out, err, uuid=f"image-{self.counter}")


def make_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src/a.ts").write_text("export const value = () => 1;\n", encoding="utf-8")
    (root / "tests/baseline.test.ts").write_text(
        "import test from 'node:test';\ntest('x', () => {});\n", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({
        "name": "fake", "type": "module", "scripts": {"test": "tsx --test tests/*.test.ts"},
        "devDependencies": {"typescript": "^5.6.0"}}), encoding="utf-8")
    (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (root / "patchproof.json").write_text('{"runtime": "node-typescript"}\n', encoding="utf-8")


class CandidateSourceCheckFlowTests(unittest.TestCase):
    def run_flow(self, scripts, **world_options):
        """scripts maps a strategy prefix to the source each successive proposal contains."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        make_repo(root)
        world = World(**world_options)
        queues = {key: list(values) for key, values in scripts.items()}
        feedback_seen: list[tuple[str, str]] = []

        def fake_candidate(**kwargs):
            strategy = kwargs["strategy"]
            feedback_seen.append((strategy, kwargs.get("retry_feedback", "")))
            key = next(k for k in queues if strategy.startswith(k))
            content = queues[key].pop(0)
            return [{"path": SOURCE, "content": content}], f"proposal {strategy}"

        sdk = SimpleNamespace(images=SimpleNamespace(use=lambda uuid, strict: object()))
        environment = {
            "NEBIUS_API_KEY": "key-secret", "NEBIUS_PROJECT_ID": "project-secret",
            "NEBIUS_MODEL": "model", "CONTREE_IMAGE": "image-uuid",
        }
        record = {"schema_version": proof.SCHEMA_VERSION, "app_version": proof.APP_VERSION,
                  "verdict": "rejected", "candidates": []}
        with patch.dict(os.environ, environment), \
                patch.object(proof, "create_sandbox_client", return_value=sdk), \
                patch.object(proof, "sandbox_workspace",
                             side_effect=lambda *a, **k: FakeState(world, {})), \
                patch.object(proof, "model_text", return_value=VERIFIER_REPLY), \
                patch.object(proof, "generate_candidate", side_effect=fake_candidate):
            try:
                result = proof.execute(root, proof.Issue(7, "value is wrong", "value() must be 2"),
                                       record)
            except proof.PatchProofError as error:
                result = {**record, "error": str(error)}
        return result, world, feedback_seen

    def test_failing_candidate_gets_one_correction_and_can_win(self):
        broken = "export const value = async () => { BROKEN };\n"
        fixed = "export const value = () => 2; // FIXED\n"
        result, world, feedback = self.run_flow({
            "minimal": [broken, fixed],
            "defensive": [broken, broken],
            "maintainable": [fixed],
        })
        self.assertEqual(result["verdict"], "verified")
        self.assertTrue(result["source_check"]["enabled"])
        first, second, third = result["candidates"]

        self.assertTrue(first["passed"])
        self.assertEqual(len(first["baseline_attempts"]), 2)
        self.assertEqual([a["passed"] for a in first["source_check_attempts"]], [False, True])
        self.assertIn("TS1308", first["source_check_attempts"][0]["output"])

        self.assertFalse(second["passed"])
        self.assertEqual(second["stage"], "source-check")
        self.assertIn("still fails the TypeScript check after one correction", second["error"])
        self.assertEqual([a["passed"] for a in second["source_check_attempts"]], [False, False])
        self.assertIn("diff", second)  # the benchmark harness can still label what it proposed

        self.assertTrue(third["passed"])
        self.assertEqual(len(third["source_check_attempts"]), 1)
        self.assertIn(result["winner"]["candidate"], {1, 3})

        # One correction means one more proposal; the first correction carried compiler output.
        corrections = [text for strategy, text in feedback if "TS1308" in text]
        self.assertGreaterEqual(len(corrections), 2)
        self.assertIn("await is only allowed inside an async function", corrections[0])
        self.assertIn("PREVIOUS PROPOSAL DIFF", corrections[0])

    def test_nothing_about_the_hidden_regression_reaches_a_solver(self):
        broken = "export const value = async () => { BROKEN };\n"
        fixed = "export const value = () => 2; // FIXED\n"
        _, world, feedback = self.run_flow({
            "minimal": [broken, fixed], "defensive": [fixed], "maintainable": [fixed],
        })
        for _, text in feedback:
            self.assertNotIn(HIDDEN, text)
            self.assertNotIn("test_patchproof_issue_7", text)
        # The compile check runs on a state that has never had the hidden test applied.
        checks = [has_test for kind, has_test in world.commands
                  if kind in {"project", "candidate-check"}]
        self.assertTrue(checks)
        self.assertFalse(any(checks))

    def test_a_project_that_does_not_pass_its_own_check_switches_the_gate_off(self):
        broken = "export const value = async () => { BROKEN };\n"
        result, world, _ = self.run_flow(
            {"minimal": [broken], "defensive": [broken], "maintainable": [broken]},
            project_exit=1,
        )
        self.assertFalse(result["source_check"]["enabled"])
        self.assertEqual(result["source_check"]["baseline_exit_code"], 1)
        self.assertNotIn("candidate-check", [kind for kind, _ in world.commands])
        for candidate in result["candidates"]:
            self.assertNotIn("source_check_attempts", candidate)
            self.assertEqual(candidate["stage"], "regression")  # judged by the hidden test only

    def test_a_check_that_cannot_run_never_rejects_a_candidate(self):
        fixed = "export const value = () => 2; // FIXED\n"
        result, world, _ = self.run_flow(
            {"minimal": [fixed], "defensive": [fixed], "maintainable": [fixed]},
            candidate_exit=2,
        )
        self.assertEqual(result["verdict"], "verified")
        for candidate in result["candidates"]:
            self.assertEqual(len(candidate["baseline_attempts"]), 1)
            self.assertTrue(candidate["source_check_attempts"][0]["passed"])

    def test_a_correct_candidate_costs_no_extra_generation(self):
        fixed = "export const value = () => 2; // FIXED\n"
        result, _, feedback = self.run_flow(
            {"minimal": [fixed], "defensive": [fixed], "maintainable": [fixed]})
        self.assertEqual(len(feedback), 3)
        self.assertTrue(all(text == "" for _, text in feedback))


class CommandSelectionTests(unittest.TestCase):
    def adapter(self, runtime_id: str) -> RuntimeAdapter:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_repo(root)
            (root / "patchproof.json").write_text(json.dumps({"runtime": runtime_id}), encoding="utf-8")
            return detect_runtime(root)

    def test_only_node_typescript_gets_a_project_or_source_check(self):
        typescript = self.adapter("node-typescript")
        self.assertEqual(typescript.id, "node-typescript")
        self.assertEqual(typescript.project_check_command(),
                         "python /patchproof/typescript_source_check.py --project")
        package = self.adapter("node-package")
        self.assertIsNone(package.project_check_command())
        self.assertIsNone(package.source_check_command(["src/a.ts"]))

    def test_the_candidate_check_is_the_same_command_and_only_runs_for_typescript_edits(self):
        adapter = self.adapter("node-typescript")
        self.assertEqual(adapter.source_check_command(["src/a.ts", "README.md"]),
                         adapter.project_check_command())
        self.assertEqual(adapter.source_check_command(["web/page.tsx"]),
                         adapter.project_check_command())
        self.assertIsNone(adapter.source_check_command(["README.md", "x.js"]))
        self.assertIsNone(adapter.source_check_command([]))


if __name__ == "__main__":
    unittest.main()
