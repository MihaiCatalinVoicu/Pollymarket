from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
REGISTRY_ROOT = DATA_ROOT / "registry"
MARKETDATA_ROOT = DATA_ROOT / "marketdata"
RUNTIME_ROOT = DATA_ROOT / "runtime"
RUN_MANIFEST_ROOT = RUNTIME_ROOT / "run_manifests"
REPORTS_ROOT = DATA_ROOT / "reports"
SHADOW_ROOT = DATA_ROOT / "shadow"
MICRO_LIVE_ROOT = DATA_ROOT / "micro_live"


def ensure_data_roots() -> None:
    for path in (
        REGISTRY_ROOT,
        MARKETDATA_ROOT,
        RUNTIME_ROOT,
        RUN_MANIFEST_ROOT,
        REPORTS_ROOT,
        SHADOW_ROOT,
        MICRO_LIVE_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)

