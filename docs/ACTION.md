# Shadow Patch GitHub Action (beta)

Use PatchProof from any repository with **one workflow file**. No engine files are
copied into your repository: the engine runs from the pinned Action version.

> **Beta.** Recorded live evidence exists for `node-typescript` and `node-package`
> targets only (see [COMPATIBILITY.md](COMPATIBILITY.md)). Every other adapter is
> experimental. Pin an exact tag, never a branch.

## 1. Add the workflow

Copy [`examples/action-usage/shadow-fix.yml`](../examples/action-usage/shadow-fix.yml)
to `.github/workflows/shadow-fix.yml` in your repository and commit it to the
default branch. Pass only the image input your adapter needs.

## 2. Add secrets and variables

| Name | Where | Purpose |
| --- | --- | --- |
| `NEBIUS_API_KEY` | Secret | Inference and Sandbox credential |
| `NEBIUS_PROJECT_ID` | Secret | Project authorized for Sandboxes |
| `NEBIUS_MODEL` | Variable (or secret) | e.g. `nvidia/nemotron-3-super-120b-a12b` |
| `CONTREE_IMAGE_<ADAPTER>` or `CONTREE_IMAGE` | Secret | Sandbox image UUID for your adapter |

Secrets are not shared between repositories. Under **Settings → Actions → General**
enable *Allow GitHub Actions to create and approve pull requests*.

## 3. Get a sandbox image

The image must match the adapter and be accessible to your Nebius project. Run
**Prepare Sandbox Image** (profile `web` for TypeScript/Node, `all` for everything)
from a repository that has [`prepare-image.yml`](../.github/workflows/prepare-image.yml),
and save the printed UUID as the matching secret. `node-typescript` needs the
`patchproof-web:v0.7` (or newer) image.

## 4. Prepare the target repository

- Your normal baseline test command must already pass.
- `node-typescript` is detected only when both `package.json` and `tsconfig.json`
  exist at the root; pin `tsx` and `typescript` in `devDependencies`.
- Add `patchproof.json` (`{"runtime": "node-typescript"}`) if detection is ambiguous.

## 5. Trigger

Create an issue that describes observable behaviour and expected output, then apply
the exact `shadow-fix` label. The Action comments on the issue, verifies, uploads
`proof.json` and `verification-report.md`, opens one PR per issue, and never merges it.

## Inputs and outputs

Inputs: `nebius-api-key`, `nebius-project-id`, `nebius-model` (required);
`nebius-max-tokens` (default `12000`); `sandbox-image`; one `image-<adapter>` per
adapter (`python-pytest`, `node-package`, `node-typescript`, `static-web`,
`web-playwright`, `java-junit`, `java-maven`, `java-gradle`, `go`, `rust`);
`github-token` (default `github.token`).

Outputs: `verdict` (`verified`, `rejected`, `blocked`) and `pull-request-url`.

## Known beta limits

- The caller must run `actions/checkout` with `fetch-depth: 0` before the Action.
- `proof.json` and `verification-report.md` are included in the repair PR, as with the
  copy-install workflow.
- Whether one sandbox image UUID can be reused across repositories in the same Nebius
  project is not yet recorded; treat it as per-repository until verified.
- The copy-install path (`tools/export_target.py`) still works and is unchanged.
