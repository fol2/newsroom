from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from newsroom.authority import (
    AggregateId,
    AuthenticationProof,
    InlinePayload,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    UtcTimestamp,
)
from newsroom.authority._neo4j_projection_system import _open_with_adapter
from newsroom.authority.neo4j_projection_system import (
    open_neo4j_projection_authority_system,
)
from newsroom.projection import ProjectionGenerationId
from newsroom.projection.neo4j import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
    Neo4jApplyOutcome,
    Neo4jApplyResult,
    Neo4jCompatibility,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jStructuralRead,
    Neo4jWriteError,
    StructuralBatch,
    StructuralGraphNodeView,
    StructuralGraphRelationView,
)

from newsroom.projection.neo4j._state import (
    _expected_projection_state_digest,
)

from .authority_event_helpers import payload_schemas
from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import (
    event_read_policy,
    projection_contracts,
    projection_read_policy,
    source_command_registry,
)


class _MemoryDeliveryStore(dict[tuple[str, int], StructuralBatch]):
    """Current fake graph batches with graph-loss-aware marker cleanup."""

    def __init__(
        self,
        markers: dict[tuple[str, int], StructuralBatch],
    ) -> None:
        super().__init__()
        self._markers = markers

    def clear(self) -> None:
        super().clear()
        self._markers.clear()


