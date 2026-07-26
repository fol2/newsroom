from __future__ import annotations

from dataclasses import dataclass
import json

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from newsroom.authority.types import TrustScope, UtcTimestamp
from newsroom.projection import INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.relations import (
    INTEGRATED_FIXTURE_V2,
    INTEGRATED_FIXTURE_V2_BINDING_ID,
    IntegratedFixtureV2BindingId,
    governed_relation_key,
)

from .models import (
    RetrievalBranch,
    RetrievalBranchExecution,
    RetrievalContractError,
    RetrievalExclusionReason,
)
from .policy import HYBRID_FIXTURE_POLICY_V1, HybridRetrievalPolicy


@dataclass(frozen=True, slots=True)
class FixtureDependencyRoot:
    root_id: str
    candidate_version_id: str | None
    dependency_ids: tuple[str, ...]
    passage_ids: tuple[str, ...]
    observed_at: UtcTimestamp
    exclusion_reason: RetrievalExclusionReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root_id, str) or not self.root_id:
            raise RetrievalContractError("fixture dependency root is invalid")
        for field_name in ("dependency_ids", "passage_ids"):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or value != tuple(sorted(set(value))):
                raise RetrievalContractError(
                    f"fixture {field_name} must be sorted and unique"
                )
        if not isinstance(self.observed_at, UtcTimestamp):
            raise RetrievalContractError(
                "fixture dependency observation time must be typed"
            )
        if self.candidate_version_id is None and self.exclusion_reason is None:
            raise RetrievalContractError(
                "non-candidate fixture roots require an exclusion reason"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "candidate_version_id": self.candidate_version_id,
            "dependency_ids": list(self.dependency_ids),
            "passage_ids": list(self.passage_ids),
            "observed_at": self.observed_at.to_text(),
            "exclusion_reason": (
                None if self.exclusion_reason is None else self.exclusion_reason.value
            ),
        }


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2RetrievalContract:
    contract_id: str
    contract_version: str
    source_fixture_digest: str
    projection_fixture_digest: str
    policy_digest: str
    fixture_id: str
    relation_fixture_binding_id: IntegratedFixtureV2BindingId
    canonical_process_id: str
    query_revision_id: str
    prior_revision_id: str
    query_valid_time: UtcTimestamp
    query_hypothesis_version_id: str
    prior_hypothesis_version_id: str
    prior_candidate_version_id: str
    fulltext_query_ids: tuple[str, ...]
    vector_query_id: str
    roots: tuple[FixtureDependencyRoot, ...]

    def __post_init__(self) -> None:
        if self.source_fixture_digest != INTEGRATED_FIXTURE_V2.manifest_digest:
            raise RetrievalContractError("retrieval source fixture digest differs")
        if self.projection_fixture_digest != INTEGRATED_FIXTURE_V2_PROJECTION.manifest_digest:
            raise RetrievalContractError("retrieval projection fixture digest differs")
        if self.policy_digest != HYBRID_FIXTURE_POLICY_V1.contract_digest:
            raise RetrievalContractError("retrieval fixture policy digest differs")
        if self.fixture_id != INTEGRATED_FIXTURE_V2.fixture_id:
            raise RetrievalContractError("retrieval fixture identity differs")
        if (
            not isinstance(
                self.relation_fixture_binding_id, IntegratedFixtureV2BindingId
            )
            or self.relation_fixture_binding_id
            != INTEGRATED_FIXTURE_V2_BINDING_ID
        ):
            raise RetrievalContractError(
                "retrieval relation fixture binding differs"
            )
        if (
            self.contract_id != "integrated_fixture_v2_retrieval"
            or self.contract_version != "integrated-fixture-v2-retrieval-v1"
        ):
            raise RetrievalContractError("retrieval fixture contract identity differs")
        source = json.loads(INTEGRATED_FIXTURE_V2.canonical_bytes)
        revisions = source["revisions"]
        hypotheses = source["event_hypotheses"]
        if self.canonical_process_id != str(
            source["formal_process"]["canonical_process_id"]
        ):
            raise RetrievalContractError("retrieval canonical process identity differs")
        if self.query_revision_id != str(revisions[-1]["source_revision_id"]):
            raise RetrievalContractError("retrieval query revision differs")
        if self.prior_revision_id != str(revisions[0]["source_revision_id"]):
            raise RetrievalContractError("retrieval prior revision differs")
        if not isinstance(self.query_valid_time, UtcTimestamp):
            raise RetrievalContractError(
                "retrieval fixture query-valid time must be typed"
            )
        if self.query_valid_time != UtcTimestamp.parse(
            "2042-03-12T12:00:00.000000Z"
        ):
            raise RetrievalContractError(
                "retrieval fixture query-valid time differs from the accepted contract"
            )
        query_observed_at = UtcTimestamp.parse(str(revisions[-1]["observed_at"]))
        if self.query_valid_time.value < query_observed_at.value:
            raise RetrievalContractError(
                "retrieval query-valid time precedes the query revision"
            )
        if self.query_hypothesis_version_id != str(hypotheses["new_version_id"]):
            raise RetrievalContractError("retrieval query hypothesis differs")
        if self.prior_hypothesis_version_id != str(hypotheses["prior_version_id"]):
            raise RetrievalContractError("retrieval prior hypothesis differs")
        if self.prior_candidate_version_id != INTEGRATED_FIXTURE_V2.prior_candidate_version_id:
            raise RetrievalContractError("retrieval prior candidate differs")
        expected_fulltext = tuple(
            sorted(item.query_id for item in INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_queries)
        )
        if self.fulltext_query_ids != expected_fulltext:
            raise RetrievalContractError("retrieval full-text query identities differ")
        if self.vector_query_id != INTEGRATED_FIXTURE_V2_PROJECTION.vector_queries[0].query_id:
            raise RetrievalContractError("retrieval vector query identity differs")
        root_ids = tuple(item.root_id for item in self.roots)
        if root_ids != tuple(sorted(set(root_ids))):
            raise RetrievalContractError("retrieval fixture roots must be sorted and unique")
        expected_root_ids = {
            f"candidate:{self.prior_candidate_version_id}",
            f"query:{self.query_revision_id}",
            "distractor:distinct-jurisdiction",
            "distractor:incompatible-formal-id",
        }
        if set(root_ids) != expected_root_ids:
            raise RetrievalContractError("retrieval fixture root inventory differs")
        passage_inventory = [
            passage_id
            for root in self.roots
            for passage_id in root.passage_ids
        ]
        if len(passage_inventory) != len(set(passage_inventory)):
            raise RetrievalContractError(
                "retrieval fixture passage authority is ambiguous across roots"
            )
        dependency_inventory = [
            dependency_id
            for root in self.roots
            for dependency_id in root.dependency_ids
        ]
        if len(dependency_inventory) != len(set(dependency_inventory)):
            raise RetrievalContractError(
                "retrieval fixture dependency authority is ambiguous across roots"
            )
        passage_ids = set(passage_inventory)
        expected_active = set(INTEGRATED_FIXTURE_V2_PROJECTION.expected_active_passage_ids)
        if passage_ids != expected_active:
            raise RetrievalContractError("retrieval roots must cover active fixture passages")
        candidate_roots = tuple(
            root for root in self.roots if root.candidate_version_id is not None
        )
        if (
            len(candidate_roots) != 1
            or candidate_roots[0].root_id
            != f"candidate:{self.prior_candidate_version_id}"
            or candidate_roots[0].candidate_version_id
            != self.prior_candidate_version_id
            or candidate_roots[0].exclusion_reason is not None
        ):
            raise RetrievalContractError(
                "retrieval fixture prior-candidate authority differs"
            )
        window_start = HYBRID_FIXTURE_POLICY_V1.date_window_start(
            self.query_valid_time
        )
        candidate = self.root_by_id.get(
            f"candidate:{self.prior_candidate_version_id}"
        )
        if (
            candidate is None
            or candidate.observed_at.value < window_start.value
            or candidate.observed_at.value > self.query_valid_time.value
        ):
            raise RetrievalContractError(
                "retrieval prior candidate is outside the accepted date window"
            )
        expected_roots = {
            f"candidate:{self.prior_candidate_version_id}": {
                "candidate_version_id": self.prior_candidate_version_id,
                "dependency_ids": tuple(
                    sorted(
                        {
                            self.prior_revision_id,
                            self.prior_hypothesis_version_id,
                            self.prior_candidate_version_id,
                        }
                    )
                ),
                "passage_ids": tuple(
                    sorted(str(item["passage_id"]) for item in revisions[0]["passages"])
                ),
                "observed_at": UtcTimestamp.parse(
                    str(revisions[0]["observed_at"])
                ),
                "exclusion_reason": None,
            },
            f"query:{self.query_revision_id}": {
                "candidate_version_id": None,
                "dependency_ids": tuple(
                    sorted(
                        {
                            self.query_revision_id,
                            self.query_hypothesis_version_id,
                        }
                    )
                ),
                "passage_ids": tuple(
                    sorted(str(item["passage_id"]) for item in revisions[-1]["passages"])
                ),
                "observed_at": UtcTimestamp.parse(
                    str(revisions[-1]["observed_at"])
                ),
                "exclusion_reason": RetrievalExclusionReason.SELF_QUERY,
            },
            "distractor:distinct-jurisdiction": {
                "candidate_version_id": None,
                "dependency_ids": ("SYN-PROC-2042-NORTH",),
                "passage_ids": ("ifv2-distinct-jurisdiction",),
                "observed_at": UtcTimestamp.parse(
                    str(revisions[0]["observed_at"])
                ),
                "exclusion_reason": (
                    RetrievalExclusionReason.INCOMPATIBLE_JURISDICTION
                ),
            },
            "distractor:incompatible-formal-id": {
                "candidate_version_id": None,
                "dependency_ids": ("SYN-PROC-2402",),
                "passage_ids": ("ifv2-incompatible-formal-id",),
                "observed_at": UtcTimestamp.parse(
                    str(revisions[-1]["observed_at"])
                ),
                "exclusion_reason": (
                    RetrievalExclusionReason.INCOMPATIBLE_FORMAL_ID
                ),
            },
        }
        for root in self.roots:
            expected = expected_roots[root.root_id]
            if any(
                (
                    root.candidate_version_id
                    != expected["candidate_version_id"],
                    root.dependency_ids != expected["dependency_ids"],
                    root.passage_ids != expected["passage_ids"],
                    root.observed_at != expected["observed_at"],
                    root.exclusion_reason != expected["exclusion_reason"],
                )
            ):
                raise RetrievalContractError(
                    "retrieval fixture root lineage differs from accepted authority"
                )

    @property
    def root_by_id(self) -> dict[str, FixtureDependencyRoot]:
        return {item.root_id: item for item in self.roots}

    @property
    def root_by_passage_id(self) -> dict[str, FixtureDependencyRoot]:
        return {
            passage_id: root
            for root in self.roots
            for passage_id in root.passage_ids
        }

    @property
    def root_by_dependency_id(self) -> dict[str, FixtureDependencyRoot]:
        return {
            dependency_id: root
            for root in self.roots
            for dependency_id in root.dependency_ids
        }

    def canonical_value(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "source_fixture_digest": self.source_fixture_digest,
            "projection_fixture_digest": self.projection_fixture_digest,
            "policy_digest": self.policy_digest,
            "fixture_id": self.fixture_id,
            "relation_fixture_binding_id": str(
                self.relation_fixture_binding_id
            ),
            "canonical_process_id": self.canonical_process_id,
            "query_revision_id": self.query_revision_id,
            "prior_revision_id": self.prior_revision_id,
            "query_valid_time": self.query_valid_time.to_text(),
            "query_hypothesis_version_id": self.query_hypothesis_version_id,
            "prior_hypothesis_version_id": self.prior_hypothesis_version_id,
            "prior_candidate_version_id": self.prior_candidate_version_id,
            "fulltext_query_ids": list(self.fulltext_query_ids),
            "vector_query_id": self.vector_query_id,
            "roots": [item.canonical_value() for item in self.roots],
        }

    @property
    def contract_digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.canonical_value()))

    def query_digest(
        self,
        *,
        generation_identity_digest: str,
        query_valid_time: str,
        watermark: int,
    ) -> str:
        try:
            validate_sha256_digest(
                generation_identity_digest,
                field="retrieval_generation_identity_digest",
            )
        except ValueError as exc:
            raise RetrievalContractError(
                "retrieval generation identity digest is invalid"
            ) from exc
        try:
            parsed_query_valid_time = UtcTimestamp.parse(query_valid_time)
        except (TypeError, ValueError) as exc:
            raise RetrievalContractError(
                "retrieval query digest time is invalid"
            ) from exc
        if parsed_query_valid_time != self.query_valid_time:
            raise RetrievalContractError(
                "retrieval query digest time differs from fixture authority"
            )
        if (
            isinstance(watermark, bool)
            or not isinstance(watermark, int)
            or watermark <= 0
        ):
            raise RetrievalContractError(
                "retrieval query digest watermark must be positive"
            )
        return digest_canonical(
            {
                "contract": "newsroom-find-related-event-candidates-query-v1",
                "retrieval_contract_digest": self.contract_digest,
                "generation_identity_digest": generation_identity_digest,
                "query_revision_id": self.query_revision_id,
                "query_hypothesis_version_id": self.query_hypothesis_version_id,
                "canonical_process_id": self.canonical_process_id,
                "query_valid_time": parsed_query_valid_time.to_text(),
                "authority_watermark": watermark,
            }
        )



