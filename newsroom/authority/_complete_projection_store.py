from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from ._object_cas import _GovernedCAS
from ._projection_store import _ProjectionAuthorityStore
from ._relation_store import _RelationAuthorityStore
from .objects import BlobIdentity, ObjectLimits
from .persistence import AuthorityPersistenceError
from .types import EventId, ObjectAdmissionId, UtcTimestamp
from newsroom.projection import (
    CompleteProjectionContract,
    CompleteProjectionProfile,
    FixtureVectorManifestContract,
    FullTextIndexContract,
    INTEGRATED_FIXTURE_V2_PROJECTION,
    VectorIndexContract,
)
from newsroom.projection.models import (
    ProjectionContractError,
    ProjectionGenerationId,
    ProjectionStateError,
)
from newsroom.projection.neo4j.complete_models import (
    AdmittedRelationProjection,
    CompleteDerivativeType,
    CompleteProjectionBatch,
    CompleteProjectionDocument,
    CompleteProjectionIdentity,
    CompleteProjectionRemoval,
)
from newsroom.relations import INTEGRATED_FIXTURE_V2
from newsroom.relations.models import RelationProjectionAction


class _CompleteProjectionAuthorityStore(
    _RelationAuthorityStore,
    _ProjectionAuthorityStore,
):
    """SQLite/governed-object source for one complete derivative generation."""

    def __init__(
        self,
        path: Path,
        *,
        object_root: Path,
        object_limits: ObjectLimits,
        **kwargs: Any,
    ) -> None:
        if not isinstance(object_root, Path):
            raise TypeError("complete projection object root must be pathlib.Path")
        if not isinstance(object_limits, ObjectLimits):
            raise TypeError("complete projection object limits must be typed")
        self._complete_cas = _GovernedCAS(
            object_root,
            limits=object_limits,
            clock=kwargs.get("clock", UtcTimestamp.now),
        )
        super().__init__(path, **kwargs)

    def _migrate_or_validate(self) -> None:
        super()._migrate_or_validate()
        self._validate_complete_fixture_cas()

    def _validate_complete_fixture_cas(self) -> None:
        with self._lock:
            conn = self._connection
            for row in conn.execute(
                "SELECT * FROM integrated_fixture_v2_bindings ORDER BY recorded_at"
            ).fetchall():
                binding = self._binding_from_row(conn, row, replayed=False)
                manifest_current, _reason, _event = self._object_current_state(
                    conn,
                    str(binding.manifest_admission_id),
                    binding.manifest_blob_digest,
                    now=self._clock(),
                )
                if manifest_current:
                    manifest = self._read_governed_bytes(
                        conn,
                        binding.manifest_admission_id,
                        binding.manifest_blob_digest,
                    )
                    if manifest != INTEGRATED_FIXTURE_V2.canonical_bytes:
                        raise AuthorityPersistenceError(
                            "complete fixture manifest bytes differ from authority"
                        )
                passages = INTEGRATED_FIXTURE_V2.passage_by_id
                for item in binding.passage_objects:
                    passage = passages[item.passage_id]
                    current, _reason, _event = self._object_current_state(
                        conn,
                        str(item.admission_id),
                        item.blob_digest,
                        now=self._clock(),
                    )
                    if not current:
                        continue
                    data = self._read_governed_bytes(
                        conn,
                        item.admission_id,
                        item.blob_digest,
                    )
                    if data != passage.canonical_bytes:
                        raise AuthorityPersistenceError(
                            "complete fixture passage bytes differ from authority"
                        )

    def latest_complete_source_ledger_seq(self) -> int:
        """Return the exact non-projection authority source watermark.

        Complete rebuild and exact replay must not chase the projection-management
        events that they create themselves.  Source authority includes governed
        objects, relation decisions and other retained newsroom events.  Projection
        family, generation, rebuild, delivery, validation and promotion events remain
        ordered ledger history, and are still processed when they fall before a later
        source event, but they never extend the source cutoff on their own.
        """

        with self._lock:
            return int(
                self._connection.execute(
                    "SELECT COALESCE(MAX(ledger_seq),0) FROM ledger_events "
                    "WHERE security_scope NOT IN ('authority.projection','authority.candidate')"
                ).fetchone()[0]
            )

    def complete_projection_contracts(
        self,
        generation_id: ProjectionGenerationId,
    ) -> tuple[
        CompleteProjectionIdentity,
        CompleteProjectionContract,
        FullTextIndexContract,
        VectorIndexContract,
        FixtureVectorManifestContract,
    ]:
        if not isinstance(generation_id, ProjectionGenerationId):
            raise TypeError("complete projection generation identity must be typed")
        with self._lock:
            metadata = self.projection_generation_metadata(generation_id)
            digest = metadata.family.complete_projection_contract_digest
            registry = self._projection_contracts.complete_projections
            if digest is None or registry is None:
                raise ProjectionStateError(
                    "projection generation is not bound to a complete contract"
                )
            binding = self._connection.execute(
                "SELECT * FROM projection_generation_complete_bindings "
                "WHERE generation_id=?",
                (str(generation_id),),
            ).fetchone()
            if binding is None:
                raise AuthorityPersistenceError(
                    "complete generation lacks immutable contract binding"
                )
            contract = registry.complete(digest)
            fulltext = registry.fulltext(contract.fulltext_contract_digest)
            vector = registry.vector(contract.vector_contract_digest)
            manifest = registry.fixture_manifest(
                contract.fixture_vector_manifest_digest
            )
            if (
                str(binding["definition_digest"])
                != metadata.family.digest
                or str(binding["complete_contract_digest"])
                != contract.contract_digest
                or str(binding["fulltext_contract_digest"])
                != fulltext.contract_digest
                or str(binding["vector_contract_digest"])
                != vector.contract_digest
                or str(binding["fixture_vector_manifest_digest"])
                != manifest.manifest_digest
            ):
                raise AuthorityPersistenceError(
                    "complete generation binding differs from retained contracts"
                )
            fixture = INTEGRATED_FIXTURE_V2_PROJECTION
            if (
                contract.contract_digest
                != fixture.complete_contract.contract_digest
                or fulltext.contract_digest
                != fixture.fulltext_contract.contract_digest
                or vector.contract_digest
                != fixture.vector_contract.contract_digest
                or manifest.manifest_digest != fixture.manifest_digest
                or contract.source_fixture_digest
                != INTEGRATED_FIXTURE_V2.manifest_digest
            ):
                raise ProjectionContractError(
                    "complete generation differs from integrated_fixture_v2 authority"
                )
            vector.require_profile(CompleteProjectionProfile.FIXTURE_QUALIFICATION)
            identity = CompleteProjectionIdentity(
                generation_id=generation_id,
                family_id=metadata.family.family_id,
                family_definition_version=(
                    metadata.family.definition_version
                ),
                projector_version=metadata.family.projector_version,
                ontology_contract_digest=(
                    metadata.family.ontology_contract_digest
                ),
                mapping_contract_digest=metadata.family.mapping_contract_digest,
                complete_contract_digest=contract.contract_digest,
                fulltext_contract_digest=fulltext.contract_digest,
                vector_contract_digest=vector.contract_digest,
                fixture_vector_manifest_digest=manifest.manifest_digest,
            )
            return identity, contract, fulltext, vector, manifest

    def complete_projection_batch(
        self,
        generation_id: ProjectionGenerationId,
        ledger_seq: int,
        *,
        now: UtcTimestamp,
    ) -> CompleteProjectionBatch:
        if not isinstance(generation_id, ProjectionGenerationId):
            raise TypeError("complete projection generation identity must be typed")
        if isinstance(ledger_seq, bool) or not isinstance(ledger_seq, int) or ledger_seq <= 0:
            raise ValueError("complete projection ledger sequence must be positive")
        if not isinstance(now, UtcTimestamp):
            raise TypeError("complete projection source time must be typed")
        with self._lock:
            identity, _contract, fulltext, vector, manifest = (
                self.complete_projection_contracts(generation_id)
            )
            source = self.projection_delivery_source(generation_id, ledger_seq)
            structural_batch = self._complete_structural_batch(source)
            documents = self._complete_documents_for_source(
                self._connection,
                identity=identity,
                source=source,
                fulltext=fulltext,
                vector=vector,
                manifest=manifest,
                now=now,
            )
            relations, relation_removals = self._complete_relations_for_source(
                self._connection,
                identity=identity,
                source=source,
                now=now,
            )
            document_removals = self._complete_document_removals_for_source(
                self._connection,
                identity=identity,
                source=source,
                now=now,
            )
            return CompleteProjectionBatch(
                identity=identity,
                ledger_seq=ledger_seq,
                source_event_id=EventId.parse(source.event.event_id),
                source_event_digest=source.source_event_digest,
                structural_batch=structural_batch,
                documents=documents,
                relations=relations,
                removals=tuple(
                    sorted(
                        (*document_removals, *relation_removals),
                        key=lambda item: (
                            item.derivative_type.value,
                            item.stable_key,
                        ),
                    )
                ),
            )

    def complete_projection_batches(
        self,
        generation_id: ProjectionGenerationId,
        through_ledger_seq: int,
        *,
        now: UtcTimestamp,
    ) -> tuple[CompleteProjectionBatch, ...]:
        if (
            isinstance(through_ledger_seq, bool)
            or not isinstance(through_ledger_seq, int)
            or through_ledger_seq < 0
        ):
            raise ValueError("complete projection checkpoint must be non-negative")
        return tuple(
            self.complete_projection_batch(
                generation_id,
                ledger_seq,
                now=now,
            )
            for ledger_seq in range(1, through_ledger_seq + 1)
        )

    @staticmethod
    def _complete_structural_batch(source: Any):
        if source.mapping is None:
            return None
        # Import lazily so the authority store does not create a module cycle
        # with the public Neo4j composition layer.
        from ._neo4j_projection_system import _build_structural_batch

        return _build_structural_batch(source)

    def _complete_documents_for_source(
        self,
        conn: sqlite3.Connection,
        *,
        identity: CompleteProjectionIdentity,
        source: Any,
        fulltext: FullTextIndexContract,
        vector: VectorIndexContract,
        manifest: FixtureVectorManifestContract,
        now: UtcTimestamp,
    ) -> tuple[CompleteProjectionDocument, ...]:
        if source.event.event_type != "integrated.fixture.v2.bound":
            return ()
        row = conn.execute(
            "SELECT * FROM integrated_fixture_v2_bindings "
            "WHERE authority_event_id=?",
            (source.event.event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityPersistenceError(
                "complete fixture binding event lacks retained authority"
            )
        binding = self._binding_from_row(conn, row, replayed=False)
        manifest_current, _reason, _event = self._object_current_state(
            conn,
            str(binding.manifest_admission_id),
            binding.manifest_blob_digest,
            now=now,
        )
        if not manifest_current:
            return ()
        manifest_bytes = self._read_governed_bytes(
            conn,
            binding.manifest_admission_id,
            binding.manifest_blob_digest,
        )
        if manifest_bytes != INTEGRATED_FIXTURE_V2.canonical_bytes:
            raise AuthorityPersistenceError(
                "complete fixture manifest bytes differ from repository authority"
            )
        fixture_documents = INTEGRATED_FIXTURE_V2_PROJECTION.document_by_id
        manifest_documents = {
            item.passage_id: item for item in manifest.documents
        }
        passages = INTEGRATED_FIXTURE_V2.passage_by_id
        documents: list[CompleteProjectionDocument] = []
        for passage_object in binding.passage_objects:
            passage = passages[passage_object.passage_id]
            if passage.expected_lifecycle != "ACTIVE":
                continue
            current, _reason, _event = self._object_current_state(
                conn,
                str(passage_object.admission_id),
                passage_object.blob_digest,
                now=now,
            )
            if not current:
                continue
            data = self._read_governed_bytes(
                conn,
                passage_object.admission_id,
                passage_object.blob_digest,
            )
            try:
                text = data.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise AuthorityPersistenceError(
                    "complete fixture passage is not valid UTF-8"
                ) from exc
            if text != passage.text:
                raise AuthorityPersistenceError(
                    "complete fixture passage bytes differ from repository authority"
                )
            fixture_document = fixture_documents[passage.passage_id]
            normalized = fulltext.normalize(text)
            if fixture_document.normalized_text_digest != _text_digest(normalized):
                raise AuthorityPersistenceError(
                    "complete fixture normalized text differs from retained contract"
                )
            manifest_document = manifest_documents.get(passage.passage_id)
            if (
                manifest_document is None
                or manifest_document.vector_digest
                != fixture_document.vector_digest
                or manifest_document.components
                != fixture_document.components
                or manifest_document.blob_digest != passage.blob_digest
            ):
                raise AuthorityPersistenceError(
                    "complete fixture vector differs from retained manifest"
                )
            vector.vector_from_components(fixture_document.components)
            documents.append(
                CompleteProjectionDocument(
                    identity=identity,
                    passage_id=passage.passage_id,
                    admission_id=passage_object.admission_id,
                    blob_digest=passage_object.blob_digest,
                    language=passage.language,
                    revision_id=passage.revision_id,
                    retrieval_text=normalized,
                    normalized_text_digest=(
                        fixture_document.normalized_text_digest
                    ),
                    vector_components=fixture_document.components,
                    vector_digest=fixture_document.vector_digest,
                    vector_dimensions=vector.dimensions,
                    vector_component_scale=vector.component_scale,
                    source_event_id=binding.authority_event_id,
                    source_ledger_seq=binding.authority_ledger_seq,
                    recorded_at=binding.recorded_at,
                )
            )
        return tuple(sorted(documents, key=lambda item: item.passage_id))

    def _read_governed_bytes(
        self,
        conn: sqlite3.Connection,
        admission_id: ObjectAdmissionId,
        expected_blob_digest: str,
    ) -> bytes:
        row = conn.execute(
            "SELECT a.blob_digest,b.size_bytes FROM object_admissions a "
            "JOIN blob_identities b ON b.blob_digest=a.blob_digest "
            "WHERE a.admission_id=?",
            (str(admission_id),),
        ).fetchone()
        if row is None or str(row["blob_digest"]) != expected_blob_digest:
            raise AuthorityPersistenceError(
                "complete fixture governed object identity is missing"
            )
        identity = BlobIdentity(
            blob_digest=expected_blob_digest,
            size_bytes=int(row["size_bytes"]),
        )
        with self._complete_cas.pin(identity) as pinned:
            return self._complete_cas.read_range(
                pinned,
                offset=0,
                length=identity.size_bytes,
            )

    def _complete_relations_for_source(
        self,
        conn: sqlite3.Connection,
        *,
        identity: CompleteProjectionIdentity,
        source: Any,
        now: UtcTimestamp,
    ) -> tuple[
        tuple[AdmittedRelationProjection, ...],
        tuple[CompleteProjectionRemoval, ...],
    ]:
        events = self.projection_events_after(
            after_ledger_seq=source.event.ledger_seq - 1,
            now=now,
            limit=2000,
        )
        selected = tuple(
            item
            for item in events
            if item.source_ledger_seq == source.event.ledger_seq
        )
        relations: list[AdmittedRelationProjection] = []
        removals: list[CompleteProjectionRemoval] = []
        recorded_at = UtcTimestamp.parse(source.event.recorded_at)
        for event in selected:
            if str(event.source_event_id) != source.event.event_id:
                raise AuthorityPersistenceError(
                    "relation projection event differs from ledger source"
                )
            if event.action is RelationProjectionAction.REMOVE:
                removals.append(
                    CompleteProjectionRemoval(
                        identity=identity,
                        derivative_type=(
                            CompleteDerivativeType.ADMITTED_RELATION
                        ),
                        stable_key=event.relation_key,
                        source_event_id=event.source_event_id,
                        source_ledger_seq=event.source_ledger_seq,
                        reason_code=event.reason_code,
                        object_admission_ids=(
                            event.tombstone_object_admission_ids
                        ),
                    )
                )
                continue
            assertion = event.assertion
            if assertion is None:
                raise AuthorityPersistenceError(
                    "admitted relation projection event lacks assertion"
                )
            relations.append(
                AdmittedRelationProjection(
                    identity=identity,
                    assertion_id=assertion.assertion_id,
                    proposal_id=assertion.proposal_id,
                    admission_decision_id=assertion.admission_decision_id,
                    relation_key=assertion.relation_key,
                    subject=assertion.subject,
                    predicate=assertion.predicate,
                    object=assertion.object,
                    temporal_scope=assertion.temporal_scope,
                    evidence_objects=assertion.evidence_objects,
                    producer=assertion.producer,
                    statement=assertion.statement,
                    uncertainties=assertion.uncertainties,
                    proposal_digest=assertion.proposal_digest,
                    source_event_id=event.source_event_id,
                    source_ledger_seq=event.source_ledger_seq,
                    recorded_at=recorded_at,
                )
            )
        return (
            tuple(sorted(relations, key=lambda item: item.relation_key)),
            tuple(
                sorted(
                    removals,
                    key=lambda item: (
                        item.derivative_type.value,
                        item.stable_key,
                    ),
                )
            ),
        )

    def _complete_document_removals_for_source(
        self,
        conn: sqlite3.Connection,
        *,
        identity: CompleteProjectionIdentity,
        source: Any,
        now: UtcTimestamp,
    ) -> tuple[CompleteProjectionRemoval, ...]:
        rows = conn.execute(
            "SELECT * FROM integrated_fixture_v2_bindings ORDER BY recorded_at"
        ).fetchall()
        removals: dict[tuple[str, str], CompleteProjectionRemoval] = {}
        passages = INTEGRATED_FIXTURE_V2.passage_by_id
        for row in rows:
            binding = self._binding_from_row(conn, row, replayed=False)
            manifest_current, manifest_reason, manifest_event = (
                self._object_current_state(
                    conn,
                    str(binding.manifest_admission_id),
                    binding.manifest_blob_digest,
                    now=now,
                )
            )
            invalid: list[
                tuple[str, str, tuple[int, EventId], tuple[ObjectAdmissionId, ...]]
            ] = []
            if not manifest_current:
                if manifest_event is None:
                    raise ProjectionStateError(
                        "invalid fixture manifest lacks ordered lifecycle authority"
                    )
                invalid.extend(
                    (
                        item.passage_id,
                        manifest_reason,
                        manifest_event,
                        (binding.manifest_admission_id,),
                    )
                    for item in binding.passage_objects
                    if passages[item.passage_id].expected_lifecycle == "ACTIVE"
                )
            for item in binding.passage_objects:
                if passages[item.passage_id].expected_lifecycle != "ACTIVE":
                    continue
                current, reason, event = self._object_current_state(
                    conn,
                    str(item.admission_id),
                    item.blob_digest,
                    now=now,
                )
                if current:
                    continue
                if event is None:
                    raise ProjectionStateError(
                        "invalid fixture passage lacks ordered lifecycle authority"
                    )
                invalid.append(
                    (item.passage_id, reason, event, (item.admission_id,))
                )
            for passage_id, reason, event, object_ids in invalid:
                event_seq, event_id = event
                if event_seq != source.event.ledger_seq:
                    continue
                if str(event_id) != source.event.event_id:
                    raise AuthorityPersistenceError(
                        "fixture removal lifecycle event differs from ledger source"
                    )
                for derivative in (
                    CompleteDerivativeType.FULL_TEXT,
                    CompleteDerivativeType.VECTOR,
                ):
                    removal = CompleteProjectionRemoval(
                        identity=identity,
                        derivative_type=derivative,
                        stable_key=passage_id,
                        source_event_id=event_id,
                        source_ledger_seq=event_seq,
                        reason_code=reason,
                        object_admission_ids=tuple(
                            sorted(set(object_ids), key=str)
                        ),
                    )
                    removals[(derivative.value, passage_id)] = removal
        return tuple(removals[key] for key in sorted(removals))


def _text_digest(value: str) -> str:
    from .canonical import digest_bytes

    return digest_bytes(value.encode("utf-8"))


__all__ = ["_CompleteProjectionAuthorityStore"]
