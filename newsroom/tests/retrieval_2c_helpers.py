from __future__ import annotations

import atexit
from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
import tempfile
from threading import RLock
from typing import Callable

from newsroom.authority import (
    AggregateId,
    InlinePayload,
    ObjectLimits,
    SemanticCommand,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    digest_canonical,
)
from newsroom.authority._retrieval_system import _open_hybrid_retrieval_with_adapter
from newsroom.projection import (
    CompleteProjectionProfile,
    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
    ProjectionGenerationPromotionRequest,
    ProjectionGenerationState,
    ProjectionGenerationTransitionRequest,
)
from newsroom.projection.neo4j import (
    CompleteDeliveryRequest,
    CompleteGenerationQualificationRequest,
    CompleteGenerationValidationRequest,
)
from newsroom.retrieval import (
    INTEGRATED_FIXTURE_V2_RETRIEVAL,
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    canonical_score,
)
from newsroom.projection import INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.relations import INTEGRATED_FIXTURE_V2

from .authority_a2b_helpers import _policy_registries
from .authority_event_helpers import payload_schemas
from .complete_projection_2b_helpers import (
    COMPLETE_NOW,
    MemoryCompleteNeo4jAdapter,
    complete_contract_registry,
    complete_scopes,
    open_complete_test_system,
    proof,
    register_complete_generation,
    seed_complete_fixture_authority,
)
from .projection_b1_helpers import source_command_registry
from .test_complete_projection_2b_authority import _current, _rebuild


_ACTIVE_TEMPLATE_LOCK = RLock()
_ACTIVE_TEMPLATE_ROOT: Path | None = None
_ACTIVE_TEMPLATE: tuple[Path, Path] | None = None


def _cleanup_active_template() -> None:
    global _ACTIVE_TEMPLATE_ROOT, _ACTIVE_TEMPLATE
    with _ACTIVE_TEMPLATE_LOCK:
        root = _ACTIVE_TEMPLATE_ROOT
        _ACTIVE_TEMPLATE = None
        _ACTIVE_TEMPLATE_ROOT = None
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


atexit.register(_cleanup_active_template)


def _active_template() -> tuple[Path, Path]:
    global _ACTIVE_TEMPLATE_ROOT, _ACTIVE_TEMPLATE
    with _ACTIVE_TEMPLATE_LOCK:
        if _ACTIVE_TEMPLATE is not None:
            return _ACTIVE_TEMPLATE
        _ACTIVE_TEMPLATE_ROOT = Path(
            tempfile.mkdtemp(prefix="newsroom-retrieval-2c-active-")
        )
        database = _ACTIVE_TEMPLATE_ROOT / "authority.sqlite3"
        object_root = _ACTIVE_TEMPLATE_ROOT / "objects"
        seed_complete_fixture_authority(database, object_root=object_root)
        complete_adapter = MemoryCompleteNeo4jAdapter()
        system = open_complete_test_system(
            database,
            object_root=object_root,
            adapter=complete_adapter,
        )
        try:
            generation = register_complete_generation(system)
            rebuilt = _rebuild(system, generation, database)
            current = _current(system, generation.generation_id)
            validation = system.complete.validate_generation(
                CompleteGenerationValidationRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        current.authority_aggregate_version
                    ),
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    reason_code="INCREMENT_2C_ACTIVE_TEMPLATE_VALIDATE",
                    idempotency_key="retrieval-2c-template-validate",
                ),
                proof=proof(),
            )
            system.complete.qualify_generation(
                CompleteGenerationQualificationRequest(
                    generation_id=generation.generation_id,
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
                ),
                proof=proof(),
            )
            current = _current(system, generation.generation_id)
            system.projections.promote_generation(
                ProjectionGenerationPromotionRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        current.authority_aggregate_version
                    ),
                    checkpoint_ledger_seq=rebuilt.checkpoint_ledger_seq,
                    validation_digest=validation.validation_digest,
                    reason_code="INCREMENT_2C_ACTIVE_TEMPLATE_PROMOTE",
                    idempotency_key="retrieval-2c-template-promote",
                ),
                proof=proof(),
            )
        finally:
            system.close()
        _ACTIVE_TEMPLATE = (database, object_root)
        return _ACTIVE_TEMPLATE


def seed_active_retrieval_authority(
    database: Path,
    *,
    object_root: Path,
) -> None:
    template_database, template_objects = _active_template()
    if database.exists() or database.is_symlink():
        raise FileExistsError(database)
    if object_root.exists() or object_root.is_symlink():
        raise FileExistsError(object_root)
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(template_database) as source, sqlite3.connect(database) as target:
            source.backup(target)
        database.chmod(0o600)
        shutil.copytree(
            template_objects,
            object_root,
            copy_function=shutil.copy2,
        )
    except Exception:
        database.unlink(missing_ok=True)
        shutil.rmtree(object_root, ignore_errors=True)
        raise


