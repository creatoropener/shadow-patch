"""Run the project's ordinary test command and accept only declared, pre-existing failures (rc.27).

    known_failures.py <base64-json-list-of-test-names> <ordinary test command>

A repository whose own suite already fails can still be repaired when the maintainer lists
the failing test names in patchproof.json (`known_failures`). The command's output is passed
through unchanged. The exit status is then 0 only when every failing leaf test is a declared
one, so every later check keeps its usual meaning: a candidate that breaks any other
test, or a regression that fails when the ordinary command runs, still exits non-zero.

Only node:test TAP output can be accounted test by test. Anything else (another runner, a
crash, a count that does not add up) keeps the command's own failing status.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys

MARKER = "PATCHPROOF_BASELINE="


def failing_tests(output: str) -> list[str] | None:
    """Names of failing leaf tests in node:test TAP output, or None when it cannot be trusted."""
    totals = re.findall(r"^# fail (\d+)\s*$", output, re.MULTILINE)
    if len(totals) != 1:
        return None
    if re.search(r"^# cancelled [1-9]\d*\s*$", output, re.MULTILINE):
        return None
    names: list[str] = []
    pattern = re.compile(r"^([ ]*)not ok \d+ - (.*?)\s*$(?:\n\1  ---\n(.*?)^\1  \.\.\.\s*$)?",
                         re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(output):
        name, body = match.group(2), match.group(3) or ""
        if re.search(r"^\s*failureType: ['\"]?subtestsFailed['\"]?\s*$", body, re.MULTILINE):
            continue  # a parent suite repeats its children's failure
        name = re.sub(r"\s+# (?:SKIP|TODO)\b.*$", "", name).replace("\\#", "#")
        names.append(name)
    return names if len(names) == int(totals[0]) else None


def decide(returncode: int, output: str, known: set[str]) -> tuple[int, dict]:
    if returncode == 0:
        return 0, {"status": "passed", "known_failures": []}
    names = failing_tests(output)
    if names is None:
        return returncode or 1, {"status": "failed", "reason": "failures could not be accounted for test by test"}
    undeclared = [name for name in names if name not in known]
    if undeclared or not names:
        return 1, {"status": "failed", "new_failures": undeclared, "known_failures": [n for n in names if n in known]}
    return 0, {"status": "passed", "known_failures": names}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: known_failures.py <base64-json-names> <command>", file=sys.stderr)
        return 2
    try:
        known = set(json.loads(base64.b64decode(argv[1]).decode("utf-8")))
    except (ValueError, TypeError) as error:
        print(f"{MARKER}" + json.dumps({"status": "failed", "reason": f"invalid known failure list: {error}"}))
        return 2
    result = subprocess.run(argv[2], shell=True, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    code, verdict = decide(result.returncode, result.stdout + "\n" + result.stderr, known)
    print(MARKER + json.dumps(verdict, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
