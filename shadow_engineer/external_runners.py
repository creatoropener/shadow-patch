import json
import os
from pathlib import Path
import uuid
from . import execution_harness
from .repository import sha


class LocalExternalFixtureRunner:
    """Internal test/demo runner. Intentionally not exposed for arbitrary repos by CLI."""
    name = "local-fixture"
    metadata = {"live_cloud": False, "isolation": "temporary directory; trusted fixture only"}

    def run(self, payload):
        result = execution_harness.execute(payload)
        return {**result, "execution_id": str(uuid.uuid4())}


def build_sdk():
    # Pinned PyPI 0.3.6 uses config/auth directly, unlike the newer docs API.
    from contree_sdk import ContreeSync
    from contree_sdk.auth import IAMAuth
    from contree_sdk.config import ContreeConfig
    return ContreeSync(ContreeConfig(
        auth=IAMAuth(token=os.environ.get("CONTREE_TOKEN") or os.environ["NEBIUS_API_KEY"],
                     base_url=os.environ["CONTREE_BASE_URL"]),
        transport_timeout=15, operation_timeout=90, operation_run_timeout=90))


class NebiusExternalRunner:
    name = "nebius-contree"

    def __init__(self):
        image_id = str(uuid.UUID(os.environ["CONTREE_IMAGE"]))
        self.sdk = build_sdk()
        self.image = self.sdk.images.use(image_id, strict=True)
        self.harness = Path(execution_harness.__file__)
        self.metadata = {"image_uuid": image_id, "contree_sdk": "0.3.6",
                         "harness_sha256": sha(self.harness.read_bytes()),
                         "live_cloud": True, "test_timeout_seconds": 30,
                         "operation_timeout_seconds": 90}

    def run(self, payload):
        result = self.image.run(
            shell="python3 /patchproof_harness.py",
            files={"patchproof_harness.py": str(self.harness)},
            stdin=json.dumps({**payload, "require_uid_separation": True}),
            timeout=60, disposable=True, truncate_output_at=3 * 1024 * 1024).wait()
        if result.exit_code != 0:
            raise RuntimeError("Nebius execution harness failed")
        parsed = json.loads(result.stdout)
        if not isinstance(parsed, dict): raise ValueError("Invalid provider evidence")
        # Disposable executions may not retain a resulting image UUID.
        parsed["result_image_uuid"] = str(result.uuid) if result.uuid else None
        return parsed
