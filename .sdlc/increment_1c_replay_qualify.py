from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def patch_store() -> None:
    path = "newsroom/authority/_integrated_store.py"
    replace_exact(
        path,
        "from newsroom.authority.persistence import AuthorityPersistenceError\nfrom newsroom.authority.types import EventId, ObjectAdmissionId, UtcTimestamp",
        '''from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import (
    AggregateId,
    EventId,
    ObjectAdmissionId,
    TrustScope,
    UtcTimestamp,
)''',
    )
    replace_exact(
        path,
        '''    IntegratedContractError,
    IntegratedFixtureManifest,
    IntegratedRetrievalContext,''',
        '''    IntegratedContractError,
    IntegratedExactIndexEntry,
    IntegratedFixtureId,
    IntegratedFixtureManifest,
    IntegratedRetrievalContext,''',
    )
    replace_exact(
        path,
        "from newsroom.projection.models import ProjectionGenerationState",
        '''from newsroom.projection.models import (
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
)''',
    )
    replace_exact(
        path,
        '''        return cls._decode_integrated_canonical(canonical, identity=identity)

    @staticmethod
    def semantic_collision_digest(''',
        '''        return cls._decode_integrated_canonical(canonical, identity=identity)

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
    def semantic_collision_digest(''',
    )


def patch_system() -> None:
    path = "newsroom/authority/_integrated_system.py"
    replace_exact(
        path,
        '''    IntegratedFixtureManifest,
    IntegratedRetrievalContext,
    IntegratedStateError,''',
        '''    IntegratedFixtureManifest,
    IntegratedRetrievalContext,
    IntegratedRetrievalContextId,
    IntegratedStateError,''',
    )
    replace_exact(
        path,
        '''class CandidateAdmissions:
    """Authenticated deterministic Candidate authority; no model write path."""

    __slots__ = ("__admit",)

    def __init__(
        self,
        admit: Callable[
            [
                CandidateAdmissionRequest,
                IntegratedRetrievalContext,
                IntegratedFixtureManifest,
                AuthenticationProof,
            ],
            CandidateAdmissionView,
        ],
    ) -> None:
        self.__admit = admit

    def admit(
        self,
        request: CandidateAdmissionRequest,
        *,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        return self.__admit(request, context, manifest, proof)''',
        '''class CandidateAdmissions:
    """Authenticated deterministic Candidate authority; no model write path."""

    __slots__ = ("__admit", "__context")

    def __init__(
        self,
        admit: Callable[
            [
                CandidateAdmissionRequest,
                IntegratedRetrievalContext,
                IntegratedFixtureManifest,
                AuthenticationProof,
            ],
            CandidateAdmissionView,
        ],
        context: Callable[
            [IntegratedRetrievalContextId, AuthenticationProof],
            IntegratedRetrievalContext,
        ],
    ) -> None:
        self.__admit = admit
        self.__context = context

    def admit(
        self,
        request: CandidateAdmissionRequest,
        *,
        context: IntegratedRetrievalContext,
        manifest: IntegratedFixtureManifest,
        proof: AuthenticationProof,
    ) -> CandidateAdmissionView:
        return self.__admit(request, context, manifest, proof)

    def context(
        self,
        context_id: IntegratedRetrievalContextId,
        *,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext:
        return self.__context(context_id, proof)''',
    )
    replace_exact(
        path,
        '''        self._clock = clock
        self._operation_lock = RLock()

    def admit(''',
        '''        self._clock = clock
        self._operation_lock = RLock()

    def context(
        self,
        context_id: IntegratedRetrievalContextId,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("retrieval context identity must be typed")
        authenticated = self._projection_boundary._authenticate_read(proof)
        context = self._store.retrieval_context(context_id)
        self._projection_boundary._authorize_read(
            family_id=context.metadata.family_id,
            operation="integrated-retained-context-read",
            semantic_value={
                "context_id": str(context.context_id),
                "context_digest": context.context_digest,
                "generation_id": str(context.metadata.generation_id),
                "authority_watermark": (
                    context.metadata.contiguous_ledger_seq
                ),
            },
            authenticated=authenticated,
        )
        return context

    def admit(''',
    )
    replace_exact(
        path,
        "            candidates=CandidateAdmissions(boundary.admit),",
        "            candidates=CandidateAdmissions(boundary.admit, boundary.context),",
    )


def patch_proof() -> None:
    path = "newsroom/integrated/proof.py"
    replace_exact(
        path,
        '''    def admit_candidate(
        self,
        request: CandidateAdmissionRequest,''',
        '''    def retained_context(
        self,
        context_id: IntegratedRetrievalContextId,
        *,
        proof: AuthenticationProof,
    ) -> IntegratedRetrievalContext | None:
        if not isinstance(context_id, IntegratedRetrievalContextId):
            raise TypeError("integrated retrieval-context identity must be typed")
        system = open_candidate_admission_authority_system(
            path=self._environment.path,
            registry=self._commands,
            payload_schemas=self._schemas,
            contracts=self._environment.projection_contracts,
            authenticator=self._environment.authenticator,
            authorizer=self._environment.authorizer,
            event_read_policy=self._environment.event_read_policy,
            projection_read_policy=self._environment.projection_read_policy,
            neo4j_config=self._environment.neo4j_config,
            clock=self._environment.clock,
        )
        try:
            try:
                return system.candidates.context(context_id, proof=proof)
            except KeyError:
                return None
        finally:
            system.close()

    def admit_candidate(
        self,
        request: CandidateAdmissionRequest,''',
    )
    replace_exact(
        path,
        '''        context = self.build_context(
            fixture,
            manifest,
            projection,
            context_id=context_id,
            proof=proof,
        )
        candidate = self.admit_candidate(''',
        '''        context = self.retained_context(context_id, proof=proof)
        if context is None:
            context = self.build_context(
                fixture,
                manifest,
                projection,
                context_id=context_id,
                proof=proof,
            )
        elif (
            context.fixture_id != fixture.fixture_id
            or context.fixture_aggregate_id != fixture.fixture_aggregate_id
            or context.fixture_event_id != fixture.fixture_event_id
            or context.admission_id != fixture.admission_id
            or context.manifest_digest != manifest.manifest_digest
            or context.metadata.generation_id
            != projection.generation.generation_id
            or context.metadata.contiguous_ledger_seq
            != projection.response.metadata.contiguous_ledger_seq
            or context.metadata.query_valid_time != query_valid_time
        ):
            raise IntegratedStateError(
                "retrieval context identity belongs to different proof evidence"
            )
        candidate = self.admit_candidate(''',
    )


def main() -> None:
    patch_store()
    patch_system()
    patch_proof()


if __name__ == "__main__":
    main()
