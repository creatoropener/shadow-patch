# QR repository: first real test plan

Status: waiting for repository URL or ZIP. No framework, features or bugs are assumed.

## Intake

1. Identify language, encoder dependency, public API and supported export formats.
2. Read project instructions, tests and dependency lockfiles.
3. Select a reported bug or small historical fix and its base/head commits.
4. Establish a passing baseline and reproduce the issue. If no suitable bug exists,
   propose a clearly labelled seeded mutation on a separate test branch.

## Candidate checks (only where supported)

| Behaviour | Evidence |
|---|---|
| Encode/export payload | Decode output with a separate decoder; compare exact content |
| Unicode | Preserve non-ASCII text through encode/export/decode |
| URL content | Preserve query parameters and reserved characters |
| Empty/oversized input | Follow documented validation behaviour |
| Dimensions/quiet zone | Follow the project's documented contract |

The encoder's success flag is not sufficient evidence of decodability. A browser app
may need Playwright and a separate image decoder. The current Node adapter alone
does not test browser rendering. Select dependencies after inspecting actual source.

## Acceptance

Show a regression failing on base, a flawed candidate rejected if available, the
corrected candidate passing existing/locked tests, and fresh replay. Report execution
errors and ambiguous requirements as blocked. Attach evidence to the exact tested commit.

## Needed next

- Repository URL (preferred) or ZIP.
- Existing issue/PR link if available; otherwise inspect for a suitable case.
- For live execution, credentials in environment secrets and prepared Nebius image UUID.

Do not paste API keys or private keys into chat.
