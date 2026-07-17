from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .canonical import canonical_json_bytes, digest_bytes
from .models import CommandDefinition
from .types import PayloadMode, require_token


class UnknownCommandDefinition(LookupError):
    pass


class UnknownPayloadSchema(LookupError):
    pass


class PayloadSchemaValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PayloadGoldenVector:
    """Named executable evidence for one canonical payload representation."""

    name: str
    input_identity: str
    value: Any = field(repr=False, compare=False)
    expected_bytes: bytes = b""

    def __post_init__(self) -> None:
        require_token(self.name, field="payload_golden_vector_name")
        require_token(self.input_identity, field="payload_golden_input_identity")
        if not isinstance(self.expected_bytes, bytes):
            raise PayloadSchemaValidationError(
                "payload golden-vector output must be immutable bytes"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "name": self.name,
            "input_identity": self.input_identity,
            "expected_digest": digest_bytes(self.expected_bytes),
            "expected_size": len(self.expected_bytes),
        }


@dataclass(frozen=True, slots=True)
class PayloadSchemaContract:
    """Immutable identity plus executable validator/canonicalizer.

    Python callables are deliberately not hashed. The contract identity is
    explicit versioned metadata plus named golden outputs, and registry
    construction executes those vectors so an implementation cannot silently
    retain the same identity while changing covered canonical behaviour.
    """

    schema_version: str
    payload_mode: PayloadMode
    contract_version: str
    canonicalizer_implementation_version: str
    canonicalizer: Callable[[Any], bytes] = field(repr=False, compare=False)
    golden_vectors: tuple[PayloadGoldenVector, ...] = ()

    def __post_init__(self) -> None:
        require_token(self.schema_version, field="payload_schema_version")
        if not isinstance(self.payload_mode, PayloadMode):
            raise PayloadSchemaValidationError("payload schema mode must be typed")
        require_token(self.contract_version, field="payload_schema_contract_version")
        require_token(
            self.canonicalizer_implementation_version,
            field="payload_canonicalizer_implementation_version",
        )
        if not callable(self.canonicalizer):
            raise PayloadSchemaValidationError("payload schema requires a canonicalizer")
        if not isinstance(self.golden_vectors, tuple) or not self.golden_vectors:
            raise PayloadSchemaValidationError(
                "payload schema requires at least one immutable golden vector"
            )
        names = [vector.name for vector in self.golden_vectors]
        if len(names) != len(set(names)):
            raise PayloadSchemaValidationError(
                "payload golden-vector names must be unique"
            )
        for vector in self.golden_vectors:
            if not isinstance(vector, PayloadGoldenVector):
                raise PayloadSchemaValidationError(
                    "payload golden vectors must be typed"
                )
            actual = self._canonicalize(vector.value)
            if actual != vector.expected_bytes:
                raise PayloadSchemaValidationError(
                    "payload canonicalizer does not match golden vector "
                    f"{vector.name}"
                )

    def _canonicalize(self, value: Any) -> bytes:
        try:
            result = self.canonicalizer(value)
        except PayloadSchemaValidationError:
            raise
        except Exception as exc:
            raise PayloadSchemaValidationError(
                f"payload failed schema {self.schema_version}: {exc}"
            ) from exc
        if not isinstance(result, bytes):
            raise PayloadSchemaValidationError(
                "payload canonicalizer must return immutable bytes"
            )
        return result

    def canonicalize(self, value: Any) -> bytes:
        return self._canonicalize(value)

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "payload_mode": self.payload_mode.value,
            "contract_version": self.contract_version,
            "canonicalizer_implementation_version": (
                self.canonicalizer_implementation_version
            ),
            "golden_vectors": [
                vector.canonical_value()
                for vector in sorted(self.golden_vectors, key=lambda item: item.name)
            ],
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))


