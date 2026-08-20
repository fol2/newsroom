#!/usr/bin/env python3
"""Hermes Control Plane private editorial-beta CLI. No public dispatch."""

from __future__ import annotations

import argparse
import json
import sys
import time

from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.graphiti import EvaluationGraphitiRunner
from newsroom.control_plane.intake import run_intake
from newsroom.control_plane.store import list_payloads
from newsroom.control_plane.veto import VetoError
from newsroom.control_plane.writer import default_writer
from newsroom.graphiti_adapter.models import REAL_GRAPHITI_RUNTIME_ENABLED

DEFAULT_PROVING = "data/newsroom/proving_store.sqlite3"
DEFAULT_UNPUBLISHED = "data/newsroom/unpublished_store.sqlite3"


def _cycle(args: argparse.Namespace):
    return run_cycle(
        proving_store=args.proving,
        unpublished_store=args.unpublished,
        writer=default_writer(),
        max_writes=args.max_writes,
        graphiti=EvaluationGraphitiRunner() if REAL_GRAPHITI_RUNTIME_ENABLED else None,
        max_graphiti=1,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Private unpublished editorial beta (no AUTO_PUBLISH)."
    )
    parser.add_argument("command", choices=("cycle", "status", "serve", "intake"))
    parser.add_argument("--proving", default=DEFAULT_PROVING)
    parser.add_argument("--unpublished", default=DEFAULT_UNPUBLISHED)
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--max-writes", type=int, default=5)
    args = parser.parse_args(argv)
    if args.command == "status":
        payloads = list_payloads(args.unpublished)
        body = {
            "count": len(payloads),
            "public_dispatch": False,
            "auto_publish": False,
            "payloads": [
                {
                    "story_candidate_id": item.story_candidate_id,
                    "title": item.title,
                    "evidence_package_digest": item.evidence_package_digest,
                    "source_lineage": list(item.source_lineage),
                    "generated_at": item.generated_at,
                    "status": item.status,
                    "writer_id": item.writer_id,
                    "publication_bundle": item.publication_bundle,
                }
                for item in payloads
            ],
        }
        sys.stdout.write(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        return 0
    if args.command == "intake":
        intake = run_intake(proving_store=args.proving)
        sys.stdout.write(
            json.dumps(
                {
                    "proving_run_id": intake.proving_run_id,
                    "authorised": intake.authorised,
                    "complete": intake.complete,
                    "ok": intake.ok,
                    "sources": intake.sources,
                    "public_dispatch": False,
                    "auto_publish": False,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return 0 if intake.authorised else 2
    if args.command == "cycle":
        report = _cycle(args)
        sys.stdout.write(
            json.dumps(
                {
                    "proving_run_id": report.proving_run_id,
                    "minted": report.minted,
                    "duplicate": report.duplicate,
                    "sources": report.sources,
                    "candidates": report.candidates,
                    "writer_id": report.writer_id,
                    "graphiti": report.graphiti,
                    "ledger_digest": report.ledger_digest,
                    "public_dispatch": False,
                    "auto_publish": False,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        return 0
    while True:
        try:
            intake = run_intake(proving_store=args.proving)
            print(
                f"intake run={intake.proving_run_id} authorised={intake.authorised} "
                f"ok={intake.ok}/{intake.sources} complete={intake.complete}",
                flush=True,
            )
            report = _cycle(args)
            print(
                f"cycle run={report.proving_run_id} minted={report.minted} "
                f"duplicate={report.duplicate} candidates={report.candidates} "
                f"writer={report.writer_id} graphiti={report.graphiti}",
                flush=True,
            )
        except (VetoError, ValueError, OSError, RuntimeError) as exc:
            print(f"cycle refused: {exc}", flush=True)
        time.sleep(max(args.interval, 30))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
