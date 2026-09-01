"""Durable Neo4j mutation journal and exact Graphiti completion marker."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes


_RESERVED_PREFIX = "_newsroom_"
_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SNAPSHOT_NODE = "NewsroomSnapshotNode"
_SNAPSHOT_RELATIONSHIP = "NewsroomSnapshotRelationship"
_MARKER = "NewsroomIngestMarker"
_MARKER_CLAIM_LEASE = "PT15M"
_SCHEMA_QUERIES = (
    f"""
    CREATE CONSTRAINT newsroom_ingest_marker_episode IF NOT EXISTS
    FOR (m:{_MARKER}) REQUIRE m.episode_uuid IS UNIQUE
    """,
)


class GuardError(RuntimeError):
    """The proposal generation could not be proved unchanged or recoverable."""


class GuardState(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    ROLLING_BACK = "ROLLING_BACK"
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
        "_claim_token",
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
        self._claim_token: str | None = None
        self._group_id = group_id
        self._episode_uuid = episode_uuid
        self._attempt_number = attempt_number
        self._input_digest = input_digest
        self._snapshot_id = f"{episode_uuid}:{attempt_number}"

    @property
    def driver(self) -> Any:
        return self._driver

    @property
    def group_id(self) -> str:
        return self._group_id

    @property
    def episode_uuid(self) -> str:
        return self._episode_uuid

    @property
    def input_digest(self) -> str:
        return self._input_digest

    async def _query(self, query: str, **parameters: object) -> list[object]:
        records, _, _ = await self._driver.execute_query(
            query, params=parameters, routing_="w"
        )
        return list(records)

    def _require_pending_claim(self, records: list[object], *, operation: str) -> None:
        if (
            not records
            or _record_value(records[0], "claim_token") != self._claim_token
        ):
            raise GuardError(f"Graphiti {operation} lost its pending claim")

    @staticmethod
    async def bootstrap_schema(driver: Any) -> None:
        """Create journal schema once during explicit Neo4j bootstrap."""

        for query in _SCHEMA_QUERIES:
            await driver.execute_query(query, params={}, routing_="w")

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

    async def _claim_marker(
        self,
    ) -> tuple[dict[str, object], bool, bool]:
        claim_token = str(uuid4())
        records = await self._query(
            f"""
            MERGE (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            ON CREATE SET
                m.group_id = $group_id,
                m.attempt_number = $attempt_number,
                m.input_digest = $input_digest,
                m.snapshot_id = $snapshot_id,
                m.state = 'SNAPSHOTTING',
                m.chat_invocations_json = '[]',
                m.embedding_usage_json = 'null',
                m.claim_token = $claim_token,
                m.claim_expires_at = datetime() + duration($claim_lease)
            RETURN properties(m) AS marker,
                   m.claim_token = $claim_token AS claimed,
                   m.state IN [
                       'SNAPSHOTTING', 'PENDING', 'ROLLING_BACK', 'RECOVERING'
                   ]
                       AND m.claim_token <> $claim_token
                       AND m.claim_expires_at > datetime() AS active
            """,
            episode_uuid=self._episode_uuid,
            group_id=self._group_id,
            attempt_number=self._attempt_number,
            input_digest=self._input_digest,
            snapshot_id=self._snapshot_id,
            claim_token=claim_token,
            claim_lease=_MARKER_CLAIM_LEASE,
        )
        if not records:
            raise GuardError("Graphiti guard marker claim did not commit")
        marker = _record_value(records[0], "marker")
        if not isinstance(marker, dict):
            raise GuardError("Graphiti guard marker is malformed")
        claimed = _record_value(records[0], "claimed") is True
        if claimed:
            self._claim_token = claim_token
        return (
            dict(marker),
            claimed,
            _record_value(records[0], "active") is True,
        )

    async def _take_over(
        self,
        raw: dict[str, object],
        *,
        state: str,
        require_expired: bool = True,
    ) -> dict[str, object] | None:
        claim_token = str(uuid4())
        records = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = $retained_state
              AND m.snapshot_id = $snapshot_id
              AND coalesce(m.claim_token, '') = $retained_claim_token
              AND (
                  NOT $require_expired
                  OR m.claim_expires_at IS NULL
                  OR m.claim_expires_at <= datetime()
              )
            SET m.state = $state,
                m.claim_token = $claim_token,
                m.claim_expires_at = datetime() + duration($claim_lease)
            RETURN properties(m) AS marker
            """,
            episode_uuid=self._episode_uuid,
            retained_state=str(raw.get("state") or ""),
            snapshot_id=str(raw.get("snapshot_id") or ""),
            retained_claim_token=str(raw.get("claim_token") or ""),
            state=state,
            require_expired=require_expired,
            claim_token=claim_token,
            claim_lease=_MARKER_CLAIM_LEASE,
        )
        if not records:
            return None
        marker = _record_value(records[0], "marker")
        if not isinstance(marker, dict):
            raise GuardError("Graphiti guard marker is malformed")
        self._claim_token = claim_token
        return dict(marker)

    async def _discard_taken_over_marker(self) -> None:
        records = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'RECOVERING' AND m.claim_token = $claim_token
            WITH m, m.episode_uuid AS episode_uuid
            DELETE m
            RETURN episode_uuid
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
        )
        if not records:
            raise GuardError("Graphiti recovery marker deletion did not commit")
        self._claim_token = None

    def _adopt_retained_snapshot(
        self, raw: dict[str, object], *, attempt_number: int
    ) -> None:
        snapshot_id = str(raw.get("snapshot_id") or "")
        expected = f"{self._episode_uuid}:{attempt_number}"
        if snapshot_id != expected:
            raise GuardError("Graphiti guard snapshot identity is malformed")
        self._snapshot_id = snapshot_id

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
        self._adopt_retained_snapshot(raw, attempt_number=attempt_number)
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
        self._snapshot_id = f"{self._episode_uuid}:{self._attempt_number}"
        retained, claimed, active = await self._claim_marker()
        if not claimed:
            if active:
                raise GuardError("Graphiti guard marker is owned by an active attempt")
            retained_state = str(retained.get("state"))
            if retained_state in {"SNAPSHOTTING", "RECOVERING"}:
                if (
                    str(retained.get("group_id") or "") != self._group_id
                    or str(retained.get("input_digest") or "") != self._input_digest
                ):
                    raise GuardError(
                        "Graphiti guard marker identity differs from this input"
                    )
                try:
                    retained_attempt = int(retained["attempt_number"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise GuardError("Graphiti guard marker is malformed") from exc
                self._adopt_retained_snapshot(
                    retained, attempt_number=retained_attempt
                )
                taken_over = await self._take_over(retained, state="RECOVERING")
                if taken_over is None:
                    return await self.begin()
                await self._delete_snapshot()
                await self._discard_taken_over_marker()
                return await self.begin()
            if retained_state in {"PENDING", "ROLLING_BACK"}:
                self._bind_marker(retained)
                taken_over = await self._take_over(retained, state=retained_state)
                if taken_over is None:
                    return await self.begin()
                retained = taken_over
            marker = self._bind_marker(retained)
            if marker.state is GuardState.COMPLETE:
                await self._delete_snapshot()
                return marker
            if marker.state is GuardState.RECOVERED_AMBIGUOUS:
                if self._attempt_number <= marker.attempt_number:
                    await self._delete_snapshot()
                    return marker
                taken_over = await self._take_over(
                    retained,
                    state="RECOVERING",
                    require_expired=False,
                )
                if taken_over is None:
                    return await self.begin()
                await self._delete_snapshot()
                await self._discard_taken_over_marker()
                return await self.begin()
            else:
                return marker

        await self._snapshot()
        pending = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'SNAPSHOTTING' AND m.claim_token = $claim_token
            SET m.state = 'PENDING'
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
        )
        if not pending or _record_value(pending[0], "state") != "PENDING":
            raise GuardError("Graphiti guard marker lost its claim before dispatch")
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
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.claim_token = $claim_token
            SET m.claim_expires_at = datetime() + duration($claim_lease)
            WITH m
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
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
            claim_lease=_MARKER_CLAIM_LEASE,
        )
        await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.claim_token = $claim_token
            SET m.claim_expires_at = datetime() + duration($claim_lease)
            WITH m
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
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
            claim_lease=_MARKER_CLAIM_LEASE,
        )

    async def record_pending_telemetry(
        self,
        *,
        chat_invocations: list[dict[str, object]],
        embedding_usage: dict[str, object],
    ) -> None:
        recorded = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING' AND m.claim_token = $claim_token
            SET m.chat_invocations_json = $chat_invocations_json,
                m.embedding_usage_json = $embedding_usage_json
            RETURN m.claim_token AS claim_token
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
            chat_invocations_json=canonical_json_bytes(chat_invocations).decode("utf-8"),
            embedding_usage_json=canonical_json_bytes(embedding_usage).decode("utf-8"),
        )
        self._require_pending_claim(recorded, operation="telemetry")

    @asynccontextmanager
    async def fenced_graph_mutation(self) -> AsyncIterator[None]:
        """Hold the marker write lock across the external graph mutation."""

        async with self._driver.session() as session:
            transaction = await session.begin_transaction()
            try:
                result = await transaction.run(
                    f"""
                    MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
                    WHERE m.state = 'PENDING' AND m.claim_token = $claim_token
                    SET m.claim_expires_at = datetime() + duration($claim_lease)
                    RETURN m.claim_token AS claim_token
                    """,
                    episode_uuid=self._episode_uuid,
                    claim_token=self._claim_token,
                    claim_lease=_MARKER_CLAIM_LEASE,
                )
                record = await result.single()
                self._require_pending_claim(
                    [] if record is None else [record], operation="mutation"
                )
                yield
                await transaction.run(
                    f"""
                    MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
                    WHERE m.state = 'PENDING' AND m.claim_token = $claim_token
                    SET m.claim_expires_at = datetime() + duration($claim_lease)
                    """,
                    episode_uuid=self._episode_uuid,
                    claim_token=self._claim_token,
                    claim_lease=_MARKER_CLAIM_LEASE,
                )
                await transaction.commit()
            except BaseException:
                await transaction.rollback()
                raise

    async def restore_preexisting(self) -> None:
        """Restore every pre-attempt node/edge property while retaining new objects."""

        await self._restore_properties()
        await self._restore_labels()
        await self.assert_preexisting_unchanged()

    async def _undo_uncommitted_graph(self) -> None:
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

    async def discard_uncommitted_generation(self) -> None:
        """Undo new graph objects while keeping the PENDING completion claim."""

        claimed = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING' AND m.claim_token = $claim_token
            SET m.claim_expires_at = datetime() + duration($claim_lease)
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
            claim_lease=_MARKER_CLAIM_LEASE,
        )
        if not claimed or _record_value(claimed[0], "state") != "PENDING":
            raise GuardError(
                "Graphiti marker cannot discard an uncommitted generation"
            )
        await self._undo_uncommitted_graph()

    async def rollback_pending(
        self,
        *,
        chat_invocations: list[dict[str, object]],
        embedding_usage: dict[str, object],
        reason: str,
    ) -> bool:
        """Restore the exact pre-attempt generation and retain a recovery marker."""

        claimed = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING' AND m.claim_token = $claim_token
            SET m.state = 'ROLLING_BACK'
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
        )
        if not claimed:
            retained = await self._marker()
            state = None if retained is None else str(retained.get("state"))
            if state == GuardState.COMPLETE.value:
                await self._delete_snapshot()
                return False
            if state != GuardState.ROLLING_BACK.value:
                raise GuardError("Graphiti marker cannot enter rollback")
            if str(retained.get("claim_token") or "") != self._claim_token:
                raise GuardError("Graphiti rollback is owned by another claim")

        await self._undo_uncommitted_graph()
        recovered = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'ROLLING_BACK' AND m.claim_token = $claim_token
            SET m.state = 'RECOVERED_AMBIGUOUS',
                m.recovery_reason = $reason,
                m.chat_invocations_json = $chat_invocations_json,
                m.embedding_usage_json = $embedding_usage_json
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
            reason=reason,
            chat_invocations_json=canonical_json_bytes(chat_invocations).decode("utf-8"),
            embedding_usage_json=canonical_json_bytes(embedding_usage).decode("utf-8"),
        )
        if not recovered or _record_value(recovered[0], "state") != "RECOVERED_AMBIGUOUS":
            raise GuardError("Graphiti recovery marker transition did not commit")
        await self._delete_snapshot()
        return True

    async def _restore_properties(self) -> None:
        await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_NODE} {{_newsroom_snapshot_id: $snapshot_id}})
            MATCH (n {{uuid: s._newsroom_source_uuid}})
            WHERE NOT n:{_SNAPSHOT_NODE}
              AND NOT n:{_SNAPSHOT_RELATIONSHIP}
              AND NOT n:{_MARKER}
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
              AND NOT a:{_SNAPSHOT_NODE} AND NOT b:{_SNAPSHOT_NODE}
              AND NOT a:{_SNAPSHOT_RELATIONSHIP}
              AND NOT b:{_SNAPSHOT_RELATIONSHIP}
              AND NOT a:{_MARKER} AND NOT b:{_MARKER}
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
            WHERE NOT n:{_SNAPSHOT_NODE}
              AND NOT n:{_SNAPSHOT_RELATIONSHIP}
              AND NOT n:{_MARKER}
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
                    f"""
                    MATCH (n {{uuid: $uuid}})
                    WHERE NOT n:{_SNAPSHOT_NODE}
                      AND NOT n:{_SNAPSHOT_RELATIONSHIP}
                      AND NOT n:{_MARKER}
                    REMOVE n:`{label}`
                    """,
                    uuid=uuid,
                )
            for label in sorted(expected - actual):
                await self._query(
                    f"""
                    MATCH (n {{uuid: $uuid}})
                    WHERE NOT n:{_SNAPSHOT_NODE}
                      AND NOT n:{_SNAPSHOT_RELATIONSHIP}
                      AND NOT n:{_MARKER}
                    SET n:`{label}`
                    """,
                    uuid=uuid,
                )

    async def assert_preexisting_unchanged(self) -> None:
        nodes = await self._query(
            f"""
            MATCH (s:{_SNAPSHOT_NODE} {{_newsroom_snapshot_id: $snapshot_id}})
            OPTIONAL MATCH (n {{uuid: s._newsroom_source_uuid}})
            WHERE NOT n:{_SNAPSHOT_NODE}
              AND NOT n:{_SNAPSHOT_RELATIONSHIP}
              AND NOT n:{_MARKER}
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
              AND NOT a:{_SNAPSHOT_NODE} AND NOT b:{_SNAPSHOT_NODE}
              AND NOT a:{_SNAPSHOT_RELATIONSHIP}
              AND NOT b:{_SNAPSHOT_RELATIONSHIP}
              AND NOT a:{_MARKER} AND NOT b:{_MARKER}
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
        completed = await self._query(
            f"""
            MATCH (m:{_MARKER} {{episode_uuid: $episode_uuid}})
            WHERE m.state = 'PENDING' AND m.claim_token = $claim_token
            SET m.state = 'COMPLETE',
                m.validated_raw_json = $validated_raw_json,
                m.validated_raw_digest = $validated_raw_digest,
                m.provider_attempt_number = $provider_attempt_number
            RETURN m.state AS state
            """,
            episode_uuid=self._episode_uuid,
            claim_token=self._claim_token,
            validated_raw_json=raw_bytes.decode("utf-8"),
            validated_raw_digest=digest_bytes(raw_bytes),
            provider_attempt_number=int(raw["provider_attempt_number"]),
        )
        if not completed or _record_value(completed[0], "state") != "COMPLETE":
            raise GuardError("Graphiti completion marker transition did not commit")
        await self._delete_snapshot()

    async def completed_raw(self) -> dict[str, object]:
        raw = await self.completed_raw_or_none()
        if raw is None:
            raise GuardError("Graphiti completion marker is absent")
        return raw

    async def completed_raw_or_none(self) -> dict[str, object] | None:
        """Read a matching completed result without creating a mutation marker."""

        marker = await self._marker()
        if marker is None or str(marker.get("state")) != GuardState.COMPLETE.value:
            return None
        self._bind_marker(marker)
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
