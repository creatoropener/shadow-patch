"""Export only the current engine installation files, excluding historical data."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
import zipfile

FILES = (
    "proof.py", "runtimes.py", "scope_policy.py", "agent_budget.py", "context_tools.py", "agent_loop.py",
    "tools/pr_files.py", "requirements-patchproof.txt",
    "patchproof_runtime/static_web_check.mjs",
    "patchproof_runtime/web_streams.mjs",
    "patchproof_runtime/web_streams.d.mts",
    "patchproof_runtime/typescript_config.py",
    "patchproof_runtime/pytest_check.py",
    "patchproof_runtime/candidate_policy.mjs",
    "patchproof_runtime/typescript_check.py",
    "patchproof_runtime/typescript_source_check.py",
    "patchproof_runtime/typescript_test_lint.mjs",
    "patchproof_runtime/typescript_runtime.d.ts",
    "patchproof_runtime/java_check.py", "patchproof_runtime/junit_check.py",
    ".github/workflows/shadow-fix.yml", ".github/workflows/prepare-image.yml",
)


def _read_app_version(root: Path) -> str:
    text = (root / "proof.py").read_text()
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not find APP_VERSION in proof.py")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for name in FILES:
        if not (root / name).is_file():
            parser.error(f"Incomplete installation: {name}")
    version = _read_app_version(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(root / name, name)
        archive.writestr("PATCHPROOF-INSTALL.md", (
            f"# Install PatchProof v{version}\n\n"
            "Copy the engine files into your target repository, preserving paths.\n"
            "Append __pycache__/ and *.py[cod] to its existing .gitignore.\n"
            "Configure NEBIUS_API_KEY, NEBIUS_PROJECT_ID, NEBIUS_MODEL and a compatible "
            "CONTREE_IMAGE (or runtime-specific image secret) in GitHub Actions.\n"
            "For node-typescript, pin tsx and TypeScript in the target baseline and configure "
            "CONTREE_IMAGE_NODE_TYPESCRIPT with a v0.7 web-image UUID.\n"
            "Copy every file, including agent_budget.py, context_tools.py, agent_loop.py, scope_policy.py and tools/pr_files.py.\n"
            "rc.26 adds an opt-in Node/TypeScript loop: set the repository variable PATCHPROOF_AGENT_MODE=bounded. "
            "The default legacy mode preserves the rc.25 flow. Read docs/BATCH2.md in the engine repository for budgets and limits.\n"
            "Generated tests must be discoverable by the target's ordinary test command. For a Node test "
            "suite, use TAP output (for example node --import tsx --test --test-reporter=tap tests/*.test.ts).\n"
            "Scope rules in patchproof.json apply to every issue; configure them for the intended repair.\n"
            "Commit the workflows to the default branch before applying shadow-fix to an issue.\n\n"
            "Full setup and the optional file-sharing example:\n"
            "https://github.com/creatoropener/shadow-patch/blob/main/docs/SETUP.md\n"
        ))
    print(f"Exported {len(FILES)} engine files (v{version}) and setup instructions to {args.output}")


if __name__ == "__main__":
    main()
