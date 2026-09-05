from __future__ import annotations

from types import SimpleNamespace

from newsroom.extraction.types import ProposalPredicateHint
from newsroom.graphiti_adapter.evaluation_attempt import evaluation_attempt_for
from newsroom.graphiti_adapter.result_mapping import relation_proposals


def _result(*, predicate: str) -> SimpleNamespace:
    return SimpleNamespace(
        nodes=(
            SimpleNamespace(uuid="node-a", name="Alice"),
            SimpleNamespace(uuid="node-b", name="Bob"),
        ),
        edges=(
            SimpleNamespace(
                name=predicate,
                fact="Alice supports Bob",
                source_node_uuid="node-a",
                target_node_uuid="node-b",
            ),
        ),
    )


def test_evaluation_extraction_run_idempotency_key_is_per_ingest() -> None:
    first = evaluation_attempt_for(("Hong Kong weather warning one.",))
    second = evaluation_attempt_for(("Hong Kong weather warning two.",))
    again = evaluation_attempt_for(("Hong Kong weather warning one.",))

    assert first.episode_uuid != second.episode_uuid
    assert first.extraction_request.idempotency_key == (
        f"evaluation-graphiti-run-{first.episode_uuid}"
    )
    assert second.extraction_request.idempotency_key == (
        f"evaluation-graphiti-run-{second.episode_uuid}"
    )
    assert (
        first.extraction_request.idempotency_key
        != second.extraction_request.idempotency_key
    )
    assert again.extraction_request.idempotency_key == (
        first.extraction_request.idempotency_key
    )
    assert first.extraction_contract.idempotency_key == (
        "evaluation-graphiti-contract-v2"
    )
    assert first.configuration.idempotency_key == (
        "evaluation-graphiti-configuration-v2"
    )
    assert first.idempotency_key == (
        f"evaluation-graphiti-attempt-{first.episode_uuid}"
    )


def test_registered_relation_label_maps_to_exact_predicate_hint() -> None:
    attempt = evaluation_attempt_for(("Alice supports Bob",))

    proposals = relation_proposals(_result(predicate="SUPPORTS"), attempt)

    assert len(proposals) == 1
    assert proposals[0].predicate_hint is ProposalPredicateHint.SUPPORTS


def test_unknown_relation_label_remains_unproposed() -> None:
    attempt = evaluation_attempt_for(("Alice supports Bob",))

    proposals = relation_proposals(_result(predicate="INVENTED_EDGE"), attempt)

    assert proposals == ()


def test_relation_without_two_exact_entity_mentions_remains_unproposed() -> None:
    attempt = evaluation_attempt_for(("Alice supports Bob",))
    result = _result(predicate="SUPPORTS")
    result.nodes = (
        result.nodes[0],
        SimpleNamespace(uuid="node-b", name="Charlie"),
    )

    proposals = relation_proposals(result, attempt)

    assert proposals == ()
