"""Provider-free measurements and owner-gated packet for #747."""

from __future__ import annotations

import argparse
import json
import sys

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    LIVE_PACKET_PATH,
    MEASUREMENTS_PATH,
    measure_token_effectiveness,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record provider-free #747 combined-temporal measurements."
    )
    parser.add_argument(
        "--write-measurements",
        action="store_true",
        help="overwrite the committed measurements JSON",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="refused: live dispatch is owner-gated and not implemented here",
    )
    parser.add_argument("--authorised-by-owner", action="store_true")
    args = parser.parse_args(argv)
    if args.execute or args.authorised_by_owner:
        raise SystemExit(
            "live calibration is owner-gated; this runner is provider-free only"
        )
    measurements = measure_token_effectiveness()
    encoded = canonical_json_bytes(measurements).decode("utf-8") + "\n"
    if args.write_measurements:
        MEASUREMENTS_PATH.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    packet = json.loads(LIVE_PACKET_PATH.read_text(encoding="utf-8"))
    if packet["live_authority"]["authorised"] is not False:
        raise SystemExit("committed live packet must remain unauthorised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
