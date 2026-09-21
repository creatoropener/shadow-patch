"""Export only the current engine installation files, excluding historical data."""
from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

FILES = (
    "proof.py", "runtimes.py", "requirements-patchproof.txt",
    "patchproof_runtime/static_web_check.mjs",
    "patchproof_runtime/web_streams.mjs",
    "patchproof_runtime/java_check.py", "patchproof_runtime/junit_check.py",
    ".github/workflows/shadow-fix.yml", ".github/workflows/prepare-image.yml",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for name in FILES:
        if not (root / name).is_file():
            parser.error(f"Incomplete installation: {name}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(root / name, name)
        archive.writestr("PATCHPROOF-INSTALL.md", (
            "# Install PatchProof v0.6.0-rc.1\n\n"
            "Copy the engine files into your target repository, preserving paths.\n"
            "Append __pycache__/ and *.py[cod] to its existing .gitignore.\n"
            "Configure NEBIUS_API_KEY, NEBIUS_PROJECT_ID, NEBIUS_MODEL and a compatible "
            "CONTREE_IMAGE (or runtime-specific image secret) in GitHub Actions.\n"
            "For node-typescript, pin tsx in the target baseline and configure "
            "CONTREE_IMAGE_NODE_TYPESCRIPT with a v0.6 web-image UUID.\n"
            "Commit the workflows to the default branch before applying shadow-fix to an issue.\n\n"
            "Full setup and the optional file-sharing example:\n"
            "https://github.com/creatoropener/shadow-patch/blob/main/docs/SETUP.md\n"
        ))
    print(f"Exported {len(FILES)} engine files and setup instructions to {args.output}")


if __name__ == "__main__":
    main()
