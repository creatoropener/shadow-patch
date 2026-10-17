#!/usr/bin/env python3
"""Check (under Node 20, as the benchmark image runs) before spending a benchmark run, that a base commit suits the spec profile.

It mirrors three things the engine does, without calling the engine or a model:

1. Runtime detection: ``node-typescript`` needs package.json and tsconfig.json at the root.
2. Test placement: the generated test goes in ``tests/`` only when ``tests/`` already holds a
   ``*.test.ts`` file, otherwise at the repository root (runtimes.RuntimeAdapter.test_path).
3. The ordinary-CI discovery gate (rc.25): the project's own baseline command (``CI=1 npm test``
   when package.json has a test script) must run the frozen test and fail on it.

It plants a probe test that always fails, runs the baseline command, and requires the probe's
marker in the output with a non-zero exit. It also runs the baseline once without the probe and
requires a green, non-empty run. With --module/--export it checks the target is a TypeScript
source file that exports the name (a text scan, as the engine's own scan is).

Usage:
    tools/preflight_base.py --repo owner/name --commit FULL_40_CHAR_SHA [--module path.ts --export name ...]
    tools/preflight_base.py --path /existing/checkout [...]
Exit code 0 = suitable, 1 = not suitable, 2 = could not check.
Network is needed only to clone and to run `npm ci`. The JSON verdict goes to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "PATCHPROOF_PREFLIGHT_PROBE_FAILS"
SUFFIX = ".test.ts"
TEST_RE = re.compile(r"^(?:# |ℹ )tests (\d+)", re.M)
PASS_RE = re.compile(r"^(?:# |ℹ )pass (\d+)", re.M)


def run(cmd: str, cwd: Path, timeout: int = 900) -> tuple[int, str]:
    env = dict(os.environ, CI="1")
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {cmd}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def counts(output: str) -> tuple[int | None, int | None]:
    total, passed = TEST_RE.search(output), PASS_RE.search(output)
    return (int(total.group(1)) if total else None, int(passed.group(1)) if passed else None)


def detect_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def install_command(root: Path) -> str:
    manager = detect_manager(root)
    if manager == "pnpm":
        return "pnpm install --frozen-lockfile --ignore-scripts"
    if manager == "yarn":
        return "yarn install --frozen-lockfile --ignore-scripts"
    if (root / "package-lock.json").is_file() or (root / "npm-shrinkwrap.json").is_file():
        return "npm ci --ignore-scripts"
    return "npm install --ignore-scripts --no-audit --no-fund"


def check_exports(root: Path, module: str, names: list[str]) -> list[str]:
    problems: list[str] = []
    path = root / module
    if path.suffix not in {".ts", ".mts", ".cts"}:
        return [f"module {module} is not a .ts/.mts/.cts file (spec profile needs TypeScript source)"]
    if not path.is_file():
        return [f"module {module} does not exist at this commit"]
    text = path.read_text(encoding="utf-8", errors="replace")
    for name in names:
        n = re.escape(name)
        pattern = (rf"export\s+(?:async\s+)?function\s*\*?\s*{n}\b|"
                   rf"export\s+(?:const|let|var)\s+{n}\b|"
                   rf"export\s*\{{[^}}]*\b{n}\b[^}}]*\}}")
        if not re.search(pattern, text):
            problems.append(f"{module} does not visibly export {name}")
    return problems


IMPORT_OK = "PATCHPROOF_PREFLIGHT_IMPORT_OK"


def import_probe(root: Path, baseline: str, folder: str, module: str, names: list[str]) -> dict:
    """Plant a passing test that imports each export from the module, trying the engine's three import styles.

    The spec profile compiles `import { name } from "<relative path>"` into the generated test, trying `.js`
    (ESM-style), then `.ts`, then the bare path when the earlier one does not resolve. A project whose test
    loader cannot import its own TypeScript source that way (a ts-node/esm loader on a CommonJS package, say)
    passes the discovery check and still cannot run a single compiled example.
    """
    import posixpath
    results: dict = {}
    probe = root / folder / "test_patchproof_issue_9998.test.ts"
    for style in ("js", "ts", "bare"):
        relative = posixpath.relpath(module, folder or ".")
        if not relative.startswith("."):
            relative = "./" + relative
        stem, ext = posixpath.splitext(relative)
        specifier = {"ts": relative, "bare": stem}.get(style, stem + {".ts": ".js", ".mts": ".mjs", ".cts": ".cjs"}[ext])
        body = ("import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
                f"import {{ {', '.join(names)} }} from {json.dumps(specifier)};\n"
                f"test('{IMPORT_OK}', () => {{ " + "".join(f"assert.equal(typeof {n}, 'function'); " for n in names) + "});\n")
        probe.write_text(body, encoding="utf-8")
        try:
            code, text = run(baseline, root)
        finally:
            probe.unlink(missing_ok=True)
        results[style] = bool(re.search(rf"^\s*ok \d+ - {IMPORT_OK}", text, re.M))
        if results[style]:
            break
    return results


def preflight(root: Path, module: str | None, names: list[str], skip_install: bool, test_directory: str = "", allow_node: bool = False) -> dict:
    out: dict = {"checks": {}, "problems": [], "node": run("node --version", root)[1].strip()}
    checks, problems = out["checks"], out["problems"]
    if not out["node"].startswith("v20.") and not allow_node:
        problems.append(f"this check ran under {out['node']}, but the benchmark image runs Node 20; Node 22 runs .ts files natively and expands globs, so its verdict can be wrong. Put a Node 20 first on PATH or pass --allow-other-node")
        return out

    pkg_path = root / "package.json"
    if not pkg_path.is_file() or not (root / "tsconfig.json").is_file():
        problems.append("runtime would not be node-typescript: package.json and tsconfig.json are both required at the root")
        return out
    package = json.loads(pkg_path.read_text(encoding="utf-8"))
    script = (package.get("scripts") or {}).get("test")
    manager = detect_manager(root)
    baseline = f"CI=1 {manager} test" if isinstance(script, str) else "node --test"
    checks["baseline_command"] = baseline
    checks["test_script"] = script
    if not isinstance(script, str):
        problems.append("no `test` script: the engine falls back to plain `node --test`, which does not run .ts files")

    if module:
        problems += check_exports(root, module, names)

    tests_dir = root / "tests"
    in_tests = tests_dir.is_dir() and any(tests_dir.glob(f"*{SUFFIX}"))
    folder = test_directory.rstrip("/") if test_directory else ("tests" if in_tests else ".")
    if test_directory:
        (root / folder).mkdir(parents=True, exist_ok=True)
    probe = Path(folder) / f"test_patchproof_issue_9999{SUFFIX}"
    checks["probe_location"] = str(probe)
    checks["existing_ts_test_in_tests_dir"] = in_tests

    if not skip_install:
        code, text = run(install_command(root), root)
        checks["install_exit"] = code
        if code != 0:
            problems.append("dependency install failed: " + text[-400:])
            out["install_failed"] = True
            return out

    code, text = run(baseline, root)
    total, passed = counts(text)
    checks["baseline_without_probe"] = {"exit": code, "tests": total, "pass": passed}
    if code != 0:
        problems.append(f"baseline is not green before the probe (exit {code}); the engine needs a passing baseline")
    if not total:
        problems.append("baseline ran zero tests: ordinary CI protects nothing here (compatibility_coverage would be absent)")

    probe_path = root / probe
    probe_path.write_text(
        "import test from 'node:test';\nimport assert from 'node:assert/strict';\n"
        f"test('{MARKER}', () => {{ assert.equal(1, 2, '{MARKER}'); }});\n",
        encoding="utf-8")
    try:
        code, text = run(baseline, root)
    finally:
        probe_path.unlink(missing_ok=True)
    seen = MARKER in text
    checks["baseline_with_probe"] = {"exit": code, "marker_seen": seen, "tests": counts(text)[0]}
    if not seen:
        problems.append(f"the baseline command did not run a generated test placed at {probe}; the discovery gate would block this case")
    elif code == 0:
        problems.append("the probe ran but the baseline still exited 0")
    if module and names and seen:
        outcome = import_probe(root, baseline, folder, module, names)
        checks["import_probe"] = outcome
        if not any(outcome.values()):
            problems.append(f"a test in {folder or '.'} cannot import {', '.join(names)} from {module} under the project's test loader "
                            "(tried .js, .ts and bare specifiers); the spec profile's compiled examples would not load")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--repo", help="owner/name on GitHub")
    where.add_argument("--path", type=Path, help="an existing checkout (a copy is made)")
    parser.add_argument("--commit", help="commit to check out (required with --repo)")
    parser.add_argument("--module", help="TypeScript file the issue's functions live in")
    parser.add_argument("--export", action="append", default=[], dest="exports")
    parser.add_argument("--test-directory", default="", help="the case's patchproof_config.test_directory, when it sets one")
    parser.add_argument("--allow-other-node", action="store_true", help="accept a Node major other than 20 (the benchmark image uses 20)")
    parser.add_argument("--skip-install", action="store_true", help="the checkout already has node_modules")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="preflight-"))
    root = work / "repo"
    try:
        if args.repo:
            if not args.commit:
                parser.error("--commit is required with --repo")
            git = (f"git init -q repo && cd repo && git remote add origin https://github.com/{args.repo}.git"
                   f" && git fetch -q --depth 1 origin {args.commit} && git checkout -q FETCH_HEAD")
            code, text = run(git, work, timeout=300)
            if code != 0:
                print(json.dumps({"verdict": "could_not_check", "reason": text[-500:]}))
                return 2
        else:
            shutil.copytree(args.path, root, symlinks=True)
        result = preflight(root, args.module, args.exports, args.skip_install, args.test_directory, args.allow_other_node)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    result["verdict"] = "suitable" if not result["problems"] else ("could_not_check" if result.get("install_failed") else "not_suitable")
    result["repo"], result["commit"] = args.repo or str(args.path), args.commit
    print(json.dumps(result, indent=2))
    return {"suitable": 0, "not_suitable": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
