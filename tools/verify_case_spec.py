#!/usr/bin/env python3
"""Offline oracle check for a spec-profile case, with no model and no engine run.

You give it the issue file, a specification written by hand in the shape the model returns, a checkout
of the base commit and a checkout of the upstream fixed commit (both with dependencies installed).
It then does what the spec stage does and one thing more:

1. validates the specification against the issue with the engine's own `spec_profile.validate_spec`
   (every value grounded in quoted issue text), strict mode;
2. compiles the test with `spec_profile.compile_test`;
3. runs the project's own `CI=1 <pm> test` on the base checkout with the test planted, and reads the
   per-example result: examples whose own assertion fails are reproduction, examples that pass are guards;
4. runs the same test on the fixed checkout and requires every example to pass.

If step 4 fails for an example, the expected value in the issue is not what the maintainers' fix does:
repair the issue text before using the case. This is evidence about the case, not about the engine.

Usage: tools/verify_case_spec.py --issue bench/issues/X.md --spec spec.json --base DIR --fixed DIR
           --module src/x.ts [--test-directory test]
Put a Node 20 first on PATH: the benchmark image runs Node 20.
Exit 0 = specification valid, reproduces on base, passes on fixed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import spec_profile as sp  # noqa: E402


def run_tests(checkout: Path, test_path: str, source: str, ids: list[str]) -> tuple[dict, str, int]:
    planted = checkout / test_path
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(source, encoding="utf-8")
    try:
        manager = "pnpm" if (checkout / "pnpm-lock.yaml").is_file() else "npm"
        proc = subprocess.run(f"CI=1 {manager} test", shell=True, cwd=checkout, capture_output=True, text=True,
                              env=dict(os.environ, CI="1"), timeout=900)
    finally:
        planted.unlink(missing_ok=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    return sp.parse_example_results(output, ids), output, proc.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issue", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True, help="JSON object as the model would return it")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--test-directory", default="")
    args = parser.parse_args(argv)

    issue_text = args.issue.read_text(encoding="utf-8")
    raw = json.loads(args.spec.read_text(encoding="utf-8"))
    modules: dict[str, str] = {}
    literals: set[str] = set()
    for path in sorted((args.base / "src").rglob("*.ts")) if (args.base / "src").is_dir() else []:
        rel = path.relative_to(args.base).as_posix()
        if ".test." in rel or rel.endswith(".d.ts"):
            continue
        modules[rel] = path.read_text(encoding="utf-8")
        literals |= sp.string_literals(modules[rel])
    if args.module not in modules:
        modules[args.module] = (args.base / args.module).read_text(encoding="utf-8")
        literals |= sp.string_literals(modules[args.module])

    validation = sp.validate_spec(raw, issue_text=issue_text, modules=modules, source_literals=literals)
    report: dict = {"validation_errors": validation.errors, "unsupported": validation.unsupported}
    if not validation.ok:
        print(json.dumps(report, indent=2))
        return 1
    spec = validation.spec
    ids = [e.id for e in spec.examples]
    folder = args.test_directory.rstrip("/")
    test_path = (folder + "/" if folder else "") + "test_patchproof_issue_9999.test.ts"

    outcome: dict = {}
    for style_index, style in enumerate(sp.IMPORT_STYLES):
        source = sp.compile_test(spec, test_path=test_path, style=style)
        base_results, base_out, _ = run_tests(args.base, test_path, source, ids)
        if sp.MODULE_RESOLUTION_CODES.search(base_out) and style_index + 1 < len(sp.IMPORT_STYLES):
            continue
        fixed_results, fixed_out, fixed_code = run_tests(args.fixed, test_path, source, ids)
        outcome = {"import_style": style, "base": {i: r["state"] for i, r in base_results.items()},
                   "fixed": {i: r["state"] for i, r in fixed_results.items()}, "fixed_exit": fixed_code}
        break
    report.update(outcome)
    decision = sp.decide(base_results, spec)
    report["engine_decision_on_base"] = {"action": decision.action, "classification": decision.classification,
                                         "qualifying": decision.qualifying, "pruned": decision.pruned}
    all_fixed_pass = all(state == "pass" for state in outcome.get("fixed", {}).values())
    report["verdict"] = ("ok" if decision.qualifying and all_fixed_pass else "check the issue text")
    print(json.dumps(report, indent=2))
    if not all_fixed_pass:
        print(fixed_out[-1500:], file=sys.stderr)
    return 0 if report["verdict"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
