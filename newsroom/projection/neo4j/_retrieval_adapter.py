from __future__ import annotations

from collections.abc import Callable, Mapping
import math
import time
from threading import RLock
from typing import Any

from newsroom.authority.canonical import digest_canonical, validate_sha256_digest
from newsroom.authority.types import TrustScope
from newsroom.projection.complete import CompleteProjectionProfile
from newsroom.projection.fixture_v2_projection import IntegratedFixtureV2Projection
from newsroom.projection.neo4j.complete_models import (
    CompleteGenerationNames,
    CompleteProjectionIdentity,
)
from newsroom.projection.neo4j.models import (
    NEO4J_B2_DRIVER_VERSION,
    NEO4J_B2_SERVER_VERSION,
    Neo4jCompatibilityError,
    Neo4jConnectionError,
    Neo4jIdentityConflict,
    Neo4jProjectorConfig,
    Neo4jReadError,
)
from newsroom.relations.models import RelationRecordType
from newsroom.retrieval.fixture_v2 import IntegratedFixtureV2RetrievalContract
from newsroom.retrieval.models import (
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalBranchHit,
    RetrievalContractError,
    RetrievalStateError,
    canonical_score,
)
from newsroom.retrieval.policy import HybridRetrievalPolicy

from ._adapter import (
    _COMPONENT_QUERY,
    _neo4j_unit_of_work_factory,
    _open_neo4j_driver,
)
from ._complete_adapter import _require_generation_contracts


_EXACT_QUERY_TEMPLATE = """
MATCH (document:`%s`)
WHERE document.generation_id = $generation_id
  AND document.revision_id IN $revision_ids
RETURN document.passage_id AS passage_id,
       document.revision_id AS source_identity,
       1.0 AS score
ORDER BY passage_id
LIMIT $limit
"""

_ADMITTED_GRAPH_QUERY_TEMPLATE = """
MATCH (source:NewsroomAdmittedRelationEndpoint {
  generation_id: $generation_id,
  record_type: $record_type,
  record_id: $query_hypothesis_version_id
})
CALL {
  WITH source
  MATCH path=(source)-[:DEVELOPMENT_OF*1..2]->(target:NewsroomAdmittedRelationEndpoint)
  WHERE target.generation_id = $generation_id
    AND target.record_type = $record_type
    AND all(
      relation IN relationships(path)
      WHERE relation.generation_id = $generation_id
        AND relation.predicate = 'DEVELOPMENT_OF'
        AND relation.trust_scope = 'ADMITTED'
    )
  RETURN path, target
  ORDER BY length(path), target.record_id
  LIMIT $fanout
}
RETURN target.record_id AS target_id,
       [relation IN relationships(path) | relation.relation_key] AS relation_keys,
       length(path) AS depth,
       1.0 / toFloat(length(path)) AS score
ORDER BY depth, target_id
LIMIT $limit
"""

_FULLTEXT_QUERY = """
CALL db.index.fulltext.queryNodes($index_name, $query, {limit: $limit})
YIELD node, score
WHERE node.generation_id = $generation_id
RETURN node.passage_id AS passage_id, score
ORDER BY score DESC, passage_id
LIMIT $limit
"""

_VECTOR_QUERY = """
CALL db.index.vector.queryNodes($index_name, $limit, $vector)
YIELD node, score
WHERE node.generation_id = $generation_id
RETURN node.passage_id AS passage_id, score
ORDER BY score DESC, passage_id
LIMIT $limit
"""

_QUERY_IDS: Mapping[RetrievalBranch, str] = {
    RetrievalBranch.EXACT: "fixture-exact-prior-revision",
    RetrievalBranch.ADMITTED_GRAPH: "fixture-admitted-development",
}


