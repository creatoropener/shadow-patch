"""Offline harness for rc.27 pipeline tests: real tsc, tsx, node:test and policy scripts; scripted model."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import proof

ROOT = Path(__file__).resolve().parents[1]
DEPS = Path(os.environ.get("TS_LINT_NODE_MODULES", "/missing"))


def available() -> bool:
    return (DEPS / ".bin/tsx").exists()


def write(folder: Path, name: str, text: str) -> None:
    target = folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


class LocalState:
    """A sandbox state backed by a temporary directory and the local toolchain."""
    counter = 0

    def __init__(self, base: Path, files, code=0, output=""):
        self.base, self.files, self.exit_code, self.stdout, self.stderr, self.uuid = base, files, code, output, "", "local"

    def apply_files(self, *, files):
        updates = {k.removeprefix("/workspace/repo/"): v for k, v in files.items()}
        return LocalState(self.base, {**self.files, **updates})

    def run(self, *, shell, cwd, timeout, disposable):
        LocalState.counter += 1
        directory = self.base / f"sandbox-{LocalState.counter}"
        directory.mkdir()
        for name, value in self.files.items():
            target = directory / ("private/" + Path(name).name if name.startswith("/patchproof/") else name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        (directory / "node_modules").symlink_to(DEPS.resolve(), target_is_directory=True)
        command = shell.replace("/patchproof/candidate-policy.json", str(directory / "private/candidate-policy.json"))
        command = command.replace("/opt/patchproof/node/node_modules/", str(DEPS.resolve()) + "/")
        command = command.replace("/patchproof/", str(ROOT / "patchproof_runtime") + "/")
        result = subprocess.run(command, shell=True, cwd=directory, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, "PATCHPROOF_TYPESCRIPT_RUNTIME": str(DEPS.parent)})
        state = LocalState(self.base, self.files, result.returncode, result.stdout + result.stderr)
        return SimpleNamespace(wait=lambda: state)


def run_engine(base: Path, checkout: Path, project: Path, issue: "proof.Issue", test_source: str,
               candidate, *, mode: str = "legacy", model_json=None, env_extra=None, model_text=None):
    """Execute proof.execute offline; returns (result_or_None, record, error_or_None)."""
    initial = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*")
               if p.is_file() and "node_modules" not in p.parts}
    reply = f"{proof.TEST_BEGIN}\n{test_source}\n{proof.TEST_END}\n{proof.RATIONALE_BEGIN}\nRegression.\n{proof.RATIONALE_END}"
    sdk = SimpleNamespace(images=SimpleNamespace(use=lambda *a, **k: object()))
    env = {"NEBIUS_API_KEY": "x", "NEBIUS_PROJECT_ID": "x", "NEBIUS_MODEL": "x", "CONTREE_IMAGE": "x",
           "PATCHPROOF_AGENT_MODE": mode, **(env_extra or {})}
    patches = [patch.dict(os.environ, env), patch.object(proof, "create_sandbox_client", return_value=sdk),
               patch.object(proof, "sandbox_workspace", side_effect=lambda *a, **k: LocalState(base, initial)),
               (patch.object(proof, "model_text", side_effect=model_text) if model_text is not None
                else patch.object(proof, "model_text", return_value=reply))]
    if mode == "bounded":
        patches.append(patch.object(proof, "model_json", side_effect=model_json))
    else:
        patches.append(patch.object(proof, "generate_candidate", side_effect=candidate))
    record = {"candidates": []}
    for item in patches:
        item.start()
    try:
        try:
            return proof.execute(checkout, issue, record), record, None
        except proof.PatchProofError as error:
            return None, record, error
    finally:
        for item in reversed(patches):
            item.stop()
