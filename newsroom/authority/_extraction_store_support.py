from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import PayloadMode, TrustScope
from newsroom.extraction.policy import (
    EXTRACTION_ATTEMPT_RECORD_COMMAND,
    EXTRACTION_OUTPUT_RETAIN_COMMAND,
    EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND,
    EXTRACTION_RUN_REGISTER_COMMAND,
    EXTRACTOR_CONTRACT_REGISTER_COMMAND,
)
from newsroom.extraction.types import (
    ExtractionIdentifierReuse,
    ExtractionRightsBlocked,
    ExtractionSemanticCollision,
    ExtractionStateError,
)

_EXTRACTION_RECORD_SPECS: dict[str, tuple[str, str, TrustScope]] = {
    EXTRACTOR_CONTRACT_REGISTER_COMMAND: (
        "extractor_contract",
        "extraction.contract.registered",
        TrustScope.ADMITTED,
    ),
    EXTRACTION_RUN_REGISTER_COMMAND: (
        "extraction_run",
        "extraction.run.registered",
        TrustScope.OBSERVED,
    ),
    EXTRACTION_ATTEMPT_RECORD_COMMAND: (
        "extraction_attempt",
        "extraction.attempt.recorded",
        TrustScope.OBSERVED,
    ),
    EXTRACTION_OUTPUT_RETAIN_COMMAND: (
        "extraction_output",
        "extraction.output.retained",
        TrustScope.OBSERVED,
    ),
    EXTRACTION_PROPOSAL_SET_RETAIN_COMMAND: (
        "extraction_proposal_set",
        "extraction.proposal_set.retained",
        TrustScope.PROPOSED,
    ),
}


