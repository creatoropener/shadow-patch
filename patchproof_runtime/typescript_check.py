"""Type-check one generated PatchProof TypeScript regression in project context."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile

try:
    from .typescript_config import resolve_config, check_options, regression_files
except ImportError:  # standalone sandbox entry point
    from typescript_config import resolve_config, check_options, regression_files


def checked_target(value: str, root: Path) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".ts":
        raise ValueError("TypeScript regression path must be a relative .ts file")
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("TypeScript regression file is missing or outside the repository")
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: typescript_check.py <generated-test.ts>", file=sys.stderr)
        return 2

    root = Path.cwd().resolve()
    try:
        target = checked_target(argv[1], root)
    except ValueError as error:
        print(f"PATCHPROOF_TYPESCRIPT_CHECK=invalid: {error}", file=sys.stderr)
        return 2

    tsconfig = root / "tsconfig.json"
    compiler = root / "node_modules" / ".bin" / "tsc"
    semantic_linter = Path(__file__).with_name("typescript_test_lint.mjs")
    for required in (tsconfig, compiler, semantic_linter):
        if not required.is_file():
            print(
                f"PATCHPROOF_TYPESCRIPT_CHECK=unavailable: missing {required}",
                file=sys.stderr,
            )
            return 2

    config_path: Path | None = None
    try:
        resolved = resolve_config(root)
        lint = subprocess.run(
            ["node", str(semantic_linter), target.relative_to(root).as_posix()],
            cwd=root,
            timeout=60,
            check=False,
        )
        if lint.returncode != 0:
            return lint.returncode

        config = {
            "extends": "./tsconfig.json",
            "compilerOptions": check_options(resolved, regression=True),
            "files": regression_files(resolved, target.relative_to(root).as_posix()),
            "include": [],
            "exclude": ["node_modules"],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json",
            prefix=".patchproof-tsconfig-", dir=root, delete=False,
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
            print("PATCHPROOF_TYPESCRIPT_CHECK=passed")
        else:
            print("PATCHPROOF_TYPESCRIPT_CHECK=failed", file=sys.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("PATCHPROOF_TYPESCRIPT_CHECK=timed_out", file=sys.stderr)
        return 2
    except (ValueError, OSError) as error:
        print(f"PATCHPROOF_TYPESCRIPT_CHECK=unavailable: {error}", file=sys.stderr)
        return 2
    finally:
        if config_path is not None:
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
