"""Emit a provider-free Graphiti steady-state evidence packet."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.graphiti_steady_state import (
    AdmissionRuntimeComposition,
    build_graphiti_steady_state_packet,
    write_content_addressed_packet,
)


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proving", required=True)
    parser.add_argument("--unpublished", required=True)
    parser.add_argument(
        "--admission-runtime",
        choices=[item.value for item in AdmissionRuntimeComposition],
        default=AdmissionRuntimeComposition.UNCOMPOSED.value,
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    packet = build_graphiti_steady_state_packet(
        proving_store=args.proving,
        unpublished_store=args.unpublished,
        head_sha=_git("rev-parse", "HEAD"),
        tree_sha=_git("rev-parse", "HEAD^{tree}"),
        observed_at=datetime.now(tz=UTC),
        admission_runtime=AdmissionRuntimeComposition(args.admission_runtime),
    )
    if args.output_dir is None:
        print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(write_content_addressed_packet(packet, args.output_dir))
    return 0 if packet["verdict"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
