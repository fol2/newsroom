from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.checks import (
    ObservableTransitionKind,
    ProposalAdmissionRequest,
    TransitionDirective,
)
from newsroom.projection import (
    ProjectionDeliveryOutcome,
    ProjectionNodeType,
    ProjectionRelationType,
)
from newsroom.projection.mapping import canonical_governed_node_id
from newsroom.sources import ObservationModel

from .check_3c_authority_helpers import open_check_system
from .discovery_projection_3e_helpers import (
    MemoryNeo4jAdapter,
    open_lineage_projection_system,
)
from .test_check_3c_model_policies import (
    _absence_guard,
    _adapter_request,
    _admit,
    _baseline,
    _confirmation_ref,
    _proposal,
    _seed_check,
    _seed_source,
)
from .test_discovery_projection_3e_authority import (
    deliver_authority_history,
    register_generation,
)


def _mutable_transition(system):
    first_request = _adapter_request(ObservationModel.MUTABLE_ITEM, suffix=101)
    first_proposal = _proposal(
        first_request,
        suffix=101,
        items=[
            {
                "id": "mutable-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "published",
                "title": "Initial maintained item",
            }
        ],
    )
    _admit(system, first_request, first_proposal, suffix=101)
    second_request = _adapter_request(
        ObservationModel.MUTABLE_ITEM,
        suffix=102,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=102,
        items=[
            {
                "id": "mutable-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "updated",
                "title": "Revised maintained item",
            }
        ],
    )
    result, _ = _admit(system, second_request, second_proposal, suffix=102)
    assert len(result.transitions) == 1
    return result.transitions[0]


def _append_only_transition(system):
    first_request = _adapter_request(ObservationModel.APPEND_ONLY, suffix=103)
    first_proposal = _proposal(
        first_request,
        suffix=103,
        items=[
            {
                "id": "append-existing",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "published",
                "title": "Existing append-only item",
            }
        ],
    )
    _admit(system, first_request, first_proposal, suffix=103)
    second_request = _adapter_request(
        ObservationModel.APPEND_ONLY,
        suffix=104,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=104,
        items=[
            {
                "id": "append-existing",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "published",
                "title": "Existing append-only item",
            },
            {
                "id": "append-new",
                "source_published_time": "2042-03-12T10:00:00.000000Z",
                "status": "published",
                "title": "New append-only item",
            },
        ],
    )
    result, _ = _admit(system, second_request, second_proposal, suffix=104)
    assert len(result.transitions) == 1
    return result.transitions[0]


