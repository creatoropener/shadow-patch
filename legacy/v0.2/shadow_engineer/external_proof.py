"""Verification policy for immutable external Git snapshots."""
import base64
import json
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET
from .repository import canonical, sha, validate_lock, candidate


def evidence(raw):
    result = {**raw, "cases": {}, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    try:
        root = ET.fromstring(raw.get("xml", ""))
        for case in root.iter("testcase"):
            key = case.get("classname", "") + "::" + case.get("name", "")
            if key in result["cases"]: raise ValueError("Duplicate test identities")
            status = ("errors" if case.find("error") is not None else
                      "failed" if case.find("failure") is not None else
                      "skipped" if case.find("skipped") is not None else "passed")
            result["cases"][key] = status
            result[status] += 1
        if not result["cases"]: raise ValueError("No test cases")
    except (ET.ParseError, ValueError, TypeError):
        result["errors"] += 1
        result["evidence_error"] = "Missing, malformed or ambiguous JUnit evidence"
    result["green"] = (raw.get("exit_code") == 0 and result["passed"] > 0 and
                       not (result["failed"] or result["errors"] or result["skipped"]) and
                       raw.get("inputs_unchanged") is True)
    result["red"] = (raw.get("exit_code") == 1 and result["failed"] > 0 and
                     not (result["errors"] or result["skipped"]) and
                     raw.get("inputs_unchanged") is True)
    return result


def verify_external(repo, head, lock, expected_digest, runner):
    report = {"schema": 2, "run_id": str(uuid.uuid4()), "status": "blocked",
              "base_commit": lock.get("base_commit"), "candidate_commit": head,
              "lock_sha256": expected_digest, "provider": runner.name,
              "provider_metadata": runner.metadata, "stages": [],
              "human_merge_required": True, "test_provenance": lock.get("test_provenance"),
              "independence": "separate test input; author independence not attested",
              "scope": "Observed test results; no general correctness or anti-tampering guarantee"}
    try:
        base = validate_lock(repo, lock, expected_digest)
        proposed, changed, patch_hash = candidate(repo, lock["base_commit"], head, base, lock["writable"])
    except (ValueError, KeyError, TypeError) as error:
        report["reason"] = str(error)
        return report
    report.update(changed_files=changed, patch_sha256=patch_hash,
                  candidate_snapshot_sha256=sha(canonical(proposed)),
                  regression_sha256=lock["regression_sha256"], test_edits_rejected=True)
    regression = {lock["regression_path"]: {"mode": "100644", "content":
                  base64.b64encode(lock["regression"].encode()).decode()}}

    def stage(name, files, targets):
        try:
            raw = runner.run({"files": files, "targets": targets, "runtime": lock["runtime"]})
            result = evidence(raw)
        except Exception as error:
            result = evidence({"exit_code": -1, "xml": "", "inputs_unchanged": False,
                               "log": "Execution failed: " + type(error).__name__})
        report["stages"].append({"stage": name, **result})
        return result

    baseline = stage("baseline", base, lock["suite"])
    if not baseline["green"]:
        report["reason"] = "Existing baseline did not pass; no verification verdict"
        return report
    reproduce = stage("reproduce", {**base, **regression}, [lock["regression_path"]])
    if not reproduce["red"]:
        report["reason"] = "Locked regression did not establish a failing test on the base"
        return report
    repaired = stage("candidate-regression", {**proposed, **regression}, [lock["regression_path"]])
    if not repaired["green"] or repaired["cases"].keys() != reproduce["cases"].keys():
        report.update(status="rejected", reason="Candidate failed the locked regression or changed test identities")
        return report
    suite = stage("candidate-suite", proposed, lock["suite"])
    if not suite["green"] or suite["cases"].keys() != baseline["cases"].keys():
        report.update(status="rejected", reason="Candidate broke the existing suite or changed test identities")
        return report
    expected_cases = baseline["cases"].keys() | reproduce["cases"].keys()
    if len(expected_cases) != len(baseline["cases"]) + len(reproduce["cases"]):
        report["reason"] = "Baseline and regression test identities overlap"
        return report
    for name in ("combined", "fresh-replay"):
        result = stage(name, {**proposed, **regression}, lock["suite"] + [lock["regression_path"]])
        if not result["green"] or result["cases"].keys() != expected_cases:
            report.update(status="rejected", reason="Combined suite/replay failed or test identities changed")
            return report
    report.update(status="passed-checks", reason="Locked regression, existing suite and fresh replay passed")
    return report


def write_report(report, output):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    (out / "proof.json").write_text(json.dumps(report, indent=2))
    lines = ["## PatchProof verification report", "", f"**Result: {report['status']}**", "",
             f"Base commit: `{report['base_commit']}`", f"Candidate commit: `{report['candidate_commit']}`",
             f"Locked input digest: `{report['lock_sha256']}`", f"Provider: {report['provider']}", "",
             "| Gate | Outcome | Passed | Failed | Errors | Skipped |",
             "|---|---|---:|---:|---:|---:|"]
    for s in report["stages"]:
        outcome = "reproduced" if s["stage"] == "reproduce" and s["red"] else "passed" if s["green"] else "failed/blocked"
        lines.append(f"| {s['stage']} | {outcome} | {s['passed']} | {s['failed']} | {s['errors']} | {s['skipped']} |")
    lines += ["", report["reason"], "", "Test provenance: " + str(report["test_provenance"]),
              "Direct changes outside the application allowlist are blocked before execution.",
              "Test evidence is not a guarantee of correctness or security. Human review is required.",
              "This report applies only to the commits above. No PR or comment has been posted."]
    if report["provider"] == "local-fixture":
        lines += ["", "Local fixture run: no model call or Nebius VM was used."]
    (out / "VERIFICATION_REPORT.md").write_text("\n".join(lines) + "\n")
    return out
