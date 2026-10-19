"""rc.35: the static-web adapter can complete a run.

Before rc.35 every static-web run died the same way. The adapter's prompt told the model to load jsdom from
a path inside the sandbox image, and `support_files` then refused any test containing that path (a plain
PatchProofError, so no retry), while the adapter's baseline was a syntax check that never runs a test file,
so the ordinary-CI discovery gate had nothing that could run and fail the frozen test.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import proof
import runtimes
from runtimes import detect_runtime, static_web_project_problems
from tools import export_target

import support_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]
SANDBOX_JSDOM = Path("/opt/patchproof/node/node_modules/jsdom")

# The test the live model wrote for Tabloop #2 on rc.34 (be3341ef-proof.json), unchanged: it follows the
# loader line the rc.34 prompt required, and rc.34 refused it before it ran.
RC34_MODEL_TEST = """import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';

const {JSDOM} = createRequire('/opt/patchproof/node/package.json')('jsdom');

test('contact form action resolves correctly under subpath', async () => {
  const baseUrl = 'https://patchproof.invalid/Tabloop/';
  const html = readFileSync(join(process.cwd(), 'index.html'), 'utf8');
  const dom = new JSDOM(html, {url: baseUrl, runScripts: 'outside-only'});
  await new Promise(resolve => setTimeout(resolve, 0));
  const form = dom.window.document.querySelector('form[name="tabloop-contact"]');
  assert.strictEqual(form.action, `${baseUrl}thank-you.html`);
});
"""
PORTABLE_MODEL_TEST = RC34_MODEL_TEST.replace(
    "const {JSDOM} = createRequire('/opt/patchproof/node/package.json')('jsdom');",
    "import { JSDOM } from './patchproof_helpers/jsdom.mjs';")
INDEX_BEFORE = ('<!doctype html><html><body>\n<form action="/thank-you.html" method="POST" name="tabloop-contact">'
                '</form>\n</body></html>\n')
INDEX_AFTER = INDEX_BEFORE.replace('action="/thank-you.html"', 'action="thank-you.html"')
ISSUE = proof.Issue(2, "Root-Absolute Form Action Breaks Subpath / Staging Deploys",
                    "The contact form posts to /thank-you.html, which ignores the deploy path.")


def site(manifest: dict | None, *, config: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="site-"))
    (root / "index.html").write_text(INDEX_BEFORE)
    (root / "patchproof.json").write_text(json.dumps(config or {"runtime": "static-web"}))
    if manifest is not None:
        (root / "package.json").write_text(json.dumps(manifest))
        (root / "package-lock.json").write_text("{}")
    return root


GOOD = {"name": "site", "scripts": {"test": "node --test"}, "devDependencies": {"jsdom": "^24.1.3"}}


class AdapterTests(unittest.TestCase):
    def test_baseline_runs_the_project_tests_after_the_syntax_check(self):
        adapter = detect_runtime(site(GOOD))
        self.assertEqual(adapter.id, "static-web")
        self.assertEqual(adapter.baseline_command, "node /patchproof/static_web_check.mjs index.html && CI=1 npm test")
        self.assertEqual(adapter.bootstrap_command, "npm ci --ignore-scripts --no-audit --no-fund")

    def test_a_site_without_a_test_script_keeps_the_syntax_check_alone(self):
        for manifest in (None, {"name": "site"}):
            with self.subTest(manifest=manifest):
                adapter = detect_runtime(site(manifest))
                self.assertEqual(adapter.baseline_command, "node /patchproof/static_web_check.mjs index.html")
                self.assertEqual(adapter.bootstrap_command, "true")

    def test_other_adapters_are_untouched(self):
        root = Path(tempfile.mkdtemp())
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
        (root / "tsconfig.json").write_text("{}")
        self.assertEqual(detect_runtime(root).id, "node-typescript")
        self.assertEqual(detect_runtime(root).baseline_command, "CI=1 npm test")

    def test_prompt_no_longer_asks_for_a_sandbox_path(self):
        guidance = detect_runtime(site(GOOD)).verifier_guidance
        self.assertNotIn("/opt/patchproof", guidance)
        self.assertIn("import { JSDOM } from './patchproof_helpers/jsdom.mjs';", guidance)

    def test_the_helper_ships_with_the_engine(self):
        self.assertIn("patchproof_runtime/jsdom.mjs", export_target.FILES)
        self.assertTrue((ROOT / "patchproof_runtime/jsdom.mjs").is_file())


class ProjectProblemTests(unittest.TestCase):
    def test_a_ready_project_has_none(self):
        self.assertEqual(static_web_project_problems(site(GOOD)), [])

    def test_no_manifest_names_both_things_to_add(self):
        problems = static_web_project_problems(site(None))
        self.assertEqual(len(problems), 1)
        self.assertIn("node --test", problems[0])
        self.assertIn("jsdom", problems[0])

    def test_missing_script_and_missing_jsdom_are_reported_separately(self):
        problems = static_web_project_problems(site({"name": "site"}))
        self.assertEqual(len(problems), 2)
        self.assertIn("no `test` script", problems[0])
        self.assertIn("jsdom is not declared", problems[1])

    def test_jsdom_may_be_a_dependency_or_a_dev_dependency(self):
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            with self.subTest(section=section):
                manifest = {"scripts": {"test": "node --test"}, section: {"jsdom": "24"}}
                self.assertEqual(static_web_project_problems(site(manifest)), [])

    def test_an_unreadable_manifest_is_reported_not_raised(self):
        root = site(GOOD)
        (root / "package.json").write_text("{not json")
        self.assertIn("cannot be read", static_web_project_problems(root)[0])


class GeneratedTestTests(unittest.TestCase):
    def setUp(self):
        self.adapter = detect_runtime(site(GOOD))

    def test_the_rc34_loader_line_becomes_the_helper_import(self):
        fixed = runtimes.canonicalize_static_web_test(RC34_MODEL_TEST)
        self.assertEqual(fixed, runtimes.canonicalize_static_web_test(PORTABLE_MODEL_TEST))
        self.assertIn("import { JSDOM } from './patchproof_helpers/jsdom.mjs';", fixed)
        self.assertFalse(runtimes.mentions_sandbox_path(fixed))
        self.adapter.validate_generated_test(fixed, "test_patchproof_issue_2.test.mjs")

    def test_spacing_and_the_missing_semicolon_do_not_defeat_it(self):
        for line in ("const { JSDOM } = createRequire( '/opt/patchproof/node/package.json' )( \"jsdom\" )",
                     "const {JSDOM}=createRequire('/opt/patchproof/node/package.json')('jsdom');"):
            with self.subTest(line=line):
                self.assertNotIn("/opt/patchproof", runtimes.canonicalize_static_web_test(line + "\n"))

    def test_other_sandbox_paths_are_left_for_the_validator(self):
        content = RC34_MODEL_TEST + "const other = createRequire('/opt/patchproof/node/package.json')('other-module');\n"
        fixed = runtimes.canonicalize_static_web_test(content)
        self.assertIn("import { JSDOM } from './patchproof_helpers/jsdom.mjs';", fixed)
        self.assertTrue(runtimes.mentions_sandbox_path(fixed))

    def test_a_sandbox_path_is_a_retryable_message_with_the_replacement_line(self):
        with self.assertRaises(ValueError) as caught:
            self.adapter.validate_generated_test(RC34_MODEL_TEST, "test_patchproof_issue_2.test.mjs")
        self.assertIn("import { JSDOM } from './patchproof_helpers/jsdom.mjs';", str(caught.exception))

    def test_a_bare_jsdom_import_points_to_the_helper_not_the_sandbox(self):
        content = PORTABLE_MODEL_TEST.replace("import { JSDOM } from './patchproof_helpers/jsdom.mjs';",
                                              "import { JSDOM } from 'jsdom';")
        with self.assertRaises(ValueError) as caught:
            self.adapter.validate_generated_test(content, "test_patchproof_issue_2.test.mjs")
        self.assertIn("./patchproof_helpers/jsdom.mjs", str(caught.exception))
        self.assertNotIn("/opt/patchproof", str(caught.exception))

    def test_node_package_is_not_subject_to_the_static_web_rules(self):
        root = Path(tempfile.mkdtemp())
        (root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
        adapter = detect_runtime(root)
        self.assertEqual(adapter.id, "node-package")
        adapter.validate_generated_test(RC34_MODEL_TEST, "test_patchproof_issue_2.test.mjs")


class SupportFilesTests(unittest.TestCase):
    def test_the_helper_is_delivered_beside_the_test(self):
        helpers = proof.support_files("test_patchproof_issue_2.test.mjs", PORTABLE_MODEL_TEST)
        self.assertEqual([h["path"] for h in helpers], ["patchproof_helpers/jsdom.mjs"])
        self.assertEqual(helpers[0]["content"], (ROOT / "patchproof_runtime/jsdom.mjs").read_text(encoding="utf-8"))

    def test_the_helper_follows_a_configured_test_directory(self):
        helpers = proof.support_files("test/test_patchproof_issue_2.test.mjs", PORTABLE_MODEL_TEST)
        self.assertEqual([h["path"] for h in helpers], ["test/patchproof_helpers/jsdom.mjs"])

    def test_web_streams_helpers_are_unchanged(self):
        content = "import { collectBytes } from './patchproof_helpers/web_streams.mjs';\n"
        names = [Path(h["path"]).name for h in proof.support_files("t.test.ts", content)]
        self.assertEqual(names, ["web_streams.mjs", "web_streams.d.mts"])

    def test_a_test_without_helpers_gets_none(self):
        self.assertEqual(proof.support_files("t.test.mjs", "import test from 'node:test';\n"), [])

    def test_a_sandbox_path_in_a_test_is_still_refused_as_a_backstop(self):
        with self.assertRaisesRegex(proof.PatchProofError, "sandbox-only"):
            proof.support_files("t.test.mjs", RC34_MODEL_TEST)


@unittest.skipUnless(SANDBOX_JSDOM.is_dir(), "requires jsdom at /opt/patchproof/node (the sandbox image's copy)")
class HelperResolutionTests(unittest.TestCase):
    def run_helper(self, folder: Path, source: str | None = None) -> str:
        helper = folder / "patchproof_helpers" / "jsdom.mjs"
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(source or (ROOT / "patchproof_runtime/jsdom.mjs").read_text(encoding="utf-8"))
        probe = "import('./patchproof_helpers/jsdom.mjs').then(m => console.log(String(m.JSDOM)), e => { console.log('ERR ' + e.message); })"
        out = subprocess.run(["node", "-e", probe], cwd=folder, capture_output=True, text=True, timeout=60)
        return (out.stdout + out.stderr).strip()

    def test_the_repository_copy_wins_over_the_sandbox_copy(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "node_modules/jsdom").mkdir(parents=True)
        (folder / "node_modules/jsdom/package.json").write_text('{"name":"jsdom","main":"index.js"}')
        (folder / "node_modules/jsdom/index.js").write_text("exports.JSDOM = 'the repository copy';")
        self.assertEqual(self.run_helper(folder), "the repository copy")

    def test_the_sandbox_copy_is_the_fallback(self):
        out = self.run_helper(Path(tempfile.mkdtemp()))
        self.assertIn("class JSDOM", out)

    def test_nothing_installed_says_what_to_add(self):
        source = (ROOT / "patchproof_runtime/jsdom.mjs").read_text(encoding="utf-8").replace(
            "/opt/patchproof/node/package.json", "/nonexistent/package.json")
        out = self.run_helper(Path(tempfile.mkdtemp()), source)
        self.assertIn("npm install --save-dev jsdom", out)

    def test_an_unrelated_error_is_not_swallowed_as_not_installed(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "node_modules/jsdom").mkdir(parents=True)
        (folder / "node_modules/jsdom/package.json").write_text('{"name":"jsdom","main":"index.js"}')
        (folder / "node_modules/jsdom/index.js").write_text("throw new Error('broken install');")
        self.assertIn("broken install", self.run_helper(folder))


@unittest.skipUnless(pipeline.available() and SANDBOX_JSDOM.is_dir(),
                     "requires tsx (TS_LINT_NODE_MODULES) and jsdom at /opt/patchproof/node")
class NativePipelineTests(unittest.TestCase):
    """The whole engine, real node:test and the real jsdom, with a scripted model."""

    def project(self, manifest: dict | None, extra: dict | None = None):
        base = Path(tempfile.mkdtemp())
        checkout = base / "checkout"
        checkout.mkdir()
        (checkout / "index.html").write_text(INDEX_BEFORE)
        for name, text in (extra or {}).items():
            (checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (checkout / name).write_text(text)
        (checkout / "patchproof.json").write_text(json.dumps({"runtime": "static-web"}))
        if manifest is not None:
            (checkout / "package.json").write_text(json.dumps(manifest))
        return base, checkout

    def run_site(self, manifest, test_source, extra=None):
        base, checkout = self.project(manifest, extra)
        calls = []

        def model_text(**kwargs):
            calls.append(kwargs)
            return (f"{proof.TEST_BEGIN}\n{test_source}\n{proof.TEST_END}\n"
                    f"{proof.RATIONALE_BEGIN}\nThe form action must resolve under the deploy path.\n{proof.RATIONALE_END}")

        candidate = lambda **k: ([{"path": "index.html", "content": INDEX_AFTER}], "relative form action")
        result, record, error = pipeline.run_engine(base, checkout, checkout, ISSUE, "unused", candidate,
                                                    model_text=model_text)
        return result, record, error, calls

    def test_the_rc34_test_from_the_live_run_now_reproduces_and_verifies(self):
        result, record, error, calls = self.run_site(GOOD, RC34_MODEL_TEST)
        self.assertIsNone(error, json.dumps(record.get("regression_test", {}).get("attempts"), default=str)[:3000])
        self.assertEqual(result["verdict"], "verified")
        regression = result["regression_test"]
        self.assertTrue(regression["failed_before_fix"])
        self.assertIn("import { JSDOM } from './patchproof_helpers/jsdom.mjs';", regression["content"])
        self.assertNotIn("/opt/patchproof", regression["content"])
        self.assertEqual([item["path"] for item in regression["support_files"]], ["patchproof_helpers/jsdom.mjs"])
        self.assertTrue(regression["ordinary_ci"]["discovered"])
        self.assertTrue(result["baseline"]["discovery_probe"]["discovered"])
        self.assertEqual(len(calls), 1)
        # What the pull request will contain: the fix, the frozen test and the helper that test imports.
        self.assertEqual(sorted(item["path"] for item in result["pr_files"]),
                         ["index.html", "patchproof_helpers/jsdom.mjs", "test_patchproof_issue_2.test.mjs"])

    def test_the_portable_import_works_unchanged(self):
        result, record, error, calls = self.run_site(GOOD, PORTABLE_MODEL_TEST)
        self.assertIsNone(error)
        self.assertEqual(result["verdict"], "verified")

    def test_a_stub_test_script_stops_before_any_model_request(self):
        stub = {**GOOD, "scripts": {"test": "echo 'Baseline test passed successfully' && exit 0"}}
        result, record, error, calls = self.run_site(stub, PORTABLE_MODEL_TEST)
        self.assertIsNone(result)
        self.assertIn("did not run a test file", str(error))
        self.assertIn("\"test\": \"node --test\"", str(error))
        self.assertEqual(calls, [])
        self.assertFalse(record["baseline"]["discovery_probe"]["discovered"])

    def test_a_script_that_misses_the_folder_stops_before_any_model_request(self):
        elsewhere = {**GOOD, "scripts": {"test": "node --test tests/*.test.mjs"}}
        existing = {"tests/existing.test.mjs": "import test from 'node:test'; test('ok', () => {});\n"}
        result, record, error, calls = self.run_site(elsewhere, PORTABLE_MODEL_TEST, existing)
        self.assertIn("did not run a test file", str(error))
        self.assertEqual(calls, [])

    def test_a_site_with_no_package_json_stops_before_the_sandbox(self):
        result, record, error, calls = self.run_site(None, PORTABLE_MODEL_TEST)
        self.assertIsNone(result)
        self.assertIn("needs a test command and jsdom", str(error))
        self.assertEqual(calls, [])
        self.assertNotIn("baseline", record)

    def test_a_missing_jsdom_declaration_stops_before_the_sandbox(self):
        result, record, error, calls = self.run_site({"scripts": GOOD["scripts"]}, PORTABLE_MODEL_TEST)
        self.assertIn("jsdom is not declared", str(error))
        self.assertEqual(calls, [])

    def test_a_blocked_run_is_bucketed_as_readiness_not_as_a_failed_repair(self):
        stub = {**GOOD, "scripts": {"test": "echo ok"}}
        result, record, error, calls = self.run_site(stub, PORTABLE_MODEL_TEST)
        record["error"] = str(error)
        proof.finalize_proof(record)
        self.assertEqual(record["outcome"]["bucket"], "readiness_blocked")
        self.assertTrue(record["readiness"]["before_inference"])

    def test_a_test_that_passes_on_the_unfixed_page_is_still_not_reproduction(self):
        passing = PORTABLE_MODEL_TEST.replace("`${baseUrl}thank-you.html`", "'https://patchproof.invalid/thank-you.html'")
        result, record, error, calls = self.run_site(GOOD, passing)
        self.assertIsNone(result if error else None)
        self.assertIsNotNone(error)


if __name__ == "__main__":
    unittest.main()
