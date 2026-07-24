from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
import sqlite3
from types import MappingProxyType
from typing import Any

from ._capability import _AuthorizedCommandGrant
from ._event_store import _EventAuthorityStore
from .canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .persistence import AuthorityPersistenceError, LedgerEventRecord
from .types import (
    EventId,
    ObjectAdmissionId,
    PayloadMode,
    TrustScope,
    UtcTimestamp,
)

from newsroom.projection.mapping import (
    StructuralEventMapping,
    StructuralMappingContract,
)
from newsroom.projection.models import (
    DeliveryRecordView,
    ProjectionCheckpointView,
    ProjectionContractError,
    ProjectionDeadLetterId,
    ProjectionDeadLetterView,
    ProjectionDeliveryAttemptId,
    ProjectionDeliveryOutcome,
    ProjectionFamilyDefinition,
    ProjectionFamilyKind,
    ProjectionFamilyView,
    ProjectionGapId,
    ProjectionGapState,
    ProjectionGapView,
    ProjectionGenerationId,
    ProjectionGenerationPromotionView,
    ProjectionGenerationState,
    ProjectionGenerationValidationView,
    ProjectionGenerationView,
    ProjectionStateError,
    ProjectionStatusMetadata,
)
from newsroom.projection.policy import ProjectionContractRegistry


@dataclass(frozen=True, slots=True)
class _ProjectionDeliverySource:
    generation: ProjectionGenerationView
    family: ProjectionFamilyDefinition
    mapping_contract: StructuralMappingContract
    mapping: StructuralEventMapping | None
    event: LedgerEventRecord
    source_event_digest: str
    payload: Mapping[str, object]
    payload_is_mapping: bool
    tombstoned_object_admission_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ProjectionRebuildReceipt:
    generation: ProjectionGenerationView
    through_ledger_seq: int
    authority_event_id: EventId
    replayed: bool
    recorded_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class _ProjectionRebuildDeliveryState:
    outcome: ProjectionDeliveryOutcome
    finalized: bool
    attempt_count: int
    source_event_id: EventId
    source_event_digest: str


@dataclass(frozen=True, slots=True)
class _ProjectionGenerationMetadata:
    generation: ProjectionGenerationView
    family: ProjectionFamilyDefinition
    contiguous_ledger_seq: int
    open_gap_count: int
    dead_letter_count: int
    serving_time: UtcTimestamp



_SUCCESS_OUTCOMES = {
    ProjectionDeliveryOutcome.APPLIED,
    ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
}
_TERMINAL_GENERATION_STATES = {
    ProjectionGenerationState.RETIRED,
    ProjectionGenerationState.FAILED,
}
_ALLOWED_TRANSITIONS = {
    ProjectionGenerationState.BUILDING: {
        ProjectionGenerationState.VALIDATING,
        ProjectionGenerationState.FAILED,
    },
    ProjectionGenerationState.VALIDATING: {
        ProjectionGenerationState.ACTIVE,
        ProjectionGenerationState.FAILED,
    },
    ProjectionGenerationState.ACTIVE: {
        ProjectionGenerationState.RETIRED,
        ProjectionGenerationState.FAILED,
    },
    ProjectionGenerationState.RETIRED: set(),
    ProjectionGenerationState.FAILED: set(),
}


