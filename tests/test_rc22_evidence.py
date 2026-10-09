"""rc.22: real assertion failures must be accepted; crashes must not."""
import json
import tempfile
import unittest
from pathlib import Path

import runtimes

FIX = Path(__file__).parent / "fixtures"


def tap(code, failure_type, message, indent="", fail=1):
    block = (f"{indent}not ok 1 - t\n{indent}  ---\n{indent}  duration_ms: 1\n"
             f"{indent}  failureType: '{failure_type}'\n{indent}  error: |-\n"
             f"{indent}    {message}\n{indent}  code: '{code}'\n{indent}  ...\n")
    return ("TAP version 13\n" + block + f"1..1\n# tests 1\n# suites 0\n# pass 0\n# fail {fail}\n"
            "# cancelled 0\n# skipped 0\n# todo 0\n# duration_ms 5\n")


class AssertionEvidenceTests(unittest.TestCase):
    def test_rejects_with_instanceof_object_is_accepted(self):
        out = (FIX / "rc22_rejects_instanceof_err_test_failure.tap").read_text()
        self.assertIn("ERR_TEST_FAILURE", out)
        self.assertNotIn("ERR_ASSERTION", out)
        self.assertTrue(runtimes._node_assertion_failure(out))

    def test_describe_wrapped_failure_is_accepted(self):
        out = (FIX / "rc22_describe_wrapped_assertion.tap").read_text()
        self.assertTrue(runtimes._node_assertion_failure(out))

    def test_plain_assertion_still_accepted(self):
        self.assertTrue(runtimes._node_assertion_failure(
            tap("ERR_ASSERTION", "testCodeFailure", "Expected values to be strictly equal:")))

    def test_application_crash_labelled_err_test_failure_is_still_refused(self):
        for message in ("Cannot read properties of undefined (reading 'x')",
                        "connect ECONNREFUSED 127.0.0.1:80",
                        "Expected values to be strictly equal inside a log line? no"):
            if message.startswith("Expected"):
                continue
            self.assertFalse(runtimes._node_assertion_failure(
                tap("ERR_TEST_FAILURE", "testCodeFailure", message)), message)

    def test_wrong_failure_type_is_refused(self):
        self.assertFalse(runtimes._node_assertion_failure(
            tap("ERR_ASSERTION", "uncaughtException", "Expected values to be strictly equal:")))

    def test_leaf_count_must_match_fail_count(self):
        two_fails = tap("ERR_ASSERTION", "testCodeFailure", "Expected values to be strictly equal:", fail=2)
        self.assertFalse(runtimes._node_assertion_failure(two_fails))

    def test_suite_only_failure_is_refused(self):
        self.assertFalse(runtimes._node_assertion_failure(
            tap("ERR_TEST_FAILURE", "subtestsFailed", "1 subtest failed")))


class AliasGuidanceTests(unittest.TestCase):
    def guidance(self, tsconfig):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            if tsconfig is not None:
                (root / "tsconfig.json").write_text(tsconfig)
            return runtimes._alias_guidance(root)

    def test_root_alias_is_described_exactly(self):
        text = self.guidance('{"compilerOptions": {"paths": {"@/*": ["./*"]}}}')
        self.assertIn("'@/*' maps to './*'", text)
        self.assertIn("'@/src/server/x'", text)

    def test_no_alias_forbids_at_slash(self):
        text = self.guidance('{"compilerOptions": {}}')
        self.assertIn("no path aliases", text)
        self.assertIn("never write imports that start with '@/'", text)

    def test_comments_and_trailing_commas_are_tolerated(self):
        text = self.guidance('{\n // c\n "compilerOptions": {"paths": {"~/*": ["src/*",],},}, /* x */\n}')
        self.assertIn("'~/*' maps to 'src/*'", text)

    def test_glob_patterns_are_not_mistaken_for_comments(self):
        text = self.guidance('{"compilerOptions": {"paths": {"@/*": ["./*"]}}, "include": ["src/**/*", "**/*.ts"]}')
        self.assertIn("'@/*' maps to './*'", text)

    def test_unreadable_config_falls_back_to_relative_paths(self):
        self.assertIn("relative import paths", self.guidance("{not json"))
        self.assertIn("relative import paths", self.guidance(None))

    def test_guidance_no_longer_names_another_repositorys_module(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "package.json").write_text('{"scripts": {"test": "node --test"}}')
            (root / "tsconfig.json").write_text('{"compilerOptions": {}}')
            guidance = runtimes.detect_runtime(root).verifier_guidance
        self.assertNotIn("crypto/aes", guidance)
        self.assertIn("assert.rejects(promise)", guidance)
        self.assertNotIn("/expected message/", guidance)


if __name__ == "__main__":
    unittest.main()
