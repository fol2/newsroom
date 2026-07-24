from __future__ import annotations

import json
import sqlite3
from typing import Any

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority._projection_store import _ProjectionAuthorityStore
from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import (
    AggregateId,
    EventId,
    ObjectAdmissionId,
    TrustScope,
    UtcTimestamp,
)
from newsroom.integrated.models import (
    CandidateAdmissionDecisionId,
    CandidateAdmissionOutcome,
    CandidateAdmissionRequest,
    CandidateAdmissionView,
    CandidateRoute,
    IntegratedContractError,
    IntegratedExactIndexEntry,
    IntegratedFixtureId,
    IntegratedFixtureManifest,
    IntegratedRetrievalContext,
    IntegratedRetrievalContextId,
    IntegratedStateError,
    IntegratedTriageProposalId,
    StoryCandidateId,
    StoryCandidateVersionId,
)
from newsroom.projection.models import (
    ProjectionGenerationId,
    ProjectionGenerationState,
)
from newsroom.projection.neo4j.models import (
    StructuralGraphNodeView,
    StructuralGraphRelationView,
    StructuralReadAuthoritySelection,
    StructuralReadMetadata,
)
from newsroom.projection.ontology import (
    ProjectionNodeType,
    ProjectionRelationType,
)

from newsroom.integrated.policy import CANDIDATE_ADMISSION_COMMAND


_CONTEXT_CONTRACT = "newsroom-integrated-retrieval-context-v1"
_CANDIDATE_VERSION_CONTRACT = "newsroom-story-candidate-version-v1"
_DECISION_CONTRACT = "newsroom-candidate-admission-decision-v1"
_COLLISION_CONTRACT = "newsroom-candidate-semantic-collision-v1"


