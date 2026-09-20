# v0.5.5 consolidation handoff

## What is ready

- Current engine, adapters, helpers and corrected workflows at repository root.
- v0.2 preserved under `legacy/v0.2/`, with the existing root MIT license retained.
- Setup, architecture, submission draft, evidence provenance and demo narration.
- Two actual GitHub screenshots, five labelled evidence cards and an offline viewer.
- A 1920×1080, 170-second **silent, captioned evidence walkthrough** at
  `docs/demo/shadow-engineer-demo-2m50.mp4`. It uses still captures and cards;
  it is a demo editing draft, not new live application footage.

The consolidation was based on creatoropener/shadow-patch commit
`1d9dee755e971cffd4e9d7ff8b39f248cc7223d4`.

## Apply to the main repository

The delivery includes a full repository snapshot and a Git patch. Prefer the
patch in a clean checkout because it preserves the move into `legacy/v0.2/`:

```bash
git switch -c release/v0.5.5-submission
git apply --index /path/to/Shadow-Engineer-v0.5.5-Consolidation.patch
git commit -m "Consolidate PatchProof v0.5.5 and submission materials"
git push -u origin release/v0.5.5-submission
```

Open a PR from that branch into main and review it before merging. If your base
has changed and the patch conflicts, resolve against the full snapshot rather
than deleting unrelated work. A ZIP overlay alone will not remove old root files;
move the previous README, CHANGELOG, .env.example, pyproject.toml, shadow_engineer,
tests, artifacts, examples and docs into legacy/v0.2 before copying the new snapshot.

## Checks actually performed

Python syntax and module imports, workflow YAML parsing, helper JavaScript syntax,
evidence JSON parsing, local documentation links, diff whitespace, image inspection,
and video duration/frame inspection. No application test suite, new model inference,
or new sandbox verification was run. The optional offline viewer was not rendered
in the cloud browser because local-file URLs are disallowed there.

## Before final submission

1. Publish/merge this consolidated source release to the main repository.
2. Remove the two historical .pyc files from the file-sharing PR before its merge.
3. Finish the demo with narration and actual workflow/module screen footage using
   docs/DEMO.md. Review credentials, scope and timing; keep it below three minutes.
4. Upload the final video publicly, add its URL to docs/SUBMISSION.md, and enter
   the submission form. Neither a Devpost submission nor a YouTube upload is made
   by this source package.

Checksums for packaged source, evidence and media are in RELEASE_FILES.sha256.
