#!/usr/bin/env python3
"""Increment 9Q-1 non-mutation assess CLI. No network I/O."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from newsroom.increment9.qualification import QualificationError, assess, evidence_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PRODUCTION_NONMUTATION_BASELINE qualification evidence."
    )
    parser.add_argument("command", choices=("assess",))
    parser.add_argument("--inventory")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if not args.inventory:
        print("inventory is required", file=sys.stderr)
        return 2
    try:
        evidence = assess(Path(args.inventory))
    except QualificationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    payload = evidence_json(evidence)
    sys.stdout.buffer.write(payload)
    sys.stdout.write("\n")
    if args.output:
        Path(args.output).write_bytes(payload + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
