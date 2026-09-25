import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import proof
from runtimes import _missing_async_success_guard, detect_runtime

LINTER = Path(__file__).resolve().parents[1] / 'patchproof_runtime/typescript_test_lint.mjs'
SOURCE = """
const FIXTURE = new Uint8Array([1,2,3,4,5,6,7]);
const CHUNK = 2;
test('full and partial round trip', async () => {
  let recovered;
  await assert.doesNotReject(async () => {
    const enc = await encrypt(key, {chunkSize: CHUNK});
    const dec = await decrypt(key);
    recovered = await collectBytes(readableFromBytes(FIXTURE, 3).pipeThrough(enc).pipeThrough(dec));
  });
  assert.deepStrictEqual(recovered, FIXTURE);
});
"""


class FastGuardTests(unittest.TestCase):
    def test_exact_proof8_test_is_rejected_before_execution(self):
        source = (Path(__file__).parent / 'fixtures/proof8_regression.test.ts').read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{"scripts":{"test":"node --test"}}')
            (root / 'tsconfig.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'doesNotReject'):
                detect_runtime(root).validate_generated_test(source, 'test.test.ts')

    def test_missing_guard_and_comment_or_rejects_do_not_bypass(self):
        source = "const result = await collectBytes(input.pipeThrough(dec)); assert.deepStrictEqual(result, expected);"
        for suffix in ('', '// await assert.doesNotReject(work)',
                       'assert.rejects(work);', 'const text = "await assert.doesNotReject(work)";'):
            self.assertTrue(_missing_async_success_guard(source + suffix))
        self.assertFalse(_missing_async_success_guard(SOURCE))
        self.assertFalse(_missing_async_success_guard('await assert.rejects(async () => collectBytes(input.pipeThrough(dec)));'))


@unittest.skipUnless(os.environ.get('TS_LINT_NODE_MODULES'), 'TypeScript installation required')
class StructuralContractTests(unittest.TestCase):
    def lint(self, source):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{}')
            (root / 'node_modules').symlink_to(Path(os.environ['TS_LINT_NODE_MODULES']).resolve(), target_is_directory=True)
            (root / 'test.ts').write_text(source)
            result = subprocess.run(['node', str(LINTER), 'test.ts'], cwd=root,
                                    capture_output=True, text=True, timeout=30)
            return result.returncode, result.stdout + result.stderr

    def test_real_ast_guard_and_coverage(self):
        cases = [
            (SOURCE, 0),
            (SOURCE.replace('[1,2,3,4,5,6,7]', '[1,2,3,4,5,6]'), 2),
            (SOURCE.replace('[1,2,3,4,5,6,7]', '[1]'), 2),
            (SOURCE.replace('await assert.doesNotReject', 'assert.doesNotReject'), 2),
            (SOURCE.replace('await assert.doesNotReject', 'await assert.rejects'), 2),
            (SOURCE.replace('    const enc = await encrypt(key, {chunkSize: CHUNK});', '')
             .replace('  let recovered;', '  let recovered; const enc = await encrypt(key, {chunkSize: CHUNK});'), 2),
            # Segmentation argument differs: coverage must use chunkSize, not 3.
            (SOURCE.replace('[1,2,3,4,5,6,7]', '[1,2,3]'), 0),
            (SOURCE.replace('new Uint8Array([1,2,3,4,5,6,7])', 'new TextEncoder().encode("a\\nb")'), 0),
            (SOURCE.replace('await assert.doesNotReject(async () => {', '{')
             .replace('  });', '  }') + "test('unrelated', async () => { await assert.doesNotReject(async () => {}); });", 2),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                code, output = self.lint(source)
                self.assertEqual(code, expected, output)
                if expected:
                    self.assertIn('PATCHPROOF_TYPESCRIPT_CONTRACT=failed', output)


class RetryLoopTests(unittest.TestCase):
    def run_loop(self, sources):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            (root / 'package.json').write_text('{"scripts":{"test":"node --test"}}')
            adapter = detect_runtime(root)
            baseline = MagicMock()
            baseline.exit_code = 0
            baseline.uuid = 'baseline'
            baseline.output = '# pass 1'
            baseline.run.return_value.wait.return_value = baseline
            stack.enter_context(patch.dict(os.environ, {
                'NEBIUS_API_KEY': 'test', 'NEBIUS_PROJECT_ID': 'test',
                'NEBIUS_MODEL': 'test', 'CONTREE_IMAGE': 'test'}))
            for name, result in [('collect_repository_context', ('context', {'app.js'})),
                                 ('create_sandbox_client', MagicMock()),
                                 ('sandbox_workspace', baseline),
                                 ('apply_contents', baseline)]:
                stack.enter_context(patch('proof.' + name, return_value=result))
            stack.enter_context(patch('proof.make_repository_archive'))
            stack.enter_context(patch('proof.text_output', side_effect=lambda state: state.output))
            generated = iter(sources)
            feedback = []
            def generate(**kwargs):
                source = next(generated)
                feedback.append(kwargs.get('retry_feedback', ''))
                kwargs['generation_attempts'].append({'attempt': len(feedback), 'status': 'validated'})
                return source, 'rationale'
            stack.enter_context(patch('proof.generate_regression_with_retry', side_effect=generate))
            def execute_test(*args):
                source = sources[len(feedback)-1]
                digest = proof.sha256_text(source)
                return SimpleNamespace(exit_code=1, uuid='execution', output=(
                    'TAP version 13\nnot ok 1 - operation\n  ---\n'
                    "  failureType: 'testCodeFailure'\n"
                    + ("  code: 'ERR_ASSERTION'\n" if source == 'valid' else "  code: 'ERR_TEST_FAILURE'\n")
                    + '  ...\n# fail 1\n# pass 0\n'
                    + f'PATCHPROOF_TEST_HASH_BEFORE={digest}\nPATCHPROOF_TEST_HASH_AFTER={digest}\n'))
            runner = stack.enter_context(patch('proof.run_protected_tests', side_effect=execute_test))
            candidate = stack.enter_context(patch('proof.generate_candidate_with_retry',
                                                  side_effect=proof.InferenceError('candidate reached')))
            report = {'candidates': []}
            with self.assertRaises(proof.PatchProofError) as error:
                proof.execute(root, proof.Issue(3, 'test', 'test'), report)
            return report, runner.call_count, candidate.call_count, feedback, str(error.exception)

    def test_duplicate_preserves_third_attempt_without_fake_execution(self):
        report, calls, candidates, feedback, error = self.run_loop(['bad', 'bad', 'valid'])
        # Candidate isolation (rc.7) means an InferenceError from one strategy no longer
        # aborts the race: all 3 strategies get an independent, isolated attempt instead
        # of the old first-InferenceError-wins short circuit. calls stays 2 (the duplicate
        # at reproduction_attempt=2 is still correctly skipped); candidates rises to 3.
        self.assertEqual((calls, candidates), (2, 3))
        self.assertEqual(
            error,
            "Only 0 of 3 candidates completed isolated Sandbox evaluation; 0 passed both "
            "the baseline and hidden regression. See individual candidate errors.",
        )
        regression = report['regression_test']
        self.assertEqual(len(regression['attempts']), 2)
        self.assertEqual(len(regression['generation_attempts']), 3)
        self.assertEqual(regression['generation_attempts'][1]['status'], 'duplicate')
        self.assertIn('doesNotReject', feedback[2])
        self.assertIn('identical', feedback[2])
        self.assertIn('not re-executed', proof.render_report(report))

    def test_repeated_duplicates_exhaust_budget_without_candidates(self):
        report, calls, candidates, _, error = self.run_loop(['bad', 'bad', 'bad'])
        self.assertEqual((calls, candidates), (1, 0))
        self.assertIn('budget exhausted', error)
        self.assertEqual(len(report['regression_test']['generation_attempts']), 3)


class UnifiedDiffTextTests(unittest.TestCase):
    def test_matches_real_file_content_against_a_proposed_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.ts').write_text('export const x = 1;\nexport const y = 2;\n')
            diff = proof.unified_diff_text(
                root, [{'path': 'app.ts', 'content': 'export const x = 1;\nexport const y = 3;\n'}])
            self.assertIn('--- app.ts', diff)
            self.assertIn('+++ app.ts', diff)
            self.assertIn('-export const y = 2;', diff)
            self.assertIn('+export const y = 3;', diff)
            self.assertIn('\n export const x = 1;\n', diff)  # unchanged line: space-prefixed context
            self.assertNotIn('-export const x = 1;', diff)
            self.assertNotIn('+export const x = 1;', diff)

    def test_multiple_files_each_get_their_own_diff_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.ts').write_text('const a = 1;\n')
            (root / 'b.ts').write_text('const b = 1;\n')
            diff = proof.unified_diff_text(root, [
                {'path': 'a.ts', 'content': 'const a = 2;\n'},
                {'path': 'b.ts', 'content': 'const b = 2;\n'},
            ])
            self.assertIn('--- a.ts', diff)
            self.assertIn('--- b.ts', diff)

    def test_no_changes_produces_an_empty_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.ts').write_text('const a = 1;\n')
            diff = proof.unified_diff_text(
                root, [{'path': 'app.ts', 'content': 'const a = 1;\n'}])
            self.assertEqual(diff, '')


class CandidateDiffRecordingTests(unittest.TestCase):
    """rc.12: a rejected candidate's proposed fix was discarded once the
    sandbox rejected it -- proof.json kept only its file paths and a line
    count, never the actual code. Built from a real Issue #3 run where all
    three candidates independently targeted the right file with the right
    general idea and still failed, with no way to see why."""

    def test_every_candidate_record_carries_a_real_diff_of_its_own_proposal(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            (root / 'package.json').write_text('{"scripts":{"test":"node --test"}}')
            (root / 'app.ts').write_text('export const x = 1;\n')
            baseline = MagicMock()
            baseline.exit_code = 0
            baseline.uuid = 'baseline'
            baseline.output = '# pass 1'
            baseline.run.return_value.wait.return_value = baseline
            stack.enter_context(patch.dict(os.environ, {
                'NEBIUS_API_KEY': 'test', 'NEBIUS_PROJECT_ID': 'test',
                'NEBIUS_MODEL': 'test', 'CONTREE_IMAGE': 'test'}))
            for name, result in [('collect_repository_context', ('context', {'app.ts'})),
                                 ('create_sandbox_client', MagicMock()),
                                 ('sandbox_workspace', baseline),
                                 ('apply_contents', baseline)]:
                stack.enter_context(patch('proof.' + name, return_value=result))
            stack.enter_context(patch('proof.make_repository_archive'))
            stack.enter_context(patch('proof.text_output', side_effect=lambda state: state.output))
            def generate_regression(**kwargs):
                kwargs['generation_attempts'].append({'attempt': 1, 'status': 'validated'})
                return 'valid', 'rationale'
            stack.enter_context(patch('proof.generate_regression_with_retry',
                                      side_effect=generate_regression))

            def execute_test(*args):
                digest = proof.sha256_text('valid')
                return SimpleNamespace(exit_code=1, uuid='execution', output=(
                    "TAP version 13\nnot ok 1 - operation\n  ---\n"
                    "  failureType: 'testCodeFailure'\n"
                    "  code: 'ERR_ASSERTION'\n"
                    '  ...\n# fail 1\n# pass 0\n'
                    f'PATCHPROOF_TEST_HASH_BEFORE={digest}\nPATCHPROOF_TEST_HASH_AFTER={digest}\n'))
            stack.enter_context(patch('proof.run_protected_tests', side_effect=execute_test))

            # Each of the 3 strategies proposes a *different* one-line change,
            # like three independently-generated real candidates would.
            proposals = iter([
                'export const x = 2;\n', 'export const x = 3;\n', 'export const x = 4;\n'])
            stack.enter_context(patch(
                'proof.generate_candidate_with_retry',
                side_effect=lambda **kwargs: (
                    [{'path': 'app.ts', 'content': next(proposals)}], 'a proposed fix')))

            report = {'candidates': []}
            with self.assertRaises(proof.PatchProofError) as error:
                proof.execute(root, proof.Issue(3, 't', 'b'), report)
            self.assertIn('All candidate repairs were rejected', str(error.exception))

            self.assertEqual(len(report['candidates']), 3)
            seen_values = set()
            for candidate in report['candidates']:
                self.assertFalse(candidate['passed'])
                self.assertIn('diff', candidate)
                self.assertIn('--- app.ts', candidate['diff'])
                self.assertIn('+++ app.ts', candidate['diff'])
                self.assertIn('-export const x = 1;', candidate['diff'])
                seen_values.add(candidate['diff'])
            # The three candidates' diffs are genuinely distinct, not a copy
            # of one strategy's proposal.
            self.assertEqual(len(seen_values), 3)
