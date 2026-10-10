"""PatchProof benchmark harness (standard library only).

Subcommands, in the order the Benchmark workflow uses them:

  plan     turn the manifest plus the dispatch inputs into a job matrix
  run      run one engine on one case once, and save what happened
  oracle   judge every distinct candidate diff of a case with a reference test
  report   classify every trial and write results.md / results.json

The engine's own verdict is not treated as ground truth. VERIFIED only means a
candidate passed the verifier's own test, and a generated test can be wrong in
either direction. Each trial is therefore also judged by something the engine
never saw: a reference test (oracle) or a recorded human label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scope_policy import validate_scope
from runtimes import _node_assertion_failure, pytest_evidence
MANIFEST_PATH = ROOT / "bench" / "manifest.json"
LABELS_DIR = ROOT / "bench" / "labels"
SPLITS = ("dev", "heldout")
MAX_JOBS = 250          # GitHub allows 256 matrix jobs per workflow run
MAX_TRIALS = 5
CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ENGINE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,100}$")
PLACEHOLDER = re.compile(r"TODO|<<|>>")
RUNTIME_ID = re.compile(r"^[a-z][a-z0-9-]*$")
# Keys the engine itself accepts in patchproof.json (runtimes.detect_runtime).
CONFIG_KEYS = frozenset({"runtime", "test_directory", "scope"})

# Trial outcomes. Only `infra` is excluded from rates, and it is always shown.
INFRA = "infra"
VERIFIER_FAILED = "verifier_failed"
TRUE_ACCEPT = "true_accept"
FALSE_ACCEPT = "false_accept"
VERIFIED_UNLABELED = "verified_unlabeled"
FALSE_REJECT = "false_reject"
TRUE_REJECT = "true_reject"
REJECTED_UNLABELED = "rejected_unlabeled"
BUDGET_STOP = "budget_exhausted"
NEEDS_SPECIFICATION = "needs_specification"
OUTCOMES = (TRUE_ACCEPT, FALSE_ACCEPT, VERIFIED_UNLABELED, FALSE_REJECT,
            TRUE_REJECT, REJECTED_UNLABELED, VERIFIER_FAILED, BUDGET_STOP, NEEDS_SPECIFICATION, INFRA)
VERIFIER_STAGES = {"verifier-investigation", "verifier-generation", "verifier-reproduction"}
AGENT_SETTINGS = ("PATCHPROOF_AGENT_CANDIDATES", "PATCHPROOF_MAX_AGENT_STEPS", "PATCHPROOF_MAX_MODEL_REQUESTS",
                  "PATCHPROOF_MAX_TOTAL_TOKENS", "PATCHPROOF_MAX_SANDBOX_COMMANDS", "PATCHPROOF_MAX_RUN_SECONDS",
                  "PATCHPROOF_MAX_COST_USD", "PATCHPROOF_INPUT_USD_PER_MILLION", "PATCHPROOF_OUTPUT_USD_PER_MILLION")


class BenchError(RuntimeError):
    """A manifest, input or result problem the operator can fix."""


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchError(f"Cannot read manifest {path}: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise BenchError("Manifest must be a JSON object with \"schema\": 1.")
    if not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise BenchError("Manifest needs a non-empty \"cases\" list.")
    return manifest


def manifest_sha256(path: Path = MANIFEST_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")):
        return False
    parts = re.split(r"[\\/]", value)
    return ".." not in parts and ":" not in parts[0]


def config_problems(config: Any) -> list[str]:
    """Problems with a case's `patchproof_config`, phrased without the case name."""
    if not isinstance(config, dict):
        return ["patchproof_config must be an object"]
    out: list[str] = []
    extra = sorted(str(key) for key in set(config) - CONFIG_KEYS)
    if extra:
        out.append("patchproof_config accepts only runtime, test_directory and scope, not " + ", ".join(extra))
    try:
        validate_scope(config.get("scope"))
    except ValueError as error:
        out.append(str(error))
    if "runtime" in config and not (isinstance(config["runtime"], str) and RUNTIME_ID.match(config["runtime"])):
        out.append("patchproof_config.runtime must be an adapter id such as node-typescript")
    if "test_directory" in config:
        directory = config["test_directory"]
        if not (isinstance(directory, str) and (directory == "" or _safe_relative(directory))):
            out.append("patchproof_config.test_directory must be a relative path without ..")
    return out


