"""Offline checks for the fresh-set tools and the first fresh case (no network, no install)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreflightHelpers(unittest.TestCase):
    def setUp(self):
        self.pre = load("preflight_base")

    def test_counts_read_tap_and_spec_reporters(self):
        self.assertEqual(self.pre.counts("# tests 4\n# pass 3\n# fail 1\n"), (4, 3))
        self.assertEqual(self.pre.counts("ℹ tests 40\nℹ pass 40\n"), (40, 40))
        self.assertEqual(self.pre.counts("nothing here"), (None, None))

    def test_export_scan_is_textual(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.ts").write_text(
                "export function a() {}\nexport const b = () => 1\nfunction c() {}\nexport { c }\nclass D {}\n")
            self.assertEqual(self.pre.check_exports(root, "m.ts", ["a", "b", "c"]), [])
            self.assertEqual(len(self.pre.check_exports(root, "m.ts", ["D"])), 1)
            self.assertIn("not a .ts", self.pre.check_exports(root, "m.js", ["a"])[0])
            self.assertIn("does not exist", self.pre.check_exports(root, "missing.ts", ["a"])[0])

    def test_manager_and_install_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(self.pre.install_command(root), "npm install --ignore-scripts --no-audit --no-fund")
            (root / "package-lock.json").write_text("{}")
            self.assertEqual(self.pre.install_command(root), "npm ci --ignore-scripts")


class FreshCase(unittest.TestCase):
    def test_manifest_case_and_issue_are_consistent(self):
        manifest = json.loads((ROOT / "bench/manifest.json").read_text(encoding="utf-8"))
        case = next(c for c in manifest["cases"] if c["id"] == "fresh-overlaykit-1")
        self.assertEqual(case["split"], "heldout")
        self.assertRegex(case["base_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(case["patchproof_config"], {"runtime": "node-typescript", "test_directory": "test"})
        body = (ROOT / case["issue"]["body_file"]).read_text(encoding="utf-8")
        for needle in ("applyOverlay", "# document", "# overlay", "# expected result"):
            self.assertIn(needle, body)
        self.assertEqual(body.count("# expected result"), 4)

    def test_examples_are_groundable_with_the_engines_validator(self):
        import spec_profile as sp
        body = (ROOT / "bench/issues/fresh-overlaykit-1.md").read_text(encoding="utf-8")
        import re
        blocks = [b.strip() for b in re.findall(r"```yaml\n(.*?)```", body, re.S)]
        self.assertEqual(len(blocks), 4)
        for block in blocks:
            self.assertIsNotNone(sp.locate_evidence(block, body))
            # the overlay header strings an argument needs are inside every block
            for word in ("1.0.0", "t", "target", "update"):
                self.assertIn(word, block)


if __name__ == "__main__":
    unittest.main()
