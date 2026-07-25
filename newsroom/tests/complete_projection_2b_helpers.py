from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newsroom.authority import (
    AuthenticationProof,
    EventId,
    ObjectAdmissionId,
    ObjectLimits,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    UtcTimestamp,
    digest_canonical,
)
from newsroom.authority._complete_projection_system import _open_complete_with_adapter
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    INTEGRATED_FIXTURE_V2_PROJECTION,
    ProjectionFamilyKind,
    ProjectionGenerationId,
    ProjectionReadPolicy,
    with_integrated_fixture_v2_complete_projection,
)
from newsroom.projection.neo4j import (
    AdmittedRelationProjection,
    CompleteProjectionBatch,
    CompleteProjectionDocument,
    CompleteProjectionIdentity,
)
from newsroom.relations import (
    FixturePassageObject,
    INTEGRATED_FIXTURE_V2,
    RelationAdmissionDecisionId,
    RelationAssertionId,
    RelationProposalId,
)

from .authority_event_helpers import payload_schemas
from .projection_b1_helpers import (
    event_read_policy,
    projection_contracts,
    projection_read_policy,
    source_command_registry,
)


COMPLETE_NOW = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
COMPLETE_GENERATION_ID = ProjectionGenerationId.parse(
    "33333333-3333-4333-8333-333333333333"
)


def complete_contract_registry():
    return with_integrated_fixture_v2_complete_projection(projection_contracts())


def complete_identity(
    generation_id: ProjectionGenerationId = COMPLETE_GENERATION_ID,
) -> CompleteProjectionIdentity:
    contracts = complete_contract_registry()
    family = contracts.family(INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID)
    fixture = INTEGRATED_FIXTURE_V2_PROJECTION
    return CompleteProjectionIdentity(
        generation_id=generation_id,
        family_id=family.family_id,
        family_definition_version=family.definition_version,
        projector_version=family.projector_version,
        ontology_contract_digest=family.ontology_contract_digest,
        mapping_contract_digest=family.mapping_contract_digest,
        complete_contract_digest=fixture.complete_contract.contract_digest,
        fulltext_contract_digest=fixture.fulltext_contract.contract_digest,
        vector_contract_digest=fixture.vector_contract.contract_digest,
        fixture_vector_manifest_digest=fixture.manifest_digest,
    )


def event_id(number: int) -> EventId:
    return EventId.parse(f"00000000-0000-4000-8000-{number:012d}")


def admission_id(number: int) -> ObjectAdmissionId:
    return ObjectAdmissionId.parse(
        f"00000000-0000-4000-8000-{number:012d}"
    )


def complete_document(
    passage_id: str = "ifv2-new-en",
    *,
    identity: CompleteProjectionIdentity | None = None,
    ledger_seq: int = 1,
    admission_number: int = 5001,
) -> CompleteProjectionDocument:
    selected_identity = identity or complete_identity()
    fixture_document = INTEGRATED_FIXTURE_V2_PROJECTION.document_by_id[passage_id]
    passage = INTEGRATED_FIXTURE_V2.passage_by_id[passage_id]
    return CompleteProjectionDocument(
        identity=selected_identity,
        passage_id=passage_id,
        admission_id=admission_id(admission_number),
        blob_digest=passage.blob_digest,
        language=passage.language,
        revision_id=passage.revision_id,
        retrieval_text=INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_contract.normalize(
            passage.text
        ),
        normalized_text_digest=fixture_document.normalized_text_digest,
        vector_components=fixture_document.components,
        vector_digest=fixture_document.vector_digest,
        vector_dimensions=INTEGRATED_FIXTURE_V2_PROJECTION.dimensions,
        vector_component_scale=INTEGRATED_FIXTURE_V2_PROJECTION.component_scale,
        source_event_id=event_id(ledger_seq),
        source_ledger_seq=ledger_seq,
        recorded_at=COMPLETE_NOW,
    )


