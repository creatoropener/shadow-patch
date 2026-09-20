"""Build a 2:50 silent evidence walkthrough. Requires ffmpeg; never runs tests."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
scenes = [
    ("docs/visuals/01-verification.png", 20,
     "Shadow Engineer turns labelled bugs into PRs backed by test evidence.\nThis walkthrough presents a completed run, not a new live execution."),
    ("docs/visuals/07-reproduction.png", 25,
     "First, an independent regression reproduces the reported defect.\nThe verifier test is created before any repair candidate is proposed."),
    ("docs/visuals/04-candidates.png", 30,
     "Three candidates run sequentially in isolated Nebius sandbox branches.\nThe hidden regression rejects candidate 2; candidate 1 is selected."),
    ("docs/visuals/05-replay.png", 30,
     "The selected patch passes again in a clean sandbox.\nThree baseline tests and two regression tests pass; the test hash matches."),
    ("docs/screenshots/02-github-run.jpg", 30,
     "Actual GitHub screenshot: the completed workflow is green.\nNVIDIA Nemotron inference and sandbox execution use Nebius Token Factory."),
    ("docs/screenshots/03-github-pr.jpg", 25,
     "Actual GitHub screenshot: the generated PR contains its verification report.\nRerunning the same issue updates its PR. A human reviews and merges."),
    ("docs/visuals/06-sources.png", 10,
     "Demonstrated scope: one TypeScript utility repair.\nInspect the evidence. Keep the human decision."),
]
out = root / "docs/demo/shadow-engineer-demo-2m50.mp4"
font = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
with tempfile.TemporaryDirectory(prefix="patchproof-video-") as directory:
    temp = Path(directory)
    clips = []
    for i, (source, seconds, caption) in enumerate(scenes):
        caption_file = temp / f"caption-{i}.txt"
        caption_file.write_text(caption)
        clip = temp / f"clip-{i}.mp4"
        filters = (
            "scale=1920:960:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:0:color=0x0a1420,setsar=1,"
            f"drawtext=fontfile={font}:textfile={caption_file}:"
            "fontsize=28:fontcolor=white:line_spacing=10:x=(w-text_w)/2:y=990"
        )
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", "10", "-i", str(root / source),
            "-t", str(seconds), "-vf", filters, "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-tune", "stillimage", "-crf", "23",
            "-threads", "2", "-pix_fmt", "yuv420p", str(clip),
        ], check=True)
        clips.append(clip)
        print(f"Rendered scene {i + 1}/{len(scenes)}", flush=True)
    listing = temp / "clips.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in clips))
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
        "-movflags", "+faststart", str(out),
    ], check=True)
print(out)
