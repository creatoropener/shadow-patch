"""Run pytest and emit exception-type evidence owned by the test runner."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


class Evidence:
    def __init__(self):
        self.assertions = []
        self.errors = []
        self.passed = 0

    def pytest_runtest_makereport(self, item, call):
        if call.excinfo is not None:
            exception = call.excinfo.value
            event = {"nodeid": item.nodeid, "phase": call.when,
                     "exception": type(exception).__module__ + "." + type(exception).__qualname__}
            if call.when == "call" and isinstance(exception, (AssertionError, pytest.fail.Exception)):
                self.assertions.append(event)
            elif not isinstance(exception, pytest.skip.Exception):
                self.errors.append(event)
        elif call.when == "call":
            self.passed += 1

    def pytest_collectreport(self, report):
        if report.failed:
            self.errors.append({"nodeid": report.nodeid, "phase": "collection"})


def main(argv):
    sys.path.insert(0, str(Path.cwd()))
    evidence = Evidence()
    code = int(pytest.main(["-q", *argv], plugins=[evidence]))
    print("PATCHPROOF_PYTEST_EVIDENCE=" + json.dumps({
        "schema": 1, "exit_code": code, "assertions": evidence.assertions,
        "errors": evidence.errors, "passed": evidence.passed,
    }, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
