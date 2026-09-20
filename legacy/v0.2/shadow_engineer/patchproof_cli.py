"""External repository commands; no automatic checkout or repository mutation."""
import argparse
import json
from pathlib import Path
import sys
from .repository import inventory, lock_inputs, canonical, sha
from .external_proof import verify_external, write_report


def main():
    p = argparse.ArgumentParser(description="PatchProof external repository verification (0.2.0)")
    sub = p.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Read tracked files and identify test/stack hints; executes nothing")
    inspect.add_argument("--repo", required=True)
    inspect.add_argument("--base", required=True)
    draft = sub.add_parser("draft-test", help="Draft a test via NVIDIA on Token Factory using base files only")
    draft.add_argument("--repo", required=True)
    draft.add_argument("--base", required=True)
    draft.add_argument("--issue", required=True, type=Path)
    draft.add_argument("--runtime", choices=["pytest", "node-test"], required=True)
    draft.add_argument("--context", action="append", required=True)
    draft.add_argument("--output", required=True, type=Path)
    lock = sub.add_parser("lock", help="Freeze issue, regression and source-only change policy")
    lock.add_argument("--repo", required=True)
    lock.add_argument("--base", required=True)
    lock.add_argument("--issue", required=True, type=Path)
    lock.add_argument("--regression", required=True, type=Path)
    lock.add_argument("--runtime", choices=["pytest", "node-test"], required=True)
    lock.add_argument("--suite", action="append", required=True)
    lock.add_argument("--writable", action="append", required=True)
    lock.add_argument("--output", required=True, type=Path)
    lock.add_argument("--provenance", default="human-supplied; author independence not attested")
    verify = sub.add_parser("verify", help="Execute immutable base/candidate snapshots on Nebius")
    verify.add_argument("--repo", required=True)
    verify.add_argument("--head", required=True)
    verify.add_argument("--lock", required=True, type=Path)
    verify.add_argument("--lock-sha256", required=True)
    verify.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    try:
        if args.command == "inspect":
            print(json.dumps(inventory(args.repo, args.base), indent=2))
            return 0
        if args.command == "draft-test":
            if args.output.exists(): raise ValueError("Choose a new output directory")
            from .regression_author import draft as author
            test, metadata = author(args.repo, args.base, args.issue.read_text(), args.context, args.runtime)
            args.output.mkdir(parents=True)
            suffix = ".py" if args.runtime == "pytest" else ".test.mjs"
            (args.output / ("regression" + suffix)).write_text(test)
            (args.output / "generation.json").write_text(json.dumps(metadata, indent=2))
            print(json.dumps({"output": str(args.output), "model": metadata["model"],
                              "regression_sha256": metadata["regression_sha256"]}))
            return 0
        if args.command == "lock":
            value = lock_inputs(args.repo, args.base, args.issue.read_text(), args.regression.read_text(),
                                args.suite, args.writable, args.runtime, args.provenance)
            # File is verifier-owned; callers retain digest separately from patch author.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x") as out: out.write(json.dumps(value, indent=2))
            print(json.dumps({"lock": str(args.output), "lock_sha256": sha(canonical(value))}))
            return 0
        if args.output.exists(): raise ValueError("Choose a new output directory for each run")
        from .external_runners import NebiusExternalRunner
        # Validate inputs before connecting to a paid execution service.
        from .repository import validate_lock, candidate
        value = json.loads(args.lock.read_text())
        base = validate_lock(args.repo, value, args.lock_sha256)
        candidate(args.repo, value["base_commit"], args.head, base, value["writable"])
        runner = NebiusExternalRunner()
        report = verify_external(args.repo, args.head, value, args.lock_sha256, runner)
        write_report(report, args.output)
        print(json.dumps({"status": report["status"], "report": str(args.output)}))
        return 0 if report["status"] == "passed-checks" else 1
    except (ValueError, OSError, KeyError) as error:
        print("PatchProof: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