class _HybridRetrievalNeo4jAdapter:
    """Private fixed-query adapter for the one bounded Increment 2C tool."""

    __slots__ = (
        "_driver",
        "_config",
        "_closed",
        "_lock",
        "_monotonic_ns",
        "_unit_of_work",
    )

    def __init__(
        self,
        *,
        driver: Any,
        config: Neo4jProjectorConfig,
        driver_version: str,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        unit_of_work_factory: Callable[..., Callable] | None = None,
    ) -> None:
        if not isinstance(config, Neo4jProjectorConfig):
            raise TypeError("retrieval Neo4j configuration must be typed")
        if driver_version != NEO4J_B2_DRIVER_VERSION:
            raise Neo4jConnectionError(
                "Neo4j retrieval driver is not the exact qualified version"
            )
        self._driver = driver
        self._config = config
        self._closed = False
        self._lock = RLock()
        if not callable(monotonic_ns):
            raise TypeError("retrieval monotonic clock must be callable")
        if unit_of_work_factory is None:
            unit_of_work_factory = _neo4j_unit_of_work_factory()
        if not callable(unit_of_work_factory):
            raise TypeError("retrieval unit-of-work factory must be callable")
        self._monotonic_ns = monotonic_ns
        self._unit_of_work = unit_of_work_factory

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._driver.close()

    def _require_open(self) -> None:
        if self._closed:
            raise Neo4jConnectionError("Neo4j retrieval adapter is closed")

    def _execute_bounded_read(
        self,
        session: Any,
        callback: Callable[[Any], list[Any]],
        *,
        policy: HybridRetrievalPolicy,
        branch: RetrievalBranch | str,
        branch_started_ns: int,
        deadline_ns: int,
    ) -> list[Any]:
        remaining_timeout_seconds = _remaining_timeout_seconds(
            branch_started_ns=branch_started_ns,
            deadline_ns=deadline_ns,
        )
        managed = self._unit_of_work(
            timeout=remaining_timeout_seconds,
            metadata={
                "newsroom_tool": policy.tool_name,
                "newsroom_branch": (
                    branch.value
                    if isinstance(branch, RetrievalBranch)
                    else branch
                ),
            },
        )(callback)
        return list(session.execute_read(managed))

    def _verify_live_compatibility(
        self,
        session: Any,
        *,
        policy: HybridRetrievalPolicy,
        deadline_ns: int,
    ) -> None:
        started_ns = self._monotonic_ns()
        rows = self._execute_bounded_read(
            session,
            lambda transaction: list(transaction.run(_COMPONENT_QUERY, {})),
            policy=policy,
            branch="COMPATIBILITY",
            branch_started_ns=started_ns,
            deadline_ns=deadline_ns,
        )
        completed_ns = self._monotonic_ns()
        _bounded_branch_elapsed_ms(
            started_ns=started_ns,
            completed_ns=completed_ns,
            deadline_ns=deadline_ns,
        )
        if len(rows) != 1:
            raise Neo4jCompatibilityError(
                "Neo4j retrieval service did not identify one component"
            )
        row = rows[0]
        try:
            version = str(row["version"])
            edition = str(row["edition"]).lower()
        except Exception:
            raise Neo4jCompatibilityError(
                "Neo4j retrieval service returned malformed compatibility metadata"
            ) from None
        if version != NEO4J_B2_SERVER_VERSION or edition != "community":
            raise Neo4jCompatibilityError(
                "Neo4j retrieval service is not the exact qualified target"
            )

    def run_bounded_hybrid_branches(
        self,
        *,
        identity: CompleteProjectionIdentity,
        fixture: IntegratedFixtureV2Projection,
        retrieval_contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
    ) -> tuple[RetrievalBranchExecution, ...]:
        with self._lock:
            return self._run_bounded_hybrid_branches_locked(
                identity=identity,
                fixture=fixture,
                retrieval_contract=retrieval_contract,
                policy=policy,
                query_digest=query_digest,
            )

    def _run_bounded_hybrid_branches_locked(
        self,
        *,
        identity: CompleteProjectionIdentity,
        fixture: IntegratedFixtureV2Projection,
        retrieval_contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
    ) -> tuple[RetrievalBranchExecution, ...]:
        self._require_open()
        if not isinstance(fixture, IntegratedFixtureV2Projection):
            raise TypeError("hybrid retrieval fixture must be typed")
        if not isinstance(
            retrieval_contract, IntegratedFixtureV2RetrievalContract
        ):
            raise TypeError("hybrid retrieval contract must be typed")
        if not isinstance(policy, HybridRetrievalPolicy):
            raise TypeError("hybrid retrieval policy must be typed")
        validate_sha256_digest(query_digest, field="hybrid_retrieval_query_digest")
        if retrieval_contract.policy_digest != policy.contract_digest:
            raise RetrievalContractError(
                "hybrid retrieval contract differs from the selected policy"
            )
        if (
            retrieval_contract.projection_fixture_digest
            != fixture.manifest_digest
        ):
            raise RetrievalContractError(
                "hybrid retrieval fixture differs from projection authority"
            )

        names = _require_generation_contracts(
            identity,
            fulltext=fixture.fulltext_contract,
            vector=fixture.vector_contract,
            profile=CompleteProjectionProfile.FIXTURE_QUALIFICATION,
        )
        started_ns = self._monotonic_ns()
        deadline_ns = started_ns + policy.timeout_ms * 1_000_000
        try:
            with self._driver.session(database=self._config.database) as session:
                self._verify_live_compatibility(
                    session,
                    policy=policy,
                    deadline_ns=deadline_ns,
                )
                executions = (
                    self._execute_exact(
                        session,
                        identity=identity,
                        names=names,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                        deadline_ns=deadline_ns,
                    ),
                    self._execute_graph(
                        session,
                        identity=identity,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                        deadline_ns=deadline_ns,
                    ),
                    self._execute_fulltext(
                        session,
                        identity=identity,
                        names=names,
                        fixture=fixture,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                        deadline_ns=deadline_ns,
                    ),
                    self._execute_vector(
                        session,
                        identity=identity,
                        names=names,
                        fixture=fixture,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                        deadline_ns=deadline_ns,
                    ),
                )
        except (
            Neo4jCompatibilityError,
            Neo4jIdentityConflict,
            Neo4jReadError,
            RetrievalContractError,
            RetrievalStateError,
        ):
            raise
        except Exception:
            raise Neo4jReadError(
                "Neo4j bounded hybrid retrieval failed"
            ) from None

        completed_ns = self._monotonic_ns()
        _elapsed_ms(started_ns, completed_ns)
        if completed_ns > deadline_ns:
            raise Neo4jReadError(
                "Neo4j bounded hybrid retrieval exceeded the server-owned timeout"
            )
        if tuple(item.branch for item in executions) != policy.required_branches:
            raise RetrievalStateError(
                "bounded hybrid retrieval did not execute all required branches"
            )
        return executions

    def _execute_exact(
        self,
        session: Any,
        *,
        identity: CompleteProjectionIdentity,
        names: CompleteGenerationNames,
        contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
        deadline_ns: int,
    ) -> RetrievalBranchExecution:
        branch = RetrievalBranch.EXACT
        query_id = _QUERY_IDS[branch]
        started_ns = self._monotonic_ns()
        query = _exact_query(names)
        rows = self._execute_bounded_read(
            session,
            lambda transaction: list(
                transaction.run(
                    query,
                    {
                        "generation_id": str(identity.generation_id),
                        "revision_ids": [contract.prior_revision_id],
                        "limit": policy.branch_result_limit,
                    },
                )
            ),
            policy=policy,
            branch=branch,
            branch_started_ns=started_ns,
            deadline_ns=deadline_ns,
        )
        hits = tuple(
            self._document_hit(
                branch=branch,
                query_id=query_id,
                query_digest=query_digest,
                rank=rank,
                row=row,
                contract=contract,
                source_kind="GOVERNED_REVISION",
                source_identity_field="source_identity",
            )
            for rank, row in enumerate(rows, start=1)
        )
        completed_ns = self._monotonic_ns()
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_bounded_branch_elapsed_ms(
                started_ns=started_ns,
                completed_ns=completed_ns,
                deadline_ns=deadline_ns,
            ),
            hits=hits,
        )

    def _execute_graph(
        self,
        session: Any,
        *,
        identity: CompleteProjectionIdentity,
        contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
        deadline_ns: int,
    ) -> RetrievalBranchExecution:
        branch = RetrievalBranch.ADMITTED_GRAPH
        query_id = _QUERY_IDS[branch]
        started_ns = self._monotonic_ns()
        rows = self._execute_bounded_read(
            session,
            lambda transaction: list(
                transaction.run(
                    _ADMITTED_GRAPH_QUERY_TEMPLATE,
                    {
                        "generation_id": str(identity.generation_id),
                        "record_type": (
                            RelationRecordType.EVENT_HYPOTHESIS_VERSION.value
                        ),
                        "query_hypothesis_version_id": (
                            contract.query_hypothesis_version_id
                        ),
                        "fanout": policy.relation_fanout,
                        "limit": policy.branch_result_limit,
                    },
                )
            ),
            policy=policy,
            branch=branch,
            branch_started_ns=started_ns,
            deadline_ns=deadline_ns,
        )
        hits: list[RetrievalBranchHit] = []
        for rank, row in enumerate(rows, start=1):
            target_id = _row_text(row, "target_id")
            root = contract.root_by_dependency_id.get(target_id)
            if root is None:
                raise Neo4jIdentityConflict(
                    "admitted graph result has no checked fixture dependency root"
                )
            depth = _row_positive_int(row, "depth", maximum=policy.graph_depth)
            relation_keys = row.get("relation_keys")
            if (
                not isinstance(relation_keys, list)
                or len(relation_keys) != depth
                or any(not isinstance(item, str) or not item for item in relation_keys)
            ):
                raise Neo4jIdentityConflict(
                    "admitted graph result has malformed relation evidence"
                )
            for relation_key in relation_keys:
                validate_sha256_digest(
                    relation_key, field="retrieval_relation_key"
                )
            relation_identity = (
                relation_keys[0]
                if len(relation_keys) == 1
                else digest_canonical({"relation_keys": relation_keys})
            )
            raw_score = _row_score(row, branch=branch)
            if not math.isclose(
                raw_score,
                1.0 / depth,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise Neo4jIdentityConflict(
                    "admitted graph result score differs from path depth"
                )
            hits.append(
                RetrievalBranchHit(
                    branch=branch,
                    query_id=query_id,
                    query_digest=query_digest,
                    rank=rank,
                    raw_score=canonical_score(raw_score),
                    result_key=f"{branch.value}:{target_id}",
                    dependency_root_id=root.root_id,
                    passage_id=None,
                    trust_scope=TrustScope.ADMITTED,
                    source_kind="RELATION_ASSERTION",
                    source_identity=relation_identity,
                )
            )
        completed_ns = self._monotonic_ns()
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_bounded_branch_elapsed_ms(
                started_ns=started_ns,
                completed_ns=completed_ns,
                deadline_ns=deadline_ns,
            ),
            hits=tuple(hits),
        )

    def _execute_fulltext(
        self,
        session: Any,
        *,
        identity: CompleteProjectionIdentity,
        names: CompleteGenerationNames,
        fixture: IntegratedFixtureV2Projection,
        contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
        deadline_ns: int,
    ) -> RetrievalBranchExecution:
        branch = RetrievalBranch.FULL_TEXT
        started_ns = self._monotonic_ns()
        query = next(
            item for item in fixture.fulltext_queries if item.language == "en-GB"
        )
        query_id = query.query_id
        rows = self._execute_bounded_read(
            session,
            lambda transaction: list(
                transaction.run(
                    _FULLTEXT_QUERY,
                    {
                        "index_name": names.fulltext_index_name,
                        "query": query.normalized_query,
                        "generation_id": str(identity.generation_id),
                        "limit": policy.branch_result_limit,
                    },
                )
            ),
            policy=policy,
            branch=branch,
            branch_started_ns=started_ns,
            deadline_ns=deadline_ns,
        )
        hits = tuple(
            self._document_hit(
                branch=branch,
                query_id=query_id,
                query_digest=query_digest,
                rank=rank,
                row=row,
                contract=contract,
                source_kind="GOVERNED_PASSAGE",
            )
            for rank, row in enumerate(rows, start=1)
        )
        completed_ns = self._monotonic_ns()
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_bounded_branch_elapsed_ms(
                started_ns=started_ns,
                completed_ns=completed_ns,
                deadline_ns=deadline_ns,
            ),
            hits=hits,
        )

    def _execute_vector(
        self,
        session: Any,
        *,
        identity: CompleteProjectionIdentity,
        names: CompleteGenerationNames,
        fixture: IntegratedFixtureV2Projection,
        contract: IntegratedFixtureV2RetrievalContract,
        policy: HybridRetrievalPolicy,
        query_digest: str,
        deadline_ns: int,
    ) -> RetrievalBranchExecution:
        branch = RetrievalBranch.VECTOR
        started_ns = self._monotonic_ns()
        query = fixture.vector_queries[0]
        query_id = query.query_id
        source = fixture.document_by_id[query.passage_id]
        vector = fixture.vector_contract.vector_from_components(source.components)
        rows = self._execute_bounded_read(
            session,
            lambda transaction: list(
                transaction.run(
                    _VECTOR_QUERY,
                    {
                        "index_name": names.vector_index_name,
                        "vector": list(vector),
                        "generation_id": str(identity.generation_id),
                        "limit": policy.branch_result_limit,
                    },
                )
            ),
            policy=policy,
            branch=branch,
            branch_started_ns=started_ns,
            deadline_ns=deadline_ns,
        )
        hits = tuple(
            self._document_hit(
                branch=branch,
                query_id=query_id,
                query_digest=query_digest,
                rank=rank,
                row=row,
                contract=contract,
                source_kind="GOVERNED_PASSAGE",
            )
            for rank, row in enumerate(rows, start=1)
        )
        completed_ns = self._monotonic_ns()
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_bounded_branch_elapsed_ms(
                started_ns=started_ns,
                completed_ns=completed_ns,
                deadline_ns=deadline_ns,
            ),
            hits=hits,
        )

    @staticmethod
    def _document_hit(
        *,
        branch: RetrievalBranch,
        query_id: str,
        query_digest: str,
        rank: int,
        row: Mapping[str, object],
        contract: IntegratedFixtureV2RetrievalContract,
        source_kind: str,
        source_identity_field: str | None = None,
    ) -> RetrievalBranchHit:
        passage_id = _row_text(row, "passage_id")
        root = contract.root_by_passage_id.get(passage_id)
        if root is None:
            raise Neo4jIdentityConflict(
                "retrieval document result has no checked fixture dependency root"
            )
        source_identity = (
            passage_id
            if source_identity_field is None
            else _row_text(row, source_identity_field)
        )
        return RetrievalBranchHit(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            rank=rank,
            raw_score=canonical_score(_row_score(row, branch=branch)),
            result_key=f"{branch.value}:{passage_id}",
            dependency_root_id=root.root_id,
            passage_id=passage_id,
            trust_scope=TrustScope.OBSERVED,
            source_kind=source_kind,
            source_identity=source_identity,
        )


