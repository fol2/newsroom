from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    value = target.read_text(encoding="utf-8")
    if value.count(old) != 1:
        raise SystemExit(f"replacement mismatch: {path}")
    target.write_text(value.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, value: str) -> None:
    target = Path(path)
    current = target.read_text(encoding="utf-8")
    if marker in current:
        raise SystemExit(f"append marker already present: {path}")
    target.write_text(current.rstrip() + "\n\n\n" + value.lstrip(), encoding="utf-8")


def create_once(path: str, value: str) -> None:
    target = Path(path)
    if target.exists():
        raise SystemExit(f"new file already exists: {path}")
    target.write_text(value, encoding="utf-8")


# Native mapping: tombstone is required structural authority, represented by
# deletion/event provenance while graph deletion is driven by retained object rows.
replace_once(
    "newsroom/projection/mapping.py",
    '''        StructuralEventMapping(
            "candidate.proposal.recorded",
            False,
            (
                _node(
                    "proposal",
                    ProjectionNodeType.CANDIDATE_PROPOSAL,
                    ProjectionIdentitySource.AGGREGATE_ID,
                ),
                _node(
                    "event",
                    ProjectionNodeType.LEDGER_EVENT,
                    ProjectionIdentitySource.EVENT_ID,
                ),
            ),
            (
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "proposal",
                    "event",
                ),
            ),
        ),
    )
''',
    '''        StructuralEventMapping(
            "candidate.proposal.recorded",
            False,
            (
                _node(
                    "proposal",
                    ProjectionNodeType.CANDIDATE_PROPOSAL,
                    ProjectionIdentitySource.AGGREGATE_ID,
                ),
                _node(
                    "event",
                    ProjectionNodeType.LEDGER_EVENT,
                    ProjectionIdentitySource.EVENT_ID,
                ),
            ),
            (
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "proposal",
                    "event",
                ),
            ),
        ),
        StructuralEventMapping(
            "governed_blob.deletion.tombstoned",
            True,
            (
                _node(
                    "deletion",
                    ProjectionNodeType.AUTHORITY_AGGREGATE,
                    ProjectionIdentitySource.AGGREGATE_ID,
                ),
                _node(
                    "event",
                    ProjectionNodeType.LEDGER_EVENT,
                    ProjectionIdentitySource.EVENT_ID,
                ),
            ),
            (
                _relation(
                    ProjectionRelationType.PROJECTED_FROM_EVENT,
                    "deletion",
                    "event",
                ),
            ),
        ),
    )
''',
)

# Retained authority input: bind payload/object-admission identity and resolve the
# exact admission set covered by a historical tombstone version.
replace_once(
    "newsroom/authority/_projection_store.py",
    "from .canonical import canonical_json_bytes, digest_bytes, digest_canonical\n",
    "from .canonical import (\n    canonical_json_bytes,\n    digest_bytes,\n    digest_canonical,\n    validate_sha256_digest,\n)\n",
)
replace_once(
    "newsroom/authority/_projection_store.py",
    '''    payload: Mapping[str, object]
    payload_is_mapping: bool
''',
    '''    payload: Mapping[str, object]
    payload_is_mapping: bool
    tombstoned_object_admission_ids: tuple[str, ...]
''',
)
replace_once(
    "newsroom/authority/_projection_store.py",
    '''            if (
                str(row["mode"]) != event.payload_mode
                or str(row["payload_digest"]) != event.payload_digest
            ):
                raise AuthorityPersistenceError(
                    "projection source payload metadata is inconsistent"
                )
            payload: Mapping[str, object]
''',
    '''            if (
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
''',
)
replace_once(
    "newsroom/authority/_projection_store.py",
    '''            else:
                payload = MappingProxyType({})
            return _ProjectionDeliverySource(
                generation=generation,
                family=family,
                mapping_contract=mapping_contract,
                mapping=mapping_contract.resolve(event.event_type),
                event=event,
                source_event_digest=source_event_digest,
                payload=payload,
                payload_is_mapping=payload_is_mapping,
            )
''',
    '''            else:
                payload = MappingProxyType({})

            tombstoned_admission_ids: tuple[str, ...] = ()
            if event.event_type == "governed_blob.deletion.tombstoned":
                if (
                    event.aggregate_type != "governed_object_lifecycle"
                    or not payload_is_mapping
                    or set(payload) != {"blob_digest"}
                    or not isinstance(payload.get("blob_digest"), str)
                ):
                    raise AuthorityPersistenceError(
                        "projection tombstone source shape is inconsistent"
                    )
                blob_digest = str(payload["blob_digest"])
                try:
                    validate_sha256_digest(blob_digest, field="blob_digest")
                except ValueError as exc:
                    raise AuthorityPersistenceError(
                        "projection tombstone blob digest is invalid"
                    ) from exc
                deletion = conn.execute(
                    "SELECT deletion_id,blob_digest,lifecycle_version FROM object_deletions "
                    "WHERE deletion_id=?",
                    (event.aggregate_id,),
                ).fetchone()
                version = conn.execute(
                    "SELECT lifecycle_version,state,event_id FROM object_deletion_versions "
                    "WHERE deletion_id=? AND event_id=?",
                    (event.aggregate_id, event.event_id),
                ).fetchone()
                if (
                    deletion is None
                    or str(deletion["blob_digest"]) != blob_digest
                    or version is None
                    or str(version["state"]) != "TOMBSTONED"
                    or int(version["lifecycle_version"]) != event.aggregate_version
                    or int(deletion["lifecycle_version"])
                    < int(version["lifecycle_version"])
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
''',
)

