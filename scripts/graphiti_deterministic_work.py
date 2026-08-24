"""Generate or verify the provider-free Graphiti #748 qualification packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from newsroom.graphiti_adapter.deterministic_work_fixtures import (
    DETERMINISTIC_WORK_MEASUREMENTS_PATH,
    run_provider_free_qualification,
)


def _render() -> str:
    return (
        json.dumps(
            run_provider_free_qualification(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DETERMINISTIC_WORK_MEASUREMENTS_PATH,
    )
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = _render()
    if arguments.check:
        if not arguments.output.is_file():
            raise SystemExit(f"qualification packet is missing: {arguments.output}")
        if arguments.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                f"qualification packet differs from provider-free replay: "
                f"{arguments.output}"
            )
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    print(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
