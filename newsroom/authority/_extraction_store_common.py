from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import PayloadMode, TrustScope, UtcTimestamp
from newsroom.extraction.models import (
    ExtractionInputBinding,
    ExtractionPassageInput,
    ExtractionRunRequest,
    ExtractorContract,
    ExtractorContractRequest,
)
from newsroom.extraction.policy import (
    EXTRACTION_RUN_EXECUTE_COMMAND,
    EXTRACTOR_CONTRACT_REGISTER_COMMAND,
)
from newsroom.extraction.types import (
    ExtractionIdentifierReuse,
    ExtractionRightsDenied,
    ExtractionSemanticCollision,
    ExtractionStateError,
    ExtractionVersionConflict,
)

_RECORD_SPECS: dict[str, tuple[str, str, TrustScope]] = {
    EXTRACTOR_CONTRACT_REGISTER_COMMAND: (
        "extractor_contract",
        "extraction.contract.registered",
        TrustScope.ADMITTED,
    ),
    EXTRACTION_RUN_EXECUTE_COMMAND: (
        "extraction_run_version",
        "extraction.run.executed",
        TrustScope.PROPOSED,
    ),
}


class _ExtractionStoreSupport:
    def _require_extraction_grant(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        command_type: str,
        aggregate_id: str,
        canonical_bytes: bytes,
    ) -> None:
        self._issuer.verify(grant)
        spec = _RECORD_SPECS.get(command_type)
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
                "extraction grant differs from the typed record"
            )

    @staticmethod
    def _ensure_identifier_absent(
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
    def _ensure_semantic_absent(
        conn: sqlite3.Connection,
        *,
        table: str,
        column: str,
        digest: str,
        identity: str,
    ) -> None:
        if conn.execute(
            f"SELECT 1 FROM {table} WHERE {column}=?", (digest,)
        ).fetchone() is not None:
            raise ExtractionSemanticCollision(
                f"{identity} already exists under another stable identity"
            )

    @staticmethod
    def _json_blob(value: object) -> bytes:
        return canonical_json_bytes(value)

    @staticmethod
    def _decode_json_blob(value: bytes | memoryview, *, identity: str) -> Any:
        data = bytes(value)
        try:
            decoded = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(
                f"{identity} retained JSON is invalid"
            ) from exc
        if canonical_json_bytes(decoded) != data:
            raise AuthorityPersistenceError(
                f"{identity} retained JSON is not canonical"
            )
        return decoded

    @classmethod
    def _canonical_row_value(
        cls, row: Mapping[str, Any], *, identity: str
    ) -> dict[str, Any]:
        data = bytes(row["canonical_bytes"])
        if digest_bytes(data) != str(row["canonical_digest"]):
            raise AuthorityPersistenceError(f"{identity} canonical digest mismatch")
        value = cls._decode_json_blob(data, identity=identity)
        if not isinstance(value, dict):
            raise AuthorityPersistenceError(f"{identity} must be a canonical object")
        return value

    @staticmethod
    def _record_context(
        conn: sqlite3.Connection, *, event_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT e.*,c.idempotency_key,p.payload_bytes "
            "FROM ledger_events e "
            "JOIN authority_commands c ON c.command_id=e.command_id "
            "JOIN authority_payloads p ON p.payload_id=e.payload_id "
            "WHERE e.event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "extraction record has no exact authority event"
            )
        return row

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
        event = cls._record_context(
            conn, event_id=str(row["authority_event_id"])
        )
        aggregate_type, event_type, trust_scope = _RECORD_SPECS[command_type]
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
    def _contract_row(
        conn: sqlite3.Connection, contract_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM extractor_contracts WHERE contract_id=?",
            (contract_id,),
        ).fetchone()
        if row is None:
            raise ExtractionStateError("extractor contract is not retained")
        return row

    @staticmethod
    def _run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM extraction_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ExtractionStateError("extraction run is not retained")
        return row

    @staticmethod
    def _run_head_row(
        conn: sqlite3.Connection, run_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM extraction_run_heads WHERE run_id=?", (run_id,)
        ).fetchone()

    @staticmethod
    def _require_source_binding_current(
        conn: sqlite3.Connection, binding: ExtractionInputBinding
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT p.*,r.item_id,r.definition_id,r.definition_version_id "
            "AS revision_definition_version_id,i.definition_version_id "
            "AS item_definition_version_id,v.lifecycle_stage,"
            "v.execution_authority,h.current_version_id "
            "FROM discovery_representations p "
            "JOIN source_revisions r ON r.revision_id=p.revision_id "
            "JOIN source_items i ON i.item_id=r.item_id "
            "JOIN source_definition_versions v "
            "ON v.version_id=p.definition_version_id "
            "JOIN source_definition_version_heads h "
            "ON h.definition_id=r.definition_id "
            "WHERE p.representation_id=? AND p.revision_id=? "
            "AND r.item_id=? AND r.definition_id=? "
            "AND p.definition_version_id=?",
            (
                str(binding.representation_id),
                str(binding.revision_id),
                str(binding.item_id),
                str(binding.definition_id),
                str(binding.definition_version_id),
            ),
        ).fetchone()
        if row is None:
            raise ExtractionStateError(
                "extraction input does not match retained source lineage"
            )
        if str(row["current_version_id"]) != str(binding.definition_version_id):
            raise ExtractionRightsDenied(
                "source definition version is no longer current for extraction"
            )
        if str(row["lifecycle_stage"]) in {"RETIRED", "REJECTED"}:
            raise ExtractionRightsDenied(
                "source lifecycle no longer permits extraction use"
            )
        if str(row["execution_authority"]) != "FIXTURE_REPLAY_ONLY_DISABLED":
            raise ExtractionStateError("source execution boundary is incompatible")
        return row

    @staticmethod
    def _current_passage_authority_row(
        conn: sqlite3.Connection,
        passage: ExtractionPassageInput,
        *,
        now: UtcTimestamp,
        principal_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT d.*,a.blob_digest,a.valid_from,a.valid_until,"
            "av.state AS admission_state,rd.allowed AS rights_allowed,"
            "rd.reason_code AS rights_reason_code,rd.decided_at AS rights_decided_at,"
            "rd.valid_from AS rights_valid_from,rd.valid_until AS rights_valid_until,"
            "bv.state AS blob_state,bv.integrity_state AS blob_integrity_state "
            "FROM object_access_decisions d "
            "JOIN object_admissions a ON a.admission_id=d.admission_id "
            "JOIN object_admission_heads ah ON ah.admission_id=a.admission_id "
            "JOIN object_admission_versions av "
            "ON av.admission_id=ah.admission_id "
            "AND av.lifecycle_version=ah.current_version "
            "JOIN object_rights_decisions rd "
            "ON rd.rights_decision_id=a.rights_decision_id "
            "JOIN blob_lifecycle_heads bh ON bh.blob_digest=a.blob_digest "
            "JOIN blob_lifecycle_versions bv "
            "ON bv.blob_digest=bh.blob_digest "
            "AND bv.lifecycle_version=bh.current_version "
            "WHERE d.access_decision_id=? AND d.admission_id=?",
            (str(passage.access_decision_id), str(passage.admission_id)),
        ).fetchone()
        if row is None:
            raise ExtractionRightsDenied(
                "governed passage access decision is not retained"
            )
        expected = {
            "hydration_policy_contract_digest": (
                passage.hydration_policy_contract_digest
            ),
            "principal_id": passage.principal_id,
            "authority_domain": passage.authority_domain,
            "purpose": passage.purpose,
            "object_class": passage.object_class,
            "allowed_use": passage.allowed_use,
            "security_scope": passage.security_scope,
            "retention_scope": passage.retention_scope,
            "byte_offset": passage.byte_offset,
            "allowed_bytes": passage.byte_length,
            "blob_digest": passage.blob_digest,
        }
        for column, value in expected.items():
            if row[column] != value:
                raise ExtractionRightsDenied(
                    f"governed passage {column} differs from access authority"
                )
        if passage.principal_id != principal_id:
            raise ExtractionRightsDenied(
                "extraction executor differs from governed hydration principal"
            )
        if passage.text_digest != passage.blob_digest:
            raise ExtractionRightsDenied(
                "passage text digest differs from admitted blob identity"
            )
        if passage.text is not None:
            data = passage.text.encode("utf-8")
            if (
                len(data) != passage.byte_length
                or digest_bytes(data) != passage.blob_digest
            ):
                raise ExtractionRightsDenied(
                    "ephemeral passage bytes differ from governed authority"
                )
        if str(row["admission_state"]) != "ACTIVE":
            raise ExtractionRightsDenied("object admission is not active")
        if (
            str(row["blob_state"]) != "ACTIVE"
            or str(row["blob_integrity_state"]) != "VERIFIED"
        ):
            raise ExtractionRightsDenied(
                "governed passage bytes are not active and verified"
            )
        if not bool(row["rights_allowed"]):
            raise ExtractionRightsDenied(str(row["rights_reason_code"]))
        admission_from = UtcTimestamp.parse(str(row["valid_from"]))
        admission_until = (
            None
            if row["valid_until"] is None
            else UtcTimestamp.parse(str(row["valid_until"]))
        )
        rights_decided = UtcTimestamp.parse(str(row["rights_decided_at"]))
        rights_from = UtcTimestamp.parse(str(row["rights_valid_from"]))
        rights_until = (
            None
            if row["rights_valid_until"] is None
            else UtcTimestamp.parse(str(row["rights_valid_until"]))
        )
        if (
            now.value < admission_from.value
            or now.value < rights_decided.value
            or now.value < rights_from.value
        ):
            raise ExtractionRightsDenied("governed passage rights are not yet valid")
        if (
            (admission_until is not None and now.value >= admission_until.value)
            or (rights_until is not None and now.value >= rights_until.value)
        ):
            raise ExtractionRightsDenied("governed passage rights have expired")
        deletion = conn.execute(
            "SELECT dv.state FROM object_deletions d "
            "JOIN object_deletion_heads dh ON dh.deletion_id=d.deletion_id "
            "JOIN object_deletion_versions dv "
            "ON dv.deletion_id=dh.deletion_id "
            "AND dv.lifecycle_version=dh.current_version "
            "WHERE d.blob_digest=? AND dv.state IN("
            "'TOMBSTONED','PHYSICALLY_REMOVED') LIMIT 1",
            (passage.blob_digest,),
        ).fetchone()
        if deletion is not None:
            raise ExtractionRightsDenied(
                "governed tombstone blocks extraction passage use"
            )
        return row

    @classmethod
    def _require_current_input(
        cls,
        conn: sqlite3.Connection,
        *,
        request: ExtractionRunRequest,
        now: UtcTimestamp,
        principal_id: str,
        require_text: bool,
    ) -> None:
        cls._require_source_binding_current(conn, request.input_binding)
        for passage in request.input_binding.passages:
            if require_text:
                passage.require_text()
            cls._current_passage_authority_row(
                conn,
                passage,
                now=now,
                principal_id=principal_id,
            )


    def preflight_extraction(
        self,
        request: ExtractionRunRequest,
        *,
        principal_id: str,
    ) -> ExtractorContract:
        """Revalidate exact source/object authority before producer execution."""

        if not isinstance(request, ExtractionRunRequest):
            raise TypeError("extraction preflight requires a typed request")
        with self._lock:
            now = self._clock()
            self._require_current_input(
                self._connection,
                request=request,
                now=now,
                principal_id=principal_id,
                require_text=True,
            )
            row = self._contract_row(
                self._connection, str(request.contract_id)
            )
            contract = self._contract_from_row(
                self._connection, row, replayed=False
            )
            if (
                contract.request.execution_profile.value
                != "FIXTURE_REPLAY_ONLY"
                or contract.request.producer_kind
                != "DETERMINISTIC_FIXTURE"
            ):
                raise ExtractionStateError(
                    "unapproved extractor contract entered fixture preflight"
                )
            return contract

    @staticmethod
    def _validate_run_chain(
        conn: sqlite3.Connection, request: ExtractionRunRequest
    ) -> None:
        head = _ExtractionStoreSupport._run_head_row(conn, str(request.run_id))
        if request.version_number == 1:
            if head is not None:
                raise ExtractionVersionConflict(
                    "initial extraction run version already has a retained head"
                )
            return
        if head is None:
            raise ExtractionVersionConflict("later extraction version has no head")
        if bool(head["terminal"]):
            raise ExtractionVersionConflict(
                "terminal extraction run cannot be retried under the same identity"
            )
        if (
            int(head["current_version_number"]) + 1 != request.version_number
            or request.expected_previous_version_id is None
            or str(head["current_run_version_id"])
            != str(request.expected_previous_version_id)
        ):
            raise ExtractionVersionConflict(
                "extraction version does not extend the exact retained head"
            )

    @staticmethod
    def _stable_run_value(
        request: ExtractionRunRequest,
    ) -> dict[str, object]:
        return {
            "run_id": str(request.run_id),
            "contract_id": str(request.contract_id),
            "input_binding": request.input_binding.canonical_value(),
            "budget": request.budget.canonical_value(),
            "fixture_case": request.fixture_case.value,
            "stable_semantic_digest": request.stable_run_semantic_digest,
        }

    @staticmethod
    def _run_version_value(
        *,
        request: ExtractionRunRequest,
        contract_digest: str,
        outcome: str,
        failure_code: str,
        started_at: str,
        ended_at: str,
        usage_value: dict[str, int],
    ) -> dict[str, object]:
        return {
            "request": request.canonical_value(),
            "contract_canonical_digest": contract_digest,
            "outcome": outcome,
            "failure_code": failure_code,
            "started_at": started_at,
            "ended_at": ended_at,
            "usage": usage_value,
        }

    @staticmethod
    def _contract_components_match(
        row: Mapping[str, Any], request: ExtractorContractRequest
    ) -> bool:
        pairs = {
            "framework": request.framework,
            "model": request.model,
            "prompt": request.prompt,
            "output_schema": request.output_schema,
            "code": request.code,
            "normalisation": request.normalisation,
            "policy": request.policy,
        }
        return all(
            str(row[f"{prefix}_id"]) == component.component_id
            and str(row[f"{prefix}_version"]) == component.component_version
            and str(row[f"{prefix}_digest"]) == component.contract_digest
            for prefix, component in pairs.items()
        )


__all__ = ["_ExtractionStoreSupport"]
