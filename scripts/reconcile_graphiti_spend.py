#!/usr/bin/env python3
"""Plan provider-free Graphiti spend reconciliation for authenticated apply."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from newsroom.control_plane.graphiti_spend_reconciliation import (
    GraphitiSpendReconciliationError,
    plan_graphiti_spend_reconciliation,
)


def _evaluated_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "evaluated-at must be an ISO-8601 instant"
        ) from exc
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def _journal_evidence(path: str | None) -> dict[str, Mapping[str, object]]:
    if path is None:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphitiSpendReconciliationError(
            "graph journal evidence is not readable canonical JSON"
        ) from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, dict) for key, item in value.items()
    ):
        raise GraphitiSpendReconciliationError(
            "graph journal evidence must map spend IDs to evidence objects"
        )
    return value


def _write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Graphiti spend reconciliation plan. Apply belongs to "
            "the authenticated ControlPlaneCommandService."
        )
    )
    parser.add_argument("mode", choices=("dry-run",))
    parser.add_argument("--unpublished", required=True)
    parser.add_argument("--evaluated-at", required=True, type=_evaluated_at)
    parser.add_argument("--journal-evidence")
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        plan = plan_graphiti_spend_reconciliation(
            args.unpublished,
            evaluated_at=args.evaluated_at,
            graph_journal_evidence=_journal_evidence(args.journal_evidence),
        )
        value = plan.as_dict()
        _write(Path(args.receipt), value)
    except (GraphitiSpendReconciliationError, OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
