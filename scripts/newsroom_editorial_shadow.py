#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence

from newsroom.editorial.legacy_adapter import IntakeError, evaluate_legacy_file
from newsroom.editorial.policy import load_shadow_policy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Credential-free newsroom editorial shadow evaluator",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser(
        "evaluate",
        help="Evaluate one explicit compatibility input without writing governance state",
        allow_abbrev=False,
    )
    evaluate.add_argument("--root-id", required=True)
    evaluate.add_argument("--path", required=True, dest="relative_path")
    evaluate.add_argument("--pretty", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    root_overrides: Mapping[str, Path] | None = None,
) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    policy = load_shadow_policy()
    try:
        if args.command != "evaluate":
            raise IntakeError("unsupported shadow command")
        payload = evaluate_legacy_file(
            root_id=args.root_id,
            relative_path=args.relative_path,
            policy=policy,
            root_overrides=root_overrides,
        )
        rc = 0
    except IntakeError as exc:
        payload = {
            "status": "intake_error",
            "error": {"type": "INTAKE_ERROR", "message": str(exc)},
            "delivery": {"state": "NOT_REQUESTED"},
        }
        rc = 2
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
