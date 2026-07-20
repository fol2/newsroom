from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable

from .canonical import canonical_json_bytes, digest_canonical
from .models import CommandDefinition
from .objects import (
    HydrationPolicyContract,
    ObjectAdmissionDefinition,
    ObjectPolicyError,
    RightsPolicyContract,
)
from .policy import (
    CommandRegistry,
    PayloadGoldenVector,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
)
from .types import PayloadMode, TrustScope, require_token


class UnknownObjectAdmissionDefinition(LookupError):
    pass


class UnknownRightsPolicyContract(LookupError):
    pass


class UnknownHydrationPolicyContract(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class RightsPolicyRegistry:
    """Immutable retained rights-policy contracts with behaviour in the digest."""

    _by_digest: Mapping[str, RightsPolicyContract]
    _by_key: Mapping[tuple[str, str], RightsPolicyContract]
    _current_versions: Mapping[str, str]

    def __init__(
        self,
        contracts: Iterable[RightsPolicyContract],
        *,
        current_versions: Mapping[str, str] | None = None,
    ) -> None:
        by_digest: dict[str, RightsPolicyContract] = {}
        by_key: dict[tuple[str, str], RightsPolicyContract] = {}
        versions: dict[str, list[str]] = {}
        for contract in contracts:
            if not isinstance(contract, RightsPolicyContract):
                raise ObjectPolicyError("rights registry accepts typed contracts only")
            key = (contract.policy_key, contract.contract_version)
            if key in by_key or contract.contract_digest in by_digest:
                raise ObjectPolicyError(
                    "duplicate rights-policy contract identity: "
                    f"{contract.policy_key}/{contract.contract_version}"
                )
            by_key[key] = contract
            by_digest[contract.contract_digest] = contract
            versions.setdefault(contract.policy_key, []).append(
                contract.contract_version
            )
        if not by_key:
            raise ObjectPolicyError("rights-policy registry cannot be empty")
        requested = dict(current_versions or {})
        selected: dict[str, str] = {}
        for policy_key, available in versions.items():
            if policy_key in requested:
                version = requested.pop(policy_key)
            elif len(available) == 1:
                version = available[0]
            else:
                raise ObjectPolicyError(
                    "multiple rights-policy versions require an explicit current "
                    f"version: {policy_key}"
                )
            if (policy_key, version) not in by_key:
                raise ObjectPolicyError(
                    f"unknown current rights-policy contract: {policy_key}/{version}"
                )
            selected[policy_key] = version
        if requested:
            raise ObjectPolicyError(
                "current rights-policy version declared for unknown keys: "
                f"{sorted(requested)}"
            )
        object.__setattr__(self, "_by_digest", MappingProxyType(dict(by_digest)))
        object.__setattr__(self, "_by_key", MappingProxyType(dict(by_key)))
        object.__setattr__(
            self, "_current_versions", MappingProxyType(dict(selected))
        )

    def resolve(
        self, policy_key: str, contract_version: str | None = None
    ) -> RightsPolicyContract:
        require_token(policy_key, field="rights_policy_key")
        version = (
            self._current_versions.get(policy_key)
            if contract_version is None
            else contract_version
        )
        if version is None:
            raise UnknownRightsPolicyContract(policy_key)
        try:
            return self._by_key[(policy_key, version)]
        except KeyError as exc:
            raise UnknownRightsPolicyContract(
                f"{policy_key}/{version}"
            ) from exc

    def resolve_digest(self, contract_digest: str) -> RightsPolicyContract:
        try:
            return self._by_digest[contract_digest]
        except KeyError as exc:
            raise UnknownRightsPolicyContract(contract_digest) from exc

    def resolve_exact(
        self,
        policy_key: str,
        contract_version: str,
        contract_digest: str,
    ) -> RightsPolicyContract:
        contract = self.resolve(policy_key, contract_version)
        if contract.contract_digest != contract_digest:
            raise UnknownRightsPolicyContract(
                "retained rights-policy contract digest mismatch"
            )
        return contract

    def contracts(self) -> tuple[RightsPolicyContract, ...]:
        return tuple(
            self._by_key[key]
            for key in sorted(self._by_key, key=lambda item: (item[0], item[1]))
        )


@dataclass(frozen=True, slots=True)
class HydrationPolicyRegistry:
    """Immutable purpose-to-policy registry with retained historical contracts."""

    _by_digest: Mapping[str, HydrationPolicyContract]
    _by_key: Mapping[tuple[str, str], HydrationPolicyContract]
    _current_versions: Mapping[str, str]
    _purpose_to_policy: Mapping[str, str]

    def __init__(
        self,
        contracts: Iterable[HydrationPolicyContract],
        *,
        current_versions: Mapping[str, str] | None = None,
        purpose_to_policy: Mapping[str, str] | None = None,
    ) -> None:
        by_digest: dict[str, HydrationPolicyContract] = {}
        by_key: dict[tuple[str, str], HydrationPolicyContract] = {}
        versions: dict[str, list[str]] = {}
        purpose_map: dict[str, str] = dict(purpose_to_policy or {})
        for contract in contracts:
            if not isinstance(contract, HydrationPolicyContract):
                raise ObjectPolicyError(
                    "hydration registry accepts typed contracts only"
                )
            key = (contract.policy_id, contract.contract_version)
            if key in by_key or contract.contract_digest in by_digest:
                raise ObjectPolicyError(
                    "duplicate hydration-policy contract identity: "
                    f"{contract.policy_id}/{contract.contract_version}"
                )
            by_key[key] = contract
            by_digest[contract.contract_digest] = contract
            versions.setdefault(contract.policy_id, []).append(
                contract.contract_version
            )
            existing_policy = purpose_map.get(contract.purpose)
            if existing_policy is None:
                purpose_map[contract.purpose] = contract.policy_id
            elif existing_policy != contract.policy_id:
                raise ObjectPolicyError(
                    "multiple hydration policies for one purpose require an "
                    "explicit unambiguous mapping"
                )
        if not by_key:
            raise ObjectPolicyError("hydration-policy registry cannot be empty")
        requested = dict(current_versions or {})
        selected: dict[str, str] = {}
        for policy_id, available in versions.items():
            if policy_id in requested:
                version = requested.pop(policy_id)
            elif len(available) == 1:
                version = available[0]
            else:
                raise ObjectPolicyError(
                    "multiple hydration-policy versions require an explicit "
                    f"current version: {policy_id}"
                )
            if (policy_id, version) not in by_key:
                raise ObjectPolicyError(
                    f"unknown current hydration policy: {policy_id}/{version}"
                )
            selected[policy_id] = version
        if requested:
            raise ObjectPolicyError(
                "current hydration-policy version declared for unknown IDs: "
                f"{sorted(requested)}"
            )
        for purpose, policy_id in purpose_map.items():
            require_token(purpose, field="hydration_purpose")
            if policy_id not in selected:
                raise ObjectPolicyError(
                    f"purpose {purpose} names unknown hydration policy {policy_id}"
                )
            current = by_key[(policy_id, selected[policy_id])]
            if current.purpose != purpose:
                raise ObjectPolicyError(
                    "hydration purpose mapping differs from retained policy contract"
                )
        object.__setattr__(self, "_by_digest", MappingProxyType(dict(by_digest)))
        object.__setattr__(self, "_by_key", MappingProxyType(dict(by_key)))
        object.__setattr__(
            self, "_current_versions", MappingProxyType(dict(selected))
        )
        object.__setattr__(
            self, "_purpose_to_policy", MappingProxyType(dict(purpose_map))
        )

    def resolve(
        self, policy_id: str, contract_version: str | None = None
    ) -> HydrationPolicyContract:
        require_token(policy_id, field="hydration_policy_id")
        version = (
            self._current_versions.get(policy_id)
            if contract_version is None
            else contract_version
        )
        if version is None:
            raise UnknownHydrationPolicyContract(policy_id)
        try:
            return self._by_key[(policy_id, version)]
        except KeyError as exc:
            raise UnknownHydrationPolicyContract(
                f"{policy_id}/{version}"
            ) from exc

    def resolve_for_purpose(self, purpose: str) -> HydrationPolicyContract:
        require_token(purpose, field="hydration_purpose")
        try:
            policy_id = self._purpose_to_policy[purpose]
        except KeyError as exc:
            raise UnknownHydrationPolicyContract(
                f"no hydration policy for purpose {purpose}"
            ) from exc
        return self.resolve(policy_id)

    def resolve_digest(self, digest: str) -> HydrationPolicyContract:
        try:
            return self._by_digest[digest]
        except KeyError as exc:
            raise UnknownHydrationPolicyContract(digest) from exc

    def resolve_exact(
        self,
        policy_id: str,
        contract_version: str,
        contract_digest: str,
    ) -> HydrationPolicyContract:
        contract = self.resolve(policy_id, contract_version)
        if contract.contract_digest != contract_digest:
            raise UnknownHydrationPolicyContract(
                "retained hydration-policy contract digest mismatch"
            )
        return contract

    def contracts(self) -> tuple[HydrationPolicyContract, ...]:
        return tuple(
            self._by_key[key]
            for key in sorted(self._by_key, key=lambda item: (item[0], item[1]))
        )


@dataclass(frozen=True, slots=True)
class ObjectAdmissionRegistry:
    """Immutable retained object-use definitions bound to exact policies."""

    _by_key: Mapping[tuple[str, str], ObjectAdmissionDefinition]
    _by_digest: Mapping[str, ObjectAdmissionDefinition]
    _current_versions: Mapping[str, str]

    def __init__(
        self,
        definitions: Iterable[ObjectAdmissionDefinition],
        *,
        rights_policies: RightsPolicyRegistry,
        hydration_policies: HydrationPolicyRegistry,
        current_versions: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(rights_policies, RightsPolicyRegistry) or not isinstance(
            hydration_policies, HydrationPolicyRegistry
        ):
            raise ObjectPolicyError(
                "admission registry requires exact rights and hydration registries"
            )
        by_key: dict[tuple[str, str], ObjectAdmissionDefinition] = {}
        by_digest: dict[str, ObjectAdmissionDefinition] = {}
        versions: dict[str, list[str]] = {}
        for definition in definitions:
            if not isinstance(definition, ObjectAdmissionDefinition):
                raise ObjectPolicyError(
                    "object admission registry accepts typed definitions only"
                )
            rights_policies.resolve_digest(
                definition.rights_policy_contract_digest
            )
            for digest in definition.hydration_policy_contract_digests:
                hydration_policies.resolve_digest(digest)
            key = (definition.admission_type, definition.definition_version)
            if key in by_key or definition.digest in by_digest:
                raise ObjectPolicyError(
                    "duplicate object admission definition: "
                    f"{definition.admission_type}/{definition.definition_version}"
                )
            by_key[key] = definition
            by_digest[definition.digest] = definition
            versions.setdefault(definition.admission_type, []).append(
                definition.definition_version
            )
        if not by_key:
            raise ObjectPolicyError("object admission registry cannot be empty")
        requested = dict(current_versions or {})
        selected: dict[str, str] = {}
        for admission_type, available in versions.items():
            if admission_type in requested:
                version = requested.pop(admission_type)
            elif len(available) == 1:
                version = available[0]
            else:
                raise ObjectPolicyError(
                    "multiple admission-definition versions require an explicit "
                    f"current version: {admission_type}"
                )
            if (admission_type, version) not in by_key:
                raise ObjectPolicyError(
                    f"unknown current admission definition: {admission_type}/{version}"
                )
            selected[admission_type] = version
        if requested:
            raise ObjectPolicyError(
                "current version declared for unknown admission types: "
                f"{sorted(requested)}"
            )
        object.__setattr__(self, "_by_key", MappingProxyType(dict(by_key)))
        object.__setattr__(self, "_by_digest", MappingProxyType(dict(by_digest)))
        object.__setattr__(
            self, "_current_versions", MappingProxyType(dict(selected))
        )

    def resolve(
        self, admission_type: str, definition_version: str | None = None
    ) -> ObjectAdmissionDefinition:
        require_token(admission_type, field="admission_type")
        version = (
            self._current_versions.get(admission_type)
            if definition_version is None
            else definition_version
        )
        if version is None:
            raise UnknownObjectAdmissionDefinition(admission_type)
        try:
            return self._by_key[(admission_type, version)]
        except KeyError as exc:
            raise UnknownObjectAdmissionDefinition(
                f"{admission_type}/{version}"
            ) from exc

    def resolve_digest(self, digest: str) -> ObjectAdmissionDefinition:
        try:
            return self._by_digest[digest]
        except KeyError as exc:
            raise UnknownObjectAdmissionDefinition(digest) from exc

    def resolve_exact(
        self,
        admission_type: str,
        definition_version: str,
        definition_digest: str,
    ) -> ObjectAdmissionDefinition:
        definition = self.resolve(admission_type, definition_version)
        if definition.digest != definition_digest:
            raise UnknownObjectAdmissionDefinition(
                "retained object admission definition digest mismatch"
            )
        return definition

    def definitions(self) -> tuple[ObjectAdmissionDefinition, ...]:
        return tuple(self._by_key[key] for key in sorted(self._by_key))


LIFECYCLE_COMMAND_TYPES: frozenset[str] = frozenset(
    {
        "object.admission.activate",
        "object.admission.revoke",
        "object.deletion.request",
        "object.deletion.tombstone",
        "object.deletion.complete",
        "object.deletion.fail",
        "object.recovery_pin.create",
        "object.recovery_pin.release",
        "object.orphan.remove",
    }
)


_LIFECYCLE_SPECS: tuple[
    tuple[str, str, str, frozenset[str], str], ...
] = (
    (
        "object.admission.activate",
        "governed_object.admission.activated",
        "object_admission_activated_v1",
        frozenset(
            {
                "operation_id",
                "admission_id",
                "blob_digest",
                "size_bytes",
                "definition_digest",
                "rights_decision_id",
                "object_class",
                "allowed_use",
                "security_scope",
                "retention_scope",
                "valid_from",
                "valid_until",
            }
        ),
        "authority.objects.lifecycle.write",
    ),
    (
        "object.admission.revoke",
        "governed_object.admission.revoked",
        "object_admission_revoked_v1",
        frozenset({"operation_id", "admission_id", "reason_code"}),
        "authority.objects.manage",
    ),
    (
        "object.deletion.request",
        "governed_blob.deletion.requested",
        "object_deletion_requested_v1",
        frozenset({"operation_id", "deletion_id", "blob_digest", "reason_code"}),
        "authority.objects.manage",
    ),
    (
        "object.deletion.tombstone",
        "governed_blob.deletion.tombstoned",
        "object_deletion_tombstoned_v1",
        frozenset({"operation_id", "deletion_id", "blob_digest", "reason_code"}),
        "authority.objects.manage",
    ),
    (
        "object.deletion.complete",
        "governed_blob.deletion.completed",
        "object_deletion_completed_v1",
        frozenset({"operation_id", "deletion_id", "blob_digest"}),
        "authority.objects.manage",
    ),
    (
        "object.deletion.fail",
        "governed_blob.deletion.failed",
        "object_deletion_failed_v1",
        frozenset({"operation_id", "deletion_id", "blob_digest", "error_code"}),
        "authority.objects.manage",
    ),
    (
        "object.recovery_pin.create",
        "governed_blob.recovery_pin.created",
        "object_recovery_pin_created_v1",
        frozenset({"operation_id", "pin_id", "blob_digest", "reason_code"}),
        "authority.objects.manage",
    ),
    (
        "object.recovery_pin.release",
        "governed_blob.recovery_pin.released",
        "object_recovery_pin_released_v1",
        frozenset({"operation_id", "pin_id", "blob_digest", "reason_code"}),
        "authority.objects.manage",
    ),
    (
        "object.orphan.remove",
        "governed_blob.orphan.removed",
        "object_orphan_removed_v1",
        frozenset({"operation_id", "blob_digest", "size_bytes"}),
        "authority.objects.manage",
    ),
)


def _strict_mapping_canonicalizer(
    required_keys: frozenset[str],
) -> Callable[[Any], bytes]:
    def canonicalize(value: Any) -> bytes:
        if not isinstance(value, dict):
            raise ValueError("lifecycle payload must be an object")
        if set(value) != set(required_keys):
            raise ValueError(
                "lifecycle payload fields differ from retained schema contract"
            )
        return canonical_json_bytes(value)

    return canonicalize


def object_lifecycle_payload_contracts() -> tuple[PayloadSchemaContract, ...]:
    contracts: list[PayloadSchemaContract] = []
    for command_type, _event_type, schema_version, keys, _scope in _LIFECYCLE_SPECS:
        canonicalizer = _strict_mapping_canonicalizer(keys)
        example: dict[str, object] = {
            key: (
                1
                if key == "size_bytes"
                else None
                if key == "valid_until"
                else f"fixture-{key.replace('_', '-')}"
            )
            for key in sorted(keys)
        }
        # Digests and UUIDs are payload strings here; the authoritative writer
        # validates typed values before constructing the internal command.
        expected = canonicalizer(example)
        contracts.append(
            PayloadSchemaContract(
                schema_version=schema_version,
                payload_mode=PayloadMode.INLINE,
                contract_version="object-lifecycle-schema-v1",
                canonicalizer_implementation_version=(
                    "object-lifecycle-canonicalizer-v1"
                ),
                canonicalizer=canonicalizer,
                golden_vectors=(
                    PayloadGoldenVector(
                        name=f"{command_type.replace('.', '_')}_fixture",
                        input_identity=f"{schema_version}-fixture-v1",
                        value=example,
                        expected_bytes=expected,
                    ),
                ),
            )
        )
    return tuple(contracts)


def object_lifecycle_command_definitions() -> tuple[CommandDefinition, ...]:
    schemas = {
        contract.schema_version: contract
        for contract in object_lifecycle_payload_contracts()
    }
    definitions: list[CommandDefinition] = []
    for command_type, event_type, schema_version, _keys, required_scope in _LIFECYCLE_SPECS:
        contract = schemas[schema_version]
        definitions.append(
            CommandDefinition(
                command_type=command_type,
                definition_version="object-lifecycle-command-v1",
                aggregate_type="governed_object_lifecycle",
                event_type=event_type,
                event_schema_version=1,
                payload_mode=PayloadMode.INLINE,
                payload_schema_version=contract.schema_version,
                payload_schema_contract_version=contract.contract_version,
                payload_schema_contract_digest=contract.contract_digest,
                payload_canonicalizer_version=(
                    contract.canonicalizer_implementation_version
                ),
                trust_scope=TrustScope.ADMITTED,
                security_scope="authority.object_lifecycle",
                retention_scope="authority.audit",
                required_scope=required_scope,
                max_inline_bytes=16 * 1024,
            )
        )
    return tuple(definitions)


def merge_authority_registries(
    *,
    command_registry: CommandRegistry,
    payload_schemas: PayloadSchemaRegistry,
) -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    """Return immutable A1 registries including exact lifecycle contracts."""

    definitions = list(command_registry.definitions())
    by_key = {
        (item.command_type, item.definition_version): item for item in definitions
    }
    for definition in object_lifecycle_command_definitions():
        key = (definition.command_type, definition.definition_version)
        existing = by_key.get(key)
        if existing is not None and existing.digest != definition.digest:
            raise ObjectPolicyError(
                f"lifecycle command identity conflict: {definition.command_type}"
            )
        if existing is None:
            definitions.append(definition)
            by_key[key] = definition
    current_commands: dict[str, str] = {}
    for command_type in {item.command_type for item in definitions}:
        if command_type in LIFECYCLE_COMMAND_TYPES:
            current_commands[command_type] = "object-lifecycle-command-v1"
        else:
            current_commands[command_type] = command_registry.resolve(
                command_type
            ).definition_version

    contracts = list(payload_schemas.contracts())
    schema_keys = {
        (item.schema_version, item.payload_mode, item.contract_version): item
        for item in contracts
    }
    for contract in object_lifecycle_payload_contracts():
        key = (
            contract.schema_version,
            contract.payload_mode,
            contract.contract_version,
        )
        existing = schema_keys.get(key)
        if existing is not None and existing.contract_digest != contract.contract_digest:
            raise ObjectPolicyError(
                f"lifecycle payload-schema identity conflict: {contract.schema_version}"
            )
        if existing is None:
            contracts.append(contract)
            schema_keys[key] = contract
    current_schemas: dict[tuple[str, PayloadMode], str] = {}
    lifecycle_schema_versions = {
        item.schema_version for item in object_lifecycle_payload_contracts()
    }
    for schema_version, mode in {
        (item.schema_version, item.payload_mode) for item in contracts
    }:
        if schema_version in lifecycle_schema_versions:
            current_schemas[(schema_version, mode)] = "object-lifecycle-schema-v1"
        else:
            current_schemas[(schema_version, mode)] = payload_schemas.resolve(
                schema_version, mode
            ).contract_version

    return (
        CommandRegistry(definitions, current_versions=current_commands),
        PayloadSchemaRegistry(contracts, current_versions=current_schemas),
    )


__all__ = [
    "HydrationPolicyRegistry",
    "LIFECYCLE_COMMAND_TYPES",
    "ObjectAdmissionRegistry",
    "RightsPolicyRegistry",
    "UnknownHydrationPolicyContract",
    "UnknownObjectAdmissionDefinition",
    "UnknownRightsPolicyContract",
    "merge_authority_registries",
    "object_lifecycle_command_definitions",
    "object_lifecycle_payload_contracts",
]
