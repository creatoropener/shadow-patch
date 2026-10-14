"""rc.27: a proof names the exact engine, project inputs and toolchain it was produced with."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proof
from runtimes import detect_runtime


def project(files):
    root = Path(tempfile.mkdtemp(prefix="prov-"))
    for name, text in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


class ProvenanceTests(unittest.TestCase):
    def test_engine_hashes_cover_every_executing_file_and_match_disk(self):
        hashes = proof.engine_file_hashes()
        for name in ("proof.py", "runtimes.py", "scope_policy.py", "agent_loop.py",
                     "patchproof_runtime/candidate_policy.mjs", "patchproof_runtime/typescript_check.py"):
            self.assertIn(name, hashes)
        engine = Path(proof.__file__).resolve().parent
        self.assertEqual(hashes["runtimes.py"], hashlib.sha256((engine / "runtimes.py").read_bytes()).hexdigest())
        self.assertFalse([name for name in hashes if "__pycache__" in name])

    def test_engine_identity_prefers_environment_then_records_version(self):
        with patch.dict("os.environ", {"PATCHPROOF_ENGINE_COMMIT": "abc123", "PATCHPROOF_ENGINE_REF": "v0.6.0-rc.27"}):
            identity = proof.engine_identity()
        self.assertEqual((identity["commit"], identity["ref"], identity["app_version"]),
                         ("abc123", "v0.6.0-rc.27", proof.APP_VERSION))

    def test_project_inputs_hash_manifests_lockfiles_and_effective_config_by_checkout_path(self):
        root = project({"patchproof.json": '{"root":"server"}', "server/package.json": "{}",
                        "server/pnpm-lock.yaml": "lockfileVersion: '9.0'\n", "server/src/a.ts": "x",
                        "server/.env": "SECRET=1"})
        found = proof.project_input_hashes(root, root / "server")
        self.assertEqual(sorted(found), ["patchproof.json", "server/package.json", "server/pnpm-lock.yaml"])
        self.assertEqual(found["server/pnpm-lock.yaml"], hashlib.sha256(b"lockfileVersion: '9.0'\n").hexdigest())
        self.assertNotIn("server/.env", found)

    def test_toolchain_names_versions_in_preflight_order(self):
        root = project({"package.json": json.dumps({"scripts": {"test": "x"}, "packageManager": "pnpm@9.15.9"}),
                        "pnpm-lock.yaml": "lockfileVersion: '9.0'\n", "tsconfig.json": "{}"})
        adapter = detect_runtime(root)
        output = "v20.11.1\n10.2.4\n9.15.9\n4.20.6\nVersion 5.6.3\n"
        found = proof.toolchain_versions(adapter, output)["versions"]
        self.assertEqual(found, {"node": "20.11.1", "npm": "10.2.4", "pnpm": "9.15.9", "tsx": "4.20.6", "tsc": "5.6.3"})

    def test_toolchain_reads_the_two_line_tsx_banner(self):
        # Real rc.30 sandbox output: tsx 4.23 prints its own version and then node's.
        adapter = detect_runtime(project({"package.json": "{}", "tsconfig.json": "{}"}))
        output = "v20.19.2\n9.2.0\ntsx v4.23.15\nnode v20.19.2\nVersion 7.0.2\n"
        found = proof.toolchain_versions(adapter, output)["versions"]
        self.assertEqual(found, {"node": "20.19.2", "npm": "9.2.0", "tsx": "4.23.15", "tsc": "7.0.2"})

    def test_toolchain_keeps_raw_lines_when_output_is_unexpected(self):
        adapter = detect_runtime(project({"package.json": "{}", "tsconfig.json": "{}"}))
        result = proof.toolchain_versions(adapter, "something unexpected\n")
        self.assertEqual(result["versions"], {})
        self.assertEqual(result["raw"], ["something unexpected"])


if __name__ == "__main__":
    unittest.main()
