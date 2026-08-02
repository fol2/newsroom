"""Typed component parsing for the exact Increment 5A decision record."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from .contract_types import (
    ComponentDisposition,
    Increment5ContractError,
    RetrievalComponentContract,
    RetrievalComponentKind,
    freeze,
)


def mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment5ContractError(f"{field} must be an object")
    return value


def parse_component(
    value: object,
    digest: str,
    expected_kind: RetrievalComponentKind,
) -> RetrievalComponentContract:
    component = mapping(value, f"component.{expected_kind.value}")
    if digest_bytes(canonical_json_bytes(component)) != digest:
        raise Increment5ContractError(f"{expected_kind.value} component digest differs")
    try:
        kind = RetrievalComponentKind(component["kind"])
        if kind is not expected_kind:
            raise Increment5ContractError("component order differs from reviewed v1")
        return RetrievalComponentContract(
            kind=kind,
            contract_id=str(component["contract_id"]),
            contract_version=str(component["contract_version"]),
            implementation_version=str(component["implementation_version"]),
            disposition=ComponentDisposition(component["disposition"]),
            compatibility_rule=str(component["compatibility_rule"]),
            change_requires=tuple(component["change_requires"]),
            configuration=freeze(component["configuration"]),
            identity_digest=digest,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise Increment5ContractError("component shape differs from reviewed v1") from exc