def admitted_relation(
    *,
    identity: CompleteProjectionIdentity | None = None,
    ledger_seq: int = 2,
) -> AdmittedRelationProjection:
    selected_identity = identity or complete_identity()
    template = INTEGRATED_FIXTURE_V2.relation
    evidence = tuple(
        sorted(
            (
                FixturePassageObject(
                    passage_id=passage_id,
                    admission_id=admission_id(6000 + index),
                    blob_digest=INTEGRATED_FIXTURE_V2.passage_by_id[
                        passage_id
                    ].blob_digest,
                )
                for index, passage_id in enumerate(
                    template.evidence_passage_ids,
                    start=1,
                )
            ),
            key=lambda item: item.passage_id,
        )
    )
    relation_key = digest_canonical(
        {
            "subject": template.subject.canonical_value(),
            "predicate": template.predicate.value,
            "object": template.object.canonical_value(),
            "temporal_scope": template.temporal_scope.canonical_value(),
        }
    )
    return AdmittedRelationProjection(
        identity=selected_identity,
        assertion_id=RelationAssertionId.parse(
            "00000000-0000-4000-8000-000000006101"
        ),
        proposal_id=RelationProposalId.parse(
            "00000000-0000-4000-8000-000000006102"
        ),
        admission_decision_id=RelationAdmissionDecisionId.parse(
            "00000000-0000-4000-8000-000000006103"
        ),
        relation_key=relation_key,
        subject=template.subject,
        predicate=template.predicate,
        object=template.object,
        temporal_scope=template.temporal_scope,
        evidence_objects=evidence,
        producer=template.producer,
        statement=template.statement,
        uncertainties=template.uncertainties,
        proposal_digest=digest_canonical(
            {
                "fixture": INTEGRATED_FIXTURE_V2.fixture_id,
                "relation_key": relation_key,
            }
        ),
        source_event_id=event_id(ledger_seq),
        source_ledger_seq=ledger_seq,
        recorded_at=COMPLETE_NOW,
    )


def complete_batch(
    *,
    identity: CompleteProjectionIdentity | None = None,
    ledger_seq: int = 1,
    documents: tuple[CompleteProjectionDocument, ...] = (),
    relations: tuple[AdmittedRelationProjection, ...] = (),
    removals=(),
) -> CompleteProjectionBatch:
    selected_identity = identity or complete_identity()
    return CompleteProjectionBatch(
        identity=selected_identity,
        ledger_seq=ledger_seq,
        source_event_id=event_id(ledger_seq),
        source_event_digest=digest_canonical(
            {"event": str(event_id(ledger_seq)), "ledger_seq": ledger_seq}
        ),
        structural_batch=None,
        documents=documents,
        relations=relations,
        removals=removals,
    )


def proof() -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential="token-1")


def complete_scopes() -> frozenset[str]:
    policy = event_read_policy()
    return frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            policy.required_scope,
            "authority.objects.admit",
            "authority.objects.read",
            "authority.objects.manage",
            "authority.objects.lifecycle.write",
            "authority.fixture.v2.bind",
            "authority.relation.propose",
            "authority.relation.admit",
            "authority.relation.metadata.read",
            "authority.relation.project",
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
        }
    )


def open_complete_test_system(
    database: Path,
    *,
    object_root: Path,
    adapter,
    clock: Callable[[], UtcTimestamp] = lambda: COMPLETE_NOW,
):
    return _open_complete_with_adapter(
        path=database,
        object_root=object_root,
        object_limits=ObjectLimits(
            global_max_bytes=1024 * 1024,
            class_max_bytes={"source_capture": 1024 * 1024},
            max_read_bytes=1024 * 1024,
            min_free_bytes=0,
            io_chunk_bytes=64,
            max_staging_bytes=1024 * 1024,
            max_range_bytes=1024 * 1024,
        ),
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=complete_contract_registry(),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="complete-projection-authz-v1",
            grants_by_principal={"principal.alpha": complete_scopes()},
        ),
        event_read_policy=event_read_policy(),
        projection_read_policy=ProjectionReadPolicy(
            policy_id="complete-projection-reader-v1",
            purpose="complete.projection.authority",
            required_scope="authority.projection.read",
            allowed_principal_ids=frozenset({"principal.alpha"}),
            allowed_family_ids=frozenset(
                {INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID, "graph.structural"}
            ),
            allowed_family_kinds=frozenset({ProjectionFamilyKind.GRAPH}),
            max_results=2000,
        ),
        adapter=adapter,
        clock=clock,
    )


