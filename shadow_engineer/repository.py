"""Read Git objects without checking out or executing repository code."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

MAX_FILES = 1000
MAX_BYTES = 10 * 1024 * 1024


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or str(p) != name or
            any(x in {"..", ".git"} for x in p.parts) or "\\" in name or
            any(ord(c) < 32 for c in name) or name.startswith("-")):
        raise ValueError(f"Unsafe repository path: {name!r}")
    return name


def git(repo, *args):
    # No checkout, hooks, submodules, filters, package installation or source imports.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    p = subprocess.run(["git", "--no-pager", "-C", str(Path(repo).resolve()),
                        "-c", "core.hooksPath=" + os.devnull, *args],
                       capture_output=True, env=env, timeout=30)
    if p.returncode:
        raise ValueError("Git could not read the requested repository/commit")
    return p.stdout


def commit(repo, ref):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", ref):
        raise ValueError("Use a full lowercase commit SHA, not a branch, tag or abbreviation")
    resolved = git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
    if resolved != ref:
        raise ValueError("Commit does not match requested SHA")
    return ref


def snapshot(repo, revision):
    commit(repo, revision)
    records = [r for r in git(repo, "ls-tree", "-r", "-z", "-l", revision).split(b"\0") if r]
    if len(records) > MAX_FILES:
        raise ValueError("Prototype repository limit: 1000 tracked files")
    files, total = {}, 0
    for record in records:
        meta, raw_name = record.split(b"\t", 1)
        mode, kind, oid, size = meta.split()
        name = safe_path(raw_name.decode("utf-8"))
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError("Symlinks and submodules are unsupported: " + name)
        total += int(size)
        if total > MAX_BYTES:
            raise ValueError("Prototype repository limit: 10 MiB of tracked files")
        content = git(repo, "cat-file", "blob", oid.decode())
        if len(content) != int(size):
            raise ValueError("Git object size mismatch")
        files[name] = {"mode": mode.decode(), "content": base64.b64encode(content).decode()}
    if not files:
        raise ValueError("Empty repository snapshot")
    return files


def inventory(repo, revision):
    files = snapshot(repo, revision)
    names = sorted(files)
    stacks = []
    if any(n.endswith(".py") for n in names): stacks.append("python")
    if any(n.endswith((".js", ".mjs", ".cjs", ".ts", ".tsx")) for n in names):
        stacks.append("javascript/typescript")
    if any(n.endswith(".html") for n in names): stacks.append("browser/html")
    return {"commit": revision, "snapshot_sha256": sha(canonical(files)),
            "file_count": len(files), "stack_hints": stacks,
            "test_candidates": [n for n in names if n.startswith(("tests/", "test/")) or
                                ".test." in n or ".spec." in n],
            "files": names, "execution": "none"}


def protected(name):
    parts = PurePosixPath(name).parts
    leaf = parts[-1]
    return (any(p.lower() in {"test", "tests", "__tests__", ".github", ".patchproof", "node_modules"}
                for p in parts) or leaf.startswith(("test_", ".env")) or
            ".test." in leaf or ".spec." in leaf or leaf.endswith("_test.py") or
            leaf in {"conftest.py", "sitecustomize.py", "usercustomize.py", "pyproject.toml",
                     "pytest.ini", "setup.cfg", "setup.py", "tox.ini", "package.json",
                     "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock"})


def lock_inputs(repo, base, issue, test, suite, writable, runtime, provenance="human-supplied"):
    files = snapshot(repo, base)
    if runtime not in {"pytest", "node-test"}:
        raise ValueError("Supported runtimes: pytest and node-test")
    suffix = ".py" if runtime == "pytest" else ".test.mjs"
    test_path = "tests/test_patchproof_locked" + suffix
    if test_path in files:
        raise ValueError("Reserved regression path already exists")
    if not isinstance(issue, str) or not issue.strip() or len(issue) > 20000:
        raise ValueError("Issue must contain 1–20000 characters")
    if not isinstance(test, str) or not test.strip() or len(test.encode()) > 100000:
        raise ValueError("Regression must contain 1–100000 bytes")
    suite, writable = sorted(set(suite)), sorted(set(writable))
    if not suite or not writable:
        raise ValueError("Specify existing suite files and writable application files")
    for name in suite + writable:
        safe_path(name)
        if name not in files:
            raise ValueError("Path is not a tracked base file: " + name)
    for name in writable:
        if name in suite or protected(name):
            raise ValueError("Tests or configuration cannot be writable: " + name)
    if any(not n.endswith(".py" if runtime == "pytest" else (".js", ".cjs", ".mjs")) for n in suite):
        raise ValueError("Suite file extension does not match runtime")
    return {"schema": 2, "base_commit": base, "base_snapshot_sha256": sha(canonical(files)),
            "runtime": runtime, "issue": issue, "suite": suite, "writable": writable,
            "regression_path": test_path, "regression": test,
            "regression_sha256": sha(test.encode()), "test_provenance": provenance,
            "independence_claim": "separate test input; author independence not attested"}


def validate_lock(repo, lock, expected_digest):
    if sha(canonical(lock)) != expected_digest:
        raise ValueError("Locked input digest mismatch")
    if lock.get("schema") != 2:
        raise ValueError("Unsupported lock schema")
    recreated = lock_inputs(repo, lock["base_commit"], lock["issue"], lock["regression"],
                            lock["suite"], lock["writable"], lock["runtime"], lock["test_provenance"])
    if recreated != lock:
        raise ValueError("Lock no longer matches base, tests or policy")
    return snapshot(repo, lock["base_commit"])


def candidate(repo, base, head, files, writable):
    commit(repo, head)
    git(repo, "merge-base", "--is-ancestor", base, head)
    proposed = snapshot(repo, head)
    changed = sorted(n for n in files.keys() | proposed.keys() if files.get(n) != proposed.get(n))
    if not changed:
        raise ValueError("Candidate contains no changes")
    if any(n not in writable or n not in proposed or proposed[n]["mode"] != files[n]["mode"] for n in changed):
        raise ValueError("Candidate changes protected files, deletes a file, or changes a mode")
    diff = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--binary", "--no-renames", base, head, "--")
    return proposed, changed, sha(diff)