def validate_fixture_branch_executions(
    *,
    executions: tuple[RetrievalBranchExecution, ...],
    policy: HybridRetrievalPolicy,
    contract: IntegratedFixtureV2RetrievalContract,
    query_digest: str,
) -> None:
    """Recheck typed adapter output at the authority boundary.

    The private adapter owns fixed Cypher, but durable context authority must not
    trust a substituted adapter merely because it returned well-typed rows.
    This fixture proof therefore binds exact query identities, trust classes,
    source identities and mandatory prior-candidate coverage for every branch.
    """

    validate_sha256_digest(query_digest, field="retrieval_query_digest")
    if policy.contract_digest != contract.policy_digest:
        raise RetrievalContractError(
            "retrieval branch policy differs from fixture authority"
        )
    if tuple(item.branch for item in executions) != policy.required_branches:
        raise RetrievalContractError(
            "retrieval branch inventory differs from fixture authority"
        )
    if sum(item.elapsed_ms for item in executions) > policy.timeout_ms:
        raise RetrievalContractError(
            "retrieval branch evidence exceeds the shared tool timeout"
        )
    observed_roots = {
        hit.dependency_root_id
        for execution in executions
        for hit in execution.hits
    }
    if observed_roots != set(contract.root_by_id):
        raise RetrievalContractError(
            "retrieval branch evidence omits the mandatory fixture neighbourhood"
        )
    fulltext_query_id = next(
        item.query_id
        for item in INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_queries
        if item.language == "en-GB"
    )
    expected_query_ids = {
        RetrievalBranch.EXACT: "fixture-exact-prior-revision",
        RetrievalBranch.ADMITTED_GRAPH: "fixture-admitted-development",
        RetrievalBranch.FULL_TEXT: fulltext_query_id,
        RetrievalBranch.VECTOR: contract.vector_query_id,
    }
    candidate_root_id = f"candidate:{contract.prior_candidate_version_id}"
    relation = INTEGRATED_FIXTURE_V2.relation
    expected_relation_key = governed_relation_key(
        fixture_binding_id=contract.relation_fixture_binding_id,
        subject=relation.subject,
        predicate=relation.predicate,
        object=relation.object,
        temporal_scope=relation.temporal_scope,
    )

    for execution in executions:
        if (
            execution.query_id != expected_query_ids[execution.branch]
            or execution.query_digest != query_digest
            or execution.result_limit != policy.branch_result_limit
            or execution.elapsed_ms > policy.timeout_ms
            or not execution.hits
        ):
            raise RetrievalContractError(
                f"{execution.branch.value} retrieval execution differs from fixture authority"
            )
        if not any(
            hit.dependency_root_id == candidate_root_id
            for hit in execution.hits
        ):
            raise RetrievalContractError(
                f"{execution.branch.value} omitted the mandatory prior candidate"
            )
        for hit in execution.hits:
            root = contract.root_by_id.get(hit.dependency_root_id)
            if root is None:
                raise RetrievalContractError(
                    "retrieval hit has no checked fixture dependency root"
                )
            score = float(hit.raw_score)
            if execution.branch in {
                RetrievalBranch.EXACT,
                RetrievalBranch.ADMITTED_GRAPH,
            } and score != 1.0:
                raise RetrievalContractError(
                    f"{execution.branch.value} score differs from fixture authority"
                )
            if (
                execution.branch is RetrievalBranch.VECTOR
                and not 0.0 <= score <= 1.0
            ):
                raise RetrievalContractError(
                    "vector score differs from fixture authority"
                )
            if hit.query_id != execution.query_id or hit.query_digest != query_digest:
                raise RetrievalContractError(
                    "retrieval hit query identity differs from its branch"
                )
            if execution.branch is RetrievalBranch.ADMITTED_GRAPH:
                if (
                    hit.passage_id is not None
                    or hit.trust_scope is not TrustScope.ADMITTED
                    or hit.source_kind != "RELATION_ASSERTION"
                    or hit.dependency_root_id != candidate_root_id
                    or hit.result_key
                    != (
                        f"{RetrievalBranch.ADMITTED_GRAPH.value}:"
                        f"{contract.prior_hypothesis_version_id}"
                    )
                    or hit.source_identity != expected_relation_key
                ):
                    raise RetrievalContractError(
                        "admitted graph evidence differs from the governed fixture relation"
                    )
                continue

            if (
                hit.passage_id is None
                or hit.trust_scope is not TrustScope.OBSERVED
                or hit.source_kind
                not in {"GOVERNED_PASSAGE", "GOVERNED_REVISION"}
                or hit.result_key
                != f"{execution.branch.value}:{hit.passage_id}"
                or contract.root_by_passage_id.get(hit.passage_id) != root
            ):
                raise RetrievalContractError(
                    "retrieval document evidence differs from governed fixture authority"
                )
            if execution.branch is RetrievalBranch.EXACT:
                if (
                    hit.source_kind != "GOVERNED_REVISION"
                    or hit.source_identity != contract.prior_revision_id
                    or hit.dependency_root_id != candidate_root_id
                ):
                    raise RetrievalContractError(
                        "exact retrieval evidence differs from prior revision authority"
                    )
            elif (
                hit.source_kind != "GOVERNED_PASSAGE"
                or hit.source_identity != hit.passage_id
            ):
                raise RetrievalContractError(
                    "approximate retrieval evidence differs from passage authority"
                )


