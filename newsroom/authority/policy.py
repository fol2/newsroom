from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .models import CommandDefinition
from .types import PayloadMode, require_token


class UnknownCommandDefinition(LookupError):
    pass


class UnknownPayloadSchema(LookupError):
    pass


class PayloadSchemaValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PayloadSchemaContract:
    """Versioned server-side payload validator and canonicalizer.

    The callable must validate the exact schema and return the canonical bytes that
    enter semantic command identity. A schema label without a registered contract
    cannot authorize a command.
    """

    schema_version: str
    payload_mode: PayloadMode
    canonicalizer: Callable[[Any], bytes]

    def __post_init__(self) -> None:
        require_token(self.schema_version, field="payload_schema_version")
        if not isinstance(self.payload_mode, PayloadMode):
            raise PayloadSchemaValidationError("payload schema mode must be typed")
        if not callable(self.canonicalizer):
            raise PayloadSchemaValidationError("payload schema requires a canonicalizer")

    def canonicalize(self, value: Any) -> bytes:
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


class PayloadSchemaRegistry:
    """Immutable registry of executable payload-schema contracts."""

    def __init__(self, schemas: Iterable[PayloadSchemaContract]) -> None:
        by_key: dict[tuple[str, PayloadMode], PayloadSchemaContract] = {}
        for schema in schemas:
            key = (schema.schema_version, schema.payload_mode)
            if key in by_key:
                raise ValueError(
                    f"duplicate payload schema: {schema.schema_version}/{schema.payload_mode.value}"
                )
            by_key[key] = schema
        if not by_key:
            raise ValueError("payload schema registry requires at least one contract")
        self._by_key = by_key

    def resolve(
        self, schema_version: str, payload_mode: PayloadMode
    ) -> PayloadSchemaContract:
        try:
            return self._by_key[(schema_version, payload_mode)]
        except KeyError as exc:
            raise UnknownPayloadSchema(
                f"{schema_version}/{payload_mode.value}"
            ) from exc


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
                    "multiple command-definition versions require an explicit current version: "
                    f"{command_type}"
                )
            if (command_type, selected_version) not in by_key:
                raise ValueError(
                    f"unknown current command definition: {command_type}/{selected_version}"
                )
            selected[command_type] = selected_version
        if requested:
            raise ValueError(
                f"current version declared for unknown command types: {sorted(requested)}"
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
            raise UnknownCommandDefinition(
                f"{command_type}/{version}"
            ) from exc

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
