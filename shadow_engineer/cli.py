import argparse
import json
import os
from pathlib import Path
from .fixture import SOURCE, ISSUE, REGRESSION, CANDIDATES
from .proof import verify
from .runners import LocalFixtureRunner, NebiusRunner


def main():
    parser = argparse.ArgumentParser(description="Shadow Engineer: PatchProof milestone one")
    parser.add_argument("command", choices=["demo", "cloud-demo"])
    parser.add_argument("--output", default="artifacts")
    args = parser.parse_args()
    regression, candidates, model = REGRESSION, CANDIDATES, "none: scripted fixture"
    if args.command == "demo":
        runner = LocalFixtureRunner()
    else:
        from contree_client.httpx import ContreeClient as ContreeSyncClient
        from contree_sdk import ContreeSync
        from .model import generate
        client = ContreeSyncClient(os.environ["NEBIUS_API_KEY"], base_url=os.environ["CONTREE_BASE_URL"])
        sdk = ContreeSync(client)
        image = sdk.images.use(os.environ["CONTREE_IMAGE"], strict=True)
        runner = NebiusRunner(sdk, image)
        regression, candidates, model = generate(ISSUE, SOURCE)
    report = verify(runner, SOURCE, regression, candidates)
    report.update(issue=ISSUE, model=model, mode=args.command)
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "proof.json").write_text(json.dumps(report, indent=2))
    lines = ["# Shadow Engineer — PatchProof evidence", "", f"Status: **{report['status']}**",
             f"Mode: {args.command}", f"Provider: {runner.name}", f"Model: {model}", "",
             "| Gate | Exit | Passed | Failed | Errors |", "|---|---:|---:|---:|---:|"]
    for stage in report["stages"]:
        lines.append(f"| {stage['stage']} | {stage['exit_code']} | {stage['passed']} | {stage['failed']} | {stage['errors']} |")
    lines += ["", "Human merge approval required. No PR has been opened.", "",
              "Evidence covers the supplied tests only. Local demo uses scripted inputs and separate temporary directories, not Nebius VMs."]
    (directory / "PR_EVIDENCE.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"status": report["status"], "winner": report["winner"],
                      "candidates_evaluated": len(report["candidates"]), "output": str(directory)}))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
