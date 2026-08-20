from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from newsroom.authority.canonical import digest_bytes
from newsroom.entities.types import EntityResolutionDecisionAction
from newsroom.extraction.models import ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionPassageId,
    ExtractionProposalKind,
    ProposalPredicateHint,
)
from newsroom.graphiti_adapter import REAL_GRAPHITI_RUNTIME_ENABLED
from newsroom.graphiti_adapter.admission import (
    ADMITTED_NEO4J_LABELS,
    ADMITTED_OD006_VECTOR_DIMENSIONS,
    GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID,
    GraphitiProposalAdmissionAction,
    GraphitiProposalAdmissionDecision,
    GraphitiProposalAdmissionDecisionId,
    GraphitiProposalAdmissionError,
    admit_graphiti_proposals_for_projectors,
    increment4_batches_for_admitted_graphiti,
    require_admitted_projector_write,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    EVALUATION_GRAPHITI_PACKET,
    GRAPHITI_WORKSPACE_GROUP,
    WRITER_FALLBACK,
    WRITER_MODEL,
)
from newsroom.graphiti_adapter.real import RealGraphitiAdapter
from newsroom.graphiti_adapter.types import GraphitiExecutionProfile
from newsroom.increment4.contracts import INCREMENT4_ADMITTED_FAMILY_ID
from newsroom.relations.models import RelationDecisionAction


_ADAPTER_ROOT = Path(__file__).resolve().parents[2] / "newsroom" / "graphiti_adapter"
_DECISION_A = GraphitiProposalAdmissionDecisionId.parse(
    "00000000-0000-4000-8000-000000004941"
)
_DECISION_B = GraphitiProposalAdmissionDecisionId.parse(
    "00000000-0000-4000-8000-000000004942"
)


def _evidence() -> EvidenceRange:
    return EvidenceRange(
        passage_id=ExtractionPassageId.parse("00000000-0000-4000-8000-000000004940"),
        start_byte=0,
        end_byte=4,
        evidence_text_digest=digest_bytes(b"test"),
    )


def _entity(*, local_id: str = "entity.one") -> ProposalDraft:
    return ProposalDraft(
        local_id=local_id,
        kind=ExtractionProposalKind.ENTITY_MENTION,
        subject_placeholder="Hong Kong",
        object_placeholder=None,
        predicate_hint=None,
        confidence_basis_points=None,
        uncertainty_codes=(),
        rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
        evidence=(_evidence(),),
    )


def _relation(*, local_id: str = "relation.one") -> ProposalDraft:
    return ProposalDraft(
        local_id=local_id,
        kind=ExtractionProposalKind.RELATION,
        subject_placeholder="Hong Kong",
        object_placeholder="Transport Department",
        predicate_hint=ProposalPredicateHint.ABOUT_EVENT,
        confidence_basis_points=None,
        uncertainty_codes=(),
        rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
        evidence=(_evidence(),),
    )


def _decision(
    proposal: ProposalDraft,
    *,
    decision_id: GraphitiProposalAdmissionDecisionId,
    action: GraphitiProposalAdmissionAction,
    reason_code: str = "EVALUATION_ADMIT",
    workspace_group: str = GRAPHITI_WORKSPACE_GROUP,
    execution_profile: GraphitiExecutionProfile = GraphitiExecutionProfile.EVALUATION,
) -> GraphitiProposalAdmissionDecision:
    return GraphitiProposalAdmissionDecision(
        decision_id=decision_id,
        proposal_digest=proposal.digest,
        proposal_kind=proposal.kind,
        proposal_local_id=proposal.local_id,
        action=action,
        reason_code=reason_code,
        workspace_group=workspace_group,
        execution_profile=execution_profile,
    )