# Typed graph batch: deletion scope is immutable, sorted, and content-addressed.
replace_once(
    "newsroom/projection/neo4j/models.py",
    '''    source_event_digest: str
    nodes: tuple[StructuralNode, ...]
    relations: tuple[StructuralRelation, ...]

    def __post_init__(self) -> None:
''',
    '''    source_event_digest: str
    nodes: tuple[StructuralNode, ...]
    relations: tuple[StructuralRelation, ...]
    tombstoned_object_admission_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
''',
)
replace_once(
    "newsroom/projection/neo4j/models.py",
    '''        object.__setattr__(
            self,
            "relations",
            _tuple_of(self.relations, StructuralRelation, field="relations", maximum=64),
        )
        if not self.nodes or not self.relations:
            raise Neo4jProjectionError("structural batch cannot be empty")
''',
    '''        object.__setattr__(
            self,
            "relations",
            _tuple_of(self.relations, StructuralRelation, field="relations", maximum=64),
        )
        tombstoned = tuple(
            _non_empty_string(
                item,
                field="tombstoned_object_admission_id",
                maximum=128,
            )
            for item in self.tombstoned_object_admission_ids
        )
        if tombstoned != tuple(sorted(set(tombstoned))):
            raise Neo4jProjectionError(
                "tombstoned object admission identities must be sorted and unique"
            )
        if bool(tombstoned) != (
            self.source_event_type == "governed_blob.deletion.tombstoned"
        ):
            raise Neo4jProjectionError(
                "tombstone deletion scope must match the authoritative event type"
            )
        object.__setattr__(
            self, "tombstoned_object_admission_ids", tombstoned
        )
        if not self.nodes or not self.relations:
            raise Neo4jProjectionError("structural batch cannot be empty")
''',
)
replace_once(
    "newsroom/projection/neo4j/models.py",
    '''                "nodes": [item.canonical_value() for item in self.nodes],
                "relations": [item.canonical_value() for item in self.relations],
            }
        )
''',
    '''                "nodes": [item.canonical_value() for item in self.nodes],
                "relations": [item.canonical_value() for item in self.relations],
                "tombstoned_object_admission_ids": list(
                    self.tombstoned_object_admission_ids
                ),
            }
        )
''',
)

replace_once(
    "newsroom/authority/_neo4j_projection_system.py",
    '''        source_event_digest=source.source_event_digest,
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        relations=tuple(relations),
    )
''',
    '''        source_event_digest=source.source_event_digest,
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        relations=tuple(relations),
        tombstoned_object_admission_ids=(
            source.tombstoned_object_admission_ids
        ),
    )
''',
)

