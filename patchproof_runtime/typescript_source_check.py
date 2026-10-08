"""Type-check the whole TypeScript project in the Sandbox (rc.24).

    typescript_source_check.py --project

Runs from the repository root. The repository's own compiler checks the project exactly
as its own tsconfig.json defines it (the same program ``tsc --noEmit`` builds), with
emit switched off. The engine calls it twice over a run:

  1. once on the unmodified repository, before any candidate is evaluated. Only when it
     passes can a later failure be blamed on a candidate rather than on the repository,
     so a failing or unavailable result switches the candidate compile check off;
  2. once per candidate after the candidate's repair is applied, before the hidden
     regression test is added. The hidden test is not in the working tree at that point,
     so nothing printed here can describe it.

The whole project is checked, not just the changed files, because ambient declarations
(``*.d.ts``, ``declare module '*.css'``) only exist in the whole program, and because a
repair can break a caller in a file it never touched.

Exit status: 0 passed, 1 diagnostics were reported, 2 the check could not run. The
compiler's diagnostics go to the output; the last line states the result.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def is_solution_style(tsconfig: Path) -> bool:
    """A root tsconfig that only lists ``references`` checks nothing by itself.

    Its compiler options live in the referenced configs, so extending it from a
    temporary config would silently use compiler defaults. Declining to run is safer
    than reporting diagnostics the project's own build would never produce.
    """
    try:
        config = json.loads(tsconfig.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(config, dict)
        and bool(config.get("references"))
        and not config.get("include")
        and not config.get("files")
    )


def compiler_options(tsconfig: Path) -> dict[str, object]:
    options: dict[str, object] = {
        "composite": False,
        "incremental": False,
        "noEmit": True,
        "noErrorTruncation": True,
        "plugins": [],
        "skipLibCheck": True,
    }
    # Same rule as typescript_check.py: a project that restricts "types" (a Vite project
    # with ["vite/client"]) would otherwise lose @types/node, and with it `node:` modules
    # such as dns, fs and http that application code imports.
    try:
        project_types = json.loads(tsconfig.read_text(encoding="utf-8")).get(
            "compilerOptions", {}
        ).get("types")
    except (OSError, ValueError, AttributeError):
        project_types = None
    if isinstance(project_types, list):
        options["types"] = list(dict.fromkeys([*project_types, "node"]))
    return options


def main(argv: list[str]) -> int:
    if argv[1:] != ["--project"]:
        print("usage: typescript_source_check.py --project", file=sys.stderr)
        return 2

    root = Path.cwd().resolve()
    tsconfig = root / "tsconfig.json"
    compiler = root / "node_modules" / ".bin" / "tsc"
    for required in (tsconfig, compiler):
        if not required.is_file():
            print(
                f"PATCHPROOF_SOURCE_CHECK=unavailable: missing {required}",
                file=sys.stderr,
            )
            return 2
    if is_solution_style(tsconfig):
        print(
            "PATCHPROOF_SOURCE_CHECK=unavailable: tsconfig.json only lists references",
            file=sys.stderr,
        )
        return 2

    config = {"extends": "./tsconfig.json", "compilerOptions": compiler_options(tsconfig)}
    config_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            prefix=".patchproof-source-tsconfig-", dir=root, delete=False,
        ) as generated:
            json.dump(config, generated, indent=2)
            generated.write("\n")
            config_path = Path(generated.name)
        result = subprocess.run(
            [str(compiler), "--project", str(config_path), "--pretty", "false"],
            cwd=root,
            timeout=180,
            check=False,
        )
        if result.returncode == 0:
            print("PATCHPROOF_SOURCE_CHECK=passed")
            return 0
        print("PATCHPROOF_SOURCE_CHECK=failed", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("PATCHPROOF_SOURCE_CHECK=timed_out", file=sys.stderr)
        return 2
    finally:
        if config_path is not None:
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
