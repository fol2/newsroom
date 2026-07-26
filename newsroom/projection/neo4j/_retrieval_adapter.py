from __future__ import annotations

from collections.abc import Callable, Mapping
import math
import time
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

from ._adapter import _open_neo4j_driver
from ._complete_adapter import _CompleteNeo4jAdapter, _require_generation_contracts


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


class _HybridRetrievalNeo4jAdapter(_CompleteNeo4jAdapter):
    """Private fixed-query adapter for the one bounded Increment 2C tool."""

    __slots__ = ("_monotonic_ns", "_unit_of_work")

    def __init__(
        self,
        *,
        driver: Any,
        config: Neo4jProjectorConfig,
        driver_version: str,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        unit_of_work_factory: Callable[..., Callable] | None = None,
    ) -> None:
        super().__init__(
            driver=driver,
            config=config,
            driver_version=driver_version,
        )
        if not callable(monotonic_ns):
            raise TypeError("retrieval monotonic clock must be callable")
        if unit_of_work_factory is None:
            from neo4j import unit_of_work

            unit_of_work_factory = unit_of_work
        if not callable(unit_of_work_factory):
            raise TypeError("retrieval unit-of-work factory must be callable")
        self._monotonic_ns = monotonic_ns
        self._unit_of_work = unit_of_work_factory

    def _execute_bounded_read(
        self,
        session: Any,
        callback: Callable[[Any], list[Any]],
        *,
        policy: HybridRetrievalPolicy,
        branch: RetrievalBranch,
    ) -> list[Any]:
        managed = self._unit_of_work(
            timeout=policy.timeout_ms / 1000.0,
            metadata={
                "newsroom_tool": policy.tool_name,
                "newsroom_branch": branch.value,
            },
        )(callback)
        return list(session.execute_read(managed))

    def run_bounded_hybrid_branches(
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
        try:
            with self._driver.session(database=self._config.database) as session:
                executions = (
                    self._execute_exact(
                        session,
                        identity=identity,
                        names=names,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                    ),
                    self._execute_graph(
                        session,
                        identity=identity,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                    ),
                    self._execute_fulltext(
                        session,
                        identity=identity,
                        names=names,
                        fixture=fixture,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                    ),
                    self._execute_vector(
                        session,
                        identity=identity,
                        names=names,
                        fixture=fixture,
                        contract=retrieval_contract,
                        policy=policy,
                        query_digest=query_digest,
                    ),
                )
        except (Neo4jIdentityConflict, RetrievalContractError, RetrievalStateError):
            raise
        except Exception:
            raise Neo4jReadError(
                "Neo4j bounded hybrid retrieval failed"
            ) from None

        elapsed_ms = _elapsed_ms(started_ns, self._monotonic_ns())
        if elapsed_ms > policy.timeout_ms:
            raise RetrievalStateError(
                "bounded hybrid retrieval exceeded the server-owned timeout"
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
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_elapsed_ms(started_ns, self._monotonic_ns()),
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
            hits.append(
                RetrievalBranchHit(
                    branch=branch,
                    query_id=query_id,
                    query_digest=query_digest,
                    rank=rank,
                    raw_score=canonical_score(_row_score(row)),
                    result_key=f"{branch.value}:{target_id}",
                    dependency_root_id=root.root_id,
                    passage_id=None,
                    trust_scope=TrustScope.ADMITTED,
                    source_kind="RELATION_ASSERTION",
                    source_identity=relation_identity,
                )
            )
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_elapsed_ms(started_ns, self._monotonic_ns()),
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
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_elapsed_ms(started_ns, self._monotonic_ns()),
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
        return RetrievalBranchExecution(
            branch=branch,
            query_id=query_id,
            query_digest=query_digest,
            result_limit=policy.branch_result_limit,
            elapsed_ms=_elapsed_ms(started_ns, self._monotonic_ns()),
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
            raw_score=canonical_score(_row_score(row)),
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


def _row_score(row: Mapping[str, object]) -> float:
    value = row.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Neo4jIdentityConflict("retrieval row has invalid score")
    score = float(value)
    if not math.isfinite(score) or score < 0:
        raise Neo4jIdentityConflict("retrieval row has invalid score")
    return score


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
