"""Inspect or reclaim obsolete native retrieval hydration diagnostics offline."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from newsroom.authority.audit_retention import prune_native_diagnostic_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Exact Newsroom data directory containing increment4 and native stores")
    parser.add_argument("--apply", action="store_true",
                        help="Prune verified obsolete diagnostics and VACUUM in place; default is read-only inspection")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    report = prune_native_diagnostic_audit(args.data_root, apply=args.apply)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 1 if report.get("compaction_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
