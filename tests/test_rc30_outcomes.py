"""rc.30: readiness summary, outcome buckets, legacy stop reasons and the readiness-only run."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import outcomes
import proof
from tests import support_pipeline as pipeline


def stopped(stage, error="boom", **extra):
    return {"verdict": "rejected", "stage": stage, "error": error, "candidates": [], **extra}


class ReadinessSummaryTests(unittest.TestCase):
    def test_blocked_at_baseline_names_the_check_and_the_change(self):
        summary = outcomes.summarize_readiness(stopped(
            "baseline", "Baseline command failed for runtime node-typescript.",
            runtime={"id": "node-typescript", "test_runtime": "node-test", "preflight_output": "ok"},
            baseline={"existing_suite_passed": False, "tests_passed": 3, "command": "npm test"}))
        self.assertEqual(summary["status"], "blocked")
        self.assertTrue(summary["before_inference"])
        blocker = summary["blockers"][0]
        self.assertEqual((blocker["stage"], blocker["check"]), ("baseline", "baseline"))
        self.assertIn("known_failures", blocker["change"])
        baseline = next(c for c in summary["checks"] if c["check"] == "baseline")
        self.assertEqual(baseline["status"], "failed")

    def test_lockfile_conflict_blocks_at_runtime_detection(self):
        summary = outcomes.summarize_readiness(stopped(
            "runtime-detection", "Multiple package-manager lockfiles found (npm, yarn)."))
        self.assertEqual(summary["blockers"][0]["check"], "package_manager")
        self.assertIn("packageManager", summary["blockers"][0]["change"])
        self.assertEqual(next(c for c in summary["checks"] if c["check"] == "runtime")["status"], "failed")

    def test_unmatched_error_is_still_reported_verbatim_without_a_suggestion(self):
        summary = outcomes.summarize_readiness(stopped("baseline-source-check", "Something new went wrong."))
        blocker = summary["blockers"][0]
        self.assertEqual(blocker["message"], "Something new went wrong.")
        self.assertNotIn("change", blocker)

    def test_zero_test_baseline_is_recorded_as_absent_compatibility_coverage(self):
        proof_record = {"verdict": "rejected", "stage": "verifier-generation", "candidates": [],
                        "runtime": {"id": "node-package", "test_runtime": "node-test", "preflight_output": "ok"},
                        "baseline": {"existing_suite_passed": True, "tests_passed": 0, "command": "node --test"}}
        summary = outcomes.summarize_readiness(proof_record)
        self.assertEqual(summary["status"], "ready")
        self.assertFalse(summary["before_inference"])
        self.assertEqual(summary["compatibility_coverage"], "absent")
        self.assertTrue(any("0 tests" in warning for warning in summary["warnings"]))

    def test_unreported_count_is_unknown_not_absent(self):
        summary = outcomes.summarize_readiness({
            "stage": "verifier-generation", "runtime": {"id": "x", "preflight_output": ""},
            "baseline": {"existing_suite_passed": True, "tests_passed": None, "command": "c"}})
        self.assertEqual(summary["compatibility_coverage"], "unknown")

    def test_existing_tests_are_present_coverage(self):
        summary = outcomes.summarize_readiness({
            "stage": "candidate-evaluation", "runtime": {"id": "x", "preflight_output": ""},
            "baseline": {"existing_suite_passed": True, "tests_passed": 12, "command": "c"}})
        self.assertEqual(summary["compatibility_coverage"], "present")
        self.assertEqual(summary["baseline_tests"], 12)

    def test_package_manager_notes_surface_as_a_warning(self):
        summary = outcomes.summarize_readiness({
            "stage": "verifier-generation",
            "runtime": {"id": "node-typescript", "preflight_output": "",
                        "package_manager": {"name": "npm", "version": None, "notes": ["Bun lockfile ignored"]}}})
        check = next(c for c in summary["checks"] if c["check"] == "package_manager")
        self.assertEqual(check["status"], "warning")
        self.assertIn("Bun lockfile ignored", check["detail"])

    def test_readiness_only_stage_is_before_inference_and_ready(self):
        summary = outcomes.summarize_readiness({"verdict": "ready", "stage": "readiness",
                                                "runtime": {"id": "x", "preflight_output": ""}})
        self.assertEqual(summary["status"], "ready")
        self.assertTrue(summary["before_inference"])


class OutcomeBucketTests(unittest.TestCase):
    def bucket(self, record):
        return outcomes.classify_outcome(record)["bucket"]

    def test_each_stage_has_its_own_bucket(self):
        accepted = {"classification": "accepted assertion failure reproduced the issue"}
        cases = [
            ({"verdict": "verified", "stage": "completed"}, "verified"),
            (stopped("baseline"), "readiness_blocked"),
            (stopped("runtime-detection"), "readiness_blocked"),
            (stopped("verifier-generation", regression_test={"generation_attempts": [{"status": "validation_failed"}]}),
             "verifier_invalid"),
            (stopped("verifier-generation", regression_test={"generation_attempts": [{"status": "inference_failed"}]}),
             "infrastructure_error"),
            (stopped("verifier-generation", error_type="PatchProofError<-InferenceError"), "infrastructure_error"),
            (stopped("verifier-reproduction", regression_test={"attempts": [
                {"classification": "test passed on the unfixed revision"}]}), "no_reproduction"),
            (stopped("verifier-reproduction", regression_test={"attempts": [
                {"classification": "generated TypeScript regression failed syntax parsing"}]}), "verifier_invalid"),
            (stopped("verifier-reproduction", regression_test={"attempts": [accepted]}), "readiness_blocked"),
            (stopped("verifier-reproduction", regression_test={"attempts": [
                {"classification": "generated TypeScript regression failed API type-check"},
                {"classification": "test passed on the unfixed revision"}]}), "no_reproduction"),
            (stopped("candidate-evaluation", candidates=[{"stage": "generation"}]), "repair_invalid"),
            (stopped("candidate-evaluation", candidates=[{"stage": "regression"}]), "repair_failed"),
            (stopped("clean-replay"), "replay_failed"),
            (stopped("verifier-generation", stop_reason="budget_exhausted"), "budget_exhausted"),
            (stopped("verifier-generation", stop_reason="needs_specification"), "needs_specification"),
            (stopped("verifier-generation", stop_reason="needs_specification",
                     regression_test={"spec": {"status": "invalid"}}), "spec_invalid"),
            (stopped("verifier-generation", regression_test={"spec": {"status": "invalid"}},
                     verifier={"profile_requested": "spec", "profile_used": "spec"}), "spec_invalid"),
            # After an automatic fall back the free-form verifier owns the outcome.
            (stopped("verifier-generation", regression_test={"spec": {"status": "invalid"}},
                     verifier={"profile_requested": "auto", "profile_used": "freeform",
                               "fallback": {"from": "spec", "to": "freeform"}}), "verifier_invalid"),
            (stopped("clean-replay", stop_reason="blocked_setup"), "delivery_blocked"),
        ]
        for record, expected in cases:
            with self.subTest(expected=expected, stage=record.get("stage")):
                self.assertEqual(self.bucket(record), expected)

    def test_only_evaluated_repairs_count_as_repair_evidence(self):
        evaluated = {b for b in outcomes.BUCKETS if b in outcomes.EVALUATED_REPAIR}
        self.assertEqual(evaluated, {"verified", "repair_failed", "replay_failed"})
        self.assertTrue(outcomes.classify_outcome(stopped("candidate-evaluation", candidates=[{"stage": "regression"}]))["evaluated_repair"])
        self.assertFalse(outcomes.classify_outcome(stopped("baseline"))["evaluated_repair"])

    def test_every_non_verified_bucket_maps_to_a_stop_reason(self):
        for bucket in outcomes.BUCKETS:
            if bucket in {"verified", "unclassified"}:
                continue
            self.assertIn(bucket, outcomes.STOP_REASON_FOR_BUCKET)

    def test_static_rejection_names_match_the_classifier(self):
        # Every string classify_reproduction can return for a gate that stops before the test runs.
        for name in ("generated TypeScript regression failed syntax parsing",
                     "generated TypeScript regression failed stream contract",
                     "generated TypeScript regression failed string-escape lint",
                     "generated TypeScript lint tooling unavailable",
                     "generated TypeScript regression failed semantic lint",
                     "generated TypeScript regression failed API type-check",
                     "generated test could not load a module"):
            self.assertTrue(outcomes.is_static_rejection(name), name)
        for name in ("test passed on the unfixed revision", "test failed without accepted assertion evidence",
                     "accepted assertion failure reproduced the issue"):
            self.assertFalse(outcomes.is_static_rejection(name), name)


class FinalizeTests(unittest.TestCase):
    def test_legacy_run_gets_a_stop_reason_and_sections(self):
        record = stopped("candidate-evaluation", candidates=[{"stage": "regression"}])
        proof.finalize_proof(record)
        self.assertEqual(record["stop_reason"], "verification_failed")
        self.assertEqual(record["outcome"]["bucket"], "repair_failed")
        self.assertIn("readiness", record)

    def test_existing_stop_reason_is_never_overwritten(self):
        record = stopped("verifier-reproduction", stop_reason="blocked_setup")
        proof.finalize_proof(record)
        self.assertEqual(record["stop_reason"], "blocked_setup")

    def test_verified_run_has_no_stop_reason(self):
        record = {"verdict": "verified", "stage": "completed", "candidates": []}
        proof.finalize_proof(record)
        self.assertNotIn("stop_reason", record)
        self.assertEqual(record["outcome"]["bucket"], "verified")

    def test_finalize_never_raises_on_a_malformed_proof(self):
        record = {"verdict": "rejected", "stage": "baseline", "runtime": "not-a-dict", "candidates": None}
        proof.finalize_proof(record)  # must not raise
        self.assertTrue("outcome" in record or "finalize_error" in record)

    def test_error_chain_names_the_root_cause(self):
        try:
            try:
                raise proof.InferenceError("model unreachable")
            except proof.InferenceError as inner:
                raise proof.PatchProofError("wrapped") from inner
        except proof.PatchProofError as error:
            self.assertEqual(proof._error_chain(error), "PatchProofError<-InferenceError")

    def test_report_shows_readiness_outcome_and_the_no_repair_note(self):
        record = stopped("baseline", "Baseline command failed for runtime node-typescript.",
                         runtime={"id": "node-typescript", "preflight_output": "ok"},
                         baseline={"existing_suite_passed": False, "tests_passed": 0, "command": "npm test"})
        proof.finalize_proof(record)
        report = proof.render_report(record)
        self.assertIn("## Readiness and outcome", report)
        self.assertIn("Outcome: `readiness_blocked`", report)
        self.assertIn("not evidence about repair quality", report)
        self.assertIn("To change:", report)


@unittest.skipUnless(pipeline.available(), "requires TypeScript, @types/node and tsx")
class ReadinessOnlyPipelineTests(unittest.TestCase):
    def project(self, tests=True):
        root = Path(tempfile.mkdtemp(prefix="readiness-"))
        put = lambda name, text: pipeline.write(root, name, text)
        runner = "node --import tsx --test --test-reporter=tap" + (" tests/*.test.ts" if tests else "")
        put("package.json", json.dumps({"type": "module", "scripts": {"test": runner}}))
        put("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"NodeNext","strict":true,'
                             '"allowImportingTsExtensions":true,"types":[],"noEmit":true},"include":["src/**/*.ts"]}')
        put("src/value.ts", "export const value = (): number => 1;\n")
        if tests:
            put("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; "
                "import {value} from '../src/value.ts'; test('number', () => assert.equal(typeof value(), 'number'));\n")
        put("patchproof.json", json.dumps({"runtime": "node-typescript"}))
        (root / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
        return root

    def run_ready(self, root, **kwargs):
        return pipeline.run_engine(Path(tempfile.mkdtemp()), root, root, proof.Issue(1, "Wrong value", "value() must return 2."),
                                   "unused", None, env_extra={"PATCHPROOF_READINESS_ONLY": "1"}, **kwargs)

    def test_readiness_only_makes_no_model_request_and_reports_ready(self):
        root = self.project()
        asked = []

        def no_model(**kwargs):
            asked.append(kwargs)
            raise AssertionError("readiness-only must not call the model")

        result, record, error = self.run_ready(root, model_text=no_model)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(asked, [])
        self.assertEqual(result["verdict"], "ready")
        proof.finalize_proof(result)
        self.assertEqual(result["readiness"]["status"], "ready")
        self.assertTrue(result["readiness"]["before_inference"])
        self.assertEqual(result["readiness"]["compatibility_coverage"], "present")
        self.assertEqual(result["outcome"]["bucket"], "unclassified")
        self.assertNotIn("regression_test", result)

    def test_project_with_no_tests_is_ready_but_flagged_as_unprotected(self):
        root = self.project(tests=False)
        result, record, error = self.run_ready(root, model_text=lambda **k: None)
        self.assertIsNone(error, json.dumps(record, default=str)[:3000])
        self.assertEqual(result["baseline"]["tests_passed"], 0)
        proof.finalize_proof(result)
        self.assertEqual(result["readiness"]["status"], "ready")
        self.assertEqual(result["readiness"]["compatibility_coverage"], "absent")
        self.assertIn("unrelated behavior is not protected", proof.render_report(result))

    def test_failing_baseline_blocks_before_any_model_request(self):
        root = self.project()
        (root / "tests/existing.test.ts").write_text(
            "import test from 'node:test'; import assert from 'node:assert/strict'; test('red', () => assert.equal(1, 2));\n")
        asked = []
        result, record, error = self.run_ready(root, model_text=lambda **k: asked.append(k))
        self.assertIsNotNone(error)
        self.assertEqual(asked, [])
        record["error"] = str(error)  # main() records the error text before it finalizes
        proof.finalize_proof(record)
        self.assertEqual(record["readiness"]["status"], "blocked")
        self.assertEqual(record["outcome"]["bucket"], "readiness_blocked")
        self.assertEqual(record["stop_reason"], "blocked_setup")
        self.assertIn("known_failures", record["readiness"]["blockers"][0]["change"])


if __name__ == "__main__":
    unittest.main()
