from __future__ import annotations

import json
import hashlib
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
from agent_budget import ACTIVE_BUDGET, AgentStop, BudgetExhausted, Limits, RunBudget, BudgetedState
from agent_loop import AgentSession
from context_tools import RepositorySnapshot, digest
from runtimes import detect_runtime
from bench import harness

ROOT = Path(__file__).resolve().parents[1]
DEPS = Path(os.environ.get("TS_LINT_NODE_MODULES", "/unavailable"))


def put(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class BudgetTests(unittest.TestCase):
    def test_benchmark_rejects_requested_actual_mode_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = json.dumps({'run_id': 'trial-one', 'agent_mode': 'legacy'}).encode()
            (root / 'proof.json').write_bytes(payload)
            put(root, 'meta.json', json.dumps({'evidence_version': 2, 'run_id': 'trial-one',
                'proof_sha256': hashlib.sha256(payload).hexdigest(), 'agent_mode': 'bounded'}))
            trial = harness.collect_results(root)[0]
            self.assertIn('requested execution profile', trial['meta']['evidence_error'])
            outcome, detail = harness.classify_trial(trial['meta'], trial['proof'], lambda _: (None, 'none'))
            self.assertEqual(outcome, 'infra')
            self.assertIn('requested execution profile', detail)

    def test_benchmark_refuses_mixed_modes_models_and_budgets_for_one_engine(self):
        baseline = {'engine_ref': 'v0.6.0-rc.26', 'agent_mode': 'bounded',
                    'model': 'offline', 'max_tokens': '12000',
                    'agent_settings': {'PATCHPROOF_MAX_AGENT_STEPS': '40'}}
        for change in ({'agent_mode': 'legacy'}, {'model': 'other'},
                       {'agent_settings': {'PATCHPROOF_MAX_AGENT_STEPS': '60'}}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                put(root, 'results/a/meta.json', json.dumps(baseline))
                put(root, 'results/b/meta.json', json.dumps({**baseline, **change}))
                with self.assertRaisesRegex(harness.BenchError, 'mixed execution profiles or budgets'):
                    harness.write_report(root / 'results', root / 'oracles', root / 'report', manifest={'cases': []})

    def test_budget_and_specification_stops_are_not_excluded_as_infrastructure(self):
        rows = []
        for reason in ('budget_exhausted', 'needs_specification'):
            outcome, _ = harness.classify_trial({}, {'verdict':'blocked','stop_reason':reason,'stage':'candidate-evaluation'}, lambda _: (None,'none'))
            self.assertEqual(outcome, reason)
            rows.append({'outcome':outcome})
        summary = harness.summarize(rows)
        self.assertEqual(summary['effective'], 2)
        self.assertEqual(summary['infra'], 0)

    def test_reservation_unknown_usage_and_reported_reconciliation(self):
        budget = RunBudget(Limits(tokens=2000, requests=2))
        request = {"messages": [{"content": "x" * 200}], "max_tokens": 1000}
        entry = budget.reserve_request(request)
        with self.assertRaises(BudgetExhausted):
            budget.reserve_request(request)
        budget.record_usage(entry, {"prompt_tokens": 50, "completion_tokens": 20})
        self.assertEqual(budget.tokens, 70)
        budget.reserve_request(request)
        with self.assertRaises(BudgetExhausted):
            budget.reserve_request(request)
        self.assertEqual(budget.requests, 2)

    def test_explicit_cost_and_wall_limits(self):
        budget = RunBudget(Limits(cost_usd=0.001, input_per_million=1, output_per_million=2))
        with self.assertRaises(BudgetExhausted):
            budget.reserve_request({"messages": [{"content": "x"}], "max_tokens": 1000})
        with patch.dict(os.environ, {"PATCHPROOF_MAX_COST_USD": "1", "PATCHPROOF_INPUT_USD_PER_MILLION": "", "PATCHPROOF_OUTPUT_USD_PER_MILLION": ""}):
            with self.assertRaisesRegex(AgentStop, "prices"):
                Limits.from_env()
        now = [0.0]
        budget = RunBudget(Limits(seconds=30), clock=lambda: now[0])
        now[0] = 29
        self.assertEqual(budget.command_timeout(600), 1)
        now[0] = 31
        with self.assertRaises(BudgetExhausted):
            budget.step()

    def test_http_transport_retries_share_budget(self):
        from openai import APIConnectionError
        import httpx
        calls = []
        def fail(**kwargs):
            calls.append(kwargs)
            raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
        manager = unittest.mock.MagicMock()
        manager.__enter__.return_value = client
        budget = RunBudget(Limits(requests=1))
        token = ACTIVE_BUDGET.set(budget)
        try:
            with patch("openai.OpenAI", return_value=manager), patch.object(proof.time, "sleep"):
                with self.assertRaises(BudgetExhausted):
                    proof.model_json(api_key="offline", model="offline", system="s", user="u", temperature=0)
        finally:
            ACTIVE_BUDGET.reset(token)
        self.assertEqual(len(calls), 1)
        self.assertEqual(budget.requests, 1)
        self.assertGreater(budget.tokens, 0)

    def test_wrapped_branches_share_command_budget(self):
        state = SimpleNamespace(uuid="one")
        state.apply_files = lambda **kwargs: state
        state.run = lambda **kwargs: SimpleNamespace(wait=lambda: state)
        budget = RunBudget(Limits(commands=1))
        wrapped = BudgetedState(state, budget)
        child = wrapped.apply_files(files={}).run(shell="true", timeout=60).wait()
        with self.assertRaises(BudgetExhausted):
            child.run(shell="true", timeout=60)


class ContextAndIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        put(self.root, "package.json", '{"scripts":{"test":"node --test"}}')
        put(self.root, "tsconfig.json", '{}')
        put(self.root, "src/app.ts", 'export const value = 1;\n')
        put(self.root, "tests/current.test.ts", 'export const baseline = 1;\n')
        put(self.root, "proof.json", 'HIDDEN_OLD_PROOF')
        put(self.root, ".env", 'PRIVATE_CREDENTIAL')
        put(self.root, "bench/oracle.ts", 'HIDDEN_ORACLE')
        (self.root / "escape").symlink_to(self.root.parent, target_is_directory=True)
        self.adapter = detect_runtime(self.root)
        self.snapshot = RepositorySnapshot(self.root, self.adapter, proof.EXCLUDED_DIRS, proof.PROTECTED_NAMES, proof.is_protected_path)

    def session(self, role, responses, record=None):
        actions = iter(responses)
        return AgentSession(role=role, snapshot=self.snapshot, allowed_paths=self.snapshot.editable,
            adapter=self.adapter, issue_text="value must be two", scope={},
            model_call=lambda *args: next(actions), run_check=lambda *args: {"passed": True},
            validate_changes=lambda changes: None, budget=RunBudget(Limits()),
            record={} if record is None else record, max_steps=6)

    def test_hidden_paths_symlinks_tests_and_unknown_paths_cannot_be_edited(self):
        self.assertNotIn('proof.json', self.snapshot.files)
        self.assertNotIn('bench/oracle.ts', self.snapshot.files)
        self.assertFalse(any(path.startswith('escape/') for path in self.snapshot.files))
        tools = self.snapshot.tools()
        for path in ('../src/app.ts', '/etc/passwd', 'proof.json', '.env'):
            with self.assertRaises(ValueError):
                tools.invoke({'action':'read','path':path})
        with self.assertRaisesRegex(ValueError, 'Read'):
            tools.prepare_edits([{'path':'src/app.ts','old':'1','new':'2'}], self.adapter)
        tools.invoke({'action':'read','path':'tests/current.test.ts'})
        with self.assertRaisesRegex(ValueError, 'protected'):
            tools.prepare_edits([{'path':'tests/current.test.ts','old':'1','new':'2'}], self.adapter)

    def test_independent_overlays_and_stale_reads(self):
        left, right = self.snapshot.tools(), self.snapshot.tools()
        left.invoke({'action':'read','path':'src/app.ts'})
        left.accept(left.prepare_edits([{'path':'src/app.ts','old':'1','new':'2'}], self.adapter))
        self.assertIn('1', right.content('src/app.ts'))
        self.assertIn('1', (self.root/'src/app.ts').read_text())
        with self.assertRaisesRegex(ValueError, 'Read'):
            left.prepare_edits([{'path':'src/app.ts','old':'2','new':'3'}], self.adapter)

    def test_read_only_verifier_and_specific_stop_reason(self):
        record = {}
        agent = self.session('verifier', [
            {'action':'edit','edits':[{'path':'src/app.ts','old':'1','new':'2'}]},
            {'action':'stop','reason':'needs_specification','message':'Units are not defined.'}], record)
        with self.assertRaises(AgentStop) as error:
            agent.run()
        self.assertEqual(error.exception.reason, 'needs_specification')
        self.assertIn('read-only', record['events'][0]['observation']['error'])

    def test_loop_exhaustion_and_raw_shell_rejection(self):
        agent = self.session('solver', [{'action':'shell','command':'cat proof.json'}] * 6)
        with self.assertRaises(BudgetExhausted):
            agent.run()
        self.assertEqual(agent.record['status'], 'budget_exhausted')
        self.assertTrue(all('Unknown action' in e['observation']['error'] for e in agent.events))

    def test_malformed_action_fields_return_diagnostics_and_allow_correction(self):
        agent = self.session('verifier', [
            {'action': ['read']}, {'action': 'check', 'check': {'name': 'typecheck'}},
            {'action': 'stop', 'reason': [], 'message': 'Invalid reason'},
            {'action': 'finish', 'summary': 'Corrected protocol.'}])
        agent.run()
        self.assertEqual(agent.record['status'], 'completed')
        self.assertEqual(sum('error' in e['observation'] for e in agent.events), 3)

    def test_literal_search_pagination_and_crlf_provenance(self):
        tools = self.snapshot.tools()
        self.assertEqual(tools.invoke({'action':'symbols','query':'value'})['matches'][0]['path'], 'src/app.ts')
        (self.root/'src/windows.ts').write_bytes(b'export const windows = 1;\r\n')
        snap = RepositorySnapshot(self.root, self.adapter, proof.EXCLUDED_DIRS, proof.PROTECTED_NAMES, proof.is_protected_path)
        self.assertEqual(snap.hashes['src/windows.ts'], digest('export const windows = 1;\r\n'))
        self.assertEqual(snap.tools().invoke({'action':'read','path':'src/windows.ts'})['line_ending'], 'CRLF')


@unittest.skipUnless((DEPS / '.bin/tsx').exists(), 'requires TypeScript, tsx and @types/node')
class NativeBoundedPipelineTests(unittest.TestCase):
    def run_pipeline(self, *, hidden_failure=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name); root = base/'subject'; root.mkdir()
        put(root, 'package.json', json.dumps({'type':'module','scripts':{'test':'node --import tsx --test --test-reporter=tap tests/*.test.ts'}}))
        put(root, 'tsconfig.json', json.dumps({'compilerOptions':{'target':'ES2022','module':'NodeNext','strict':True,'allowImportingTsExtensions':True,'noEmit':True},'include':['lib/**/*.ts','z/**/*.ts']}))
        api = 'export interface Reading { amount: { value: number }; suffix: string }\nexport const measure = (n: number): Reading => ({amount: {value: n / 1024}, suffix: "KiB"});\n'
        source = '''import { measure } from '../lib/api.ts';
export function describeBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const readout = measure(bytes);
  return `${bytes} B`;
}
export function adjacent() { return "stable"; }
'''
        put(root, 'lib/api.ts', api);put(root, 'z/presentation.ts', source)
        for i in range(100): put(root, f'filler/f{i:03}.ts', f'export const filler{i} = {i};\n')
        put(root, 'tests/baseline.test.ts', "import test from 'node:test'; import assert from 'node:assert/strict'; import {describeBytes, adjacent} from '../z/presentation.ts'; test('compatibility', () => {assert.equal(describeBytes(512), '512 B'); assert.equal(adjacent(), 'stable');});\n")
        put(root, 'patchproof.json', json.dumps({'runtime':'node-typescript'}))
        (root/'node_modules').symlink_to(DEPS.resolve(), target_is_directory=True)
        frozen = """import test from 'node:test';
import assert from 'node:assert/strict';
import { describeBytes } from '../z/presentation.ts';
test('HIDDEN_REGRESSION_SENTINEL', async () => { assert.equal(describeBytes(1536), '1.5 KiB'); });
"""
        initial = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*')
                   if p.is_file() and 'node_modules' not in p.parts}
        count = 0
        class LocalState:
            def __init__(self, files, code=0, output=''):
                self.files, self.exit_code, self.stdout, self.stderr, self.uuid = files, code, output, '', 'offline-native'
            def apply_files(self, *, files):
                return LocalState({**self.files, **{k.removeprefix('/workspace/repo/'):v for k,v in files.items()}})
            def run(self, *, shell, cwd, timeout, disposable):
                nonlocal count
                count += 1; directory = base/f'sandbox-{count}';directory.mkdir()
                for name,value in self.files.items():
                    target = directory/('private/'+Path(name).name if name.startswith('/patchproof/') else name)
                    target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(value)
                (directory/'node_modules').symlink_to(DEPS.resolve(), target_is_directory=True)
                command = shell.replace('/patchproof/candidate-policy.json',str(directory/'private/candidate-policy.json'))
                command = command.replace('/opt/patchproof/node/node_modules/',str(DEPS.resolve())+'/')
                command = command.replace('/patchproof/',str(ROOT/'patchproof_runtime')+'/')
                result = subprocess.run(command,shell=True,cwd=directory,text=True,capture_output=True,timeout=timeout,
                    env={**os.environ,'PATCHPROOF_TYPESCRIPT_RUNTIME':str(DEPS.parent)})
                return SimpleNamespace(wait=lambda:LocalState(self.files,result.returncode,result.stdout+result.stderr))
        verifier = iter([
            {'action':'search','query':'describeBytes'}, {'action':'read','path':'z/presentation.ts'},
            {'action':'symbols','query':'measure'}, {'action':'read','path':'lib/api.ts'},
            {'action':'finish','summary':'VERIFIER_PRIVATE_SENTINEL: Reading contains amount.value and suffix.'}])
        old = 'const readout = measure(bytes);\n  return `${bytes} B`;'
        bad = 'const readout = measure(bytes);\n  return `${readout.value} ${readout.suffix}`;'
        solver_actions = [
            {'action':'search','query':'describeBytes'}, {'action':'read','path':'z/presentation.ts'},
            {'action':'edit','edits':[{'path':'z/presentation.ts','old':old,'new':bad}]},
            {'action':'check','check':'typecheck'}, {'action':'symbols','query':'measure'},
            {'action':'read','path':'lib/api.ts'}, {'action':'read','path':'z/presentation.ts'},
            {'action':'edit','edits':[{'path':'z/presentation.ts','old':'readout.value','new':'readout.amount.value + 1' if hidden_failure else 'readout.amount.value'}]},
            {'action':'finish','summary':'Format the measured amount and unit.'}]
        solver = iter(solver_actions); solver_prompts = []
        def model_json(**kwargs):
            if 'independent verifier' in kwargs['system']:
                return next(verifier)
            solver_prompts.append(kwargs['user'])
            return next(solver)
        reply = f'{proof.TEST_BEGIN}\n{frozen}\n{proof.TEST_END}\n{proof.RATIONALE_BEGIN}\nCheck the reported output.\n{proof.RATIONALE_END}'
        sdk = SimpleNamespace(images=SimpleNamespace(use=lambda *a,**k:object()))
        env={'NEBIUS_API_KEY':'offline-key','NEBIUS_PROJECT_ID':'offline-project','NEBIUS_MODEL':'offline-model','CONTREE_IMAGE':'offline-image',
             'PATCHPROOF_AGENT_MODE':'bounded','PATCHPROOF_AGENT_CANDIDATES':'1'}
        record={'candidates':[],'app_version':proof.APP_VERSION,'schema_version':proof.SCHEMA_VERSION,'run_id':'offline'}
        with patch.dict(os.environ,env), patch.object(proof,'create_sandbox_client',return_value=sdk), \
                patch.object(proof,'sandbox_workspace',side_effect=lambda *a,**k:LocalState(initial)), \
                patch.object(proof,'model_text',return_value=reply),patch.object(proof,'model_json',side_effect=model_json):
            if hidden_failure:
                with self.assertRaisesRegex(proof.PatchProofError,'All candidate'):
                    proof.execute(root,proof.Issue(1,'Readable units','For 1536 bytes, describeBytes must return 1.5 KiB. Keep byte-sized formatting and adjacent behavior.'),record)
            else:
                proof.execute(root,proof.Issue(1,'Readable units','For 1536 bytes, describeBytes must return 1.5 KiB. Keep byte-sized formatting and adjacent behavior.'),record)
        for text in solver_prompts:
            self.assertNotIn('HIDDEN_REGRESSION_SENTINEL', text)
            self.assertNotIn('VERIFIER_PRIVATE_SENTINEL', text)
        self.assertEqual(len(solver_prompts), len(solver_actions))
        self.assertNotIn('z/presentation.ts', solver_prompts[0])
        self.assertIsNone(ACTIVE_BUDGET.get())
        self.assertTrue(any("Property 'value' does not exist" in text for text in solver_prompts))
        self.assertTrue((root/'proof.json').exists())
        checkpoint=json.loads((root/'proof.json').read_text())
        self.assertIn('budget',checkpoint)
        self.assertEqual(checkpoint['engine_provenance']['agent_loop.py'],
                         hashlib.sha256((ROOT/'agent_loop.py').read_bytes()).hexdigest())
        for session in [checkpoint['agent_sessions']['verifier'], *checkpoint['agent_sessions']['solvers']]:
            self.assertEqual(len(session['system_sha256']), 64)
            self.assertIn('INITIAL REPOSITORY MAP', session['initial_context'])
        self.assertGreater(record['budget']['sandbox_commands'], 0)
        return root,record

    def test_discovers_beyond_map_and_corrects_real_type_error_without_leakage(self):
        root,record=self.run_pipeline()
        self.assertEqual(record['verdict'],'verified')
        self.assertTrue(record['clean_replay']['passed'])
        self.assertTrue(record['regression_test']['ordinary_ci']['discovered'])
        self.assertEqual(record['race']['planned'],1)
        result=subprocess.run(['npm','test'],cwd=root,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_hidden_failure_has_no_solver_retry_and_no_local_delivery(self):
        root,record=self.run_pipeline(hidden_failure=True)
        self.assertFalse(record['candidates'][0]['passed'])
        self.assertNotIn('pr_files',record)
        self.assertNotIn('readout.amount.value', (root/'z/presentation.ts').read_text())


if __name__ == '__main__':
    unittest.main()
