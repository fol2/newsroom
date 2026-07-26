from __future__ import annotations

from dataclasses import dataclass
import json

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.projection import INTEGRATED_FIXTURE_V2_PROJECTION
from newsroom.relations import INTEGRATED_FIXTURE_V2

from .models import RetrievalContractError, RetrievalExclusionReason
from .policy import HYBRID_FIXTURE_POLICY_V1


@dataclass(frozen=True, slots=True)
class FixtureDependencyRoot:
    root_id: str
    candidate_version_id: str | None
    dependency_ids: tuple[str, ...]
    passage_ids: tuple[str, ...]
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
    canonical_process_id: str
    query_revision_id: str
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
        source = json.loads(INTEGRATED_FIXTURE_V2.canonical_bytes)
        revisions = source["revisions"]
        hypotheses = source["event_hypotheses"]
        if self.query_revision_id != str(revisions[-1]["source_revision_id"]):
            raise RetrievalContractError("retrieval query revision differs")
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
        passage_ids = {
            passage_id
            for root in self.roots
            for passage_id in root.passage_ids
        }
        expected_active = set(INTEGRATED_FIXTURE_V2_PROJECTION.expected_active_passage_ids)
        if passage_ids != expected_active:
            raise RetrievalContractError("retrieval roots must cover active fixture passages")

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
            "canonical_process_id": self.canonical_process_id,
            "query_revision_id": self.query_revision_id,
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

    def query_digest(self, *, generation_identity_digest: str, query_valid_time: str, watermark: int) -> str:
        return digest_canonical(
            {
                "contract": "newsroom-find-related-event-candidates-query-v1",
                "retrieval_contract_digest": self.contract_digest,
                "generation_identity_digest": generation_identity_digest,
                "query_revision_id": self.query_revision_id,
                "query_hypothesis_version_id": self.query_hypothesis_version_id,
                "canonical_process_id": self.canonical_process_id,
                "query_valid_time": query_valid_time,
                "authority_watermark": watermark,
            }
        )


_SOURCE_VALUE = json.loads(INTEGRATED_FIXTURE_V2.canonical_bytes)
_REVISIONS = _SOURCE_VALUE["revisions"]
_prior = _REVISIONS[0]
_new = _REVISIONS[1]
_HYPOTHESES = _SOURCE_VALUE["event_hypotheses"]
_CANONICAL_PROCESS_ID = str(_SOURCE_VALUE["formal_process"]["canonical_process_id"])

INTEGRATED_FIXTURE_V2_RETRIEVAL = IntegratedFixtureV2RetrievalContract(
    contract_id="integrated_fixture_v2_retrieval",
    contract_version="integrated-fixture-v2-retrieval-v1",
    source_fixture_digest=INTEGRATED_FIXTURE_V2.manifest_digest,
    projection_fixture_digest=INTEGRATED_FIXTURE_V2_PROJECTION.manifest_digest,
    policy_digest=HYBRID_FIXTURE_POLICY_V1.contract_digest,
    fixture_id=INTEGRATED_FIXTURE_V2.fixture_id,
    canonical_process_id=_CANONICAL_PROCESS_ID,
    query_revision_id=str(_new["source_revision_id"]),
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
                    exclusion_reason=RetrievalExclusionReason.SELF_QUERY,
                ),
                FixtureDependencyRoot(
                    root_id="distractor:distinct-jurisdiction",
                    candidate_version_id=None,
                    dependency_ids=("SYN-PROC-2042-NORTH",),
                    passage_ids=("ifv2-distinct-jurisdiction",),
                    exclusion_reason=RetrievalExclusionReason.INCOMPATIBLE_JURISDICTION,
                ),
                FixtureDependencyRoot(
                    root_id="distractor:incompatible-formal-id",
                    candidate_version_id=None,
                    dependency_ids=("SYN-PROC-2402",),
                    passage_ids=("ifv2-incompatible-formal-id",),
                    exclusion_reason=RetrievalExclusionReason.INCOMPATIBLE_FORMAL_ID,
                ),
            ),
            key=lambda item: item.root_id,
        )
    ),
)
