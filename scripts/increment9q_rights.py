#!/usr/bin/env python3
"""Increment 9Q Rights Review assess CLI. No network I/O."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from newsroom.increment9.rights import (
    QualificationError,
    assess,
    evidence_json,
    fixtures_for,
)


def _write_output(path: Path, payload: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "RIGHTS_UK-01, RIGHTS_UK-02, RIGHTS_UK-03, RIGHTS_UK-05, "
            "RIGHTS_UK-10 and RIGHTS_HK-01 qualification evidence."
        )
    )
    parser.add_argument("command", choices=("assess",))
    parser.add_argument("--gate", required=True)
    parser.add_argument("--inventory")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.inventory is not None and not args.inventory:
        print("inventory is required", file=sys.stderr)
        return 2
    try:
        inventory = Path(args.inventory) if args.inventory else fixtures_for(args.gate)
        evidence = assess(inventory, gate=args.gate)
    except QualificationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = evidence_json(evidence)
    sys.stdout.buffer.write(payload)
    sys.stdout.write("\n")
    if args.output:
        _write_output(Path(args.output), payload + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
