"""Native regressions for the rc.24 audit findings. No network or inference."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import proof
import runtimes
from bench import harness as bench
from scope_policy import check_paths, load_scope, node_payload
from tools.pr_files import verified_paths

ROOT = Path(__file__).resolve().parents[1]
DEPS = Path(os.environ.get("TS_LINT_NODE_MODULES", "/missing"))


def put(root, name, content):
    dest = root / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


class AuditEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_large_context_file_does_not_hide_later_bug_or_change_permissions(self):
        put(self.root, "package.json", "{}")
        put(self.root, "a.js", "//" + "x" * 115000)
        put(self.root, "b.js", "//" + "x" * 95000)
        put(self.root, "c.js", "//" + "x" * 125000)
        put(self.root, "z-bug.js", "export const bug = 1;")
        adapter = runtimes.detect_runtime(self.root)
        context, editable = proof.collect_repository_context(self.root, adapter, include_tests=False)
        self.assertIn("z-bug.js", context)
        self.assertEqual(editable, {"a.js", "b.js", "c.js", "z-bug.js"})

    def test_constant_message_pin_is_rejected(self):
        content = "const expected = /Blocked/; await assert.rejects(p, expected);"
        self.assertEqual(runtimes.ungrounded_message_pins(content, "Refuse private addresses."), ["/Blocked/"])
        self.assertEqual(runtimes.ungrounded_message_pins(content, "Use Blocked as the message."), [])

    def test_python_runtime_error_text_is_not_assertion_evidence(self):
        adapter = runtimes.RuntimeAdapter("python-pytest", "Python", ("Python",), "pytest",
            frozenset({".py"}), frozenset({".py"}), frozenset(), ".py", "", "", "", "", "")
        for source, accepted in [
            ('def test_bug():\n    raise RuntimeError("AssertionError: 1 failed")\n', False),
            ('def test_bug():\n    assert 1 == 2\n', True),
            ('def test_bug():\n    assert True\n', False),
            ('import missing_dependency\n', False),
        ]:
            put(self.root, "test_bug.py", source)
            result = subprocess.run([sys.executable, str(ROOT / "patchproof_runtime/pytest_check.py"), "test_bug.py"],
                cwd=self.root, capture_output=True, text=True, timeout=30)
            output = result.stdout + result.stderr
            self.assertEqual(adapter.is_regression_failure(result.returncode, output), accepted, output)
        self.assertFalse(adapter.is_regression_failure(1, "RuntimeError: AssertionError\n1 failed"))

    def case(self):
        put(self.root, "bench/issues/c.md", "The value should be two.\n")
        case = {"id": "c", "split": "dev", "repo": "owner/repo", "base_commit": "a" * 40,
                "issue": {"number": 1, "title": "Wrong value", "body_file": "bench/issues/c.md"}, "oracle": None}
        put(self.root, "bench/manifest.json", json.dumps({"schema": 1, "protocol_id": "test-v2", "cases": [case]}))
        return case

    def test_stale_proof_is_quarantined_and_cannot_be_a_success(self):
        case = self.case()
        put(self.root, "engine/proof.py", "raise SystemExit(1)\n")
        put(self.root, "subject/proof.json", '{"verdict":"verified"}')
        meta = bench.run_trial(case=case, trial=1, engine_ref="v", engine_dir=self.root / "engine",
            subject=self.root / "subject", out=self.root / "out", root=self.root)
        self.assertFalse(meta["has_proof"])
        self.assertTrue((self.root / "out/previous/proof.json").is_file())
        trial = bench.collect_results(self.root / "out")[0]
        self.assertEqual(bench.classify_trial(meta, trial["proof"], lambda _: (True, "test"))[0], bench.INFRA)
        self.assertEqual(bench.classify_trial({"exit_code": 1}, {"verdict": "verified"}, lambda _: (True, "test"))[0], bench.INFRA)

    def test_proof_mutation_and_wrong_run_are_detected(self):
        self.case()
        record = {"verdict": "verified", "run_id": "other"}
        raw = json.dumps(record)
        put(self.root, "results/proof.json", raw)
        put(self.root, "results/meta.json", json.dumps({"evidence_version": 2, "run_id": "expected",
            "proof_sha256": hashlib.sha256(raw.encode()).hexdigest()}))
        trial = bench.collect_results(self.root / "results")[0]
        self.assertIn("run_id", trial["meta"]["evidence_error"])
        put(self.root, "results/proof.json", '{}')
        trial = bench.collect_results(self.root / "results")[0]
        self.assertIn("digest", trial["meta"]["evidence_error"])

    def test_historical_split_comes_from_trial_and_protocols_cannot_be_pooled(self):
        case = self.case()
        meta = {"case": "c", "split": "dev", "engine_ref": "v", "trial": 1, "manifest_sha256": "a"}
        rows = bench.build_rows([{"meta": meta, "proof": None}], {"cases": [{**case, "split": "heldout"}]}, {}, self.root / "labels")
        self.assertEqual(rows[0]["split"], "dev")
        for n, digest in enumerate(("a", "b")):
            put(self.root, f"results/{n}/meta.json", json.dumps({**meta, "manifest_sha256": digest}))
        with self.assertRaisesRegex(bench.BenchError, "different protocol"):
            bench.write_report(self.root / "results", self.root / "oracles", self.root / "report", manifest={"cases": [case]})

    def test_different_literal_whitespace_never_reuses_a_legacy_label(self):
        left = '--- a.js\n+++ a.js\n@@ -1 +1 @@\n-x\n+export const x = `a \n'
        right = left.replace('`a ', '`a')
        self.assertNotEqual(bench.diff_hash(left), bench.diff_hash(right))
        old = hashlib.sha256("\n".join(l.rstrip() for l in left.splitlines()).strip().encode()).hexdigest()[:16]
        judge = bench.make_judge("c", None, {old: {"correct": True}})
        self.assertEqual(judge(bench.diff_hash(left)), (None, "none"))

    def test_pr_delivery_accepts_only_replayed_bytes(self):
        put(self.root, "src/fix.js", "export const x = 2;\n")
        value = {"verdict": "verified", "clean_replay": {"passed": True}, "pr_files": [
            {"path": "src/fix.js", "sha256": hashlib.sha256((self.root / "src/fix.js").read_bytes()).hexdigest()}]}
        put(self.root, "proof.json", json.dumps(value))
        self.assertEqual(verified_paths(self.root), [":(literal)src/fix.js"])
        put(self.root, "src/fix.js", "export const x = 3;\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            verified_paths(self.root)

    def test_python_scope_protects_decorators_and_rejects_unknown_symbols(self):
        original = '@cache\ndef adjacent():\n    return 1\n\ndef value():\n    return 1\n'
        put(self.root, 'app.py', original)
        scope = {'protected_symbols': {'app.py': ['adjacent']}}
        with self.assertRaisesRegex(ValueError, 'scope_failed'):
            check_paths(self.root, [{'path': 'app.py', 'content': original.replace('@cache', '@other')}], scope)
        with self.assertRaisesRegex(ValueError, 'missing'):
            check_paths(self.root, [], {'protected_symbols': {'app.py': ['missing']}})


@unittest.skipUnless((DEPS / "typescript").is_dir() and shutil.which("node"), "requires TS_LINT_NODE_MODULES")
class NativeCandidatePolicyTests(unittest.TestCase):
    def run_policy(self, original, updated, symbols=()):
        with tempfile.TemporaryDirectory() as temp:
            request = Path(temp) / "request.json"
            request.write_text(json.dumps({"files": [{"path": "src/value.ts", "original": original,
                "content": updated, "protected_symbols": list(symbols)}]}))
            return subprocess.run(["node", str(ROOT / "patchproof_runtime/candidate_policy.mjs"), str(request)],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "PATCHPROOF_TYPESCRIPT_RUNTIME": str(DEPS.parent)})

    def test_scope_rejects_eta_changes_and_allows_bytes_fix(self):
        original = 'export function formatBytes() { return "bad"; }\nexport function formatEta() { return "60s"; }\n'
        good = original.replace('"bad"', '"1.0 KB"')
        self.assertEqual(self.run_policy(original, good, ["formatEta"]).returncode, 0)
        bad = self.run_policy(original, good.replace('"60s"', '"1m"'), ["formatEta"])
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("scope_failed", bad.stderr)
        protected_const = 'export const formatEta = () => "60s";'
        self.assertNotEqual(self.run_policy(protected_const, protected_const.replace('export ', ''), ['formatEta']).returncode, 0)

    def test_mutating_assertions_is_rejected_even_through_simple_aliases(self):
        original = 'export const value = () => 1;\n'
        for mutation in (
            "import assert from 'node:assert/strict'; assert.equal = () => {};",
            "import check from 'node:assert/strict'; const alias = check; alias['equal'] = () => {};",
            "const check = require('assert'); Object.assign(check, { equal: () => {} });",
            "import check from 'node:assert'; Object.defineProperty(check, 'equal', {value: () => {}});",
            "process.exit(0);",
        ):
            result = self.run_policy(original, mutation + original)
            self.assertNotEqual(result.returncode, 0, mutation)
            self.assertIn("interference", result.stderr)
        result = self.run_policy(original, '// assert.equal = () => {}\n' + original.replace('1', '2'))
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless((DEPS / ".bin/tsx").exists(), "requires TypeScript, @types/node and tsx")
class PortableDeliveryIntegrationTests(unittest.TestCase):
    def test_real_typescript_pipeline_delivers_tree_that_passes_ordinary_ci(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "subject"
            root.mkdir()
            put(root, "package.json", json.dumps({"type": "module", "scripts": {"test": "node --import tsx --test --test-reporter=tap tests/*.test.ts"}}))
            put(root, "config/base.json", '{ // JSONC plus inherited restrictive types\n "compilerOptions": {"target":"ES2022", "module":"NodeNext", "types":[], "strict":true, "allowImportingTsExtensions":true,},\n}\n')
            put(root, "tsconfig.json", '{"extends":"./config/base.json", "include":["src/**/*.ts", "app-types.d.ts"]}')
            put(root, "app-types.d.ts", 'interface ApplicationValue { amount: number }\n')
            original = 'export const value = (): ApplicationValue => ({ amount: 1 });\nexport function formatEta() { return "60s"; }\n'
            put(root, "src/value.ts", original)
            put(root, "tests/existing.test.ts", "import test from 'node:test'; import assert from 'node:assert/strict'; import {formatEta} from '../src/value.ts'; test('adjacent compatibility', () => assert.equal(formatEta(), '60s'));\n")
            put(root, "patchproof.json", json.dumps({"runtime": "node-typescript", "scope": {"allowed_paths": ["src/value.ts"], "protected_symbols": {"src/value.ts": ["formatEta"]}}}))
            (root / "node_modules").symlink_to(DEPS.resolve(), target_is_directory=True)
            content = """import test from 'node:test';
