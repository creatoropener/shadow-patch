## PatchProof verification report

**Result: rejected**

Base commit: `737eeb2ebc48caee636856ad5e16debae604ebde`
Candidate commit: `2136d5a29f14cd2fa47f14d780b400ed37b3a94c`
Locked input digest: `4d135c431b3672c658ada8f9ed4808c59df908ae2dbf4b7dfe4f72748bc151db`
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
