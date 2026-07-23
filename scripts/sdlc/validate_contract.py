from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .contracts import ContractError, load_contract


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the accepted Newsroom SDLC contract")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--contract", default=".sdlc/gates.toml")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        contract = load_contract(Path(arguments.repo_root), arguments.contract)
    except ContractError as exc:
        print(f"CONTRACT_ERROR:{exc}", file=sys.stderr)
        return 2
    summary = {
        "schema_version": "newsroom.sdlc.contract-validation.v1",
        "contract_version": contract.contract_version,
        "risk_tiers": list(sorted(contract.risk_rank, key=contract.risk_rank.__getitem__)),
        "path_groups": sorted(contract.path_groups),
        "sentinels": list(contract.sentinels),
        "status": "PASS",
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
