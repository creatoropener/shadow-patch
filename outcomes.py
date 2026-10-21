"""rc.30: readiness summary and outcome buckets derived from a proof record.

Both functions are pure: they read the proof dictionary the engine already
writes and add two plain sections to it. Nothing here runs a model, a sandbox
or a command, so the same functions can be applied to any saved proof.json,
including the ones recorded by earlier releases.

Why this exists. Until rc.29 a run that stopped before any inference said so
only in a free-text error, and a legacy run recorded no stop reason at all.
Benchmark reports therefore could not tell "the project could not be set up"
from "the verifier never produced a usable test" from "the repair was wrong".
Those are different findings, and only the last one says anything about repair
quality.
"""
from __future__ import annotations

import re
from typing import Any

# Stages that run before the first model request. A failure in one of them is a
# readiness failure: no inference was spent and nothing about repair quality can
# be concluded from the run.
BLOCKED_STAGES = (
    "configuration", "runtime-detection", "repository-analysis",
    "runtime-preflight", "baseline", "baseline-source-check",
)

# A readiness-only run stops after these checks without a model request.
PRE_INFERENCE_STAGES = BLOCKED_STAGES + ("readiness",)

VERIFIED = "verified"
READINESS_BLOCKED = "readiness_blocked"
NEEDS_SPECIFICATION = "needs_specification"
SPEC_INVALID = "spec_invalid"
VERIFIER_INVALID = "verifier_invalid"
NO_REPRODUCTION = "no_reproduction"
REPAIR_INVALID = "repair_invalid"
REPAIR_FAILED = "repair_failed"
REPLAY_FAILED = "replay_failed"
DELIVERY_BLOCKED = "delivery_blocked"
BUDGET_EXHAUSTED = "budget_exhausted"
INFRASTRUCTURE_ERROR = "infrastructure_error"
UNCLASSIFIED = "unclassified"

BUCKETS = (
    VERIFIED, READINESS_BLOCKED, NEEDS_SPECIFICATION, SPEC_INVALID, VERIFIER_INVALID,
    NO_REPRODUCTION, REPAIR_INVALID, REPAIR_FAILED, REPLAY_FAILED, DELIVERY_BLOCKED,
    BUDGET_EXHAUSTED, INFRASTRUCTURE_ERROR, UNCLASSIFIED,
)

# What each bucket says about the repair itself. Only the last group evaluated
# a repair; every other group stopped earlier and is not evidence about it.
EVALUATED_REPAIR = frozenset({VERIFIED, REPAIR_FAILED, REPLAY_FAILED})

# stop_reason values the engine has used since rc.26, extended in rc.30 so legacy
# runs record one too. Existing values keep their meaning.
STOP_REASON_FOR_BUCKET = {
    READINESS_BLOCKED: "blocked_setup",
    NEEDS_SPECIFICATION: "needs_specification",
    SPEC_INVALID: "needs_specification",
    VERIFIER_INVALID: "verification_failed",
    NO_REPRODUCTION: "verification_failed",
    REPAIR_INVALID: "candidate_invalid",
    REPAIR_FAILED: "verification_failed",
    REPLAY_FAILED: "verification_failed",
    DELIVERY_BLOCKED: "blocked_setup",
    BUDGET_EXHAUSTED: "budget_exhausted",
    INFRASTRUCTURE_ERROR: "infrastructure_error",
}

