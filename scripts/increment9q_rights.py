#!/usr/bin/env python3
"""Increment 9Q-11 Rights Review assess CLI. No network I/O."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from newsroom.increment9.rights import (
    PACKAGE_FIXTURES,
    QualificationError,
    assess,
    evidence_json,
)


def _write_output(path: Path, payload: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RIGHTS_UK-01 qualification evidence."
    )
    parser.add_argument("command", choices=("assess",))
    parser.add_argument("--gate", required=True)
    parser.add_argument("--inventory", default=str(PACKAGE_FIXTURES))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if not args.inventory:
        print("inventory is required", file=sys.stderr)
        return 2
    try:
        evidence = assess(Path(args.inventory), gate=args.gate)
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
