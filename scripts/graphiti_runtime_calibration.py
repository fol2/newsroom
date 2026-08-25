#!/usr/bin/env python3
"""Provider-free #771 runtime calibration packet."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from newsroom.graphiti_adapter.runtime_calibration import (
    CalibrationClosed,
    run_provider_free_runtime_calibration,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.execute:
        raise CalibrationClosed(
            "owner-gated live packet remains unauthorised; provider calls=0"
        )
    print(
        json.dumps(
            run_provider_free_runtime_calibration().as_record(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
