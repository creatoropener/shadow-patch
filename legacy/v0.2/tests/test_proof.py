import unittest
from shadow_engineer.proof import Result, verify
from shadow_engineer.fixture import SOURCE, REGRESSION, CANDIDATES
from shadow_engineer.runners import validate_paths, parse_result


class ScriptedRunner:
    name = "test-double"
    def __init__(self, results): self.results = iter(results)
    def run(self, files, target): return next(self.results)


class ProofTests(unittest.TestCase):
    def test_success(self):
        r = verify(ScriptedRunner([Result(0, 2), Result(1, failed=1), Result(0, 1), Result(0, 3), Result(0, 3)]), SOURCE, REGRESSION, [CANDIDATES[2]])
        self.assertEqual(r['status'], 'verified')

    def test_replay_failure_rejects(self):
        r = verify(ScriptedRunner([Result(0, 2), Result(1, failed=1), Result(0, 1), Result(0, 3), Result(1, failed=1)]), SOURCE, REGRESSION, [CANDIDATES[2]])
        self.assertEqual(r['status'], 'rejected')

    def test_collection_error_is_not_reproduction(self):
        r = verify(ScriptedRunner([Result(0, 2), Result(2, errors=1)]), SOURCE, REGRESSION, CANDIDATES)
        self.assertEqual(r['candidates'], [])

    def test_already_passing_test_rejected(self):
        r = verify(ScriptedRunner([Result(0, 2), Result(0, 1)]), SOURCE, REGRESSION, CANDIDATES)
        self.assertEqual(r['status'], 'rejected')

    def test_test_edit_rejected(self):
        r = verify(ScriptedRunner([Result(0, 2), Result(1, failed=1)]), SOURCE, REGRESSION, [{'tests/test_existing.py': ''}])
        self.assertFalse(r['candidates'][0]['accepted'])

    def test_skipped_or_empty_is_not_green(self):
        self.assertFalse(Result(0).green)
        self.assertFalse(Result(0, passed=1, skipped=1).green)

    def test_paths(self):
        for path in ('../evil.py', '/app/a.py', 'app/../../evil.py', 'app\\evil.py'):
            with self.assertRaises(ValueError): validate_paths({path: ''})

    def test_missing_evidence_fails_closed(self):
        self.assertFalse(parse_result(0, '', 'ok', 'x').green)


if __name__ == '__main__': unittest.main()
