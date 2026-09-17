import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from shadow_engineer.repository import (canonical, sha, snapshot, inventory, commit, safe_path,
                                         lock_inputs, validate_lock, candidate)
from shadow_engineer.demo_external import seed, git_write
from shadow_engineer.external_proof import verify_external, evidence, write_report
from shadow_engineer.external_runners import LocalExternalFixtureRunner


class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.lock, self.heads = seed(self.repo)
        self.digest = sha(canonical(self.lock))

    def tearDown(self): self.temp.cleanup()

    def verify(self, head=None, runner=None):
        return verify_external(self.repo, head or self.heads[1], self.lock, self.digest,
                               runner or LocalExternalFixtureRunner())

    def test_real_pytest_regression_and_replay(self):
        bad, good = self.verify(self.heads[0]), self.verify()
        self.assertEqual(bad["status"], "rejected", bad)
        self.assertEqual(good["status"], "passed-checks", good)
        self.assertEqual(len(good["stages"]), 6)
        self.assertEqual(good["stages"][-1]["passed"], 3)

    def test_worktree_changes_are_excluded(self):
        before = snapshot(self.repo, self.heads[1])
        (self.repo / "shipping.py").write_text("raise RuntimeError('dirty worktree')")
        (self.repo / "untracked.py").write_text("untracked")
        self.assertEqual(before, snapshot(self.repo, self.heads[1]))

    def test_altered_lock_rejected_before_execution(self):
        self.lock["regression"] = "assert True"
        class Never:
            name, metadata = "test", {}
            def run(self, payload): raise AssertionError("Should not run")
        result = self.verify(runner=Never())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stages"], [])

    def test_candidate_test_change_blocked(self):
        (self.repo / "tests/test_existing.py").write_text("def test_fake(): pass")
        git_write(self.repo, "add", "."); git_write(self.repo, "commit", "-m", "Tamper with tests")
        report = self.verify(git_write(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["stages"], [])

    def test_test_cannot_be_allowlisted(self):
        with self.assertRaises(ValueError):
            lock_inputs(self.repo, self.lock["base_commit"], "issue", "test", ["tests/test_existing.py"],
                        ["tests/test_existing.py"], "pytest")

    def test_full_sha_required(self):
        for ref in ("HEAD", "main", self.heads[0][:7], "--help"):
            with self.assertRaises(ValueError): commit(self.repo, ref)

    def test_path_escape_rejected(self):
        for name in ("../file", "/tmp/file", "a/../b", ".git/config", "a\\b", "a\nb", "a//b"):
            with self.assertRaises(ValueError): safe_path(name)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support")
    def test_symlink_in_commit_rejected(self):
        (self.repo / "escape").symlink_to("/tmp")
        git_write(self.repo, "add", "."); git_write(self.repo, "commit", "-m", "Symlink")
        with self.assertRaises(ValueError): snapshot(self.repo, git_write(self.repo, "rev-parse", "HEAD"))

    def test_replay_failure_not_accepted(self):
        class ReplayFails(LocalExternalFixtureRunner):
            calls = 0
            def run(self, payload):
                self.calls += 1
                if self.calls == 6: return {"exit_code": -1, "xml": "", "inputs_unchanged": False}
                return super().run(payload)
        self.assertEqual(self.verify(runner=ReplayFails())["status"], "rejected")

    def test_changed_test_identity_rejected(self):
        class IdentityChanges(LocalExternalFixtureRunner):
            calls = 0
            def run(self, payload):
                self.calls += 1
                result = super().run(payload)
                if self.calls == 3:
                    result["xml"] = result["xml"].replace("test_next_gram", "test_unrelated")
                return result
        self.assertEqual(self.verify(runner=IdentityChanges())["status"], "rejected")

    def test_reports_never_overwrite(self):
        report = self.verify(self.heads[0])
        out = self.repo / "report"
        write_report(report, out)
        with self.assertRaises(FileExistsError): write_report(report, out)
        text = (out / "VERIFICATION_REPORT.md").read_text()
        self.assertIn(self.heads[0], text)
        self.assertIn("No PR or comment has been posted", text)

    def test_inventory_is_read_only(self):
        data = inventory(self.repo, self.lock["base_commit"])
        self.assertEqual(data["execution"], "none")
        self.assertEqual(data["stack_hints"], ["python"])


class EvidenceTests(unittest.TestCase):
    def test_invalid_empty_skipped_duplicate_evidence(self):
        for xml in ("", "<testsuites/>", '<testsuite><testcase name="t"><skipped/></testcase></testsuite>',
                    '<testsuite><testcase name="t"/><testcase name="t"/></testsuite>'):
            self.assertFalse(evidence({"exit_code": 0, "xml": xml, "inputs_unchanged": True})["green"])

    def test_inputs_must_remain_unchanged(self):
        result = evidence({"exit_code": 0, "xml": '<testsuite><testcase name="t"/></testsuite>',
                           "inputs_unchanged": False})
        self.assertFalse(result["green"])

    def test_collection_error_is_not_reproduction(self):
        self.assertFalse(evidence({"exit_code": 2, "xml": '<testsuite><testcase name="t"><error/></testcase></testsuite>',
                                   "inputs_unchanged": True})["red"])

    @unittest.skipUnless(shutil.which("node"), "Node required")
    def test_node_test_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            lock, heads = seed(Path(directory), "node-test")
            runner = LocalExternalFixtureRunner()
            bad = verify_external(directory, heads[0], lock, sha(canonical(lock)), runner)
            good = verify_external(directory, heads[1], lock, sha(canonical(lock)), runner)
            self.assertEqual(bad["status"], "rejected", bad)
            self.assertEqual(good["status"], "passed-checks", good)


if __name__ == "__main__": unittest.main()
