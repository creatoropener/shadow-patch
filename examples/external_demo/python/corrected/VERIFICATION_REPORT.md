## PatchProof verification report

**Result: passed-checks**

Base commit: `737eeb2ebc48caee636856ad5e16debae604ebde`
Candidate commit: `c07fcd99385629aa7b345688d5abda0ad35b8060`
Locked input digest: `4d135c431b3672c658ada8f9ed4808c59df908ae2dbf4b7dfe4f72748bc151db`
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