import assert from 'node:assert/strict';
import { value } from '../src/value.ts';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';
test('correct value and portable helper', async () => {
  const expected = new Uint8Array([1, 2, 3]);
  let actual: Uint8Array | undefined;
  await assert.doesNotReject(async () => { actual = await collectBytes(readableFromBytes(expected)); });
  assert.deepStrictEqual(actual, expected);
  assert.equal(value().amount, 2);
});
"""
            initial = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*')
                       if p.is_file() and "node_modules" not in p.parts}
            count = 0

            class LocalState:
                def __init__(self, files, code=0, output=""):
                    self.files, self.exit_code, self.stdout, self.stderr, self.uuid = files, code, output, "", "local-test"

                def apply_files(self, *, files):
                    updates = {k.removeprefix('/workspace/repo/'): v for k, v in files.items()}
                    return LocalState({**self.files, **updates})

                def run(self, *, shell, cwd, timeout, disposable):
                    nonlocal count
                    count += 1
                    directory = base / f"sandbox-{count}"
                    directory.mkdir()
                    for name, value in self.files.items():
                        target = directory / ("private/" + Path(name).name if name.startswith('/patchproof/') else name)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(value)
                    (directory / "node_modules").symlink_to(DEPS.resolve(), target_is_directory=True)
                    command = shell.replace('/patchproof/candidate-policy.json', str(directory / 'private/candidate-policy.json'))
                    command = command.replace('/opt/patchproof/node/node_modules/', str(DEPS.resolve()) + '/')
                    command = command.replace('/patchproof/', str(ROOT / 'patchproof_runtime') + '/')
                    result = subprocess.run(command, shell=True, cwd=directory, capture_output=True, text=True,
                        timeout=timeout, env={**os.environ, 'PATCHPROOF_TYPESCRIPT_RUNTIME': str(DEPS.parent)})
                    state = LocalState(self.files, result.returncode, result.stdout + result.stderr)
                    return SimpleNamespace(wait=lambda: state)

            solver_inputs = []
            def candidate(**kwargs):
                solver_inputs.append(kwargs)
                if kwargs['strategy'].startswith('maintainable'):
                    raise proof.InferenceError('simulated isolated generation failure')
                updated = original.replace('amount: 1', 'amount: 2')
                if kwargs['strategy'].startswith('defensive'):
                    updated = updated.replace('"60s"', '"1m"')
                return [{"path": "src/value.ts", "content": updated}], 'Correct value'

            sdk = SimpleNamespace(images=SimpleNamespace(use=lambda *a, **k: object()))
            reply = f'{proof.TEST_BEGIN}\n{content}\n{proof.TEST_END}\n{proof.RATIONALE_BEGIN}\nFix the value.\n{proof.RATIONALE_END}'
            env = {"NEBIUS_API_KEY": "offline", "NEBIUS_PROJECT_ID": "offline", "NEBIUS_MODEL": "offline", "CONTREE_IMAGE": "offline"}
            with patch.dict(os.environ, env), patch.object(proof, 'create_sandbox_client', return_value=sdk), \
                    patch.object(proof, 'sandbox_workspace', side_effect=lambda *a, **k: LocalState(initial)), \
                    patch.object(proof, 'model_text', return_value=reply), \
                    patch.object(proof, 'generate_candidate', side_effect=candidate):
                record = {'candidates': []}
                try:
                    result = proof.execute(root, proof.Issue(1, 'Wrong value', 'value().amount must be 2; keep ETA formatting unchanged.'), record)
                except proof.PatchProofError as error:
                    self.fail(str(error) + '\n' + json.dumps(record, indent=2))
            self.assertEqual(result['verdict'], 'verified')
            self.assertEqual(result['race']['passing'], 1)
            self.assertIn('scope_failed', result['candidates'][1]['error'])
            self.assertTrue(result['regression_test']['ordinary_ci']['discovered'])
            self.assertEqual(len(result['regression_test']['support_files']), 2)
            self.assertNotIn('/patchproof/', result['regression_test']['content'])
            for item in solver_inputs:
                self.assertNotIn('correct value and portable helper', item['context'])
            ordinary = subprocess.run(['npm', 'test'], cwd=root, capture_output=True, text=True, timeout=60)
            self.assertEqual(ordinary.returncode, 0, ordinary.stdout + ordinary.stderr)
            self.assertIn('# pass 2', ordinary.stdout)
            put(root, 'proof.json', json.dumps(result))
            self.assertEqual(len(verified_paths(root)), 4)
            for item in result['pr_files']:
                self.assertEqual(item['sha256'], hashlib.sha256((root / item['path']).read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