# Fixed-query Neo4j tombstone application inside the same delivery transaction.
replace_once(
    "newsroom/projection/neo4j/_adapter.py",
    '''_CREATE_DELIVERY_MARKER_QUERY = """
CREATE (delivery:NewsroomProjectionDelivery {
''',
    '''_TOMBSTONE_RELATIONS_QUERY = """
MATCH (source:NewsroomProjectionNode {generation_id: $generation_id})
      -[relation]->
      (target:NewsroomProjectionNode {generation_id: $generation_id})
WHERE relation.object_admission_id IN $object_admission_ids
WITH collect(DISTINCT relation.relation_key) AS relation_keys,
     collect(DISTINCT source.canonical_id)
       + collect(DISTINCT target.canonical_id) AS canonical_ids,
     collect(relation) AS relations
FOREACH (item IN relations | DELETE item)
RETURN relation_keys, canonical_ids, size(relations) AS deleted_count
"""
_TOMBSTONE_RELATION_IDENTITIES_QUERY = """
MATCH (identity:NewsroomProjectionRelationIdentity {generation_id: $generation_id})
WHERE identity.relation_key IN $relation_keys
WITH collect(identity) AS identities
FOREACH (item IN identities | DELETE item)
RETURN size(identities) AS deleted_count
"""
_TOMBSTONE_ORPHAN_NODES_QUERY = """
MATCH (node:NewsroomProjectionNode {generation_id: $generation_id})
WHERE node.canonical_id IN $canonical_ids AND NOT (node)--()
WITH collect(node) AS nodes
FOREACH (item IN nodes | DELETE item)
RETURN size(nodes) AS deleted_count
"""
_CREATE_DELIVERY_MARKER_QUERY = """
CREATE (delivery:NewsroomProjectionDelivery {
''',
)
replace_once(
    "newsroom/projection/neo4j/_adapter.py",
    '''        for node in batch.nodes:
            existing = transaction.run(
''',
    '''        if batch.tombstoned_object_admission_ids:
            deleted = transaction.run(
                _TOMBSTONE_RELATIONS_QUERY,
                generation_id=str(batch.generation_id),
                object_admission_ids=list(
                    batch.tombstoned_object_admission_ids
                ),
            ).single()
            if deleted is None:
                raise Neo4jWriteError(
                    "Neo4j tombstone deletion returned no result"
                )
            relation_keys = sorted(
                {
                    str(item)
                    for item in (deleted["relation_keys"] or [])
                    if item is not None
                }
            )
            canonical_ids = sorted(
                {
                    str(item)
                    for item in (deleted["canonical_ids"] or [])
                    if item is not None
                }
            )
            if relation_keys:
                transaction.run(
                    _TOMBSTONE_RELATION_IDENTITIES_QUERY,
                    generation_id=str(batch.generation_id),
                    relation_keys=relation_keys,
                ).consume()
            if canonical_ids:
                transaction.run(
                    _TOMBSTONE_ORPHAN_NODES_QUERY,
                    generation_id=str(batch.generation_id),
                    canonical_ids=canonical_ids,
                ).consume()

        for node in batch.nodes:
            existing = transaction.run(
''',
)