@dataclass
class MemoryCompleteNeo4jAdapter:
    fail_writes: bool = False
    reconciliation_mismatch: bool = False
    qualification_mismatch: bool = False

    def __post_init__(self) -> None:
        from newsroom.projection.neo4j import NEO4J_B2_DRIVER_VERSION, NEO4J_B2_SERVER_VERSION

        self.server_version = NEO4J_B2_SERVER_VERSION
        self.driver_version = NEO4J_B2_DRIVER_VERSION
        self.deliveries: dict[tuple[str, int], CompleteProjectionBatch] = {}
        self.bootstrap_schema_count = 0
        self.bootstrap_index_count = 0
        self.apply_count = 0
        self.cleanup_count = 0
        self.reconcile_count = 0
        self.qualify_count = 0
        self.closed = False

    def verify_compatibility(self):
        from newsroom.projection.neo4j import Neo4jCompatibility

        return Neo4jCompatibility(
            server_version=self.server_version,
            edition="community",
            driver_version=self.driver_version,
        )

    def bootstrap_schema(self) -> None:
        self.bootstrap_schema_count += 1

    def bootstrap_generation_indexes(
        self,
        identity,
        *,
        fulltext,
        vector,
        profile,
        timeout_seconds: int = 120,
    ):
        from newsroom.projection.neo4j import complete_generation_names

        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        vector.require_profile(profile)
        self.bootstrap_index_count += 1
        return complete_generation_names(identity, fulltext, vector)

    def apply_complete(self, batch, *, fulltext, vector, profile):
        from newsroom.projection.neo4j import (
            CompleteProjectionApplyResult,
            Neo4jApplyOutcome,
            Neo4jIdentityConflict,
            Neo4jWriteError,
        )

        self.apply_count += 1
        if self.fail_writes:
            raise Neo4jWriteError("fixed complete write failure")
        vector.require_profile(profile)
        key = (str(batch.identity.generation_id), batch.ledger_seq)
        existing = self.deliveries.get(key)
        if existing is not None:
            if existing != batch:
                raise Neo4jIdentityConflict(
                    "memory complete delivery identity conflict"
                )
            outcome = Neo4jApplyOutcome.DUPLICATE
            affected = 0
        else:
            self.deliveries[key] = batch
            outcome = Neo4jApplyOutcome.APPLIED
            affected = (
                len(batch.documents)
                + len(batch.relations)
                + len(batch.removals)
                + 1
            )
        return CompleteProjectionApplyResult(
            outcome=outcome,
            identity=batch.identity,
            ledger_seq=batch.ledger_seq,
            source_event_id=batch.source_event_id,
            source_event_digest=batch.source_event_digest,
            batch_digest=batch.batch_digest,
            affected_record_count=affected,
        )

    def _batches(self, identity, checkpoint_ledger_seq):
        return tuple(
            batch
            for (generation_id, ledger_seq), batch in sorted(self.deliveries.items())
            if generation_id == str(identity.generation_id)
            and ledger_seq <= checkpoint_ledger_seq
        )

    def reconcile_complete_generation(
        self,
        *,
        identity,
        checkpoint_ledger_seq,
        expected_batches,
        fulltext,
        vector,
        profile,
    ) -> str:
        from newsroom.projection.neo4j import (
            Neo4jIdentityConflict,
            expected_complete_projection_state,
        )

        self.reconcile_count += 1
        expected = expected_complete_projection_state(
            identity,
            checkpoint_ledger_seq,
            expected_batches,
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        actual = expected_complete_projection_state(
            identity,
            checkpoint_ledger_seq,
            self._batches(identity, checkpoint_ledger_seq),
            fulltext=fulltext,
            vector=vector,
            profile=profile,
        )
        if self.reconciliation_mismatch or actual.state_digest != expected.state_digest:
            raise Neo4jIdentityConflict(
                "memory complete state differs from retained authority"
            )
        return actual.state_digest

    def qualify_complete_generation(
        self,
        *,
        identity,
        checkpoint_ledger_seq,
        expected_batches,
        fixture,
        profile,
        recorded_at,
    ):
        from newsroom.projection.neo4j import (
            CompleteProjectionQualification,
            CompleteQualificationResult,
            CompleteQueryHit,
            CompleteQueryKind,
            Neo4jIdentityConflict,
            expected_complete_projection_state,
        )

        self.qualify_count += 1
        digest = self.reconcile_complete_generation(
            identity=identity,
            checkpoint_ledger_seq=checkpoint_ledger_seq,
            expected_batches=expected_batches,
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=profile,
        )
        state = expected_complete_projection_state(
            identity,
            checkpoint_ledger_seq,
            expected_batches,
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=profile,
        )
        active = {item.passage_id for item in state.documents}
        if active != set(fixture.expected_active_passage_ids):
            raise Neo4jIdentityConflict(
                "memory complete active set differs from fixture"
            )
        fulltext_hits = []
        for query in fixture.fulltext_queries:
            passage_id = (
                "ifv2-prior-en"
                if self.qualification_mismatch
                else query.expected_first_passage_id
            )
            fulltext_hits.append(
                CompleteQueryHit(
                    query_id=query.query_id,
                    query_kind=CompleteQueryKind.FULL_TEXT,
                    passage_id=passage_id,
                    score=1.0,
                    rank=1,
                )
            )
        vector_hits = []
        for query in fixture.vector_queries:
            prefix = (
                tuple(reversed(query.expected_active_prefix))
                if self.qualification_mismatch
                else query.expected_active_prefix
            )
            vector_hits.extend(
                CompleteQueryHit(
                    query_id=query.query_id,
                    query_kind=CompleteQueryKind.VECTOR,
                    passage_id=passage_id,
                    score=1.0 - (rank - 1) * 0.01,
                    rank=rank,
                )
                for rank, passage_id in enumerate(prefix, start=1)
            )
        if self.qualification_mismatch:
            raise Neo4jIdentityConflict(
                "memory complete qualification differs from fixture"
            )
        return CompleteProjectionQualification(
            identity=identity,
            checkpoint_ledger_seq=checkpoint_ledger_seq,
            projection_state_digest=digest,
            result=CompleteQualificationResult.PASSED,
            fulltext_hits=tuple(fulltext_hits),
            vector_hits=tuple(vector_hits),
            expected_tombstoned_passage_ids=tuple(
                sorted(fixture.expected_tombstoned_passage_ids)
            ),
            recorded_at=recorded_at,
        )

    def cleanup_complete_generation(self, identity, *, fulltext, vector) -> int:
        self.cleanup_count += 1
        selected = [
            key for key in self.deliveries if key[0] == str(identity.generation_id)
        ]
        deleted = sum(
            len(self.deliveries[key].documents)
            + len(self.deliveries[key].relations)
            + len(self.deliveries[key].removals)
            + 1
            for key in selected
        )
        for key in selected:
            del self.deliveries[key]
        return deleted

    def close(self) -> None:
        self.closed = True


def seed_complete_fixture_authority(
    database: Path,
    *,
    object_root: Path,
):
    from newsroom.relations import RelationDecisionAction
    from .relation_2a_helpers import (
        bind_fixture_and_propose,
        decision_request,
        open_relation_system,
        proof as relation_proof,
        seed_fixture_objects,
    )

    seeded = seed_fixture_objects(database, object_root=object_root)
    proposal = bind_fixture_and_propose(database, seeded)
    system = open_relation_system(database)
    try:
        decision = system.relations.decide(
            decision_request(proposal, action=RelationDecisionAction.ADMIT),
            proof=relation_proof(),
        )
    finally:
        system.close()
    return seeded, proposal, decision


def register_complete_generation(
    system,
    *,
    suffix: str = "default",
    register_family: bool = True,
):
    from newsroom.projection import (
        INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
        ProjectionFamilyRegistrationRequest,
        ProjectionGenerationCreateRequest,
    )

    if register_family:
        system.projections.register_family(
            ProjectionFamilyRegistrationRequest(
                INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
                f"complete-family-register-{suffix}",
            ),
            proof=proof(),
        )
    generation_id = (
        COMPLETE_GENERATION_ID
        if suffix == "default"
        else ProjectionGenerationId.new()
    )
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            generation_id,
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            "INCREMENT_2B_COMPLETE_BUILD",
            f"complete-generation-create-{suffix}",
        ),
        proof=proof(),
    )