class PayloadSchemaRegistry:
    """Immutable registry retaining every schema contract in the replay horizon."""

    def __init__(
        self,
        schemas: Iterable[PayloadSchemaContract],
        *,
        current_versions: Mapping[tuple[str, PayloadMode], str] | None = None,
    ) -> None:
        by_key: dict[tuple[str, PayloadMode, str], PayloadSchemaContract] = {}
        versions_by_schema: dict[tuple[str, PayloadMode], list[str]] = {}
        for schema in schemas:
            key = (schema.schema_version, schema.payload_mode, schema.contract_version)
            if key in by_key:
                raise ValueError(
                    "duplicate payload schema contract: "
                    f"{schema.schema_version}/{schema.payload_mode.value}/"
                    f"{schema.contract_version}"
                )
            by_key[key] = schema
            versions_by_schema.setdefault(
                (schema.schema_version, schema.payload_mode), []
            ).append(schema.contract_version)
        if not by_key:
            raise ValueError("payload schema registry requires at least one contract")

        requested = dict(current_versions or {})
        selected: dict[tuple[str, PayloadMode], str] = {}
        for schema_key, versions in versions_by_schema.items():
            if schema_key in requested:
                version = requested.pop(schema_key)
            elif len(versions) == 1:
                version = versions[0]
            else:
                raise ValueError(
                    "multiple payload-schema contract versions require an "
                    f"explicit current version: {schema_key[0]}/{schema_key[1].value}"
                )
            if (*schema_key, version) not in by_key:
                raise ValueError(
                    "unknown current payload-schema contract: "
                    f"{schema_key[0]}/{schema_key[1].value}/{version}"
                )
            selected[schema_key] = version
        if requested:
            raise ValueError(
                "current version declared for unknown payload schemas: "
                f"{sorted((key[0], key[1].value) for key in requested)}"
            )
        self._by_key = by_key
        self._current_versions = selected

    def resolve(
        self,
        schema_version: str,
        payload_mode: PayloadMode,
        contract_version: str | None = None,
    ) -> PayloadSchemaContract:
        version = (
            self._current_versions.get((schema_version, payload_mode))
            if contract_version is None
            else contract_version
        )
        if version is None:
            raise UnknownPayloadSchema(f"{schema_version}/{payload_mode.value}")
        try:
            return self._by_key[(schema_version, payload_mode, version)]
        except KeyError as exc:
            raise UnknownPayloadSchema(
                f"{schema_version}/{payload_mode.value}/{version}"
            ) from exc

    def resolve_exact(
        self,
        schema_version: str,
        payload_mode: PayloadMode,
        contract_version: str,
        contract_digest: str,
        canonicalizer_implementation_version: str,
    ) -> PayloadSchemaContract:
        contract = self.resolve(schema_version, payload_mode, contract_version)
        if contract.contract_digest != contract_digest:
            raise UnknownPayloadSchema(
                "retained payload-schema contract digest does not match "
                "command-definition identity"
            )
        if (
            contract.canonicalizer_implementation_version
            != canonicalizer_implementation_version
        ):
            raise UnknownPayloadSchema(
                "retained payload canonicalizer version does not match "
                "command-definition identity"
            )
        return contract

    def contracts(self) -> tuple[PayloadSchemaContract, ...]:
        return tuple(
            self._by_key[key]
            for key in sorted(
                self._by_key,
                key=lambda item: (item[0], item[1].value, item[2]),
            )
        )


class CommandRegistry:
    """Immutable server-side command-definition registry with retained history."""

    def __init__(
        self,
        definitions: Iterable[CommandDefinition],
        *,
        current_versions: Mapping[str, str] | None = None,
    ) -> None:
        by_key: dict[tuple[str, str], CommandDefinition] = {}
        versions_by_type: dict[str, list[str]] = {}
        for definition in definitions:
            key = (definition.command_type, definition.definition_version)
            if key in by_key:
                raise ValueError(
                    "duplicate command definition: "
                    f"{definition.command_type}/{definition.definition_version}"
                )
            by_key[key] = definition
            versions_by_type.setdefault(definition.command_type, []).append(
                definition.definition_version
            )
        if not by_key:
            raise ValueError("command registry requires at least one definition")

        selected: dict[str, str] = {}
        requested = dict(current_versions or {})
        for command_type, versions in versions_by_type.items():
            if command_type in requested:
                selected_version = requested.pop(command_type)
            elif len(versions) == 1:
                selected_version = versions[0]
            else:
                raise ValueError(
                    "multiple command-definition versions require an explicit "
                    f"current version: {command_type}"
                )
            if (command_type, selected_version) not in by_key:
                raise ValueError(
                    f"unknown current command definition: "
                    f"{command_type}/{selected_version}"
                )
            selected[command_type] = selected_version
        if requested:
            raise ValueError(
                f"current version declared for unknown command types: "
                f"{sorted(requested)}"
            )

        self._by_key = by_key
        self._current_versions = selected

    def resolve(
        self, command_type: str, definition_version: str | None = None
    ) -> CommandDefinition:
        version = (
            self._current_versions.get(command_type)
            if definition_version is None
            else definition_version
        )
        if version is None:
            raise UnknownCommandDefinition(command_type)
        try:
            return self._by_key[(command_type, version)]
        except KeyError as exc:
            raise UnknownCommandDefinition(f"{command_type}/{version}") from exc

    def resolve_exact(
        self, command_type: str, definition_version: str, definition_digest: str
    ) -> CommandDefinition:
        definition = self.resolve(command_type, definition_version)
        if definition.digest != definition_digest:
            raise UnknownCommandDefinition(
                "retained command definition digest does not match committed identity"
            )
        return definition

    def definitions(self) -> tuple[CommandDefinition, ...]:
        return tuple(self._by_key[key] for key in sorted(self._by_key))
