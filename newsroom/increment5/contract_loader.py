"""Load the exact source-governed Increment 5A retrieval contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)

from .contract_components import mapping, parse_component
from .contract_types import (
    ContractEffect,
    ContractStatus,
    Increment5AContract,
    Increment5ContractError,
    RetrievalComponentKind,
    RetrievalMode,
    RetrievalProfileKind,
    freeze,
)

EXPECTED_CONTRACT_DIGEST = (
    "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
)
EXPECTED_IMPLEMENTATION_BASE = "3ea1874de5e1bd6c622a3760eabb74adfe75d169"


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise Increment5ContractError(f"duplicate object name: {name}")
        value[name] = item
    return value


def load_increment5a_contract(path: Path) -> Increment5AContract:
    """Return an immutable view only when bytes equal the reviewed v1 content."""

    if not isinstance(path, Path):
        raise Increment5ContractError("contract path must be a pathlib.Path")
    try:
        raw = path.read_bytes()
        record = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
        canonical = canonical_json_bytes(record)
    except (OSError, UnicodeError, json.JSONDecodeError, CanonicalizationError) as exc:
        raise Increment5ContractError("cannot read canonical Increment 5A contract") from exc
    if raw != canonical:
        raise Increment5ContractError("contract record must use exact canonical JSON")
    contract_digest = digest_bytes(raw)
    if contract_digest != EXPECTED_CONTRACT_DIGEST:
        payload = record.get("payload") if isinstance(record, dict) else None
        if isinstance(payload, dict) and payload.get("production_activation_authorized") is True:
            raise Increment5ContractError("Increment 5A cannot activate production")
        raise Increment5ContractError(
            "contract bytes differ from reviewed v1; component digest identities differ"
        )

    try:
        top = mapping(record, "contract")
        payload = mapping(top["payload"], "payload")
        payload_digest = str(top["payload_digest"])
        if digest_bytes(canonical_json_bytes(payload)) != payload_digest:
            raise Increment5ContractError("payload digest differs")
        component_digests = dict(mapping(top["component_digests"], "component_digests"))
        raw_components = list(payload["components"])
        kinds = tuple(RetrievalComponentKind)
        if len(raw_components) != len(kinds) or frozenset(component_digests) != frozenset(
            kind.value for kind in kinds
        ):
            raise Increment5ContractError("component inventory differs from reviewed v1")
        components = tuple(
            parse_component(item, component_digests[kind.value], kind)
            for item, kind in zip(raw_components, kinds, strict=True)
        )
        contract = Increment5AContract(
            schema_version=str(top["schema_version"]),
            contract_id=str(payload["contract_id"]),
            contract_version=str(payload["contract_version"]),
            status=ContractStatus(payload["decision_status"]),
            effect=ContractEffect(payload["effect"]),
            owner=str(payload["owner"]),
            accepted_date=str(payload["accepted_date"]),
            implementation_base=str(payload["implementation_base"]),
            issue_number=int(payload["issue_number"]),
            parent_issue_number=int(payload["parent_issue_number"]),
            programme_issue_number=int(payload["programme_issue_number"]),
            pr_number=int(payload["pr_number"]),
            effective_when=str(payload["effective_when"]),
            approved_profiles=tuple(
                RetrievalProfileKind(item) for item in payload["approved_profiles"]
            ),
            required_modes=tuple(RetrievalMode(item) for item in payload["required_modes"]),
            named_tools=tuple(payload["named_tools"]),
            components=components,
            component_digests=MappingProxyType(component_digests),
            profile_schema_digests=MappingProxyType(
                dict(payload["profile_schema_digests"])
            ),
            payload_digest=payload_digest,
            contract_digest=contract_digest,
            payload=freeze(payload),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, Increment5ContractError):
            raise
        raise Increment5ContractError("contract shape differs from reviewed v1") from exc

    if (
        contract.schema_version != "newsroom.increment5a.retrieval-contract.v1"
        or contract.implementation_base != EXPECTED_IMPLEMENTATION_BASE
        or contract.production_activation_authorized
        or contract.approved_profiles != tuple(RetrievalProfileKind)
        or contract.required_modes != tuple(RetrievalMode)
    ):
        raise Increment5ContractError("contract boundary differs from reviewed v1")
    return contract