class _ProjectionAuthorityStore(_EventAuthorityStore):
    """Private SQLite projection authority layered on the A1/A2a ledger."""

    def __init__(self, *args: Any, contracts: ProjectionContractRegistry, **kwargs: Any) -> None:
        self._projection_contracts = contracts
        super().__init__(*args, **kwargs)

    @staticmethod
    def _validate_object_admission_payload_record(
        conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        """Validate an immutable A2b reference without reactivating current rights."""

        if row["payload_bytes"] is not None:
            raise AuthorityPersistenceError(
                "object admission payload cannot embed bytes"
            )
        if row["object_admission_id"] is None:
            raise AuthorityPersistenceError(
                "object admission payload lacks admission identity"
            )
        admission_id = ObjectAdmissionId.parse(
            str(row["object_admission_id"])
        )
        validate_sha256_digest(
            str(row["payload_digest"]), field="object_payload_digest"
        )
        admission = conn.execute(
            "SELECT a.blob_digest,v.state,v.event_id "
            "FROM object_admissions a "
            "JOIN object_admission_versions v "
            "ON v.admission_id=a.admission_id "
            "AND v.lifecycle_version=1 "
            "WHERE a.admission_id=?",
            (str(admission_id),),
        ).fetchone()
        if admission is None or str(admission["state"]) != "ACTIVE":
            raise AuthorityPersistenceError(
                "object admission payload lacks immutable activation authority"
            )
        if admission["event_id"] is None:
            raise AuthorityPersistenceError(
                "object admission activation lacks authority event identity"
            )
        if str(admission["blob_digest"]) != str(row["payload_digest"]):
            raise AuthorityPersistenceError(
                "object payload digest differs from admitted blob"
            )
        contract = conn.execute(
            "SELECT schema_version,payload_mode,contract_version,"
            "canonicalizer_implementation_version "
            "FROM payload_schema_contracts WHERE contract_digest=?",
            (str(row["schema_contract_digest"]),),
        ).fetchone()
        if contract is None:
            raise AuthorityPersistenceError(
                "object payload schema contract is missing"
            )
        if (
            str(contract["schema_version"]) != str(row["schema_version"])
            or str(contract["payload_mode"])
            != PayloadMode.OBJECT_ADMISSION.value
            or str(contract["contract_version"])
            != str(row["schema_contract_version"])
            or str(contract["canonicalizer_implementation_version"])
            != str(row["canonicalizer_implementation_version"])
        ):
            raise AuthorityPersistenceError(
                "object payload does not match its immutable schema contract"
            )

    def _migrate_or_validate(self) -> None:
        super()._migrate_or_validate()
        with self._transaction() as conn:
            self._persist_projection_contracts(conn)
        self._validate_projection_integrity()

    def _persist_projection_contracts(self, conn: sqlite3.Connection) -> None:
        recorded_at = self._clock().to_text()
        for ontology in self._projection_contracts.ontologies.contracts():
            canonical = canonical_json_bytes(ontology.canonical_value())
            if digest_bytes(canonical) != ontology.contract_digest:
                raise AuthorityPersistenceError("projection ontology digest mismatch")
            conn.execute(
                "INSERT OR IGNORE INTO projection_ontology_contracts("
                "contract_digest,ontology_id,ontology_version,implementation_version,"
                "canonical_bytes,registered_at) VALUES(?,?,?,?,?,?)",
                (
                    ontology.contract_digest,
                    ontology.ontology_id,
                    ontology.ontology_version,
                    ontology.implementation_version,
                    canonical,
                    recorded_at,
                ),
            )
            self._require_exact_bytes(
                conn,
                "projection_ontology_contracts",
                "contract_digest",
                ontology.contract_digest,
                canonical,
            )
        for mapping in self._projection_contracts.mappings.contracts():
            canonical = canonical_json_bytes(mapping.canonical_value())
            if digest_bytes(canonical) != mapping.contract_digest:
                raise AuthorityPersistenceError("projection mapping digest mismatch")
            conn.execute(
                "INSERT OR IGNORE INTO projection_mapping_contracts("
                "contract_digest,mapping_id,mapping_version,implementation_version,"
                "ontology_contract_digest,canonical_bytes,registered_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    mapping.contract_digest,
                    mapping.mapping_id,
                    mapping.mapping_version,
                    mapping.implementation_version,
                    mapping.ontology_contract_digest,
                    canonical,
                    recorded_at,
                ),
            )
            self._require_exact_bytes(
                conn,
                "projection_mapping_contracts",
                "contract_digest",
                mapping.contract_digest,
                canonical,
            )
        for definition in self._projection_contracts.families.definitions():
            canonical = canonical_json_bytes(definition.canonical_value())
            if digest_bytes(canonical) != definition.digest:
                raise AuthorityPersistenceError("projection family digest mismatch")
            conn.execute(
                "INSERT OR IGNORE INTO projection_family_definitions("
                "definition_digest,family_id,definition_version,authority_aggregate_id,"
                "family_kind,projector_version,ontology_contract_digest,"
                "mapping_contract_digest,canonical_bytes,registered_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    definition.digest,
                    definition.family_id,
                    definition.definition_version,
                    str(definition.authority_aggregate_id),
                    definition.family_kind.value,
                    definition.projector_version,
                    definition.ontology_contract_digest,
                    definition.mapping_contract_digest,
                    canonical,
                    recorded_at,
                ),
            )
            self._require_exact_bytes(
                conn,
                "projection_family_definitions",
                "definition_digest",
                definition.digest,
                canonical,
            )
        for contract in self._projection_contracts.graphiti_contracts():
            canonical = canonical_json_bytes(contract.canonical_value())
            if digest_bytes(canonical) != contract.contract_digest:
                raise AuthorityPersistenceError("Graphiti workspace digest mismatch")
            conn.execute(
                "INSERT OR IGNORE INTO projection_graphiti_workspace_contracts("
                "contract_digest,workspace_id,contract_version,endpoint_reference,"
                "secret_reference,mode,canonical_bytes,registered_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    contract.contract_digest,
                    contract.workspace_id,
                    contract.contract_version,
                    contract.endpoint_reference,
                    contract.secret_reference,
                    contract.mode.value,
                    canonical,
                    recorded_at,
                ),
            )
            self._require_exact_bytes(
                conn,
                "projection_graphiti_workspace_contracts",
                "contract_digest",
                contract.contract_digest,
                canonical,
            )

    @staticmethod
    def _require_exact_bytes(
        conn: sqlite3.Connection,
        table: str,
        key_column: str,
        key: str,
        canonical: bytes,
    ) -> None:
        row = conn.execute(
            f"SELECT canonical_bytes FROM {table} WHERE {key_column}=?",
            (key,),
        ).fetchone()
        if row is None or bytes(row["canonical_bytes"]) != canonical:
            raise AuthorityPersistenceError(
                f"{table} identity belongs to another exact contract"
            )

    def _validate_projection_integrity(self) -> None:
        with self._lock:
            conn = self._connection
            bad_head = conn.execute(
                "SELECT g.generation_id FROM projection_generations g "
                "LEFT JOIN projection_generation_versions v "
                "ON v.generation_id=g.generation_id "
                "AND v.lifecycle_version=g.lifecycle_version "
                "WHERE v.generation_id IS NULL "
                "OR v.state!=g.state "
                "OR NOT (v.validated_through_ledger_seq "
                "IS g.validated_through_ledger_seq) LIMIT 1"
            ).fetchone()
            if bad_head is not None:
                raise AuthorityPersistenceError(
                    "projection generation head lacks exact lifecycle version"
                )
            bad_checkpoint = conn.execute(
                "SELECT c.generation_id FROM projection_checkpoint_versions c "
                "JOIN projection_generations g ON g.generation_id=c.generation_id "
                "GROUP BY c.generation_id HAVING MAX(c.contiguous_ledger_seq) > "
                "(SELECT MAX(ledger_seq) FROM ledger_events) LIMIT 1"
            ).fetchone()
            if bad_checkpoint is not None:
                raise AuthorityPersistenceError(
                    "projection checkpoint exceeds authority ledger"
                )
            bad_family_authority = conn.execute(
                "SELECT f.family_id FROM projection_families f "
                "LEFT JOIN authority_aggregates a "
                "ON a.aggregate_type='projection_family' "
                "AND a.aggregate_id=f.authority_aggregate_id "
                "AND a.current_version=f.authority_aggregate_version "
                "LEFT JOIN ledger_events e ON e.event_id=f.registered_event_id "
                "AND e.aggregate_type='projection_family' "
                "AND e.aggregate_id=f.authority_aggregate_id "
                "AND e.aggregate_version=f.authority_aggregate_version "
                "WHERE a.aggregate_id IS NULL OR e.event_id IS NULL LIMIT 1"
            ).fetchone()
            if bad_family_authority is not None:
                raise AuthorityPersistenceError(
                    "projection family authority head is inconsistent"
                )
            bad_generation_authority = conn.execute(
                "SELECT g.generation_id FROM projection_generations g "
                "LEFT JOIN authority_aggregates a "
                "ON a.aggregate_type='projection_generation' "
                "AND a.aggregate_id=g.generation_id "
                "AND a.current_version=g.authority_aggregate_version "
                "LEFT JOIN ledger_events e ON e.event_id=g.updated_event_id "
                "AND e.aggregate_type='projection_generation' "
                "AND e.aggregate_id=g.generation_id "
                "AND e.aggregate_version=g.authority_aggregate_version "
                "WHERE a.aggregate_id IS NULL OR e.event_id IS NULL LIMIT 1"
            ).fetchone()
            if bad_generation_authority is not None:
                raise AuthorityPersistenceError(
                    "projection generation authority head is inconsistent"
                )
            bad_generation_version = conn.execute(
                "SELECT v.generation_id FROM projection_generation_versions v "
                "LEFT JOIN ledger_events e ON e.event_id=v.authority_event_id "
                "AND e.aggregate_type='projection_generation' "
                "AND e.aggregate_id=v.generation_id "
                "AND e.aggregate_version=v.authority_aggregate_version "
                "WHERE e.event_id IS NULL LIMIT 1"
            ).fetchone()
            if bad_generation_version is not None:
                raise AuthorityPersistenceError(
                    "projection generation version lacks exact authority event"
                )
            bad_checkpoint_authority = conn.execute(
                "SELECT c.generation_id FROM projection_checkpoint_versions c "
                "LEFT JOIN ledger_events e ON e.event_id=c.authority_event_id "
                "AND e.aggregate_type='projection_generation' "
                "AND e.aggregate_id=c.generation_id "
                "AND e.aggregate_version=c.authority_aggregate_version "
                "WHERE e.event_id IS NULL LIMIT 1"
            ).fetchone()
            if bad_checkpoint_authority is not None:
                raise AuthorityPersistenceError(
                    "projection checkpoint lacks exact authority event"
                )
            for family_row in conn.execute(
                "SELECT family_id FROM projection_families"
            ).fetchall():
                self._registered_family_definition(
                    conn, str(family_row["family_id"])
                )
            self._validate_projection_delivery_integrity(conn)
            self._validate_projection_promotion_integrity(conn)

    @staticmethod
    def _validation_canonical_value(row: sqlite3.Row) -> dict[str, object]:
        return {
            "generation_id": str(row["generation_id"]),
            "validation_version": int(row["validation_version"]),
            "lifecycle_version": int(row["lifecycle_version"]),
            "checkpoint_ledger_seq": int(row["checkpoint_ledger_seq"]),
            "definition_digest": str(row["definition_digest"]),
            "ontology_contract_digest": str(row["ontology_contract_digest"]),
            "mapping_contract_digest": str(row["mapping_contract_digest"]),
            "projector_version": str(row["projector_version"]),
            "service_compatibility_digest": str(
                row["service_compatibility_digest"]
            ),
            "projection_state_digest": str(row["projection_state_digest"]),
            "authority_aggregate_version": int(
                row["authority_aggregate_version"]
            ),
            "authority_event_id": str(row["authority_event_id"]),
        }

    @staticmethod
    def _promotion_canonical_value(row: sqlite3.Row) -> dict[str, object]:
        return {
            "family_id": str(row["family_id"]),
            "generation_id": str(row["generation_id"]),
            "prior_generation_id": (
                None
                if row["prior_generation_id"] is None
                else str(row["prior_generation_id"])
            ),
            "checkpoint_ledger_seq": int(row["checkpoint_ledger_seq"]),
            "validation_digest": str(row["validation_digest"]),
            "target_authority_aggregate_version": int(
                row["target_authority_aggregate_version"]
            ),
            "target_authority_event_id": str(row["target_authority_event_id"]),
            "prior_authority_aggregate_version": (
                None
                if row["prior_authority_aggregate_version"] is None
                else int(row["prior_authority_aggregate_version"])
            ),
            "prior_authority_event_id": (
                None
                if row["prior_authority_event_id"] is None
                else str(row["prior_authority_event_id"])
            ),
        }

    def _validate_projection_promotion_integrity(
        self, conn: sqlite3.Connection
    ) -> None:
        for row in conn.execute(
            "SELECT * FROM projection_generation_validations"
        ).fetchall():
            canonical = canonical_json_bytes(
                self._validation_canonical_value(row)
            )
            if (
                bytes(row["canonical_bytes"]) != canonical
                or digest_bytes(canonical) != str(row["validation_digest"])
            ):
                raise AuthorityPersistenceError(
                    "projection generation validation digest is inconsistent"
                )
            generation = self._generation_row(
                conn, str(row["generation_id"])
            )
            family = self._registered_family_definition(
                conn, str(generation["family_id"])
            )
            if (
                str(row["definition_digest"]) != family.digest
                or str(row["ontology_contract_digest"])
                != family.ontology_contract_digest
                or str(row["mapping_contract_digest"])
                != family.mapping_contract_digest
                or str(row["projector_version"]) != family.projector_version
            ):
                raise AuthorityPersistenceError(
                    "projection generation validation contract identity is inconsistent"
                )
            version = conn.execute(
                "SELECT * FROM projection_generation_versions "
                "WHERE generation_id=? AND lifecycle_version=?",
                (
                    str(row["generation_id"]),
                    int(row["lifecycle_version"]),
                ),
            ).fetchone()
            event = conn.execute(
                "SELECT * FROM ledger_events WHERE event_id=? "
                "AND aggregate_type='projection_generation' "
                "AND aggregate_id=? AND aggregate_version=?",
                (
                    str(row["authority_event_id"]),
                    str(row["generation_id"]),
                    int(row["authority_aggregate_version"]),
                ),
            ).fetchone()
            if (
                version is None
                or event is None
                or str(version["state"])
                != ProjectionGenerationState.VALIDATING.value
                or int(version["authority_aggregate_version"])
                != int(row["authority_aggregate_version"])
                or int(version["validated_through_ledger_seq"])
                != int(row["checkpoint_ledger_seq"])
                or str(version["authority_event_id"])
                != str(row["authority_event_id"])
            ):
                raise AuthorityPersistenceError(
                    "projection generation validation lacks exact authority version"
                )

        for row in conn.execute(
            "SELECT * FROM projection_generation_promotions"
        ).fetchall():
            canonical = canonical_json_bytes(
                self._promotion_canonical_value(row)
            )
            if (
                bytes(row["canonical_bytes"]) != canonical
                or digest_bytes(canonical) != str(row["promotion_digest"])
            ):
                raise AuthorityPersistenceError(
                    "projection generation promotion digest is inconsistent"
                )
            target = self._generation_row(conn, str(row["generation_id"]))
            if str(target["family_id"]) != str(row["family_id"]):
                raise AuthorityPersistenceError(
                    "projection generation promotion family is inconsistent"
                )
            validation = conn.execute(
                "SELECT * FROM projection_generation_validations "
                "WHERE validation_digest=? AND generation_id=?",
                (
                    str(row["validation_digest"]),
                    str(row["generation_id"]),
                ),
            ).fetchone()
            target_version = conn.execute(
                "SELECT * FROM projection_generation_versions "
                "WHERE authority_event_id=? AND generation_id=?",
                (
                    str(row["target_authority_event_id"]),
                    str(row["generation_id"]),
                ),
            ).fetchone()
            target_event = conn.execute(
                "SELECT 1 FROM ledger_events WHERE event_id=? "
                "AND aggregate_type='projection_generation' "
                "AND aggregate_id=? AND aggregate_version=?",
                (
                    str(row["target_authority_event_id"]),
                    str(row["generation_id"]),
                    int(row["target_authority_aggregate_version"]),
                ),
            ).fetchone()
            if (
                validation is None
                or int(validation["checkpoint_ledger_seq"])
                != int(row["checkpoint_ledger_seq"])
                or target_version is None
                or target_event is None
                or str(target_version["state"])
                != ProjectionGenerationState.ACTIVE.value
                or int(target_version["authority_aggregate_version"])
                != int(row["target_authority_aggregate_version"])
                or int(target_version["validated_through_ledger_seq"])
                != int(row["checkpoint_ledger_seq"])
            ):
                raise AuthorityPersistenceError(
                    "projection generation promotion lacks exact target authority"
                )
            prior_id = row["prior_generation_id"]
            if prior_id is not None:
                prior = self._generation_row(conn, str(prior_id))
                prior_version = conn.execute(
                    "SELECT * FROM projection_generation_versions "
                    "WHERE authority_event_id=? AND generation_id=?",
                    (str(row["prior_authority_event_id"]), str(prior_id)),
                ).fetchone()
                prior_event = conn.execute(
                    "SELECT 1 FROM ledger_events WHERE event_id=? "
                    "AND aggregate_type='projection_generation' "
                    "AND aggregate_id=? AND aggregate_version=?",
                    (
                        str(row["prior_authority_event_id"]),
                        str(prior_id),
                        int(row["prior_authority_aggregate_version"]),
                    ),
                ).fetchone()
                if (
                    str(prior["family_id"]) != str(row["family_id"])
                    or prior_version is None
                    or prior_event is None
                    or str(prior_version["state"])
                    != ProjectionGenerationState.RETIRED.value
                    or int(prior_version["authority_aggregate_version"])
                    != int(row["prior_authority_aggregate_version"])
                ):
                    raise AuthorityPersistenceError(
                        "projection generation promotion lacks exact prior authority"
                    )

    def _registered_family_definition(
        self, conn: sqlite3.Connection, family_id: str
    ) -> ProjectionFamilyDefinition:
        row = conn.execute(
            "SELECT definition_digest FROM projection_families WHERE family_id=?",
            (family_id,),
        ).fetchone()
        if row is None:
            raise ProjectionStateError("projection family is not registered")
        digest = str(row["definition_digest"])
        try:
            return self._projection_contracts.families.resolve_digest(digest)
        except ProjectionContractError as exc:
            raise AuthorityPersistenceError(
                "registered projection family definition is unavailable"
            ) from exc

    @staticmethod
    def _require_delivery_source_integrity(
        conn: sqlite3.Connection, row: sqlite3.Row
    ) -> LedgerEventRecord:
        source = conn.execute(
            "SELECT * FROM ledger_events WHERE ledger_seq=?",
            (int(row["ledger_seq"]),),
        ).fetchone()
        if source is None:
            raise AuthorityPersistenceError(
                "projection delivery source ledger event is absent"
            )
        source_record = _EventAuthorityStore._event_from_row(source)
        if (
            str(source_record.event_id) != str(row["source_event_id"])
            or source_record.event_type != str(row["source_event_type"])
            or digest_canonical(asdict(source_record))
            != str(row["source_event_digest"])
        ):
            raise AuthorityPersistenceError(
                "projection delivery source provenance is inconsistent"
            )
        authority_event_id = (
            row["authority_event_id"]
            if "authority_event_id" in row.keys()
            else row["last_authority_event_id"]
        )
        if str(source_record.event_id) == str(authority_event_id):
            raise AuthorityPersistenceError(
                "projection delivery targets its own authority event"
            )
        return source_record

    def _validate_projection_delivery_integrity(
        self, conn: sqlite3.Connection
    ) -> None:
        self._validate_projection_family_rows(conn)
        self._validate_projection_gap_heads(conn)
        self._validate_projection_checkpoints(conn)
        self._validate_projection_delivery_rows(conn)

        bad_attempt_authority = conn.execute(
            "SELECT a.delivery_attempt_id FROM projection_delivery_attempts a "
            "LEFT JOIN ledger_events e ON e.event_id=a.authority_event_id "
            "AND e.aggregate_type='projection_generation' "
            "AND e.aggregate_id=a.generation_id "
            "WHERE e.event_id IS NULL LIMIT 1"
        ).fetchone()
        if bad_attempt_authority is not None:
            raise AuthorityPersistenceError(
                "projection delivery attempt lacks exact generation authority"
            )
        bad_state_authority = conn.execute(
            "SELECT s.generation_id FROM projection_delivery_states s "
            "LEFT JOIN ledger_events e ON e.event_id=s.last_authority_event_id "
            "AND e.aggregate_type='projection_generation' "
            "AND e.aggregate_id=s.generation_id "
            "WHERE e.event_id IS NULL LIMIT 1"
        ).fetchone()
        if bad_state_authority is not None:
            raise AuthorityPersistenceError(
                "projection delivery state lacks exact generation authority"
            )
        bad_dead_letter = conn.execute(
            "SELECT d.dead_letter_id FROM projection_dead_letters d "
            "LEFT JOIN ledger_events source ON source.event_id=d.source_event_id "
            "AND source.ledger_seq=d.ledger_seq "
            "LEFT JOIN ledger_events authority "
            "ON authority.event_id=d.authority_event_id "
            "AND authority.aggregate_type='projection_generation' "
            "AND authority.aggregate_id=d.generation_id "
            "WHERE source.event_id IS NULL OR authority.event_id IS NULL LIMIT 1"
        ).fetchone()
        if bad_dead_letter is not None:
            raise AuthorityPersistenceError(
                "projection dead letter provenance is inconsistent"
            )
        bad_dead_letter_attempt = conn.execute(
            "SELECT d.dead_letter_id FROM projection_dead_letters d "
            "LEFT JOIN projection_delivery_attempts a "
            "ON a.generation_id=d.generation_id "
            "AND a.ledger_seq=d.ledger_seq "
            "AND a.source_event_id=d.source_event_id "
            "AND a.attempt_number=d.attempts "
            "AND a.authority_event_id=d.authority_event_id "
            "AND a.outcome IN ('RETRYABLE_FAILURE','REQUIRED_UNSUPPORTED') "
            "WHERE a.delivery_attempt_id IS NULL LIMIT 1"
        ).fetchone()
        if bad_dead_letter_attempt is not None:
            raise AuthorityPersistenceError(
                "projection dead letter lacks its exact failed delivery attempt"
            )
        bad_gap_authority = conn.execute(
            "SELECT v.gap_id FROM projection_gap_versions v "
            "JOIN projection_gaps g ON g.gap_id=v.gap_id "
            "LEFT JOIN ledger_events e ON e.event_id=v.authority_event_id "
            "AND e.aggregate_type='projection_generation' "
            "AND e.aggregate_id=g.generation_id "
            "WHERE e.event_id IS NULL LIMIT 1"
        ).fetchone()
        if bad_gap_authority is not None:
            raise AuthorityPersistenceError(
                "projection gap version lacks exact generation authority"
            )

    def _validate_projection_family_rows(
        self, conn: sqlite3.Connection
    ) -> None:
        for row in conn.execute("SELECT * FROM projection_families").fetchall():
            definition = self._registered_family_definition(
                conn, str(row["family_id"])
            )
            if (
                str(definition.authority_aggregate_id)
                != str(row["authority_aggregate_id"])
                or definition.family_kind.value != str(row["family_kind"])
            ):
                raise AuthorityPersistenceError(
                    "projection family head differs from retained definition"
                )

    @staticmethod
    def _validate_projection_gap_heads(conn: sqlite3.Connection) -> None:
        for gap in conn.execute("SELECT * FROM projection_gaps").fetchall():
            version = conn.execute(
                "SELECT * FROM projection_gap_versions "
                "WHERE gap_id=? AND lifecycle_version=?",
                (str(gap["gap_id"]), int(gap["lifecycle_version"])),
            ).fetchone()
            if version is None or (
                str(version["state"]) != str(gap["state"])
                or int(version["required"]) != int(gap["required"])
                or str(version["reason_code"]) != str(gap["reason_code"])
            ):
                raise AuthorityPersistenceError(
                    "projection gap head differs from exact lifecycle version"
                )
            if str(gap["state"]) == ProjectionGapState.OPEN.value:
                if (
                    gap["resolved_event_id"] is not None
                    or str(version["authority_event_id"])
                    != str(gap["opened_event_id"])
                ):
                    raise AuthorityPersistenceError(
                        "open projection gap provenance is inconsistent"
                    )
            elif (
                gap["resolved_event_id"] is None
                or str(version["authority_event_id"])
                != str(gap["resolved_event_id"])
            ):
                raise AuthorityPersistenceError(
                    "resolved projection gap provenance is inconsistent"
                )

    @staticmethod
    def _validate_projection_checkpoints(conn: sqlite3.Connection) -> None:
        generation_rows = conn.execute(
            "SELECT generation_id FROM projection_generations"
        ).fetchall()
        for generation in generation_rows:
            generation_id = str(generation["generation_id"])
            rows = conn.execute(
                "SELECT checkpoint_version,contiguous_ledger_seq "
                "FROM projection_checkpoint_versions WHERE generation_id=? "
                "ORDER BY checkpoint_version",
                (generation_id,),
            ).fetchall()
            if not rows:
                raise AuthorityPersistenceError(
                    "projection generation lacks checkpoint history"
                )
            previous_version = 0
            previous_sequence = -1
            for row in rows:
                version = int(row["checkpoint_version"])
                sequence = int(row["contiguous_ledger_seq"])
                if version != previous_version + 1 or sequence < previous_sequence:
                    raise AuthorityPersistenceError(
                        "projection checkpoint history is not contiguous and monotonic"
                    )
                previous_version = version
                previous_sequence = sequence
            blocked = conn.execute(
                "SELECT 1 FROM projection_gaps WHERE generation_id=? "
                "AND state='OPEN' AND required=1 "
                "AND ledger_seq_start<=? LIMIT 1",
                (generation_id, previous_sequence),
            ).fetchone()
            if blocked is not None:
                raise AuthorityPersistenceError(
                    "projection checkpoint crosses an unresolved required gap"
                )

    def _validate_projection_delivery_rows(
        self, conn: sqlite3.Connection
    ) -> None:
        attempts_by_delivery: dict[tuple[str, int], list[sqlite3.Row]] = {}
        for attempt in conn.execute(
            "SELECT * FROM projection_delivery_attempts "
            "ORDER BY generation_id,ledger_seq,attempt_number"
        ).fetchall():
            source = self._require_delivery_source_integrity(conn, attempt)
            generation = self._generation_row(
                conn, str(attempt["generation_id"])
            )
            family = self._registered_family_definition(
                conn, str(generation["family_id"])
            )
            mapping = self._projection_contracts.mappings.resolve_digest(
                family.mapping_contract_digest
            ).resolve(source.event_type)
            outcome = ProjectionDeliveryOutcome(str(attempt["outcome"]))
            try:
                self._validate_delivery_outcome(mapping, outcome)
            except ProjectionStateError as exc:
                raise AuthorityPersistenceError(
                    "projection delivery attempt violates retained mapping"
                ) from exc
            required = False if mapping is None else mapping.required
            if bool(attempt["required"]) is not required:
                raise AuthorityPersistenceError(
                    "projection delivery required flag differs from retained mapping"
                )
            key = (str(attempt["generation_id"]), int(attempt["ledger_seq"]))
            attempts_by_delivery.setdefault(key, []).append(attempt)

        states = conn.execute("SELECT * FROM projection_delivery_states").fetchall()
        for state in states:
            self._require_delivery_source_integrity(conn, state)
            key = (str(state["generation_id"]), int(state["ledger_seq"]))
            attempts = attempts_by_delivery.get(key, [])
            count = int(state["attempt_count"])
            if len(attempts) != count or [
                int(item["attempt_number"]) for item in attempts
            ] != list(range(1, count + 1)):
                raise AuthorityPersistenceError(
                    "projection delivery attempt history is not contiguous"
                )
            latest = attempts[-1]
            comparable = (
                ("source_event_id", "source_event_id"),
                ("source_event_digest", "source_event_digest"),
                ("source_event_type", "source_event_type"),
                ("required", "required"),
                ("current_outcome", "outcome"),
                ("last_error_code", "error_code"),
                ("last_authority_event_id", "authority_event_id"),
            )
            for state_field, attempt_field in comparable:
                if state[state_field] != latest[attempt_field]:
                    raise AuthorityPersistenceError(
                        "projection delivery head differs from latest attempt"
                    )
            generation = self._generation_row(conn, key[0])
            family = self._registered_family_definition(
                conn, str(generation["family_id"])
            )
            outcome = ProjectionDeliveryOutcome(str(state["current_outcome"]))
            expected_finalized = (
                outcome in _SUCCESS_OUTCOMES
                or outcome is ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED
                or (
                    outcome is ProjectionDeliveryOutcome.RETRYABLE_FAILURE
                    and count >= family.max_delivery_attempts
                )
            )
            if bool(state["finalized"]) is not expected_finalized:
                raise AuthorityPersistenceError(
                    "projection delivery finalized state is inconsistent"
                )

        orphan_attempt = next(
            (key for key in attempts_by_delivery if not any(
                str(state["generation_id"]) == key[0]
                and int(state["ledger_seq"]) == key[1]
                for state in states
            )),
            None,
        )
        if orphan_attempt is not None:
            raise AuthorityPersistenceError(
                "projection delivery attempt lacks a delivery head"
            )

    def register_family(
        self,
        grant: _AuthorizedCommandGrant,
        definition: ProjectionFamilyDefinition,
    ) -> ProjectionFamilyView:
        with self._lock, self._transaction() as conn:
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            if not result.replayed:
                conn.execute(
                    "INSERT INTO projection_families("
                    "family_id,definition_digest,authority_aggregate_id,family_kind,"
                    "authority_aggregate_version,registered_event_id,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        definition.family_id,
                        definition.digest,
                        str(definition.authority_aggregate_id),
                        definition.family_kind.value,
                        result.aggregate_version,
                        result.event_id,
                        self._clock().to_text(),
                    ),
                )
            return self._family_view(conn, definition.family_id)

    def create_generation(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        generation_id: ProjectionGenerationId,
        family_id: str,
        reason_code: str,
    ) -> ProjectionGenerationView:
        with self._lock, self._transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM projection_families WHERE family_id=?",
                (family_id,),
            ).fetchone() is None:
                raise ProjectionStateError("projection family is not registered")
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            if result.replayed:
                return self._generation_version_for_event(conn, result.event_id)
            recorded_at = self._clock().to_text()
            conn.execute(
                "INSERT INTO projection_generations("
                "generation_id,family_id,state,lifecycle_version,"
                "authority_aggregate_version,validated_through_ledger_seq,"
                "created_event_id,updated_event_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(generation_id),
                    family_id,
                    ProjectionGenerationState.BUILDING.value,
                    1,
                    result.aggregate_version,
                    None,
                    result.event_id,
                    result.event_id,
                    recorded_at,
                    recorded_at,
                ),
            )
            conn.execute(
                "INSERT INTO projection_generation_versions("
                "generation_id,lifecycle_version,state,authority_aggregate_version,"
                "validated_through_ledger_seq,reason_code,authority_event_id,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(generation_id),
                    1,
                    ProjectionGenerationState.BUILDING.value,
                    result.aggregate_version,
                    None,
                    reason_code,
                    result.event_id,
                    recorded_at,
                ),
            )
            conn.execute(
                "INSERT INTO projection_checkpoint_versions("
                "generation_id,checkpoint_version,contiguous_ledger_seq,"
                "authority_aggregate_version,authority_event_id,recorded_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    str(generation_id),
                    1,
                    0,
                    result.aggregate_version,
                    result.event_id,
                    recorded_at,
                ),
            )
            return self._generation_view(conn, str(generation_id))

    def transition_generation(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        generation_id: ProjectionGenerationId,
        target_state: ProjectionGenerationState,
        validated_through_ledger_seq: int | None,
        reason_code: str,
    ) -> ProjectionGenerationView:
        with self._lock, self._transaction() as conn:
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            if result.replayed:
                return self._generation_version_for_event(conn, result.event_id)
            if target_state is ProjectionGenerationState.ACTIVE:
                raise ProjectionStateError(
                    "ACTIVE generation requires authority promotion"
                )
            current = self._generation_row(conn, str(generation_id))
            state = ProjectionGenerationState(str(current["state"]))
            if target_state not in _ALLOWED_TRANSITIONS[state]:
                raise ProjectionStateError(
                    f"invalid generation transition: {state.value}->{target_state.value}"
                )
            checkpoint = self._checkpoint_seq(conn, str(generation_id))
            current_validated = (
                None
                if current["validated_through_ledger_seq"] is None
                else int(current["validated_through_ledger_seq"])
            )
            if target_state is ProjectionGenerationState.VALIDATING:
                if validated_through_ledger_seq is None:
                    validated_through_ledger_seq = checkpoint
                if validated_through_ledger_seq > checkpoint:
                    raise ProjectionStateError(
                        "generation cannot validate beyond contiguous checkpoint"
                    )
            elif target_state is ProjectionGenerationState.ACTIVE:
                active = conn.execute(
                    "SELECT generation_id FROM projection_generations "
                    "WHERE family_id=? AND state='ACTIVE' AND generation_id!=? LIMIT 1",
                    (str(current["family_id"]), str(generation_id)),
                ).fetchone()
                if active is not None:
                    raise ProjectionStateError(
                        "projection family already has an active generation"
                    )
                if validated_through_ledger_seq is None:
                    validated_through_ledger_seq = current_validated
                if validated_through_ledger_seq is None:
                    raise ProjectionStateError(
                        "ACTIVE generation requires validated-through sequence"
                    )
                if (
                    current_validated is not None
                    and validated_through_ledger_seq < current_validated
                ):
                    raise ProjectionStateError(
                        "ACTIVE generation cannot regress validation coverage"
                    )
                if validated_through_ledger_seq != checkpoint:
                    raise ProjectionStateError(
                        "ACTIVE generation must be validated through the current contiguous checkpoint"
                    )
                open_required = conn.execute(
                    "SELECT 1 FROM projection_gaps WHERE generation_id=? "
                    "AND state='OPEN' AND required=1 AND ledger_seq_start<=? LIMIT 1",
                    (str(generation_id), validated_through_ledger_seq),
                ).fetchone()
                if open_required is not None:
                    raise ProjectionStateError(
                        "generation cannot activate across a required gap"
                    )
            else:
                if (
                    validated_through_ledger_seq is not None
                    and validated_through_ledger_seq != current_validated
                ):
                    raise ProjectionStateError(
                        "terminal generation transition cannot rewrite validation coverage"
                    )
                validated_through_ledger_seq = current_validated
            lifecycle_version = int(current["lifecycle_version"]) + 1
            recorded_at = self._clock().to_text()
            conn.execute(
                "UPDATE projection_generations SET state=?,lifecycle_version=?,"
                "authority_aggregate_version=?,validated_through_ledger_seq=?,"
                "updated_event_id=?,updated_at=? WHERE generation_id=?",
                (
                    target_state.value,
                    lifecycle_version,
                    result.aggregate_version,
                    validated_through_ledger_seq,
                    result.event_id,
                    recorded_at,
                    str(generation_id),
                ),
            )
            conn.execute(
                "INSERT INTO projection_generation_versions("
                "generation_id,lifecycle_version,state,authority_aggregate_version,"
                "validated_through_ledger_seq,reason_code,authority_event_id,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(generation_id),
                    lifecycle_version,
                    target_state.value,
                    result.aggregate_version,
                    validated_through_ledger_seq,
                    reason_code,
                    result.event_id,
                    recorded_at,
                ),
            )
            return self._generation_view(conn, str(generation_id))

    def validate_generation(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        generation_id: ProjectionGenerationId,
        checkpoint_ledger_seq: int,
        service_compatibility_digest: str,
        projection_state_digest: str,
        reason_code: str,
    ) -> ProjectionGenerationValidationView:
        with self._lock, self._transaction() as conn:
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            if result.replayed:
                return self._validation_for_authority_event(conn, result.event_id)
            current = self._generation_row(conn, str(generation_id))
            state = ProjectionGenerationState(str(current["state"]))
            if state not in {
                ProjectionGenerationState.BUILDING,
                ProjectionGenerationState.VALIDATING,
            }:
                raise ProjectionStateError(
                    "only building or validating generations can be validated"
                )
            checkpoint = self._checkpoint_seq(conn, str(generation_id))
            if checkpoint_ledger_seq != checkpoint:
                raise ProjectionStateError(
                    "generation validation must bind the exact current contiguous checkpoint"
                )
            open_required = conn.execute(
                "SELECT 1 FROM projection_gaps WHERE generation_id=? "
                "AND state='OPEN' AND required=1 AND ledger_seq_start<=? LIMIT 1",
                (str(generation_id), checkpoint_ledger_seq),
            ).fetchone()
            if open_required is not None:
                raise ProjectionStateError(
                    "generation cannot validate across a required gap"
                )
            family = self._registered_family_definition(
                conn, str(current["family_id"])
            )
            validation_version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(validation_version),0)+1 "
                    "FROM projection_generation_validations WHERE generation_id=?",
                    (str(generation_id),),
                ).fetchone()[0]
            )
            lifecycle_version = int(current["lifecycle_version"]) + 1
            recorded_at = self._clock().to_text()
            canonical_value: dict[str, object] = {
                "generation_id": str(generation_id),
                "validation_version": validation_version,
                "lifecycle_version": lifecycle_version,
                "checkpoint_ledger_seq": checkpoint_ledger_seq,
                "definition_digest": family.digest,
                "ontology_contract_digest": family.ontology_contract_digest,
                "mapping_contract_digest": family.mapping_contract_digest,
                "projector_version": family.projector_version,
                "service_compatibility_digest": service_compatibility_digest,
                "projection_state_digest": projection_state_digest,
                "authority_aggregate_version": result.aggregate_version,
                "authority_event_id": str(result.event_id),
            }
            canonical = canonical_json_bytes(canonical_value)
            validation_digest = digest_bytes(canonical)
            conn.execute(
                "UPDATE projection_generations SET state=?,lifecycle_version=?,"
                "authority_aggregate_version=?,validated_through_ledger_seq=?,"
                "updated_event_id=?,updated_at=? WHERE generation_id=?",
                (
                    ProjectionGenerationState.VALIDATING.value,
                    lifecycle_version,
                    result.aggregate_version,
                    checkpoint_ledger_seq,
                    result.event_id,
                    recorded_at,
                    str(generation_id),
                ),
            )
            conn.execute(
                "INSERT INTO projection_generation_versions("
                "generation_id,lifecycle_version,state,authority_aggregate_version,"
                "validated_through_ledger_seq,reason_code,authority_event_id,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(generation_id),
                    lifecycle_version,
                    ProjectionGenerationState.VALIDATING.value,
                    result.aggregate_version,
                    checkpoint_ledger_seq,
                    reason_code,
                    result.event_id,
                    recorded_at,
                ),
            )
            conn.execute(
                "INSERT INTO projection_generation_validations("
                "validation_digest,generation_id,validation_version,lifecycle_version,"
                "checkpoint_ledger_seq,definition_digest,ontology_contract_digest,"
                "mapping_contract_digest,projector_version,"
                "service_compatibility_digest,projection_state_digest,canonical_bytes,"
                "authority_aggregate_version,authority_event_id,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    validation_digest,
                    str(generation_id),
                    validation_version,
                    lifecycle_version,
                    checkpoint_ledger_seq,
                    family.digest,
                    family.ontology_contract_digest,
                    family.mapping_contract_digest,
                    family.projector_version,
                    service_compatibility_digest,
                    projection_state_digest,
                    canonical,
                    result.aggregate_version,
                    result.event_id,
                    recorded_at,
                ),
            )
            return self._validation_view_from_row(
                conn.execute(
                    "SELECT * FROM projection_generation_validations "
                    "WHERE validation_digest=?",
                    (validation_digest,),
                ).fetchone()
            )

    def promote_generation(
        self,
        target_grant: _AuthorizedCommandGrant,
        prior_grant: _AuthorizedCommandGrant | None,
        *,
        generation_id: ProjectionGenerationId,
        checkpoint_ledger_seq: int,
        validation_digest: str,
        prior_generation_id: ProjectionGenerationId | None,
        reason_code: str,
    ) -> ProjectionGenerationPromotionView:
        with self._lock, self._transaction() as conn:
            recorded_at = self._clock().to_text()
            prior_result = None
            if prior_grant is not None:
                prior_result = self._commit_grant_in_transaction(
                    conn, prior_grant, recorded_at=recorded_at
                )
            target_result = self._commit_grant_in_transaction(
                conn, target_grant, recorded_at=recorded_at
            )
            if target_result.replayed:
                if prior_result is not None and not prior_result.replayed:
                    raise AuthorityPersistenceError(
                        "projection promotion replay is only partially retained"
                    )
                return self._promotion_for_authority_event(
                    conn, target_result.event_id
                )
            if prior_result is not None and prior_result.replayed:
                raise ProjectionStateError(
                    "projection promotion cannot reuse a prior retirement command"
                )

            current = self._generation_row(conn, str(generation_id))
            if ProjectionGenerationState(str(current["state"])) is not (
                ProjectionGenerationState.VALIDATING
            ):
                raise ProjectionStateError(
                    "only a validating generation can be promoted"
                )
            family_id = str(current["family_id"])
            checkpoint = self._checkpoint_seq(conn, str(generation_id))
            if checkpoint_ledger_seq != checkpoint:
                raise ProjectionStateError(
                    "promotion checkpoint is stale"
                )
            current_validated = current["validated_through_ledger_seq"]
            if (
                current_validated is None
                or int(current_validated) != checkpoint_ledger_seq
            ):
                raise ProjectionStateError(
                    "promotion requires validation through the exact current checkpoint"
                )
            validation = conn.execute(
                "SELECT * FROM projection_generation_validations "
                "WHERE validation_digest=? AND generation_id=?",
                (validation_digest, str(generation_id)),
            ).fetchone()
            if validation is None:
                raise ProjectionStateError(
                    "promotion requires retained validation evidence"
                )
            if (
                int(validation["checkpoint_ledger_seq"]) != checkpoint_ledger_seq
                or int(validation["lifecycle_version"])
                != int(current["lifecycle_version"])
                or int(validation["authority_aggregate_version"])
                != int(current["authority_aggregate_version"])
                or str(validation["authority_event_id"])
                != str(current["updated_event_id"])
            ):
                raise ProjectionStateError(
                    "promotion validation evidence is stale"
                )
            family = self._registered_family_definition(conn, family_id)
            if (
                str(validation["definition_digest"]) != family.digest
                or str(validation["ontology_contract_digest"])
                != family.ontology_contract_digest
                or str(validation["mapping_contract_digest"])
                != family.mapping_contract_digest
                or str(validation["projector_version"]) != family.projector_version
            ):
                raise AuthorityPersistenceError(
                    "promotion validation differs from retained family contracts"
                )
            open_required = conn.execute(
                "SELECT 1 FROM projection_gaps WHERE generation_id=? "
                "AND state='OPEN' AND required=1 AND ledger_seq_start<=? LIMIT 1",
                (str(generation_id), checkpoint_ledger_seq),
            ).fetchone()
            if open_required is not None:
                raise ProjectionStateError(
                    "generation cannot promote across a required gap"
                )

            active = conn.execute(
                "SELECT * FROM projection_generations WHERE family_id=? "
                "AND state='ACTIVE' LIMIT 1",
                (family_id,),
            ).fetchone()
            expected_prior_id = (
                None if prior_generation_id is None else str(prior_generation_id)
            )
            actual_prior_id = (
                None if active is None else str(active["generation_id"])
            )
            if actual_prior_id != expected_prior_id:
                raise ProjectionStateError(
                    "promotion prior active generation changed"
                )
            if (active is None) != (prior_result is None):
                raise ProjectionStateError(
                    "promotion prior retirement authority is incomplete"
                )

            prior_view = None
            if active is not None:
                assert prior_result is not None
                prior_lifecycle_version = int(active["lifecycle_version"]) + 1
                prior_validated = (
                    None
                    if active["validated_through_ledger_seq"] is None
                    else int(active["validated_through_ledger_seq"])
                )
                conn.execute(
                    "UPDATE projection_generations SET state=?,lifecycle_version=?,"
                    "authority_aggregate_version=?,validated_through_ledger_seq=?,"
                    "updated_event_id=?,updated_at=? WHERE generation_id=?",
                    (
                        ProjectionGenerationState.RETIRED.value,
                        prior_lifecycle_version,
                        prior_result.aggregate_version,
                        prior_validated,
                        prior_result.event_id,
                        recorded_at,
                        actual_prior_id,
                    ),
                )
                conn.execute(
                    "INSERT INTO projection_generation_versions("
                    "generation_id,lifecycle_version,state,authority_aggregate_version,"
                    "validated_through_ledger_seq,reason_code,authority_event_id,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        actual_prior_id,
                        prior_lifecycle_version,
                        ProjectionGenerationState.RETIRED.value,
                        prior_result.aggregate_version,
                        prior_validated,
                        reason_code,
                        prior_result.event_id,
                        recorded_at,
                    ),
                )
                prior_view = self._generation_view(conn, actual_prior_id)

            target_lifecycle_version = int(current["lifecycle_version"]) + 1
            conn.execute(
                "UPDATE projection_generations SET state=?,lifecycle_version=?,"
                "authority_aggregate_version=?,validated_through_ledger_seq=?,"
                "updated_event_id=?,updated_at=? WHERE generation_id=?",
                (
                    ProjectionGenerationState.ACTIVE.value,
                    target_lifecycle_version,
                    target_result.aggregate_version,
                    checkpoint_ledger_seq,
                    target_result.event_id,
                    recorded_at,
                    str(generation_id),
                ),
            )
            conn.execute(
                "INSERT INTO projection_generation_versions("
                "generation_id,lifecycle_version,state,authority_aggregate_version,"
                "validated_through_ledger_seq,reason_code,authority_event_id,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(generation_id),
                    target_lifecycle_version,
                    ProjectionGenerationState.ACTIVE.value,
                    target_result.aggregate_version,
                    checkpoint_ledger_seq,
                    reason_code,
                    target_result.event_id,
                    recorded_at,
                ),
            )
            canonical_value: dict[str, object] = {
                "family_id": family_id,
                "generation_id": str(generation_id),
                "prior_generation_id": actual_prior_id,
                "checkpoint_ledger_seq": checkpoint_ledger_seq,
                "validation_digest": validation_digest,
                "target_authority_aggregate_version": target_result.aggregate_version,
                "target_authority_event_id": str(target_result.event_id),
                "prior_authority_aggregate_version": (
                    None if prior_result is None else prior_result.aggregate_version
                ),
                "prior_authority_event_id": (
                    None if prior_result is None else str(prior_result.event_id)
                ),
            }
            canonical = canonical_json_bytes(canonical_value)
            promotion_digest = digest_bytes(canonical)
            conn.execute(
                "INSERT INTO projection_generation_promotions("
                "promotion_digest,family_id,generation_id,prior_generation_id,"
                "checkpoint_ledger_seq,validation_digest,"
                "target_authority_aggregate_version,target_authority_event_id,"
                "prior_authority_aggregate_version,prior_authority_event_id,"
                "canonical_bytes,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    promotion_digest,
                    family_id,
                    str(generation_id),
                    actual_prior_id,
                    checkpoint_ledger_seq,
                    validation_digest,
                    target_result.aggregate_version,
                    target_result.event_id,
                    None if prior_result is None else prior_result.aggregate_version,
                    None if prior_result is None else prior_result.event_id,
                    canonical,
                    recorded_at,
                ),
            )
            target_view = self._generation_view(conn, str(generation_id))
            return ProjectionGenerationPromotionView(
                promotion_digest=promotion_digest,
                family_id=family_id,
                generation=target_view,
                prior_generation=prior_view,
                checkpoint_ledger_seq=checkpoint_ledger_seq,
                validation_digest=validation_digest,
                target_authority_event_id=EventId.parse(
                    str(target_result.event_id)
                ),
                prior_authority_event_id=(
                    None
                    if prior_result is None
                    else EventId.parse(str(prior_result.event_id))
                ),
                recorded_at=UtcTimestamp.parse(recorded_at),
            )

    def begin_projection_rebuild(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        generation_id: ProjectionGenerationId,
        through_ledger_seq: int,
    ) -> _ProjectionRebuildReceipt:
        with self._lock, self._transaction() as conn:
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            current = self._generation_row(conn, str(generation_id))
            state = ProjectionGenerationState(str(current["state"]))
            if state is not ProjectionGenerationState.BUILDING:
                raise ProjectionStateError(
                    "only a building generation can be destructively rebuilt"
                )
            checkpoint = self._checkpoint_seq(conn, str(generation_id))
            if not result.replayed and through_ledger_seq < checkpoint:
                raise ProjectionStateError(
                    "rebuild target cannot precede the authoritative checkpoint"
                )
            maximum_before_rebuild = result.ledger_seq - 1
            if through_ledger_seq > maximum_before_rebuild:
                raise ProjectionStateError(
                    "rebuild target exceeds retained authority at command commit"
                )
            recorded_at = self._source_event(conn, result.ledger_seq).recorded_at
            if not result.replayed:
                self._update_generation_authority_version(
                    conn,
                    generation_id=str(generation_id),
                    authority_version=result.aggregate_version,
                    authority_event_id=result.event_id,
                    recorded_at=recorded_at,
                )
                self._advance_checkpoint(
                    conn,
                    generation_id=str(generation_id),
                    authority_version=result.aggregate_version,
                    authority_event_id=result.event_id,
                    recorded_at=recorded_at,
                )
            return _ProjectionRebuildReceipt(
                generation=self._generation_view(conn, str(generation_id)),
                through_ledger_seq=through_ledger_seq,
                authority_event_id=EventId.parse(str(result.event_id)),
                replayed=result.replayed,
                recorded_at=UtcTimestamp.parse(recorded_at),
            )

    def record_delivery(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        generation_id: ProjectionGenerationId,
        ledger_seq: int,
        outcome: ProjectionDeliveryOutcome,
        error_code: str | None,
    ) -> DeliveryRecordView:
        with self._lock, self._transaction() as conn:
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            if result.replayed:
                return self._delivery_for_authority_event(conn, result.event_id)
            generation = self._generation_row(conn, str(generation_id))
            generation_state = ProjectionGenerationState(str(generation["state"]))
            if generation_state in _TERMINAL_GENERATION_STATES:
                raise ProjectionStateError(
                    "terminal projection generation cannot accept deliveries"
                )
            family = self._registered_family_definition(
                conn, str(generation["family_id"])
            )
            mapping_contract = self._projection_contracts.mappings.resolve_digest(
                family.mapping_contract_digest
            )
            source = self._source_event(conn, ledger_seq)
            if source.event_id == result.event_id:
                raise ProjectionStateError(
                    "projection delivery cannot target its own authority event"
                )
            mapping = mapping_contract.resolve(source.event_type)
            required = False if mapping is None else mapping.required
            self._validate_delivery_outcome(mapping, outcome)
            source_digest = digest_canonical(asdict(source))
            existing = conn.execute(
                "SELECT * FROM projection_delivery_states "
                "WHERE generation_id=? AND ledger_seq=?",
                (str(generation_id), ledger_seq),
            ).fetchone()
            if existing is not None and int(existing["finalized"]) == 1:
                previous = ProjectionDeliveryOutcome(str(existing["current_outcome"]))
                recoverable = previous in {
                    ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                    ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED,
                } and (
                    outcome is ProjectionDeliveryOutcome.APPLIED
                    or (
                        not bool(existing["required"])
                        and outcome
                        is ProjectionDeliveryOutcome.IGNORED_OPTIONAL
                    )
                )
                if not recoverable:
                    raise ProjectionStateError("projection delivery is already finalized")
            attempt_number = 1 if existing is None else int(existing["attempt_count"]) + 1
            if existing is not None:
                if (
                    str(existing["source_event_id"]) != source.event_id
                    or str(existing["source_event_digest"]) != source_digest
                ):
                    raise ProjectionStateError(
                        "projection sequence belongs to another source event"
                    )
            checkpoint = self._checkpoint_seq(conn, str(generation_id))
            if ledger_seq - checkpoint - 1 > family.max_gap_span:
                raise ProjectionStateError("projection delivery exceeds maximum gap span")
            recorded_at = self._clock().to_text()
            for missing_seq in range(checkpoint + 1, ledger_seq):
                if conn.execute(
                    "SELECT 1 FROM projection_delivery_states "
                    "WHERE generation_id=? AND ledger_seq=? AND finalized=1",
                    (str(generation_id), missing_seq),
                ).fetchone() is not None:
                    continue
                missing = self._source_event(conn, missing_seq)
                missing_mapping = mapping_contract.resolve(missing.event_type)
                if missing_mapping is not None and missing_mapping.required:
                    self._open_gap(
                        conn,
                        generation_id=str(generation_id),
                        ledger_seq=missing_seq,
                        required=True,
                        reason_code="OUT_OF_ORDER_DELIVERY",
                        authority_event_id=result.event_id,
                        recorded_at=recorded_at,
                    )
            finalized = outcome in _SUCCESS_OUTCOMES
            should_dead_letter = False
            if outcome is ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED:
                finalized = True
                should_dead_letter = True
            elif (
                outcome is ProjectionDeliveryOutcome.RETRYABLE_FAILURE
                and attempt_number >= family.max_delivery_attempts
            ):
                finalized = True
                should_dead_letter = True
            attempt_id = str(ProjectionDeliveryAttemptId.new())
            conn.execute(
                "INSERT INTO projection_delivery_attempts("
                "delivery_attempt_id,generation_id,ledger_seq,source_event_id,"
                "source_event_digest,source_event_type,attempt_number,outcome,required,"
                "error_code,authority_event_id,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    str(generation_id),
                    ledger_seq,
                    source.event_id,
                    source_digest,
                    source.event_type,
                    attempt_number,
                    outcome.value,
                    int(required),
                    error_code,
                    result.event_id,
                    recorded_at,
                ),
            )
            if existing is None:
                conn.execute(
                    "INSERT INTO projection_delivery_states("
                    "generation_id,ledger_seq,source_event_id,source_event_digest,"
                    "source_event_type,required,attempt_count,current_outcome,finalized,"
                    "last_error_code,last_authority_event_id,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(generation_id),
                        ledger_seq,
                        source.event_id,
                        source_digest,
                        source.event_type,
                        int(required),
                        attempt_number,
                        outcome.value,
                        int(finalized),
                        error_code,
                        result.event_id,
                        recorded_at,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE projection_delivery_states SET attempt_count=?,"
                    "current_outcome=?,finalized=?,last_error_code=?,"
                    "last_authority_event_id=?,updated_at=? "
                    "WHERE generation_id=? AND ledger_seq=?",
                    (
                        attempt_number,
                        outcome.value,
                        int(finalized),
                        error_code,
                        result.event_id,
                        recorded_at,
                        str(generation_id),
                        ledger_seq,
                    ),
                )
            if outcome not in _SUCCESS_OUTCOMES and should_dead_letter:
                reason = error_code or outcome.value
                self._open_gap(
                    conn,
                    generation_id=str(generation_id),
                    ledger_seq=ledger_seq,
                    required=required,
                    reason_code=(
                        "DEAD_LETTERED_REQUIRED_EVENT"
                        if required
                        else "DEAD_LETTERED_OPTIONAL_EVENT"
                    ),
                    authority_event_id=result.event_id,
                    recorded_at=recorded_at,
                )
                conn.execute(
                    "INSERT INTO projection_dead_letters("
                    "dead_letter_id,generation_id,ledger_seq,source_event_id,attempts,"
                    "reason_code,authority_event_id,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        str(ProjectionDeadLetterId.new()),
                        str(generation_id),
                        ledger_seq,
                        source.event_id,
                        attempt_number,
                        reason,
                        result.event_id,
                        recorded_at,
                    ),
                )
            self._update_generation_authority_version(
                conn,
                generation_id=str(generation_id),
                authority_version=result.aggregate_version,
                authority_event_id=result.event_id,
                recorded_at=recorded_at,
            )
            self._advance_checkpoint(
                conn,
                generation_id=str(generation_id),
                authority_version=result.aggregate_version,
                authority_event_id=result.event_id,
                recorded_at=recorded_at,
            )
            return self._delivery_for_authority_event(conn, result.event_id)

    def resolve_gap(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        generation_id: ProjectionGenerationId,
        gap_id: ProjectionGapId,
        reason_code: str,
    ) -> ProjectionGapView:
        with self._lock, self._transaction() as conn:
            result = self._commit_grant_in_transaction(
                conn, grant, recorded_at=self._clock().to_text()
            )
            if result.replayed:
                return self._gap_version_for_event(conn, result.event_id)
            generation = self._generation_row(conn, str(generation_id))
            if ProjectionGenerationState(str(generation["state"])) in _TERMINAL_GENERATION_STATES:
                raise ProjectionStateError(
                    "terminal projection generation cannot resolve gaps"
                )
            gap = conn.execute(
                "SELECT * FROM projection_gaps WHERE gap_id=? AND generation_id=?",
                (str(gap_id), str(generation_id)),
            ).fetchone()
            if gap is None:
                raise ProjectionStateError("projection gap does not exist")
            if str(gap["state"]) != ProjectionGapState.OPEN.value:
                raise ProjectionStateError("projection gap is not open")
            unfinished = conn.execute(
                "SELECT 1 FROM projection_delivery_states WHERE generation_id=? "
                "AND ledger_seq BETWEEN ? AND ? AND finalized=0 LIMIT 1",
                (
                    str(generation_id),
                    int(gap["ledger_seq_start"]),
                    int(gap["ledger_seq_end"]),
                ),
            ).fetchone()
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM projection_delivery_states "
                    "WHERE generation_id=? AND ledger_seq BETWEEN ? AND ? "
                    "AND finalized=1 AND current_outcome IN ('APPLIED','IGNORED_OPTIONAL')",
                    (
                        str(generation_id),
                        int(gap["ledger_seq_start"]),
                        int(gap["ledger_seq_end"]),
                    ),
                ).fetchone()[0]
            )
            expected = int(gap["ledger_seq_end"]) - int(gap["ledger_seq_start"]) + 1
            if unfinished is not None or count != expected:
                raise ProjectionStateError(
                    "required gap cannot be waived without successful delivery"
                )
            recorded_at = self._clock().to_text()
            self._resolve_gap_row(
                conn,
                gap,
                authority_event_id=result.event_id,
                recorded_at=recorded_at,
                reason_code=reason_code,
            )
            self._update_generation_authority_version(
                conn,
                generation_id=str(generation_id),
                authority_version=result.aggregate_version,
                authority_event_id=result.event_id,
                recorded_at=recorded_at,
            )
            self._advance_checkpoint(
                conn,
                generation_id=str(generation_id),
                authority_version=result.aggregate_version,
                authority_event_id=result.event_id,
                recorded_at=recorded_at,
            )
            return self._gap_version_for_event(conn, result.event_id)

    def _validate_delivery_outcome(
        self,
        mapping: StructuralEventMapping | None,
        outcome: ProjectionDeliveryOutcome,
    ) -> None:
        if mapping is None:
            if outcome is not ProjectionDeliveryOutcome.IGNORED_OPTIONAL:
                raise ProjectionStateError(
                    "unmapped event may only be ignored as optional"
                )
            return
        if mapping.required and outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL:
            raise ProjectionStateError("required event cannot be ignored")
        if (
            not mapping.required
            and outcome is ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED
        ):
            raise ProjectionStateError(
                "optional event cannot be marked required-unsupported"
            )

    def _open_gap(
        self,
        conn: sqlite3.Connection,
        *,
        generation_id: str,
        ledger_seq: int,
        required: bool,
        reason_code: str,
        authority_event_id: str,
        recorded_at: str,
    ) -> None:
        existing = conn.execute(
            "SELECT * FROM projection_gaps WHERE generation_id=? "
            "AND ledger_seq_start=? AND ledger_seq_end=?",
            (generation_id, ledger_seq, ledger_seq),
        ).fetchone()
        if existing is not None:
            if str(existing["state"]) == ProjectionGapState.OPEN.value:
                if required and not bool(existing["required"]):
                    raise ProjectionStateError(
                        "existing optional gap cannot be silently upgraded"
                    )
                return
            raise ProjectionStateError("resolved projection gap cannot be reopened")
        gap_id = str(ProjectionGapId.new())
        conn.execute(
            "INSERT INTO projection_gaps("
            "gap_id,generation_id,ledger_seq_start,ledger_seq_end,state,"
            "lifecycle_version,required,reason_code,opened_event_id,"
            "resolved_event_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?)",
            (
                gap_id,
                generation_id,
                ledger_seq,
                ledger_seq,
                ProjectionGapState.OPEN.value,
                1,
                int(required),
                reason_code,
                authority_event_id,
                recorded_at,
                recorded_at,
            ),
        )
        conn.execute(
            "INSERT INTO projection_gap_versions("
            "gap_id,lifecycle_version,state,required,reason_code,"
            "authority_event_id,recorded_at) VALUES(?,?,?,?,?,?,?)",
            (
                gap_id,
                1,
                ProjectionGapState.OPEN.value,
                int(required),
                reason_code,
                authority_event_id,
                recorded_at,
            ),
        )

    def _resolve_gap_for_sequence(
        self,
        conn: sqlite3.Connection,
        *,
        generation_id: str,
        ledger_seq: int,
        authority_event_id: str,
        recorded_at: str,
    ) -> None:
        rows = conn.execute(
            "SELECT * FROM projection_gaps WHERE generation_id=? AND state='OPEN' "
            "AND ledger_seq_start<=? AND ledger_seq_end>=?",
            (generation_id, ledger_seq, ledger_seq),
        ).fetchall()
        for row in rows:
            self._resolve_gap_row(
                conn,
                row,
                authority_event_id=authority_event_id,
                recorded_at=recorded_at,
                reason_code="DELIVERY_SUCCEEDED",
            )

    @staticmethod
    def _resolve_gap_row(
        conn: sqlite3.Connection,
        gap: sqlite3.Row,
        *,
        authority_event_id: str,
        recorded_at: str,
        reason_code: str,
    ) -> None:
        version = int(gap["lifecycle_version"]) + 1
        conn.execute(
            "UPDATE projection_gaps SET state='RESOLVED',lifecycle_version=?,"
            "reason_code=?,resolved_event_id=?,updated_at=? WHERE gap_id=?",
            (
                version,
                reason_code,
                authority_event_id,
                recorded_at,
                str(gap["gap_id"]),
            ),
        )
        conn.execute(
            "INSERT INTO projection_gap_versions("
            "gap_id,lifecycle_version,state,required,reason_code,"
            "authority_event_id,recorded_at) VALUES(?,?,?,?,?,?,?)",
            (
                str(gap["gap_id"]),
                version,
                ProjectionGapState.RESOLVED.value,
                int(gap["required"]),
                reason_code,
                authority_event_id,
                recorded_at,
            ),
        )

    def _advance_checkpoint(
        self,
        conn: sqlite3.Connection,
        *,
        generation_id: str,
        authority_version: int,
        authority_event_id: str,
        recorded_at: str,
    ) -> None:
        current = self._checkpoint_seq(conn, generation_id)
        candidate = current
        while True:
            next_seq = candidate + 1
            gap = conn.execute(
                "SELECT 1 FROM projection_gaps WHERE generation_id=? "
                "AND state='OPEN' AND ledger_seq_start<=? AND ledger_seq_end>=? LIMIT 1",
                (generation_id, next_seq, next_seq),
            ).fetchone()
            if gap is not None:
                break
            delivery = conn.execute(
                "SELECT finalized,current_outcome FROM projection_delivery_states "
                "WHERE generation_id=? AND ledger_seq=?",
                (generation_id, next_seq),
            ).fetchone()
            if delivery is not None:
                if int(delivery["finalized"]) != 1:
                    break
                if ProjectionDeliveryOutcome(str(delivery["current_outcome"])) not in _SUCCESS_OUTCOMES:
                    break
                candidate = next_seq
                continue

            # Projection management events and other explicitly optional/unmapped
            # events are deterministically skipped under the retained mapping
            # contract. Requiring a new delivery command for those events would
            # create an infinite self-generated ledger tail.
            source = conn.execute(
                "SELECT event_type FROM ledger_events WHERE ledger_seq=?",
                (next_seq,),
            ).fetchone()
            if source is None:
                break
            generation = self._generation_row(conn, generation_id)
            family = self._registered_family_definition(
                conn, str(generation["family_id"])
            )
            mapping_contract = self._projection_contracts.mappings.resolve_digest(
                family.mapping_contract_digest
            )
            mapping = mapping_contract.resolve(str(source["event_type"]))
            if mapping is not None and mapping.required:
                break
            candidate = next_seq
        if candidate == current:
            return
        version = int(
            conn.execute(
                "SELECT COALESCE(MAX(checkpoint_version),0)+1 "
                "FROM projection_checkpoint_versions WHERE generation_id=?",
                (generation_id,),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO projection_checkpoint_versions("
            "generation_id,checkpoint_version,contiguous_ledger_seq,"
            "authority_aggregate_version,authority_event_id,recorded_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                generation_id,
                version,
                candidate,
                authority_version,
                authority_event_id,
                recorded_at,
            ),
        )

    @staticmethod
    def _update_generation_authority_version(
        conn: sqlite3.Connection,
        *,
        generation_id: str,
        authority_version: int,
        authority_event_id: str,
        recorded_at: str,
    ) -> None:
        conn.execute(
            "UPDATE projection_generations SET authority_aggregate_version=?,"
            "updated_event_id=?,updated_at=? WHERE generation_id=?",
            (
                authority_version,
                authority_event_id,
                recorded_at,
                generation_id,
            ),
        )

    def _source_event(
        self, conn: sqlite3.Connection, ledger_seq: int
    ) -> LedgerEventRecord:
        row = conn.execute(
            "SELECT * FROM ledger_events WHERE ledger_seq=?",
            (ledger_seq,),
        ).fetchone()
        if row is None:
            raise ProjectionStateError("source ledger event does not exist")
        return self._event_from_row(row)

    @staticmethod
    def _generation_row(
        conn: sqlite3.Connection, generation_id: str
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM projection_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        if row is None:
            raise ProjectionStateError("projection generation does not exist")
        return row

    def _checkpoint_seq(self, conn: sqlite3.Connection, generation_id: str) -> int:
        row = conn.execute(
            "SELECT contiguous_ledger_seq FROM projection_checkpoint_versions "
            "WHERE generation_id=? ORDER BY checkpoint_version DESC LIMIT 1",
            (generation_id,),
        ).fetchone()
        if row is None:
            raise ProjectionStateError("projection generation lacks checkpoint")
        return int(row["contiguous_ledger_seq"])

    def _family_view(self, conn: sqlite3.Connection, family_id: str) -> ProjectionFamilyView:
        row = conn.execute(
            "SELECT * FROM projection_families WHERE family_id=?",
            (family_id,),
        ).fetchone()
        if row is None:
            raise ProjectionStateError("projection family is not registered")
        definition = self._registered_family_definition(conn, family_id)
        return ProjectionFamilyView(
            family_id=str(row["family_id"]),
            definition_digest=str(row["definition_digest"]),
            authority_aggregate_id=definition.authority_aggregate_id,
            family_kind=ProjectionFamilyKind(str(row["family_kind"])),
            authority_aggregate_version=int(row["authority_aggregate_version"]),
            registered_event_id=EventId.parse(str(row["registered_event_id"])),
            created_at=UtcTimestamp.parse(str(row["created_at"])),
        )

    def _generation_view(
        self, conn: sqlite3.Connection, generation_id: str
    ) -> ProjectionGenerationView:
        row = self._generation_row(conn, generation_id)
        return ProjectionGenerationView(
            generation_id=ProjectionGenerationId.parse(str(row["generation_id"])),
            family_id=str(row["family_id"]),
            state=ProjectionGenerationState(str(row["state"])),
            lifecycle_version=int(row["lifecycle_version"]),
            authority_aggregate_version=int(row["authority_aggregate_version"]),
            validated_through_ledger_seq=(
                None
                if row["validated_through_ledger_seq"] is None
                else int(row["validated_through_ledger_seq"])
            ),
            created_at=UtcTimestamp.parse(str(row["created_at"])),
            updated_at=UtcTimestamp.parse(str(row["updated_at"])),
        )

    def _generation_version_for_event(
        self, conn: sqlite3.Connection, event_id: str
    ) -> ProjectionGenerationView:
        row = conn.execute(
            "SELECT v.*,g.family_id,g.created_at FROM projection_generation_versions v "
            "JOIN projection_generations g ON g.generation_id=v.generation_id "
            "WHERE v.authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "projection command replay lacks generation result"
            )
        return ProjectionGenerationView(
            generation_id=ProjectionGenerationId.parse(str(row["generation_id"])),
            family_id=str(row["family_id"]),
            state=ProjectionGenerationState(str(row["state"])),
            lifecycle_version=int(row["lifecycle_version"]),
            authority_aggregate_version=int(row["authority_aggregate_version"]),
            validated_through_ledger_seq=(
                None
                if row["validated_through_ledger_seq"] is None
                else int(row["validated_through_ledger_seq"])
            ),
            created_at=UtcTimestamp.parse(str(row["created_at"])),
            updated_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )

    @staticmethod
    def _validation_view_from_row(
        row: sqlite3.Row | None,
    ) -> ProjectionGenerationValidationView:
        if row is None:
            raise AuthorityPersistenceError(
                "projection validation evidence is absent"
            )
        return ProjectionGenerationValidationView(
            validation_digest=str(row["validation_digest"]),
            generation_id=ProjectionGenerationId.parse(
                str(row["generation_id"])
            ),
            validation_version=int(row["validation_version"]),
            lifecycle_version=int(row["lifecycle_version"]),
            checkpoint_ledger_seq=int(row["checkpoint_ledger_seq"]),
            definition_digest=str(row["definition_digest"]),
            ontology_contract_digest=str(row["ontology_contract_digest"]),
            mapping_contract_digest=str(row["mapping_contract_digest"]),
            projector_version=str(row["projector_version"]),
            service_compatibility_digest=str(
                row["service_compatibility_digest"]
            ),
            projection_state_digest=str(row["projection_state_digest"]),
            authority_aggregate_version=int(
                row["authority_aggregate_version"]
            ),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )

    def _validation_for_authority_event(
        self, conn: sqlite3.Connection, event_id: str
    ) -> ProjectionGenerationValidationView:
        return self._validation_view_from_row(
            conn.execute(
                "SELECT * FROM projection_generation_validations "
                "WHERE authority_event_id=?",
                (event_id,),
            ).fetchone()
        )

    def _promotion_view_from_row(
        self, conn: sqlite3.Connection, row: sqlite3.Row | None
    ) -> ProjectionGenerationPromotionView:
        if row is None:
            raise AuthorityPersistenceError(
                "projection promotion evidence is absent"
            )
        prior_id = row["prior_generation_id"]
        return ProjectionGenerationPromotionView(
            promotion_digest=str(row["promotion_digest"]),
            family_id=str(row["family_id"]),
            generation=self._generation_view(
                conn, str(row["generation_id"])
            ),
            prior_generation=(
                None
                if prior_id is None
                else self._generation_view(conn, str(prior_id))
            ),
            checkpoint_ledger_seq=int(row["checkpoint_ledger_seq"]),
            validation_digest=str(row["validation_digest"]),
            target_authority_event_id=EventId.parse(
                str(row["target_authority_event_id"])
            ),
            prior_authority_event_id=(
                None
                if row["prior_authority_event_id"] is None
                else EventId.parse(str(row["prior_authority_event_id"]))
            ),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )

    def _promotion_for_authority_event(
        self, conn: sqlite3.Connection, event_id: str
    ) -> ProjectionGenerationPromotionView:
        return self._promotion_view_from_row(
            conn,
            conn.execute(
                "SELECT * FROM projection_generation_promotions "
                "WHERE target_authority_event_id=?",
                (event_id,),
            ).fetchone(),
        )

    def _delivery_for_authority_event(
        self, conn: sqlite3.Connection, event_id: str
    ) -> DeliveryRecordView:
        row = conn.execute(
            "SELECT a.*,g.family_id FROM projection_delivery_attempts a "
            "JOIN projection_generations g ON g.generation_id=a.generation_id "
            "WHERE a.authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "projection command replay lacks delivery result"
            )
        outcome = ProjectionDeliveryOutcome(str(row["outcome"]))
        family = self._registered_family_definition(
            conn, str(row["family_id"])
        )
        finalized = outcome in _SUCCESS_OUTCOMES or (
            outcome is ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED
            or (
                outcome is ProjectionDeliveryOutcome.RETRYABLE_FAILURE
                and int(row["attempt_number"]) >= family.max_delivery_attempts
            )
        )
        return DeliveryRecordView(
            generation_id=ProjectionGenerationId.parse(str(row["generation_id"])),
            ledger_seq=int(row["ledger_seq"]),
            source_event_id=EventId.parse(str(row["source_event_id"])),
            source_event_digest=str(row["source_event_digest"]),
            source_event_type=str(row["source_event_type"]),
            outcome=outcome,
            required=bool(row["required"]),
            attempt_count=int(row["attempt_number"]),
            finalized=finalized,
            error_code=(None if row["error_code"] is None else str(row["error_code"])),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )

    def _gap_version_for_event(
        self, conn: sqlite3.Connection, event_id: str
    ) -> ProjectionGapView:
        row = conn.execute(
            "SELECT v.*,g.generation_id,g.ledger_seq_start,g.ledger_seq_end,"
            "g.opened_event_id FROM projection_gap_versions v "
            "JOIN projection_gaps g ON g.gap_id=v.gap_id "
            "WHERE v.authority_event_id=? ORDER BY v.lifecycle_version DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "projection command replay lacks gap result"
            )
        state = ProjectionGapState(str(row["state"]))
        return ProjectionGapView(
            gap_id=ProjectionGapId.parse(str(row["gap_id"])),
            generation_id=ProjectionGenerationId.parse(str(row["generation_id"])),
            ledger_seq_start=int(row["ledger_seq_start"]),
            ledger_seq_end=int(row["ledger_seq_end"]),
            state=state,
            lifecycle_version=int(row["lifecycle_version"]),
            required=bool(row["required"]),
            reason_code=str(row["reason_code"]),
            opened_event_id=EventId.parse(str(row["opened_event_id"])),
            resolved_event_id=(
                EventId.parse(str(row["authority_event_id"]))
                if state is ProjectionGapState.RESOLVED
                else None
            ),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )

    @staticmethod
    def _gap_view_from_row(row: sqlite3.Row) -> ProjectionGapView:
        return ProjectionGapView(
            gap_id=ProjectionGapId.parse(str(row["gap_id"])),
            generation_id=ProjectionGenerationId.parse(str(row["generation_id"])),
            ledger_seq_start=int(row["ledger_seq_start"]),
            ledger_seq_end=int(row["ledger_seq_end"]),
            state=ProjectionGapState(str(row["state"])),
            lifecycle_version=int(row["lifecycle_version"]),
            required=bool(row["required"]),
            reason_code=str(row["reason_code"]),
            opened_event_id=EventId.parse(str(row["opened_event_id"])),
            resolved_event_id=(
                None
                if row["resolved_event_id"] is None
                else EventId.parse(str(row["resolved_event_id"]))
            ),
            recorded_at=UtcTimestamp.parse(str(row["updated_at"])),
        )

    def projection_rebuild_delivery_state(
        self,
        generation_id: ProjectionGenerationId,
        ledger_seq: int,
    ) -> _ProjectionRebuildDeliveryState | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM projection_delivery_states "
                "WHERE generation_id=? AND ledger_seq=?",
                (str(generation_id), ledger_seq),
            ).fetchone()
            if row is None:
                return None
            self._require_delivery_source_integrity(self._connection, row)
            return _ProjectionRebuildDeliveryState(
                outcome=ProjectionDeliveryOutcome(str(row["current_outcome"])),
                finalized=bool(row["finalized"]),
                attempt_count=int(row["attempt_count"]),
                source_event_id=EventId.parse(str(row["source_event_id"])),
                source_event_digest=str(row["source_event_digest"]),
            )

    def projection_delivery_source(
        self,
        generation_id: ProjectionGenerationId,
        ledger_seq: int,
    ) -> _ProjectionDeliverySource:
        """Resolve exact retained projection input without exposing the store."""

        with self._lock:
            conn = self._connection
            generation = self._generation_view(conn, str(generation_id))
            family = self._registered_family_definition(
                conn, generation.family_id
            )
            mapping_contract = (
                self._projection_contracts.mappings.resolve_digest(
                    family.mapping_contract_digest
                )
            )
            event = self._source_event(conn, ledger_seq)
            source_event_digest = digest_canonical(asdict(event))
            row = conn.execute(
                "SELECT mode,payload_digest,payload_bytes,object_admission_id "
                "FROM authority_payloads WHERE payload_id=?",
                (event.payload_id,),
            ).fetchone()
            if row is None:
                raise AuthorityPersistenceError(
                    "projection source payload record is absent"
                )
            if (
                str(row["mode"]) != event.payload_mode
                or str(row["payload_digest"]) != event.payload_digest
            ):
                raise AuthorityPersistenceError(
                    "projection source payload metadata is inconsistent"
                )
            retained_admission_id = (
                None
                if row["object_admission_id"] is None
                else str(row["object_admission_id"])
            )
            if retained_admission_id != event.object_admission_id:
                raise AuthorityPersistenceError(
                    "projection source object admission identity is inconsistent"
                )
            payload: Mapping[str, object]
            payload_is_mapping = False
            if event.payload_mode == "INLINE":
                payload_bytes = bytes(row["payload_bytes"] or b"")
                if not payload_bytes or digest_bytes(payload_bytes) != event.payload_digest:
                    raise AuthorityPersistenceError(
                        "projection source inline payload digest mismatch"
                    )
                try:
                    decoded = json.loads(payload_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise AuthorityPersistenceError(
                        "projection source inline payload is not canonical JSON"
                    ) from exc
                if isinstance(decoded, dict):
                    payload = MappingProxyType(dict(decoded))
                    payload_is_mapping = True
                else:
                    payload = MappingProxyType({})
            else:
                payload = MappingProxyType({})

            tombstoned_admission_ids: tuple[str, ...] = ()
            if event.event_type == "governed_blob.deletion.tombstoned":
                expected_fields = {
                    "operation_id",
                    "deletion_id",
                    "blob_digest",
                    "reason_code",
                }
                if (
                    event.aggregate_type != "governed_object_lifecycle"
                    or not payload_is_mapping
                    or set(payload) != expected_fields
                    or any(not isinstance(payload[field], str) for field in expected_fields)
                    or str(payload["deletion_id"]) != event.aggregate_id
                ):
                    raise AuthorityPersistenceError(
                        "projection tombstone source shape is inconsistent"
                    )
                blob_digest = str(payload["blob_digest"])
                try:
                    if validate_sha256_digest(
                        blob_digest, field="blob_digest"
                    ) != blob_digest:
                        raise ValueError("non-canonical digest")
                except ValueError as exc:
                    raise AuthorityPersistenceError(
                        "projection tombstone blob digest is invalid"
                    ) from exc
                deletion = conn.execute(
                    "SELECT d.blob_digest,d.reason_code,v.lifecycle_version,"
                    "v.state,v.operation_id,v.event_id "
                    "FROM object_deletions d JOIN object_deletion_versions v "
                    "ON v.deletion_id=d.deletion_id "
                    "WHERE d.deletion_id=? AND v.event_id=?",
                    (event.aggregate_id, event.event_id),
                ).fetchone()
                if (
                    deletion is None
                    or str(deletion["blob_digest"]) != blob_digest
                    or str(deletion["reason_code"]) != str(payload["reason_code"])
                    or str(deletion["operation_id"]) != str(payload["operation_id"])
                    or str(deletion["state"]) != "TOMBSTONED"
                    or int(deletion["lifecycle_version"]) != event.aggregate_version
                    or str(deletion["event_id"]) != event.event_id
                ):
                    raise AuthorityPersistenceError(
                        "projection tombstone authority record is inconsistent"
                    )
                admissions = conn.execute(
                    "SELECT admission_id FROM object_admissions WHERE blob_digest=? "
                    "ORDER BY admission_id",
                    (blob_digest,),
                ).fetchall()
                tombstoned_admission_ids = tuple(
                    str(item["admission_id"]) for item in admissions
                )
                if not tombstoned_admission_ids:
                    raise AuthorityPersistenceError(
                        "projection tombstone lacks covered object admissions"
                    )

            return _ProjectionDeliverySource(
                generation=generation,
                family=family,
                mapping_contract=mapping_contract,
                mapping=mapping_contract.resolve(event.event_type),
                event=event,
                source_event_digest=source_event_digest,
                payload=payload,
                payload_is_mapping=payload_is_mapping,
                tombstoned_object_admission_ids=tombstoned_admission_ids,
            )

    def projection_active_generation_metadata(
        self, family_id: str
    ) -> _ProjectionGenerationMetadata:
        with self._lock:
            self._registered_family_definition(self._connection, family_id)
            rows = self._connection.execute(
                "SELECT generation_id FROM projection_generations "
                "WHERE family_id=? AND state='ACTIVE' "
                "ORDER BY generation_id LIMIT 2",
                (family_id,),
            ).fetchall()
            if not rows:
                raise ProjectionStateError(
                    "projection family has no authority-selected active generation"
                )
            if len(rows) != 1:
                raise AuthorityPersistenceError(
                    "projection family has multiple active generations"
                )
            return self.projection_generation_metadata(
                ProjectionGenerationId.parse(str(rows[0]["generation_id"]))
            )

    def projection_generation_metadata(
        self, generation_id: ProjectionGenerationId
    ) -> _ProjectionGenerationMetadata:
        with self._lock:
            conn = self._connection
            generation = self._generation_view(conn, str(generation_id))
            family = self._registered_family_definition(
                conn, generation.family_id
            )
            contiguous = self._checkpoint_seq(conn, str(generation_id))
            open_gap_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM projection_gaps "
                    "WHERE generation_id=? AND state='OPEN'",
                    (str(generation_id),),
                ).fetchone()[0]
            )
            dead_letter_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM projection_dead_letters "
                    "WHERE generation_id=?",
                    (str(generation_id),),
                ).fetchone()[0]
            )
            return _ProjectionGenerationMetadata(
                generation=generation,
                family=family,
                contiguous_ledger_seq=contiguous,
                open_gap_count=open_gap_count,
                dead_letter_count=dead_letter_count,
                serving_time=self._clock(),
            )

    def projection_family_definition(
        self, family_id: str
    ) -> ProjectionFamilyDefinition:
        with self._lock:
            return self._registered_family_definition(
                self._connection, family_id
            )

    def projection_status(self, family_id: str) -> ProjectionStatusMetadata:
        with self._lock:
            definition = self._registered_family_definition(
                self._connection, family_id
            )
            family = self._connection.execute(
                "SELECT * FROM projection_families WHERE family_id=?",
                (family_id,),
            ).fetchone()
            if family is None:
                raise ProjectionStateError("projection family is not registered")
            generation = self._connection.execute(
                "SELECT * FROM projection_generations WHERE family_id=? "
                "ORDER BY CASE state WHEN 'ACTIVE' THEN 0 ELSE 1 END,"
                "updated_at DESC LIMIT 1",
                (family_id,),
            ).fetchone()
            if generation is None:
                generation_id = None
                generation_state = None
                checkpoint = 0
                gaps = 0
                dead_letters = 0
            else:
                generation_id = ProjectionGenerationId.parse(
                    str(generation["generation_id"])
                )
                generation_state = ProjectionGenerationState(str(generation["state"]))
                checkpoint = self._checkpoint_seq(
                    self._connection, str(generation_id)
                )
                gaps = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM projection_gaps "
                        "WHERE generation_id=? AND state='OPEN'",
                        (str(generation_id),),
                    ).fetchone()[0]
                )
                dead_letters = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM projection_dead_letters "
                        "WHERE generation_id=?",
                        (str(generation_id),),
                    ).fetchone()[0]
                )
            return ProjectionStatusMetadata(
                family_id=family_id,
                family_kind=definition.family_kind,
                projector_version=definition.projector_version,
                ontology_contract_digest=definition.ontology_contract_digest,
                mapping_contract_digest=definition.mapping_contract_digest,
                generation_id=generation_id,
                generation_state=generation_state,
                contiguous_ledger_seq=checkpoint,
                open_gap_count=gaps,
                dead_letter_count=dead_letters,
                trust_scope=TrustScope.ADMITTED,
                serving_time=self._clock(),
            )

    def projection_generation(
        self, generation_id: ProjectionGenerationId
    ) -> ProjectionGenerationView:
        with self._lock:
            return self._generation_view(self._connection, str(generation_id))

    def projection_generations(
        self, family_id: str, limit: int
    ) -> tuple[ProjectionGenerationView, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT generation_id FROM projection_generations "
                "WHERE family_id=? ORDER BY created_at DESC LIMIT ?",
                (family_id, limit),
            ).fetchall()
            return tuple(
                self._generation_view(self._connection, str(row["generation_id"]))
                for row in rows
            )

    def projection_generation_validation(
        self, generation_id: ProjectionGenerationId
    ) -> ProjectionGenerationValidationView:
        with self._lock:
            return self._validation_view_from_row(
                self._connection.execute(
                    "SELECT * FROM projection_generation_validations "
                    "WHERE generation_id=? ORDER BY validation_version DESC LIMIT 1",
                    (str(generation_id),),
                ).fetchone()
            )

    def projection_promotions(
        self, family_id: str, limit: int
    ) -> tuple[ProjectionGenerationPromotionView, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM projection_generation_promotions "
                "WHERE family_id=? ORDER BY recorded_at DESC LIMIT ?",
                (family_id, limit),
            ).fetchall()
            return tuple(
                self._promotion_view_from_row(self._connection, row)
                for row in rows
            )

    def projection_gaps(
        self, generation_id: ProjectionGenerationId, limit: int
    ) -> tuple[ProjectionGapView, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM projection_gaps WHERE generation_id=? "
                "ORDER BY ledger_seq_start LIMIT ?",
                (str(generation_id), limit),
            ).fetchall()
            return tuple(self._gap_view_from_row(row) for row in rows)

    def projection_dead_letters(
        self, generation_id: ProjectionGenerationId, limit: int
    ) -> tuple[ProjectionDeadLetterView, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM projection_dead_letters WHERE generation_id=? "
                "ORDER BY ledger_seq LIMIT ?",
                (str(generation_id), limit),
            ).fetchall()
            return tuple(
                ProjectionDeadLetterView(
                    dead_letter_id=ProjectionDeadLetterId.parse(
                        str(row["dead_letter_id"])
                    ),
                    generation_id=ProjectionGenerationId.parse(
                        str(row["generation_id"])
                    ),
                    ledger_seq=int(row["ledger_seq"]),
                    source_event_id=EventId.parse(str(row["source_event_id"])),
                    attempts=int(row["attempts"]),
                    reason_code=str(row["reason_code"]),
                    authority_event_id=EventId.parse(
                        str(row["authority_event_id"])
                    ),
                    recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
                )
                for row in rows
            )


__all__ = ["_ProjectionAuthorityStore"]
