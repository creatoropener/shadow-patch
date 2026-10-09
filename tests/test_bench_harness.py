"""Tests for the benchmark harness (bench/harness.py). No network, no model calls."""
from __future__ import annotations

import contextlib
import difflib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from bench import harness as h

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/fixtures/bench_rc20_verified_proof.json").read_text(encoding="utf-8"))
HAVE_TOOLS = bool(shutil.which("patch") and shutil.which("git") and shutil.which("node"))


def diff_of(before: str, after: str, path: str = "src/a.js") -> str:
    """Same construction the engine uses for a candidate's evidence diff."""
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile=path, tofile=path))


def make_proof(verdict="rejected", stage="candidate-evaluation", error="", candidates=(), winner=None):
    proof = {"app_version": "0.6.0-rc.test", "verdict": verdict, "stage": stage, "error": error,
             "candidates": [dict(c) for c in candidates], "regression_test": {"generation_attempts": [{}]}}
    if winner is not None:
        proof["winner"] = {"candidate": winner}
    return proof


def cand(number, diff="--- a\n+++ a\n@@ -1 +1 @@\n-x\n+y\n", evaluated=True):
    record = {"candidate": number, "diff": diff}
    if evaluated:
        record["image"] = "img"
    return record


def judge_from(mapping):
    return lambda digest: (mapping.get(digest), "test")


def write_case_files(root: Path, *, ready=True, body="Bug body.\n"):
    (root / "bench/issues").mkdir(parents=True, exist_ok=True)
    (root / "bench/issues/one.md").write_text(body if ready else "<<PASTE>>\n", encoding="utf-8")
    return {"id": "one", "split": "dev", "repo": "owner/repo", "base_commit": "a" * 40,
            "issue": {"number": 1, "title": "Title", "body_file": "bench/issues/one.md"}, "oracle": None}


class ManifestTests(unittest.TestCase):
    def test_shipped_manifest_is_structurally_valid_and_ready(self):
        manifest = h.load_manifest()
        self.assertEqual(h.validate_manifest(manifest), [])
        ready = h.validate_manifest(manifest, ready_ids={c["id"] for c in manifest["cases"] if c["split"] == "dev"})
        self.assertEqual(ready, [], "every shipped case must be filled in: " + "; ".join(ready))
        splits = {c["split"] for c in manifest["cases"]}
        self.assertEqual(splits, {"dev", "heldout"})

    def test_pinned_recorded_base_commit_matches_the_evidence_file(self):
        evidence = json.loads((ROOT / "docs/evidence/github-run-35464615209.json").read_text(encoding="utf-8"))
        case = next(c for c in h.load_manifest()["cases"] if c["id"] == "file-sharing-app-1")
        self.assertEqual(case["base_commit"], evidence["head_sha"])
        self.assertEqual(case["issue"]["title"], evidence["display_title"])

    def test_ready_case_passes_and_placeholders_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = write_case_files(root)
            self.assertEqual(h.case_problems(case, root, ready=True), [])
            case = write_case_files(root, ready=False)
            problems = h.case_problems(case, root, ready=True)
            self.assertTrue(any("placeholder" in p for p in problems))
            self.assertEqual(h.case_problems(case, root, ready=False), [])

    def test_structural_problems_are_always_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = write_case_files(root)
            case.update(id="Bad Id", split="staging", repo="no-slash")
            case["issue"]["body_file"] = "../escape.md"
            problems = "\n".join(h.case_problems(case, root, ready=False))
            for expected in ("id must be", "split must", "repo must", "relative path"):
                self.assertIn(expected, problems)

    def test_short_sha_is_not_accepted_for_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = write_case_files(root)
            case["base_commit"] = "abc1234"
            self.assertTrue(any("40-character" in p for p in h.case_problems(case, root, ready=True)))

    def test_duplicate_ids_and_oracle_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = write_case_files(root)
            twin = json.loads(json.dumps(case))
            twin["oracle"] = {"test_file": "bench/oracles/missing.js", "dest": "../x.js", "command": "node x"}
            problems = "\n".join(h.validate_manifest({"schema": 1, "cases": [case, twin]}, root))
            self.assertIn("duplicate id", problems)
            self.assertIn("does not exist", problems)
            self.assertIn("oracle.dest must be a relative path", problems)

    def test_body_is_read_byte_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = write_case_files(root, body="line one\r\nline two \r\n\r\n")
            self.assertEqual(h.read_body(case, root), "line one\r\nline two \r\n\r\n")


