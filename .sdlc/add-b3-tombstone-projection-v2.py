from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    value = target.read_text(encoding="utf-8")
    if value.count(old) != 1:
        raise SystemExit(f"replacement mismatch: {path}: {old[:80]!r}")
    target.write_text(value.replace(old, new), encoding="utf-8")


def insert_before(path: str, marker: str, insertion: str) -> None:
    target = Path(path)
    value = target.read_text(encoding="utf-8")
    if value.count(marker) != 1:
        raise SystemExit(f"insertion mismatch: {path}: {marker[:80]!r}")
    target.write_text(value.replace(marker, insertion + marker), encoding="utf-8")


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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


# The authoritative tombstone itself remains visible as deletion/event provenance.
insert_before(
    "newsroom/projection/mapping.py",
    "    )\n    contract = StructuralMappingContract(\n",
    '''        StructuralEventMapping(
            "governed_blob.deletion.tombstoned",
            True,
            (
                _node(
                    "deletion",
                    ProjectionNodeType.AUTHORITY_AGGREGATE,
                    ProjectionIdentitySource.AGGREGATE,
                ),
                _node(
                    "event",
                    ProjectionNodeType.LEDGER_EVENT,
                    ProjectionIdentitySource.EVENT,
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
''',
)

# Resolve the exact historical object admissions covered by a retained tombstone.
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
''',
)

# The batch digest binds the exact sorted deletion scope.
replace_once(
    "newsroom/projection/neo4j/models.py",
    "from newsroom.authority.types import EventId, TrustScope, UtcTimestamp, require_token\n",
    "from newsroom.authority.types import (\n    EventId,\n    ObjectAdmissionId,\n    TrustScope,\n    UtcTimestamp,\n    require_token,\n)\n",
)
replace_once(
    "newsroom/projection/neo4j/models.py",
    '''    nodes: tuple[StructuralNode, ...]
    relations: tuple[StructuralRelation, ...]

    def __post_init__(self) -> None:
''',
    '''    nodes: tuple[StructuralNode, ...]
    relations: tuple[StructuralRelation, ...]
    tombstoned_object_admission_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
''',
)
replace_once(
    "newsroom/projection/neo4j/models.py",
    '''        validate_sha256_digest(self.source_event_digest, field="source_event_digest")
        if not isinstance(self.nodes, tuple) or not self.nodes:
''',
    '''        validate_sha256_digest(self.source_event_digest, field="source_event_digest")
        if (
            not isinstance(self.tombstoned_object_admission_ids, tuple)
            or len(self.tombstoned_object_admission_ids) > 1024
        ):
            raise ProjectionContractError(
                "tombstoned object admission identities must be a bounded tuple"
            )
        try:
            tombstoned = tuple(
                str(ObjectAdmissionId.parse(item))
                for item in self.tombstoned_object_admission_ids
            )
        except (TypeError, ValueError) as exc:
            raise ProjectionContractError(
                "tombstoned object admission identity is invalid"
            ) from exc
        if tombstoned != tuple(sorted(set(tombstoned))):
            raise ProjectionContractError(
                "tombstoned object admission identities must be sorted and unique"
            )
        if bool(tombstoned) != (
            self.source_event_type == "governed_blob.deletion.tombstoned"
        ):
            raise ProjectionContractError(
                "tombstone deletion scope must match the authoritative event type"
            )
        object.__setattr__(
            self, "tombstoned_object_admission_ids", tombstoned
        )
        if not isinstance(self.nodes, tuple) or not self.nodes:
''',
)
replace_once(
    "newsroom/projection/neo4j/models.py",
    '''                    for item in self.relations
                ],
            }
''',
    '''                    for item in self.relations
                ],
                "tombstoned_object_admission_ids": list(
                    self.tombstoned_object_admission_ids
                ),
            }
''',
)
replace_once(
    "newsroom/authority/_neo4j_projection_system.py",
    '''        relations=tuple(
            sorted(relations, key=lambda value: value.relation_key)
        ),
    )
''',
    '''        relations=tuple(
            sorted(relations, key=lambda value: value.relation_key)
        ),
        tombstoned_object_admission_ids=(
            source.tombstoned_object_admission_ids
        ),
    )
