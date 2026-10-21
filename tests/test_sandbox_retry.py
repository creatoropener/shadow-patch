"""rc.39: a transient failure of the Sandbox API is retried, and is not reported as a readiness block.

The run this came from: GET /sandboxes/v1/files/<sha> answered HTTP 500 while the engine uploaded its helper
files. The first failure ended the run at `runtime-preflight` and the outcome said `readiness_blocked`.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import outcomes
import proof
import runtimes

# The message the live run recorded, unchanged.
LIVE_ERROR = ("ApiStatusCodeError(request=RequestInfo(url='https://api.tokenfactory.nebius.com/sandboxes/v1/files/"
              "a26c0dde8e22f148507354234ffe057586f468fb7a5b8c63ba8f1fee1d279522', method='GET'), "
              "response=ResponseInfo(headers={'content-type': 'application/json; charset=utf-8'}), "
              "status=500, error='Internal Server Error')")


def api_error(status=None, name="ApiStatusCodeError"):
    cls = type(name, (Exception,), {})
    error = cls(f"{name} status={status}")
    error.status = status
    return error


class TransientTests(unittest.TestCase):
    def test_server_errors_and_throttling_are_transient(self):
        for status in (500, 502, 503, 504, 408, 429):
            self.assertTrue(proof.sandbox_error_is_transient(api_error(status)), status)

    def test_client_errors_are_not(self):
        for status in (400, 401, 403, 404, 422):
            self.assertFalse(proof.sandbox_error_is_transient(api_error(status)), status)

    def test_timeouts_and_transport_failures_are_transient(self):
        self.assertTrue(proof.sandbox_error_is_transient(api_error(None, "ApiTimeoutError")))
        self.assertTrue(proof.sandbox_error_is_transient(api_error(None, "ContreeTransportError")))

    def test_ordinary_exceptions_are_not(self):
        self.assertFalse(proof.sandbox_error_is_transient(ValueError("boom")))
        self.assertFalse(proof.sandbox_error_is_transient(proof.PatchProofError("Sandbox workspace setup failed")))


@mock.patch.object(proof.time, "sleep")
class RetryTests(unittest.TestCase):
    def test_two_failures_then_success(self, sleep):
        calls = []

        def action():
            calls.append(1)
            if len(calls) < 3:
                raise api_error(500)
            return "state"

        self.assertEqual(proof.sandbox_retry(action, "x"), "state")
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5.0, 15.0])

    def test_a_persistent_failure_is_raised_after_three_tries(self, sleep):
        calls = []

        def action():
            calls.append(1)
            raise api_error(500)

        with self.assertRaises(Exception) as caught:
            proof.sandbox_retry(action, "x")
        self.assertEqual(getattr(caught.exception, "status", None), 500)
        self.assertEqual(len(calls), 3)

    def test_a_non_transient_error_is_not_retried(self, sleep):
        calls = []

        def action():
            calls.append(1)
            raise api_error(404)

        with self.assertRaises(Exception):
            proof.sandbox_retry(action, "x")
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_a_bug_in_the_step_is_not_retried(self, sleep):
        def action():
            raise KeyError("x")

        with self.assertRaises(KeyError):
            proof.sandbox_retry(action, "x")
        sleep.assert_not_called()


class Step:
    def __init__(self, owner, label, code=0):
        self.owner, self.label, self.exit_code, self.stdout, self.stderr = owner, label, code, "", ""

    def wait(self):
        return self

    def run(self, **kwargs):
        return self.owner.step(kwargs)


class FlakyImage:
    """Fails the first `failures` calls of the first step with HTTP 500, like the live upload lookup."""

    def __init__(self, failures):
        self.failures, self.calls = failures, []

    def step(self, kwargs):
        self.calls.append(kwargs.get("shell", "")[:40])
        if self.failures:
            self.failures -= 1
            raise api_error(500)
        return Step(self, "ok")

    def run(self, **kwargs):
        return self.step(kwargs)


@mock.patch.object(proof.time, "sleep")
class WorkspaceTests(unittest.TestCase):
    def adapter(self):
        root = Path(tempfile.mkdtemp())
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
        (root / "tsconfig.json").write_text("{}")
        return root, runtimes.detect_runtime(root)

    def test_the_upload_step_survives_one_server_error(self, sleep):
        root, adapter = self.adapter()
        image = FlakyImage(failures=1)
        archive = root / "a.tgz"
        archive.write_bytes(b"x")
        state = proof.sandbox_workspace(image, archive, adapter, root)
        self.assertEqual(state.exit_code, 0)
        self.assertEqual(len(image.calls), 1 + 1 + 1 + 1)  # failed upload, upload, install, preflight
        sleep.assert_called_once_with(5.0)

    def test_three_server_errors_still_stop_the_run_with_the_api_error(self, sleep):
        root, adapter = self.adapter()
        image = FlakyImage(failures=3)
        archive = root / "a.tgz"
        archive.write_bytes(b"x")
        with self.assertRaises(Exception) as caught:
            proof.sandbox_workspace(image, archive, adapter, root)
        self.assertEqual(getattr(caught.exception, "status", None), 500)


class ClassificationTests(unittest.TestCase):
    def record(self, error, stage="runtime-preflight"):
        return {"verdict": "rejected", "stage": stage, "error": error, "stop_reason": "blocked_setup",
                "candidates": [], "schema_version": "0.6", "app_version": proof.APP_VERSION, "run_id": "x"}

    def test_the_live_error_is_infrastructure_not_readiness(self):
        result = outcomes.classify_outcome(self.record(LIVE_ERROR))
        self.assertEqual(result["bucket"], "infrastructure_error")
        self.assertFalse(result["evaluated_repair"])

    def test_a_real_setup_problem_is_still_readiness(self):
        result = outcomes.classify_outcome(self.record("Runtime preflight failed for node-typescript:\ntsc: not found"))
        self.assertEqual(result["bucket"], "readiness_blocked")

    def test_a_client_error_from_the_api_is_not_called_infrastructure(self):
        result = outcomes.classify_outcome(self.record(LIVE_ERROR.replace("status=500", "status=403")))
        self.assertEqual(result["bucket"], "readiness_blocked")

    def test_a_5xx_in_a_later_stage_is_infrastructure_too(self):
        result = outcomes.classify_outcome(self.record(LIVE_ERROR, stage="candidate-evaluation"))
        self.assertEqual(result["bucket"], "infrastructure_error")

    def test_the_finalized_proof_records_it(self):
        record = {"candidates": [], "schema_version": "0.6", "app_version": proof.APP_VERSION, "run_id": "x",
                  "verdict": "rejected", "stage": "runtime-preflight", "error": LIVE_ERROR,
                  "error_type": "ApiStatusCodeError", "stop_reason": "blocked_setup"}
        proof.finalize_proof(record)
        self.assertEqual(record["outcome"]["bucket"], "infrastructure_error")


if __name__ == "__main__":
    unittest.main()
