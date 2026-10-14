"""rc.30: the benchmark report separates where runs stopped and states coverage next to the solve rate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import outcomes
from bench import harness as h
from tests import test_bench_harness as base
from tests.test_bench_harness import cand, make_proof

GOOD = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+GOOD\n"
BAD = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+BAD\n"


def with_outcome(proof, *, requested="spec", used=None, spec=None, fallback=None):
    proof["verifier"] = {"profile_requested": requested, "profile_used": used or requested, "fallback": fallback}
    if spec is not None:
        proof["regression_test"]["spec"] = spec
    proof["outcome"] = outcomes.classify_outcome(proof)
    return proof


def write_trial(results: Path, case, trial, proof, **meta):
    folder = results / f"trial-v1-{case}-t{trial}"
    folder.mkdir(parents=True)
    record = {"case": case, "split": "dev", "trial": trial, "engine_ref": "v1", "model": "m",
              "manifest_sha256": "f" * 64, "timed_out": False, "elapsed_seconds": 9.0,
              "verifier_profile": "spec", **meta}
    if proof is not None:
        text = json.dumps(proof)
        (folder / "proof.json").write_text(text)
        if record.get("evidence_version") == 2:
            record["proof_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    (folder / "meta.json").write_text(json.dumps(record))


class SpecReportTests(unittest.TestCase):
    def build(self, root: Path):
        results, labels = root / "r", root / "l"
        labels.mkdir()
        (labels / "c1.json").write_text(json.dumps({h.diff_hash(GOOD): {"correct": True},
                                                      h.diff_hash(BAD): {"correct": False}}))
        grounded = {"status": "accepted", "spec_sha256": "a" * 64}
        write_trial(results, "c1", 1, with_outcome(
            make_proof("verified", "completed", winner=1, candidates=[cand(1, GOOD)]), spec=grounded))
        proof = make_proof("rejected", "verifier-generation", "The specification profile could not verify this issue: no example")
        proof["stop_reason"] = "needs_specification"
        write_trial(results, "c1", 2, with_outcome(proof, spec={"status": "unsupported", "reason": "no example"}))
        proof = make_proof("rejected", "verifier-generation", "The specification profile could not verify this issue: repeated")
        proof["stop_reason"] = "needs_specification"
        write_trial(results, "c1", 3, with_outcome(proof, spec={"status": "invalid"}))
        proof = make_proof(candidates=[{**cand(1, BAD), "stage": "regression"}])
        write_trial(results, "c1", 4, with_outcome(proof, spec=grounded))
        proof = make_proof("blocked", "baseline", "The unmodified repository fails its own test command.")
        proof["regression_test"] = {}
        write_trial(results, "c1", 5, with_outcome(proof, requested="spec"))
        manifest = {"schema": 1, "cases": [{"id": "c1", "split": "dev"}]}
        return h.write_report(results, root / "none", root / "out", manifest=manifest, labels_dir=labels)

    def test_buckets_coverage_and_repair_rate_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            written = self.build(root)
            rows = {r["trial"]: r for r in written["rows"]}
            self.assertEqual({t: r["bucket"] for t, r in rows.items()},
                             {1: "verified", 2: "needs_specification", 3: "spec_invalid", 4: "repair_failed",
                              5: "readiness_blocked"})
            self.assertEqual({t: r["outcome"] for t, r in rows.items()},
                             {1: h.TRUE_ACCEPT, 2: h.NEEDS_SPECIFICATION, 3: h.NEEDS_SPECIFICATION,
                              4: h.TRUE_REJECT, 5: h.INFRA})
            self.assertEqual({t: r["profile_covered"] for t, r in rows.items()},
                             {1: True, 2: False, 3: False, 4: True, 5: False})
            summary = json.loads((root / "out/results.json").read_text())["summary"]["v1/dev"]
            self.assertEqual((summary["end_to_end_success"], summary["effective"]), (1, 4))  # stops stay in the denominator
            self.assertEqual((summary["coverage_covered"], summary["coverage_runs"]), (2, 4))
            self.assertEqual((summary["repair_correct"], summary["repair_evaluated"]), (1, 2))
            self.assertEqual(summary["buckets"]["spec_invalid"], 1)
            self.assertEqual(summary["buckets"]["readiness_blocked"], 1)

    def test_the_markdown_puts_coverage_beside_the_solve_rate_and_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build(root)
            text = (root / "out/results.md").read_text()
            self.assertIn("## Profile coverage and repair rate", text)
            self.assertIn("| v1 | dev | 1/4 | 2/4 (50%) | 1/2 (50%) |", text)
            self.assertIn("## Where runs stopped", text)
            self.assertIn("Verifier profiles (requested): v1=spec", text)
            self.assertIn("count needs_specification and spec_invalid as unsolved", text)
            self.assertIn("stopped at the readiness check", text)

    def test_freeform_runs_have_no_coverage_figure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "r"
            write_trial(results, "c1", 1, with_outcome(
                make_proof("rejected", "verifier-reproduction", "no"), requested="freeform"), verifier_profile="freeform")
            manifest = {"schema": 1, "cases": [{"id": "c1", "split": "dev"}]}
            h.write_report(results, root / "o", root / "out", manifest=manifest, labels_dir=root / "l")
            text = (root / "out/results.md").read_text()
            self.assertIn("n/a (free-form verifier)", text)
            self.assertNotIn("count needs_specification and spec_invalid as unsolved", text)

    def test_pre_rc30_proofs_report_no_bucket_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "r"
            write_trial(results, "c1", 1, make_proof("rejected", "verifier-reproduction", "no"), verifier_profile="freeform")
            manifest = {"schema": 1, "cases": [{"id": "c1", "split": "dev"}]}
            written = h.write_report(results, root / "o", root / "out", manifest=manifest, labels_dir=root / "l")
            self.assertEqual(written["rows"][0]["bucket"], h.NO_BUCKET)
            self.assertFalse(written["rows"][0]["evaluated_repair"])

    def test_a_trial_whose_engine_ignored_the_verifier_profile_is_infra(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "r"
            proof = with_outcome(make_proof("rejected", "verifier-reproduction", "no"), requested="freeform")
            write_trial(results, "c1", 1, proof, evidence_version=2, verifier_profile="spec")
            trials = h.collect_results(results)
            self.assertIn("did not run the requested verifier profile", trials[0]["meta"]["evidence_error"])
            self.assertIn("spec requested, freeform recorded", trials[0]["meta"]["evidence_error"])

    def test_mixed_verifier_profiles_for_one_engine_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "r"
            write_trial(results, "c1", 1, with_outcome(make_proof("rejected", "verifier-reproduction", "no"), requested="spec"))
            write_trial(results, "c1", 2, with_outcome(make_proof("rejected", "verifier-reproduction", "no"), requested="freeform"),
                        verifier_profile="freeform")
            manifest = {"schema": 1, "cases": [{"id": "c1", "split": "dev"}]}
            with self.assertRaisesRegex(h.BenchError, "mixed execution profiles"):
                h.write_report(results, root / "o", root / "out", manifest=manifest, labels_dir=root / "l")


class TrialRecordsProfileTests(unittest.TestCase):
    """run_trial writes the requested verifier profile into meta.json (default freeform)."""

    def test_requested_verifier_profile_is_recorded(self):
        for env, expected in (({"PATCHPROOF_VERIFIER": "auto"}, "auto"), ({}, "freeform"), ({"PATCHPROOF_VERIFIER": ""}, "freeform")):
            with self.subTest(env=env), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                case = base.write_case_files(root, body="Body\n")
                (root / "bench").mkdir(exist_ok=True)
                (root / "bench/manifest.json").write_text(json.dumps({"schema": 1, "cases": [case]}))
                engine, subject = root / "engine", root / "subject"
                engine.mkdir()
                subject.mkdir()
                (engine / "proof.py").write_text(base.RunTrialTests.FAKE_ENGINE)
                meta = h.run_trial(case=case, trial=1, engine_ref="v", engine_dir=engine, subject=subject,
                                   out=root / "out", root=root, environ={"PATH": "", **env})
                self.assertEqual(meta["verifier_profile"], expected)


if __name__ == "__main__":
    unittest.main()
