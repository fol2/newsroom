"""Checked Increment 6 current-head readiness and ownership allocation.

The repository record reserves identities and migration slots; it does not apply a
migration, mint runtime authority, or enable any external effect.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import inspect
import json
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

import newsroom.authority.migrations as _authority_migrations
import newsroom.discovery as _discovery
import newsroom.increment5._named_tool_authority_receipt_validation_core as _receipt_validation_core
import newsroom.increment5.named_tool_authority_execution as _authority_execution
import newsroom.increment5.named_tool_authority_receipt_validation as _receipt_validation
import newsroom.increment5.named_tool_contracts as _named_tool_contracts
import newsroom.increment5.retrieval_context as _retrieval_context
import newsroom.integrated as _integrated
from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)


EXPECTED_READINESS_DIGEST = (
    "sha256:13b43c927e4222c143b8691eaf179eb956096c19a72f4cc29cae13008d6e0590"
)
READINESS_CONTRACT_PATH = Path(__file__).with_name("increment6_readiness_v1.json")
_INTERFACE_MODULES: Mapping[str, ModuleType] = MappingProxyType(
    {
        "newsroom.authority.migrations": _authority_migrations,
        "newsroom.discovery": _discovery,
        "newsroom.increment5.named_tool_authority_execution": _authority_execution,
        "newsroom.increment5.named_tool_authority_receipt_validation": (
            _receipt_validation
        ),
        "newsroom.increment5._named_tool_authority_receipt_validation_core": (
            _receipt_validation_core
        ),
        "newsroom.increment5.named_tool_contracts": _named_tool_contracts,
        "newsroom.increment5.retrieval_context": _retrieval_context,
        "newsroom.integrated": _integrated,
    }
)


class Increment6ReadinessError(ValueError):
    """The supplied record is not the reviewed Increment 6R contract."""


class GateTier(StrEnum):
    L = "L"
    S = "S"
    M = "M"


@dataclass(frozen=True, slots=True)
class InterfaceCompanion:
    module: str
    symbols: tuple[str, ...]
    symbol_values: Mapping[str, object]
    source_digests: Mapping[str, str]
    symbol_signatures: Mapping[str, str]
    module_source_digest: str | None


@dataclass(frozen=True, slots=True)
class InterfaceInventoryItem:
    interface_id: str
    module: str
    symbols: tuple[str, ...]
    symbol_digests: Mapping[str, str]
    symbol_values: Mapping[str, object]
    source_digests: Mapping[str, str]
    symbol_signatures: Mapping[str, str]
    module_source_digest: str | None
    companions: tuple[InterfaceCompanion, ...]
    boundary: str


@dataclass(frozen=True, slots=True)
class ChildAllocation:
    issue_number: int
    atom: str
    title: str
    dependencies: tuple[int, ...]
    gate_tier: GateTier
    public_modules: tuple[str, ...]
    schema_ids: tuple[str, ...]
    migration_version: int | None
    migration_name: str | None
    migration_module: str | None
    table_names: tuple[str, ...]
    interface_ownership: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Increment6ReadinessContract:
    schema_version: str
    contract_id: str
    contract_version: str
    issue_number: int
    parent_issue_number: int
    accepted_base_commit: str
    accepted_base_tree: str
    accepted_schema_version: int
    accepted_schema_fingerprint: str
    accepted_last_migration_name: str
    accepted_migration_history: tuple[tuple[int, str, str], ...]
    effective_when: str
    production_activation_authorised: bool
    interface_inventory: tuple[InterfaceInventoryItem, ...]
    allocations: tuple[ChildAllocation, ...]
    parallel_waves: Mapping[int, tuple[int, ...]]
    migration_policy: Mapping[str, object]
    rollback: Mapping[str, object]
    gate_requirements: Mapping[GateTier, tuple[str, ...]]
    exclusions: tuple[str, ...]
    contract_digest: str

    @property
    def allocation_by_issue(self) -> Mapping[int, ChildAllocation]:
        return MappingProxyType(
            {item.issue_number: item for item in self.allocations}
        )


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise Increment6ReadinessError(f"duplicate object name: {name}")
        value[name] = item
    return value


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Increment6ReadinessError(f"{field} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise Increment6ReadinessError(f"{field} fields differ")


def _strict_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Increment6ReadinessError(f"{field} must be an integer")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise Increment6ReadinessError(f"{field} must contain non-empty strings")
    return tuple(value)


def _integers(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise Increment6ReadinessError(f"{field} must be an array")
    return tuple(_strict_int(item, field) for item in value)


def _migration_history(
    value: object, field: str
) -> tuple[tuple[int, str, str], ...]:
    if not isinstance(value, list):
        raise Increment6ReadinessError(f"{field} must be an array")
    history: list[tuple[int, str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, list) or len(item) != 3:
            raise Increment6ReadinessError(f"{field}[{index}] must be a triple")
        version = _strict_int(item[0], f"{field}[{index}].version")
        name, checksum = item[1], item[2]
        if not isinstance(name, str) or not name:
            raise Increment6ReadinessError(f"{field}[{index}].name must be text")
        if not isinstance(checksum, str) or not checksum:
            raise Increment6ReadinessError(
                f"{field}[{index}].checksum must be text"
            )
        history.append((version, name, checksum))
    return tuple(history)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({name: _freeze(item) for name, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _frozen_mapping(value: object, field: str) -> Mapping[str, object]:
    raw = _mapping(value, field)
    frozen = _freeze(raw)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded above
        raise Increment6ReadinessError(f"{field} must be an object")
    return frozen


def _parse_companion(value: object, field: str) -> InterfaceCompanion:
    raw = _mapping(value, field)
    allowed = {
        "module",
        "symbols",
        "symbol_values",
        "source_digests",
        "symbol_signatures",
        "module_source_digest",
    }
    if not set(raw) <= allowed or not {"module", "symbols"} <= set(raw):
        raise Increment6ReadinessError(f"{field} fields differ")
    symbol_values = _mapping(raw.get("symbol_values", {}), f"{field}.symbol_values")
    source_digests = _mapping(
        raw.get("source_digests", {}), f"{field}.source_digests"
    )
    symbol_signatures = _mapping(
        raw.get("symbol_signatures", {}), f"{field}.symbol_signatures"
    )
    return InterfaceCompanion(
        module=str(raw["module"]),
        symbols=_strings(raw["symbols"], f"{field}.symbols"),
        symbol_values=MappingProxyType(dict(symbol_values)),
        source_digests=MappingProxyType(
            {str(name): str(item) for name, item in source_digests.items()}
        ),
        symbol_signatures=MappingProxyType(
            {str(name): str(item) for name, item in symbol_signatures.items()}
        ),
        module_source_digest=(
            str(raw["module_source_digest"])
            if raw.get("module_source_digest") is not None
            else None
        ),
    )


def _parse_interface(value: object, index: int) -> InterfaceInventoryItem:
    field = f"interface_inventory[{index}]"
    raw = _mapping(value, field)
    _exact_keys(
        raw,
        {
            "interface_id",
            "module",
            "symbols",
            "symbol_digests",
            "symbol_values",
            "source_digests",
            "symbol_signatures",
            "module_source_digest",
            "companions",
            "boundary",
        },
        field,
    )
    digests = _mapping(raw["symbol_digests"], f"{field}.symbol_digests")
    values = _mapping(raw["symbol_values"], f"{field}.symbol_values")
    source_digests = _mapping(raw["source_digests"], f"{field}.source_digests")
    signatures = _mapping(
        raw["symbol_signatures"], f"{field}.symbol_signatures"
    )
    companions = raw["companions"]
    if not isinstance(companions, list):
        raise Increment6ReadinessError(f"{field}.companions must be an array")
    return InterfaceInventoryItem(
        interface_id=str(raw["interface_id"]),
        module=str(raw["module"]),
        symbols=_strings(raw["symbols"], f"{field}.symbols"),
        symbol_digests=MappingProxyType(
            {str(name): str(item) for name, item in digests.items()}
        ),
        symbol_values=MappingProxyType(dict(values)),
        source_digests=MappingProxyType(
            {str(name): str(item) for name, item in source_digests.items()}
        ),
        symbol_signatures=MappingProxyType(
            {str(name): str(item) for name, item in signatures.items()}
        ),
        module_source_digest=(
            str(raw["module_source_digest"])
            if raw["module_source_digest"] is not None
            else None
        ),
        companions=tuple(
            _parse_companion(item, f"{field}.companions[{position}]")
            for position, item in enumerate(companions)
        ),
        boundary=str(raw["boundary"]),
    )


def _parse_allocation(value: object, index: int) -> ChildAllocation:
    field = f"allocations[{index}]"
    raw = _mapping(value, field)
    _exact_keys(
        raw,
        {
            "issue_number",
            "atom",
            "title",
            "dependencies",
            "gate_tier",
            "public_modules",
            "schema_ids",
            "migration_version",
            "migration_name",
            "migration_module",
            "table_names",
            "interface_ownership",
        },
        field,
    )
    migration_version = raw["migration_version"]
    if migration_version is not None:
        migration_version = _strict_int(
            migration_version, f"{field}.migration_version"
        )
    for optional_name in ("migration_name", "migration_module"):
        if raw[optional_name] is not None and not isinstance(raw[optional_name], str):
            raise Increment6ReadinessError(f"{field}.{optional_name} must be text")
    return ChildAllocation(
        issue_number=_strict_int(raw["issue_number"], f"{field}.issue_number"),
        atom=str(raw["atom"]),
        title=str(raw["title"]),
        dependencies=_integers(raw["dependencies"], f"{field}.dependencies"),
        gate_tier=GateTier(str(raw["gate_tier"])),
        public_modules=_strings(raw["public_modules"], f"{field}.public_modules"),
        schema_ids=_strings(raw["schema_ids"], f"{field}.schema_ids"),
        migration_version=migration_version,
        migration_name=(
            str(raw["migration_name"])
            if raw["migration_name"] is not None
            else None
        ),
        migration_module=(
            str(raw["migration_module"])
            if raw["migration_module"] is not None
            else None
        ),
        table_names=_strings(raw["table_names"], f"{field}.table_names"),
        interface_ownership=_strings(
            raw["interface_ownership"], f"{field}.interface_ownership"
        ),
    )


def _validate_allocation(contract: Increment6ReadinessContract) -> None:
    expected_issues = tuple(range(354, 369))
    if tuple(item.issue_number for item in contract.allocations) != expected_issues:
        raise Increment6ReadinessError("Increment 6 child inventory differs")

    def require_unique(values: list[str | int], field: str) -> None:
        if len(values) != len(set(values)):
            raise Increment6ReadinessError(f"{field} is multiply owned")

    require_unique(
        [name for item in contract.allocations for name in item.public_modules],
        "public module",
    )
    require_unique(
        [name for item in contract.allocations for name in item.schema_ids],
        "schema identity",
    )
    require_unique(
        [name for item in contract.allocations for name in item.table_names],
        "table name",
    )
    require_unique(
        [
            name
            for item in contract.allocations
            for name in item.interface_ownership
        ],
        "public interface",
    )

    migration_allocations = [
        item for item in contract.allocations if item.migration_version is not None
    ]
    require_unique(
        [item.migration_version for item in migration_allocations if item.migration_version],
        "migration version",
    )
    require_unique(
        [item.migration_name for item in migration_allocations if item.migration_name],
        "migration name",
    )
    require_unique(
        [item.migration_module for item in migration_allocations if item.migration_module],
        "migration module",
    )
    if tuple(sorted(item.migration_version for item in migration_allocations)) != tuple(
        range(17, 26)
    ):
        raise Increment6ReadinessError("migration reservation is not contiguous")
    for item in contract.allocations:
        fields = (
            item.migration_version,
            item.migration_name,
            item.migration_module,
        )
        if any(value is None for value in fields) != all(
            value is None for value in fields
        ):
            raise Increment6ReadinessError("migration ownership is incomplete")

    wave_issues = tuple(
        issue
        for issues in contract.parallel_waves.values()
        for issue in issues
    )
    if tuple(sorted(wave_issues)) != expected_issues:
        raise Increment6ReadinessError(
            "parallel waves must allocate every child exactly once"
        )
    wave_by_issue = {
        issue: wave
        for wave, issues in contract.parallel_waves.items()
        for issue in issues
    }
    for item in contract.allocations:
        if len(item.dependencies) != len(set(item.dependencies)):
            raise Increment6ReadinessError("dependency is repeated")
        for dependency in item.dependencies:
            if dependency in wave_by_issue and (
                wave_by_issue[dependency] >= wave_by_issue[item.issue_number]
            ):
                raise Increment6ReadinessError("parallel wave precedes its dependency")

    migration_merge_order = tuple(
        item.migration_version
        for item in sorted(
            migration_allocations,
            key=lambda item: (wave_by_issue[item.issue_number], item.issue_number),
        )
    )
    if migration_merge_order != tuple(range(17, 26)):
        raise Increment6ReadinessError(
            "migration reservation conflicts with admitted merge waves"
        )


def load_increment6_readiness_contract(path: Path) -> Increment6ReadinessContract:
    """Load the one exact canonical 6R record and validate its allocations."""

    if not isinstance(path, Path):
        raise Increment6ReadinessError("readiness path must be a pathlib.Path")
    try:
        raw = path.read_bytes()
        record = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
        canonical = canonical_json_bytes(record)
    except Increment6ReadinessError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, CanonicalizationError) as exc:
        raise Increment6ReadinessError("cannot read canonical Increment 6R contract") from exc
    if raw != canonical:
        raise Increment6ReadinessError("readiness record must use exact canonical JSON")
    contract_digest = digest_bytes(raw)
    if contract_digest != EXPECTED_READINESS_DIGEST:
        raise Increment6ReadinessError("readiness bytes differ from reviewed v1")

    try:
        top = _mapping(record, "contract")
        _exact_keys(top, {"schema_version", "payload"}, "contract")
        payload = _mapping(top["payload"], "payload")
        _exact_keys(
            payload,
            {
                "contract_id",
                "contract_version",
                "issue_number",
                "parent_issue_number",
                "accepted_base",
                "effective_when",
                "production_activation_authorised",
                "interface_inventory",
                "allocations",
                "parallel_waves",
                "migration_policy",
                "rollback",
                "gate_requirements",
                "exclusions",
            },
            "payload",
        )
        accepted = _mapping(payload["accepted_base"], "accepted_base")
        _exact_keys(
            accepted,
            {
                "commit",
                "tree",
                "schema_version",
                "schema_fingerprint",
                "last_migration_name",
                "migration_history",
            },
            "accepted_base",
        )
        raw_interfaces = payload["interface_inventory"]
        raw_allocations = payload["allocations"]
        raw_waves = payload["parallel_waves"]
        raw_gates = _mapping(payload["gate_requirements"], "gate_requirements")
        if not isinstance(raw_interfaces, list) or not isinstance(raw_allocations, list):
            raise Increment6ReadinessError("inventory and allocations must be arrays")
        if not isinstance(raw_waves, list):
            raise Increment6ReadinessError("parallel_waves must be an array")
        waves: dict[int, tuple[int, ...]] = {}
        for index, value in enumerate(raw_waves):
            wave = _mapping(value, f"parallel_waves[{index}]")
            _exact_keys(wave, {"wave", "issues"}, f"parallel_waves[{index}]")
            number = _strict_int(wave["wave"], f"parallel_waves[{index}].wave")
            if number in waves:
                raise Increment6ReadinessError("duplicate parallel wave")
            waves[number] = _integers(
                wave["issues"], f"parallel_waves[{index}].issues"
            )
        gate_requirements = MappingProxyType(
            {
                GateTier(name): _strings(items, f"gate_requirements.{name}")
                for name, items in raw_gates.items()
            }
        )
        production_activation_authorised = payload[
            "production_activation_authorised"
        ]
        if not isinstance(production_activation_authorised, bool):
            raise Increment6ReadinessError(
                "production_activation_authorised must be boolean"
            )
        contract = Increment6ReadinessContract(
            schema_version=str(top["schema_version"]),
            contract_id=str(payload["contract_id"]),
            contract_version=str(payload["contract_version"]),
            issue_number=_strict_int(payload["issue_number"], "issue_number"),
            parent_issue_number=_strict_int(
                payload["parent_issue_number"], "parent_issue_number"
            ),
            accepted_base_commit=str(accepted["commit"]),
            accepted_base_tree=str(accepted["tree"]),
            accepted_schema_version=_strict_int(
                accepted["schema_version"], "accepted_base.schema_version"
            ),
            accepted_schema_fingerprint=str(accepted["schema_fingerprint"]),
            accepted_last_migration_name=str(accepted["last_migration_name"]),
            accepted_migration_history=_migration_history(
                accepted["migration_history"],
                "accepted_base.migration_history",
            ),
            effective_when=str(payload["effective_when"]),
            production_activation_authorised=production_activation_authorised,
            interface_inventory=tuple(
                _parse_interface(item, index)
                for index, item in enumerate(raw_interfaces)
            ),
            allocations=tuple(
                _parse_allocation(item, index)
                for index, item in enumerate(raw_allocations)
            ),
            parallel_waves=MappingProxyType(dict(sorted(waves.items()))),
            migration_policy=_frozen_mapping(
                payload["migration_policy"], "migration_policy"
            ),
            rollback=_frozen_mapping(payload["rollback"], "rollback"),
            gate_requirements=gate_requirements,
            exclusions=_strings(payload["exclusions"], "exclusions"),
            contract_digest=contract_digest,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, Increment6ReadinessError):
            raise
        raise Increment6ReadinessError("readiness shape differs from reviewed v1") from exc

    if (
        contract.schema_version != "newsroom.increment6.readiness.v1"
        or contract.contract_id
        != "increment6-current-head-readiness-and-allocation"
        or contract.contract_version != "increment6-readiness-v1"
        or contract.issue_number != 354
        or contract.parent_issue_number != 146
        or contract.accepted_base_commit
        != "ba0832b4d0ac7b9a65f318beb266889c9dcd9f2e"
        or contract.accepted_base_tree
        != "069f19698f8bfe6d0f8453219ccd961c89be94c4"
        or contract.accepted_schema_version != 16
        or tuple(item[0] for item in contract.accepted_migration_history)
        != tuple(range(1, 17))
        or contract.accepted_migration_history[-1][1]
        != contract.accepted_last_migration_name
        or contract.effective_when != "PRESENT_ON_MAIN_AFTER_REVIEWED_6R_MERGE"
        or contract.production_activation_authorised
    ):
        raise Increment6ReadinessError("readiness boundary differs from reviewed v1")
    if set(contract.gate_requirements) != set(GateTier):
        raise Increment6ReadinessError("gate tier inventory differs")
    _validate_allocation(contract)
    return contract


def _validate_module_anchor(
    *,
    module_name: str,
    symbols: tuple[str, ...],
    expected_values: Mapping[str, object],
    source_digests: Mapping[str, str],
    symbol_signatures: Mapping[str, str],
    module_source_digest: str | None,
) -> list[str]:
    errors: list[str] = []
    module = _INTERFACE_MODULES.get(module_name)
    if module is None:
        return [f"{module_name}: module is outside the reviewed inventory"]
    if module_source_digest is not None:
        module_path = getattr(module, "__file__", None)
        try:
            raw_module = Path(module_path).read_bytes()
        except (OSError, TypeError):
            errors.append(f"{module_name}: module source is unavailable")
        else:
            if digest_bytes(raw_module) != module_source_digest:
                errors.append(f"{module_name}: module source differs")
    for symbol in symbols:
        if not hasattr(module, symbol):
            errors.append(f"{module_name}:{symbol}: missing")
    for symbol, expected in expected_values.items():
        if not hasattr(module, symbol):
            errors.append(f"{module_name}:{symbol}: missing")
        elif getattr(module, symbol) != expected:
            errors.append(f"{module_name}:{symbol}: value differs")
    for symbol, expected in source_digests.items():
        if not hasattr(module, symbol):
            continue
        try:
            source = inspect.getsource(getattr(module, symbol)).encode("utf-8")
        except (OSError, TypeError):
            errors.append(f"{module_name}:{symbol}: source is unavailable")
        else:
            if digest_bytes(source) != expected:
                errors.append(f"{module_name}:{symbol}: source differs")
    for symbol, expected in symbol_signatures.items():
        if not hasattr(module, symbol):
            continue
        try:
            actual = str(inspect.signature(getattr(module, symbol)))
        except (TypeError, ValueError):
            errors.append(f"{module_name}:{symbol}: signature is unavailable")
        else:
            if actual != expected:
                errors.append(f"{module_name}:{symbol}: signature differs")
    return errors


def _validate_schema_prefix(
    contract: Increment6ReadinessContract,
) -> list[str]:
    """Admit additive successors while retaining the exact accepted v16 prefix."""

    errors: list[str] = []
    history = _authority_migrations.EXPECTED_MIGRATION_HISTORY
    accepted = contract.accepted_migration_history
    if (
        not isinstance(history, tuple)
        or len(history) < len(accepted)
        or history[: len(accepted)] != accepted
    ):
        errors.append("newsroom.authority.migrations: accepted history prefix differs")
    suffix = history[len(accepted) :] if isinstance(history, tuple) else ()
    expected_names = {
        item.migration_version: item.migration_name
        for item in contract.allocations
        if item.migration_version is not None
    }
    for index, entry in enumerate(suffix, start=contract.accepted_schema_version + 1):
        if not isinstance(entry, tuple) or len(entry) != 3:
            errors.append("newsroom.authority.migrations: suffix entry is malformed")
            continue
        version, name, checksum = entry
        if version != index:
            errors.append("newsroom.authority.migrations: suffix is not contiguous")
        expected_name = expected_names.get(index)
        if expected_name is not None and name != expected_name:
            errors.append(
                f"newsroom.authority.migrations: reserved v{index} name differs"
            )
        try:
            validate_sha256_digest(checksum, field="migration checksum")
        except (TypeError, ValueError):
            errors.append(
                f"newsroom.authority.migrations: v{index} checksum is malformed"
            )
    if (
        isinstance(_authority_migrations.SCHEMA_VERSION, bool)
        or not isinstance(_authority_migrations.SCHEMA_VERSION, int)
        or _authority_migrations.SCHEMA_VERSION < contract.accepted_schema_version
    ):
        errors.append("newsroom.authority.migrations: schema version regressed")
    elif (
        isinstance(history, tuple)
        and history
        and history[-1][0] != _authority_migrations.SCHEMA_VERSION
    ):
        errors.append("newsroom.authority.migrations: live history/version differ")
    if (
        _authority_migrations.SCHEMA_VERSION == contract.accepted_schema_version
        and _authority_migrations.EXPECTED_SCHEMA_FINGERPRINT
        != contract.accepted_schema_fingerprint
    ):
        errors.append("newsroom.authority.migrations: accepted fingerprint differs")
    return errors


def validate_interface_inventory(
    contract: Increment6ReadinessContract,
) -> tuple[str, ...]:
    """Return exact current-interface drift findings without granting authority."""

    if not isinstance(contract, Increment6ReadinessContract):
        raise Increment6ReadinessError("interface inventory contract must be typed")
    errors: list[str] = []
    for item in contract.interface_inventory:
        expected = dict(item.symbol_values)
        expected.update(item.symbol_digests)
        errors.extend(
            _validate_module_anchor(
                module_name=item.module,
                symbols=item.symbols,
                expected_values=expected,
                source_digests=item.source_digests,
                symbol_signatures=item.symbol_signatures,
                module_source_digest=item.module_source_digest,
            )
        )
        for companion in item.companions:
            errors.extend(
                _validate_module_anchor(
                    module_name=companion.module,
                    symbols=companion.symbols,
                    expected_values=companion.symbol_values,
                    source_digests=companion.source_digests,
                    symbol_signatures=companion.symbol_signatures,
                    module_source_digest=companion.module_source_digest,
                )
            )
    errors.extend(_validate_schema_prefix(contract))
    return tuple(sorted(errors))


INCREMENT_6_READINESS = load_increment6_readiness_contract(
    READINESS_CONTRACT_PATH
)
INCREMENT_6_READINESS_DIGEST = INCREMENT_6_READINESS.contract_digest


__all__ = [
    "EXPECTED_READINESS_DIGEST",
    "INCREMENT_6_READINESS",
    "INCREMENT_6_READINESS_DIGEST",
    "READINESS_CONTRACT_PATH",
    "ChildAllocation",
    "GateTier",
    "Increment6ReadinessContract",
    "Increment6ReadinessError",
    "InterfaceCompanion",
    "InterfaceInventoryItem",
    "load_increment6_readiness_contract",
    "validate_interface_inventory",
]