@dataclass
class MemoryNeo4jAdapter:
    fail_writes: bool = False
    reconciliation_mismatch: bool = False

    def __post_init__(self) -> None:
        self._delivery_markers: dict[tuple[str, int], StructuralBatch] = {}
        self.deliveries: dict[tuple[str, int], StructuralBatch] = (
            _MemoryDeliveryStore(self._delivery_markers)
        )
        self.bootstrap_count = 0
        self.apply_count = 0
        self.cleanup_count = 0
        self.reconcile_count = 0
        self.closed = False

    def verify_compatibility(self) -> Neo4jCompatibility:
        return Neo4jCompatibility(
            server_version=NEO4J_B2_SERVER_VERSION,
            edition="community",
            driver_version=NEO4J_B2_DRIVER_VERSION,
        )

    def bootstrap_schema(self) -> None:
        self.bootstrap_count += 1

    def apply(self, batch: StructuralBatch) -> Neo4jApplyResult:
        self.apply_count += 1
        if self.fail_writes:
            raise Neo4jWriteError("fixed fake write failure")
        key = (str(batch.generation_id), batch.ledger_seq)
        existing = self._delivery_markers.get(key)
        if existing is not None:
            if (
                existing.source_event_id != batch.source_event_id
                or existing.source_event_digest != batch.source_event_digest
                or existing.batch_digest != batch.batch_digest
            ):
                raise Neo4jIdentityConflict(
                    "fake delivery identity belongs to another batch"
                )
            outcome = Neo4jApplyOutcome.DUPLICATE
        else:
            self._delivery_markers[key] = batch
            self.deliveries[key] = batch
            outcome = Neo4jApplyOutcome.APPLIED
        return Neo4jApplyResult(
            outcome=outcome,
            generation_id=batch.generation_id,
            ledger_seq=batch.ledger_seq,
            source_event_id=batch.source_event_id,
            source_event_digest=batch.source_event_digest,
            batch_digest=batch.batch_digest,
        )

    def read(
        self,
        *,
        generation_id: str,
        canonical_ids: tuple[str, ...],
        maximum_ledger_seq: int,
        limit: int,
    ) -> Neo4jStructuralRead:
        selected = set(canonical_ids)
        batches = tuple(
            batch
            for (stored_generation, sequence), batch in sorted(
                self.deliveries.items(), key=lambda item: item[0]
            )
            if stored_generation == generation_id
            and sequence <= maximum_ledger_seq
        )
        stored_nodes = {
            node.canonical_id: node
            for batch in batches
            for node in batch.nodes
        }
        selected_relations = tuple(
            relation
            for batch in batches
            for relation in batch.relations
            if relation.source_canonical_id in selected
            or relation.target_canonical_id in selected
        )[:limit]
        selected_node_ids = selected | {
            endpoint
            for relation in selected_relations
            for endpoint in (
                relation.source_canonical_id,
                relation.target_canonical_id,
            )
        }
        nodes = tuple(
            StructuralGraphNodeView(
                canonical_id=node.canonical_id,
                node_type=node.node_type,
                identity_source=node.identity_source,
                identity_reference_digest=node.identity_reference_digest,
                first_ledger_seq=node.first_ledger_seq,
                first_source_event_id=node.first_source_event_id,
                first_source_event_digest=node.first_source_event_digest,
            )
            for canonical_id in sorted(selected_node_ids)
            if (node := stored_nodes.get(canonical_id)) is not None
        )[:limit]
        relations = tuple(
            StructuralGraphRelationView(
                relation_key=relation.relation_key,
                relation_type=relation.relation_type,
                source_canonical_id=relation.source_canonical_id,
                target_canonical_id=relation.target_canonical_id,
                ledger_seq=relation.ledger_seq,
                source_event_id=relation.source_event_id,
                source_event_type=relation.source_event_type,
                source_event_digest=relation.source_event_digest,
                aggregate_type=relation.aggregate_type,
                aggregate_id=relation.aggregate_id,
                aggregate_version=relation.aggregate_version,
                payload_id=relation.payload_id,
                payload_digest=relation.payload_digest,
                object_admission_id=relation.object_admission_id,
                principal_id=relation.principal_id,
                trust_scope=relation.trust_scope,
                security_scope=relation.security_scope,
                retention_scope=relation.retention_scope,
                recorded_at=relation.recorded_at,
            )
            for relation in selected_relations
        )
        return Neo4jStructuralRead(nodes=nodes, relations=relations)

    def reconcile_generation(
        self,
        *,
        generation_id: str,
        expected_batches: tuple[StructuralBatch, ...],
    ) -> str:
        self.reconcile_count += 1
        expected_digest = _expected_projection_state_digest(
            generation_id, expected_batches
        )
        actual_batches = tuple(
            batch
            for (stored_generation, _ledger_seq), batch in sorted(
                self._delivery_markers.items(), key=lambda item: item[0]
            )
            if stored_generation == generation_id
        )
        actual_digest = _expected_projection_state_digest(
            generation_id, actual_batches
        )
        if (
            self.reconciliation_mismatch
            or actual_digest != expected_digest
        ):
            raise Neo4jIdentityConflict(
                "fake graph state differs from retained authority"
            )
        return actual_digest

    def cleanup_generation(self, generation_id: str) -> int:
        self.cleanup_count += 1
        selected = {
            key for key in self.deliveries if key[0] == generation_id
        } | {
            key for key in self._delivery_markers if key[0] == generation_id
        }
        for key in selected:
            self.deliveries.pop(key, None)
            self._delivery_markers.pop(key, None)
        return len(selected)

    def corrupt_delivery_digest(
        self, generation_id: ProjectionGenerationId, ledger_seq: int
    ) -> None:
        key = (str(generation_id), ledger_seq)
        batch = self.deliveries[key]
        object.__setattr__(batch, "source_event_digest", "sha256:" + "f" * 64)

    def close(self) -> None:
        self.closed = True


def open_b2_system(
    path: Path,
    adapter: MemoryNeo4jAdapter,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
):
    policy = event_read_policy()
    selected = scopes or frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            policy.required_scope,
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
        }
    )
    return _open_with_adapter(
        path=path,
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=projection_contracts(),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={"principal.alpha": selected},
        ),
        event_read_policy=policy,
        projection_read_policy=projection_read_policy(),
        adapter=adapter,
        clock=clock or (lambda: FIXED_NOW),
    )


