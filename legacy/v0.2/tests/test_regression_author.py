import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from shadow_engineer.demo_external import seed
from shadow_engineer.regression_author import draft


class RegressionAuthorTests(unittest.TestCase):
    def test_only_base_files_reach_model(self):
        with tempfile.TemporaryDirectory() as d:
            lock, _ = seed(Path(d))
            calls = []
            def response(request, **kwargs):
                calls.append(json.loads(request.data))
                return io.BytesIO(json.dumps({"id": "mock-call", "choices": [{"message": {"content":
                    json.dumps({"regression": "def test_case(): assert False", "assumptions": []})}}]}).encode())
            with patch.dict(os.environ, {"NEBIUS_MODEL": "nvidia/test-model", "NEBIUS_API_KEY": "mock-key"}), \
                 patch("shadow_engineer.regression_author.urlopen", response):
                test, metadata = draft(d, lock["base_commit"], lock["issue"], ["shipping.py"], "pytest")
            sent = json.loads(calls[0]["messages"][1]["content"])
            self.assertIn("g // 1000", sent["base_files"]["shipping.py"])
            self.assertNotIn("(g - 1)", sent["base_files"]["shipping.py"])
            self.assertFalse(metadata["candidate_context"])
            self.assertNotIn("mock-key", json.dumps(metadata))

    def test_model_refusal_or_ambiguity_is_not_executable(self):
        with tempfile.TemporaryDirectory() as d:
            lock, _ = seed(Path(d))
            response = io.BytesIO(json.dumps({"choices": [{"message": {"content": '{"regression": null}'}}]}).encode())
            with patch.dict(os.environ, {"NEBIUS_MODEL": "nvidia/test-model", "NEBIUS_API_KEY": "mock-key"}), \
                 patch("shadow_engineer.regression_author.urlopen", return_value=response):
                with self.assertRaises(ValueError):
                    draft(d, lock["base_commit"], lock["issue"], ["shipping.py"], "pytest")
