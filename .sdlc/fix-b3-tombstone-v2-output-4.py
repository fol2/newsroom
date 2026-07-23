from __future__ import annotations

from pathlib import Path


adapter = Path("newsroom/projection/neo4j/_adapter.py")
value = adapter.read_text(encoding="utf-8")
old = '''    def _apply_transaction(transaction: Any, batch: StructuralBatch) -> Neo4jApplyOutcome:
        delivery_properties = _delivery_properties(batch)
        _apply_tombstone_cleanup(transaction, batch)
        existing_delivery = transaction.run(
            _FIND_DELIVERY_QUERY,
            {
                "generation_id": str(batch.generation_id),
                "ledger_seq": batch.ledger_seq,
            },
        ).single()
        if existing_delivery is not None:
            _require_exact_properties(
                _record_mapping(existing_delivery, "properties"),
                delivery_properties,
                allowed_keys=_DELIVERY_PROPERTY_KEYS,
                identity="Neo4j delivery marker",
            )
            return Neo4jApplyOutcome.DUPLICATE

        node_by_id = {item.canonical_id: item for item in batch.nodes}
'''
new = '''    def _apply_transaction(transaction: Any, batch: StructuralBatch) -> Neo4jApplyOutcome:
        delivery_properties = _delivery_properties(batch)
        existing_delivery = transaction.run(
            _FIND_DELIVERY_QUERY,
            {
                "generation_id": str(batch.generation_id),
                "ledger_seq": batch.ledger_seq,
            },
        ).single()
        if existing_delivery is not None:
            _require_exact_properties(
                _record_mapping(existing_delivery, "properties"),
                delivery_properties,
                allowed_keys=_DELIVERY_PROPERTY_KEYS,
                identity="Neo4j delivery marker",
            )
            _apply_tombstone_cleanup(transaction, batch)
            return Neo4jApplyOutcome.DUPLICATE

        _apply_tombstone_cleanup(transaction, batch)
        node_by_id = {item.canonical_id: item for item in batch.nodes}
'''
if value.count(old) != 1:
    raise SystemExit("Neo4j tombstone delivery-fence replacement mismatch")
adapter.write_text(value.replace(old, new), encoding="utf-8")

helper = Path("newsroom/tests/projection_b3_tombstone_helpers.py")
value = helper.read_text(encoding="utf-8")
old = '''class TombstoneMemoryNeo4jAdapter(MemoryNeo4jAdapter):
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
'''
new = '''class TombstoneMemoryNeo4jAdapter(MemoryNeo4jAdapter):
    def apply(self, batch: StructuralBatch) -> Neo4jApplyResult:
        key = (str(batch.generation_id), batch.ledger_seq)
        if key in self.deliveries:
            result = super().apply(batch)
            self._apply_tombstone_cleanup(batch)
            return result
        self._apply_tombstone_cleanup(batch)
        return super().apply(batch)

    def _apply_tombstone_cleanup(self, batch: StructuralBatch) -> None:
        if not batch.tombstoned_object_admission_ids:
            return
        covered = set(batch.tombstoned_object_admission_ids)
        for key, prior in tuple(self.deliveries.items()):
            if key[0] != str(batch.generation_id):
                continue
            if any(
                relation.object_admission_id in covered
                for relation in prior.relations
            ):
                del self.deliveries[key]
'''
if value.count(old) != 1:
    raise SystemExit("memory tombstone delivery-fence replacement mismatch")
helper.write_text(value.replace(old, new), encoding="utf-8")

test = Path("newsroom/tests/test_projection_b3_tombstone.py")
value = test.read_text(encoding="utf-8")
old_import = '''from pathlib import Path

from newsroom.authority import digest_canonical
'''
new_import = '''from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import digest_canonical
'''
if value.count(old_import) != 1:
    raise SystemExit("tombstone adversarial import replacement mismatch")
value = value.replace(old_import, new_import)
old_import = '''from newsroom.projection.neo4j import (
    StructuralReadRequest,
    StructuralRebuildRequest,
)
'''
new_import = '''from newsroom.projection.neo4j import (
    Neo4jIdentityConflict,
    StructuralReadRequest,
    StructuralRebuildRequest,
)
'''
if value.count(old_import) != 1:
    raise SystemExit("tombstone identity-conflict import replacement mismatch")
value = value.replace(old_import, new_import)
old_import = '''from .projection_b1_helpers import FAMILY_ID, proof
'''
new_import = '''from .projection_b1_helpers import FAMILY_ID, proof
from .projection_b2_helpers import structural_batch
'''
if value.count(old_import) != 1:
    raise SystemExit("tombstone structural-batch import replacement mismatch")
value = value.replace(old_import, new_import)
append = '''

def test_tombstone_duplicate_repairs_but_conflict_has_no_destructive_effect() -> None:
    admission_id = "00000000-0000-4000-8000-000000000123"
    generation_id = ProjectionGenerationId.new()
    source = structural_batch(
        generation_id=generation_id,
        ledger_seq=1,
        object_admission_id=admission_id,
    )
    raw_marker = structural_batch(
        generation_id=generation_id,
        ledger_seq=2,
    )
    marker_relations = tuple(
        replace(
            item,
            source_event_type="governed_blob.deletion.tombstoned",
        )
        for item in raw_marker.relations
    )
    marker = replace(
        raw_marker,
        source_event_type="governed_blob.deletion.tombstoned",
        relations=marker_relations,
        tombstoned_object_admission_ids=(admission_id,),
    )
    adapter = TombstoneMemoryNeo4jAdapter()
    adapter.apply(source)
    adapter.apply(marker)
    source_key = (str(generation_id), 1)
    marker_key = (str(generation_id), 2)
    assert source_key not in adapter.deliveries
    assert marker_key in adapter.deliveries

    adapter.deliveries[source_key] = source
    duplicate = adapter.apply(marker)
    assert duplicate.outcome.value == "DUPLICATE"
    assert source_key not in adapter.deliveries

    adapter.deliveries[source_key] = source
    conflict_digest = digest_canonical({"conflict": "tombstone-delivery"})
    conflict = replace(
        marker,
        source_event_digest=conflict_digest,
        relations=tuple(
            replace(item, source_event_digest=conflict_digest)
            for item in marker.relations
        ),
    )
    with pytest.raises(Neo4jIdentityConflict):
        adapter.apply(conflict)
    assert source_key in adapter.deliveries
    assert adapter.deliveries[marker_key] == marker
'''
if "test_tombstone_duplicate_repairs_but_conflict_has_no_destructive_effect" in value:
    raise SystemExit("tombstone adversarial test already exists")
test.write_text(value.rstrip() + append, encoding="utf-8")
