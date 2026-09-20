# Shadow Engineer — PatchProof evidence

Status: **verified**
Mode: demo
Provider: local-trusted-fixture (not VM isolated)
Model: none: scripted fixture

| Gate | Exit | Passed | Failed | Errors |
|---|---:|---:|---:|---:|
| baseline | 0 | 2 | 0 | 0 |
| reproduce | 1 | 0 | 1 | 0 |
| candidate-1-regression | 1 | 0 | 1 | 0 |
| candidate-1-suite | 1 | 2 | 1 | 0 |
| candidate-2-regression | 1 | 0 | 1 | 0 |
| candidate-2-suite | 1 | 1 | 2 | 0 |
| candidate-3-regression | 0 | 1 | 0 | 0 |
| candidate-3-suite | 0 | 3 | 0 | 0 |
| candidate-3-replay | 0 | 3 | 0 | 0 |

Human merge approval required. No PR has been opened.

Evidence covers the supplied tests only. Local demo uses scripted inputs and separate temporary directories, not Nebius VMs.