_SOURCE_VALUE = json.loads(INTEGRATED_FIXTURE_V2.canonical_bytes)
_REVISIONS = _SOURCE_VALUE["revisions"]
_prior = _REVISIONS[0]
_new = _REVISIONS[1]
_HYPOTHESES = _SOURCE_VALUE["event_hypotheses"]
_CANONICAL_PROCESS_ID = str(_SOURCE_VALUE["formal_process"]["canonical_process_id"])
_QUERY_VALID_TIME = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
_PRIOR_OBSERVED_AT = UtcTimestamp.parse(str(_prior["observed_at"]))
_NEW_OBSERVED_AT = UtcTimestamp.parse(str(_new["observed_at"]))

INTEGRATED_FIXTURE_V2_RETRIEVAL = IntegratedFixtureV2RetrievalContract(
    contract_id="integrated_fixture_v2_retrieval",
    contract_version="integrated-fixture-v2-retrieval-v1",
    source_fixture_digest=INTEGRATED_FIXTURE_V2.manifest_digest,
    projection_fixture_digest=INTEGRATED_FIXTURE_V2_PROJECTION.manifest_digest,
    policy_digest=HYBRID_FIXTURE_POLICY_V1.contract_digest,
    fixture_id=INTEGRATED_FIXTURE_V2.fixture_id,
    relation_fixture_binding_id=INTEGRATED_FIXTURE_V2_BINDING_ID,
    canonical_process_id=_CANONICAL_PROCESS_ID,
    query_revision_id=str(_new["source_revision_id"]),
    prior_revision_id=str(_prior["source_revision_id"]),
    query_valid_time=_QUERY_VALID_TIME,
    query_hypothesis_version_id=str(_HYPOTHESES["new_version_id"]),
    prior_hypothesis_version_id=str(_HYPOTHESES["prior_version_id"]),
    prior_candidate_version_id=INTEGRATED_FIXTURE_V2.prior_candidate_version_id,
    fulltext_query_ids=tuple(
        sorted(item.query_id for item in INTEGRATED_FIXTURE_V2_PROJECTION.fulltext_queries)
    ),
    vector_query_id=INTEGRATED_FIXTURE_V2_PROJECTION.vector_queries[0].query_id,
    roots=tuple(
        sorted(
            (
                FixtureDependencyRoot(
                    root_id=f"candidate:{INTEGRATED_FIXTURE_V2.prior_candidate_version_id}",
                    candidate_version_id=INTEGRATED_FIXTURE_V2.prior_candidate_version_id,
                    dependency_ids=tuple(
                        sorted(
                            {
                                str(_prior["source_revision_id"]),
                                str(_HYPOTHESES["prior_version_id"]),
                                INTEGRATED_FIXTURE_V2.prior_candidate_version_id,
                            }
                        )
                    ),
                    passage_ids=tuple(sorted(str(item["passage_id"]) for item in _prior["passages"])),
                    observed_at=_PRIOR_OBSERVED_AT,
                ),
                FixtureDependencyRoot(
                    root_id=f"query:{_new["source_revision_id"]}",
                    candidate_version_id=None,
                    dependency_ids=tuple(
                        sorted(
                            {
                                str(_new["source_revision_id"]),
                                str(_HYPOTHESES["new_version_id"]),
                            }
                        )
                    ),
                    passage_ids=tuple(sorted(str(item["passage_id"]) for item in _new["passages"])),
                    observed_at=_NEW_OBSERVED_AT,
                    exclusion_reason=RetrievalExclusionReason.SELF_QUERY,
                ),
                FixtureDependencyRoot(
                    root_id="distractor:distinct-jurisdiction",
                    candidate_version_id=None,
                    dependency_ids=("SYN-PROC-2042-NORTH",),
                    passage_ids=("ifv2-distinct-jurisdiction",),
                    observed_at=_PRIOR_OBSERVED_AT,
                    exclusion_reason=RetrievalExclusionReason.INCOMPATIBLE_JURISDICTION,
                ),
                FixtureDependencyRoot(
                    root_id="distractor:incompatible-formal-id",
                    candidate_version_id=None,
                    dependency_ids=("SYN-PROC-2402",),
                    passage_ids=("ifv2-incompatible-formal-id",),
                    observed_at=_NEW_OBSERVED_AT,
                    exclusion_reason=RetrievalExclusionReason.INCOMPATIBLE_FORMAL_ID,
                ),
            ),
            key=lambda item: item.root_id,
        )
    ),
)
