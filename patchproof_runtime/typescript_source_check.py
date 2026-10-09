"""Type-check the whole TypeScript project in the Sandbox (rc.24).

    typescript_source_check.py --project

Runs from the repository root. The repository's own compiler checks the project exactly
as its own tsconfig.json defines it (the same program ``tsc --noEmit`` builds), with
emit switched off. The engine calls it twice over a run:

  1. once on the unmodified repository, before any candidate is evaluated. Only when it
     passes can a later failure be blamed on a candidate rather than on the repository,
     so a failing or unavailable result blocks this runtime profile;
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


try:
    from .typescript_config import resolve_config, check_options
except ImportError:
    from typescript_config import resolve_config, check_options


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
    config_path: Path | None = None
    try:
        resolved = resolve_config(root)
        config = {"extends": "./tsconfig.json", "compilerOptions": check_options(resolved)}
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
    except (ValueError, OSError) as error:
        print(f"PATCHPROOF_SOURCE_CHECK=unavailable: {error}", file=sys.stderr)
        return 2
    finally:
        if config_path is not None:
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
