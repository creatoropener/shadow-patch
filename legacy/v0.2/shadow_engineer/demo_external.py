"""Known fixture in a real disposable Git repo; not the user's QR repository."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from .repository import canonical, sha
from .repository import lock_inputs
from .external_proof import verify_external, write_report
from .external_runners import LocalExternalFixtureRunner

ORIGINAL = "def shipping_rate(g):\n    return 100 + 50 * (g // 1000)\n"
FLAWED = "def shipping_rate(g):\n    return 100 + 50 * max(0, g // 1000 - 1)\n"
CORRECT = "def shipping_rate(g):\n    return 100 + 50 * ((g - 1) // 1000)\n"
SUITE = "from shipping import shipping_rate\ndef test_small():\n    assert shipping_rate(500) == 100\n"
REGRESSION = "from shipping import shipping_rate\ndef test_reported_bug():\n    assert shipping_rate(1000) == 100\ndef test_next_gram():\n    assert shipping_rate(1001) == 150\n"
ISSUE = "Shipping: 1–1000g costs 100; 1001–2000g costs 150. Exactly 1000g is overcharged."


def git_write(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), "-c", "user.name=PatchProof fixture",
                                    "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                                    *args], stderr=subprocess.DEVNULL).decode().strip()


def seed(repo, runtime="pytest"):
    git_write(repo, "init")
    (repo / "tests").mkdir()
    if runtime == "pytest":
        app, suite = "shipping.py", "tests/test_existing.py"
        variants, test, regression = (ORIGINAL, FLAWED, CORRECT), SUITE, REGRESSION
    else:
        app, suite = "shipping.mjs", "tests/existing.test.mjs"
        variants = tuple("export function shippingRate(g) { return " + formula + "; }\n" for formula in (
            "100 + 50 * Math.floor(g / 1000)",
            "100 + 50 * Math.max(0, Math.floor(g / 1000) - 1)",
            "100 + 50 * Math.floor((g - 1) / 1000)"))
        imports = "import {test} from 'node:test';\nimport assert from 'node:assert/strict';\nimport {shippingRate} from '../shipping.mjs';\n"
        test = imports + "test('small', () => assert.equal(shippingRate(500), 100));\n"
        regression = imports + "test('reported bug', () => assert.equal(shippingRate(1000), 100));\ntest('next gram', () => assert.equal(shippingRate(1001), 150));\n"
    (repo / app).write_text(variants[0])
    (repo / suite).write_text(test)
    git_write(repo, "add", "."); git_write(repo, "commit", "-m", "Base fixture")
    base = git_write(repo, "rev-parse", "HEAD")
    lock = lock_inputs(repo, base, ISSUE, regression, [suite], [app], runtime,
                       provenance="scripted fixture; not AI-generated")
    heads = []
    for number, content in enumerate(variants[1:], 1):
        (repo / app).write_text(content)
        git_write(repo, "add", app); git_write(repo, "commit", "-m", f"Candidate {number}")
        heads.append(git_write(repo, "rev-parse", "HEAD"))
    return lock, heads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=["pytest", "node-test"], default="pytest")
    parser.add_argument("--output", default="artifacts/external-demo")
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists(): raise SystemExit("Choose a new output directory")
    with tempfile.TemporaryDirectory() as d:
        lock, heads = seed(Path(d), args.runtime)
        digest = sha(canonical(lock))
        for name, head in zip(("flawed", "corrected"), heads):
            report = verify_external(d, head, lock, digest, LocalExternalFixtureRunner())
            write_report(report, out / name)
            print(name, report["status"])
        (out / "lock.json").write_text(json.dumps(lock, indent=2))
        git_write(Path(d), "bundle", "create", str(out.resolve() / "fixture.bundle"), "--all")


if __name__ == "__main__": main()
