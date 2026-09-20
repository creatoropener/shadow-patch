"""Render an offline evidence viewer from captured reports; never runs tests."""
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
proof = json.loads((root / "docs/evidence/green-run-v0.5.5.json").read_text())
run = json.loads((root / "docs/evidence/github-run-35464615209.json").read_text())
data = json.dumps({"proof": proof, "run": {key: run[key] for key in (
    "id", "conclusion", "head_sha", "run_started_at", "updated_at", "html_url",
)}}, ensure_ascii=True).replace("<", "\\u003c")
template = (root / "tools/evidence_template.html").read_text()
out = root / "docs/demo/index.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(template.replace("__EVIDENCE_DATA__", data))
print(f"Rendered recorded evidence to {out}")