# Test adapter and composition helpers.
replace_once(
    "newsroom/tests/projection_b2_helpers.py",
    '''    AggregateId,
    AuthenticationProof,
    InlinePayload,
''',
    '''    AggregateId,
    AuthenticationProof,
    CommandRegistry,
    InlinePayload,
    PayloadSchemaRegistry,
''',
)
replace_once(
    "newsroom/tests/projection_b2_helpers.py",
    '''        else:
            self.deliveries[key] = batch
            outcome = Neo4jApplyOutcome.APPLIED
''',
    '''        else:
            if batch.tombstoned_object_admission_ids:
                covered = set(batch.tombstoned_object_admission_ids)
                for prior_key, prior in tuple(self.deliveries.items()):
                    if prior_key[0] != str(batch.generation_id):
                        continue
                    if any(
                        relation.object_admission_id in covered
                        for relation in prior.relations
                    ):
                        del self.deliveries[prior_key]
            self.deliveries[key] = batch
            outcome = Neo4jApplyOutcome.APPLIED
''',
)
replace_once(
    "newsroom/tests/projection_b2_helpers.py",
    '''def open_b2_system(
    path: Path,
    adapter: MemoryNeo4jAdapter,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
):
''',
    '''def open_b2_system(
    path: Path,
    adapter: MemoryNeo4jAdapter,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
    command_registry: CommandRegistry | None = None,
    payload_schema_registry: PayloadSchemaRegistry | None = None,
):
''',
)
replace_once(
    "newsroom/tests/projection_b2_helpers.py",
    '''        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=projection_contracts(),
''',
    '''        registry=command_registry or source_command_registry(),
        payload_schemas=payload_schema_registry or payload_schemas(),
        contracts=projection_contracts(),
''',
)
replace_once(
    "newsroom/tests/projection_b2_helpers.py",
    '''def open_b2_service_system(
    path: Path,
    config: Neo4jProjectorConfig,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
):
''',
    '''def open_b2_service_system(
    path: Path,
    config: Neo4jProjectorConfig,
    *,
    scopes: frozenset[str] | None = None,
    clock: Callable[[], UtcTimestamp] | None = None,
    command_registry: CommandRegistry | None = None,
    payload_schema_registry: PayloadSchemaRegistry | None = None,
):
''',
)
# Only the remaining service opening retains the original exact registry lines.
replace_once(
    "newsroom/tests/projection_b2_helpers.py",
    '''        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=projection_contracts(),
''',
    '''        registry=command_registry or source_command_registry(),
        payload_schemas=payload_schema_registry or payload_schemas(),
        contracts=projection_contracts(),
''',
)

