"""Emit a provider-free Graphiti steady-state evidence packet."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from newsroom.control_plane.graphiti_steady_state import (
    build_graphiti_steady_state_packet,
    write_content_addressed_packet,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        check=True,
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    ).stdout.strip()


def _exact_main_identity() -> tuple[str, str]:
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("steady-state evidence requires a clean worktree")
    head_sha = _git("rev-parse", "HEAD")
    if head_sha != _git("rev-parse", "origin/main"):
        raise RuntimeError("steady-state evidence requires exact origin/main")
    return head_sha, _git("rev-parse", "HEAD^{tree}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proving", required=True)
    parser.add_argument("--unpublished", required=True)
    parser.add_argument("--authority")
    parser.add_argument("--campaign-input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    head_sha, tree_sha = _exact_main_identity()
    campaign_input = (
        json.loads(args.campaign_input.read_text(encoding="utf-8"))
        if args.campaign_input is not None
        else None
    )
    if campaign_input is not None and not isinstance(campaign_input, dict):
        raise ValueError("campaign input must be a JSON object")
    packet = build_graphiti_steady_state_packet(
        proving_store=args.proving,
        unpublished_store=args.unpublished,
        head_sha=head_sha,
        tree_sha=tree_sha,
        observed_at=datetime.now(tz=UTC),
        authority_store=args.authority,
        campaign_input=campaign_input,
    )
    if _exact_main_identity() != (head_sha, tree_sha):
        raise RuntimeError("code identity changed while building steady-state evidence")
    if args.output_dir is None:
        print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(write_content_addressed_packet(packet, args.output_dir))
    return 0 if packet["verdict"] == "READY_FOR_OWNER_DECISION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
