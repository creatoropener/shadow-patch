"""Guards the reusable Action manifest so packaging cannot drift from the engine."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_IMAGE_ENV = {
    "python-pytest": "CONTREE_IMAGE_PYTHON_PYTEST",
    "node-package": "CONTREE_IMAGE_NODE_PACKAGE",
    "node-typescript": "CONTREE_IMAGE_NODE_TYPESCRIPT",
    "static-web": "CONTREE_IMAGE_STATIC_WEB",
    "web-playwright": "CONTREE_IMAGE_WEB_PLAYWRIGHT",
    "java-junit": "CONTREE_IMAGE_JAVA_JUNIT",
    "java-maven": "CONTREE_IMAGE_JAVA_MAVEN",
    "java-gradle": "CONTREE_IMAGE_JAVA_GRADLE",
    "go": "CONTREE_IMAGE_GO",
    "rust": "CONTREE_IMAGE_RUST",
}


class ActionManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
        cls.text = (ROOT / "action.yml").read_text(encoding="utf-8")

    def test_is_composite_with_required_credentials(self) -> None:
        self.assertEqual(self.action["runs"]["using"], "composite")
        for name in ("nebius-api-key", "nebius-project-id", "nebius-model"):
            self.assertTrue(self.action["inputs"][name]["required"], name)

    def test_every_adapter_has_an_image_input_wired_to_its_env_var(self) -> None:
        run_step = next(s for s in self.action["runs"]["steps"] if s.get("id") == "patchproof")
        env = run_step["env"]
        for env_name in ADAPTER_IMAGE_ENV.values():
            self.assertIn(env_name, env)
            self.assertRegex(env[env_name], r"^\$\{\{ inputs\.image-[a-z-]+ \}\}$")
        self.assertIn("CONTREE_IMAGE", env)

    def test_image_env_names_match_the_engines_derivation(self) -> None:
        source = (ROOT / "proof.py").read_text(encoding="utf-8")
        self.assertIn("CONTREE_IMAGE_{adapter.id.replace('-', '_').upper()}", source)
        for adapter_id, env_name in ADAPTER_IMAGE_ENV.items():
            self.assertEqual(env_name, "CONTREE_IMAGE_" + adapter_id.replace("-", "_").upper())

    def test_every_run_step_declares_a_shell(self) -> None:
        for step in self.action["runs"]["steps"]:
            if "run" in step:
                self.assertEqual(step.get("shell"), "bash", step.get("name"))

    def test_engine_runs_from_action_path_against_the_workspace(self) -> None:
        self.assertIn('python "${{ github.action_path }}/proof.py" --repo "$GITHUB_WORKSPACE"', self.text)

    def test_no_secrets_context_inside_the_action(self) -> None:
        self.assertNotRegex(self.text, r"\$\{\{\s*secrets\.")

    def test_example_caller_pins_the_current_version(self) -> None:
        example = (ROOT / "examples/action-usage/shadow-fix.yml").read_text(encoding="utf-8")
        version = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', (ROOT / "proof.py").read_text(), re.M).group(1)
        self.assertIn(f"creatoropener/shadow-patch@v{version}", example)


if __name__ == "__main__":
    unittest.main()