def open_b2_service_system(
    path: Path,
    config: Neo4jProjectorConfig,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
):
    """Open the public authenticated B2 composition against a real service."""

    policy = event_read_policy()
    selected = scopes or frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            policy.required_scope,
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
        }
    )
    return open_neo4j_projection_authority_system(
        path=path,
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=projection_contracts(),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={"principal.alpha": selected},
        ),
        event_read_policy=policy,
        projection_read_policy=projection_read_policy(),
        neo4j_config=config,
        clock=clock or (lambda: FIXED_NOW),
    )


def proof() -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential="token-1")


def source_command(*, key: str, aggregate_id: AggregateId | None = None) -> SemanticCommand:
    return SemanticCommand(
        command_type="source.item.write",
        aggregate_id=aggregate_id or AggregateId.new(),
        expected_aggregate_version=0,
        payload=InlinePayload({"headline": "B2 fixture", "count": 1}),
        idempotency_key=key,
    )


def structural_batch(
    *,
    generation_id: ProjectionGenerationId | None = None,
    ledger_seq: int = 1,
    object_admission_id: str | None = None,
) -> StructuralBatch:
    """Build a deterministic typed batch for private adapter tests."""

    from newsroom.authority import TrustScope, digest_canonical
    from newsroom.projection import ProjectionNodeType, ProjectionRelationType
    from newsroom.projection.neo4j import StructuralNode, StructuralRelation

    selected_generation = generation_id or ProjectionGenerationId.new()
    source_event_id = "event-b2-adapter-fixture"
    source_event_digest = digest_canonical(
        {
            "fixture": "projection-b2-adapter",
            "ledger_seq": ledger_seq,
        }
    )
    source_id = "npid:v1:source-item:adapter-fixture"
    event_id = "npid:v1:ledger-event:adapter-fixture"
    nodes = (
        StructuralNode(
            canonical_id=source_id,
            node_type=ProjectionNodeType.SOURCE_ITEM,
            identity_source="AGGREGATE_ID",
            identity_reference_digest=digest_canonical(
                {"canonical_id": source_id, "type": "SOURCE_ITEM"}
            ),
            first_ledger_seq=ledger_seq,
            first_source_event_id=source_event_id,
            first_source_event_digest=source_event_digest,
        ),
        StructuralNode(
            canonical_id=event_id,
            node_type=ProjectionNodeType.LEDGER_EVENT,
            identity_source="EVENT_ID",
            identity_reference_digest=digest_canonical(
                {"canonical_id": event_id, "type": "LEDGER_EVENT"}
            ),
            first_ledger_seq=ledger_seq,
            first_source_event_id=source_event_id,
            first_source_event_digest=source_event_digest,
        ),
    )
    relation = StructuralRelation(
        relation_key=digest_canonical(
            {
                "source": source_id,
                "target": event_id,
                "ledger_seq": ledger_seq,
            }
        ),
        relation_type=ProjectionRelationType.PROJECTED_FROM_EVENT,
        source_canonical_id=source_id,
        target_canonical_id=event_id,
        ledger_seq=ledger_seq,
        source_event_id=source_event_id,
        source_event_type="source.item.written",
        source_event_digest=source_event_digest,
        aggregate_type="source_item",
        aggregate_id="aggregate-b2-adapter-fixture",
        aggregate_version=1,
        payload_id="payload-b2-adapter-fixture",
        payload_digest=digest_canonical({"payload": "adapter-fixture"}),
        object_admission_id=object_admission_id,
        principal_id="principal.alpha",
        trust_scope=TrustScope.OBSERVED,
        security_scope="newsroom.internal",
        retention_scope="newsroom.standard",
        recorded_at=FIXED_NOW,
    )
    return StructuralBatch(
        generation_id=selected_generation,
        family_id="native-structural-v1",
        family_definition_version="projection-family-v1",
        projector_version="native-projector-v1",
        ontology_contract_digest=digest_canonical({"ontology": "v1"}),
        mapping_contract_digest=digest_canonical({"mapping": "v1"}),
        ledger_seq=ledger_seq,
        source_event_id=source_event_id,
        source_event_type="source.item.written",
        source_event_digest=source_event_digest,
        nodes=nodes,
        relations=(relation,),
    )
