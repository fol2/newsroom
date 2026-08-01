from __future__ import annotations

import base64
from pathlib import Path


def _emit(label: str, path: str) -> None:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    print(f"NEWSROOM_EXPORT_{label}_BEGIN")
    for offset in range(0, len(encoded), 4096):
        print(encoded[offset : offset + 4096])
    print(f"NEWSROOM_EXPORT_{label}_END")


def test_temporary_export_exact_sdlc_sources() -> None:
    _emit("WORKFLOW_LANE", "scripts/sdlc/workflow_lane.py")
    _emit(
        "WORKFLOW_TESTS",
        "newsroom/tests/test_sdlc_workflow_lane.py",
    )
    raise AssertionError("temporary exact source export")
