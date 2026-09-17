# External commit verification

Use a local Git clone and full commit SHAs. Branch names are rejected because they
can move. A source ZIP can be inspected first; preserving upstream commit identity
requires the repository URL or known commit metadata. Replace all example paths
with actual repository files; do not assume the QR repository uses Python.

## 1. Read-only inventory

```bash
python -m shadow_engineer.patchproof_cli inspect --repo /path/to/repo --base FULL_BASE_SHA
```

This reads Git objects. It does not execute code, check out files or install dependencies.

## 2. Draft a separate regression (optional)

Install `python -m pip install -e '.[cloud]'`. Set NEBIUS_API_KEY and the exact
available NVIDIA model ID in NEBIUS_MODEL. Credentials belong in environment secrets.

```bash
python -m shadow_engineer.patchproof_cli draft-test \
  --repo /path/to/repo --base FULL_BASE_SHA \
  --issue /path/to/issue.md --runtime pytest \
  --context src/qr.py --context tests/test_qr.py \
  --output verifier/draft-1
```

This makes a paid API call when configured, sending the issue and only selected base
files. Review those files before sending; filename checks are not a general secret
scanner. Candidate code is never an input. Outputs are regression.py (or
regression.test.mjs) and generation.json with context/test hashes, assumptions,
model ID and response ID when available. Review assumptions before locking.
Different prompts/models do not establish correct expected behaviour. Release tests
mock inference; no live model request has been validated.

A human-authored regression is also supported. Tests are copied to
tests/test_patchproof_locked.py or tests/test_patchproof_locked.test.mjs; use imports
relative to that destination. Test files run in the same process as application
imports; an independent role is not a security boundary for malicious code.

## 3. Freeze verifier inputs

```bash
python -m shadow_engineer.patchproof_cli lock \
  --repo /path/to/repo --base FULL_BASE_SHA \
  --issue /path/to/issue.md --regression verifier/draft-1/regression.py \
  --runtime pytest --suite tests/test_qr.py --writable src/qr.py \
  --provenance 'separate test draft reviewed by maintainer' \
  --output verifier/qr-lock.json
```

Repeat --suite / --writable for individual files. Tests and configuration cannot be
writable. Save the printed lock_sha256 separately in verifier-controlled configuration.
It detects changes relative to that reference; it is not a signature and does not
establish authorship or test creation time. Keep generation.json with the run evidence.

## 4. Verify a candidate

Set CONTREE_BASE_URL, CONTREE_IMAGE (immutable UUID), and CONTREE_TOKEN or
NEBIUS_API_KEY. The image must contain Python 3.11+, pytest or Node and all required
dependencies, and start the harness as root. The child runs as UID/GID 65534 against
root-owned read-only files. Use a clean image without secrets. Local Node dependencies,
browser dependencies and any build step need explicit preparation; arbitrary project
installation/build scripts are not supported yet.

```bash
python -m shadow_engineer.patchproof_cli verify \
  --repo /path/to/repo --head FULL_CANDIDATE_SHA \
  --lock verifier/qr-lock.json --lock-sha256 PRINTED_DIGEST \
  --output artifacts/qr-run-1
```

Candidate must descend from base. Policy checks run before cloud connection. Each
stage starts from the same prepared image. Tests have a 30-second timeout, remote
execution has a 60-second limit and SDK operations have a 90-second timeout.
Disposal is requested for executions.

Exit 0 means passed-checks; 1 means verification did not pass; 2 means an input/config
error. Provider failures before a report starts may raise an SDK exception; they
never produce a passing report.

## 5. Review

proof.json and VERIFICATION_REPORT.md contain the exact base/head and lock digest.
No GitHub upload occurs. A future PR integration must recheck current PR base/head
before posting a report or check. Disposable runs may not return a result-image UUID;
complete provider run provenance must be checked during live integration. Local run
IDs are generated locally and are never presented as service operation IDs.