def append_retrieval_source_event(
    database: Path,
    *,
    object_root: Path,
    key: str = "retrieval-2c-stale-source",
) -> None:
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=MemoryCompleteNeo4jAdapter(),
    )
    try:
        system.commands.execute(
            SemanticCommand(
                command_type="source.item.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload(
                    {"headline": "Increment 2C source advance", "count": 1}
                ),
                idempotency_key=key,
            ),
            proof=proof(),
        )
    finally:
        system.close()


def block_active_retrieval_generation(
    database: Path,
    *,
    object_root: Path,
    dead_letter: bool,
) -> None:
    adapter = MemoryCompleteNeo4jAdapter(fail_writes=True)
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=adapter,
    )
    try:
        status = system.projections.status(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        system.commands.execute(
            SemanticCommand(
                command_type="source.item.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload(
                    {
                        "headline": "Increment 2C blocked source",
                        "count": 1,
                    }
                ),
                idempotency_key=(
                    "retrieval-2c-dead-letter-source"
                    if dead_letter
                    else "retrieval-2c-gap-source"
                ),
            ),
            proof=proof(),
        )
        target = system.events.after(0, limit=1000, proof=proof())[-1]
        attempts = 3 if dead_letter else 1
        for attempt in range(1, attempts + 1):
            generation = next(
                item
                for item in system.projections.generations(
                    INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
                    proof=proof(),
                )
                if item.generation_id == status.generation_id
            )
            system.complete.deliver(
                CompleteDeliveryRequest(
                    generation_id=generation.generation_id,
                    expected_authority_version=(
                        generation.authority_aggregate_version
                    ),
                    ledger_seq=target.ledger_seq,
                    idempotency_key=(
                        f"retrieval-2c-blocked-delivery-{dead_letter}-{attempt}"
                    ),
                ),
                proof=proof(),
            )
    finally:
        system.close()


def retire_active_retrieval_generation(
    database: Path,
    *,
    object_root: Path,
) -> None:
    system = open_complete_test_system(
        database,
        object_root=object_root,
        adapter=MemoryCompleteNeo4jAdapter(),
    )
    try:
        status = system.projections.status(
            INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
            proof=proof(),
        )
        generation = next(
            item
            for item in system.projections.generations(
                INTEGRATED_FIXTURE_V2_COMPLETE_FAMILY_ID,
                proof=proof(),
            )
            if item.generation_id == status.generation_id
        )
        system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                generation_id=generation.generation_id,
                expected_authority_version=(
                    generation.authority_aggregate_version
                ),
                target_state=ProjectionGenerationState.RETIRED,
                reason_code="INCREMENT_2C_NO_ACTIVE_GENERATION",
                idempotency_key="retrieval-2c-retire-active-generation",
                validated_through_ledger_seq=(
                    generation.validated_through_ledger_seq
                ),
            ),
            proof=proof(),
        )
    finally:
        system.close()


