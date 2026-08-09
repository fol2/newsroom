"""Frozen production-shaped retrieval target loader for Increment 5E1."""

from __future__ import annotations

from collections.abc import Mapping

from ._retrieval_qualification_common import (
    TARGET_SPEC,
    TARGET_SPEC_DIGEST,
    QualificationMode,
    QualificationSystem,
    RetrievalQualificationError,
    digest,
    thaw,
)
from ._retrieval_qualification_contracts import QualificationTarget
from .contract_types import RetrievalComponentKind
from .decision import INCREMENT_5A_CONTRACT, INCREMENT_5A_CONTRACT_DIGEST
from .evaluation_plan import EVALUATION_PLAN_DIGEST, INCREMENT_5_EVALUATION_PLAN


def load_qualification_target(
    spec: Mapping[str, object] = TARGET_SPEC,
) -> QualificationTarget:
    value = thaw(spec)
    plan = thaw(INCREMENT_5_EVALUATION_PLAN)
    fulltext = INCREMENT_5A_CONTRACT.component_by_kind[
        RetrievalComponentKind.FULL_TEXT_INDEX
    ]
    if digest(value) != TARGET_SPEC_DIGEST:
        raise RetrievalQualificationError(
            "qualification target differs from reviewed v1"
        )
    if (
        value["contract_digest"] != INCREMENT_5A_CONTRACT_DIGEST
        or value["evaluation_plan_digest"] != EVALUATION_PLAN_DIGEST
        or value["required_component_digests"]
        != dict(INCREMENT_5A_CONTRACT.component_digests)
    ):
        raise RetrievalQualificationError("target contract differs")
    if (
        value["systems"] != plan["contract_evaluation_summary"]["ablations"]
        or value["qualification_target"]
        != plan["decision_scope"]["qualification_target"]
        or value["comparative_ablations"]
        != plan["decision_scope"]["comparative_ablations"]
    ):
        raise RetrievalQualificationError("target decision scope differs")

    graph = value["graph_engine"]
    proposal = value["proposal_framework"]
    challenger = value["challenger"]
    expected_graph = {
        "family": "NEO4J_COMMUNITY",
        "image": fulltext.configuration["engine_image"],
        "driver_version": fulltext.configuration["driver_version"],
        "mandatory": True,
        "fake_or_noop_allowed": False,
    }
    expected_challenger = {
        "enabled": False,
        "engine": None,
        "measured_blocker": None,
        "owner_approved_comparison_purpose": None,
    }
    if (
        graph != expected_graph
        or proposal["proposal_workspace_is_authority"] is not False
        or challenger != expected_challenger
    ):
        raise RetrievalQualificationError("target implementation differs")
    forbidden = (
        value["graph_free_profile_allowed"],
        value["silent_mode_fallback_allowed"],
        value["embedding_quality_qualified"],
        value["external_call_limit"],
        value["provider_spend_micros"],
        value["production_activation_authorized"],
    )
    if (
        any(forbidden)
        or value["authority_effect"] != "NONE"
        or value["candidate_effect"]
        != "READ_ONLY_EXPECTED_DISPOSITION_ONLY"
    ):
        raise RetrievalQualificationError("target widens the boundary")
    return QualificationTarget(
        target_id=value["target_id"],
        contract_digest=value["contract_digest"],
        evaluation_plan_digest=value["evaluation_plan_digest"],
        profile_id=value["profile_id"],
        systems=tuple(QualificationSystem(item) for item in value["systems"]),
        qualification_target=QualificationSystem(
            value["qualification_target"]
        ),
        comparative_ablations=tuple(
            QualificationSystem(item)
            for item in value["comparative_ablations"]
        ),
        required_modes=tuple(
            QualificationMode(item) for item in value["required_modes"]
        ),
        component_digests=tuple(
            sorted(value["required_component_digests"].items())
        ),
        graph_engine_family=graph["family"],
        graph_engine_image=graph["image"],
        graph_driver_version=graph["driver_version"],
        proposal_framework_family=proposal["family"],
        proposal_execution_status=proposal["execution_status"],
        vector_scope=value["vector_scope"],
        manifest_digest=TARGET_SPEC_DIGEST,
    )