def _rolling_list_transition(system):
    first_request = _adapter_request(ObservationModel.ROLLING_LIST, suffix=105)
    first_proposal = _proposal(
        first_request,
        suffix=105,
        items=[
            {
                "id": "rolling-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "active",
                "title": "Rolling item",
            }
        ],
    )
    _admit(system, first_request, first_proposal, suffix=105)
    item_key = first_proposal.candidate_items[0].item_key
    second_request = _adapter_request(
        ObservationModel.ROLLING_LIST,
        suffix=106,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(second_request, suffix=106, items=[])

    def directives(
        admission: ProposalAdmissionRequest,
    ) -> tuple[TransitionDirective, ...]:
        return (
            TransitionDirective(
                item_key=item_key,
                kind=ObservableTransitionKind.AMBIGUOUS_ABSENCE,
                transition_discriminator="projection-rolling-window-absence",
                absence_guard=_absence_guard(
                    authorizing=False,
                    confirmation_outcomes=(_confirmation_ref(admission),),
                ),
            ),
        )

    result, _ = _admit(
        system,
        second_request,
        second_proposal,
        suffix=106,
        transition_directive_factory=directives,
    )
    assert len(result.transitions) == 1
    return result.transitions[0]


def _complete_state_transition(system):
    request = _adapter_request(
        ObservationModel.COMPLETE_CURRENT_STATE,
        suffix=107,
    )
    proposal = _proposal(
        request,
        suffix=107,
        items=[
            {
                "id": "active-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "active",
                "title": "Active complete-state item",
            }
        ],
    )
    result, _ = _admit(system, request, proposal, suffix=107)
    assert len(result.transitions) == 1
    return result.transitions[0]


def _explicit_delta_transition(system):
    first_request = _adapter_request(ObservationModel.EXPLICIT_DELTA, suffix=108)
    first_proposal = _proposal(
        first_request,
        suffix=108,
        items=[
            {
                "id": "delta-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "normal",
                "title": "Explicit delta item",
            }
        ],
    )
    _admit(system, first_request, first_proposal, suffix=108)
    second_request = _adapter_request(
        ObservationModel.EXPLICIT_DELTA,
        suffix=109,
        baseline=_baseline(first_request, first_proposal),
    )
    second_proposal = _proposal(
        second_request,
        suffix=109,
        items=[
            {
                "id": "delta-1",
                "source_published_time": "2042-03-12T09:00:00.000000Z",
                "status": "urgent",
                "title": "Explicit delta item",
            }
        ],
    )
    request, attempt = _seed_check(system, second_request, suffix=109)
    admission = ProposalAdmissionRequest(
        request.request_id,
        attempt.attempt_id,
        second_request,
        second_proposal,
        transition_directives=(
            TransitionDirective(
                item_key=second_proposal.candidate_items[0].item_key,
                kind=ObservableTransitionKind.ESCALATED,
                transition_discriminator="projection-explicit-escalation",
                change_facets=("STATUS",),
            ),
        ),
    )
    result = system.checks.admit_proposal(admission, proof=_proof())
    assert len(result.transitions) == 1
    return result.transitions[0]


def _agenda_transition(system):
    request = _adapter_request(ObservationModel.PLANNED_AGENDA, suffix=110)
    proposal = _proposal(
        request,
        suffix=110,
        items=[
            {
                "expected_time": "2042-03-13T10:00:00.000000Z",
                "id": "agenda-1",
                "status": "planned",
                "title": "Future fixture agenda",
            }
        ],
    )
    result, _ = _admit(system, request, proposal, suffix=110)
    assert len(result.transitions) == 1
    return result.transitions[0]


def _proof():
    # Keep the proof provider local so importing this test does not introduce a
    # second public authority boundary.
    from .check_3c_authority_helpers import proof

    return proof()


_BUILDERS = {
    ObservationModel.MUTABLE_ITEM: _mutable_transition,
    ObservationModel.APPEND_ONLY: _append_only_transition,
    ObservationModel.ROLLING_LIST: _rolling_list_transition,
    ObservationModel.COMPLETE_CURRENT_STATE: _complete_state_transition,
    ObservationModel.EXPLICIT_DELTA: _explicit_delta_transition,
    ObservationModel.PLANNED_AGENDA: _agenda_transition,
}

_EXPECTED_KINDS = {
    ObservationModel.MUTABLE_ITEM: ObservableTransitionKind.REVISED,
    ObservationModel.APPEND_ONLY: ObservableTransitionKind.FIRST_OBSERVED,
    ObservationModel.ROLLING_LIST: ObservableTransitionKind.AMBIGUOUS_ABSENCE,
    ObservationModel.COMPLETE_CURRENT_STATE: ObservableTransitionKind.ACTIVATED,
    ObservationModel.EXPLICIT_DELTA: ObservableTransitionKind.ESCALATED,
    ObservationModel.PLANNED_AGENDA: ObservableTransitionKind.AGENDA_CREATED,
}


@pytest.mark.parametrize("model", tuple(ObservationModel))
def test_every_accepted_observation_model_projects_meaningful_transition(
    tmp_path: Path,
    model: ObservationModel,
) -> None:
    database = tmp_path / f"{model.value.lower()}.sqlite3"
    authority = open_check_system(database)
    try:
        _seed_source(authority, model)
        transition = _BUILDERS[model](authority)
        assert transition.request.kind is _EXPECTED_KINDS[model]
    finally:
        authority.close()

    adapter = MemoryNeo4jAdapter()
    projection = open_lineage_projection_system(database, adapter)
    try:
        generation = register_generation(projection)
        deliveries = deliver_authority_history(projection, generation)
        event, _request, result = next(
            item
            for item in deliveries
            if item[0].event_type == "source.observable_transition.recorded"
            and str(item[0].aggregate_id)
            == str(transition.request.transition_id)
        )
        assert result.outcome is ProjectionDeliveryOutcome.APPLIED
        batch = adapter.deliveries[
            (str(generation.generation_id), event.ledger_seq)
        ]
        transition_id = canonical_governed_node_id(
            ProjectionNodeType.OBSERVABLE_TRANSITION,
            "observable_transition",
            str(transition.request.transition_id),
        )
        item_id = canonical_governed_node_id(
            ProjectionNodeType.SOURCE_ITEM,
            "source_item",
            str(transition.request.item_id),
        )
        outcome_id = canonical_governed_node_id(
            ProjectionNodeType.CHECK_OUTCOME,
            "check_outcome",
            str(transition.request.check_outcome_id),
        )
        assert any(
            node.node_type is ProjectionNodeType.OBSERVABLE_TRANSITION
            and node.canonical_id == transition_id
            for node in batch.nodes
        )
        assert any(
            relation.relation_type is ProjectionRelationType.TRANSITION_OF_ITEM
            and relation.source_canonical_id == item_id
            and relation.target_canonical_id == transition_id
            for relation in batch.relations
        )
        assert any(
            relation.relation_type
            is ProjectionRelationType.CLASSIFIED_BY_TRANSITION
            and relation.source_canonical_id == outcome_id
            and relation.target_canonical_id == transition_id
            for relation in batch.relations
        )
    finally:
        projection.close()