# Reusable authoritative history fixture for memory and actual-service tests.
create_once(
    "newsroom/tests/projection_b3_tombstone_helpers.py",
    '''from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newsroom.authority import (
    AggregateId,
    CommandDefinition,
    CommandRegistry,
    EventWindow,
    ObjectAdmissionDescriptor,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    PayloadGoldenVector,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
    SemanticCommand,
    TrustScope,
    canonical_json_bytes,
)
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.authority.persistence import LedgerEventRecord

from .authority_a2b_helpers import admit, open_object_system
from .authority_event_helpers import payload_schemas
from .projection_b1_helpers import proof, source_command_registry


@dataclass(frozen=True, slots=True)
class TombstonedStructuralHistory:
    admission_id: ObjectAdmissionId
    blob_digest: str
    source_event: LedgerEventRecord
    tombstone_event: LedgerEventRecord


def _object_reference_bytes(value: object) -> bytes:
    if not isinstance(value, ObjectAdmissionDescriptor):
        raise PayloadSchemaValidationError(
            "object-reference payload requires an admission descriptor"
        )
    return canonical_json_bytes(
        {
            "admission_id": str(value.admission_id),
            "blob_digest": value.blob_digest,
            "object_class": value.object_class,
            "allowed_use": value.allowed_use,
            "security_scope": value.security_scope,
            "retention_scope": value.retention_scope,
        }
    )


def _object_contract() -> PayloadSchemaContract:
    vector = ObjectAdmissionDescriptor(
        admission_id=ObjectAdmissionId.parse(
            "00000000-0000-4000-8000-000000000001"
        ),
        blob_digest="sha256:" + "a" * 64,
        object_class="source_capture",
        allowed_use="project.discovery",
        security_scope="authority.protected",
        retention_scope="source.short",
        active=True,
    )
    return PayloadSchemaContract(
        schema_version="projection_object_reference_v1",
        payload_mode=PayloadMode.OBJECT_ADMISSION,
        contract_version="projection-object-contract-v1",
        canonicalizer_implementation_version="projection-object-canonicalizer-v1",
        canonicalizer=_object_reference_bytes,
        golden_vectors=(
            PayloadGoldenVector(
                name="projection-object-reference",
                input_identity="projection-object-reference-v1",
                value=vector,
                expected_bytes=_object_reference_bytes(vector),
            ),
        ),
    )


def _object_definition(contract: PayloadSchemaContract) -> CommandDefinition:
    return CommandDefinition(
        command_type="record.object_versioned",
        definition_version="projection-object-command-v1",
        aggregate_type="fixture_aggregate",
        event_type="authority.aggregate.versioned",
        event_schema_version=1,
        payload_mode=PayloadMode.OBJECT_ADMISSION,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=contract.canonicalizer_implementation_version,
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="source.short",
        required_scope="authority.observed.write",
        required_object_class="source_capture",
        required_allowed_use="project.discovery",
    )


def tombstone_registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    contract = _object_contract()
    commands = CommandRegistry(
        (*source_command_registry().definitions(), _object_definition(contract))
    )
    schemas = PayloadSchemaRegistry((*payload_schemas().contracts(), contract))
    return merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )


def create_tombstoned_structural_history(
    database: Path,
    object_root: Path,
) -> tuple[CommandRegistry, PayloadSchemaRegistry, TombstonedStructuralHistory]:
    commands, schemas = tombstone_registries()
    system = open_object_system(
        database,
        object_root=object_root,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        admission = admit(
            system,
            data=b"B3 authoritative object-backed structural payload",
        ).admission
        committed = system.commands.execute(
            SemanticCommand(
                command_type="record.object_versioned",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=ObjectAdmissionPayload(admission.admission_id),
                idempotency_key="b3-object-structural-event",
            ),
            proof=proof(),
        )
        system.objects.revoke(
            admission.admission_id,
            reason_code="B3_TOMBSTONE_REVOKE",
            idempotency_key="b3-object-revoke",
            proof=proof(),
        )
        deletion = system.objects.request_deletion(
            admission.blob.blob_digest,
            reason_code="B3_TOMBSTONE_REQUEST",
            idempotency_key="b3-object-delete",
            proof=proof(),
        )
        tombstone = system.objects.tombstone(
            deletion.deletion_id,
            reason_code="B3_TOMBSTONE_COMMIT",
            idempotency_key="b3-object-tombstone",
            proof=proof(),
        )
        events = system.events.after(
            EventWindow(
                minimum_ledger_seq=1,
                maximum_ledger_seq=None,
                limit=1000,
            ),
            proof=proof(),
        )
        source_event = next(
            item for item in events if item.event_id == str(committed.event_id)
        )
        tombstone_event = next(
            item for item in events if item.event_id == str(tombstone.last_event_id)
        )
        return (
            commands,
            schemas,
            TombstonedStructuralHistory(
                admission_id=admission.admission_id,
                blob_digest=admission.blob.blob_digest,
                source_event=source_event,
                tombstone_event=tombstone_event,
            ),
        )
    finally:
        system.close()
''',
)