@dataclass
class MemoryHybridRetrievalAdapter:
    failure: Exception | None = None
    on_execute: Callable[[], None] | None = None
    include_exclusions: bool = True

    def __post_init__(self) -> None:
        self.call_count = 0
        self.closed = False
        self.last_query_digest: str | None = None

    def run_bounded_hybrid_branches(
        self,
        *,
        identity,
        fixture,
        retrieval_contract,
        policy,
        query_digest: str,
    ) -> tuple[RetrievalBranchExecution, ...]:
        self.call_count += 1
        self.last_query_digest = query_digest
        if self.on_execute is not None:
            self.on_execute()
        if self.failure is not None:
            raise self.failure
        candidate_root = (
            f"candidate:{retrieval_contract.prior_candidate_version_id}"
        )
        relation = INTEGRATED_FIXTURE_V2.relation
        relation_key = digest_canonical(
            {
                "subject": relation.subject.canonical_value(),
                "predicate": relation.predicate.value,
                "object": relation.object.canonical_value(),
                "temporal_scope": relation.temporal_scope.canonical_value(),
            }
        )
        query_ids = {
            RetrievalBranch.EXACT: "fixture-exact-prior-revision",
            RetrievalBranch.ADMITTED_GRAPH: "fixture-admitted-development",
            RetrievalBranch.FULL_TEXT: next(
                item.query_id
                for item in INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_queries
                if item.language == "en-GB"
            ),
            RetrievalBranch.VECTOR: retrieval_contract.vector_query_id,
        }
        executions: list[RetrievalBranchExecution] = []
        for branch in RetrievalBranch:
            query_id = query_ids[branch]
            candidate = RetrievalBranchHit(
                branch=branch,
                query_id=query_id,
                query_digest=query_digest,
                rank=1,
                raw_score=canonical_score(1.0),
                result_key=(
                    f"{branch.value}:{retrieval_contract.prior_hypothesis_version_id}"
                    if branch is RetrievalBranch.ADMITTED_GRAPH
                    else f"{branch.value}:ifv2-prior-en"
                ),
                dependency_root_id=candidate_root,
                passage_id=(
                    None
                    if branch is RetrievalBranch.ADMITTED_GRAPH
                    else "ifv2-prior-en"
                ),
                trust_scope=(
                    TrustScope.ADMITTED
                    if branch is RetrievalBranch.ADMITTED_GRAPH
                    else TrustScope.OBSERVED
                ),
                source_kind=(
                    "RELATION_ASSERTION"
                    if branch is RetrievalBranch.ADMITTED_GRAPH
                    else (
                        "GOVERNED_REVISION"
                        if branch is RetrievalBranch.EXACT
                        else "GOVERNED_PASSAGE"
                    )
                ),
                source_identity=(
                    relation_key
                    if branch is RetrievalBranch.ADMITTED_GRAPH
                    else (
                        retrieval_contract.prior_revision_id
                        if branch is RetrievalBranch.EXACT
                        else "ifv2-prior-en"
                    )
                ),
            )
            hits = [candidate]
            if self.include_exclusions and branch in {
                RetrievalBranch.FULL_TEXT,
                RetrievalBranch.VECTOR,
            }:
                hits.append(
                    RetrievalBranchHit(
                        branch=branch,
                        query_id=query_id,
                        query_digest=query_digest,
                        rank=2,
                        raw_score=canonical_score(0.5),
                        result_key=(
                            f"{branch.value}:ifv2-incompatible-formal-id"
                        ),
                        dependency_root_id=(
                            "distractor:incompatible-formal-id"
                        ),
                        passage_id="ifv2-incompatible-formal-id",
                        trust_scope=TrustScope.OBSERVED,
                        source_kind="GOVERNED_PASSAGE",
                        source_identity="ifv2-incompatible-formal-id",
                    )
                )
            executions.append(
                RetrievalBranchExecution(
                    branch=branch,
                    query_id=query_id,
                    query_digest=query_digest,
                    result_limit=policy.branch_result_limit,
                    elapsed_ms=1,
                    hits=tuple(hits),
                )
            )
        return tuple(executions)

    def close(self) -> None:
        self.closed = True


def object_limits() -> ObjectLimits:
    return ObjectLimits(
        global_max_bytes=1024 * 1024,
        class_max_bytes={"source_capture": 1024 * 1024},
        max_read_bytes=1024 * 1024,
        min_free_bytes=0,
        io_chunk_bytes=64,
        max_staging_bytes=1024 * 1024,
        max_range_bytes=1024 * 1024,
    )


def open_retrieval_test_system(
    database: Path,
    *,
    object_root: Path,
    adapter: MemoryHybridRetrievalAdapter | object,
    scopes: frozenset[str] | None = None,
    principal_id: str = "principal.alpha",
    clock: Callable = lambda: COMPLETE_NOW,
):
    rights, hydration, admissions = _policy_registries()
    selected_scopes = scopes or frozenset(
        {*complete_scopes(), "authority.retrieval.read"}
    )
    return _open_hybrid_retrieval_with_adapter(
        path=database,
        object_root=object_root,
        object_limits=object_limits(),
        registry=source_command_registry(),
        payload_schemas=payload_schemas(),
        contracts=complete_contract_registry(),
        admission_registry=admissions,
        rights_policies=rights,
        hydration_policies=hydration,
        authenticator=StaticAuthenticator(
            credentials={"token-1": StaticPrincipal(principal_id)},
            authority_domain="newsroom.authority",
        ),
        authorizer=StaticAuthorizer(
            policy_version="retrieval-2c-authz-v1",
            grants_by_principal={principal_id: selected_scopes},
        ),
        adapter=adapter,
        clock=clock,
    )


__all__ = [
    "MemoryHybridRetrievalAdapter",
    "append_retrieval_source_event",
    "block_active_retrieval_generation",
    "open_retrieval_test_system",
    "retire_active_retrieval_generation",
    "seed_active_retrieval_authority",
]