class PlanTests(unittest.TestCase):
    def ready_manifest(self, root, count=2, oracle=False):
        cases = []
        for index in range(count):
            case = write_case_files(root)
            case.update(id=f"c{index}", split="dev" if index == 0 else "heldout")
            if oracle and index == 0:
                (root / "bench/oracles").mkdir(parents=True, exist_ok=True)
                (root / "bench/oracles/t.js").write_text("// t\n")
                (root / "bench/oracles/ref.diff").write_text("placeholder for plan validation\n")
                case["oracle"] = {"test_file": "bench/oracles/t.js", "dest": "t.js", "command": "node t.js", "reference_patch": "bench/oracles/ref.diff", "failure_evidence": "node-test"}
            cases.append(case)
        return {"schema": 1, "cases": cases}

    def test_matrix_interleaves_engines_within_each_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = h.build_plan(self.ready_manifest(root), engines=["v1", "v2"], trials=2,
                                split="all", ids=[], root=root)
            order = [(j["trial"], j["case"], j["engine"]) for j in plan["matrix"]["include"]]
            self.assertEqual(order, [(1, "c0", "v1"), (1, "c0", "v2"), (1, "c1", "v1"), (1, "c1", "v2"),
                                     (2, "c0", "v1"), (2, "c0", "v2"), (2, "c1", "v1"), (2, "c1", "v2")])
            self.assertEqual(plan["jobs"], 8)
            self.assertFalse(plan["has_oracle"])

    def test_split_and_case_filters_and_oracle_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.ready_manifest(root, oracle=True)
            dev = h.build_plan(manifest, engines=["v1"], trials=1, split="dev", ids=[], root=root)
            self.assertEqual([j["case"] for j in dev["matrix"]["include"]], ["c0"])
            self.assertEqual([c["case"] for c in dev["oracle_cases"]["include"]], ["c0"])
            held = h.build_plan(manifest, engines=["v1"], trials=1, split="heldout", ids=[], root=root)
            self.assertFalse(held["has_oracle"])
            one = h.build_plan(manifest, engines=["v1"], trials=1, split="all", ids=["c1"], root=root)
            self.assertEqual([j["case"] for j in one["matrix"]["include"]], ["c1"])

    def test_unselected_unfinished_cases_do_not_block_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.ready_manifest(root)
            manifest["cases"][1]["base_commit"] = "TODO"
            plan = h.build_plan(manifest, engines=["v1"], trials=1, split="all", ids=["c0"], root=root)
            self.assertEqual(plan["jobs"], 1)
            with self.assertRaises(h.BenchError) as raised:
                h.build_plan(manifest, engines=["v1"], trials=1, split="all", ids=[], root=root)
            self.assertIn("c1", str(raised.exception))

    def test_bad_inputs_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.ready_manifest(root)
            for kwargs in ({"engines": []}, {"engines": ["--evil"]}, {"engines": ["a/../b"]},
                           {"engines": ["v1", "v1"]}, {"trials": 0}, {"trials": 6},
                           {"split": "prod"}, {"ids": ["nope"]}):
                params = {"engines": ["v1"], "trials": 1, "split": "all", "ids": [], **kwargs}
                with self.subTest(kwargs=kwargs), self.assertRaises(h.BenchError):
                    h.build_plan(manifest, root=root, **params)

    def test_workflow_only_uses_matrix_fields_the_plan_provides(self):
        workflow = (ROOT / ".github/workflows/benchmark.yml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = h.build_plan(self.ready_manifest(root, oracle=True), engines=["v1"], trials=1,
                                split="all", ids=[], root=root)
        trial_keys = set(plan["matrix"]["include"][0])
        oracle_keys = set(plan["oracle_cases"]["include"][0])
        used = set(re.findall(r"matrix\.(\w+)", workflow))
        self.assertTrue(used <= trial_keys | oracle_keys, used - (trial_keys | oracle_keys))
        for name in re.findall(r"matrix\.(\w+)", workflow.split("  oracle:")[1].split("  report:")[0]):
            self.assertIn(name, oracle_keys)


