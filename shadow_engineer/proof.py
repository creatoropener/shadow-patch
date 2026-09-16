"""Verification policy independent of execution providers."""
from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from typing import Protocol


def digest(files: dict[str, str]) -> str:
    return sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


@dataclass
class Result:
    exit_code: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    log: str = ""
    execution_id: str = ""

    @property
    def green(self):
        return self.exit_code == 0 and self.passed > 0 and not (
            self.failed or self.errors or self.skipped)

    @property
    def red(self):
        return self.exit_code == 1 and self.failed > 0 and self.errors == 0


class Runner(Protocol):
    name: str
    def run(self, files: dict[str, str], target: str) -> Result: ...


def verify(runner: Runner, source: dict[str, str], regression: str,
           candidates: list[dict[str, str]]) -> dict:
    """Only application-source replacement is permitted in this narrow MVP."""
    report = {"schema": 1, "provider": runner.name, "status": "rejected",
              "base_sha256": digest(source), "regression_sha256": digest({"test": regression}),
              "stages": [], "candidates": [], "winner": None,
              "human_merge_required": True,
              "scope": "Observed pytest evidence; not a correctness or security proof."}

    def record(stage, files, target):
        result = runner.run(files, target)
        report["stages"].append({"stage": stage, **asdict(result)})
        return result

    if not record("baseline", source, "tests").green:
        report["reason"] = "Baseline suite must pass before repair."
        return report
    tested = {**source, "tests/test_regression.py": regression}
    if not record("reproduce", tested, "tests/test_regression.py").red:
        report["reason"] = "Regression must fail as a test failure on original code."
        return report
    for index, patch in enumerate(candidates[:3], 1):
        entry = {"candidate": index, "patch_sha256": digest(patch), "accepted": False}
        report["candidates"].append(entry)
        if not patch or any(p not in source or not p.startswith("app/") or
                            not p.endswith(".py") for p in patch):
            entry["reason"] = "Only existing app/*.py source files may change."
            continue
        files = {**tested, **patch}
        red_green = record(f"candidate-{index}-regression", files, "tests/test_regression.py")
        suite = record(f"candidate-{index}-suite", files, "tests")
        if not (red_green.green and suite.green):
            entry["reason"] = "Candidate did not pass both verification gates."
            continue
        # Runner contract: each invocation starts from fresh original environment.
        replay = record(f"candidate-{index}-replay", files, "tests")
        if not replay.green or replay.passed != suite.passed:
            entry["reason"] = "Fresh replay failed or test count changed."
            continue
        entry["accepted"] = True
        report.update(status="verified", winner=index, patch=patch,
                      verified_files_sha256=digest(files))
        break
    if report["winner"] is None:
        report["reason"] = "No candidate passed all gates."
    return report