def case_problems(case: Any, root: Path = ROOT, *, ready: bool) -> list[str]:
    """Problems with one case. `ready` also rejects unfinished placeholders."""
    if not isinstance(case, dict):
        return ["case is not an object"]
    name = case.get("id", "?")
    out: list[str] = []

    def bad(message: str) -> None:
        out.append(f"{name}: {message}")

    if not isinstance(case.get("id"), str) or not CASE_ID.match(case["id"]):
        bad("id must be lowercase letters, digits and dashes")
    if case.get("split") not in SPLITS:
        bad(f"split must be one of {', '.join(SPLITS)}")
    if not isinstance(case.get("repo"), str) or not REPO_NAME.match(case["repo"]):
        bad("repo must look like owner/name")
    base = case.get("base_commit")
    if not isinstance(base, str):
        bad("base_commit is missing")
    elif ready and not FULL_SHA.match(base):
        bad("base_commit must be the full 40-character SHA of an UNFIXED commit")
    issue = case.get("issue")
    if not isinstance(issue, dict):
        bad("issue is missing")
    else:
        number = issue.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            bad("issue.number must be a positive integer")
        title = issue.get("title")
        if not isinstance(title, str) or not title.strip():
            bad("issue.title is missing")
        elif ready and PLACEHOLDER.search(title):
            bad("issue.title still contains a placeholder")
        body_file = issue.get("body_file")
        if not _safe_relative(body_file):
            bad("issue.body_file must be a relative path inside the repository")
        else:
            body_path = root / body_file
            if not body_path.is_file():
                bad(f"issue body file {body_file} does not exist")
            elif ready:
                text = body_path.read_text(encoding="utf-8")
                if not text.strip():
                    bad(f"issue body file {body_file} is empty")
                elif PLACEHOLDER.search(text):
                    bad(f"issue body file {body_file} still contains a placeholder")
    if case.get("patchproof_config") is not None:
        for message in config_problems(case["patchproof_config"]):
            bad(message)
    oracle = case.get("oracle")
    if oracle is not None:
        if not isinstance(oracle, dict):
            bad("oracle must be an object or null")
        else:
            for key in ("test_file", "dest", "command", "reference_patch"):
                if not isinstance(oracle.get(key), str) or not oracle[key].strip():
                    bad(f"oracle.{key} is missing")
            for key in ("test_file", "dest", "reference_patch"):
                if isinstance(oracle.get(key), str) and not _safe_relative(oracle[key]):
                    bad(f"oracle.{key} must be a relative path without ..")
            test_file = oracle.get("test_file")
            if _safe_relative(test_file) and not (root / test_file).is_file():
                bad(f"oracle test file {test_file} does not exist")
            reference = oracle.get("reference_patch")
            if _safe_relative(reference) and not (root / reference).is_file():
                bad(f"oracle reference_patch {reference} does not exist")
            if oracle.get("failure_evidence") not in {"node-test", "pytest"}:
                bad("oracle.failure_evidence must be node-test or pytest (structured runner evidence)")
    return out


def validate_manifest(manifest: dict[str, Any], root: Path = ROOT, *,
                      ready_ids: set[str] | None = None) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for case in manifest["cases"]:
        case_id = case.get("id") if isinstance(case, dict) else None
        if case_id in seen:
            problems.append(f"{case_id}: duplicate id")
        seen.add(case_id)
        problems += case_problems(case, root, ready=bool(ready_ids and case_id in ready_ids))
    return problems


def select_cases(manifest: dict[str, Any], split: str, ids: list[str]) -> list[dict[str, Any]]:
    if split not in ("all", *SPLITS):
        raise BenchError(f"split must be all, dev or heldout, not {split!r}.")
    known = {case["id"] for case in manifest["cases"]}
    unknown = [item for item in ids if item not in known]
    if unknown:
        raise BenchError(f"Unknown case id(s): {', '.join(unknown)}.")
    chosen = [case for case in manifest["cases"]
              if (split == "all" or case["split"] == split) and (not ids or case["id"] in ids)]
    if not chosen:
        raise BenchError("No cases match the split and case filters.")
    return chosen


def read_body(case: dict[str, Any], root: Path = ROOT) -> str:
    """The issue body exactly as stored: bytes are decoded, never re-normalized."""
    return (root / case["issue"]["body_file"]).read_bytes().decode("utf-8")


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "x"


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

def parse_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def build_plan(manifest: dict[str, Any], *, engines: list[str], trials: int, split: str,
               ids: list[str], root: Path = ROOT) -> dict[str, Any]:
    if not engines:
        raise BenchError("Give at least one engine tag, for example v0.6.0-rc.20.")
    for engine in engines:
        if not ENGINE_REF.match(engine) or ".." in engine:
            raise BenchError(f"Engine ref {engine!r} is not a plain tag or branch name.")
    if len(set(engines)) != len(engines):
        raise BenchError("Engine list contains a duplicate.")
    if not 1 <= trials <= MAX_TRIALS:
        raise BenchError(f"trials must be between 1 and {MAX_TRIALS}.")
    chosen = select_cases(manifest, split, ids)
    if any(c["split"] == "heldout" for c in chosen) and manifest.get("protocol_status", "frozen") != "frozen":
        raise BenchError("Unseen protocol is not frozen; select dev cases until independent cases and oracles are validated.")
    problems = validate_manifest(manifest, root, ready_ids={case["id"] for case in chosen})
    if problems:
        raise BenchError("Manifest is not ready to run:\n- " + "\n- ".join(problems))
    include = []
    # Trial-major, then case, then engine: engines being compared run side by
    # side in time, so backend drift does not favour whichever ran first.
    for trial in range(1, trials + 1):
        for case in chosen:
            for engine in engines:
                include.append({
                    "engine": engine, "engine_slug": slug(engine), "case": case["id"],
                    "trial": trial, "repo": case["repo"], "base_commit": case["base_commit"],
                    "split": case["split"],
                })
    if len(include) > MAX_JOBS:
        raise BenchError(f"{len(include)} jobs exceeds the {MAX_JOBS} job limit; lower trials or cases.")
    oracle_cases = [
        {"case": case["id"], "repo": case["repo"], "base_commit": case["base_commit"]}
        for case in chosen if case.get("oracle")
    ]
    return {"matrix": {"include": include}, "oracle_cases": {"include": oracle_cases},
            "has_oracle": bool(oracle_cases), "jobs": len(include)}


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #

