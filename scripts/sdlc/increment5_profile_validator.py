#!/usr/bin/env python3
"""Validate one canonical Increment 5 profile in a fresh isolated process.

The receipt proves only that exact bytes passed the reviewed profile structure
and semantic checks in this process. It grants no qualification, production,
component, source, model, provider, spend, write, or public-effect authority.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


_MAX_INPUT_BYTES = 1_048_576
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from newsroom.authority.canonical import (  # noqa: E402
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)
from newsroom.increment5.profiles import (  # noqa: E402
    Increment5ProfileError,
    _check_profile_manifest,
)


class ProfileInputError(ValueError):
    """The isolated validator input is malformed or non-canonical."""


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ProfileInputError(f"duplicate JSON object name: {name}")
        result[name] = value
    return result


def _fail(message: str) -> int:
    sys.stderr.write(f"increment5 profile validation failed: {message}\n")
    return 2


def main() -> int:
    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        return _fail("input exceeds 1048576 bytes")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
        canonical = canonical_json_bytes(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
        ProfileInputError,
    ) as exc:
        return _fail(str(exc))

    if raw != canonical:
        return _fail("input is not canonical JSON")
    if not isinstance(value, dict):
        return _fail("profile manifest must be an object")

    try:
        _check_profile_manifest(value)
    except Increment5ProfileError as exc:
        return _fail(str(exc))

    profile_kind = value.get("profile_kind")
    if not isinstance(profile_kind, str):
        return _fail("profile kind is not canonical text")

    receipt = {
        "authority_effect": "NONE",
        "manifest_digest": digest_bytes(raw),
        "production_activation_authorized": False,
        "profile_kind": profile_kind,
        "qualification_authority_granted": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v1",
        "validation_scope": "REVIEWED_PROFILE_STRUCTURE_AND_SEMANTICS",
    }
    sys.stdout.buffer.write(canonical_json_bytes(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
