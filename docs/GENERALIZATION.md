# Project support added in rc.27

rc.27 widens which Node/TypeScript projects the engine can set up and repair. It does not change how a repair is verified: the frozen regression, ordinary-CI discovery, clean replay and verified-file delivery still gate every result. It is locally validated only; no live Nebius run covers these paths.

## `patchproof.json` reference

All keys are optional. The file lives at the repository root and is never editable by a solver.

| Key | Meaning |
| --- | --- |
| `runtime` | Adapter ID, needed only when detection is ambiguous. |
| `test_directory` | Existing folder for generated tests (relative to the project). |
| `root` | A self-contained subfolder to treat as the project, for example `server`. |
| `known_failures` | Names of tests that already fail on the base commit and are unrelated to the issue. |
| `scope.allowed_paths` | Exact existing files a repair may edit. |
| `scope.protected_symbols` | Top-level declarations that must stay byte-identical, per file. |
| `scope.new_file_dirs` | Existing folders where a repair may create new source files (bounded mode only). |

## Package managers

The install tool comes from the project, never from a default:

1. `packageManager` in `package.json` (for example `pnpm@9.15.9`) names the tool and exact version.
2. Otherwise the lockfile decides: `package-lock.json` or `npm-shrinkwrap.json` is npm, `pnpm-lock.yaml` is pnpm, `yarn.lock` is Yarn.
3. With no lockfile and no declaration the engine uses `npm install`, as before.

Installs use the lockfile (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --frozen-lockfile`, or `yarn install --immutable` for Yarn 2+) with install scripts disabled. pnpm, Yarn Classic and Yarn Berry are installed into the sandbox with `npm install -g` at the pinned version; when only a lockfile is present, the pnpm major comes from `lockfileVersion` and Yarn Berry's from its `__metadata` block. The ordinary test command and `build` check then run through the same tool (`CI=1 pnpm test`).

The engine stops with a specific message instead of guessing when: two lockfiles disagree and `packageManager` does not settle it; `packageManager` names a tool whose lockfile is absent; the tool is Bun; or the project is Yarn Plug'n'Play (the type checker and sandbox need `node_modules`; set `nodeLinker: node-modules`).

Checked locally with real npm, pnpm 9, Yarn 1 and Yarn 4 lockfiles: frozen install, version probe and test run all succeed. **Not checked:** the sandbox image installs Node from apt, so confirm that `npm install -g` can write there on the first pnpm or Yarn target. Native-addon packages that need install scripts are out of scope.

## Project folder (`root`)

`{"root": "server"}` makes the engine treat `server/` as the whole project: detection, archive, install, tests, type check and generated-test placement are all scoped to it. Scope paths and `test_directory` are relative to that folder. `patchproof.json` and `proof.json` stay at the repository root, and the PR file list is prefixed with the folder (`server/src/a.ts`) so the pull request stages the right paths.

This is for a folder that installs and tests on its own, such as `client/` and `server/` in one repository. The engine refuses, with a message, when the root is a symlink, is outside the repository, or is part of a workspace: `pnpm-workspace.yaml`, a `workspaces` field, or a `workspace:`, `link:` or `file:..` dependency. Workspace packages need an install from the repository root and are not supported.

`.mts` and `.cts` files are now editable and visible context for the TypeScript adapter, like `.ts` and `.tsx`.

## Known failures

If the project's own suite already fails, list the failing tests by exactly the name the runner prints:

```json
{"known_failures": ["legacy: removed feature"]}
```

The ordinary test command then passes only when every failing leaf test is a listed one. A new failure, a candidate that breaks a passing test, or a failure that cannot be accounted for test by test still stops the run, so passing tests stay protected. The proof records the declared names and the failures observed on the base commit.

Limits. Only `node:test` TAP output can be read test by test; other runners (Jest, Vitest, pytest and so on) are refused when the list is set. Names must match exactly, and a repeated name in two files cannot be told apart. Declared failures share the command's output, so ordinary-CI discovery accepts the frozen regression when the command executes its file and reports a failure nobody declared; the explicit regression run has already established the assertion failure. List only failures unrelated to the issue: a listed test that the repair should fix is not protected.

## New files

```json
{"scope": {"new_file_dirs": ["src/util"]}}
```

In bounded mode the solver gains a `create` action. The folder must already exist. A new file must sit under a listed folder, use an editable source extension, avoid hidden, generated, protected and test paths, not collide with an existing file (even one outside the model's view), stay under 200000 bytes, and be one of at most three. Existing code must import it through a normal `edit`, and the type check, interference check, frozen regression, clean replay and delivery hash check apply to it like any other source. Legacy mode refuses a scope that allows new files, because its candidates are exact-match edits to existing files. New dependencies, config files and files outside the declared folders remain unsupported.

## Provenance

Every proof now records, in both modes: `engine` (version, commit when known, ref), `engine_provenance` (SHA-256 of each engine file that ran), `project_inputs` (manifests, lockfiles, `.yarnrc.yml` and the effective `patchproof.json`), `archive_sha256`, `project_root`, the package-manager command, and `runtime.toolchain` (Node, npm, package manager, tsx and tsc versions printed by the sandbox, with raw lines kept). Set `PATCHPROOF_ENGINE_COMMIT` to record a commit where the engine is not a git checkout. An environment file such as `.npmrc` is never hashed or read.

## Still not supported

Workspace installs from a repository root, Yarn Plug'n'Play, Bun, non-TAP test runners for known failures, new files in legacy mode or for other runtimes, dependency or config repairs, and a bounded profile for runtimes other than `node-typescript`.