# Each rule is (pattern on the engine's error text, readiness check, what to change).
# Messages come from this repository's own PatchProofError/RuntimeDetectionError texts,
# so the table is a convenience for the reader: an unmatched message is still reported
# verbatim as a blocker, just without a suggested change.
_HINTS: tuple[tuple[str, str, str], ...] = (
    (r"Multiple package-manager lockfiles",
     "package_manager",
     "Keep exactly one supported lockfile, or declare the tool in the packageManager field of package.json."),
    (r"Unsupported packageManager|Bun is not supported|Cannot tell which Yarn",
     "package_manager",
     "Use npm, pnpm or Yarn and declare it as name@version in package.json."),
    (r"Multiple runtime manifests",
     "runtime",
     "Set \"runtime\" in patchproof.json to choose one adapter."),
    (r"Missing manifest for selected runtime|Requested runtime",
     "runtime",
     "The runtime named in patchproof.json does not match the project files; correct it or remove it."),
    (r"is part of a workspace|workspace",
     "project_root",
     "Point \"root\" in patchproof.json at a self-contained project, or install from a single package."),
    (r"Invalid patchproof\.json|patchproof\.json accepts only",
     "configuration",
     "Fix patchproof.json: it accepts only runtime, test_directory, scope, root and known_failures."),
    (r"is not set|Missing required environment|required environment",
     "configuration",
     "Set the named secret or environment variable for this workflow."),
    (r"No candidate-editable source files",
     "source_files",
     "The project has no source file the adapter may edit; check root and scope.allowed_paths."),
    (r"Scope lists non-editable or missing source files",
     "source_files",
     "scope.allowed_paths names files that do not exist or cannot be edited; correct the list."),
    (r"Sandbox workspace setup failed",
     "sandbox_setup",
     "The sandbox could not unpack the repository; retry, then check the image and project size."),
    (r"Runtime dependency preparation failed",
     "dependency_install",
     "The frozen install failed; make the lockfile consistent with package.json and rerun."),
    (r"Runtime preflight failed",
     "sandbox_setup",
     "The sandbox image lacks a required tool; rebuild it with the prepare-image workflow and update its secret."),
    (r"Baseline command failed",
     "baseline",
     "The project's own test command fails on the base commit. Fix it, or list the failing tests under known_failures."),
    (r"Required baseline TypeScript check",
     "type_check",
     "The whole project must type-check before a repair is attempted; fix the project's compiler errors."),
    (r"requires node-typescript",
     "runtime",
     "Bounded mode supports node-typescript only; use agent-mode legacy for this runtime."),
)


def _first_line(text: str, limit: int = 600) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _hint(message: str) -> tuple[str | None, str | None]:
    for pattern, check, change in _HINTS:
        if re.search(pattern, message, re.IGNORECASE):
            return check, change
    return None, None



# Classifications that mean the generated test never ran an assertion: it was refused by a
# static gate (parser, lint, type-check) or could not be loaded. They do not count as
# reproduction attempts (rc.30) and are not evidence about the reported behavior.
STATIC_REJECTIONS = frozenset({
    "generated TypeScript regression failed syntax parsing",
    "generated JavaScript regression failed syntax parsing",
    "generated TypeScript regression failed stream contract",
    "generated TypeScript regression failed string-escape lint",
    "generated TypeScript lint tooling unavailable",
    "generated TypeScript regression failed semantic lint",
    "generated TypeScript regression failed API type-check",
    "generated test could not load a module",
})


def is_static_rejection(classification: str) -> bool:
    return classification in STATIC_REJECTIONS


def _is_static(attempt: dict[str, Any]) -> bool:
    if "static_rejection" in attempt:
        return bool(attempt["static_rejection"])
    return is_static_rejection(str(attempt.get("classification", "")))

_STAGE_CHECK = {
    "configuration": "configuration",
    "runtime-detection": "runtime",
    "repository-analysis": "source_files",
    "runtime-preflight": "sandbox_setup",
    "baseline": "baseline",
    "baseline-source-check": "type_check",
}


