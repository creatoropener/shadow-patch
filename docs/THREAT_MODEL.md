# Prototype trust boundary

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