def _exact_query(names: CompleteGenerationNames) -> str:
    if not isinstance(names, CompleteGenerationNames):
        raise TypeError("exact retrieval names must be typed")
    return _EXACT_QUERY_TEMPLATE % names.document_label


def _row_text(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value:
        raise Neo4jIdentityConflict(f"retrieval row lacks {field}")
    return value


def _row_positive_int(
    row: Mapping[str, object], field: str, *, maximum: int
) -> int:
    value = row.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > maximum
    ):
        raise Neo4jIdentityConflict(f"retrieval row has invalid {field}")
    return value


def _row_score(
    row: Mapping[str, object],
    *,
    branch: RetrievalBranch,
) -> float:
    value = row.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Neo4jIdentityConflict("retrieval row has invalid score")
    score = float(value)
    if not math.isfinite(score) or score < 0:
        raise Neo4jIdentityConflict("retrieval row has invalid score")
    if branch is RetrievalBranch.EXACT and score != 1.0:
        raise Neo4jIdentityConflict("exact retrieval row has invalid score")
    if branch is RetrievalBranch.ADMITTED_GRAPH and not 0.0 < score <= 1.0:
        raise Neo4jIdentityConflict("graph retrieval row has invalid score")
    if branch is RetrievalBranch.VECTOR and score > 1.0:
        raise Neo4jIdentityConflict("vector retrieval row has invalid score")
    return score