def summarize_readiness(proof: dict[str, Any]) -> dict[str, Any]:
    """What was established about the project before any model request, and what blocked it.

    The summary only restates what the proof already recorded. `before_inference` is true
    when the run stopped (or finished) without ever reaching a model request, which is the
    case for every failure at a stage in BLOCKED_STAGES.
    """
    stage = str(proof.get("stage") or "")
    error = str(proof.get("error") or "")
    runtime = proof.get("runtime") or {}
    baseline = proof.get("baseline") or {}
    source_check = proof.get("source_check")
    scope = proof.get("scope") or {}
    manager = runtime.get("package_manager") or {}
    failed_stage = stage if stage in BLOCKED_STAGES and error else ""

    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    if runtime.get("id"):
        add("runtime", "passed", f"{runtime['id']} ({runtime.get('test_runtime', 'unknown test runtime')})")
    elif failed_stage == "runtime-detection":
        add("runtime", "failed", _first_line(error))
    else:
        add("runtime", "skipped", "not reached")

    root = proof.get("project_root")
    if root is not None:
        add("project_root", "passed", "repository root" if root in ("", ".") else root)

    if manager.get("name"):
        notes = [str(note) for note in manager.get("notes") or []]
        version = f"@{manager['version']}" if manager.get("version") else ""
        add("package_manager", "warning" if notes else "passed",
            f"{manager['name']}{version}" + (f"; {'; '.join(notes)}" if notes else ""))

    if scope.get("status"):
        add("scope", "passed", f"{scope['status']} source scope")

    if failed_stage == "runtime-preflight":
        add("sandbox_setup", "failed", _first_line(error))
    elif runtime.get("preflight_output") is not None:
        add("sandbox_setup", "passed", "workspace unpacked, dependencies installed, toolchain present")
    else:
        add("sandbox_setup", "skipped", "not reached")

    baseline_tests = baseline.get("tests_passed") if baseline else None
    if baseline:
        passed = bool(baseline.get("existing_suite_passed"))
        detail = f"`{baseline.get('command', '')}`"
        if baseline_tests is not None:
            detail += f"; {baseline_tests} test(s) passed"
        add("baseline", "passed" if passed else "failed", detail)
    elif failed_stage == "baseline":
        add("baseline", "failed", _first_line(error))
    else:
        add("baseline", "skipped", "not reached")

    # A suite that passes because it contains no tests protects nothing. That is not a
    # blocker (a repair can still be proven against the new regression), but it must be
    # visible: "the existing tests still pass" is vacuous for such a project.
    if baseline and baseline.get("existing_suite_passed"):
        if baseline_tests == 0:
            coverage = "absent"
            add("compatibility_coverage", "warning",
                "the baseline suite ran 0 tests, so unrelated behavior is not protected by existing tests")
        elif baseline_tests is None:
            coverage = "unknown"
            add("compatibility_coverage", "warning", "the runner did not report a passed-test count")
        else:
            coverage = "present"
            add("compatibility_coverage", "passed", f"{baseline_tests} existing test(s) guard unrelated behavior")
    else:
        coverage = "unknown"

    if source_check is not None:
        status = str(source_check.get("status") or ("passed" if source_check.get("enabled") else "unavailable"))
        add("type_check", "passed" if source_check.get("enabled") else "failed", f"whole-project check: {status}")
    elif failed_stage == "baseline-source-check":
        add("type_check", "failed", _first_line(error))

    blockers: list[dict[str, str]] = []
    if failed_stage:
        check, change = _hint(error)
        blocker = {"stage": failed_stage, "check": check or _STAGE_CHECK.get(failed_stage, failed_stage),
                   "message": _first_line(error)}
        if change:
            blocker["change"] = change
        blockers.append(blocker)
        for item in checks:
            if item["check"] == blocker["check"] and item["status"] == "skipped":
                item["status"] = "failed"
                item["detail"] = blocker["message"]

    reached_inference = bool(stage) and stage not in PRE_INFERENCE_STAGES
    status = "blocked" if blockers else ("ready" if reached_inference or proof.get("verdict") == "ready" else "unknown")
    return {
        "status": status,
        "before_inference": not reached_inference,
        "checks": checks,
        "blockers": blockers,
        "warnings": [f"{c['check']}: {c['detail']}" for c in checks if c["status"] == "warning"],
        "baseline_tests": baseline_tests,
        "compatibility_coverage": coverage,
    }