class ClassificationTests(unittest.TestCase):
    META = {"timed_out": False}

    def classify(self, proof, mapping=None, meta=None):
        return h.classify_trial(meta or self.META, proof, judge_from(mapping or {}))

    def test_real_rc20_verified_run_with_and_without_a_judgement(self):
        winner = next(c for c in FIXTURE["candidates"] if c["candidate"] == FIXTURE["winner"]["candidate"])
        digest = h.diff_hash(winner["diff"])
        self.assertEqual(self.classify(FIXTURE, {digest: True})[0], h.TRUE_ACCEPT)
        self.assertEqual(self.classify(FIXTURE, {digest: False})[0], h.FALSE_ACCEPT)
        self.assertEqual(self.classify(FIXTURE)[0], h.VERIFIED_UNLABELED)

    def test_infrastructure_outcomes(self):
        self.assertEqual(self.classify(None)[0], h.INFRA)
        self.assertEqual(self.classify(make_proof(), meta={"timed_out": True})[0], h.INFRA)
        self.assertEqual(self.classify(make_proof("blocked", "baseline", "tests fail"))[0], h.INFRA)
        self.assertEqual(self.classify(make_proof("rejected", "verifier-generation",
                                                  "Inference HTTP 503. Try again."))[0], h.INFRA)
        self.assertEqual(self.classify(make_proof("verified", "completed", winner=9,
                                                  candidates=[cand(1)]))[0], h.INFRA)

    def test_verifier_failures_have_no_candidates_to_judge(self):
        for stage in ("verifier-generation", "verifier-reproduction"):
            outcome, reason = self.classify(make_proof("rejected", stage, "Verifier test block is empty."))
            self.assertEqual(outcome, h.VERIFIER_FAILED)
            self.assertIn(stage, reason)

    def test_rejected_run_with_a_correct_candidate_is_a_false_reject(self):
        good, bad = cand(1, "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+GOOD\n"), cand(2, "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+BAD\n")
        mapping = {h.diff_hash(good["diff"]): True, h.diff_hash(bad["diff"]): False}
        outcome, reason = self.classify(make_proof(candidates=[good, bad]), mapping)
        self.assertEqual(outcome, h.FALSE_REJECT)
        self.assertIn("[1]", reason)

    def test_rejected_true_and_unlabeled(self):
        a, b = cand(1, "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+A\n"), cand(2, "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+B\n")
        both_bad = {h.diff_hash(a["diff"]): False, h.diff_hash(b["diff"]): False}
        self.assertEqual(self.classify(make_proof(candidates=[a, b]), both_bad)[0], h.TRUE_REJECT)
        half = {h.diff_hash(a["diff"]): False}
        self.assertEqual(self.classify(make_proof(candidates=[a, b]), half)[0], h.REJECTED_UNLABELED)
        self.assertEqual(self.classify(make_proof(candidates=[{"candidate": 1, "image": "i"}]))[0], h.TRUE_REJECT)

    def test_clean_replay_rejection_counts_as_candidate_stage(self):
        good = cand(1)
        outcome, _ = self.classify(make_proof(stage="clean-replay", candidates=[good]),
                                   {h.diff_hash(good["diff"]): True})
        self.assertEqual(outcome, h.FALSE_REJECT)

    def test_unknown_verdict_is_infra_not_silently_counted(self):
        self.assertEqual(self.classify(make_proof("weird"))[0], h.INFRA)


class JudgeAndStatsTests(unittest.TestCase):
    def test_oracle_wins_label_fills_gaps_invalid_oracle_is_ignored(self):
        labels = {"aaa": {"correct": False}, "bbb": {"correct": True}}
        oracle = {"valid": True, "diffs": {"aaa": {"passed": True}, "ccc": {"passed": None}}}
        judge = h.make_judge("c", oracle, labels)
        self.assertEqual(judge("aaa"), (True, "oracle"))
        self.assertEqual(judge("bbb"), (True, "label"))
        self.assertEqual(judge("ccc"), (None, "none"))
        invalid = h.make_judge("c", {"valid": False, "diffs": {"aaa": {"passed": True}}}, labels)
        self.assertEqual(invalid("aaa"), (False, "label"))

    def test_diff_hash_preserves_line_endings_and_trailing_space(self):
        base = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+y\n"
        self.assertNotEqual(h.diff_hash(base), h.diff_hash(base.replace("\n", "\r\n")))
        self.assertNotEqual(h.diff_hash(base), h.diff_hash(base.replace("+y", "+y   ")))
        self.assertEqual(len(h.diff_hash(base)), 64)
        self.assertNotEqual(h.diff_hash(base), h.diff_hash(base.replace("+y", "+z")))

    def test_labels_file_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            labels = Path(directory)
            (labels / "c.json").write_text('{"abc": {"correct": "yes"}}')
            with self.assertRaises(h.BenchError):
                h.load_labels("c", labels)
            self.assertEqual(h.load_labels("missing", labels), {})

    def test_wilson_interval(self):
        self.assertIsNone(h.wilson(0, 0))
        low, high = h.wilson(3, 3)
        self.assertGreater(low, 0.4)
        self.assertEqual(high, 1.0)
        low, high = h.wilson(0, 3)
        self.assertEqual(low, 0.0)
        self.assertLess(high, 0.6)

    def test_summary_excludes_only_infra(self):
        rows = [{"outcome": o} for o in (h.TRUE_ACCEPT, h.TRUE_ACCEPT, h.FALSE_REJECT, h.VERIFIER_FAILED,
                                         h.INFRA, h.VERIFIED_UNLABELED)]
        summary = h.summarize(rows)
        self.assertEqual((summary["trials"], summary["infra"], summary["effective"]), (6, 1, 5))
        self.assertEqual((summary["end_to_end_success"], summary["end_to_end_upper"]), (2, 3))
        self.assertAlmostEqual(summary["verifier_failure_rate"], 0.2)


