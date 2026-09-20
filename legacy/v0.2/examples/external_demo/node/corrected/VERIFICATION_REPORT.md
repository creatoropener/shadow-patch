## PatchProof verification report

**Result: passed-checks**

Base commit: `9c1ed6c3862e1e2aefc18c3ace0fc3183c558ebe`
Candidate commit: `b8656d1c9e06d95b107f12689ac0f583107d6362`
Locked input digest: `d2c33cc40c12580f3b70c15adea1a71dd22710201d431a3dc7dd5fb1ccd6ec5b`
Provider: local-fixture

| Gate | Outcome | Passed | Failed | Errors | Skipped |
|---|---|---:|---:|---:|---:|
| baseline | passed | 1 | 0 | 0 | 0 |
| reproduce | reproduced | 1 | 1 | 0 | 0 |
| candidate-regression | passed | 2 | 0 | 0 | 0 |
| candidate-suite | passed | 1 | 0 | 0 | 0 |
| combined | passed | 3 | 0 | 0 | 0 |
| fresh-replay | passed | 3 | 0 | 0 | 0 |

Locked regression, existing suite and fresh replay passed

Test provenance: scripted fixture; not AI-generated
Direct changes outside the application allowlist are blocked before execution.
Test evidence is not a guarantee of correctness or security. Human review is required.
This report applies only to the commits above. No PR or comment has been posted.

Local fixture run: no model call or Nebius VM was used.