def _remaining_timeout_seconds(
    *,
    branch_started_ns: int,
    deadline_ns: int,
) -> float:
    if (
        isinstance(branch_started_ns, bool)
        or not isinstance(branch_started_ns, int)
        or isinstance(deadline_ns, bool)
        or not isinstance(deadline_ns, int)
    ):
        raise RetrievalStateError(
            "retrieval monotonic deadline is not an integer nanosecond value"
        )
    remaining_ns = deadline_ns - branch_started_ns
    if remaining_ns <= 0:
        raise Neo4jReadError(
            "Neo4j bounded hybrid retrieval exhausted the server-owned timeout"
        )
    return remaining_ns / 1_000_000_000


def _bounded_branch_elapsed_ms(
    *,
    started_ns: int,
    completed_ns: int,
    deadline_ns: int,
) -> int:
    elapsed_ms = _elapsed_ms(started_ns, completed_ns)
    if completed_ns > deadline_ns:
        raise Neo4jReadError(
            "Neo4j bounded hybrid retrieval exceeded the server-owned timeout"
        )
    return elapsed_ms


def _elapsed_ms(started_ns: int, completed_ns: int) -> int:
    if (
        isinstance(started_ns, bool)
        or not isinstance(started_ns, int)
        or isinstance(completed_ns, bool)
        or not isinstance(completed_ns, int)
        or completed_ns < started_ns
    ):
        raise RetrievalStateError("retrieval monotonic clock moved backwards")
    return (completed_ns - started_ns) // 1_000_000


def _open_hybrid_retrieval_neo4j_adapter(
    config: Neo4jProjectorConfig,
) -> _HybridRetrievalNeo4jAdapter:
    driver, driver_version = _open_neo4j_driver(config)
    return _HybridRetrievalNeo4jAdapter(
        driver=driver,
        config=config,
        driver_version=driver_version,
    )


__all__ = [
    "_HybridRetrievalNeo4jAdapter",
    "_open_hybrid_retrieval_neo4j_adapter",
]