def test_admit_is_required_before_increment4_projector_write() -> None:
    entity = _entity()
    relation = _relation()
    write = admit_graphiti_proposals_for_projectors(
        proposals=(entity, relation),
        decisions=(
            _decision(entity, decision_id=_DECISION_A, action=GraphitiProposalAdmissionAction.ADMIT),
            _decision(
                relation,
                decision_id=_DECISION_B,
                action=GraphitiProposalAdmissionAction.ADMIT,
                reason_code="EVALUATION_ADMIT_RELATION",
            ),
        ),
    )
    gated = require_admitted_projector_write(write)
    assert gated.may_write_admitted_projector is True
    assert gated.proposals == (entity, relation)
    assert gated.workspace_group == "newsroom-eval-proposal"
    assert gated.projector_family_id == INCREMENT4_ADMITTED_FAMILY_ID
    assert gated.projector_family_id == GRAPHITI_ADMITTED_PROJECTOR_FAMILY_ID
    assert gated.admitted_vector_dimensions_excluded == 1024
    assert gated.admitted_vector_dimensions_excluded == ADMITTED_OD006_VECTOR_DIMENSIONS
    assert write.decisions[0].entity_resolution_action() is (
        EntityResolutionDecisionAction.ACCEPT
    )
    assert write.decisions[1].relation_admission_action() is RelationDecisionAction.ADMIT
    with pytest.raises(
        GraphitiProposalAdmissionError,
        match="typed Increment 4 snapshot",
    ):
        increment4_batches_for_admitted_graphiti(
            admission=write,
            snapshot=None,
            generation_id=None,
            family=None,
        )


@pytest.mark.parametrize(
    "action",
    (
        GraphitiProposalAdmissionAction.REJECT,
        GraphitiProposalAdmissionAction.HOLD,
    ),
)
def test_reject_and_hold_cannot_produce_admitted_projector_writes(
    action: GraphitiProposalAdmissionAction,
) -> None:
    entity = _entity()
    write = admit_graphiti_proposals_for_projectors(
        proposals=(entity,),
        decisions=(
            _decision(
                entity,
                decision_id=_DECISION_A,
                action=action,
                reason_code="EVALUATION_HOLD",
            ),
        ),
    )
    assert write.proposals == ()
    assert write.may_write_admitted_projector is False
    with pytest.raises(GraphitiProposalAdmissionError, match="ADMIT decision"):
        require_admitted_projector_write(write)
    with pytest.raises(GraphitiProposalAdmissionError, match="ADMIT decision"):
        increment4_batches_for_admitted_graphiti(
            admission=write,
            snapshot=None,
            generation_id=None,
            family=None,
        )


def test_hold_leaves_admitted_sibling_eligible_for_existing_projector_seam() -> None:
    entity = _entity()
    relation = _relation()
    write = admit_graphiti_proposals_for_projectors(
        proposals=(entity, relation),
        decisions=(
            _decision(entity, decision_id=_DECISION_A, action=GraphitiProposalAdmissionAction.ADMIT),
            _decision(
                relation,
                decision_id=_DECISION_B,
                action=GraphitiProposalAdmissionAction.HOLD,
                reason_code="EVALUATION_HOLD",
            ),
        ),
    )
    assert write.proposals == (entity,)
    assert write.decisions[0].action is GraphitiProposalAdmissionAction.ADMIT
    require_admitted_projector_write(write)


def test_missing_decision_fails_closed() -> None:
    entity = _entity()
    relation = _relation()
    with pytest.raises(GraphitiProposalAdmissionError, match="exactly one"):
        admit_graphiti_proposals_for_projectors(
            proposals=(entity, relation),
            decisions=(
                _decision(
                    entity,
                    decision_id=_DECISION_A,
                    action=GraphitiProposalAdmissionAction.ADMIT,
                ),
            ),
        )