def _generation_statuses(proof: dict[str, Any]) -> list[str]:
    regression = proof.get("regression_test") or {}
    return [str(item.get("status", "")) for item in regression.get("generation_attempts") or []]


_SANDBOX_API_FAILURE = re.compile(
    r"ApiStatusCodeError\(.*?status=(?:5\d\d|408|429)\b|ApiTimeoutError\(|ContreeTransportError\(", re.S)


def classify_outcome(proof: dict[str, Any]) -> dict[str, Any]:
    """One bucket per run, derived from the recorded stage and evidence.

    The buckets separate "never reached a repair" from "a repair was evaluated", so a report
    can state its repair success rate over runs that actually evaluated a repair and show
    every other run in its own column instead of folding it into a single failure count.
    """
    verdict = str(proof.get("verdict") or "")
    stage = str(proof.get("stage") or "")
    stop = str(proof.get("stop_reason") or "")
    error = str(proof.get("error") or "")
    regression = proof.get("regression_test") or {}
    attempts = regression.get("attempts") or []
    candidates = proof.get("candidates") or []
    spec = regression.get("spec") or {}

    def result(bucket: str, detail: str) -> dict[str, Any]:
        return {"bucket": bucket, "stage": stage, "detail": _first_line(detail) if detail else "",
                "evaluated_repair": bucket in EVALUATED_REPAIR}

    if verdict == VERIFIED:
        return result(VERIFIED, "repair verified and replayed")
    if verdict == "ready":
        return result(UNCLASSIFIED, "readiness check only; no repair was attempted")
    if _SANDBOX_API_FAILURE.search(error):
        # rc.39: the Sandbox API itself failed (HTTP 5xx, 408, 429, timeout). That is not a statement
        # about the repository, the test or the repair, so it is not a readiness block or a failed repair.
        return result(INFRASTRUCTURE_ERROR, error)
    if stop == "needs_specification":
        return result(SPEC_INVALID if spec.get("status") == "invalid" else NEEDS_SPECIFICATION, error)
    if stop == "budget_exhausted":
        return result(BUDGET_EXHAUSTED, error)
    if stage in BLOCKED_STAGES:
        return result(READINESS_BLOCKED, error)
    if stop == "blocked_setup":
        return result(DELIVERY_BLOCKED if stage in {"clean-replay", "completed"} else READINESS_BLOCKED, error)
    if stage in {"verifier-investigation", "verifier-generation", "verifier-reproduction"}:
        if "inference_failed" in _generation_statuses(proof) or "InferenceError" in str(proof.get("error_type") or ""):
            return result(INFRASTRUCTURE_ERROR, error)
        if spec.get("status") == "invalid" and (proof.get("verifier") or {}).get("profile_used") == "spec":
            # (After an automatic fall back the free-form verifier owns the outcome instead.)
            return result(SPEC_INVALID, error)
        # A test that never ran (syntax, lint, type-check, import) says nothing about the issue;
        # only tests that executed can fail to reproduce it.
        executed = [a for a in attempts if not _is_static(a)]
        if any(str(a.get("classification", "")).startswith("accepted assertion failure") for a in attempts):
            # Reproduced, but a later check (ordinary CI discovery) refused the frozen test.
            return result(READINESS_BLOCKED, error)
        if executed:
            return result(NO_REPRODUCTION, error)
        return result(VERIFIER_INVALID, error)
    if stage == "candidate-evaluation":
        if any(c.get("stage") == "regression" for c in candidates):
            return result(REPAIR_FAILED, error)
        return result(REPAIR_INVALID, error)
    if stage == "clean-replay":
        return result(REPLAY_FAILED, error)
    return result(UNCLASSIFIED, error)


def legacy_stop_reason(outcome: dict[str, Any]) -> str | None:
    """The stop_reason a run should carry for this outcome (None for a verified run)."""
    return STOP_REASON_FOR_BUCKET.get(outcome.get("bucket", ""))
