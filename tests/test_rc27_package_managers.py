"""rc.27: the install tool comes from the project's own lockfile or packageManager field."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from runtimes import RuntimeDetectionError, detect_package_manager, detect_runtime, package_manager_commands


def project(files: dict[str, str], package: dict | None = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="pm-"))
    (root / "package.json").write_text(json.dumps({"name": "t", "scripts": {"test": "node --test"}, **(package or {})}))
    (root / "tsconfig.json").write_text("{}")
    for name, text in files.items():
        (root / name).write_text(text)
    return root


def detect(files, package=None):
    root = project(files, package)
    return detect_package_manager(root, json.loads((root / "package.json").read_text()))


class PackageManagerDetectionTests(unittest.TestCase):
    def test_npm_with_lockfile_uses_ci_and_without_uses_install(self):
        locked = detect({"package-lock.json": "{}"})
        self.assertEqual((locked.name, locked.locked), ("npm", True))
        self.assertTrue(package_manager_commands(locked)[0].startswith("npm ci --ignore-scripts"))
        unlocked = detect({})
        self.assertEqual((unlocked.name, unlocked.locked), ("npm", False))
        self.assertTrue(package_manager_commands(unlocked)[0].startswith("npm install --ignore-scripts"))

    def test_pnpm_lockfile_selects_matching_major_and_frozen_install(self):
        for header, major in (("lockfileVersion: '9.0'", "9"), ("lockfileVersion: '6.0'", "8"), ("lockfileVersion: 5.4", "7")):
            with self.subTest(header=header):
                manager = detect({"pnpm-lock.yaml": header + "\n"})
                self.assertEqual((manager.name, manager.version), ("pnpm", major))
                command = package_manager_commands(manager)[0]
                self.assertIn(f"pnpm@{major}", command)
                self.assertIn("pnpm install --frozen-lockfile --ignore-scripts", command)

    def test_package_manager_field_pins_the_exact_version(self):
        manager = detect({"pnpm-lock.yaml": "lockfileVersion: '9.0'\n"}, {"packageManager": "pnpm@10.4.1+sha512.abc"})
        self.assertEqual((manager.name, manager.version), ("pnpm", "10.4.1"))

    def test_yarn_classic_and_berry_are_told_apart(self):
        classic = detect({"yarn.lock": "# yarn lockfile v1\n"})
        self.assertEqual((classic.name, classic.berry), ("yarn", False))
        self.assertIn("yarn install --frozen-lockfile --ignore-scripts", package_manager_commands(classic)[0])
        berry = detect({"yarn.lock": "__metadata:\n  version: 8\n", ".yarnrc.yml": "nodeLinker: node-modules\n"})
        self.assertEqual((berry.berry, berry.version), (True, "4"))
        command = package_manager_commands(berry)[0]
        self.assertIn("@yarnpkg/cli-dist@4", command)
        self.assertIn("yarn install --immutable --mode=skip-build", command)

    def test_yarn_plug_and_play_is_refused_explicitly(self):
        with self.assertRaisesRegex(RuntimeDetectionError, "Plug'n'Play"):
            detect({"yarn.lock": "__metadata:\n  version: 8\n"})
        with self.assertRaisesRegex(RuntimeDetectionError, "Plug'n'Play"):
            detect({"yarn.lock": "__metadata:\n  version: 8\n", ".yarnrc.yml": "nodeLinker: pnp\n"})

    def test_never_installs_with_a_different_tool_than_the_lockfile(self):
        with self.assertRaisesRegex(RuntimeDetectionError, "Multiple package-manager lockfiles"):
            detect({"package-lock.json": "{}", "yarn.lock": "# yarn lockfile v1\n"})
        with self.assertRaisesRegex(RuntimeDetectionError, "declares pnpm but .* npm lockfile"):
            detect({"package-lock.json": "{}"}, {"packageManager": "pnpm@9.1.0"})
        # An explicit declaration settles two lockfiles only when it names a present one.
        manager = detect({"package-lock.json": "{}", "yarn.lock": "# yarn lockfile v1\n"}, {"packageManager": "yarn@1.22.22"})
        self.assertEqual(manager.name, "yarn")

    def test_stray_bun_lockfile_beside_npm_lockfile_does_not_block_the_run(self):
        # QRcrafts ships package-lock.json and a Bun lockfile; npm is what rc.20-rc.26 used.
        for bun in ("bun.lock", "bun.lockb"):
            manager = detect({"package-lock.json": "{}", bun: "{}"})
            self.assertEqual((manager.name, manager.locked), ("npm", True))
            self.assertIn("Bun lockfile", manager.notes[0])
        with self.assertRaisesRegex(RuntimeDetectionError, "Multiple package-manager lockfiles"):
            detect({"package-lock.json": "{}", "yarn.lock": "# yarn lockfile v1\n", "bun.lock": "{}"})
        root = project({"package-lock.json": "{}", "bun.lock": "{}"})
        self.assertIn("Bun lockfile", detect_runtime(root).package_manager_notes[0])

    def test_bun_and_malformed_declarations_are_refused(self):
        with self.assertRaisesRegex(RuntimeDetectionError, "Bun is not supported"):
            detect({"bun.lock": "{}"})
        with self.assertRaisesRegex(RuntimeDetectionError, "Unsupported packageManager"):
            detect({}, {"packageManager": "pnpm"})

    def test_adapter_uses_the_project_tool_for_tests_scripts_and_preflight(self):
        root = project({"pnpm-lock.yaml": "lockfileVersion: '9.0'\n"})
        adapter = detect_runtime(root)
        self.assertEqual(adapter.id, "node-typescript")
        self.assertEqual(adapter.package_manager, "pnpm")
        self.assertEqual(adapter.baseline_command, "CI=1 pnpm test")
        self.assertEqual(adapter.script_command("build"), "CI=1 pnpm run build")
        self.assertIn("pnpm --version", adapter.preflight_command)
        npm = detect_runtime(project({"package-lock.json": "{}"}))
        self.assertEqual(npm.script_command("build"), "CI=1 npm run build")
        self.assertNotIn("pnpm", npm.preflight_command)


if __name__ == "__main__":
    unittest.main()
