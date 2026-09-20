## PatchProof verification report

**Result: rejected**

Base commit: `9c1ed6c3862e1e2aefc18c3ace0fc3183c558ebe`
Candidate commit: `58488f541e70e96d5addb9789dfdf27a4cb056c3`
Locked input digest: `d2c33cc40c12580f3b70c15adea1a71dd22710201d431a3dc7dd5fb1ccd6ec5b`
Provider: local-fixture

| Gate | Outcome | Passed | Failed | Errors | Skipped |
|---|---|---:|---:|---:|---:|
| baseline | passed | 1 | 0 | 0 | 0 |
| reproduce | reproduced | 1 | 1 | 0 | 0 |
| candidate-regression | failed/blocked | 1 | 1 | 0 | 0 |

Candidate failed the locked regression or changed test identities

Test provenance: scripted fixture; not AI-generated
Direct changes outside the application allowlist are blocked before execution.
Test evidence is not a guarantee of correctness or security. Human review is required.
This report applies only to the commits above. No PR or comment has been posted.

Local fixture run: no model call or Nebius VM was used.
