"""Standalone harness uploaded to a prepared sandbox. Never imports repository code.

Test processes are still untrusted: their reports are evidence, not attestations.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import subprocess
import sys
import tempfile


def execute(payload):
    runtime = payload["runtime"]
    files, targets = payload["files"], payload["targets"]
    if runtime not in {"pytest", "node-test"}:
        raise ValueError("Unknown runtime")
    if len(files) > 1001 or not targets or any(t not in files for t in targets):
        raise ValueError("Invalid files/targets")
    with tempfile.TemporaryDirectory(prefix="patchproof-run-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        work, output = root / "repo", root / "output"
        work.mkdir(); output.mkdir()
        can_drop = bool(payload.get("require_uid_separation")) and os.name == "posix" and os.geteuid() == 0
        if payload.get("require_uid_separation") and not can_drop:
            raise ValueError("Prepared cloud image must run harness as root for UID separation")
        total = 0
        for name, item in files.items():
            path = PurePosixPath(name)
            if (path.is_absolute() or str(path) != name or ".." in path.parts or
                    ".git" in path.parts or "\\" in name or name.startswith("-") or
                    any(ord(c) < 32 for c in name)):
                raise ValueError("Unsafe file path")
            content = base64.b64decode(item["content"], validate=True)
            total += len(content)
            if total > 11 * 1024 * 1024:
                raise ValueError("Input too large")
            dest = work / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            dest.chmod(0o555 if item["mode"] == "100755" else 0o444)
        for path in work.rglob("*"):
            if path.is_dir(): path.chmod(0o555)
        work.chmod(0o555)
        report_path = output / "junit.xml"
        env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": str(work), "HOME": str(output), "TMPDIR": str(output)}
        if os.name == "nt": env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        if runtime == "pytest":
            command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                       "-o", "addopts=", "--junitxml=" + str(report_path), *targets]
        else:
            node = shutil.which("node")
            if not node: raise ValueError("Prepared image is missing Node.js")
            command = [node, "--test", "--test-reporter=junit",
                       "--test-reporter-destination=" + str(report_path), *targets]
        options = {}
        if can_drop:
            os.chown(output, 65534, 65534)
            options.update(user=65534, group=65534, extra_groups=[])
        before = {n: hashlib.sha256((work / n).read_bytes()).hexdigest() for n in files}
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(command, cwd=work, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=os.name == "posix", **options)
            timed_out = False
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
            finally:
                if os.name == "posix":
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                process.wait()
            log.seek(0)
            log_text = log.read(50000).decode(errors="replace")
        intact = all((work / n).is_file() and not (work / n).is_symlink() and
                     hashlib.sha256((work / n).read_bytes()).hexdigest() == h for n, h in before.items())
        xml = ""
        if report_path.is_file() and not report_path.is_symlink():
            if report_path.stat().st_size < 2 * 1024 * 1024:
                xml = report_path.read_text(errors="replace")
        result = {"exit_code": -1 if timed_out else process.returncode, "xml": xml,
                  "log": log_text, "inputs_unchanged": intact,
                  "uid_separation": can_drop, "timeout": timed_out,
                  "command": command, "python_version": sys.version.split()[0]}
        # Permit cleanup when this runs as a normal non-root developer account.
        for path in work.rglob("*"):
            if path.is_dir(): path.chmod(0o755)
        work.chmod(0o755)
        return result


if __name__ == "__main__":
    try:
        print(json.dumps(execute(json.load(sys.stdin))))
    except Exception as error:
        print(json.dumps({"exit_code": -1, "xml": "", "inputs_unchanged": False,
                          "log": "Harness error: " + type(error).__name__}))
