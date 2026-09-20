"""Local runner is exclusively for the bundled trusted fixture."""
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from .proof import Result


def validate_paths(files):
    for name, content in files.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe input path")
        if not name.startswith(("app/", "tests/")) or not name.endswith(".py"):
            raise ValueError("Only Python app and test inputs are supported")
        if not isinstance(content, str) or len(content) > 100_000:
            raise ValueError("Invalid or oversized file")


def parse_result(code, xml, log, execution_id):
    try:
        root = ET.fromstring(xml)
        suites = list(root.iter("testsuite"))
        totals = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        return Result(code, totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"],
                      totals["failures"], totals["errors"], totals["skipped"], log[-20000:], execution_id)
    except (ET.ParseError, ValueError, TypeError):
        return Result(-1, errors=1, log="Missing/invalid test evidence: " + log[-10000:],
                      execution_id=execution_id)


class LocalFixtureRunner:
    name = "local-trusted-fixture (not VM isolated)"

    def run(self, files, target):
        validate_paths(files)
        if target not in ("tests", "tests/test_regression.py"):
            raise ValueError("Unsupported target")
        with tempfile.TemporaryDirectory(prefix="patchproof-") as directory:
            root = Path(directory)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            env = {"PATH": os.environ.get("PATH", ""), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                   "PYTHONDONTWRITEBYTECODE": "1", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
            try:
                process = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                          "--junitxml=proof.xml", target], cwd=root,
                                         env=env, capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                return Result(-1, errors=1, log="Test timeout")
            xml = (root / "proof.xml").read_text() if (root / "proof.xml").exists() else ""
            return parse_result(process.returncode, xml, process.stdout + process.stderr, str(uuid.uuid4()))


class NebiusRunner:
    name = "nebius-contree (adapter awaiting live validation)"

    def __init__(self, sdk, image):
        self.sdk = sdk
        self.image = image

    def run(self, files, target):
        validate_paths(files)
        if target not in ("tests", "tests/test_regression.py"):
            raise ValueError("Unsupported target")
        # Static harness; source content travels through stdin, never shell interpolation.
        harness = '''import json, pathlib, subprocess, sys, tempfile
p=json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix="patchproof-") as d:
 for name, content in p["files"].items():
  f=pathlib.Path(d)/name; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(content)
 try:
  r=subprocess.run([sys.executable,"-m","pytest","-q","-p","no:cacheprovider","--junitxml=proof.xml",p["target"]],cwd=d,env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD":"1","PATH":"/usr/local/bin:/usr/bin:/bin"},capture_output=True,text=True,timeout=30)
  f=pathlib.Path(d)/"proof.xml"
  print(json.dumps({"code":r.returncode,"xml":f.read_text() if f.exists() else "","log":(r.stdout+r.stderr)[-20000:]}))
 except subprocess.TimeoutExpired:
  print(json.dumps({"code":-1,"xml":"","log":"Timeout"}))
'''
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "harness.py"
            script.write_text(harness)
            # Every execution forks from the SAME clean base, never a candidate result.
            result = self.image.run(shell="python /harness.py", files={"harness.py": str(script)},
                                    stdin=json.dumps({"files": files, "target": target})).wait()
        if result.exit_code != 0:
            return Result(-1, errors=1, log="Sandbox harness failed", execution_id=str(result.uuid))
        try:
            payload = json.loads(result.stdout)
            return parse_result(payload["code"], payload["xml"], payload["log"], str(result.uuid))
        except (ValueError, KeyError, TypeError):
            return Result(-1, errors=1, log="Invalid sandbox evidence")
