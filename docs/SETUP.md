# Setup and first run

## Install the engine

From this repository, run:

```bash
python3 tools/export_target.py --output ../patchproof-target-v0.6.0-rc.5.zip
```

Extract the ZIP and copy its files to the **target repository root**, preserving
`.github/workflows/shadow-fix.yml` and `.github/workflows/prepare-image.yml`.
Commit to that repository's default branch. The export excludes historical
prototypes, submission files and recorded regression output.

Add these rules to the target's existing `.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
```

The workflow disables Python bytecode generation on the Actions runner. Already
tracked `.pyc` files must be removed in a cleanup commit; ignoring them is not enough.
The target may commit generated proof reports as part of its repair PR, so the
engine repository's root report-ignore rules are not exported.

## Configure GitHub

Under the target's **Settings → Secrets and variables → Actions**:

| Name | Location | Purpose |
| --- | --- | --- |
| `NEBIUS_API_KEY` | Secret | Working credential for the configured Nebius inference and sandbox calls |
| `NEBIUS_PROJECT_ID` | Secret | Project authorized for Sandboxes |
| `NEBIUS_MODEL` | Variable, or existing secret | Model identifier; demonstrated: `nvidia/Nemotron-3_5-Lightning` |
| `CONTREE_IMAGE` | Secret | Shared compatible sandbox image UUID |
| `NEBIUS_MAX_TOKENS` | Optional variable | Completion budget, default `12000` |

A runtime-specific image secret takes precedence over `CONTREE_IMAGE`:

| Adapter | Image secret |
| --- | --- |
| python-pytest | `CONTREE_IMAGE_PYTHON_PYTEST` |
| node-package | `CONTREE_IMAGE_NODE_PACKAGE` |
| node-typescript | `CONTREE_IMAGE_NODE_TYPESCRIPT` |
| static-web | `CONTREE_IMAGE_STATIC_WEB` |
| web-playwright | `CONTREE_IMAGE_WEB_PLAYWRIGHT` |
| java-junit | `CONTREE_IMAGE_JAVA_JUNIT` |
| java-maven | `CONTREE_IMAGE_JAVA_MAVEN` |
| java-gradle | `CONTREE_IMAGE_JAVA_GRADLE` |
| go | `CONTREE_IMAGE_GO` |
| rust | `CONTREE_IMAGE_RUST` |

Do not paste credentials into an issue, README or recording. Repository secrets
are not automatically shared with another repository. Sandbox beta access must
already be enabled for your project. See [Nebius sandbox documentation](https://docs.tokenfactory.nebius.com/sandboxes/swe-agents).

Enable Actions and, where permitted by organization policy, the setting allowing
GitHub Actions to create pull requests. The workflow requests contents, issues
and pull-request write permissions. Do not broaden those permissions to bypass
an organization policy.

## Prepare or reuse an image

An existing image can be reused only if the project can access it and its
toolchain matches the adapter. The `node-typescript` image must contain the pinned
`tsx` executable at `/opt/patchproof/node/node_modules/.bin/tsx`; an older v0.5
image will fail preflight. The target's own locked dependencies are installed
during sandbox bootstrap.

Otherwise run **Prepare Sandbox Image** from Actions. Choose `web` for this
TypeScript case, or `all` for the combined toolchain. Copy the resulting UUID to
the matching image secret. Other profiles are `python`, `jvm`, `go` and `rust`.
The setup uses `contree-sdk==0.3.6` and `openai==1.109.1` on the runner.

## Configure a testable target

Runtime detection reads root manifests. Select explicitly when ambiguous:

```json
{"runtime": "node-typescript"}
```

Save that as `patchproof.json`. Only `runtime` and `test_directory` are accepted.
For Go, `test_directory` names the existing package containing source. Consult
`runtimes.py` for conventional Maven, Gradle and Rust layouts.

An existing baseline must pass before repair. Keep the new root-level regression
out of the baseline command. For a TypeScript target, pin `tsx` and `typescript`
in the target's development dependencies and use a baseline such as:

```json
"scripts": {
  "test": "tsx --test --test-reporter=tap tests/*.test.ts"
},
"devDependencies": {
  "tsx": "4.23.15",
  "typescript": "5.6.3"
}
```

For the demonstrated file-sharing target, copy `examples/file-sharing-setup/tests/`
and its `patchproof.json`, add the test script and exact development dependencies
above, then regenerate `package-lock.json` with
`npm install --save-dev --save-exact tsx@4.23.15 typescript@5.6.3`. Do not replace the target's
entire package.json or lockfile. The engine export includes generic Web Streams
test plumbing and a temporary project-aware type-check harness; it does not install
application dependencies into the repository.

The known unfixed app revision is `807346b22421d0a58103092ccc318c1bdc1d7231` in
creatoropener/file-sharing-app. Reproduce in a separate demonstration repository
based on that revision, adding the current engine and setup before labeling the
issue. Do not revert a repaired main branch merely for a demo.

## Trigger and inspect

1. Create an issue describing observable behavior and expected outputs. The
   [demo guide](DEMO.md) supplies the file-sharing case.
2. Create and apply the exact `shadow-fix` label **after** committing the workflow.
3. Open Actions → Shadow Fix. Inspect the report artifact and job summary.
4. Review the source diff, frozen regression and report in the PR. Merge manually.

Rerunning the same issue uses `shadow-fix/issue-<number>` and can update its
existing PR. It is not expected to create a duplicate PR. A previously merged
repair may no longer reproduce; that rejection is appropriate.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No workflow run | Both workflow filenames must end in `.yml`; commit on default branch, then remove/reapply the label |
| Forbidden from Nebius | Authorized project, credential and Sandbox access; the CLI tutorial alone does not grant API access |
| Missing node/npm/jsdom/tsx | Correct image profile, runtime-specific secret and new image UUID; do not reuse the v0.5 image |
| Empty or truncated model output | Reported inference reason and configured budget; incomplete JSON remains rejected |
| Baseline fails | Existing tests or bootstrap must be repaired separately; do not weaken expected behavior |
| PR exists but old run is red | Old notification step tried reading a report after PR creation; install the corrected workflow |
| Green run, no new PR | Inspect the linked existing PR; the PR action may update it or find no new diff |

Notification failure is non-blocking; verification or PR-action failure is still
blocking. An empty PR-action result can currently yield no PR; green alone is not
evidence of a newly created PR. Always inspect the report and PR URL.