''',
)

# Fixed, parameterised tombstone cleanup runs in the same Neo4j transaction as
# the authoritative tombstone marker and delivery marker.
insert_before(
    "newsroom/projection/neo4j/_adapter.py",
    "_NODE_PROPERTY_KEYS = frozenset(\n",
    '''_TOMBSTONE_RELATIONS_QUERY = """
MATCH (source:NewsroomProjectionNode {generation_id: $generation_id})
      -[relation]->
      (target:NewsroomProjectionNode {generation_id: $generation_id})
WHERE relation.generation_id = $generation_id
  AND type(relation) IN $relation_types
  AND relation.object_admission_id IN $object_admission_ids
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


''',
)
replace_once(
    "newsroom/projection/neo4j/_adapter.py",
    '''    def _apply_transaction(transaction: Any, batch: StructuralBatch) -> Neo4jApplyOutcome:
        delivery_properties = _delivery_properties(batch)
        existing_delivery = transaction.run(
''',
    '''    def _apply_transaction(transaction: Any, batch: StructuralBatch) -> Neo4jApplyOutcome:
        delivery_properties = _delivery_properties(batch)
        _apply_tombstone_cleanup(transaction, batch)
        existing_delivery = transaction.run(
''',
)
insert_before(
    "newsroom/projection/neo4j/_adapter.py",
    "def _open_neo4j_adapter(config: Neo4jProjectorConfig) -> _Neo4jAdapter:\n",
    '''def _apply_tombstone_cleanup(transaction: Any, batch: StructuralBatch) -> None:
    if not batch.tombstoned_object_admission_ids:
        return
    record = transaction.run(
        _TOMBSTONE_RELATIONS_QUERY,
        {
            "generation_id": str(batch.generation_id),
            "relation_types": [item.value for item in ProjectionRelationType],
            "object_admission_ids": list(
                batch.tombstoned_object_admission_ids
            ),
        },
    ).single()
    if record is None:
        raise Neo4jIdentityConflict(
            "Neo4j tombstone cleanup returned no exact relation state"
        )
    try:
        relation_keys = tuple(
            sorted({str(item) for item in (record["relation_keys"] or [])})
        )
        canonical_ids = tuple(
            sorted({str(item) for item in (record["canonical_ids"] or [])})
        )
        int(record["deleted_count"])
    except Exception:
        raise Neo4jIdentityConflict(
            "Neo4j tombstone cleanup returned malformed relation state"
        ) from None
    if relation_keys:
        identities = transaction.run(
            _TOMBSTONE_RELATION_IDENTITIES_QUERY,
            {
                "generation_id": str(batch.generation_id),
                "relation_keys": list(relation_keys),
            },
        ).single()
        if identities is None or int(identities["deleted_count"]) != len(
            relation_keys
        ):
            raise Neo4jIdentityConflict(
                "Neo4j tombstone relation identity state is incomplete"
            )
    if canonical_ids:
        orphans = transaction.run(
            _TOMBSTONE_ORPHAN_NODES_QUERY,
            {
                "generation_id": str(batch.generation_id),
                "canonical_ids": list(canonical_ids),
            },
        ).single()
        if orphans is None:
            raise Neo4jIdentityConflict(
                "Neo4j tombstone orphan cleanup returned no exact state"
            )


''',
)

# A retained governed-object history is shared by memory and actual-service proofs.
create_once(
    "newsroom/tests/projection_b3_tombstone_helpers.py",
    '''from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newsroom.authority import (
    AggregateId,
    CommandDefinition,
    CommandRegistry,
    ObjectAdmissionDescriptor,
    ObjectAdmissionId,
    ObjectAdmissionPayload,
    PayloadGoldenVector,
    PayloadMode,
    PayloadSchemaContract,
    PayloadSchemaRegistry,
    PayloadSchemaValidationError,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    canonical_json_bytes,
)
from newsroom.authority._neo4j_projection_system import _open_with_adapter
from newsroom.authority.neo4j_projection_system import (
    open_neo4j_projection_authority_system,
)
from newsroom.authority.object_policy import merge_authority_registries
from newsroom.authority.persistence import LedgerEventRecord
from newsroom.projection.neo4j import (
    Neo4jApplyResult,
    Neo4jProjectorConfig,
    StructuralBatch,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_event_helpers import payload_schemas
from .projection_b1_helpers import (
    event_read_policy,
    projection_contracts,
    projection_read_policy,
    proof,
    source_command_registry,
)
from .projection_b2_helpers import MemoryNeo4jAdapter


@dataclass(frozen=True, slots=True)
class TombstonedStructuralHistory:
    admission_id: ObjectAdmissionId
    blob_digest: str
    source_event: LedgerEventRecord
    tombstone_event: LedgerEventRecord


class TombstoneMemoryNeo4jAdapter(MemoryNeo4jAdapter):
    def apply(self, batch: StructuralBatch) -> Neo4jApplyResult:
        if batch.tombstoned_object_admission_ids:
            covered = set(batch.tombstoned_object_admission_ids)
            for key, prior in tuple(self.deliveries.items()):
                if key[0] != str(batch.generation_id):
                    continue
                if any(
                    relation.object_admission_id in covered
                    for relation in prior.relations
                ):
                    del self.deliveries[key]
        return super().apply(batch)


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
        canonicalizer_implementation_version=(
            "projection-object-canonicalizer-v1"
        ),
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


def tombstone_registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    contract = _object_contract()
    definition = CommandDefinition(
        command_type="record.object_versioned",
        definition_version="projection-object-command-v1",
        aggregate_type="fixture_aggregate",
        event_type="authority.aggregate.versioned",
        event_schema_version=1,
        payload_mode=PayloadMode.OBJECT_ADMISSION,
        payload_schema_version=contract.schema_version,
        payload_schema_contract_version=contract.contract_version,
        payload_schema_contract_digest=contract.contract_digest,
        payload_canonicalizer_version=(
            contract.canonicalizer_implementation_version
        ),
        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="source.short",
        required_scope="authority.observed.write",
        required_object_class="source_capture",
        required_allowed_use="project.discovery",
    )
    commands = CommandRegistry(
        (*source_command_registry().definitions(), definition)
    )
    schemas = PayloadSchemaRegistry(
        (*payload_schemas().contracts(), contract)
    )
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
        events = system.events.after(0, limit=1000, proof=proof())
        source_event = next(
            item for item in events if item.event_id == str(committed.event_id)
        )
        tombstone_event = next(
            item for item in events if item.event_id == str(tombstone.event_id)
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


def _scopes() -> frozenset[str]:
    policy = event_read_policy()
    return frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            policy.required_scope,
            "authority.projection.manage",
            "authority.projection.write",
            "authority.projection.read",
        }
    )


def open_tombstone_memory_system(
    path: Path,
    adapter: TombstoneMemoryNeo4jAdapter,
    commands: CommandRegistry,
    schemas: PayloadSchemaRegistry,
):
    policy = event_read_policy()
    return _open_with_adapter(
        path=path,
        registry=commands,
        payload_schemas=schemas,
        contracts=projection_contracts(),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={"principal.alpha": _scopes()},
        ),
        event_read_policy=policy,
        projection_read_policy=projection_read_policy(),
        adapter=adapter,
    )


def open_tombstone_service_system(
    path: Path,
    config: Neo4jProjectorConfig,
    commands: CommandRegistry,
    schemas: PayloadSchemaRegistry,
):
    policy = event_read_policy()
    return open_neo4j_projection_authority_system(
        path=path,
        registry=commands,
        payload_schemas=schemas,
        contracts=projection_contracts(),
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal("principal.alpha")},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={"principal.alpha": _scopes()},
        ),
        event_read_policy=policy,
        projection_read_policy=projection_read_policy(),
        neo4j_config=config,
    )
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
    StructuralNodeBinding,
    canonical_node_id,
)
from newsroom.projection.neo4j import (
    StructuralReadRequest,
    StructuralRebuildRequest,
)

from .authority_helpers import FIXED_NOW
from .projection_b1_helpers import FAMILY_ID, proof
from .projection_b3_tombstone_helpers import (
    TombstoneMemoryNeo4jAdapter,
    TombstonedStructuralHistory,
    create_tombstoned_structural_history,
    open_tombstone_memory_system,
)


SERVICE_DIGEST = digest_canonical(
    {"neo4j_server": "2026.06.0", "edition": "community", "driver": "6.2.0"}
)


def _canonical_id(event, node_type, identity_source) -> str:
    return canonical_node_id(
        StructuralNodeBinding("fixture", node_type, identity_source),
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


def _read(system, generation_id, history: TombstonedStructuralHistory):
    original = _canonical_id(
        history.source_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    deletion = _canonical_id(
        history.tombstone_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    event = _canonical_id(
        history.tombstone_event,
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT,
    )
    return original, system.structural.read(
        StructuralReadRequest(
            generation_id,
            (original, deletion, event),
            FIXED_NOW,
            limit=100,
        ),
        proof=proof(),
    )


def _assert_non_resurrection(history, original_id: str, response) -> None:
    assert original_id not in {item.canonical_id for item in response.nodes}
    assert all(
        item.object_admission_id != str(history.admission_id)
        for item in response.relations
    )
    marker = [
        item
        for item in response.relations
        if item.source_event_type == "governed_blob.deletion.tombstoned"
    ]
    assert len(marker) == 1
    assert marker[0].relation_type is ProjectionRelationType.PROJECTED_FROM_EVENT
    assert marker[0].source_event_id == history.tombstone_event.event_id


def test_tombstone_survives_wipe_rebuild_duplicate_and_promotion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    commands, schemas, history = create_tombstoned_structural_history(
        database,
        tmp_path / "objects",
    )
    adapter = TombstoneMemoryNeo4jAdapter()
    system = open_tombstone_memory_system(
        database,
        adapter,
        commands,
        schemas,
    )
    try:
        generation = _register_generation(system)
        current = next(
            item
            for item in system.projections.generations(FAMILY_ID, proof=proof())
            if item.generation_id == generation.generation_id
        )
        request = StructuralRebuildRequest(
            generation_id=generation.generation_id,
            expected_authority_version=current.authority_aggregate_version,
            through_ledger_seq=history.tombstone_event.ledger_seq,
            reason_code="B3_TOMBSTONE_REBUILD",
            idempotency_key="b3-tombstone-rebuild",
        )
        first = system.structural.rebuild(request, proof=proof())
        assert first.recorded_delivery_count == 2
        original_id, initial = _read(system, generation.generation_id, history)
        _assert_non_resurrection(history, original_id, initial)

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
        state_digest = digest_canonical(
            {
                "nodes": [item.canonical_id for item in rebuilt.nodes],
                "relations": [item.relation_key for item in rebuilt.relations],
            }
        )
        validation = system.projections.validate_generation(
            ProjectionGenerationValidationRequest(
                current.generation_id,
                current.authority_aggregate_version,
                rebuilt.metadata.contiguous_ledger_seq,
                SERVICE_DIGEST,
                state_digest,
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

append_once(
    "newsroom/tests/test_projection_b3_neo4j_service.py",
    "test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild",
    '''def test_actual_service_tombstone_does_not_resurrect_after_wipe_rebuild(
    tmp_path: Path,
) -> None:
    from newsroom.projection import (
        ProjectionIdentitySource,
        ProjectionNodeType,
        StructuralNodeBinding,
    )
    from .projection_b3_tombstone_helpers import (
        create_tombstoned_structural_history,
        open_tombstone_service_system,
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
            StructuralNodeBinding("fixture", node_type, identity_source),
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
        ProjectionIdentitySource.AGGREGATE,
    )
    deletion_id = canonical(
        history.tombstone_event,
        ProjectionNodeType.AUTHORITY_AGGREGATE,
        ProjectionIdentitySource.AGGREGATE,
    )
    tombstone_event_id = canonical(
        history.tombstone_event,
        ProjectionNodeType.LEDGER_EVENT,
        ProjectionIdentitySource.EVENT,
    )
    canonical_ids = (original_id, deletion_id, tombstone_event_id)

    system = open_tombstone_service_system(
        authority_path,
        config,
        commands,
        schemas,
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
        assert original_id not in {item.canonical_id for item in initial.nodes}
        assert all(
            item.object_admission_id != str(history.admission_id)
            for item in initial.relations
        )
        assert any(
            item.source_event_type == "governed_blob.deletion.tombstoned"
            for item in initial.relations
        )
    finally:
        system.close()

    assert generation_id is not None
    assert request is not None
    try:
        _cleanup(config, generation_id)
        restarted = open_tombstone_service_system(
            authority_path,
            config,
            commands,
            schemas,
        )
        try:
            replay = restarted.structural.rebuild(request, proof=proof())
            assert replay.authority_command_replayed is True
            assert replay.reapplied_delivery_count == 2
            rebuilt = _read(restarted, generation_id, canonical_ids)
            assert original_id not in {
                item.canonical_id for item in rebuilt.nodes
            }
            assert all(
                item.object_admission_id != str(history.admission_id)
                for item in rebuilt.relations
            )
            assert any(
                item.source_event_type == "governed_blob.deletion.tombstoned"
                for item in rebuilt.relations
            )
        finally:
            restarted.close()
    finally:
        _cleanup(config, generation_id)
''',
)

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