class _ExtractionStoreSupport:
    """Shared exact-lineage and authority-envelope checks for Increment 4A."""

    def _require_extraction_grant(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        command_type: str,
        aggregate_id: str,
        canonical_bytes: bytes,
    ) -> None:
        self._issuer.verify(grant)
        spec = _EXTRACTION_RECORD_SPECS.get(command_type)
        if spec is None:
            raise AuthorityPersistenceError("unknown extraction authority command")
        aggregate_type, event_type, trust_scope = spec
        definition = grant.definition
        if (
            grant.command_type != command_type
            or grant.aggregate_id != aggregate_id
            or grant.expected_aggregate_version != 0
            or definition.command_type != command_type
            or definition.aggregate_type != aggregate_type
            or definition.event_type != event_type
            or definition.trust_scope is not trust_scope
            or definition.security_scope != "authority.extraction"
            or definition.retention_scope != "authority.audit"
            or definition.payload_mode is not PayloadMode.INLINE
            or grant.payload.kind != PayloadMode.INLINE.value
            or grant.payload.inline_bytes != canonical_bytes
            or grant.payload.digest != digest_bytes(canonical_bytes)
        ):
            raise AuthorityPersistenceError(
                "extraction command grant differs from the typed record"
            )

    @staticmethod
    def _extraction_identifier_absent(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        identifier: str,
        identity: str,
    ) -> None:
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?", (identifier,)
        ).fetchone() is not None:
            raise ExtractionIdentifierReuse(
                f"{identity} is already retained under different command identity"
            )

    @staticmethod
    def _extraction_semantic_absent(
        conn: sqlite3.Connection,
        *,
        table: str,
        predicate: str,
        parameters: tuple[object, ...],
        identity: str,
    ) -> None:
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {predicate}", parameters
        ).fetchone() is not None:
            raise ExtractionSemanticCollision(
                f"{identity} already exists under another stable identity"
            )

    @classmethod
    def _validate_record_envelope(
        cls,
        conn: sqlite3.Connection,
        row: Mapping[str, Any],
        *,
        command_type: str,
        aggregate_id: str,
        canonical_bytes: bytes,
        canonical_digest: str,
    ) -> sqlite3.Row:
        spec = _EXTRACTION_RECORD_SPECS.get(command_type)
        if spec is None:
            return super()._validate_record_envelope(  # type: ignore[misc]
                conn,
                row,
                command_type=command_type,
                aggregate_id=aggregate_id,
                canonical_bytes=canonical_bytes,
                canonical_digest=canonical_digest,
            )
        event = cls._record_context(conn, event_id=str(row["authority_event_id"]))
        aggregate_type, event_type, trust_scope = spec
        if (
            str(event["event_type"]) != event_type
            or int(event["event_schema_version"]) != 1
            or str(event["aggregate_type"]) != aggregate_type
            or str(event["aggregate_id"]) != aggregate_id
            or int(event["aggregate_version"])
            != int(row["authority_aggregate_version"])
            or int(row["authority_aggregate_version"]) != 1
            or str(event["recorded_at"]) != str(row["recorded_at"])
            or str(event["security_scope"]) != "authority.extraction"
            or str(event["retention_scope"]) != "authority.audit"
            or str(event["trust_scope"]) != trust_scope.value
            or str(event["payload_mode"]) != PayloadMode.INLINE.value
            or str(event["payload_digest"]) != canonical_digest
            or event["payload_bytes"] is None
            or bytes(event["payload_bytes"]) != canonical_bytes
            or digest_bytes(canonical_bytes) != canonical_digest
        ):
            raise AuthorityPersistenceError(
                "extraction record authority envelope is inconsistent"
            )
        return event

    @staticmethod
    def _decode_json(blob: bytes | bytearray | memoryview, *, identity: str) -> Any:
        try:
            value = json.loads(bytes(blob).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(
                f"{identity} canonical bytes are invalid"
            ) from exc
        if canonical_json_bytes(value) != bytes(blob):
            raise AuthorityPersistenceError(
                f"{identity} bytes are not canonical JSON"
            )
        return value

    @staticmethod
    def _required_row(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        identifier: str,
        identity: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            f"SELECT * FROM {table} WHERE {column}=?", (identifier,)
        ).fetchone()
        if row is None:
            raise ExtractionStateError(f"{identity} is not retained")
        return row

    @staticmethod
    def _contract_row(conn: sqlite3.Connection, contract_id: str) -> sqlite3.Row:
        return _ExtractionStoreSupport._required_row(
            conn,
            table="extractor_contracts",
            column="contract_id",
            identifier=contract_id,
            identity="extractor contract",
        )

    @staticmethod
    def _run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        return _ExtractionStoreSupport._required_row(
            conn,
            table="extraction_runs",
            column="run_id",
            identifier=run_id,
            identity="extraction run",
        )

    @staticmethod
    def _attempt_row(conn: sqlite3.Connection, attempt_id: str) -> sqlite3.Row:
        return _ExtractionStoreSupport._required_row(
            conn,
            table="extraction_attempts",
            column="attempt_id",
            identifier=attempt_id,
            identity="extraction attempt",
        )

    @staticmethod
    def _output_row(conn: sqlite3.Connection, output_id: str) -> sqlite3.Row:
        return _ExtractionStoreSupport._required_row(
            conn,
            table="extraction_outputs",
            column="output_id",
            identifier=output_id,
            identity="extraction output",
        )

    @staticmethod
    def _proposal_set_row(
        conn: sqlite3.Connection, proposal_set_id: str
    ) -> sqlite3.Row:
        return _ExtractionStoreSupport._required_row(
            conn,
            table="extraction_proposal_sets",
            column="proposal_set_id",
            identifier=proposal_set_id,
            identity="extraction proposal set",
        )

    @staticmethod
    def _require_current_contract(
        conn: sqlite3.Connection, *, contract_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT c.* FROM extractor_contracts c "
            "JOIN extractor_contract_heads h "
            "ON h.contract_family=c.contract_family "
            "AND h.current_contract_id=c.contract_id "
            "WHERE c.contract_id=?",
            (contract_id,),
        ).fetchone()
        if row is None:
            raise ExtractionStateError(
                "extraction run is not pinned to the current extractor contract"
            )
        return row

    @staticmethod
    def _require_current_run_rights(
        conn: sqlite3.Connection, *, run_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT r.*,v.lifecycle_stage AS current_lifecycle_stage "
            "FROM extraction_runs r "
            "JOIN source_definition_version_heads h "
            "ON h.definition_id=r.definition_id "
            "AND h.current_version_id=r.definition_version_id "
            "JOIN source_definition_versions v "
            "ON v.version_id=h.current_version_id "
            "WHERE r.run_id=? "
            "AND v.rights_decision_id=r.rights_decision_id "
            "AND v.rights_policy_version=r.rights_policy_version "
            "AND v.allowed_use=r.allowed_use "
            "AND v.source_retention_scope=r.source_retention_scope "
            "AND v.lifecycle_stage NOT IN('RETIRED','REJECTED')",
            (run_id,),
        ).fetchone()
        if row is None:
            raise ExtractionRightsBlocked(
                "current source version or rights no longer permit extraction use"
            )
        return row

    @staticmethod
    def _require_active_object_admission(
        conn: sqlite3.Connection, admission_id: str | None
    ) -> None:
        if admission_id is None:
            return
        row = conn.execute(
            "SELECT v.state FROM object_admission_heads h "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "WHERE h.admission_id=?",
            (admission_id,),
        ).fetchone()
        if row is None or str(row["state"]) != "ACTIVE":
            raise ExtractionRightsBlocked(
                "governed object admission is not currently ACTIVE"
            )


__all__ = ["_ExtractionStoreSupport", "_EXTRACTION_RECORD_SPECS"]
