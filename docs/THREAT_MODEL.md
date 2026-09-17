# Prototype trust boundary

## External workflow added in 0.2

The maintainer retains the lock digest outside candidate control. Only full Git
SHAs are accepted. Snapshots exclude dirty/untracked worktree files. Candidate
changes outside an explicit application-file allowlist are blocked.

The cloud harness requires root to create read-only input files and drop the child
to UID/GID 65534 with supplementary groups cleared. Local fixtures do not change
users. Cloud UID separation is not live-tested and fails closed if unavailable.
Network/resource isolation still depends on the prepared cloud environment; no
egress-control claim is made. All tracked files enter the cloud snapshot; review
the inventory and keep credentials out of the target repository.

Input hashes detect some modifications. They cannot prevent in-process monkey
patching, fabricated JUnit, test inspection, vulnerable VM escapes or network abuse.
Reports are unsigned. Matching test names does not prove equal test semantics.
Test provenance is a declaration, not attested authorship. Human review and independently
established expected behaviour remain essential.

## Legacy v0.1 fixture and general limitations

The local command only executes our bundled fixture. It is not a safe general-purpose
sandbox. Source, issue text, generated tests, generated fixes and model responses
must be treated as untrusted when extending the project.

Current policy rejects path traversal and direct candidate changes outside existing
app Python files. It separates secrets from the cloud test harness, checks JUnit
evidence and rejects non-test failures as reproduction. These controls do not stop
Python code from manipulating pytest, rewriting evidence, patching imports, spawning
children or abusing network access from inside its execution environment.

Before accepting arbitrary repositories: constrain egress and resources, keep the
verification harness outside candidate write access where feasible, add process-group
termination and remote operation cancellation, attest inputs and runner configuration,
check test identity and collected node IDs, use independent behavioral checks, inspect
the regression for relevance, reject skips/xfails and evidence tampering, and enforce
repository/installation authorization. Never accept untrusted repository instructions
as authority to disclose secrets, modify the orchestrator, or change verification gates.

Fresh replay here means a new temporary working tree or a new branch from the same
prepared cloud image. It does not reinstall dependencies or provide bit-for-bit
reproducibility across infrastructure. Candidate generation is sequential and bounded
to three candidates. Test evidence and source hashes are not signed attestations.
