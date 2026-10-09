"""Resolve JSONC, extends and file lists with the target's own TypeScript CLI.

No dependency on the classic Compiler API: native compiler distributions can
also provide --showConfig. Unsupported project graphs are explicit, never passes.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess


def resolve_config(root: Path) -> dict:
    compiler = root / "node_modules/.bin/tsc"
    result = subprocess.run(
        [str(compiler), "--showConfig", "--project", str(root / "tsconfig.json")],
        cwd=root, capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode:
        raise ValueError("Cannot resolve tsconfig: " + (result.stdout + result.stderr)[-2000:])
    config = json.loads(result.stdout)
    if not isinstance(config, dict):
        raise ValueError("Compiler returned an invalid configuration")
    if config.get("references"):
        raise ValueError("Project references require a configured owning-project adapter; this profile checks a single tsconfig")
    return config


def check_options(config: dict, *, regression: bool = False) -> dict:
    options = {
        "composite": False, "incremental": False, "noEmit": True,
        "noErrorTruncation": True, "plugins": [],
    }
    if regression:
        options["rootDir"] = "."
        types = config.get("compilerOptions", {}).get("types")
        if isinstance(types, list):
            options["types"] = list(dict.fromkeys([*types, "node"]))
    return options


def regression_files(config: dict, target: str) -> list[str]:
    # A files:[test] override otherwise drops project-owned global declarations.
    declarations = [name for name in config.get("files", [])
                    if name.endswith((".d.ts", ".d.mts", ".d.cts"))]
    return list(dict.fromkeys([target, *declarations]))