create_once(
    "newsroom/tests/test_projection_b3_tombstone.py",
    '''from __future__ import annotations

from pathlib import Path

from newsroom.authority import digest_canonical
from newsroom.projection import (
    ProjectionFamilyRegistrationRequest,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationValidationRequest,
    ProjectionIdentitySource,
    ProjectionNodeType,
    ProjectionRelationType,
    StructuralIdentityContext,
    canonical_node_id,
)
from newsroom.projection.neo4j import (
    StructuralReadRequest,
    StructuralRebuildRequest,
)

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID, proof
from .projection_b2_helpers import MemoryNeo4jAdapter, open_b2_system
from .projection_b3_tombstone_helpers import (
    TombstonedStructuralHistory,
    create_tombstoned_structural_history,
)


SERVICE_DIGEST = digest_canonical(
    {"neo4j_server": "2026.06.0", "edition": "community", "driver": "6.2.0"}
)


def _canonical_id(
    event,
    node_type: ProjectionNodeType,
    identity_source: ProjectionIdentitySource,
) -> str:
    return canonical_node_id(
        type(
            "Binding",
            (),
            {
                "node_type": node_type,
                "identity_source": identity_source,
                "payload_field": None,
            },
        )(),
        StructuralIdentityContext(
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            aggregate_version=event.aggregate_version,
            event_id=event.event_id,
            payload_id=event.payload_id,
            payload={},
        ),
    )


def _register_generation(system):
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "b3-tombstone-family"),
        proof=proof(),
    )
    return system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            ProjectionGenerationId.new(),
            FAMILY_ID,
            "B3_TOMBSTONE_REBUILD",
            "b3-tombstone-generation",
        ),
        proof=proof(),
    )


def _rebuild_request(system, generation, through: int) -> StructuralRebuildRequest:
    current = next(
        item
        for item in system.projections.generations(FAMILY_ID, proof=proof())
        if item.generation_id == generation.generation_id
    )
    return StructuralRebuildRequest(
        generation_id=generation.generation_id,
        expected_authority_version=current.authority_aggregate_version,
        through_ledger_seq=through,
        reason_code="B3_TOMBSTONE_REBUILD",
        idempotency_key="b3-tombstone-rebuild",
    )


def _read(system, generation_id, history: TombstonedStructuralHistory):
    original = _canonical_id(
        history.source_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE_ID,
    )
    deletion = _canonical_id(
        history.tombstone_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE_ID,
    )
    tombstone_event = _canonical_id(
        history.tombstone_event,
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT_ID,
    )
    return original, system.structural.read(
        StructuralReadRequest(
            generation_id,
            (original, deletion, tombstone_event),
            FIXED_NOW,
            limit=100,
        ),
        proof=proof(),
    )


def _assert_non_resurrection(history, original_id: str, response) -> None:
    assert original_id not in {item.canonical_id for item in response.graph.nodes}
    assert all(
        item.object_admission_id != str(history.admission_id)
        for item in response.graph.relations
    )
    marker = [
        item
        for item in response.graph.relations
        if item.source_event_type == "governed_blob.deletion.tombstoned"
    ]
    assert len(marker) == 1
    assert marker[0].relation_type is ProjectionRelationType.PROJECTED_FROM_EVENT
    assert marker[0].source_event_id == history.tombstone_event.event_id
    assert marker[0].payload_digest == history.tombstone_event.payload_digest


def test_tombstone_removes_covered_state_and_survives_wipe_rebuild_and_promotion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    commands, schemas, history = create_tombstoned_structural_history(
        database,
        tmp_path / "objects",
    )
    adapter = MemoryNeo4jAdapter()
    system = open_b2_system(
        database,
        adapter,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        generation = _register_generation(system)
        request = _rebuild_request(
            system,
            generation,
            history.tombstone_event.ledger_seq,
        )
        first = system.structural.rebuild(request, proof=proof())
        assert first.recorded_delivery_count == 2
        original_id, initial = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, initial)
        assert (str(generation.generation_id), history.source_event.ledger_seq) not in (
            adapter.deliveries
        )

        adapter.deliveries.clear()
        replay = system.structural.rebuild(request, proof=proof())
        assert replay.authority_command_replayed is True
        assert replay.reapplied_delivery_count == 2
        original_id, rebuilt = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, rebuilt)

        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation.generation_id
        )
        graph_digest = digest_canonical(
            {
                "nodes": [item.canonical_id for item in rebuilt.graph.nodes],
                "relations": [item.relation_key for item in rebuilt.graph.relations],
            }
        )
        validation = system.projections.validate_generation(
            ProjectionGenerationValidationRequest(
                current.generation_id,
                current.authority_aggregate_version,
                rebuilt.metadata.contiguous_ledger_seq,
                SERVICE_DIGEST,
                graph_digest,
                "B3_TOMBSTONE_VALIDATE",
                "b3-tombstone-validate",
            ),
            proof=proof(),
        )
        validating = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation.generation_id
        )
        promotion = system.projections.promote_generation(
            ProjectionGenerationPromotionRequest(
                validating.generation_id,
                validating.authority_aggregate_version,
                validation.checkpoint_ledger_seq,
                validation.validation_digest,
                "B3_TOMBSTONE_PROMOTE",
                "b3-tombstone-promote",
            ),
            proof=proof(),
        )
        assert promotion.generation.state.value == "ACTIVE"
        original_id, promoted = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, promoted)
    finally:
        system.close()
''',
)

