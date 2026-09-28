"""Verify first-attempt/retry guidance at the actual model-request boundary."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import proof

class VerifierStringPromptTests(unittest.TestCase):
    def generate(self, runtime, feedback=''):
        adapter = SimpleNamespace(id=runtime, application_languages=('TypeScript',),
            test_runtime='node-test', verifier_guidance='ADAPTER_GUIDANCE',
            validate_generated_test=Mock())
        source = "import test from 'node:test';\ntest('case', () => {});\n"
        with patch.object(proof, 'model_json', return_value={
                'test_content': source, 'rationale': 'Exercise the reported behavior.'}) as model:
            result = proof.generate_regression_test(
                issue=SimpleNamespace(number=1, title='Example', body='Expected behavior'),
                context='CONTEXT', api_key='unused', model='unused', adapter=adapter,
                test_path='tests/regression.test.ts', retry_feedback=feedback)
        adapter.validate_generated_test.assert_called_once_with(source, 'tests/regression.test.ts')
        self.assertEqual(result[0], source)
        return model.call_args.kwargs

    def test_first_attempt_receives_string_guidance(self):
        request = self.generate('node-typescript')
        for phrase in ('String.raw', 'actual CR/LF', 'JSON transport escaping',
                       'keep assertions strict', 'real imported application function'):
            self.assertIn(phrase, request['system'])
        self.assertNotIn('PREVIOUS ATTEMPT', request['user'])
        self.assertIn('ADAPTER_GUIDANCE', request['user'])
        self.assertIn('CONTEXT', request['user'])

    def test_retry_retains_guidance_and_exact_feedback(self):
        request = self.generate('node-typescript', 'EXACT_PREVIOUS_SOURCE_AND_DIAGNOSTIC')
        self.assertIn('String.raw', request['system'])
        self.assertIn('EXACT_PREVIOUS_SOURCE_AND_DIAGNOSTIC', request['user'])

    def test_other_adapters_do_not_receive_typescript_guidance(self):
        for runtime in ('node-package', 'python-pytest', 'static-web'):
            with self.subTest(runtime=runtime):
                request = self.generate(runtime)
                self.assertNotIn('TypeScript string-value contract', request['system'])
                self.assertNotIn('String.raw', request['system'])

if __name__ == '__main__':
    unittest.main()