def test_production_profile_and_foreign_group_are_refused() -> None:
    entity = _entity()
    with pytest.raises(GraphitiProposalAdmissionError, match="EVALUATION"):
        _decision(
            entity,
            decision_id=_DECISION_A,
            action=GraphitiProposalAdmissionAction.ADMIT,
            execution_profile=GraphitiExecutionProfile.PRODUCTION,
        )
    with pytest.raises(GraphitiProposalAdmissionError, match="newsroom-eval-proposal"):
        _decision(
            entity,
            decision_id=_DECISION_A,
            action=GraphitiProposalAdmissionAction.ADMIT,
            workspace_group="graphiti-qualification",
        )


def test_claim_proposals_are_outside_this_admission_slice() -> None:
    claim = ProposalDraft(
        local_id="claim.one",
        kind=ExtractionProposalKind.CLAIM,
        subject_placeholder="Hong Kong",
        object_placeholder=None,
        predicate_hint=None,
        confidence_basis_points=None,
        uncertainty_codes=(),
        rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
        evidence=(_evidence(),),
    )
    with pytest.raises(GraphitiProposalAdmissionError, match="entity and relation"):
        GraphitiProposalAdmissionDecision(
            decision_id=_DECISION_A,
            proposal_digest=claim.digest,
            proposal_kind=claim.kind,
            proposal_local_id=claim.local_id,
            action=GraphitiProposalAdmissionAction.ADMIT,
            reason_code="EVALUATION_ADMIT",
        )


def test_real_adapter_cannot_mutate_ledger_or_admitted_labels() -> None:
    assert REAL_GRAPHITI_RUNTIME_ENABLED is False
    assert GRAPHITI_WORKSPACE_GROUP == "newsroom-eval-proposal"
    assert inspect.signature(RealGraphitiAdapter.execute).parameters.keys() == {
        "self",
        "attempt",
        "workspace_root",
    }
    source = (_ADAPTER_ROOT / "real.py").read_text(encoding="utf-8")
    assert "group_id=GRAPHITI_WORKSPACE_GROUP" in source
    assert "update_communities=False" in source
    for label in ADMITTED_NEO4J_LABELS:
        assert label not in source
    assert "VECTOR_GENERATION_1024" not in source
    assert "ledger_events" not in source
    tree = ast.parse(source, filename="real.py")
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "sqlite3",
        "neo4j",
        "newsroom.authority._entity_store_commit",
        "newsroom.increment4.projection",
        "newsroom.projection.neo4j",
    }
    assert not imported & forbidden
    assert not any(
        name.startswith("newsroom.projection.neo4j")
        or name.startswith("newsroom.authority._entity")
        or name.startswith("newsroom.authority._relation")
        for name in imported
    )


def test_graphiti_adapter_sources_stay_on_private_workspace_and_group_id() -> None:
    files = (
        "fake.py",
        "replay.py",
        "producer.py",
        "workspace.py",
        "real.py",
    )
    for name in files:
        text = (_ADAPTER_ROOT / name).read_text(encoding="utf-8")
        for label in ADMITTED_NEO4J_LABELS:
            assert label not in text
        assert "VECTOR_GENERATION_1024" not in text
        assert "AUTO_PUBLISH" not in text
        assert "TargetOperation" not in text
        tree = ast.parse(text, filename=name)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "sqlite3" not in imported
        assert "newsroom.authority.persistence" not in imported
    packet = EVALUATION_GRAPHITI_PACKET.canonical_value()
    assert packet["framework_release"] == "graphiti-core-0.29.3"
    destination = {
        "engine": "neo4j-community-plus-graphiti",
        "neo4j_server": "2026.06.0",
        "driver": "neo4j==6.2.0",
        "graphiti_writes_ledger": False,
        "graphiti_writes_admitted_graph": False,
        "workspace_group": GRAPHITI_WORKSPACE_GROUP,
    }
    from newsroom.authority.canonical import digest_canonical

    assert packet["destination_contract_digest"] == digest_canonical(destination)
    assert WRITER_MODEL == "grok-build-cli:grok-4.6"
    assert WRITER_FALLBACK == "cursor-agent-cli"
    assert ADMITTED_OD006_VECTOR_DIMENSIONS == 1024