# Actual Neo4j proof, using the same retained SQLite/object history.
append_once(
    "newsroom/tests/test_projection_b3_neo4j_service.py",
    "test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
    '''def test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild(
    tmp_path: Path,
) -> None:
    from newsroom.projection import ProjectionIdentitySource, ProjectionNodeType

    from .projection_b3_tombstone_helpers import (
        create_tombstoned_structural_history,
    )

    config = _service_config()
    authority_path = tmp_path / "authority.sqlite3"
    commands, schemas, history = create_tombstoned_structural_history(
        authority_path,
        tmp_path / "objects",
    )
    generation_id: ProjectionGenerationId | None = None
    request: StructuralRebuildRequest | None = None

    def canonical(event, node_type, identity_source):
        return canonical_node_id(
            type(
                "Binding",
                (),
                {
                    "node_type": node_type,
                    "identity_source": identity_source,
                    "payload_field": None,
                },
            )(),
            StructuralIdentityContext(
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_version=event.aggregate_version,
                event_id=event.event_id,
                payload_id=event.payload_id,
                payload={},
            ),
        )

    original_id = canonical(
        history.source_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE_ID,
    )
    deletion_id = canonical(
        history.tombstone_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE_ID,
    )
    tombstone_event_id = canonical(
        history.tombstone_event,
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT_ID,
    )
    canonical_ids = (original_id, deletion_id, tombstone_event_id)

    system = open_b2_service_system(
        authority_path,
        config,
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        _register(system)
        generation = _create_generation(system, suffix="tombstone")
        generation_id = generation.generation_id
        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation_id
        )
        request = StructuralRebuildRequest(
            generation_id=generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=history.tombstone_event.ledger_seq,
            reason_code="B3_ACTUAL_SERVICE_TOMBSTONE",
            idempotency_key="b3-service-tombstone-rebuild",
        )
        first = system.structural.rebuild(request, proof=proof())
        assert first.recorded_delivery_count == 2
        initial = _read(system, generation_id, canonical_ids)
        assert original_id not in {item.canonical_id for item in initial.graph.nodes}
        assert all(
            item.object_admission_id != str(history.admission_id)
            for item in initial.graph.relations
        )
        assert any(
            item.source_event_type == "governed_blob.deletion.tombstoned"
            for item in initial.graph.relations
        )
    finally:
        system.close()

    assert generation_id is not None
    assert request is not None
    try:
        _cleanup(config, generation_id)
        restarted = open_b2_service_system(
            authority_path,
            config,
            command_registry=commands,
            payload_schema_registry=schemas,
        )
        try:
            replay = restarted.structural.rebuild(request, proof=proof())
            assert replay.authority_command_replayed is True
            assert replay.reapplied_delivery_count == 2
            rebuilt = _read(restarted, generation_id, canonical_ids)
            assert original_id not in {
                item.canonical_id for item in rebuilt.graph.nodes
            }
            assert all(
                item.object_admission_id != str(history.admission_id)
                for item in rebuilt.graph.relations
            )
            assert any(
                item.source_event_type == "governed_blob.deletion.tombstoned"
                for item in rebuilt.graph.relations
            )
        finally:
            restarted.close()
    finally:
        _cleanup(config, generation_id)
''',
)

# Permanent service gate and SDLC graph-free optional topology now include the
# third actual-service proof.
replace_once(
    ".github/workflows/projection-b2-neo4j.yml",
    '''          if len(rebuild) < 2:
              raise SystemExit(
                  f"expected at least 2 B3 actual-service tests, found {len(rebuild)}"
              )
''',
    '''          if len(rebuild) < 3:
              raise SystemExit(
                  f"expected at least 3 B3 actual-service tests, found {len(rebuild)}"
              )
''',
)
replace_once(
    "scripts/sdlc/workflow_lane.py",
    '''    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
)
''',
    '''    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
    "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
)
''',
)
replace_once(
    "newsroom/tests/test_sdlc_workflow_lane.py",
    '''        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
    )
''',
    '''        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_graph_loss_and_process_restart_rebuild_from_authority",
        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_rebuild_cleanup_cannot_cross_generation_namespace",
        "newsroom.tests.test_projection_b3_neo4j_service::test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
    )
''',
)
