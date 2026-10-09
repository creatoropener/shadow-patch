"""Validate the delivered files, then expose literal Git pathspecs to PR Actions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import uuid


def verified_paths(root: Path) -> list[str]:
    proof = json.loads((root / "proof.json").read_text())
    if proof.get("verdict") != "verified" or not proof.get("clean_replay", {}).get("passed"):
        raise ValueError("PR delivery needs a verified clean replay")
    files = proof.get("pr_files")
    if not isinstance(files, list) or not files:
        raise ValueError("No verified PR file manifest")
    paths = []
    for item in files:
        name = item.get("path", "")
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name
                or any(c in name for c in "\r\n\0\\") or name in {"proof.json", "verification-report.md"}):
            raise ValueError("Unsafe PR file path")
        local = root / name
        if local.is_symlink() or not local.resolve().is_relative_to(root.resolve()):
            raise ValueError("PR file escapes repository")
        if hashlib.sha256(local.read_bytes()).hexdigest() != item.get("sha256"):
            raise ValueError("PR file differs from the replayed bytes: " + name)
        paths.append(":(literal)" + name)
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate PR file path")
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    paths = verified_paths(args.repo.resolve())
    output = "\n".join(paths)
    if os.environ.get("GITHUB_OUTPUT"):
        delimiter = "PATCHPROOF_" + uuid.uuid4().hex
        with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
            handle.write(f"paths<<{delimiter}\n{output}\n{delimiter}\n")
    print(output)


if __name__ == "__main__":
    main()