class ReportTests(unittest.TestCase):
    def write_trial(self, results: Path, engine, case, trial, proof, **meta):
        folder = results / f"trial-{engine}-{case}-t{trial}"
        folder.mkdir(parents=True)
        record = {"case": case, "split": "dev", "trial": trial, "engine_ref": engine, "model": "m",
                  "manifest_sha256": "f" * 64, "timed_out": False, "elapsed_seconds": 12.5, **meta}
        (folder / "meta.json").write_text(json.dumps(record))
        if proof is not None:
            (folder / "proof.json").write_text(json.dumps(proof))

    def test_end_to_end_report_with_labels_and_oracle(self):
        good = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+GOOD\n"
        bad = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+BAD\n"
        other = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+OTHER\n"
        manifest = {"schema": 1, "cases": [
            {"id": "c1", "split": "dev"}, {"id": "c2", "split": "heldout"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results, oracle, labels, out = root / "r", root / "o", root / "l", root / "out"
            labels.mkdir()
            (labels / "c1.json").write_text(json.dumps({h.diff_hash(good): {"correct": True},
                                                          h.diff_hash(bad): {"correct": False}}))
            self.write_trial(results, "v1", "c1", 1, make_proof("verified", "completed", winner=1,
                                                                candidates=[cand(1, good)]))
            self.write_trial(results, "v1", "c1", 2, make_proof(candidates=[cand(1, good), cand(2, bad)]))
            self.write_trial(results, "v1", "c1", 3, make_proof("rejected", "verifier-reproduction", "no"))
            self.write_trial(results, "v1", "c2", 1, make_proof("verified", "completed", winner=1,
                                                                candidates=[cand(1, other)]), split="heldout")
            self.write_trial(results, "v1", "c2", 2, None, split="heldout")
            oracle.mkdir()
            (oracle / "oracle-c2.json").write_text(json.dumps(
                {"case": "c2", "valid": True, "diffs": {h.diff_hash(other): {"passed": False}}}))
            written = h.write_report(results, oracle, out, manifest=manifest, labels_dir=labels)
            outcomes = {(r["case"], r["trial"]): r["outcome"] for r in written["rows"]}
            self.assertEqual(outcomes, {("c1", 1): h.TRUE_ACCEPT, ("c1", 2): h.FALSE_REJECT,
                                        ("c1", 3): h.VERIFIER_FAILED, ("c2", 1): h.FALSE_ACCEPT,
                                        ("c2", 2): h.INFRA})
            self.assertEqual(written["needed"], [])
            summary = json.loads((out / "results.json").read_text())["summary"]
            self.assertEqual(summary["v1/dev"]["counts"][h.TRUE_ACCEPT], 1)
            self.assertEqual(summary["v1/heldout"]["infra"], 1)
            markdown = (out / "results.md").read_text()
            self.assertIn("Read before quoting", markdown)
            self.assertIn("infrastructure failures", markdown)
            self.assertIn("Only 1 held-out case", markdown)

    def test_unjudged_diffs_are_listed_and_not_counted_as_success(self):
        manifest = {"schema": 1, "cases": [{"id": "c1", "split": "dev"}]}
        diff = "--- a\n+++ a\n@@ -1 +1 @@\n-x\n+NEW\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results, out = root / "r", root / "out"
            for trial in (1, 2):
                self.write_trial(results, "v1", "c1", trial, make_proof(
                    "verified", "completed", winner=1, candidates=[cand(1, diff)]))
            written = h.write_report(results, root / "none", out, manifest=manifest, labels_dir=root / "l")
            self.assertEqual({r["outcome"] for r in written["rows"]}, {h.VERIFIED_UNLABELED})
            self.assertEqual(len(written["needed"]), 1)
            self.assertEqual(len(written["needed"][0]["seen"]), 2)
            needed = (out / "labels-needed.md").read_text()
            self.assertIn(h.diff_hash(diff), needed)
            self.assertIn("+NEW", needed)
            self.assertIn("0/2 (up to 2)", (out / "results.md").read_text())

    def test_blocked_configuration_trial_is_shown_with_its_reason_and_no_rates(self):
        # The real first live trial: CONTREE_IMAGE was not set in shadow-patch.
        manifest = {"schema": 1, "cases": [{"id": "c1", "split": "dev"}]}
        proof = {"app_version": "0.6.0-rc.20", "verdict": "blocked", "stage": "configuration",
                 "candidates": [], "error": "Required environment variable CONTREE_IMAGE is missing."}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_trial(root / "r", "v1", "c1", 1, proof, exit_code=1)
            written = h.write_report(root / "r", root / "o", root / "out", manifest=manifest,
                                     labels_dir=root / "l")
            row = written["rows"][0]
            self.assertEqual(row["outcome"], h.INFRA)
            self.assertIn("CONTREE_IMAGE is missing", row["reason"])
            markdown = (root / "out/results.md").read_text()
            self.assertIn("0/0", markdown)
            self.assertIn("no held-out cases", markdown)
            self.assertNotIn("Only 0 held-out", markdown)
            summary = json.loads((root / "out/results.json").read_text())["summary"]["v1/dev"]
            self.assertIsNone(summary["end_to_end_ci"])
            self.assertIsNone(summary["verifier_failure_rate"])

    def test_empty_results_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(h.BenchError):
            h.write_report(Path(directory), Path(directory) / "o", Path(directory) / "out",
                           manifest={"schema": 1, "cases": []})


class RunTrialTests(unittest.TestCase):
    FAKE_ENGINE = textwrap.dedent('''\
        import argparse, json, sys, time
        from pathlib import Path
        parser = argparse.ArgumentParser()
        parser.add_argument("--repo"); parser.add_argument("--issue-number")
        parser.add_argument("--issue-title"); parser.add_argument("--issue-body")
        args = parser.parse_args()
        repo = Path(args.repo)
        if "SLEEP" in args.issue_body:
            time.sleep(30)
        (repo / "proof.json").write_text(json.dumps({"verdict": "rejected", "stage": "verifier-generation",
            "app_version": "fake", "seen_title": args.issue_title, "seen_body": args.issue_body,
            "seen_number": args.issue_number}))
        (repo / "verification-report.md").write_text("report")
        print("fake engine ran"); sys.exit(1)
        ''')

    def setup_case(self, root, body):
        case = write_case_files(root, body=body)
        (root / "bench").mkdir(exist_ok=True)
        (root / "bench/manifest.json").write_text(json.dumps({"schema": 1, "cases": [case]}))
        engine = root / "engine"
        engine.mkdir()
        (engine / "proof.py").write_text(self.FAKE_ENGINE)
        subject = root / "subject"
        subject.mkdir()
        return case, engine, subject

    def test_engine_gets_the_exact_issue_and_failure_is_recorded_not_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = "Line one\r\n\r\n  indented \"quoted\" `tick`\r\n"
            case, engine, subject = self.setup_case(root, body)
            meta = h.run_trial(case=case, trial=2, engine_ref="v-test", engine_dir=engine, subject=subject,
                               out=root / "out", root=root, environ={"NEBIUS_MODEL": "m/x", "PATH": ""})
            self.assertEqual((meta["exit_code"], meta["timed_out"], meta["has_proof"]), (1, False, True))
            proof = json.loads((root / "out/proof.json").read_text())
            self.assertEqual((proof["seen_title"], proof["seen_number"], proof["seen_body"]), ("Title", "1", body))
            self.assertEqual(meta["issue_body_sha256"], __import__("hashlib").sha256(body.encode()).hexdigest())
            self.assertEqual((meta["engine_ref"], meta["trial"], meta["model"]), ("v-test", 2, "m/x"))
            self.assertIn("fake engine ran", (root / "out/engine-stdout.txt").read_text())
            self.assertTrue((root / "out/verification-report.md").is_file())

    def test_body_or_title_starting_with_a_dash_is_still_a_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = "--not-an-option\n- a list item\n"
            case, engine, subject = self.setup_case(root, body)
            case["issue"]["title"] = "-starts with dash"
            h.run_trial(case=case, trial=1, engine_ref="v", engine_dir=engine, subject=subject,
                        out=root / "out", root=root, environ={"PATH": ""})
            proof = json.loads((root / "out/proof.json").read_text())
            self.assertEqual((proof["seen_body"], proof["seen_title"]), (body, "-starts with dash"))

    def test_timeout_is_recorded_and_classified_as_infra(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case, engine, subject = self.setup_case(root, "SLEEP\n")
            meta = h.run_trial(case=case, trial=1, engine_ref="v", engine_dir=engine, subject=subject,
                               out=root / "out", root=root, timeout_seconds=1, environ={"PATH": ""})
            self.assertTrue(meta["timed_out"])
            self.assertFalse(meta["has_proof"])
            self.assertEqual(h.classify_trial(meta, None, judge_from({}))[0], h.INFRA)


class PatchproofConfigTests(unittest.TestCase):
    """A case can replace the pinned commit's patchproof.json before the engine runs."""

    REPORTING_ENGINE = textwrap.dedent('''\
        import argparse, json, sys
        from pathlib import Path
        parser = argparse.ArgumentParser()
        parser.add_argument("--repo"); parser.add_argument("--issue-number")
        parser.add_argument("--issue-title"); parser.add_argument("--issue-body")
        repo = Path(parser.parse_args().repo)
        config = repo / "patchproof.json"
        (repo / "proof.json").write_text(json.dumps({"verdict": "rejected", "stage": "verifier-generation",
            "app_version": "fake", "seen_config": config.read_text() if config.is_file() else None}))
        sys.exit(1)
        ''')

    def run_case(self, root, config, *, existing=None):
        case = write_case_files(root)
        if config is not None:
            case["patchproof_config"] = config
        (root / "bench").mkdir(exist_ok=True)
        (root / "bench/manifest.json").write_text(json.dumps({"schema": 1, "cases": [case]}))
        engine = root / "engine"
        engine.mkdir()
        (engine / "proof.py").write_text(self.REPORTING_ENGINE)
        subject = root / "subject"
        subject.mkdir()
        if existing is not None:
            (subject / "patchproof.json").write_text(existing)
        meta = h.run_trial(case=case, trial=1, engine_ref="v", engine_dir=engine, subject=subject,
                           out=root / "out", root=root, environ={"PATH": ""})
        proof = json.loads((root / "out/proof.json").read_text())
        return case, subject, meta, proof

    def test_pinned_file_is_replaced_not_merged_and_recorded(self):
        pinned = '{\n  "runtime": "node-package",\n  "test_directory": "old"\n}\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, subject, meta, proof = self.run_case(root, {"runtime": "node-typescript"}, existing=pinned)
            self.assertEqual(json.loads(proof["seen_config"]), {"runtime": "node-typescript"})
            self.assertEqual(json.loads((subject / "patchproof.json").read_text()), {"runtime": "node-typescript"})
            self.assertEqual(meta["patchproof_config"], {"runtime": "node-typescript"})
            self.assertEqual(meta["replaced_patchproof_json_sha256"],
                             __import__("hashlib").sha256(pinned.encode()).hexdigest())
            self.assertEqual(json.loads((root / "out/meta.json").read_text())["patchproof_config"],
                             {"runtime": "node-typescript"})

    def test_override_is_created_when_the_commit_has_no_file(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, meta, proof = self.run_case(Path(directory), {"runtime": "node-typescript"})
            self.assertEqual(json.loads(proof["seen_config"]), {"runtime": "node-typescript"})
            self.assertIsNone(meta["replaced_patchproof_json_sha256"])

    def test_empty_object_removes_the_pin_so_the_engine_auto_detects(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, meta, proof = self.run_case(Path(directory), {}, existing='{"runtime": "node-package"}')
            self.assertEqual(json.loads(proof["seen_config"]), {})
            self.assertEqual(meta["patchproof_config"], {})

    def test_ordinary_case_leaves_the_checkout_and_the_meta_alone(self):
        pinned = '{"runtime": "node-package"}'
        with tempfile.TemporaryDirectory() as directory:
            _, subject, meta, proof = self.run_case(Path(directory), None, existing=pinned)
            self.assertEqual(proof["seen_config"], pinned)
            self.assertEqual((subject / "patchproof.json").read_text(), pinned)
            self.assertNotIn("patchproof_config", meta)
            self.assertNotIn("replaced_patchproof_json_sha256", meta)

    def test_bad_config_is_a_manifest_problem_and_never_written(self):
        bad = [
            ("not-an-object", ["runtime"]),
            ("unknown key", {"runtime": "node-typescript", "image": "x"}),
            ("runtime must be a string", {"runtime": 7}),
            ("runtime id shape", {"runtime": "Node TypeScript"}),
            ("absolute test directory", {"test_directory": "/etc"}),
            ("parent test directory", {"test_directory": "../out"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, config in bad:
                case = write_case_files(root)
                case["patchproof_config"] = config
                problems = h.case_problems(case, root, ready=False)
                self.assertTrue(problems, label)
                self.assertTrue(all(p.startswith("one: ") for p in problems), label)
                subject = root / "subject-" / label.replace(" ", "-")
                subject.mkdir(parents=True)
                with self.assertRaises(h.BenchError, msg=label):
                    h.apply_patchproof_config(subject, case)
                self.assertFalse((subject / "patchproof.json").exists(), label)

    def test_good_configs_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for config in ({}, {"runtime": "node-typescript"}, {"runtime": "go", "test_directory": ""},
                           {"runtime": "node-package", "test_directory": "spec/unit"}):
                case = write_case_files(root)
                case["patchproof_config"] = config
                self.assertEqual(h.case_problems(case, root, ready=True), [], config)

    def test_engine_accepts_the_written_file_and_can_then_edit_typescript(self):
        # The file-sharing-app-1 situation in miniature: a stale node-package pin in a
        # TypeScript project. Under the pin the bug's file is not editable; after the
        # harness writes the manifest's config, the engine's own detection picks
        # node-typescript and the file is editable. Guards the key names too.
        import runtimes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in (("package.json", "{}"), ("tsconfig.json", "{}"),
                               ("lib/format.ts", "export const x = 1;\n"),
                               ("patchproof.json", '{"runtime": "node-package"}')):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            pinned = runtimes.detect_runtime(root)
            self.assertEqual(pinned.id, "node-package")
            self.assertFalse(pinned.is_editable_source(Path("lib/format.ts")))
            h.apply_patchproof_config(root, {"id": "one", "patchproof_config": {"runtime": "node-typescript"}})
            fixed = runtimes.detect_runtime(root)
            self.assertEqual(fixed.id, "node-typescript")
            self.assertTrue(fixed.is_editable_source(Path("lib/format.ts")))

    def test_shipped_file_sharing_case_overrides_the_stale_pin(self):
        case = next(c for c in h.load_manifest()["cases"] if c["id"] == "file-sharing-app-1")
        self.assertEqual(case["patchproof_config"]["runtime"], "node-typescript")
        self.assertEqual(case["patchproof_config"]["scope"]["protected_symbols"], {"lib/utils/format.ts": ["formatEta"]})
        qr = next(c for c in h.load_manifest()["cases"] if c["id"] == "qrcrafts-1")
        self.assertNotIn("patchproof_config", qr)
        self.assertEqual(h.validate_manifest(h.load_manifest(), ready_ids={"file-sharing-app-1", "qrcrafts-1"}), [])

    def test_report_says_which_cases_ran_under_an_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            for name, extra in (("one", {"patchproof_config": {"runtime": "node-typescript"}}), ("two", {})):
                folder = results / f"trial-v-{name}-t1"
                folder.mkdir(parents=True)
                (folder / "meta.json").write_text(json.dumps({
                    "case": name, "split": "dev", "trial": 1, "engine_ref": "v", "model": "m",
                    "manifest_sha256": "f" * 64, "timed_out": False, "elapsed_seconds": 1.0, **extra}))
                (folder / "proof.json").write_text(json.dumps(make_proof(
                    verdict="rejected", stage="verifier-generation")))
            manifest = {"schema": 1, "cases": [dict(write_case_files(root), id="one"), dict(write_case_files(root), id="two")]}
            report = h.write_report(results, root / "no-oracle", root / "out", manifest=manifest,
                                    labels_dir=root / "no-labels")
            rows = {r["case"]: r for r in report["rows"]}
            self.assertEqual(rows["one"]["runtime_override"], {"runtime": "node-typescript"})
            self.assertIsNone(rows["two"]["runtime_override"])
            text = (root / "out/results.md").read_text()
            self.assertIn("`one` ran with the repository's patchproof.json replaced", text)
            self.assertNotIn("`two` ran with the repository's patchproof.json replaced", text)


@unittest.skipUnless(HAVE_TOOLS, "needs git, patch and node")
class OracleTests(unittest.TestCase):
    ORIGINAL = "exports.add = (a, b) => a - b;\n"
    FIXED = "exports.add = (a, b) => a + b;\n"
    ORACLE = textwrap.dedent('''\
        const test = require("node:test");
        const assert = require("node:assert");
        const { add } = require("../src/a.js");
        test("adds", () => assert.strictEqual(add(2, 3), 5));
        ''')

    def make_repo(self, root: Path) -> Path:
        repo = root / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src/a.js").write_text(self.ORIGINAL)
        (repo / ".gitignore").write_text("node_modules\n")
        for command in (["git", "init", "-q"], ["git", "add", "-A"],
                        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
            subprocess.run(command, cwd=repo, check=True)
        return repo

    def make_case(self, root: Path, command="node --test --test-reporter=tap tests/bench_oracle.test.js", oracle_source=None):
        (root / "bench/oracles").mkdir(parents=True)
        (root / "bench/oracles/o.test.js").write_text(oracle_source or self.ORACLE)
        case = write_case_files(root)
        (root / "bench/oracles/ref.diff").write_text(diff_of(self.ORIGINAL, self.FIXED))
        return {**case, "id": "c", "oracle": {"test_file": "bench/oracles/o.test.js",
                "dest": "tests/bench_oracle.test.js", "command": command,
                "reference_patch": "bench/oracles/ref.diff", "failure_evidence": "node-test"}}

    def test_apply_and_reset_use_the_engines_diff_format(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            diff = diff_of(self.ORIGINAL, self.FIXED)
            self.assertEqual(h.apply_diff(repo, diff), (True, ""))
            self.assertEqual((repo / "src/a.js").read_text(), self.FIXED)
            h.reset_checkout(repo)
            self.assertEqual((repo / "src/a.js").read_text(), self.ORIGINAL)

    def test_multi_file_diff_joined_the_way_the_engine_joins_it(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            (repo / "src/b.js").write_text("module.exports = 1;\n")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "b"],
                           cwd=repo, check=True)
            combined = "\n".join([diff_of(self.ORIGINAL, self.FIXED),
                                  diff_of("module.exports = 1;\n", "module.exports = 2;\n", "src/b.js")])
            self.assertEqual(len(h.split_diff(combined)), 2)
            self.assertEqual(h.apply_diff(repo, combined), (True, ""))
            self.assertEqual((repo / "src/b.js").read_text(), "module.exports = 2;\n")

    def test_bad_diffs_are_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(Path(directory))
            self.assertFalse(h.apply_diff(repo, "not a diff")[0])
            stale = diff_of("something else\n", "changed\n")
            self.assertFalse(h.apply_diff(repo, stale)[0])
            self.assertFalse(h.apply_diff(repo, diff_of("a\n", "b\n", "../outside.js"))[0])
            self.assertEqual((repo / "src/a.js").read_text(), self.ORIGINAL)

    def test_oracle_separates_a_correct_from_a_wrong_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            case = self.make_case(root)
            results = root / "results"
            good = diff_of(self.ORIGINAL, self.FIXED)
            wrong = diff_of(self.ORIGINAL, "exports.add = (a, b) => a * b;\n")
            stale = diff_of("no such line\n", "x\n")
            for trial, diffs in ((1, [good, wrong]), (2, [good, stale])):
                folder = results / f"trial-{trial}"
                folder.mkdir(parents=True)
                (folder / "meta.json").write_text(json.dumps({"case": "c", "trial": trial, "engine_ref": "v"}))
                (folder / "proof.json").write_text(json.dumps(
                    {"candidates": [{"candidate": i + 1, "diff": d} for i, d in enumerate(diffs)]}))
            result = h.run_oracle(case, results, repo, root=root)
            self.assertTrue(result["valid"])
            self.assertEqual(len(result["diffs"]), 3, "the correct diff is judged once, not once per trial")
            self.assertIs(result["diffs"][h.diff_hash(good)]["passed"], True)
            self.assertIs(result["diffs"][h.diff_hash(wrong)]["passed"], False)
            self.assertIsNone(result["diffs"][h.diff_hash(stale)]["passed"])
            self.assertEqual((repo / "src/a.js").read_text(), self.ORIGINAL)
            self.assertFalse((repo / "tests/bench_oracle.test.js").exists())

    def test_oracle_that_passes_on_the_unfixed_base_is_declared_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            case = self.make_case(root, oracle_source='require("node:test")("always", () => {});\n')
            (root / "results").mkdir()
            result = h.run_oracle(case, root / "results", repo, root=root)
            self.assertFalse(result["valid"])
            self.assertIn("unfixed base", result["reason"])

    def test_failed_setup_invalidates_the_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            case = self.make_case(root)
            case["oracle"]["setup"] = "exit 3"
            (root / "results").mkdir()
            result = h.run_oracle(case, root / "results", repo, root=root)
            self.assertFalse(result["valid"])
            self.assertIn("setup failed", result["reason"])

    def test_runtime_crash_is_not_a_valid_oracle_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            case = self.make_case(root, oracle_source='require("node:test")("case", () => { throw new Error("boom"); });\n')
            result = h.run_oracle(case, root / "results", repo, root=root)
            self.assertFalse(result["valid"])
            self.assertIn("recognized assertion", result["reason"])

    def test_a_reference_repair_must_pass_before_candidates_are_judged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root)
            case = self.make_case(root)
            (root / case["oracle"]["reference_patch"]).write_text(
                diff_of(self.ORIGINAL, "exports.add = (a, b) => a * b;\n"))
            result = h.run_oracle(case, root / "results", repo, root=root)
            self.assertFalse(result["valid"])
            self.assertIn("reference repair", result["reason"])
            self.assertEqual(result["diffs"], {})


class CliTests(unittest.TestCase):
    def run_main(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = h.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_validate_and_unready_plan_exit_codes(self):
        self.assertEqual(self.run_main("validate")[0], 0)
        self.assertEqual(self.run_main("validate", "--ready")[0], 1)  # unseen placeholders remain unselected
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"schema": 1, "cases": [write_case_files(root, ready=False)]}
            path = root / "bench/manifest.json"
            path.write_text(json.dumps(manifest))
            original_root, original_manifest = h.ROOT, h.MANIFEST_PATH
            h.ROOT, h.MANIFEST_PATH = root, path
            try:
                validate_code, _, _ = self.run_main("validate", "--ready")
                plan_code, _, stderr = self.run_main("plan", "--engines", "v0.6.0-rc.20", "--cases", "one")
            finally:
                h.ROOT, h.MANIFEST_PATH = original_root, original_manifest
        self.assertEqual(validate_code, 1)
        self.assertEqual(plan_code, 2)
        self.assertIn("not ready to run", stderr)

    def test_plan_writes_github_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"schema": 1, "cases": [write_case_files(root)]}
            path = root / "bench/manifest.json"
            path.write_text(json.dumps(manifest))
            original_root, original_manifest = h.ROOT, h.MANIFEST_PATH
            h.ROOT, h.MANIFEST_PATH = root, path
            try:
                output = root / "gh_output"
                code = h.main(["plan", "--engines", "v1,v2", "--trials", "2", "--github-output", str(output)])
            finally:
                h.ROOT, h.MANIFEST_PATH = original_root, original_manifest
            self.assertEqual(code, 0)
            lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual(len(json.loads(lines["matrix"])["include"]), 4)
            self.assertEqual(lines["has_oracle"], "false")


if __name__ == "__main__":
    unittest.main()
