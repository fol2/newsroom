"""Immutable target, corpus, and Epoch contracts for Increment 5E1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ._retrieval_qualification_common import (
    MODE_ORDER,
    SYSTEM_ORDER,
    QualificationMode,
    QualificationSystem,
    RetrievalQualificationError,
    canonical_text_tuple,
    digest,
    parse_utc,
    require_digest,
    require_token,
    require_tree_sha,
    require_uint,
)


@dataclass(frozen=True, slots=True)
class QualificationTarget:
    target_id: str
    contract_digest: str
    evaluation_plan_digest: str
    profile_id: str
    systems: tuple[QualificationSystem, ...]
    qualification_target: QualificationSystem
    comparative_ablations: tuple[QualificationSystem, ...]
    required_modes: tuple[QualificationMode, ...]
    component_digests: tuple[tuple[str, str], ...]
    graph_engine_family: str
    graph_engine_image: str
    graph_driver_version: str
    proposal_framework_family: str
    proposal_execution_status: str
    vector_scope: str
    manifest_digest: str
    generation_id: str = "increment5-qualification-generation-v1"
    graph_mandatory: bool = True
    fake_or_noop_allowed: bool = False
    embedding_quality_qualified: bool = False
    external_call_limit: int = 0
    provider_spend_micros: int = 0
    authority_effect: str = "NONE"
    production_activation_authorized: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.target_id,
            self.profile_id,
            self.graph_engine_family,
            self.proposal_framework_family,
            self.proposal_execution_status,
            self.vector_scope,
            self.generation_id,
        ):
            require_token(value, field="target token")
        for value in (
            self.contract_digest,
            self.evaluation_plan_digest,
            self.manifest_digest,
        ):
            require_digest(value, field="target digest")
        if (
            self.systems != SYSTEM_ORDER
            or self.required_modes != MODE_ORDER
            or self.qualification_target is not QualificationSystem.HYBRID
        ):
            raise RetrievalQualificationError("target inventory differs")
        expected_ablations = tuple(
            system
            for system in SYSTEM_ORDER
            if system is not QualificationSystem.HYBRID
        )
        if self.comparative_ablations != expected_ablations:
            raise RetrievalQualificationError("ablation inventory differs")
        if self.component_digests != tuple(sorted(self.component_digests)):
            raise RetrievalQualificationError("component identities are not canonical")
        if len({name for name, _ in self.component_digests}) != len(
            self.component_digests
        ):
            raise RetrievalQualificationError("component identities duplicate")
        for name, value in self.component_digests:
            require_token(name, field="component name")
            require_digest(value, field="component digest")
        if type(self.graph_mandatory) is not bool or self.graph_mandatory is not True:
            raise RetrievalQualificationError("graph target must be mandatory")
        if type(self.fake_or_noop_allowed) is not bool or self.fake_or_noop_allowed:
            raise RetrievalQualificationError("graph target cannot use a fake or no-op")
        for field_name in (
            "embedding_quality_qualified",
            "production_activation_authorized",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise RetrievalQualificationError(f"{field_name} must be boolean")
        require_uint(self.external_call_limit, field="external_call_limit")
        require_uint(self.provider_spend_micros, field="provider_spend_micros")
        if (
            self.embedding_quality_qualified
            or self.external_call_limit
            or self.provider_spend_micros
            or self.authority_effect != "NONE"
            or self.production_activation_authorized
        ):
            raise RetrievalQualificationError("target claims a forbidden effect")


@dataclass(frozen=True, slots=True)
class QualificationCase:
    case_id: str
    sequence: int
    family_id: str
    case_type: str
    language: str
    query_valid_time: str
    expected_root: str
    prohibited_root: str
    slice_labels: tuple[str, ...]
    triage_labels: tuple[str, ...]
    expected_candidate_count: int
    fixture_hits: tuple[tuple[QualificationMode, tuple[str, ...]], ...]
    source_inventory_ids: tuple[str, ...]
    label_digest: str
    fixture_digest: str

    def __post_init__(self) -> None:
        require_token(self.case_id, field="case_id")
        if require_uint(self.sequence, field="sequence") == 0:
            raise RetrievalQualificationError("sequence must be positive")
        require_token(self.family_id, field="family_id")
        require_token(self.case_type, field="case_type")
        require_token(self.language, field="language")
        parse_utc(self.query_valid_time, field="query_valid_time")
        canonical_text_tuple(
            self.slice_labels,
            field="slice_labels",
            required=True,
        )
        canonical_text_tuple(self.triage_labels, field="triage_labels")
        canonical_text_tuple(
            self.source_inventory_ids,
            field="source_inventory_ids",
            required=True,
        )
        require_digest(self.label_digest, field="label_digest")
        require_digest(self.fixture_digest, field="fixture_digest")
        require_token(self.expected_root, field="expected_root")
        require_token(self.prohibited_root, field="prohibited_root")
        if self.expected_root == self.prohibited_root:
            raise RetrievalQualificationError("expected and prohibited roots overlap")
        if self.expected_candidate_count not in {0, 1}:
            raise RetrievalQualificationError("candidate expectation is outside bounds")
        if tuple(mode for mode, _ in self.fixture_hits) != MODE_ORDER:
            raise RetrievalQualificationError("case branch inventory differs")
        for _, roots in self.fixture_hits:
            if roots != tuple(sorted(set(roots))) or len(roots) > 8:
                raise RetrievalQualificationError("fixture roots differ")
            for root in roots:
                require_token(root, field="fixture root")

    @property
    def fixture_mapping(self) -> Mapping[QualificationMode, tuple[str, ...]]:
        return dict(self.fixture_hits)


@dataclass(frozen=True, slots=True)
class QualificationCorpus:
    corpus_id: str
    generator_version: str
    cases: tuple[QualificationCase, ...]
    query_set_digest: str
    label_policy_digest: str
    source_inventory_digest: str
    dataset_manifest_digest: str
    corpus_spec_digest: str

    def __post_init__(self) -> None:
        require_token(self.corpus_id, field="corpus_id")
        require_token(self.generator_version, field="generator_version")
        for value in (
            self.query_set_digest,
            self.label_policy_digest,
            self.source_inventory_digest,
            self.dataset_manifest_digest,
            self.corpus_spec_digest,
        ):
            require_digest(value, field="corpus digest")
        if len(self.cases) != 100:
            raise RetrievalQualificationError("corpus must contain exactly 100 cases")
        if tuple(case.sequence for case in self.cases) != tuple(range(1, 101)):
            raise RetrievalQualificationError("corpus case sequence differs")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise RetrievalQualificationError("corpus case identities duplicate")


@dataclass(frozen=True, slots=True)
class QualificationEpoch:
    epoch_id: str
    contract_digest: str
    evaluation_plan_digest: str
    target_manifest_digest: str
    component_digests: tuple[tuple[str, str], ...]
    source_inventory_digest: str
    source_provider_versions_digest: str
    adapter_parser_versions_digest: str
    query_set_digest: str
    threshold_set_digest: str
    policy_set_digest: str
    dataset_manifest_digest: str
    label_adjudication_policy_digest: str
    code_tree_sha: str
    generation_id: str

    def __post_init__(self) -> None:
        require_token(self.epoch_id, field="epoch_id")
        require_token(self.generation_id, field="generation_id")
        require_tree_sha(self.code_tree_sha)
        for value in (
            self.contract_digest,
            self.evaluation_plan_digest,
            self.target_manifest_digest,
            self.source_inventory_digest,
            self.source_provider_versions_digest,
            self.adapter_parser_versions_digest,
            self.query_set_digest,
            self.threshold_set_digest,
            self.policy_set_digest,
            self.dataset_manifest_digest,
            self.label_adjudication_policy_digest,
        ):
            require_digest(value, field="Epoch digest")
        if self.component_digests != tuple(sorted(self.component_digests)):
            raise RetrievalQualificationError("Epoch components are not canonical")
        for name, value in self.component_digests:
            require_token(name, field="Epoch component name")
            require_digest(value, field="Epoch component digest")

    def canonical_value(self) -> dict[str, object]:
        return {
            "schema_version": "newsroom.increment5.retrieval-qualification-epoch.v1",
            "epoch_id": self.epoch_id,
            "contract_digest": self.contract_digest,
            "evaluation_plan_digest": self.evaluation_plan_digest,
            "target_manifest_digest": self.target_manifest_digest,
            "component_digests": [
                {"name": name, "digest": value}
                for name, value in self.component_digests
            ],
            "source_inventory_digest": self.source_inventory_digest,
            "source_provider_versions_digest": self.source_provider_versions_digest,
            "adapter_parser_versions_digest": self.adapter_parser_versions_digest,
            "query_set_digest": self.query_set_digest,
            "threshold_set_digest": self.threshold_set_digest,
            "policy_set_digest": self.policy_set_digest,
            "dataset_manifest_digest": self.dataset_manifest_digest,
            "label_adjudication_policy_digest": (
                self.label_adjudication_policy_digest
            ),
            "code_tree_sha": self.code_tree_sha,
            "generation_id": self.generation_id,
        }

    @property
    def epoch_digest(self) -> str:
        return digest(self.canonical_value())
