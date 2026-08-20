"""Durable Neo4j mutation journal and exact Graphiti completion marker."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes


_RESERVED_PREFIX = "_newsroom_"
_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SNAPSHOT_NODE = "NewsroomSnapshotNode"
_SNAPSHOT_RELATIONSHIP = "NewsroomSnapshotRelationship"
_MARKER = "NewsroomIngestMarker"


class GuardError(RuntimeError):
    """The proposal generation could not be proved unchanged or recoverable."""


class GuardState(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    RECOVERED_AMBIGUOUS = "RECOVERED_AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class GuardMarker:
    state: GuardState
    attempt_number: int
    input_digest: str
    chat_invocations: tuple[dict[str, object], ...] = ()
    embedding_usage: dict[str, object] | None = None


def _normalise(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return value


def _record_value(record: object, key: str) -> object:
    if isinstance(record, dict):
        return record.get(key)
    try:
        return record[key]  # type: ignore[index]
    except (KeyError, TypeError):
        return None


class Neo4jMutationGuard:
    """Journal a generation before provider work and restore existing values."""

    __slots__ = (
        "_attempt_number",
        "_driver",
        "_episode_uuid",
        "_group_id",
        "_input_digest",
        "_snapshot_id",
    )

    def __init__(
        self,
        driver: Any,
        *,
        group_id: str,
        episode_uuid: str,
        attempt_number: int,
        input_digest: str,
    ) -> None:
        self._driver = driver
        self._group_id = group_id
        self._episode_uuid = episode_uuid
        self._attempt_number = attempt_number
        self._input_digest = input_digest
        self._snapshot_id = f"{episode_uuid}:{attempt_number}"

    async def _query(self, query: str, **parameters: object) -> list[object]:
        records, _, _ = await self._driver.execute_query(
            query, params=parameters, routing_="w"
        )
        return list(records)

    async def _marker(self) -> dict[str, object] | None:
        records = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            RETURN properties(m) AS marker
            """,
            episode_uuid=self._episode_uuid,
        )
        if not records:
            return None
        marker = _record_value(records[0], "marker")
        return dict(marker) if isinstance(marker, dict) else None

    def _bind_marker(self, raw: dict[str, object]) -> GuardMarker:
        if (
            str(raw.get("group_id") or "") != self._group_id
            or str(raw.get("input_digest") or "") != self._input_digest
        ):
            raise GuardError("Graphiti guard marker identity differs from this input")
        try:
            state = GuardState(str(raw["state"]))
            attempt_number = int(raw["attempt_number"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GuardError("Graphiti guard marker is malformed") from exc
        invocations: tuple[dict[str, object], ...] = ()
        embedding_usage: dict[str, object] | None = None
        try:
            parsed_invocations = json.loads(str(raw.get("chat_invocations_json") or "[]"))
            parsed_usage = json.loads(str(raw.get("embedding_usage_json") or "null"))
        except json.JSONDecodeError as exc:
            raise GuardError("Graphiti guard telemetry is malformed") from exc
        if isinstance(parsed_invocations, list) and all(
            isinstance(item, dict) for item in parsed_invocations
        ):
            invocations = tuple(dict(item) for item in parsed_invocations)
        if isinstance(parsed_usage, dict):
            embedding_usage = dict(parsed_usage)
        return GuardMarker(
            state=state,
            attempt_number=attempt_number,
            input_digest=self._input_digest,
            chat_invocations=invocations,
            embedding_usage=embedding_usage,
        )

    async def begin(self) -> GuardMarker:
        retained = await self._marker()
        if retained is not None:
            if str(retained.get("state")) == "SNAPSHOTTING":
                if (
                    str(retained.get("group_id") or "") != self._group_id
                    or str(retained.get("input_digest") or "") != self._input_digest
                ):
                    raise GuardError(
                        "Graphiti guard marker identity differs from this input"
                    )
                await self._delete_snapshot()
                await self._delete_marker()
                return await self.begin()
            marker = self._bind_marker(retained)
            if marker.state is GuardState.COMPLETE:
                return marker
            if marker.state is GuardState.RECOVERED_AMBIGUOUS:
                if self._attempt_number <= marker.attempt_number:
                    return marker
                await self._delete_marker()
            else:
                return marker

        await self._query(
            f"""
            CREATE (m:{_MARKER} {{
                episode_uuid: $episode_uuid,
                group_id: $group_id,
                attempt_number: $attempt_number,
                input_digest: $input_digest,
                snapshot_id: $snapshot_id,
                state: 'SNAPSHOTTING',
                chat_invocations_json: '[]',
                embedding_usage_json: 'null'
            }})
            """,
            episode_uuid=self._episode_uuid,
            group_id=self._group_id,
            attempt_number=self._attempt_number,
            input_digest=self._input_digest,
            snapshot_id=self._snapshot_id,
        )
        await self._snapshot()
        await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            SET m.state = 'PENDING'
            """,
            episode_uuid=self._episode_uuid,
        )
        return GuardMarker(
            state=GuardState.CREATED,
            attempt_number=self._attempt_number,
            input_digest=self._input_digest,
        )

    async def _snapshot(self) -> None:
        unsafe = await self._query(
            f"""
            MATCH (n)
            WHERE n.group_id = $group_id
              AND NOT n:{_SNAPSHOT_NODE}
              AND NOT n:{_SNAPSHOT_RELATIONSHIP}
              AND NOT n:{_MARKER}
              AND (
                  n.uuid IS NULL
                  OR any(key IN keys(n) WHERE key STARTS WITH $reserved_prefix)
              )
            RETURN count(n) AS unsafe_nodes
            """,
            group_id=self._group_id,
            reserved_prefix=_RESERVED_PREFIX,
        )
        if unsafe and int(_record_value(unsafe[0], "unsafe_nodes") or 0):
            raise GuardError(
                "Graphiti generation has no stable UUID or uses reserved guard properties"
            )
        unsafe_relationships = await self._query(
            """
            MATCH (a)-[r]->(b)
            WHERE (a.group_id = $group_id OR b.group_id = $group_id)
              AND (r.uuid IS NULL OR a.uuid IS NULL OR b.uuid IS NULL)
            RETURN count(r) AS unsafe_relationships
            """,
            group_id=self._group_id,
        )
        if unsafe_relationships and int(
            _record_value(unsafe_relationships[0], "unsafe_relationships") or 0
        ):
            raise GuardError("Graphiti generation relationship has no stable UUID")
        await self._query(
            f"""
            MATCH (n)
            WHERE n.group_id = $group_id
              AND NOT n:{_SNAPSHOT_NODE}
              AND NOT n:{_SNAPSHOT_RELATIONSHIP}
              AND NOT n:{_MARKER}
            CREATE (s:{_SNAPSHOT_NODE})
            SET s = properties(n)
            SET s._newsroom_snapshot_id = $snapshot_id,
                s._newsroom_source_uuid = n.uuid,
                s._newsroom_source_labels = labels(n)
            """,
            group_id=self._group_id,
            snapshot_id=self._snapshot_id,
        )
        await self._query(
            f"""
            MATCH (a)-[r]->(b)
            WHERE (a.group_id = $group_id OR b.group_id = $group_id)
              AND NOT a:{_SNAPSHOT_NODE} AND NOT b:{_SNAPSHOT_NODE}
              AND r.uuid IS NOT NULL
            CREATE (s:{_SNAPSHOT_RELATIONSHIP})
            SET s = properties(r)
            SET s._newsroom_snapshot_id = $snapshot_id,
                s._newsroom_relationship_uuid = r.uuid,
                s._newsroom_source_uuid = a.uuid,
                s._newsroom_target_uuid = b.uuid,
                s._newsroom_relationship_type = type(r)
            """,
            group_id=self._group_id,
            snapshot_id=self._snapshot_id,
        )

    async def record_pending_telemetry(
        self,
        *,
        chat_invocations: list[dict[str, object]],
        embedding_usage: dict[str, object],
    ) -> None:
        completed = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING'
            SET m.chat_invocations_json = $chat_invocations_json,
                m.embedding_usage_json = $embedding_usage_json
            """,
            episode_uuid=self._episode_uuid,
            chat_invocations_json=canonical_json_bytes(chat_invocations).decode("utf-8"),
            embedding_usage_json=canonical_json_bytes(embedding_usage).decode("utf-8"),
        )

    async def restore_preexisting(self) -> None:
        """Restore every pre-attempt node/edge property while retaining new objects."""

        await self._restore_properties()
        await self._restore_labels()
        await self.assert_preexisting_unchanged()

    async def rollback_pending(
        self,
        *,
        chat_invocations: list[dict[str, object]],
        embedding_usage: dict[str, object],
        reason: str,
    ) -> None:
        """Restore the exact pre-attempt generation and retain a recovery marker."""

        await self._query(
            f"""
            MATCH (a)-[r]->(b)
            WHERE (a.group_id = $group_id OR b.group_id = $group_id)
              AND NOT EXISTS {{
                  MATCH (s:{_SNAPSHOT_RELATIONSHIP} {{
                      _newsroom_snapshot_id: $snapshot_id,
                      _newsroom_relationship_uuid: r.uuid
                  }})
              }}
            DELETE r
            """,
            group_id=self._group_id,
            snapshot_id=self._snapshot_id,
        )
        await self._query(
            f"""
            MATCH (n)
            WHERE n.group_id = $group_id
              AND NOT n:{_SNAPSHOT_NODE}
              AND NOT n:{_SNAPSHOT_RELATIONSHIP}
              AND NOT n:{_MARKER}
              AND NOT EXISTS {{
                  MATCH (s:{_SNAPSHOT_NODE} {{
                      _newsroom_snapshot_id: $snapshot_id,
                      _newsroom_source_uuid: n.uuid
                  }})
              }}
            DETACH DELETE n
            """,
            group_id=self._group_id,
            snapshot_id=self._snapshot_id,
        )
        await self._restore_properties()
        await self._restore_labels()
        await self.assert_preexisting_unchanged()
        recovered = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING'
            SET m.state = 'RECOVERED_AMBIGUOUS',
                m.recovery_reason = $reason,
                m.chat_invocations_json = $chat_invocations_json,
                m.embedding_usage_json = $embedding_usage_json
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            reason=reason,
            chat_invocations_json=canonical_json_bytes(chat_invocations).decode("utf-8"),
            embedding_usage_json=canonical_json_bytes(embedding_usage).decode("utf-8"),
        )
        if not recovered or _record_value(recovered[0], "state") != "RECOVERED_AMBIGUOUS":
            raise GuardError("Graphiti recovery marker transition did not commit")
        await self._delete_snapshot()

    async def _restore_properties(self) -> None:
        await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_NODE} {{_newsroom_snapshot_id: $snapshot_id}})
            MATCH (n {{uuid: s._newsroom_source_uuid}})
            SET n = properties(s)
            REMOVE n._newsroom_snapshot_id,
                   n._newsroom_source_uuid,
                   n._newsroom_source_labels
            """,
            snapshot_id=self._snapshot_id,
        )
        await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_RELATIONSHIP} {{_newsroom_snapshot_id: $snapshot_id}})
            MATCH (a {{uuid: s._newsroom_source_uuid}})
                  -[r {{uuid: s._newsroom_relationship_uuid}}]->
                  (b {{uuid: s._newsroom_target_uuid}})
            WHERE type(r) = s._newsroom_relationship_type
            SET r = properties(s)
            REMOVE r._newsroom_snapshot_id,
                   r._newsroom_relationship_uuid,
                   r._newsroom_source_uuid,
                   r._newsroom_target_uuid,
                   r._newsroom_relationship_type
            """,
            snapshot_id=self._snapshot_id,
        )

    async def _restore_labels(self) -> None:
        records = await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_NODE} {{_newsroom_snapshot_id: $snapshot_id}})
            MATCH (n {{uuid: s._newsroom_source_uuid}})
            RETURN n.uuid AS uuid,
                   s._newsroom_source_labels AS expected,
                   labels(n) AS actual
            """,
            snapshot_id=self._snapshot_id,
        )
        for record in records:
            uuid = str(_record_value(record, "uuid") or "")
            expected = {str(item) for item in (_record_value(record, "expected") or [])}
            actual = {str(item) for item in (_record_value(record, "actual") or [])}
            if not uuid or any(_LABEL.fullmatch(item) is None for item in expected | actual):
                raise GuardError("Graphiti generation contains an unsafe dynamic label")
            for label in sorted(actual - expected):
                await self._query(
                    f"MATCH (n {{uuid: $uuid}}) REMOVE n:`{label}`",
                    uuid=uuid,
                )
            for label in sorted(expected - actual):
                await self._query(
                    f"MATCH (n {{uuid: $uuid}}) SET n:`{label}`",
                    uuid=uuid,
                )

    async def assert_preexisting_unchanged(self) -> None:
        nodes = await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_NODE} {{_newsroom_snapshot_id: $snapshot_id}})
            OPTIONAL MATCH (n {{uuid: s._newsroom_source_uuid}})
            RETURN properties(s) AS snapshot,
                   properties(n) AS current,
                   labels(n) AS current_labels
            """,
            snapshot_id=self._snapshot_id,
        )
        for record in nodes:
            snapshot = _record_value(record, "snapshot")
            current = _record_value(record, "current")
            if not isinstance(snapshot, dict) or not isinstance(current, dict):
                raise GuardError("a pre-existing Graphiti node is missing")
            expected = {
                str(key): value
                for key, value in snapshot.items()
                if not str(key).startswith(_RESERVED_PREFIX)
            }
            expected_labels = {
                str(item) for item in snapshot.get("_newsroom_source_labels", [])
            }
            current_labels = {
                str(item) for item in (_record_value(record, "current_labels") or [])
            }
            if _normalise(expected) != _normalise(current) or expected_labels != current_labels:
                raise GuardError("a pre-existing Graphiti node changed across the attempt")

        relationships = await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_RELATIONSHIP} {{_newsroom_snapshot_id: $snapshot_id}})
            OPTIONAL MATCH (a {{uuid: s._newsroom_source_uuid}})
                  -[r {{uuid: s._newsroom_relationship_uuid}}]->
                  (b {{uuid: s._newsroom_target_uuid}})
            WHERE type(r) = s._newsroom_relationship_type
            RETURN properties(s) AS snapshot,
                   properties(r) AS current,
                   a.uuid AS source_uuid,
                   b.uuid AS target_uuid,
                   type(r) AS relationship_type
            """,
            snapshot_id=self._snapshot_id,
        )
        for record in relationships:
            snapshot = _record_value(record, "snapshot")
            current = _record_value(record, "current")
            if not isinstance(snapshot, dict) or not isinstance(current, dict):
                raise GuardError("a pre-existing Graphiti relationship is missing")
            expected = {
                str(key): value
                for key, value in snapshot.items()
                if not str(key).startswith(_RESERVED_PREFIX)
            }
            if (
                _normalise(expected) != _normalise(current)
                or str(_record_value(record, "source_uuid"))
                != str(snapshot.get("_newsroom_source_uuid"))
                or str(_record_value(record, "target_uuid"))
                != str(snapshot.get("_newsroom_target_uuid"))
                or str(_record_value(record, "relationship_type"))
                != str(snapshot.get("_newsroom_relationship_type"))
            ):
                raise GuardError(
                    "a pre-existing Graphiti relationship changed across the attempt"
                )

    async def complete(self, raw: dict[str, object]) -> None:
        raw_bytes = canonical_json_bytes(raw)
        await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING'
            SET m.state = 'COMPLETE',
                m.validated_raw_json = $validated_raw_json,
                m.validated_raw_digest = $validated_raw_digest,
                m.provider_attempt_number = $provider_attempt_number
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            validated_raw_json=raw_bytes.decode("utf-8"),
            validated_raw_digest=digest_bytes(raw_bytes),
            provider_attempt_number=int(raw["provider_attempt_number"]),
        )
        if not completed or _record_value(completed[0], "state") != "COMPLETE":
            raise GuardError("Graphiti completion marker transition did not commit")
        await self._delete_snapshot()

    async def completed_raw(self) -> dict[str, object]:
        marker = await self._marker()
        if marker is None or str(marker.get("state")) != GuardState.COMPLETE.value:
            raise GuardError("Graphiti completion marker is absent")
        raw_json = marker.get("validated_raw_json")
        retained_digest = marker.get("validated_raw_digest")
        if not isinstance(raw_json, str) or not isinstance(retained_digest, str):
            raise GuardError("Graphiti completion marker has no validated result")
        try:
            raw = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise GuardError("Graphiti completion snapshot is malformed") from exc
        if not isinstance(raw, dict):
            raise GuardError("Graphiti completion snapshot is malformed")
        raw_bytes = canonical_json_bytes(raw)
        if raw_bytes.decode("utf-8") != raw_json or digest_bytes(raw_bytes) != retained_digest:
            raise GuardError("Graphiti completion snapshot digest differs")
        return raw

    async def _delete_snapshot(self) -> None:
        await self._query(
            f"""
            MATCH (s)
            WHERE (s:{_SNAPSHOT_NODE} OR s:{_SNAPSHOT_RELATIONSHIP})
              AND s._newsroom_snapshot_id = $snapshot_id
            DELETE s
            """,
            snapshot_id=self._snapshot_id,
        )

    async def _delete_marker(self) -> None:
        await self._query(
            f"MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}}) DELETE m",
            episode_uuid=self._episode_uuid,
        )


__all__ = [
    "GuardError",
    "GuardMarker",
    "GuardState",
    "Neo4jMutationGuard",
]