def apply_patchproof_config(subject: Path, case: dict[str, Any]) -> dict[str, Any] | None:
    """Replace the checkout's patchproof.json with the case's `patchproof_config`.

    The pinned commit's own file is a historical artifact: file-sharing-app at
    4f8b912 pins `node-package`, an adapter that cannot edit its TypeScript
    sources, so no repair could ever be evaluated whichever engine ran. The
    manifest says what to run instead. The file is replaced, never merged, so the
    result is exactly the manifest's object. Returns what was applied and the hash
    of the file it replaced (None if there was none), or None for an ordinary case.
    """
    if case.get("patchproof_config") is None:
        return None
    problems = config_problems(case["patchproof_config"])
    if problems:
        raise BenchError(f"{case.get('id', '?')}: " + "; ".join(problems))
    target = subject / "patchproof.json"
    replaced = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
    target.write_text(json.dumps(case["patchproof_config"], indent=2) + "\n", encoding="utf-8")
    return {"patchproof_config": case["patchproof_config"], "replaced_patchproof_json_sha256": replaced}


def run_trial(*, case: dict[str, Any], trial: int, engine_ref: str, engine_dir: Path,
              subject: Path, out: Path, timeout_seconds: float = 75 * 60,
              root: Path = ROOT, environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Run one engine once on one case. Engine failure is data, not an error."""
    out.mkdir(parents=True, exist_ok=True)
    if (out / "meta.json").exists():
        raise BenchError("Trial output already contains a run; choose a new output directory.")
    run_id = uuid.uuid4().hex
    # A failed process cannot inherit evidence from a previous invocation.
    for name in ("proof.json", "verification-report.md"):
        prior = subject / name
        if prior.exists():
            (out / "previous").mkdir(exist_ok=True)
            shutil.copyfile(prior, out / "previous" / name)
            prior.unlink()
        (out / name).unlink(missing_ok=True)
    issue = case["issue"]
    body = read_body(case, root)
    override = apply_patchproof_config(subject, case)
    env = dict(os.environ if environ is None else environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env["PATCHPROOF_RUN_ID"] = run_id
    command = [sys.executable, str(engine_dir / "proof.py"), "--repo", str(subject),
               f"--issue-number={issue['number']}", f"--issue-title={issue['title']}",
               f"--issue-body={body}"]   # `=` form: a body starting with "-" is still a value
    started = time.monotonic()
    timed_out = False
    try:
        finished = subprocess.run(command, env=env, capture_output=True, text=True,
                                  timeout=timeout_seconds)
        exit_code, stdout, stderr = finished.returncode, finished.stdout, finished.stderr
    except subprocess.TimeoutExpired as error:
        timed_out, exit_code = True, None
        stdout = (error.stdout or b"").decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = (error.stderr or b"").decode("utf-8", "replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
    elapsed = round(time.monotonic() - started, 1)
    (out / "engine-stdout.txt").write_text(stdout, encoding="utf-8")
    (out / "engine-stderr.txt").write_text(stderr, encoding="utf-8")
    for name in ("proof.json", "verification-report.md"):
        if (subject / name).is_file():
            shutil.copyfile(subject / name, out / name)
    meta = {
        "evidence_version": 2, "run_id": run_id, "diff_identity": "sha256-utf8-exact-v1",
        "case": case["id"], "split": case["split"], "trial": trial,
        "engine_ref": engine_ref, "repo": case["repo"], "base_commit": case["base_commit"],
        "issue_number": issue["number"], "issue_title": issue["title"],
        "issue_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "manifest_sha256": manifest_sha256(root / "bench" / "manifest.json"),
        "model": env.get("NEBIUS_MODEL", ""), "max_tokens": env.get("NEBIUS_MAX_TOKENS", ""),
        "agent_mode": env.get("PATCHPROOF_AGENT_MODE", "legacy"),
        "agent_settings": {key: env[key] for key in AGENT_SETTINGS if env.get(key)},
        "exit_code": exit_code, "timed_out": timed_out, "elapsed_seconds": elapsed,
        "has_proof": (out / "proof.json").is_file(),
        "proof_sha256": hashlib.sha256((out / "proof.json").read_bytes()).hexdigest() if (out / "proof.json").is_file() else None,
        "protocol_id": load_manifest(root / "bench/manifest.json").get("protocol_id", "legacy"),
        "case_sha256": case_identity(case, root),
    }
    (out / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(root / "bench/manifest.json", out / "manifest.json")
    (out / "issue.md").write_bytes(body.encode("utf-8"))
    resolved = subprocess.run(["git", "-C", str(engine_dir), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=False)
    meta["engine_commit"] = resolved.stdout.strip() if resolved.returncode == 0 else None
    if override:
        meta.update(override)
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


# --------------------------------------------------------------------------- #
# Diffs, labels, oracle
# --------------------------------------------------------------------------- #

def diff_hash(diff: str) -> str:
    """Full SHA-256 of exact UTF-8 patch bytes, including whitespace and endings."""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def case_identity(case: dict, root: Path) -> str:
    snapshot = {key: case.get(key) for key in ("id", "repo", "base_commit", "issue", "patchproof_config", "oracle")}
    snapshot["issue_body_sha256"] = hashlib.sha256(read_body(case, root).encode("utf-8")).hexdigest()
    oracle = case.get("oracle") or {}
    for key in ("test_file", "reference_patch"):
        if oracle.get(key) and (root / oracle[key]).is_file():
            snapshot[key + "_sha256"] = hashlib.sha256((root / oracle[key]).read_bytes()).hexdigest()
    return diff_hash(json.dumps(snapshot, sort_keys=True))


def split_diff(diff: str) -> list[tuple[str, str]]:
    """Split the engine's combined difflib output into (path, patch) sections."""
    sections: list[tuple[str, list[str]]] = []
    lines = diff.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
            sections.append((line[4:].split("\t")[0].strip(), []))
        if sections:
            sections[-1][1].append(line)
    return [(path, "".join(body)) for path, body in sections]


def apply_diff(checkout: Path, diff: str) -> tuple[bool, str]:
    sections = split_diff(diff)
    if not sections:
        return False, "no file sections found in the diff"
    for path, patch in sections:
        if not _safe_relative(path):
            return False, f"unsafe path in diff: {path!r}"
        result = subprocess.run(
            ["patch", "-p0", "--batch", "--forward", "-s", "--no-backup-if-mismatch", path],
            cwd=checkout, input=patch, capture_output=True, text=True)
        if result.returncode != 0:
            return False, (result.stdout + result.stderr).strip()[-400:] or "patch failed"
    return True, ""


def reset_checkout(checkout: Path) -> None:
    subprocess.run(["git", "checkout", "-q", "--", "."], cwd=checkout, check=False)
    subprocess.run(["git", "clean", "-fdq", "-e", "node_modules", "-e", ".venv"],
                   cwd=checkout, check=False)


def _shell(command: str, cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        done = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout)
        return done.returncode, (done.stdout + done.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


def evaluate_diff(checkout: Path, oracle: dict[str, Any], diff: str, *,
                  root: Path = ROOT) -> dict[str, Any]:
    """Apply one candidate diff to a clean checkout and run the reference test."""
    timeout = int(oracle.get("timeout_seconds", 300))
    reset_checkout(checkout)
    try:
        applied, message = apply_diff(checkout, diff)
        if not applied:
            return {"passed": None, "detail": f"diff did not apply: {message}"}
        destination = checkout / oracle["dest"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / oracle["test_file"], destination)
        code, output = _shell(oracle["command"], checkout, timeout)
        return {"passed": oracle_passed(oracle, code, output), "exit_code": code, "detail": output.strip()[-2000:]}
    finally:
        reset_checkout(checkout)


def collect_results(results_dir: Path) -> list[dict[str, Any]]:
    """Every downloaded trial: meta.json plus proof.json (or None)."""
    trials = []
    for meta_path in sorted(results_dir.rglob("meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        proof_path = meta_path.parent / "proof.json"
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.is_file() else None
        except (ValueError, OSError):
            proof = None
            meta["evidence_error"] = "proof.json is unreadable"
        if proof is not None and not isinstance(proof, dict):
            proof = None
            meta["evidence_error"] = "proof.json is not an object"
        if meta.get("evidence_version") == 2 and proof is not None:
            actual = hashlib.sha256(proof_path.read_bytes()).hexdigest()
            if actual != meta.get("proof_sha256"):
                meta["evidence_error"] = "proof digest does not match this trial"
            if proof.get("run_id") is not None and proof["run_id"] != meta.get("run_id"):
                meta["evidence_error"] = "proof run_id does not match this trial"
            if meta.get("agent_mode", "legacy") != proof.get("agent_mode", "legacy"):
                meta["evidence_error"] = "engine did not run the requested execution profile"
        trials.append({"meta": meta, "proof": proof, "dir": str(meta_path.parent)})
    return trials


def candidate_diffs(proof: dict[str, Any] | None) -> list[tuple[int | None, str]]:
    if not proof:
        return []
    return [(c.get("candidate"), c["diff"]) for c in proof.get("candidates", [])
            if isinstance(c.get("diff"), str) and c["diff"].strip()]


def run_oracle(case: dict[str, Any], results_dir: Path, checkout: Path, *,
               root: Path = ROOT) -> dict[str, Any]:
    oracle = case["oracle"]
    diffs: dict[str, str] = {}
    for trial in collect_results(results_dir):
        if trial["meta"].get("case") == case["id"]:
            for _, diff in candidate_diffs(trial["proof"]):
                diffs.setdefault(diff_hash(diff), diff)
    result: dict[str, Any] = {"case": case["id"], "valid": True, "diffs": {}}
    result["case_sha256"] = case_identity(case, root)
    reference = oracle.get("reference_patch")
    if (not _safe_relative(reference) or not (root / reference).is_file()
            or oracle.get("failure_evidence") not in {"node-test", "pytest"}):
        return {**result, "valid": False, "reason": "oracle needs a reference_patch and structured failure_evidence"}
    timeout = int(oracle.get("timeout_seconds", 300))
    if oracle.get("setup"):
        code, output = _shell(oracle["setup"], checkout, int(oracle.get("setup_timeout_seconds", 900)))
        if code != 0:
            return {**result, "valid": False, "reason": "oracle setup failed: " + output.strip()[-300:]}
    # An oracle that already passes on the unfixed code judges nothing.
    reset_checkout(checkout)
    destination = checkout / oracle["dest"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / oracle["test_file"], destination)
    code, output = _shell(oracle["command"], checkout, timeout)
    reset_checkout(checkout)
    if code == 0:
        return {**result, "valid": False,
                "reason": "the reference test passes on the unfixed base commit, so it cannot tell fixes apart"}
    if not oracle_assertion(oracle, code, output):
        return {**result, "valid": False, "reason": "unfixed base did not produce a recognized assertion failure",
                "base_output": output[-2000:]}
    result["base_output"] = output.strip()[-300:]
    reference_result = evaluate_diff(checkout, oracle, (root / reference).read_bytes().decode("utf-8"), root=root)
    result["reference"] = reference_result
    if reference_result["passed"] is not True:
        return {**result, "valid": False, "reason": "known-correct reference repair did not pass the oracle"}
    for digest, diff in sorted(diffs.items()):
        result["diffs"][digest] = evaluate_diff(checkout, oracle, diff, root=root)
    return result


def oracle_assertion(oracle: dict, code: int, output: str) -> bool:
    if code != 1:
        return False
    if oracle.get("failure_evidence") == "node-test":
        return _node_assertion_failure(output)
    data = pytest_evidence(output)
    return bool(data and data["assertions"] and not data["errors"] and data.get("exit_code") == 1)


def oracle_passed(oracle: dict, code: int, output: str) -> bool:
    if code != 0:
        return False
    if oracle.get("failure_evidence") == "node-test":
        counts = re.findall(r"^# pass\s+(\d+)\s*$", output, re.MULTILINE)
        return bool(counts and int(counts[-1]) > 0)
    data = pytest_evidence(output)
    return bool(data and data.get("exit_code") == 0 and data.get("passed", 0) > 0
                and not data["assertions"] and not data["errors"])


def load_labels(case_id: str, labels_dir: Path = LABELS_DIR) -> dict[str, dict[str, Any]]:
    path = labels_dir / f"{case_id}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BenchError(f"{path} must be a JSON object keyed by diff hash.")
    for digest, item in data.items():
        if not isinstance(item, dict) or not isinstance(item.get("correct"), bool):
            raise BenchError(f"{path}: label {digest} needs a boolean \"correct\".")
    return data


def make_judge(case_id: str, oracle_result: dict[str, Any] | None,
               labels: dict[str, dict[str, Any]]) -> Callable[[str], tuple[bool | None, str]]:
    """digest -> (correct?, source). The oracle wins; a manual label fills gaps."""
    def judge(digest: str) -> tuple[bool | None, str]:
        if oracle_result and oracle_result.get("valid"):
            verdict = (oracle_result.get("diffs") or {}).get(digest)
            if verdict and verdict.get("passed") is not None:
                return verdict["passed"], "oracle"
        label = labels.get(digest)
        if label is not None:
            return label["correct"], "label"
        return None, "none"
    return judge


def trial_judge(meta: dict, oracle_results: dict, labels_dir: Path):
    oracle = oracle_results.get(meta["case"])
    if meta.get("evidence_version") == 2 and oracle and oracle.get("case_sha256") != meta.get("case_sha256"):
        oracle = None
    labels = load_labels(meta["case"], labels_dir)
    if meta.get("evidence_version") == 2:
        labels = {digest: item for digest, item in labels.items()
                  if item.get("case_sha256") == meta.get("case_sha256")}
    return make_judge(meta["case"], oracle, labels)


# --------------------------------------------------------------------------- #
# Classification and statistics
# --------------------------------------------------------------------------- #

def classify_trial(meta: dict[str, Any], proof: dict[str, Any] | None,
                   judge: Callable[[str], tuple[bool | None, str]]) -> tuple[str, str]:
    """(outcome, reason) for one trial. Never guesses: unknown stays unlabeled."""
    if meta.get("timed_out"):
        return INFRA, "engine hit the time limit"
    if meta.get("evidence_error"):
        return INFRA, meta["evidence_error"]
    if proof is None:
        return INFRA, "no proof.json was produced"
    verdict = proof.get("verdict")
    stage = str(proof.get("stage") or "")
    error = str(proof.get("error") or "")
    if verdict != "verified" and proof.get("stop_reason") in {BUDGET_STOP, NEEDS_SPECIFICATION}:
        return proof["stop_reason"], f"{proof['stop_reason']} at {stage}: {error[:140]}"
    if verdict == "blocked":
        return INFRA, f"blocked at {stage}: {error[:140]}"
    if verdict == "rejected" and error.startswith("Inference "):
        return INFRA, f"inference failure: {error[:140]}"
    candidates = proof.get("candidates") or []
    if verdict == "verified":
        if meta.get("exit_code", None if meta.get("evidence_version") == 2 else 0) != 0:
            return INFRA, "verified proof conflicts with unsuccessful engine exit"
        winner = (proof.get("winner") or {}).get("candidate")
        chosen = next((c for c in candidates if c.get("candidate") == winner), None)
        if not chosen or not chosen.get("diff"):
            return INFRA, "verified verdict without a winner diff"
        correct, source = judge(diff_hash(chosen["diff"]))
        if correct is True:
            return TRUE_ACCEPT, f"winner {winner} correct ({source})"
        if correct is False:
            return FALSE_ACCEPT, f"winner {winner} incorrect ({source})"
        return VERIFIED_UNLABELED, f"winner {winner} not yet judged"
    if verdict != "rejected":
        return INFRA, f"unexpected verdict {verdict!r}"
    evaluated = [c for c in candidates if "image" in c]
    if stage in VERIFIER_STAGES or (not evaluated and stage not in {"candidate-evaluation", "clean-replay"}):
        return VERIFIER_FAILED, f"stopped at {stage}: {error[:140]}"
    verdicts = [(c.get("candidate"), judge(diff_hash(c["diff"]))[0])
                for c in candidates if isinstance(c.get("diff"), str) and c["diff"].strip()]
    correct_ones = [number for number, ok in verdicts if ok is True]
    if correct_ones:
        return FALSE_REJECT, f"candidate(s) {correct_ones} were correct but the run was rejected"
    if not verdicts:
        return TRUE_REJECT, "no candidate produced a repair"
    if all(ok is False for _, ok in verdicts):
        return TRUE_REJECT, "every candidate was incorrect"
    return REJECTED_UNLABELED, "some candidates not yet judged"


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {name: 0 for name in OUTCOMES}
    for row in rows:
        counts[row["outcome"]] += 1
    total = len(rows)
    effective = total - counts[INFRA]
    success = counts[TRUE_ACCEPT]
    return {
        "trials": total, "infra": counts[INFRA], "effective": effective, "counts": counts,
        "operational_success_rate": success / total if total else None,
        "distinct_cases": len({r.get("case") for r in rows if r.get("case")}),
        "end_to_end_success": success,
        "end_to_end_upper": success + counts[VERIFIED_UNLABELED],
        "end_to_end_ci": wilson(success, effective),
        "verifier_failure_rate": (counts[VERIFIER_FAILED] / effective) if effective else None,
    }


def build_rows(trials: list[dict[str, Any]], manifest: dict[str, Any],
               oracle_results: dict[str, dict[str, Any]], labels_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for trial in trials:
        meta, proof = trial["meta"], trial["proof"]
        case_id = meta["case"]
        outcome, reason = classify_trial(meta, proof, trial_judge(meta, oracle_results, labels_dir))
        rows.append({
            "engine": meta["engine_ref"], "app_version": (proof or {}).get("app_version", ""),
            "case": case_id, "split": meta.get("split", "unknown"),
            "protocol_id": meta.get("protocol_id", "legacy:" + meta.get("manifest_sha256", "unknown")),
            "trial": meta["trial"], "outcome": outcome, "reason": reason,
            "stage": (proof or {}).get("stage", ""), "verdict": (proof or {}).get("verdict", ""),
            "elapsed_seconds": meta.get("elapsed_seconds"),
            "verifier_generations": len(((proof or {}).get("regression_test") or {}).get("generation_attempts") or []),
            "winner": ((proof or {}).get("winner") or {}).get("candidate"),
            "runtime_override": meta.get("patchproof_config"),
            "agent_mode": (proof or {}).get("agent_mode", "legacy"),
            "stop_reason": (proof or {}).get("stop_reason"),
            "budget": (proof or {}).get("budget"),
        })
    rows.sort(key=lambda r: (r["engine"], r["split"], r["case"], r["trial"]))
    return rows


def labels_needed(trials: list[dict[str, Any]], manifest: dict[str, Any],
                  oracle_results: dict[str, dict[str, Any]], labels_dir: Path) -> list[dict[str, Any]]:
    """Distinct candidate diffs that nothing has judged yet, with where they appeared."""
    pending: dict[tuple[str, str], dict[str, Any]] = {}
    for trial in trials:
        meta = trial["meta"]
        judge = trial_judge(meta, oracle_results, labels_dir)
        for number, diff in candidate_diffs(trial["proof"]):
            digest = diff_hash(diff)
            if judge(digest)[0] is None:
                entry = pending.setdefault((meta["case"], digest), {
                    "case": meta["case"], "case_sha256": meta.get("case_sha256"),
                    "hash": digest, "diff": diff, "seen": []})
                entry["seen"].append(f"{meta['engine_ref']} t{meta['trial']} c{number}")
    return sorted(pending.values(), key=lambda e: (e["case"], e["hash"]))


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render_markdown(rows: list[dict[str, Any]], needed: list[dict[str, Any]], *,
                    manifest: dict[str, Any], meta_summary: dict[str, Any]) -> str:
    out = ["# PatchProof benchmark", ""]
    out.append(f"- Manifest sha256: `{meta_summary['manifest_sha256'][:16]}`; "
               f"models seen: {', '.join(meta_summary['models']) or 'unknown'}")
    out.append(f"- Engines: {', '.join(meta_summary['engines'])}; trials recorded: {len(rows)}")
    out.append(f"- Protocol: `{meta_summary.get('protocol_id', 'legacy')}`. Split membership comes from each trial snapshot.")
    out.append("- Execution profiles: " + ", ".join(sorted({f"{row['engine']}={row.get('agent_mode', 'legacy')}" for row in rows})) + ".")
    operational = summarize(rows)
    out.append(f"- Operational success (all attempts, including infrastructure failures): {operational['end_to_end_success']}/{operational['trials']}.")
    out.append("")
    out.append("## Summary")
    out.append("")
    out.append("| Engine | Split | Trials | Infra (excluded) | Budget stops | Needs spec | Verifier failed | Rejected, no repair | "
               "False reject | False accept | Verified, unjudged | Correct and accepted | 95% interval |")
    out.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["engine"], row["split"]), []).append(row)
        groups.setdefault((row["engine"], "all"), []).append(row)
    for (engine, split), members in sorted(groups.items()):
        s = summarize(members)
        c = s["counts"]
        interval = s["end_to_end_ci"]
        span = f"{pct(interval[0])}–{pct(interval[1])}" if interval else "n/a"
        upper = f" (up to {s['end_to_end_upper']})" if c[VERIFIED_UNLABELED] else ""
        out.append(f"| {engine} | {split} | {s['trials']} | {s['infra']} | {c[BUDGET_STOP]} | {c[NEEDS_SPECIFICATION]} | {c[VERIFIER_FAILED]} | "
                   f"{c[TRUE_REJECT]} | {c[FALSE_REJECT]} | {c[FALSE_ACCEPT]} | {c[VERIFIED_UNLABELED]} | "
                   f"{c[TRUE_ACCEPT]}/{s['effective']}{upper} | {span} |")
    out += ["", "*Correct and accepted* = the engine said VERIFIED and the winning repair was judged correct "
                "by something the engine never saw. *False reject* = rejected although a candidate was correct. "
                "*Verifier failed* = no repair was ever evaluated because the generated test was never accepted. "
                "Budget and specification stops remain in the denominator. "
                "Rows for `all` combine dev and heldout; report heldout on its own.", ""]
    out.append("## Every trial")
    out.append("")
    out.append("| Engine | Case | Split | Trial | Outcome | Stage | Verifier tries | Seconds | Note |")
    out.append("| --- | --- | --- | ---: | --- | --- | ---: | ---: | --- |")
    for row in rows:
        out.append(f"| {row['engine']} | {row['case']} | {row['split']} | {row['trial']} | {row['outcome']} | "
                   f"{row['stage']} | {row['verifier_generations']} | {row['elapsed_seconds']} | "
                   f"{row['reason'].replace('|', '/')} |")
    warnings = []
    infra = sum(1 for r in rows if r["outcome"] == INFRA)
    if infra:
        warnings.append(f"{infra} trial(s) were infrastructure failures and are excluded from the rates. "
                        "Re-run them before quoting numbers.")
    unjudged = sum(1 for r in rows if r["outcome"] in (VERIFIED_UNLABELED, REJECTED_UNLABELED))
    if unjudged:
        warnings.append(f"{unjudged} trial(s) have an outcome that depends on an unjudged repair, so they are "
                        "not counted as successes.")
    if needed:
        warnings.append(f"{len(needed)} distinct candidate diff(s) have no oracle result or label yet; "
                        "see labels-needed.md.")
    overridden: dict[str, Any] = {}
    for row in rows:
        if row.get("runtime_override") is not None:
            overridden[row["case"]] = row["runtime_override"]
    for case_id, config in sorted(overridden.items()):
        warnings.append(f"`{case_id}` ran with the repository's patchproof.json replaced by "
                        f"`{json.dumps(config, sort_keys=True)}` from the manifest, so it measures that "
                        "configuration, not the file at the pinned commit. Compare engines only on "
                        "trials that used the same override.")
    heldout_cases = {r["case"] for r in rows if r["split"] == "heldout"}
    if not heldout_cases:
        warnings.append("This run has no held-out cases, so it says nothing about issues the engine has not "
                        "been tuned on.")
    elif len(heldout_cases) < 3:
        warnings.append(f"Only {len(heldout_cases)} held-out case(s): trials of one case are not independent "
                        "evidence about new issues. Read these numbers as examples, not statistics.")
    if warnings:
        out += ["", "## Read before quoting", ""] + [f"- {w}" for w in warnings]
    return "\n".join(out) + "\n"


def render_labels_needed(needed: list[dict[str, Any]]) -> str:
    if not needed:
        return "# Labels needed\n\nEvery candidate diff has been judged.\n"
    out = ["# Labels needed", "",
           "Each block is a distinct candidate diff. Judge it against the issue text only: does it make the "
           "reported behavior correct without breaking anything else? Then add its hash to "
           "`bench/labels/<case>.json` as `{\"correct\": true|false, \"case_sha256\": \"<case digest below>\", \"note\": \"...\"}`. "
           "Use the full exact patch hash; legacy normalized labels are not reused.", ""]
    for item in needed:
        out += [f"## {item['case']} — `{item['hash']}`", "", f"Case SHA-256: `{item.get('case_sha256') or 'legacy / not recorded'}`", "", f"Seen in: {', '.join(item['seen'])}", "",
                "```diff", item["diff"].rstrip("\n"), "```", ""]
    return "\n".join(out)


def load_oracle_results(oracle_dir: Path) -> dict[str, dict[str, Any]]:
    results = {}
    for path in sorted(oracle_dir.rglob("oracle-*.json")) if oracle_dir.is_dir() else []:
        data = json.loads(path.read_text(encoding="utf-8"))
        results[data["case"]] = data
    return results


def write_report(results_dir: Path, oracle_dir: Path, out_dir: Path, *,
                 manifest: dict[str, Any], labels_dir: Path = LABELS_DIR) -> dict[str, Any]:
    trials = collect_results(results_dir)
    if not trials:
        raise BenchError(f"No trial results found under {results_dir}.")
    protocols = {(t["meta"].get("protocol_id", "legacy"), t["meta"].get("manifest_sha256", "unknown")) for t in trials}
    if len(protocols) != 1:
        raise BenchError("Trials use different protocol/manifest snapshots. Report each separately; do not pool historical and retuned cases.")
    profiles: dict[str, set[str]] = {}
    for trial in trials:
        meta = trial["meta"]
        profile = json.dumps({"mode": meta.get("agent_mode", "legacy"), "settings": meta.get("agent_settings", {}),
                              "model": meta.get("model", ""), "max_tokens": meta.get("max_tokens", "")}, sort_keys=True)
        profiles.setdefault(meta["engine_ref"], set()).add(profile)
    if any(len(values) > 1 for values in profiles.values()):
        raise BenchError("One engine has mixed execution profiles or budgets. Report those runs separately.")
    oracle_results = load_oracle_results(oracle_dir)
    rows = build_rows(trials, manifest, oracle_results, labels_dir)
    needed = labels_needed(trials, manifest, oracle_results, labels_dir)
    meta_summary = {
        "protocol_id": next(iter(protocols))[0],
        "manifest_sha256": sorted({t["meta"].get("manifest_sha256", "") for t in trials})[-1],
        "models": sorted({t["meta"].get("model", "") for t in trials} - {""}),
        "engines": sorted({t["meta"]["engine_ref"] for t in trials}),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.md").write_text(
        render_markdown(rows, needed, manifest=manifest, meta_summary=meta_summary), encoding="utf-8")
    (out_dir / "labels-needed.md").write_text(render_labels_needed(needed), encoding="utf-8")
    summaries = {}
    for engine in meta_summary["engines"]:
        for split in ("dev", "heldout", "all"):
            members = [r for r in rows if r["engine"] == engine and (split == "all" or r["split"] == split)]
            if members:
                summaries[f"{engine}/{split}"] = summarize(members)
    (out_dir / "results.json").write_text(json.dumps({
        "meta": meta_summary, "summary": summaries, "trials": rows,
        "labels_needed": [{k: v for k, v in e.items() if k != "diff"} for e in needed],
        "oracle": {case: {"valid": r.get("valid"), "reason": r.get("reason")} for case, r in oracle_results.items()},
    }, indent=2) + "\n", encoding="utf-8")
    return {"rows": rows, "needed": needed}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _write_output(path: str | None, values: dict[str, str]) -> None:
    text = "".join(f"{key}={value}\n" for key, value in values.items())
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check the manifest; --ready also rejects placeholders")
    p.add_argument("--ready", action="store_true")

    p = sub.add_parser("plan")
    p.add_argument("--engines", required=True)
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--split", default="all")
    p.add_argument("--cases", default="")
    p.add_argument("--github-output")

    p = sub.add_parser("run")
    p.add_argument("--case", required=True)
    p.add_argument("--trial", type=int, required=True)
    p.add_argument("--engine-ref", required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--subject", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--timeout-minutes", type=int, default=75)

    p = sub.add_parser("oracle")
    p.add_argument("--case", required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--checkout", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)

    p = sub.add_parser("report")
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--oracle", type=Path, default=Path("oracle-results"))
    p.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(MANIFEST_PATH)
        if args.command == "validate":
            ids = {case["id"] for case in manifest["cases"]} if args.ready else set()
            problems = validate_manifest(manifest, ROOT, ready_ids=ids)
            for problem in problems:
                print(problem)
            print(f"{len(manifest['cases'])} case(s); {len(problems)} problem(s).")
            return 1 if problems else 0
        if args.command == "plan":
            plan = build_plan(manifest, engines=parse_list(args.engines), trials=args.trials,
                              split=args.split, ids=parse_list(args.cases), root=ROOT)
            _write_output(args.github_output, {
                "matrix": json.dumps(plan["matrix"]), "oracle_cases": json.dumps(plan["oracle_cases"]),
                "has_oracle": str(plan["has_oracle"]).lower()})
            print(f"Planned {plan['jobs']} trial job(s).")
            return 0
        if args.command == "run":
            case = next((c for c in manifest["cases"] if c["id"] == args.case), None)
            if case is None:
                raise BenchError(f"Unknown case {args.case}.")
            meta = run_trial(case=case, trial=args.trial, engine_ref=args.engine_ref,
                             engine_dir=args.engine_dir, subject=args.subject, out=args.out,
                             timeout_seconds=args.timeout_minutes * 60, root=ROOT)
            print(json.dumps(meta, indent=2))
            return 0            # engine failure is a recorded result, not a job failure
        if args.command == "oracle":
            case = next((c for c in manifest["cases"] if c["id"] == args.case), None)
            if case is None or not case.get("oracle"):
                raise BenchError(f"Case {args.case} has no oracle.")
            result = run_oracle(case, args.results, args.checkout, root=ROOT)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / f"oracle-{args.case}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"Oracle for {args.case}: valid={result['valid']}, diffs judged={len(result['diffs'])}")
            return 0
        if args.command == "report":
            write_report(args.results, args.oracle, args.out, manifest=manifest, labels_dir=LABELS_DIR)
            print((args.out / "results.md").read_text(encoding="utf-8"))
            return 0
    except BenchError as error:
        print(f"::error::{error}" if os.environ.get("GITHUB_ACTIONS") else f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
