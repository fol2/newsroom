from __future__ import annotations

from collections.abc import Iterable

from .models import CommandDefinition


class UnknownCommandDefinition(LookupError):
    pass


class CommandRegistry:
    """Immutable versioned server-side command-definition registry."""

    def __init__(self, definitions: Iterable[CommandDefinition]) -> None:
        by_type: dict[str, CommandDefinition] = {}
        for definition in definitions:
            if definition.command_type in by_type:
                raise ValueError(
                    f"duplicate command definition: {definition.command_type}"
                )
            by_type[definition.command_type] = definition
        if not by_type:
            raise ValueError("command registry requires at least one definition")
        self._by_type = by_type

    def resolve(self, command_type: str) -> CommandDefinition:
        try:
            return self._by_type[command_type]
        except KeyError as exc:
            raise UnknownCommandDefinition(command_type) from exc

    def definitions(self) -> tuple[CommandDefinition, ...]:
        return tuple(self._by_type[key] for key in sorted(self._by_type))