class _IntegratedCandidateStore(_ProjectionAuthorityStore):
    """SQLite-authoritative retrieval evidence and Candidate admission state."""

    def _migrate_or_validate(self) -> None:
        super()._migrate_or_validate()
        self._validate_integrated_integrity()

    @staticmethod
    def _decode_integrated_canonical(data: bytes, *, identity: str) -> dict[str, Any]:
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(
                f"{identity} canonical JSON is invalid"
            ) from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != data:
            raise AuthorityPersistenceError(
                f"{identity} is not an exact canonical object"
            )
        return value

    @classmethod
    def _canonical_row_value(
        cls,
        row: sqlite3.Row,
        *,
        identity: str,
    ) -> dict[str, Any]:
        canonical = bytes(row["canonical_bytes"])
        digest = str(row["canonical_digest"])
        if digest_bytes(canonical) != digest:
            raise AuthorityPersistenceError(
                f"{identity} canonical digest is inconsistent"
            )
        return cls._decode_integrated_canonical(canonical, identity=identity)

    @classmethod
    def _context_from_row(
        cls,
        row: sqlite3.Row,
    ) -> IntegratedRetrievalContext:
        value = cls._canonical_row_value(
            row, identity="integrated retrieval context"
        )
        try:
            metadata_value = value["metadata"]
            nodes_value = value["nodes"]
            relations_value = value["relations"]
            index_value = value["exact_index"]
            omissions_value = value["known_omissions"]
            if (
                not isinstance(metadata_value, dict)
                or not isinstance(nodes_value, list)
                or not isinstance(relations_value, list)
                or not isinstance(index_value, list)
                or not isinstance(omissions_value, list)
            ):
                raise TypeError("retrieval context collections are malformed")
            context = IntegratedRetrievalContext(
                context_id=IntegratedRetrievalContextId.parse(
                    str(row["context_id"])
                ),
                fixture_id=IntegratedFixtureId.parse(
                    str(value["fixture_id"])
                ),
                fixture_aggregate_id=AggregateId.parse(
                    str(value["fixture_aggregate_id"])
                ),
                fixture_event_id=EventId.parse(
                    str(value["fixture_event_id"])
                ),
                admission_id=ObjectAdmissionId.parse(
                    str(value["admission_id"])
                ),
                metadata=StructuralReadMetadata(
                    family_id=str(metadata_value["family_id"]),
                    family_definition_version=str(
                        metadata_value["family_definition_version"]
                    ),
                    projector_version=str(
                        metadata_value["projector_version"]
                    ),
                    ontology_contract_digest=str(
                        metadata_value["ontology_contract_digest"]
                    ),
                    mapping_contract_digest=str(
                        metadata_value["mapping_contract_digest"]
                    ),
                    generation_id=ProjectionGenerationId.parse(
                        str(metadata_value["generation_id"])
                    ),
                    generation_state=ProjectionGenerationState(
                        str(metadata_value["generation_state"])
                    ),
                    authority_selection=StructuralReadAuthoritySelection(
                        str(metadata_value["authority_selection"])
                    ),
                    contiguous_ledger_seq=int(
                        metadata_value["contiguous_ledger_seq"]
                    ),
                    open_gap_count=int(metadata_value["open_gap_count"]),
                    dead_letter_count=int(
                        metadata_value["dead_letter_count"]
                    ),
                    trust_scope=TrustScope(
                        str(metadata_value["trust_scope"])
                    ),
                    query_valid_time=UtcTimestamp.parse(
                        str(metadata_value["query_valid_time"])
                    ),
                    serving_time=UtcTimestamp.parse(
                        str(metadata_value["serving_time"])
                    ),
                    authoritative_system=str(
                        metadata_value["authoritative_system"]
                    ),
                    graph_role=str(metadata_value["graph_role"]),
                ),
                nodes=tuple(
                    StructuralGraphNodeView(
                        canonical_id=str(item["canonical_id"]),
                        node_type=ProjectionNodeType(
                            str(item["node_type"])
                        ),
                        identity_source=str(item["identity_source"]),
                        identity_reference_digest=str(
                            item["identity_reference_digest"]
                        ),
                        first_ledger_seq=int(item["first_ledger_seq"]),
                        first_source_event_id=str(
                            item["first_source_event_id"]
                        ),
                        first_source_event_digest=str(
                            item["first_source_event_digest"]
                        ),
                    )
                    for item in nodes_value
                ),
                relations=tuple(
                    StructuralGraphRelationView(
                        relation_key=str(item["relation_key"]),
                        relation_type=ProjectionRelationType(
                            str(item["relation_type"])
                        ),
                        source_canonical_id=str(
                            item["source_canonical_id"]
                        ),
                        target_canonical_id=str(
                            item["target_canonical_id"]
                        ),
                        ledger_seq=int(item["ledger_seq"]),
                        source_event_id=str(item["source_event_id"]),
                        source_event_type=str(item["source_event_type"]),
                        source_event_digest=str(
                            item["source_event_digest"]
                        ),
                        aggregate_type=str(item["aggregate_type"]),
                        aggregate_id=str(item["aggregate_id"]),
                        aggregate_version=int(item["aggregate_version"]),
                        payload_id=str(item["payload_id"]),
                        payload_digest=str(item["payload_digest"]),
                        object_admission_id=(
                            None
                            if item["object_admission_id"] is None
                            else str(item["object_admission_id"])
                        ),
                        principal_id=str(item["principal_id"]),
                        trust_scope=TrustScope(str(item["trust_scope"])),
                        security_scope=str(item["security_scope"]),
                        retention_scope=str(item["retention_scope"]),
                        recorded_at=UtcTimestamp.parse(
                            str(item["recorded_at"])
                        ),
                    )
                    for item in relations_value
                ),
                exact_index=tuple(
                    IntegratedExactIndexEntry(
                        canonical_id=str(item["canonical_id"]),
                        node_type=ProjectionNodeType(
                            str(item["node_type"])
                        ),
                        first_ledger_seq=int(item["first_ledger_seq"]),
                        first_source_event_id=str(
                            item["first_source_event_id"]
                        ),
                        first_source_event_digest=str(
                            item["first_source_event_digest"]
                        ),
                    )
                    for item in index_value
                ),
                hydrated_blob_digest=str(value["hydrated_blob_digest"]),
                hydration_policy_contract_digest=str(
                    value["hydration_policy_contract_digest"]
                ),
                hydration_access_decision_id=ObjectAccessDecisionId.parse(
                    str(row["hydration_access_decision_id"])
                ),
                manifest_digest=str(value["manifest_digest"]),
                retrieval_version=str(value["retrieval_version"]),
                query_digest=str(value["query_digest"]),
                known_omissions=tuple(str(item) for item in omissions_value),
                recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
            )
        except (KeyError, TypeError, ValueError, IntegratedStateError) as exc:
            raise AuthorityPersistenceError(
                "integrated retrieval context cannot be rehydrated"
            ) from exc
        if context.context_digest != str(row["context_digest"]):
            raise AuthorityPersistenceError(
                "rehydrated retrieval context digest is inconsistent"
            )
        return context

    def retrieval_context(
        self,
        context_id: IntegratedRetrievalContextId,
    ) -> IntegratedRetrievalContext:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("retrieval context identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM integrated_retrieval_contexts WHERE context_id=?",
                (str(context_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(context_id))
            self._validate_context_row(self._connection, row)
            return self._context_from_row(row)

    @staticmethod
    def semantic_collision_digest(
        request: CandidateAdmissionRequest,
        manifest: IntegratedFixtureManifest,
        context: IntegratedRetrievalContext,
    ) -> str:
        if request.fixture_id != manifest.fixture_id:
            raise IntegratedContractError(
                "candidate request and manifest fixture identities differ"
            )
        if context.fixture_id != manifest.fixture_id:
            raise IntegratedContractError(
                "retrieval context and manifest fixture identities differ"
            )
        return digest_canonical(
            {
                "contract": _COLLISION_CONTRACT,
                "fixture_id": str(manifest.fixture_id),
                "fixture_event_id": str(context.fixture_event_id),
                "signal_id": str(manifest.signal_id),
                "lead_id": str(manifest.lead_id),
                "hypothesis_version_id": str(
                    manifest.hypothesis_version_id
                ),
                "route": request.route.value,
                "manifest_digest": manifest.manifest_digest,
            }
        )

    def _validate_integrated_integrity(self) -> None:
        with self._lock:
            conn = self._connection
            for row in conn.execute(
                "SELECT * FROM integrated_retrieval_contexts"
            ).fetchall():
                self._validate_context_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM story_candidate_versions"
            ).fetchall():
                self._validate_candidate_version_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM candidate_admission_decisions"
            ).fetchall():
                self._validate_decision_row(conn, row)

    def _validate_context_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="integrated retrieval context"
        )
        canonical_digest = str(row["canonical_digest"])
        if str(row["context_digest"]) != canonical_digest:
            raise AuthorityPersistenceError(
                "integrated retrieval context digest differs from canonical bytes"
            )
        if value.get("contract") != _CONTEXT_CONTRACT:
            raise AuthorityPersistenceError(
                "integrated retrieval context contract identity is inconsistent"
            )
        metadata = value.get("metadata")
        if not isinstance(metadata, dict):
            raise AuthorityPersistenceError(
                "integrated retrieval context metadata is malformed"
            )
        expected = {
            "fixture_id": str(row["fixture_id"]),
            "fixture_aggregate_id": str(row["fixture_aggregate_id"]),
            "fixture_event_id": str(row["fixture_event_id"]),
            "admission_id": str(row["admission_id"]),
            "manifest_digest": str(row["manifest_digest"]),
            "retrieval_version": str(row["retrieval_version"]),
        }
        if any(value.get(key) != item for key, item in expected.items()):
            raise AuthorityPersistenceError(
                "integrated retrieval context columns differ from canonical evidence"
            )
        if (
            metadata.get("generation_id") != str(row["generation_id"])
            or metadata.get("contiguous_ledger_seq")
            != int(row["projected_through_ledger_seq"])
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context projection identity is inconsistent"
            )
        validate_sha256_digest(
            str(row["context_digest"]), field="integrated_context_digest"
        )
        validate_sha256_digest(
            str(row["manifest_digest"]), field="integrated_manifest_digest"
        )

        event = conn.execute(
            "SELECT aggregate_type,aggregate_id,object_admission_id,payload_digest "
            "FROM ledger_events WHERE event_id=?",
            (str(row["fixture_event_id"]),),
        ).fetchone()
        if (
            event is None
            or str(event["aggregate_type"]) != "integrated_fixture"
            or str(event["aggregate_id"]) != str(row["fixture_aggregate_id"])
            or str(event["object_admission_id"]) != str(row["admission_id"])
            or str(event["payload_digest"]) != str(row["manifest_digest"])
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks exact fixture authority"
            )

        access = conn.execute(
            "SELECT * FROM object_access_decisions WHERE access_decision_id=?",
            (str(row["hydration_access_decision_id"]),),
        ).fetchone()
        if access is None:
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks hydration authority"
            )
        access_value = self._canonical_row_value(
            access, identity="integrated hydration decision"
        )
        if (
            str(access["admission_id"]) != str(row["admission_id"])
            or access_value.get("admission_id") != str(row["admission_id"])
        ):
            raise AuthorityPersistenceError(
                "integrated hydration decision belongs to another admission"
            )

        nodes = value.get("nodes")
        exact_index = value.get("exact_index")
        if not isinstance(nodes, list) or not isinstance(exact_index, list):
            raise AuthorityPersistenceError(
                "integrated retrieval graph/index evidence is malformed"
            )
        expected_index = {
            str(item["canonical_id"]): item for item in exact_index
        }
        rows = conn.execute(
            "SELECT * FROM integrated_exact_index_entries WHERE context_id=? "
            "ORDER BY canonical_id",
            (str(row["context_id"]),),
        ).fetchall()
        if len(rows) != len(expected_index):
            raise AuthorityPersistenceError(
                "integrated exact index does not cover canonical context"
            )
        for index_row in rows:
            index_value = self._canonical_row_value(
                index_row, identity="integrated exact index entry"
            )
            canonical_id = str(index_row["canonical_id"])
            if index_value != expected_index.get(canonical_id):
                raise AuthorityPersistenceError(
                    "integrated exact index differs from context evidence"
                )

    def _validate_candidate_version_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="story candidate version"
        )
        manifest = value.get("manifest")
        if not isinstance(manifest, dict):
            raise AuthorityPersistenceError(
                "story candidate version lacks a canonical fixture manifest"
            )
        if (
            value.get("contract") != _CANDIDATE_VERSION_CONTRACT
            or value.get("candidate_id") != str(row["candidate_id"])
            or value.get("candidate_version_id")
            != str(row["candidate_version_id"])
            or value.get("version_number") != int(row["version_number"])
            or value.get("fixture_id") != str(row["fixture_id"])
            or value.get("signal_id") != str(row["signal_id"])
            or value.get("lead_id") != str(row["lead_id"])
            or value.get("hypothesis_version_id")
            != str(row["hypothesis_version_id"])
            or value.get("route") != str(row["route"])
            or value.get("hypothesis_trust_scope")
            != str(row["hypothesis_trust_scope"])
            or value.get("retrieval_context_id")
            != str(row["retrieval_context_id"])
            or value.get("manifest_digest") != str(row["manifest_digest"])
        ):
            raise AuthorityPersistenceError(
                "story candidate version columns differ from canonical evidence"
            )

        context = conn.execute(
            "SELECT fixture_id,fixture_event_id,admission_id,context_digest,"
            "manifest_digest FROM integrated_retrieval_contexts "
            "WHERE context_id=?",
            (str(row["retrieval_context_id"]),),
        ).fetchone()
        if (
            context is None
            or str(context["fixture_id"]) != str(row["fixture_id"])
            or str(context["manifest_digest"])
            != str(row["manifest_digest"])
            or value.get("fixture_event_id")
            != str(context["fixture_event_id"])
            or value.get("admission_id") != str(context["admission_id"])
            or value.get("retrieval_context_digest")
            != str(context["context_digest"])
        ):
            raise AuthorityPersistenceError(
                "story candidate version differs from retained retrieval context"
            )

        manifest_digest = digest_canonical(manifest)
        if (
            manifest.get("contract")
            != "newsroom-integrated-fixture-manifest-v1"
            or manifest_digest != str(row["manifest_digest"])
            or manifest.get("fixture_id") != str(row["fixture_id"])
            or manifest.get("signal_id") != str(row["signal_id"])
            or manifest.get("lead_id") != str(row["lead_id"])
            or manifest.get("hypothesis_version_id")
            != str(row["hypothesis_version_id"])
            or manifest.get("hypothesis_trust_scope") != "PROPOSED"
            or value.get("hypothesis_trust_scope") != "PROPOSED"
        ):
            raise AuthorityPersistenceError(
                "story candidate version manifest identity is inconsistent"
            )

        candidate = conn.execute(
            "SELECT semantic_collision_digest FROM story_candidates "
            "WHERE candidate_id=?",
            (str(row["candidate_id"]),),
        ).fetchone()
        if candidate is None:
            raise AuthorityPersistenceError(
                "story candidate version lacks stable candidate identity"
            )
        expected_collision = digest_canonical(
            {
                "contract": _COLLISION_CONTRACT,
                "fixture_id": str(row["fixture_id"]),
                "fixture_event_id": str(context["fixture_event_id"]),
                "signal_id": str(row["signal_id"]),
                "lead_id": str(row["lead_id"]),
                "hypothesis_version_id": str(row["hypothesis_version_id"]),
                "route": str(row["route"]),
                "manifest_digest": str(row["manifest_digest"]),
            }
        )
        collision = str(candidate["semantic_collision_digest"])
        validate_sha256_digest(
            collision,
            field="candidate_semantic_collision_digest",
        )
        if collision != expected_collision:
            raise AuthorityPersistenceError(
                "story candidate semantic collision differs from immutable version"
            )

    def _validate_decision_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="candidate admission decision"
        )
        expected = {
            "decision_id": str(row["decision_id"]),
            "proposal_id": str(row["proposal_id"]),
            "outcome": str(row["outcome"]),
            "candidate_id": str(row["candidate_id"]),
            "candidate_version_id": str(row["candidate_version_id"]),
            "route": str(row["route"]),
            "fixture_id": str(row["fixture_id"]),
            "retrieval_context_id": str(row["retrieval_context_id"]),
            "retrieval_context_digest": str(
                row["retrieval_context_digest"]
            ),
            "manifest_digest": str(row["manifest_digest"]),
            "semantic_collision_digest": str(
                row["semantic_collision_digest"]
            ),
            "authority_event_id": str(row["authority_event_id"]),
            "authority_aggregate_version": int(
                row["authority_aggregate_version"]
            ),
        }
        if value.get("contract") != _DECISION_CONTRACT or any(
            value.get(key) != item for key, item in expected.items()
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision columns differ from canonical evidence"
            )

        candidate = conn.execute(
            "SELECT semantic_collision_digest FROM story_candidates "
            "WHERE candidate_id=?",
            (str(row["candidate_id"]),),
        ).fetchone()
        version = conn.execute(
            "SELECT candidate_id,fixture_id,route,retrieval_context_id,"
            "manifest_digest FROM story_candidate_versions "
            "WHERE candidate_version_id=?",
            (str(row["candidate_version_id"]),),
        ).fetchone()
        context = conn.execute(
            "SELECT context_digest FROM integrated_retrieval_contexts "
            "WHERE context_id=?",
            (str(row["retrieval_context_id"]),),
        ).fetchone()
        if (
            candidate is None
            or version is None
            or context is None
            or str(candidate["semantic_collision_digest"])
            != str(row["semantic_collision_digest"])
            or str(version["candidate_id"]) != str(row["candidate_id"])
            or str(version["fixture_id"]) != str(row["fixture_id"])
            or str(version["route"]) != str(row["route"])
            or str(version["retrieval_context_id"])
            != str(row["retrieval_context_id"])
            or str(version["manifest_digest"])
            != str(row["manifest_digest"])
            or str(context["context_digest"])
            != str(row["retrieval_context_digest"])
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision cross-record identity is inconsistent"
            )

        event = conn.execute(
            "SELECT event_type,aggregate_type,aggregate_id,aggregate_version,"
            "payload_digest,object_admission_id,trust_scope,security_scope,"
            "retention_scope FROM ledger_events WHERE event_id=?",
            (str(row["authority_event_id"]),),
        ).fetchone()
        event_payload_digest = digest_canonical(
            {
                "proposal_id": str(row["proposal_id"]),
                "route": str(row["route"]),
                "fixture_id": str(row["fixture_id"]),
                "retrieval_context_digest": str(
                    row["retrieval_context_digest"]
                ),
                "manifest_digest": str(row["manifest_digest"]),
                "semantic_collision_digest": str(
                    row["semantic_collision_digest"]
                ),
            }
        )
        if (
            event is None
            or str(event["event_type"]) != "candidate.admission.decided"
            or str(event["aggregate_type"])
            != str(row["proposal_aggregate_type"])
            or str(event["aggregate_id"]) != str(row["proposal_id"])
            or int(event["aggregate_version"])
            != int(row["authority_aggregate_version"])
            or str(event["payload_digest"]) != event_payload_digest
            or event["object_admission_id"] is not None
            or str(event["trust_scope"]) != "ADMITTED"
            or str(event["security_scope"]) != "authority.integrated"
            or str(event["retention_scope"]) != "authority.audit"
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision lacks exact authority event"
            )

    def _require_current_context(
        self,
        conn: sqlite3.Connection,
        *,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        checked_at: UtcTimestamp,
    ) -> None:
        if request.expected_context_digest != context.context_digest:
            raise IntegratedStateError(
                "candidate admission requires the exact retrieval context digest"
            )
        if manifest.manifest_digest != context.manifest_digest:
            raise IntegratedStateError(
                "retrieval context belongs to another fixture manifest"
            )
        if context.hydrated_blob_digest != manifest.manifest_digest:
            raise IntegratedStateError(
                "hydrated fixture bytes differ from the canonical manifest"
            )
        if context.metadata.query_valid_time.value > context.metadata.serving_time.value:
            raise IntegratedStateError(
                "retrieval query-valid time exceeds authoritative serving time"
            )
        if checked_at.value < context.recorded_at.value:
            raise IntegratedStateError(
                "candidate admission cannot predate retrieval context"
            )

        node_by_id = {item.canonical_id: item for item in context.nodes}
        for entry in context.exact_index:
            node = node_by_id.get(entry.canonical_id)
            if (
                node is None
                or entry.node_type is not node.node_type
                or entry.first_ledger_seq != node.first_ledger_seq
                or entry.first_source_event_id != node.first_source_event_id
                or entry.first_source_event_digest
                != node.first_source_event_digest
            ):
                raise IntegratedStateError(
                    "exact index differs from current structural read"
                )
        if any(
            item.first_ledger_seq > context.metadata.contiguous_ledger_seq
            for item in context.nodes
        ) or any(
            item.ledger_seq > context.metadata.contiguous_ledger_seq
            for item in context.relations
        ):
            raise IntegratedStateError(
                "retrieval context exceeds the authoritative projection watermark"
            )
        fixture_relations = tuple(
            item
            for item in context.relations
            if item.source_event_id == str(context.fixture_event_id)
            and item.aggregate_type == "integrated_fixture"
            and item.aggregate_id == str(context.fixture_aggregate_id)
            and item.object_admission_id == str(context.admission_id)
        )
        if not fixture_relations or any(
            item.payload_digest != context.hydrated_blob_digest
            for item in fixture_relations
        ):
            raise IntegratedStateError(
                "graph context differs from hydrated fixture authority"
            )

        event = conn.execute(
            "SELECT ledger_seq,event_type,aggregate_type,aggregate_id,"
            "aggregate_version,payload_digest,object_admission_id,trust_scope "
            "FROM ledger_events WHERE event_id=?",
            (str(context.fixture_event_id),),
        ).fetchone()
        if (
            event is None
            or str(event["event_type"]) != "authority.aggregate.versioned"
            or str(event["aggregate_type"]) != "integrated_fixture"
            or str(event["aggregate_id"]) != str(context.fixture_aggregate_id)
            or str(event["payload_digest"]) != manifest.manifest_digest
            or str(event["object_admission_id"]) != str(context.admission_id)
            or str(event["trust_scope"]) != "OBSERVED"
            or int(event["ledger_seq"])
            > context.metadata.contiguous_ledger_seq
        ):
            raise IntegratedStateError(
                "retrieval context does not resolve exact fixture authority"
            )

        admission = conn.execute(
            "SELECT a.blob_digest,a.valid_from,a.valid_until,"
            "v.state AS admission_state,bv.state AS blob_state,"
            "bv.integrity_state,r.allowed AS rights_allowed,"
            "r.valid_from AS rights_valid_from,r.valid_until AS rights_valid_until "
            "FROM object_admissions a "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "
            "JOIN object_admission_versions v "
            "ON v.admission_id=h.admission_id "
            "AND v.lifecycle_version=h.current_version "
            "JOIN blob_lifecycle_heads bh ON bh.blob_digest=a.blob_digest "
            "JOIN blob_lifecycle_versions bv "
            "ON bv.blob_digest=bh.blob_digest "
            "AND bv.lifecycle_version=bh.current_version "
            "JOIN object_rights_decisions r "
            "ON r.rights_decision_id=a.rights_decision_id "
            "WHERE a.admission_id=?",
            (str(context.admission_id),),
        ).fetchone()
        if (
            admission is None
            or str(admission["blob_digest"]) != manifest.manifest_digest
            or str(admission["admission_state"]) != "ACTIVE"
            or str(admission["blob_state"]) != "ACTIVE"
            or str(admission["integrity_state"]) != "VERIFIED"
            or not bool(admission["rights_allowed"])
        ):
            raise IntegratedStateError(
                "governed fixture is not currently hydratable authority"
            )
        for start_field, end_field in (
            ("valid_from", "valid_until"),
            ("rights_valid_from", "rights_valid_until"),
        ):
            start = UtcTimestamp.parse(str(admission[start_field]))
            end = (
                None
                if admission[end_field] is None
                else UtcTimestamp.parse(str(admission[end_field]))
            )
            if checked_at.value < start.value or (
                end is not None and checked_at.value >= end.value
            ):
                raise IntegratedStateError(
                    "governed fixture authority is not current"
                )

        access = conn.execute(
            "SELECT * FROM object_access_decisions WHERE access_decision_id=?",
            (str(context.hydration_access_decision_id),),
        ).fetchone()
        if access is None:
            raise IntegratedStateError(
                "retrieval context lacks a retained hydration decision"
            )
        access_value = self._canonical_row_value(
            access, identity="candidate hydration decision"
        )
        access_cutoff = access_value.get("state_cutoff")
        if not isinstance(access_cutoff, dict):
            raise IntegratedStateError(
                "hydration decision lacks an exact authority state cutoff"
            )
        if (
            str(access["admission_id"]) != str(context.admission_id)
            or str(access["hydration_policy_contract_digest"])
            != context.hydration_policy_contract_digest
            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) <= 0
            or access_value.get("admission_id") != str(context.admission_id)
            or access_value.get("policy_contract_digest")
            != context.hydration_policy_contract_digest
            or access_cutoff.get("admission_id")
            != str(context.admission_id)
            or access_cutoff.get("blob_digest") != manifest.manifest_digest
            or access_cutoff.get("admission_state") != "ACTIVE"
            or access_cutoff.get("blob_state") != "ACTIVE"
            or access_cutoff.get("blob_integrity_state") != "VERIFIED"
            or access_cutoff.get("deletion_state") is not None
            or access_cutoff.get("offset") != 0
            or access_cutoff.get("length") != int(access["allowed_bytes"])
        ):
            raise IntegratedStateError(
                "hydration decision differs from retrieval context"
            )

        generation = conn.execute(
            "SELECT g.state,g.validated_through_ledger_seq,g.family_id,"
            "d.definition_version,d.projector_version,"
            "d.ontology_contract_digest,d.mapping_contract_digest "
            "FROM projection_generations g "
            "JOIN projection_families f ON f.family_id=g.family_id "
            "JOIN projection_family_definitions d "
            "ON d.definition_digest=f.definition_digest "
            "WHERE g.generation_id=?",
            (str(context.metadata.generation_id),),
        ).fetchone()
        if (
            generation is None
            or str(generation["state"])
            != ProjectionGenerationState.ACTIVE.value
            or str(generation["family_id"]) != context.metadata.family_id
            or str(generation["definition_version"])
            != context.metadata.family_definition_version
            or str(generation["projector_version"])
            != context.metadata.projector_version
            or str(generation["ontology_contract_digest"])
            != context.metadata.ontology_contract_digest
            or str(generation["mapping_contract_digest"])
            != context.metadata.mapping_contract_digest
        ):
            raise IntegratedStateError(
                "retrieval context generation is no longer authority-selected ACTIVE"
            )
        active_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM projection_generations "
                "WHERE family_id=? AND state='ACTIVE'",
                (context.metadata.family_id,),
            ).fetchone()[0]
        )
        if active_count != 1:
            raise IntegratedStateError(
                "candidate admission requires exactly one ACTIVE generation"
            )
        checkpoint_row = conn.execute(
            "SELECT contiguous_ledger_seq FROM projection_checkpoint_versions "
            "WHERE generation_id=? ORDER BY checkpoint_version DESC LIMIT 1",
            (str(context.metadata.generation_id),),
        ).fetchone()
        checkpoint = -1 if checkpoint_row is None else int(checkpoint_row[0])
        if (
            checkpoint != context.metadata.contiguous_ledger_seq
            or generation["validated_through_ledger_seq"] is None
            or int(generation["validated_through_ledger_seq"]) != checkpoint
        ):
            raise IntegratedStateError(
                "retrieval context projection watermark or validation is stale"
            )
        validation = conn.execute(
            "SELECT checkpoint_ledger_seq FROM projection_generation_validations "
            "WHERE generation_id=? ORDER BY validation_version DESC LIMIT 1",
            (str(context.metadata.generation_id),),
        ).fetchone()
        if validation is None or int(validation[0]) != checkpoint:
            raise IntegratedStateError(
                "ACTIVE generation lacks current retained validation"
            )
        open_gaps = int(
            conn.execute(
                "SELECT COUNT(*) FROM projection_gaps "
                "WHERE generation_id=? AND state='OPEN'",
                (str(context.metadata.generation_id),),
            ).fetchone()[0]
        )
        dead_letters = int(
            conn.execute(
                "SELECT COUNT(*) FROM projection_dead_letters "
                "WHERE generation_id=?",
                (str(context.metadata.generation_id),),
            ).fetchone()[0]
        )
        if open_gaps or dead_letters:
            raise IntegratedStateError(
                "projection failure state blocks Candidate admission"
            )

    def _persist_context(
        self,
        conn: sqlite3.Connection,
        context: IntegratedRetrievalContext,
    ) -> None:
        canonical = canonical_json_bytes(context.canonical_value())
        canonical_digest = digest_bytes(canonical)
        if canonical_digest != context.context_digest:
            raise AuthorityPersistenceError(
                "server context digest differs from canonical evidence"
            )
        existing = conn.execute(
            "SELECT * FROM integrated_retrieval_contexts WHERE context_id=?",
            (str(context.context_id),),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["context_digest"]) != context.context_digest
                or bytes(existing["canonical_bytes"]) != canonical
                or str(existing["hydration_access_decision_id"])
                != str(context.hydration_access_decision_id)
            ):
                raise AuthorityPersistenceError(
                    "retrieval context identity belongs to different evidence"
                )
            return
        conn.execute(
            "INSERT INTO integrated_retrieval_contexts("
            "context_id,context_digest,fixture_id,fixture_aggregate_type,"
            "fixture_aggregate_id,fixture_event_id,admission_id,generation_id,"
            "projected_through_ledger_seq,hydration_access_decision_id,"
            "manifest_digest,retrieval_version,canonical_bytes,canonical_digest,"
            "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(context.context_id),
                context.context_digest,
                str(context.fixture_id),
                "integrated_fixture",
                str(context.fixture_aggregate_id),
                str(context.fixture_event_id),
                str(context.admission_id),
                str(context.metadata.generation_id),
                context.metadata.contiguous_ledger_seq,
                str(context.hydration_access_decision_id),
                context.manifest_digest,
                context.retrieval_version,
                canonical,
                canonical_digest,
                context.recorded_at.to_text(),
            ),
        )
        for entry in context.exact_index:
            value = entry.canonical_value()
            entry_canonical = canonical_json_bytes(value)
            conn.execute(
                "INSERT INTO integrated_exact_index_entries("
                "context_id,canonical_id,node_type,first_ledger_seq,"
                "first_source_event_id,first_source_event_digest,"
                "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(context.context_id),
                    entry.canonical_id,
                    entry.node_type.value,
                    entry.first_ledger_seq,
                    entry.first_source_event_id,
                    entry.first_source_event_digest,
                    entry_canonical,
                    digest_bytes(entry_canonical),
                ),
            )

    @staticmethod
    def _candidate_version_value(
        *,
        candidate_id: StoryCandidateId,
        candidate_version_id: StoryCandidateVersionId,
        version_number: int,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
    ) -> dict[str, object]:
        return {
            "contract": _CANDIDATE_VERSION_CONTRACT,
            "candidate_id": str(candidate_id),
            "candidate_version_id": str(candidate_version_id),
            "version_number": version_number,
            "fixture_id": str(manifest.fixture_id),
            "fixture_event_id": str(context.fixture_event_id),
            "admission_id": str(context.admission_id),
            "signal_id": str(manifest.signal_id),
            "lead_id": str(manifest.lead_id),
            "hypothesis_version_id": str(manifest.hypothesis_version_id),
            "route": request.route.value,
            "hypothesis_trust_scope": manifest.hypothesis_trust_scope.value,
            "retrieval_context_id": str(context.context_id),
            "retrieval_context_digest": context.context_digest,
            "manifest_digest": manifest.manifest_digest,
            "manifest": manifest.canonical_value(),
        }

    @staticmethod
    def _decision_value(
        *,
        decision_id: CandidateAdmissionDecisionId,
        outcome: CandidateAdmissionOutcome,
        candidate_id: StoryCandidateId,
        candidate_version_id: StoryCandidateVersionId,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        semantic_collision_digest: str,
        authority_event_id: EventId,
        authority_aggregate_version: int,
    ) -> dict[str, object]:
        return {
            "contract": _DECISION_CONTRACT,
            "decision_id": str(decision_id),
            "proposal_id": str(request.proposal_id),
            "outcome": outcome.value,
            "candidate_id": str(candidate_id),
            "candidate_version_id": str(candidate_version_id),
            "route": request.route.value,
            "fixture_id": str(request.fixture_id),
            "retrieval_context_id": str(context.context_id),
            "retrieval_context_digest": context.context_digest,
            "manifest_digest": manifest.manifest_digest,
            "semantic_collision_digest": semantic_collision_digest,
            "authority_event_id": str(authority_event_id),
            "authority_aggregate_version": authority_aggregate_version,
        }

    def commit_candidate_admission(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: CandidateAdmissionRequest,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        semantic_collision_digest: str,
    ) -> CandidateAdmissionView:
        if not isinstance(request, CandidateAdmissionRequest):
            raise TypeError("candidate admission requires a typed request")
        if not isinstance(context, IntegratedRetrievalContext):
            raise TypeError("candidate admission requires a typed retrieval context")
        if not isinstance(manifest, IntegratedFixtureManifest):
            raise TypeError("candidate admission requires a typed fixture manifest")
        validate_sha256_digest(
            semantic_collision_digest,
            field="semantic_collision_digest",
        )
        expected_collision = self.semantic_collision_digest(
            request, manifest, context
        )
        if semantic_collision_digest != expected_collision:
            raise IntegratedStateError(
                "candidate collision identity differs from server semantics"
            )
        if (
            grant.command_type != CANDIDATE_ADMISSION_COMMAND
            or grant.aggregate_id != str(request.proposal_id)
            or grant.expected_aggregate_version != 0
        ):
            raise PermissionError(
                "candidate admission grant is not bound to the exact proposal"
            )

        with self._lock, self._transaction() as conn:
            checked_at = self._clock()
            self._require_current_context(
                conn,
                request=request,
                context=context,
                manifest=manifest,
                checked_at=checked_at,
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn,
                grant,
                recorded_at=recorded_at,
            )
            if committed.replayed:
                return self._decision_for_event(conn, committed.event_id)

            self._persist_context(conn, context)
            candidate = conn.execute(
                "SELECT candidate_id FROM story_candidates "
                "WHERE semantic_collision_digest=?",
                (semantic_collision_digest,),
            ).fetchone()
            if candidate is None:
                outcome = CandidateAdmissionOutcome.ADMITTED
                candidate_id = StoryCandidateId.new()
                candidate_version_id = StoryCandidateVersionId.new()
                version_number = 1
                conn.execute(
                    "INSERT INTO story_candidates("
                    "candidate_id,semantic_collision_digest,created_at) "
                    "VALUES(?,?,?)",
                    (
                        str(candidate_id),
                        semantic_collision_digest,
                        recorded_at,
                    ),
                )
                version_value = self._candidate_version_value(
                    candidate_id=candidate_id,
                    candidate_version_id=candidate_version_id,
                    version_number=version_number,
                    request=request,
                    context=context,
                    manifest=manifest,
                )
                version_canonical = canonical_json_bytes(version_value)
                conn.execute(
                    "INSERT INTO story_candidate_versions("
                    "candidate_version_id,candidate_id,version_number,fixture_id,"
                    "signal_id,lead_id,hypothesis_version_id,route,"
                    "hypothesis_trust_scope,retrieval_context_id,manifest_digest,"
                    "canonical_bytes,canonical_digest,recorded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(candidate_version_id),
                        str(candidate_id),
                        version_number,
                        str(manifest.fixture_id),
                        str(manifest.signal_id),
                        str(manifest.lead_id),
                        str(manifest.hypothesis_version_id),
                        request.route.value,
                        manifest.hypothesis_trust_scope.value,
                        str(context.context_id),
                        manifest.manifest_digest,
                        version_canonical,
                        digest_bytes(version_canonical),
                        recorded_at,
                    ),
                )
            else:
                outcome = CandidateAdmissionOutcome.DEDUPLICATED
                candidate_id = StoryCandidateId.parse(
                    str(candidate["candidate_id"])
                )
                version = conn.execute(
                    "SELECT candidate_version_id,version_number "
                    "FROM story_candidate_versions WHERE candidate_id=? "
                    "ORDER BY version_number DESC LIMIT 1",
                    (str(candidate_id),),
                ).fetchone()
                if version is None:
                    raise AuthorityPersistenceError(
                        "candidate collision lacks an immutable version"
                    )
                candidate_version_id = StoryCandidateVersionId.parse(
                    str(version["candidate_version_id"])
                )
                version_number = int(version["version_number"])

            decision_id = CandidateAdmissionDecisionId.new()
            authority_event_id = EventId.parse(committed.event_id)
            decision_value = self._decision_value(
                decision_id=decision_id,
                outcome=outcome,
                candidate_id=candidate_id,
                candidate_version_id=candidate_version_id,
                request=request,
                context=context,
                manifest=manifest,
                semantic_collision_digest=semantic_collision_digest,
                authority_event_id=authority_event_id,
                authority_aggregate_version=committed.aggregate_version,
            )
            decision_canonical = canonical_json_bytes(decision_value)
            conn.execute(
                "INSERT INTO candidate_admission_decisions("
                "decision_id,proposal_aggregate_type,proposal_id,outcome,"
                "candidate_id,candidate_version_id,route,fixture_id,"
                "retrieval_context_id,retrieval_context_digest,manifest_digest,"
                "semantic_collision_digest,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(decision_id),
                    "candidate_admission_proposal",
                    str(request.proposal_id),
                    outcome.value,
                    str(candidate_id),
                    str(candidate_version_id),
                    request.route.value,
                    str(request.fixture_id),
                    str(context.context_id),
                    context.context_digest,
                    manifest.manifest_digest,
                    semantic_collision_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    decision_canonical,
                    digest_bytes(decision_canonical),
                    recorded_at,
                ),
            )
            return self._decision_for_event(conn, committed.event_id)

    def _decision_for_event(
        self,
        conn: sqlite3.Connection,
        event_id: str,
    ) -> CandidateAdmissionView:
        row = conn.execute(
            "SELECT d.*,v.version_number,c.fixture_event_id,c.admission_id "
            "FROM candidate_admission_decisions d "
            "JOIN story_candidate_versions v "
            "ON v.candidate_version_id=d.candidate_version_id "
            "JOIN integrated_retrieval_contexts c "
            "ON c.context_id=d.retrieval_context_id "
            "WHERE d.authority_event_id=?",
            (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "candidate admission command lacks its exact decision"
            )
        return CandidateAdmissionView(
            decision_id=CandidateAdmissionDecisionId.parse(
                str(row["decision_id"])
            ),
            outcome=CandidateAdmissionOutcome(str(row["outcome"])),
            proposal_id=IntegratedTriageProposalId.parse(
                str(row["proposal_id"])
            ),
            candidate_id=StoryCandidateId.parse(str(row["candidate_id"])),
            candidate_version_id=StoryCandidateVersionId.parse(
                str(row["candidate_version_id"])
            ),
            candidate_version=int(row["version_number"]),
            route=CandidateRoute(str(row["route"])),
            fixture_id=request_fixture_id(str(row["fixture_id"])),
            fixture_event_id=EventId.parse(str(row["fixture_event_id"])),
            admission_id=ObjectAdmissionId.parse(str(row["admission_id"])),
            retrieval_context_id=IntegratedRetrievalContextId.parse(
                str(row["retrieval_context_id"])
            ),
            retrieval_context_digest=str(row["retrieval_context_digest"]),
            manifest_digest=str(row["manifest_digest"]),
            semantic_collision_digest=str(row["semantic_collision_digest"]),
            authority_event_id=EventId.parse(str(row["authority_event_id"])),
            authority_aggregate_version=int(
                row["authority_aggregate_version"]
            ),
            recorded_at=UtcTimestamp.parse(str(row["recorded_at"])),
        )


def request_fixture_id(value: str):
    from newsroom.integrated.models import IntegratedFixtureId

    return IntegratedFixtureId.parse(value)


__all__ = ["_IntegratedCandidateStore"]
