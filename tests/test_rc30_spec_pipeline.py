"""rc.30: the specification profile inside the real pipeline (real tsc, tsx and node:test; scripted model)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import outcomes
import proof
import spec_profile as sp
from agent_budget import AgentStop
from tests import support_pipeline as pipeline

BS = "\\"

BUGGY = '''export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  return `${(n / 1024).toFixed(2)} KB`;
}
export const formatSpeed = (n: number): string => formatBytes(n) + "/s";
export function label(n: number): string {
  if (n < 0) throw new RangeError("negative");
  return n === 0 ? "none" : "some";
}
'''
FIXED = BUGGY.replace("toFixed(2)", "toFixed(1)")

ISSUE = proof.Issue(7, "formatBytes prints two decimals", "\n".join([
    'formatBytes 512 gives "512 B", which is right.',
    'formatBytes 1536 should give "1.5 KB" but gives "1.50 KB".',
    'formatSpeed 1536 should give "1.5 KB/s".',
    'formatSpeed 512 gives "512 B/s", which is right.',
    'label -1 should return "negative".',
]))

FREEFORM_TEST = (
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
    "import { formatBytes } from '../src/format.ts';\n"
    "test('kilobytes use one decimal', () => { assert.equal(formatBytes(1536), '1.5 KB'); });\n"
)


def spec_reply(raw):
    return f"{sp.SPEC_BEGIN}\n{json.dumps(raw)}\n{sp.SPEC_END}"


def example(ident, export, args, **kw):
    return {"id": ident, "export": export, "args": args, **kw}


E_ROUND = example("e1", "formatBytes", [512], returns="512 B", evidence='formatBytes 512 gives "512 B", which is right.')
E_KB = example("e2", "formatBytes", [1536], returns="1.5 KB",
               evidence='formatBytes 1536 should give "1.5 KB" but gives "1.50 KB".')
E_SPEED = example("e3", "formatSpeed", [1536], returns="1.5 KB/s", evidence='formatSpeed 1536 should give "1.5 KB/s".')
E_SPEED_OK = example("e5", "formatSpeed", [512], returns="512 B/s", evidence='formatSpeed 512 gives "512 B/s", which is right.')
E_LABEL = example("e4", "label", [-1], returns="negative", evidence='label -1 should return "negative".')


def good(*examples):
    return spec_reply({"supported": True, "module": "src/format.ts", "examples": list(examples)})


def freeform_reply(source=FREEFORM_TEST):
    return (f"{proof.TEST_BEGIN}\n{source}\n{proof.TEST_END}\n"
            f"{proof.RATIONALE_BEGIN}\nChecks formatBytes.\n{proof.RATIONALE_END}")


@unittest.skipUnless(pipeline.available(), "set TS_LINT_NODE_MODULES to a tsx/tsc install")
class SpecPipelineTests(unittest.TestCase):
    def project(self):
        base = Path(tempfile.mkdtemp())
        checkout = base / "checkout"
        checkout.mkdir()
        w = lambda name, text: pipeline.write(checkout, name, text)
        w("package.json", json.dumps({"type": "module", "scripts": {"test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
        w("tsconfig.json", '{"compilerOptions":{"target":"ES2022","module":"NodeNext","strict":true,"allowImportingTsExtensions":true,"types":[],"noEmit":true},"include":["src/**/*.ts"]}')
        w("src/format.ts", BUGGY)
        w("tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; import {formatBytes} from '../src/format.ts'; test('small', () => assert.equal(formatBytes(512), '512 B'));\n")
        w("patchproof.json", json.dumps({"runtime": "node-typescript"}))
        (checkout / "node_modules").symlink_to(pipeline.DEPS.resolve(), target_is_directory=True)
        return base, checkout

    def execute(self, replies, *, profile="spec", fixes=True):
        base, checkout = self.project()
        queue = list(replies)
        calls = []

        def model_text(**kwargs):
            calls.append(kwargs)
            return queue.pop(0) if len(queue) > 1 else queue[0]

        repaired = []

        def candidate(**kwargs):
            repaired.append(kwargs)
            if not fixes:
                raise AssertionError("no repair should be requested")
            return [{"path": "src/format.ts", "content": FIXED}], "one decimal"

        env = {} if profile is None else {"PATCHPROOF_VERIFIER": profile}
        result, record, error = pipeline.run_engine(base, checkout, checkout, ISSUE, "unused", candidate,
                                                    model_text=model_text, env_extra=env)
        return result, record, error, calls, repaired

    def finalize(self, record, error):
        if error is not None:
            record["error"] = str(error)
        proof.finalize_proof(record)
        return record["outcome"]

    # -- the supported path ------------------------------------------------------------------
    def test_a_grounded_specification_is_compiled_reproduced_and_repaired(self):
        result, record, error, calls, _ = self.execute([good(E_ROUND, E_KB, E_SPEED)])
        self.assertIsNone(error, json.dumps(record.get("regression_test", {}).get("spec"), default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(len(calls), 1)  # one model request; the engine wrote the test
        self.assertEqual(calls[0]["system"], sp.SYSTEM_PROMPT)
        regression = result["regression_test"]
        spec = regression["spec"]
        self.assertEqual((spec["status"], spec["profile"], spec["import_style"]), ("accepted", "spec-v1", "js"))
        self.assertEqual(spec["reproducing_examples"], ["e2", "e3"])
        self.assertEqual(spec["frozen_test_sha256"], regression["sha256"])
        self.assertEqual(spec["pre_fix_states"][0]["states"], {"e1": "pass", "e2": "mismatch", "e3": "mismatch"})
        self.assertIn("written by the engine, not the model", regression["rationale"])
        self.assertIn(spec["spec_sha256"], regression["content"])
        self.assertEqual(result["verifier"]["profile_used"], "spec")
        self.assertIsNone(result["verifier"]["fallback"])
        self.assertEqual(self.finalize(result, None)["bucket"], "verified")

    def test_an_example_that_errors_is_dropped_and_the_test_recompiled_without_the_model(self):
        # label(-1) throws on this revision; that is an error, not the intended assertion failure.
        result, record, error, calls, _ = self.execute([good(E_KB, E_LABEL)])
        self.assertIsNone(error, json.dumps(record["regression_test"]["spec"], default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(len(calls), 1)
        spec = result["regression_test"]["spec"]
        self.assertEqual([d["id"] for d in spec["dropped_examples"]], ["e4"])
        self.assertEqual(spec["reproducing_examples"], ["e2"])
        self.assertEqual([e["id"] for e in spec["examples"]], ["e2"])
        self.assertNotIn("label", result["regression_test"]["content"])
        attempts = result["regression_test"]["attempts"]
        self.assertEqual([a["counts_toward_limit"] for a in attempts], [False, True])
        self.assertEqual(result["regression_test"]["generation_attempts"][-1]["origin"], "engine recompile (no model call)")

    def test_the_default_profile_is_still_the_free_form_verifier(self):
        result, record, error, calls, _ = self.execute([freeform_reply()], profile=None)
        self.assertIsNone(error)
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(result["verifier"], {"profile_requested": "freeform", "profile_used": "freeform", "fallback": None})
        self.assertNotIn("spec", result["regression_test"])
        self.assertNotEqual(calls[0]["system"], sp.SYSTEM_PROMPT)

    # -- refused before any run ----------------------------------------------------------------
    def test_a_value_the_issue_does_not_contain_is_refused_before_any_sandbox_run(self):
        invented = dict(E_KB, returns="1.5 kB")  # lowercase k appears nowhere in the evidence
        result, record, error, calls, _ = self.execute([good(invented), good(E_ROUND, E_KB)])
        self.assertIsNone(error)
        self.assertEqual(len(calls), 2)
        self.assertIn('is not in the quoted evidence', calls[1]["user"])
        self.assertEqual(len(result["regression_test"]["attempts"]), 1)  # only the grounded spec ever ran
        statuses = [a["status"] for a in result["regression_test"]["spec"]["attempts"]]
        self.assertEqual(statuses, ["validation_failed", "validated"])

    def test_an_invented_example_is_dropped_and_the_grounded_ones_are_kept(self):
        # The live qrcrafts-1 failure: the model added a third example with values the issue never gives.
        invented = example("e6", "formatBytes", [999], returns="ninety-nine B", evidence="formatBytes 999 ordinary values keep working")
        result, record, error, calls, _ = self.execute([good(E_ROUND, E_KB, E_SPEED, invented)])
        self.assertIsNone(error, json.dumps(record.get("regression_test", {}).get("spec"), default=str)[:2000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(len(calls), 1)  # no retry spent on the example the issue does not support
        spec = result["regression_test"]["spec"]
        self.assertEqual([e["id"] for e in spec["examples"]], ["e1", "e2", "e3"])
        self.assertEqual([r["example"] for r in spec["rejected_examples"]], ["example e6"])
        self.assertIn("evidence", spec["rejected_examples"][0]["reason"])
        self.assertNotIn("ninety-nine", result["regression_test"]["content"])

    def test_an_unclosed_specification_is_repaired_without_another_model_call(self):
        # The live file-sharing-app-1 failure: the model ended `}], "` and then the END marker, and sent
        # the same text three times. The values are all grounded, so only the closing brackets are added.
        body = json.dumps({"supported": True, "module": "src/format.ts", "examples": [E_ROUND, E_KB, E_SPEED]})[:-1]
        reply = f"{sp.SPEC_BEGIN}\n{body}, \"{sp.SPEC_END}"
        result, record, error, calls, _ = self.execute([reply])
        self.assertIsNone(error, json.dumps(record.get("regression_test", {}).get("spec"), default=str)[:2000])
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(len(calls), 1)
        attempt = result["regression_test"]["spec"]["attempts"][0]
        self.assertEqual(attempt["status"], "validated")
        self.assertIn("dangling quote", attempt["json_repaired"])

    def test_a_repaired_block_is_still_grounded_example_by_example(self):
        invented = example("e6", "formatBytes", [999], returns="ninety-nine B", evidence="formatBytes 999 is fine")
        body = json.dumps({"supported": True, "module": "src/format.ts", "examples": [E_ROUND, E_KB, invented]})[:-1]
        result, record, error, calls, _ = self.execute([f"{sp.SPEC_BEGIN}\n{body}, \"{sp.SPEC_END}"])
        self.assertIsNone(error)
        spec = result["regression_test"]["spec"]
        self.assertEqual([r["example"] for r in spec["rejected_examples"]], ["example e6"])
        self.assertNotIn("ninety-nine", result["regression_test"]["content"])

    def test_a_json_backslash_mistake_comes_back_with_the_escaping_rule(self):
        bad = f'{sp.SPEC_BEGIN}\n{{"supported": true, "module": "src/format.ts", "examples": [{{"returns": "a{BS};b"}}]}}\n{sp.SPEC_END}'
        result, record, error, calls, _ = self.execute([bad, good(E_ROUND, E_KB)])
        self.assertIsNone(error)
        self.assertEqual(len(calls), 2)
        self.assertIn("two backslashes", calls[1]["user"])

    # -- no specification ---------------------------------------------------------------------
    def test_spec_mode_stops_with_needs_specification_and_never_asks_for_a_repair(self):
        unsupported = spec_reply({"supported": False, "reason": "The issue names no concrete input and output."})
        result, record, error, calls, repaired = self.execute([unsupported], fixes=False)
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(repaired, [])
        self.assertEqual(record["stop_reason"], "needs_specification")
        outcome = self.finalize(record, error)
        self.assertEqual((outcome["bucket"], outcome["evaluated_repair"]), ("needs_specification", False))
        self.assertEqual(record["regression_test"]["spec"]["status"], "unsupported")
        self.assertIn("names no concrete input", record["regression_test"]["spec"]["reason"])
        self.assertEqual(record["verifier"]["profile_used"], "spec")

    def test_a_specification_that_cannot_be_grounded_is_its_own_bucket(self):
        invented = good(dict(E_KB, returns="1.5 kB"))
        result, record, error, calls, repaired = self.execute([invented], fixes=False)
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 3)  # three identical refusals end the loop; no fourth request
        self.assertEqual(self.finalize(record, error)["bucket"], "spec_invalid")
        self.assertEqual(record["stop_reason"], "needs_specification")
        self.assertEqual(record["regression_test"]["spec"]["status"], "invalid")
        self.assertEqual(repaired, [])

    def test_headline_accounting_does_not_count_a_stop_for_specification_as_solved(self):
        unsupported = spec_reply({"supported": False, "reason": "No example."})
        _, record, error, _, _ = self.execute([unsupported], fixes=False)
        outcome = self.finalize(record, error)
        self.assertNotIn(outcome["bucket"], outcomes.EVALUATED_REPAIR)
        self.assertNotEqual(outcome["bucket"], outcomes.VERIFIED)

    # -- automatic fall back ---------------------------------------------------------------------
    def test_auto_falls_back_to_the_free_form_verifier_and_says_so(self):
        unsupported = spec_reply({"supported": False, "reason": "No example."})
        result, record, error, calls, _ = self.execute([unsupported, freeform_reply()], profile="auto")
        self.assertIsNone(error)
        self.assertEqual(result["verdict"], "verified")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["system"], sp.SYSTEM_PROMPT)
        self.assertNotEqual(calls[1]["system"], sp.SYSTEM_PROMPT)
        verifier = result["verifier"]
        self.assertEqual(verifier["profile_used"], "freeform")
        self.assertEqual(verifier["fallback"]["from"], "spec")
        self.assertIn("No example.", verifier["fallback"]["reason"])
        self.assertNotIn("frozen_test_sha256", result["regression_test"]["spec"])

    def test_auto_falls_back_after_two_specifications_that_do_not_reproduce(self):
        passing_a = good(E_ROUND)
        passing_b = good(E_SPEED_OK)
        result, record, error, calls, _ = self.execute([passing_a, passing_b, freeform_reply()], profile="auto")
        self.assertIsNone(error, json.dumps(record["regression_test"]["attempts"], default=str)[:2000])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["verifier"]["profile_used"], "freeform")
        self.assertIn("did not reproduce the issue after 2 rounds", result["verifier"]["fallback"]["reason"])
        self.assertNotIn("PREVIOUS SPECIFICATION", calls[2]["user"])  # the free-form prompt is clean

    def test_a_fallback_run_that_then_fails_is_not_blamed_on_the_specification(self):
        unsupported = spec_reply({"supported": False, "reason": "No example."})

        def passing(n):  # three different tests, all green on the unfixed code
            return freeform_reply(
                "import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
                "import { formatBytes } from '../src/format.ts';\n"
                f"test('t{n}', () => {{ assert.equal(formatBytes({n}), '{n} B'); }});\n")

        result, record, error, calls, _ = self.execute(
            [unsupported, passing(1), passing(2), passing(3)], profile="auto", fixes=False)
        self.assertIsNotNone(error)
        outcome = self.finalize(record, error)
        self.assertEqual(record["verifier"]["profile_used"], "freeform")
        self.assertEqual(record["regression_test"]["spec"]["status"], "unsupported")
        self.assertEqual(outcome["bucket"], "no_reproduction")  # not spec_invalid, not needs_specification


class PlanUnitTests(unittest.TestCase):
    """VerifierPlan decisions that the local toolchain cannot be made to produce on demand."""

    class Adapter:
        def __init__(self, ident="node-typescript"):
            self.id = ident

    def plan(self, *, requested="spec", adapter="node-typescript", modules=None):
        modules = {"src/format.ts": BUGGY} if modules is None else modules
        return proof.VerifierPlan(
            requested=requested, adapter=self.Adapter(adapter), issue=ISSUE, root=Path("."), test_path="tests/t.test.ts",
            modules=modules, literals=set(), api_key="x", model="m", generation_attempts=[], guard=proof.RepeatGuard())

    def with_spec(self, plan):
        validation = sp.validate_spec(json.loads(good(E_KB, E_SPEED).split("\n")[1]),
                                      issue_text=f"{ISSUE.title}\n{ISSUE.body}", modules=plan.modules, source_literals=set())
        self.assertTrue(validation.ok, validation.errors)
        plan.spec = validation.spec
        return plan

    def test_a_non_typescript_runtime_is_blocked_in_spec_mode_and_falls_back_in_auto(self):
        with self.assertRaises(AgentStop) as caught:
            self.plan(adapter="node-package")
        self.assertEqual(caught.exception.reason, "blocked_setup")
        auto = self.plan(requested="auto", adapter="node-package")
        self.assertEqual(auto.summary["profile_used"], "freeform")
        self.assertIn("node-typescript only", auto.summary["fallback"]["reason"])

    def test_no_exported_modules_falls_back_in_auto_and_blocks_in_spec(self):
        with self.assertRaises(AgentStop):
            self.plan(modules={})
        self.assertEqual(self.plan(requested="auto", modules={}).summary["fallback"]["from"], "spec")

    def test_free_form_plan_never_reviews(self):
        plan = self.plan(requested="freeform")
        self.assertIsNone(plan.review(reproduced=False, protected=True, classification="x", output="", test_content="t"))

    def test_module_resolution_failures_rotate_the_import_style_without_a_model_call(self):
        plan = self.with_spec(self.plan())
        static = "generated test could not load a module"
        seen = []
        for expected in ("ts", "bare"):
            review = plan.review(reproduced=False, protected=True, classification=static,
                                 output="Error [ERR_MODULE_NOT_FOUND]: Cannot find module '/x/src/format.js'", test_content="t")
            self.assertEqual((review.reproduced, review.feedback), (False, None))
            self.assertEqual(sp.IMPORT_STYLES[plan.style], expected)
            content, _ = plan.take_pending()
            seen.append(content)
        self.assertIn('"../src/format.ts"', seen[0])
        self.assertIn('"../src/format";', seen[1])
        last = plan.review(reproduced=False, protected=True, classification=static,
                           output="Cannot find module '/x/src/format'", test_content="t")
        self.assertIsNotNone(last.feedback)  # every style tried: now the model is told
        self.assertIsNone(plan.pending)
        self.assertEqual([c["to"] for c in plan.record["import_style_changes"]], ["ts", "bare"])

    def test_other_static_rejections_are_returned_to_the_model_with_the_specification(self):
        plan = self.with_spec(self.plan())
        review = plan.review(reproduced=False, protected=True, classification="generated TypeScript regression failed API type-check",
                             output="src/t.test.ts:3:1: error TS2345: bad", test_content="t")
        self.assertIsNotNone(review.feedback)
        self.assertIsNone(plan.pending)
        self.assertEqual(plan.style, 0)

    def test_unprotected_runs_are_never_read_as_evidence(self):
        plan = self.with_spec(self.plan())
        self.assertIsNone(plan.review(reproduced=True, protected=False, classification="accepted assertion failure reproduced the issue",
                                      output="", test_content="t"))

    def test_changing_failures_between_runs_are_not_accepted(self):
        plan = self.with_spec(self.plan())
        plan.expected = ["e2"]
        tap = ("TAP version 13\nnot ok 1 - e3\n  ---\n  code: 'ERR_ASSERTION'\n  error: |-\n    PATCHPROOF_EXAMPLE e3 VALUE\n  ...\n"
               "ok 2 - e2\n1..2\n")
        review = plan.review(reproduced=True, protected=True, classification="accepted assertion failure reproduced the issue",
                             output=tap, test_content="t")
        self.assertFalse(review.reproduced)
        self.assertIn("not deterministic", review.feedback)


class QrcraftsGroundingTests(unittest.TestCase):
    """The documented qrcrafts-1 clarification can be expressed in the profile, with exact payloads."""

    @classmethod
    def setUpClass(cls):
        cls.text = (Path(__file__).resolve().parents[1] / "docs" / "QRCRAFTS-ISSUE-1.md").read_text(encoding="utf-8")
        cls.modules = {"src/utils/qrBuilder.ts": "export function buildContent(input: { type: string; ssid: string; password: string; security: string }): string { return ''; }\n"}

    def example(self, ident, ssid, password, payload, evidence):
        return {"id": ident, "export": "buildContent",
                "args": [{"type": "wifi", "security": "WPA", "ssid": ssid, "password": password}],
                "returns": payload, "evidence": evidence}

    def test_both_documented_examples_ground_and_compile(self):
        one_payload = "WIFI:T:WPA;S:Cafe" + BS + ";Guest;P:pass" + BS + ":word;;"
        two_payload = "WIFI:T:WPA;S:Office" + BS + ",West" + BS + BS + "Lab;P:say" + BS + '"hello;;'
        self.assertIn(one_payload, self.text)
        self.assertIn(two_payload, self.text)
        evidence_one = self.text[self.text.index("- Security: WPA"):self.text.index(one_payload) + len(one_payload)]
        evidence_two = self.text[self.text.index("Example 2"):self.text.index(two_payload) + len(two_payload)]
        raw = {"supported": True, "module": "src/utils/qrBuilder.ts", "examples": [
            self.example("e1", "Cafe;Guest", "pass:word", one_payload, evidence_one),
            self.example("e2", "Office,West" + BS + "Lab", 'say"hello', two_payload, evidence_two)]}
        # The model's reply is JSON text, so go through the real parser the way a reply would.
        reply = f"{sp.SPEC_BEGIN}\n{json.dumps(raw)}\n{sp.SPEC_END}"
        parsed = sp.parse_spec_response(reply)
        result = sp.validate_spec(parsed, issue_text="Clarification\n" + self.text, modules=self.modules,
                                  source_literals={"wifi"})
        self.assertTrue(result.ok, result.errors)
        source = sp.compile_test(result.spec, test_path="tests/t.test.ts")
        self.assertEqual(source.count("PATCHPROOF_EXAMPLE"), 2)
        self.assertIn(json.dumps(two_payload), source)

    def test_the_benchmark_issue_text_grounds_the_same_examples(self):
        # What the benchmark harness actually sends is bench/issues/qrcrafts-1.md, not the proposal document.
        body = (Path(__file__).resolve().parents[1] / "bench" / "issues" / "qrcrafts-1.md").read_text(encoding="utf-8")
        one_payload = "WIFI:T:WPA;S:Cafe" + BS + ";Guest;P:pass" + BS + ":word;;"
        two_payload = "WIFI:T:WPA;S:Office" + BS + ",West" + BS + BS + "Lab;P:say" + BS + '"hello;;'
        self.assertIn(one_payload, body)
        self.assertIn(two_payload, body)
        evidence_one = body[body.index("Security: WPA"):body.index(one_payload) + len(one_payload)]
        evidence_two = body[body.rindex("Security: WPA"):body.index(two_payload) + len(two_payload)]
        raw = {"supported": True, "module": "src/utils/qrBuilder.ts", "examples": [
            self.example("e1", "Cafe;Guest", "pass:word", one_payload, evidence_one),
            self.example("e2", "Office,West" + BS + "Lab", 'say"hello', two_payload, evidence_two)]}
        result = sp.validate_spec(sp.parse_spec_response(f"{sp.SPEC_BEGIN}\n{json.dumps(raw)}\n{sp.SPEC_END}"),
                                  issue_text="Fix WiFi payload escaping\n" + body, modules=self.modules,
                                  source_literals={"wifi"})
        self.assertTrue(result.ok, result.errors)

    def test_a_payload_with_the_backslashes_halved_is_refused(self):
        one_payload = "WIFI:T:WPA;S:Cafe" + BS + ";Guest;P:pass" + BS + ":word;;"
        evidence = self.text[self.text.index("- Security: WPA"):self.text.index(one_payload) + len(one_payload)]
        wrong = one_payload.replace(BS, "")
        raw = {"supported": True, "module": "src/utils/qrBuilder.ts",
               "examples": [self.example("e1", "Cafe;Guest", "pass:word", wrong, evidence)]}
        result = sp.validate_spec(raw, issue_text=self.text, modules=self.modules, source_literals={"wifi"})
        self.assertFalse(result.ok)
        self.assertIn("is not in the quoted evidence", result.errors[0])


if __name__ == "__main__":
    unittest.main()
