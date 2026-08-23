"""Provider-free proofs for NewsroomCombinedTemporalExtractionV1 (#747).

Seams under test, taken from issue #747:

- compact schema and canonical digest
- deterministic evidence segmentation of one retained revision
- Newsroom prompt builder (no graphiti-core conversational-memory prompt)
- injected fake transport: one generate_response leaf, never BatchEdgeTimestamps
- normalisation to Graphiti-compatible node/edge proposals with temporal fields
- fail-closed malformed / temporal / evidence leaves
- prompt/schema byte comparison versus graphiti-core 0.29.3
- owner-gated live packet remains unauthorised
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_canonical
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CALL_SHAPES_PATH,
    CONTRACT_NAME,
    LIVE_PACKET_PATH,
    MEASUREMENTS_PATH,
    SCHEMA,
    SCHEMA_DIGEST,
    UNMEASURED,
    CombinedTemporalFailureCode,
    CombinedTemporalLeaf,
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
    build_compact_prompt,
    extract_combined_temporal,
    segment_source,
)
from newsroom.graphiti_adapter.combined_temporal_pipeline import (
    CombinedTemporalPipelineError,
    CombinedTemporalPipelineResult,
)
from newsroom.graphiti_adapter.combined_temporal_fixtures import (
    FIXTURES,
    INGESTED_AT,
    MALFORMED_CASES,
    GoldFixture,
    fixture,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_CORE_RELEASE,
    GRAPHITI_WORKSPACE_GROUP,
)
from newsroom.graphiti_adapter.identity import configuration_digest, content_digest
from newsroom.graphiti_adapter.temporal_vocabulary import TEMPORAL_POLICY_VERSION

_REPO = Path(__file__).resolve().parents[2]
_RESEARCH = _REPO / "docs" / "research"
GRAPHITI_MEMORY_PHRASE = "AI agent memory system"


class _FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def generate_response(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        response_model: str,
    ) -> CombinedTemporalTransportResult:
        del prompt, schema, response_model
        return CombinedTemporalTransportResult(
            raw=self.payload,
            framework_version=GRAPHITI_CORE_RELEASE,
            model_version=None,
            token_usage={"basis": UNMEASURED},
            provider_cost=None,
        )


class _ProviderFreePipeline:
    def prepare_attempt(self) -> None:
        return None

    def complete_failure(
        self, receipt: Mapping[str, object]
    ) -> Mapping[str, object]:
        return receipt

    def execute(
        self,
        *,
        nodes: tuple[Any, ...],
        edges: tuple[Any, ...],
        receipt: Mapping[str, object],
    ) -> CombinedTemporalPipelineResult:
        assert receipt["provider_attempt_number"] == 1
        for node in nodes:
            node.attributes = {**node.attributes, "resolution": "NEW"}
        for edge in edges:
            edge.fact_embedding = [0.0]
        return CombinedTemporalPipelineResult(
            nodes=nodes,
            edges=edges,
            guarded_edges=edges,
            node_resolutions=tuple("NEW" for _node in nodes),
            graph_effect_attempted=False,
            embedding_skipped=not edges,
            journal_skipped=False,
            rollback_skipped=True,
        )


_PIPELINE = _ProviderFreePipeline()


def _extract(
    name: str, payload: object | None = None
) -> tuple[CombinedTemporalLeaf, GoldFixture]:
    case = fixture(name)
    transport = _FakeTransport(case.gold if payload is None else payload)
    return extract_combined_temporal(
        case.revision,
        transport=transport,
        pipeline=_PIPELINE,
    ), case


def _named_pair_payload(
    fact: str,
    *,
    evidence: tuple[int, ...] = (0,),
    source_evidence: tuple[int, ...] | None = None,
    target_evidence: tuple[int, ...] | None = None,
    valid_at: str | None = None,
) -> dict[str, object]:
    source_ids = source_evidence or evidence
    target_ids = target_evidence or evidence
    return {
        "entities": [
            {
                "local_id": 0,
                "name": "Alice",
                "entity_type_id": 0,
                "evidence_segment_ids": list(source_ids),
            },
            {
                "local_id": 1,
                "name": "Bob",
                "entity_type_id": 0,
                "evidence_segment_ids": list(target_ids),
            },
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": fact,
                "valid_at": valid_at,
                "invalid_at": None,
                "evidence_segment_ids": list(evidence),
            }
        ],
    }


def test_compact_schema_matches_the_ticket_contract() -> None:
    assert CONTRACT_NAME == "NewsroomCombinedTemporalExtractionV1"
    assert SCHEMA["type"] == "object"
    assert SCHEMA["additionalProperties"] is False
    assert SCHEMA["required"] == ["entities", "facts"]
    entity = SCHEMA["properties"]["entities"]["items"]
    fact = SCHEMA["properties"]["facts"]["items"]
    assert entity["properties"]["evidence_segment_ids"]["items"]["type"] == "integer"
    assert fact["properties"]["evidence_segment_ids"]["items"]["type"] == "integer"
    assert fact["properties"]["valid_at"]["type"] == ["string", "null"]
    assert fact["properties"]["invalid_at"]["type"] == ["string", "null"]
    assert SCHEMA_DIGEST == digest_canonical(SCHEMA)
    assert SCHEMA_DIGEST.startswith("sha256:")


def test_wire_vocabulary_is_confined_to_untrusted_proposal_terms() -> None:
    prompt = build_compact_prompt(fixture("pair-current").revision).text
    assert "untrusted Entity Mentions" in prompt
    assert "untrusted Relation Proposals" in prompt
    note = (
        _RESEARCH / "2026-08-22-graphiti-combined-temporal-extraction.md"
    ).read_text(encoding="utf-8")
    assert "never Canonical Entities" in note
    assert "EntityNode` / `EntityEdge.fact` remain confined" in note


def test_segmentation_round_trips_retained_bytes_and_uses_integer_ids() -> None:
    body = fixture("pair-current").revision.body
    segments = segment_source(body)
    encoded = b"".join(
        body.encode("utf-8")[item.start_byte : item.end_byte] for item in segments
    )
    assert encoded == body.encode("utf-8")
    assert [item.segment_id for item in segments] == list(range(len(segments)))
    assert all(item.end_byte > item.start_byte for item in segments)


def test_long_chunk_keeps_the_8192_byte_boundary() -> None:
    body = fixture("long-8192").revision.body
    assert len(body.encode("utf-8")) == 8192
    segments = segment_source(body)
    assert b"".join(item.text.encode("utf-8") for item in segments) == body.encode(
        "utf-8"
    )


def test_prompt_retains_every_segment_and_excludes_predecessor_body() -> None:
    case = fixture("correction-revision")
    prompt = build_compact_prompt(case.revision)
    assert case.revision.body in prompt.text
    assert "Technology and Living curriculum" not in prompt.text
    assert "Design and Applied Technology" in prompt.text
    assert case.revision.predecessor_revision_id in prompt.text
    assert str(SCHEMA["required"]) not in prompt.text or "entities" in prompt.text
    for segment in prompt.segments:
        assert f"[{segment.segment_id}]" in prompt.text
    assert "Do not fork" not in prompt.text
    assert "BatchEdgeTimestamps" not in prompt.text
    assert GRAPHITI_MEMORY_PHRASE not in prompt.text


def test_zero_result_makes_exactly_one_generate_response_request() -> None:
    leaf, _case = _extract("zero-result")
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
    assert leaf.failure_code is CombinedTemporalFailureCode.NONE
    assert [call["response_model"] for call in leaf.transport_calls] == [
        CONTRACT_NAME
    ]
    assert leaf.payload == {"entities": [], "facts": []}
    assert leaf.nodes == ()
    assert leaf.edges == ()
    assert leaf.graph_effect_attempted is False
    assert leaf.embedding_skipped is True
    assert leaf.journal_skipped is False
    assert leaf.rollback_skipped is True
    assert leaf.node_resolutions == ()


def test_nonzero_relation_makes_one_request_and_sets_temporal_fields() -> None:
    leaf, case = _extract("pair-current")
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert [call["response_model"] for call in leaf.transport_calls] == [
        CONTRACT_NAME
    ]
    assert "BatchEdgeTimestamps" not in [
        call["response_model"] for call in leaf.transport_calls
    ]
    names = {node.name for node in leaf.nodes}
    assert names == {
        "Legislative Council",
        "Technology and Living curriculum",
    }
    assert len(leaf.edges) == 1
    assert leaf.edges[0].name == "ASKED_ABOUT"
    assert leaf.edges[0].valid_at is None
    assert leaf.edges[0].invalid_at is None
    assert leaf.graph_effect_attempted is False
    assert leaf.embedding_skipped is False
    assert leaf.journal_skipped is False
    assert leaf.rollback_skipped is True
    assert leaf.node_resolutions == ("NEW", "NEW")
    assert all(node.attributes["resolution"] == "NEW" for node in leaf.nodes)
    assert all(edge.fact_embedding == [0.0] for edge in leaf.edges)
    assert all(node.attributes["entity_type_id"] == 0 for node in leaf.nodes)
    assert leaf.edges[0].attributes["evidence_segment_ids"] == [0]
    assert case.gold["facts"][0]["source_local_id"] != case.gold["facts"][0][
        "target_local_id"
    ]


@pytest.mark.parametrize(
    ("name", "expect_valid", "expect_invalid"),
    (
        ("explicit-valid-at", datetime(2026, 8, 20, tzinfo=UTC), None),
        ("explicit-invalid-at", None, datetime(2026, 3, 31, tzinfo=UTC)),
        ("relative-date", datetime(2026, 8, 20, tzinfo=UTC), None),
        ("null-temporal", None, None),
    ),
)
def test_temporal_bounds_parse_from_the_primary_object(
    name: str,
    expect_valid: datetime | None,
    expect_invalid: datetime | None,
) -> None:
    leaf, _case = _extract(name)
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert len(leaf.edges) == 1
    assert leaf.edges[0].valid_at == expect_valid
    assert leaf.edges[0].invalid_at == expect_invalid
    assert len(leaf.transport_calls) == 1


def test_every_success_fixture_connects_entities_and_resolves_evidence() -> None:
    for case in FIXTURES:
        if case.gold["facts"] == []:
            continue
        leaf, _ = _extract(case.name)
        assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
        local_ids = {entity["local_id"] for entity in leaf.payload["entities"]}
        connected: set[int] = set()
        for fact in leaf.payload["facts"]:
            source = fact["source_local_id"]
            target = fact["target_local_id"]
            assert source in local_ids
            assert target in local_ids
            assert source != target
            connected.update((source, target))
            ranges = leaf.evidence_ranges[fact["fact"]]
            retained = b"".join(
                case.revision.body.encode("utf-8")[item.start_byte : item.end_byte]
                for item in ranges
            ).decode("utf-8")
            assert fact["fact"] in retained
        assert connected == local_ids


def test_normalisation_is_stable_under_key_and_order_variation() -> None:
    case = fixture("several-relations")
    shuffled = {
        "facts": list(reversed(case.gold["facts"])),
        "entities": list(reversed(case.gold["entities"])),
    }
    first, _ = _extract("several-relations")
    second = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(shuffled),
        pipeline=_PIPELINE,
    )
    assert first.payload_digest == second.payload_digest
    assert first.payload == second.payload


def test_same_name_entities_keep_distinct_local_identities() -> None:
    leaf, _case = _extract("same-name")
    names = [node.name for node in leaf.nodes]
    assert names.count("Lee") == 2
    assert len({node.uuid for node in leaf.nodes}) == 3
    sources = {edge.source_node_uuid for edge in leaf.edges}
    assert len(sources) == 2


def test_same_name_fact_endpoints_must_share_their_entity_evidence() -> None:
    case = fixture("same-name")
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["source_local_id"] = 2
    payload["facts"][1]["source_local_id"] = 0

    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_fact_must_name_both_endpoints_to_be_self_contained() -> None:
    case = fixture("pair-current")
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["fact"] = "asked about"

    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_fact_evidence_must_be_one_contiguous_source_range() -> None:
    case = fixture("pair-current")
    revision = replace(
        case.revision,
        body="Alice. [OMITTED CONTRADICTORY CONTEXT.] asked Bob.",
    )
    payload = _named_pair_payload(
        "Alice. asked Bob.",
        evidence=(0, 2),
        source_evidence=(0,),
        target_evidence=(2,),
    )

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_entity_evidence_may_span_non_contiguous_facts() -> None:
    case = fixture("pair-current")
    revision = replace(
        case.revision,
        body="Alice asked Bob. Unrelated note. Alice asked Carol.",
    )
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": 0,
                "name": "Alice",
                "entity_type_id": 0,
                "evidence_segment_ids": [0, 2],
            },
            {
                "local_id": 1,
                "name": "Bob",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
            {
                "local_id": 2,
                "name": "Carol",
                "entity_type_id": 0,
                "evidence_segment_ids": [2],
            },
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": target,
                "relation_type": "ASKED",
                "fact": fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [segment],
            }
            for target, fact, segment in (
                (1, "Alice asked Bob.", 0),
                (2, "Alice asked Carol.", 2),
            )
        ],
    }

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert leaf.payload["entities"][0]["evidence_segment_ids"] == [0, 2]


def test_entity_evidence_rejects_an_unrelated_extra_segment() -> None:
    case = fixture("pair-current")
    revision = replace(
        case.revision,
        body="Alice asked Bob. Unrelated note. Carol danced.",
    )
    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(
            _named_pair_payload(
                "Alice asked Bob.",
                source_evidence=(0, 2),
                target_evidence=(0,),
            )
        ),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_implied_relation_is_absent_from_gold_and_rejected_if_emitted() -> None:
    leaf, case = _extract("no-implied-relation")
    types = {edge.name for edge in leaf.edges}
    assert "WORKS_FOR" not in types
    assert types == {"ATTENDED", "HOSTED"}

    forged = {
        "entities": case.gold["entities"],
        "facts": [
            *case.gold["facts"],
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "WORKS_FOR",
                "fact": "Ms Chan works for the Education Bureau.",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
        ],
    }
    failed = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(forged),
    )
    assert failed.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert failed.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED
    assert len(failed.transport_calls) == 1
    assert failed.graph_effect_attempted is False
    assert failed.raw_output_digest is not None

    lexical = {
        "entities": case.gold["entities"],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 2,
                "relation_type": "WORKS_FOR",
                "fact": "Ms Chan attended the briefing.",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    rejected = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(lexical),
    )
    assert rejected.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert rejected.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize("name", [case.name for case in MALFORMED_CASES])
def test_malformed_primary_object_fails_closed_without_retry(name: str) -> None:
    case = next(item for item in MALFORMED_CASES if item.name == name)
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.payload),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is case.failure_code
    assert len(leaf.transport_calls) == 1
    assert leaf.nodes == ()
    assert leaf.edges == ()
    assert leaf.graph_effect_attempted is False


def test_relative_date_text_is_not_accepted_as_a_timestamp() -> None:
    case = fixture("relative-date")
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["valid_at"] = "yesterday"
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(payload),
    )
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert len(leaf.transport_calls) == 1


@pytest.mark.parametrize(
    ("body", "valid_at"),
    (
        ("Last week Alice asked Bob.", None),
        ("At 2026-08-20T18:30:00Z Alice asked Bob.", "2026-08-20T00:00:00Z"),
    ),
)
def test_temporal_cues_require_the_exact_source_time(
    body: str,
    valid_at: str | None,
) -> None:
    case = fixture("pair-current")
    revision = replace(case.revision, body=body)

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(_named_pair_payload(body, valid_at=valid_at)),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID


def test_exact_source_timestamp_is_retained() -> None:
    case = fixture("pair-current")
    body = "At 2026-08-20T18:30:00Z Alice asked Bob."
    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(
            _named_pair_payload(body, valid_at="2026-08-20T18:30:00Z")
        ),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert leaf.edges[0].valid_at == datetime(2026, 8, 20, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "source_timestamp",
    (
        "2026-08-20T19:30:00.123+01:00",
        "2026-08-20T19:30:00.123+0100",
        "2026-08-20T19:30:00.123+01",
        "2026-08-20T19:30:00,123+01:00",
    ),
)
def test_offset_source_timestamp_keeps_the_exact_instant(
    source_timestamp: str,
) -> None:
    case = fixture("pair-current")
    body = f"At {source_timestamp} Alice asked Bob."
    revision = replace(case.revision, body=body)

    wrong = extract_combined_temporal(
        revision,
        transport=_FakeTransport(
            _named_pair_payload(body, valid_at="2026-08-20T00:00:00.123Z")
        ),
        pipeline=_PIPELINE,
    )
    exact = extract_combined_temporal(
        revision,
        transport=_FakeTransport(
            _named_pair_payload(body, valid_at="2026-08-20T18:30:00.123Z")
        ),
        pipeline=_PIPELINE,
    )

    assert wrong.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert exact.edges[0].valid_at == datetime(
        2026, 8, 20, 18, 30, 0, 123_000, tzinfo=UTC
    )


@pytest.mark.parametrize("separator", ("and", ", after"))
@pytest.mark.parametrize(
    "other_fact",
    (
        "Bob visited Paris on 2026-02-01.",
        "Bob met Carol on 2026-02-01.",
        "bob saw carol on 2026-02-01.",
    ),
)
def test_temporal_cue_must_belong_to_the_fact_clause(
    separator: str, other_fact: str
) -> None:
    case = fixture("pair-current")
    body = (
        f"On 2026-01-01 Alice JOINED Acme {separator} "
        f"{other_fact}"
    )
    revision = replace(case.revision, body=body)
    payload = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("Alice", "Acme"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "JOINED",
                "fact": body,
                "valid_at": "2026-02-01T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    payload["facts"][0]["valid_at"] = "2026-01-01T00:00:00Z"
    exact = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    "body",
    (
        "On 2026-01-01, Alice asked Bob.",
        "On 2026-01-01, according to officials, Alice asked Bob.",
        "On 2026-01-01, per officials, Alice asked Bob.",
        "On 2026-01-01, officials stated, Alice asked Bob.",
        "On 2026-01-01, sources say, Alice asked Bob.",
        "Alice asked Bob (on 2026-01-01).",
        "Alice asked Bob — effective 2026-01-01.",
        "Alice asked Bob, effective on 2026-01-01.",
        "Alice asked Bob, effective at 2026-01-01.",
        "Alice asked Bob, dated 2026-01-01.",
        "Alice asked Bob, around 2026-01-01.",
        "Alice asked Bob, by 2026-01-01.",
    ),
)
def test_temporal_modifier_delimiters_remain_attributed(body: str) -> None:
    case = fixture("pair-current")
    revision = replace(case.revision, body=body)

    omitted = extract_combined_temporal(
        revision,
        transport=_FakeTransport(_named_pair_payload(body)),
        pipeline=_PIPELINE,
    )
    exact = extract_combined_temporal(
        revision,
        transport=_FakeTransport(
            _named_pair_payload(body, valid_at="2026-01-01T00:00:00Z")
        ),
        pipeline=_PIPELINE,
    )

    assert omitted.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


def test_lowercase_unrelated_assertion_does_not_supply_fact_time() -> None:
    case = fixture("pair-current")
    body = "alice asked bob, charlie joined acme on 2026-01-01."
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("alice", "bob"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": "alice asked bob",
                "valid_at": "2026-01-01T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    wrong = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    payload["facts"][0]["valid_at"] = None
    exact = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert wrong.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


def test_invalid_source_date_is_a_typed_failed_leaf() -> None:
    case = fixture("pair-current")
    body = "On 2026-02-30 Alice asked Bob."
    revision = replace(case.revision, body=body)

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(_named_pair_payload(body)),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID


def test_correction_dash_cannot_join_old_and_corrected_attribution() -> None:
    case = fixture("pair-current")
    body = "Alice asked Bob. Correction — Alice did not ask Bob."
    revision = replace(case.revision, body=body)

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(
            _named_pair_payload("Alice asked Bob.", evidence=(0, 1))
        ),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize(
    ("body", "evidence"),
    (
        ("Alice JOINED Acme. Alice didn’t JOIN Acme.", [0, 1]),
        ("Alice JOINED Acme and Alice didn’t JOIN Acme.", [0]),
        ("Alice JOINED Acme. Alice hasn't JOINED Acme.", [0, 1]),
        ("Alice JOINED Acme. Alice won’t JOIN Acme.", [0, 1]),
        ("Alice JOINED Acme. Alice cannot JOIN Acme.", [0, 1]),
    ),
)
def test_plain_negation_cannot_join_contradictory_attribution(
    body: str, evidence: list[int]
) -> None:
    case = fixture("pair-current")
    revision = replace(case.revision, body=body)
    payload = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": evidence,
            }
            for local_id, name in enumerate(("Alice", "Acme"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "JOINED",
                "fact": "Alice JOINED Acme.",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": evidence,
            }
        ],
    }

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED

    positive_body = "Alice JOINED Acme without delay."
    for entity in payload["entities"]:
        entity["evidence_segment_ids"] = [0]
    payload["facts"][0].update(
        fact=positive_body,
        evidence_segment_ids=[0],
    )
    positive = extract_combined_temporal(
        replace(case.revision, body=positive_body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    assert positive.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    ("body", "relation_type", "fact"),
    (
        (
            "Alice is a member of Acme. Alice isn’t a member of Acme.",
            "IS_MEMBER_OF",
            "Alice is a member of Acme.",
        ),
        (
            "Alice is a member of Acme, Alice isn’t a member of Acme.",
            "IS_MEMBER_OF",
            "Alice is a member of Acme",
        ),
        (
            "Alice is a member of Acme — Alice isn’t a member of Acme.",
            "IS_MEMBER_OF",
            "Alice is a member of Acme",
        ),
        (
            "Alice is a member of Acme (Alice isn’t a member of Acme).",
            "IS_MEMBER_OF",
            "Alice is a member of Acme",
        ),
        (
            "Alice will join Acme. Alice won’t join Acme.",
            "WILL_JOIN",
            "Alice will join Acme.",
        ),
        (
            "Alice can join Acme. Alice cannot join Acme.",
            "CAN_JOIN",
            "Alice can join Acme.",
        ),
    ),
)
def test_unicode_contraction_cannot_join_contradictory_attribution(
    body: str,
    relation_type: str,
    fact: str,
) -> None:
    case = fixture("pair-current")
    revision = replace(case.revision, body=body)
    evidence = [item.segment_id for item in segment_source(body)]
    payload = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": evidence,
            }
            for local_id, name in enumerate(("Alice", "Acme"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": relation_type,
                "fact": fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": evidence,
            }
        ],
    }

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_plain_no_cannot_join_contradictory_attribution() -> None:
    case = fixture("pair-current")
    body = (
        "Alice has a contract with Acme. "
        "Alice has no contract with Acme."
    )
    payload = _named_pair_payload(
        "Alice has a contract with Acme.", evidence=(0, 1)
    )
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "HAS_CONTRACT_WITH"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_entity_name_must_be_a_complete_source_name() -> None:
    case = fixture("pair-current")
    body = "Annabelle JOINED Acme."
    payload = _named_pair_payload(body)
    payload["entities"][0]["name"] = "Ann"  # type: ignore[index]
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "JOINED"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize(
    ("body", "partial_name"),
    (
        ("Ann-Marie JOINED Acme.", "Ann"),
        ("O'Brien JOINED Acme.", "O"),
        ("Hong-Kong JOINED Acme.", "Hong"),
    ),
)
def test_entity_name_cannot_be_part_of_a_connected_name(
    body: str, partial_name: str
) -> None:
    case = fixture("pair-current")
    payload = _named_pair_payload(body)
    payload["entities"][0]["name"] = partial_name  # type: ignore[index]
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "JOINED"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize(
    ("body", "partial_name"),
    (
        ("Анна JOINED Acme.", "Ан"),
        ("Αννα JOINED Acme.", "Αν"),
        ("さくら JOINED Acme.", "さ"),
        ("123Alice JOINED Acme.", "123"),
        ("3Mcorp JOINED Acme.", "3M"),
        ("AliceБоб JOINED Acme.", "Alice"),
        ("陳志明1 JOINED Acme.", "陳志明"),
        ("陳志明Alice JOINED Acme.", "陳志明"),
        ("教育局2 JOINED Acme.", "教育局"),
        ("Alice支持者 JOINED Acme.", "Alice"),
        ("Alice質詢者 JOINED Acme.", "Alice"),
    ),
)
def test_entity_name_cannot_be_part_of_another_unicode_name(
    body: str, partial_name: str
) -> None:
    case = fixture("pair-current")
    payload = _named_pair_payload(body)
    payload["entities"][0]["name"] = partial_name  # type: ignore[index]
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "JOINED"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_contract_number_is_not_a_negation() -> None:
    case = fixture("pair-current")
    body = (
        "Alice has contract with Acme. "
        "Alice has contract no 5 with Acme."
    )
    payload = _named_pair_payload(
        "Alice has contract with Acme.", evidence=(0, 1)
    )
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "HAS_CONTRACT_WITH"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    ("body", "names", "relation_type"),
    (
        ("立法會質詢教育局。", ("立法會", "教育局"), "QUESTIONED"),
        ("Alice質詢教育局。", ("Alice", "教育局"), "QUESTIONED"),
        ("陳志明是教育局成員。", ("陳志明", "教育局"), "IS_MEMBER_OF"),
        ("立法會向教育局提問。", ("立法會", "教育局"), "ASKED"),
        ("陳志明與教育局簽約。", ("陳志明", "教育局"), "HAS_CONTRACT_WITH"),
    ),
)
def test_traditional_chinese_fact_is_source_grounded(
    body: str, names: tuple[str, str], relation_type: str
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(names)
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": relation_type,
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    ("body", "names", "relation_type"),
    (
        ("陳志明支持教育局。", ("陳志", "教育局"), "SUPPORTED"),
        ("陳志明支持教育局。", ("陳志明", "教育局"), "CONDEMNED"),
        ("立法會與教育局。", ("立法會", "教育局"), "QUESTIONED"),
        ("立法會質詢教育局。", ("立法會", "教育"), "QUESTIONED"),
        ("陳志明 SUPPORTED 教育局.", ("陳志", "教育局"), "SUPPORTED"),
        ("陳志明 SUPPORTED 教育局.", ("陳志明", "教育"), "SUPPORTED"),
        ("1Alice質詢教育局2。", ("Alice", "教育局"), "QUESTIONED"),
        ("Alice質詢教育局2。", ("Alice", "教育局"), "QUESTIONED"),
        ("X立法會質詢教育局Y。", ("立法會", "教育局"), "QUESTIONED"),
    ),
)
def test_traditional_chinese_grounding_fails_closed(
    body: str, names: tuple[str, str], relation_type: str
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(names)
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": relation_type,
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_traditional_chinese_date_keeps_source_temporal_semantics() -> None:
    case = fixture("pair-current")
    body = "立法會質詢教育局，日期為2026年1月1日。"
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("立法會", "教育局"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "QUESTIONED",
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    omitted = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    payload["facts"][0]["valid_at"] = "2026-01-01T00:00:00Z"
    exact = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert omitted.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


def test_traditional_chinese_sentences_keep_separate_fact_dates() -> None:
    case = fixture("pair-current")
    first = "立法會支持教育局，日期為2026年1月1日。"
    body = first + "陳志明支持醫管局，日期為2026年2月1日。"
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("立法會", "教育局"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": first,
                "valid_at": "2026-01-01T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert len(segment_source(body)) == 2
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert leaf.edges[0].valid_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_traditional_chinese_invalidation_keeps_bound_semantics() -> None:
    case = fixture("pair-current")
    body = "立法會支持教育局，截至2026年1月1日。"
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("立法會", "教育局"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": body,
                "valid_at": "2026-01-01T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    wrong = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    payload["facts"][0]["valid_at"] = None
    payload["facts"][0]["invalid_at"] = "2026-01-01T00:00:00Z"
    exact = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert wrong.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    ("body", "fact"),
    (
        ("昨日，立法會支持教育局。", "立法會支持教育局。"),
        ("立法會支持教育局，日期為昨日。", "立法會支持教育局，日期為昨日。"),
    ),
)
def test_traditional_chinese_relative_date_uses_reference_time(
    body: str, fact: str
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("立法會", "教育局"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    omitted = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    payload["facts"][0]["valid_at"] = "2026-08-20T00:00:00Z"
    exact = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert omitted.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


def test_relative_date_word_inside_entity_name_is_not_a_temporal_cue() -> None:
    case = fixture("pair-current")
    body = "今日新聞支持教育局。"
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("今日新聞", "教育局"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    exact = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )
    payload["facts"][0]["valid_at"] = "2026-08-21T00:00:00Z"
    fabricated = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert exact.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert fabricated.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID


def test_no_doubt_is_not_a_negation() -> None:
    case = fixture("pair-current")
    body = (
        "Alice is a member of Acme. "
        "No doubt Alice is a member of Acme."
    )
    payload = _named_pair_payload(
        "Alice is a member of Acme.", evidence=(0, 1)
    )
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "IS_MEMBER_OF"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


def test_anything_but_is_a_negation() -> None:
    case = fixture("pair-current")
    body = (
        "Alice is a member of Acme. "
        "Alice is anything but a member of Acme."
    )
    payload = _named_pair_payload(
        "Alice is a member of Acme.", evidence=(0, 1)
    )
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "IS_MEMBER_OF"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize(
    ("body", "fact", "evidence"),
    (
        (
            "立法會支持教育局。立法會不支持教育局。",
            "立法會支持教育局。",
            (0, 1),
        ),
        (
            "立法會支持教育局 及 立法會不支持教育局。",
            "立法會支持教育局",
            (0,),
        ),
        (
            "立法會支持教育局 及 立法會 did not SUPPORT 教育局.",
            "立法會支持教育局",
            (0,),
        ),
    ),
)
def test_traditional_chinese_negation_cannot_join_positive_attribution(
    body: str, fact: str, evidence: tuple[int, ...]
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(("立法會", "教育局"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": list(evidence),
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize(
    ("body", "names", "relation_type"),
    (
        ("Alice did not JOIN Acme.", ("Alice", "Acme"), "JOINED"),
        ("立法會不支持教育局。", ("立法會", "教育局"), "SUPPORTED"),
    ),
)
def test_negative_assertion_cannot_become_a_positive_relation(
    body: str, names: tuple[str, str], relation_type: str
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(names)
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": relation_type,
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_negative_assertion_can_keep_a_negative_relation_type() -> None:
    case = fixture("pair-current")
    body = "Alice did not JOIN Acme."
    payload = _named_pair_payload(body)
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "DID_NOT_JOIN"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    ("body", "names", "relation_type"),
    (
        ("立法會不支持教育局。", ("立法會", "教育局"), "NOT_SUPPORTED"),
        ("陳志明不是教育局成員。", ("陳志明", "教育局"), "IS_NOT_MEMBER_OF"),
        ("陳志明不是教育局成員。", ("陳志明", "教育局"), "NOT_MEMBER_OF"),
    ),
)
def test_traditional_chinese_negative_relation_keeps_source_polarity(
    body: str, names: tuple[str, str], relation_type: str
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(names)
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": relation_type,
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


@pytest.mark.parametrize(
    ("body", "names"),
    (
        ("立法會無支持無。", ("立法會", "無")),
        ("Alice never SUPPORTED never.", ("Alice", "never")),
    ),
)
def test_negation_equal_to_endpoint_name_remains_syntactic(
    body: str, names: tuple[str, str]
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(names)
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


@pytest.mark.parametrize(
    ("body", "names"),
    (
        ("無國界醫生支持教育局。", ("無國界醫生", "教育局")),
        ("立法會支持未來基金。", ("立法會", "未來基金")),
        ("立法會支持無條件教育基金。", ("立法會", "無條件教育基金")),
        (
            "無國界醫生表示 無國界醫生支持教育局。",
            ("無國界醫生", "教育局"),
        ),
        ("立法會支持未來基金 未來基金回應。", ("立法會", "未來基金")),
        ("毫無疑問 立法會支持教育局。", ("立法會", "教育局")),
        ("立法會支持教育局 無疑是正確決定。", ("立法會", "教育局")),
        ("立法會支持教育局 未來會繼續合作。", ("立法會", "教育局")),
    ),
)
def test_non_polarity_chinese_words_do_not_negate_relation(
    body: str, names: tuple[str, str]
) -> None:
    case = fixture("pair-current")
    payload: dict[str, Any] = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            }
            for local_id, name in enumerate(names)
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "SUPPORTED",
                "fact": body,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS


def test_repeated_fact_with_conflicting_dates_is_temporally_ambiguous() -> None:
    case = fixture("pair-current")
    body = (
        "On 2026-01-01 Alice JOINED Acme. "
        "On 2026-02-01 Alice JOINED Acme."
    )
    revision = replace(case.revision, body=body)
    evidence = [item.segment_id for item in segment_source(body)]
    payload = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": evidence,
            }
            for local_id, name in enumerate(("Alice", "Acme"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "JOINED",
                "fact": "Alice JOINED Acme.",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": evidence,
            }
        ],
    }

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID


def test_distinct_same_relation_facts_keep_their_own_dates() -> None:
    case = fixture("pair-current")
    body = (
        "On 2026-01-01 Alice JOINED Acme as an employee. "
        "On 2026-02-01 Alice JOINED Acme as a director."
    )
    revision = replace(case.revision, body=body)
    payload = {
        "entities": [
            {
                "local_id": local_id,
                "name": name,
                "entity_type_id": 0,
                "evidence_segment_ids": [0, 1],
            }
            for local_id, name in enumerate(("Alice", "Acme"))
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "JOINED",
                "fact": f"Alice JOINED Acme as {role}.",
                "valid_at": f"2026-0{month}-01T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": [month - 1],
            }
            for month, role in ((1, "an employee"), (2, "a director"))
        ],
    }

    leaf = extract_combined_temporal(
        revision,
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
    assert {edge.fact: edge.valid_at for edge in leaf.edges} == {
        "Alice JOINED Acme as an employee.": datetime(2026, 1, 1, tzinfo=UTC),
        "Alice JOINED Acme as a director.": datetime(2026, 2, 1, tzinfo=UTC),
    }


def test_temporal_modifier_between_assertions_does_not_merge_them() -> None:
    case = fixture("pair-current")
    body = "Alice asked Bob, yesterday, Alice did not ask Bob."
    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(
            _named_pair_payload(
                "Alice asked Bob",
                evidence=(0,),
                valid_at="2026-08-20T00:00:00Z",
            )
        ),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_han_assertion_with_date_is_not_a_temporal_modifier() -> None:
    case = fixture("pair-current")
    body = (
        "Alice JOINED Acme, 張三支持李四日期為2026年2月2日, "
        "Bob JOINED Charlie."
    )
    payload = _named_pair_payload(
        "Alice JOINED Acme",
        valid_at="2026-02-02T00:00:00Z",
    )
    payload["entities"][1]["name"] = "Acme"  # type: ignore[index]
    payload["facts"][0]["relation_type"] = "JOINED"  # type: ignore[index]

    leaf = extract_combined_temporal(
        replace(case.revision, body=body),
        transport=_FakeTransport(payload),
        pipeline=_PIPELINE,
    )

    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID


def test_correction_revision_does_not_contaminate_the_prompt() -> None:
    leaf, case = _extract("correction-revision")
    names = {node.name for node in leaf.nodes}
    assert "Design and Applied Technology" in names
    assert "Technology and Living curriculum" not in names
    assert case.revision.predecessor_body not in leaf.prompt.text


def test_edge_guard_keeps_primary_temporal_fields() -> None:
    leaf, _ = _extract("explicit-valid-at")
    assert leaf.edges[0].valid_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert leaf.guarded_edges[0].valid_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert leaf.guarded_edges[0].invalid_at is None


def test_ingest_time_does_not_replace_source_reference_time() -> None:
    leaf, case = _extract("pair-current")
    ingested = datetime(2026, 8, 22, 12, tzinfo=UTC)
    source = datetime(2026, 8, 21, tzinfo=UTC)
    assert case.revision.ingested_at == INGESTED_AT
    assert leaf.nodes[0].created_at == ingested
    assert leaf.edges[0].created_at == ingested
    assert leaf.edges[0].reference_time == source
    assert leaf.temporal_basis == "SOURCE_PUBLISHED"
    assert leaf.edges[0].attributes["temporal_policy"] == TEMPORAL_POLICY_VERSION


def test_episode_identity_binds_source_digests_and_source_timestamps() -> None:
    leaf, case = _extract("pair-current")
    assert leaf.ingest_id == case.revision.ingest_id
    assert leaf.edges[0].episodes == [case.revision.ingest_id]
    assert leaf.configuration_digest == configuration_digest()
    shifted = replace(case.revision, published_at="2026-01-01T00:00:00Z")
    other = extract_combined_temporal(
        shifted,
        transport=_FakeTransport(case.gold),
        pipeline=_PIPELINE,
    )
    assert other.ingest_id != leaf.ingest_id
    assert {node.uuid for node in other.nodes} != {node.uuid for node in leaf.nodes}
    assert {edge.uuid for edge in other.edges} != {edge.uuid for edge in leaf.edges}
    later = extract_combined_temporal(
        replace(case.revision, ingested_at="2026-08-23T00:00:00Z"),
        transport=_FakeTransport(case.gold),
        pipeline=_PIPELINE,
    )
    assert later.ingest_id == leaf.ingest_id
    assert {node.uuid for node in later.nodes} == {node.uuid for node in leaf.nodes}
    assert later.nodes[0].created_at != leaf.nodes[0].created_at
    assert leaf.prompt_digest is not None
    assert case.revision.ingest_id == leaf.ingest_id


def test_leaf_receipt_retains_raw_digest_usage_and_versions() -> None:
    leaf, _case = _extract("pair-current")
    call = leaf.transport_calls[0]
    assert leaf.raw_output_digest is not None
    assert leaf.raw_output_digest.startswith("sha256:")
    assert call["raw_output_digest"] == leaf.raw_output_digest
    assert leaf.framework_version == GRAPHITI_CORE_RELEASE
    assert leaf.model_version is None
    assert leaf.prompt_digest is not None
    assert leaf.prompt_digest.startswith("sha256:")
    assert leaf.invocation_count == 1
    assert leaf.token_usage["basis"] == UNMEASURED
    assert leaf.provider_cost is None
    wrapped = extract_combined_temporal(
        fixture("pair-current").revision,
        transport=_FakeTransport("Here is the JSON:\n{}"),
    )
    assert wrapped.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert wrapped.raw_output_digest is not None
    assert wrapped.transport_calls[0]["raw_output_digest"] == wrapped.raw_output_digest


def test_live_packet_is_owner_gated_and_redacted() -> None:
    payload = json.loads(LIVE_PACKET_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == (
        "newsroom.graphiti-combined-temporal-live-packet.v1"
    )
    assert payload["issue"] == 747
    assert payload["parent_issue"] == 739
    assert payload["live_authority"]["authorised"] is False
    assert payload["live_authority"]["requires_explicit_owner_instruction"] is True
    assert payload["live_authority"]["maximum_cursor_sdk_model_leaves"] == 8
    assert payload["live_authority"]["neo4j_mutation_permitted"] is False
    raw = LIVE_PACKET_PATH.read_text(encoding="utf-8")
    for forbidden in ("CURSOR_API_KEY", "/Users/", '"prompt":', '"result":'):
        assert forbidden not in raw


def test_measurements_record_one_leaf_and_beat_the_separate_pair_baseline() -> None:
    committed = json.loads(MEASUREMENTS_PATH.read_text(encoding="utf-8"))
    assert committed["hermetic_separate_pair_chat_tokens"] == 46_105
    assert committed["do_not_compare_against_zero_edge_combined_as_complete"] is True
    assert committed["token_usage_basis"] == "UNMEASURED"
    assert committed["provider_free_proxy"] == "prompt_and_schema_bytes"
    assert committed["schema_digest"] == SCHEMA_DIGEST
    assert committed["graphiti_core_version"] == "0.29.3"
    for case in FIXTURES:
        prompt = build_compact_prompt(case.revision)
        recorded = committed["fixtures"][case.name]
        assert recorded["compact_chat_leaves"] == 1
        assert recorded["compact_prompt_bytes"] == len(prompt.text.encode("utf-8"))
        assert recorded["compact_schema_bytes"] == len(canonical_json_bytes(SCHEMA))
    pair = committed["fixtures"]["pair-current"]
    assert pair["upstream_nonzero_chat_leaves"] == 2
    assert pair["leaf_count_reduction"] == 1
    assert pair["compact_prompt_bytes"] < pair["upstream_combined_prompt_bytes"]
    assert pair["compact_schema_bytes"] < (
        pair["upstream_combined_schema_bytes"]
        + pair["upstream_batch_timestamp_schema_bytes"]
    )
    assert pair["entity_name_bytes_avoided"] > 0
    assert pair["evidence_bytes_avoided"] > 0


def test_research_note_recommends_without_amending_ging_010() -> None:
    note = (
        _RESEARCH / "2026-08-22-graphiti-combined-temporal-extraction.md"
    ).read_text(encoding="utf-8")
    assert "GING-010" in note
    assert "does not amend `GING-010`" in note
    assert "#731" in note
    assert "QUALIFIED_PROVIDER_FREE" in note
    assert "owner-gated" in note
    assert "Neo4jMutationGuard" in note
    assert "LOCAL_NEW" not in note
    assert "RESOLUTION_DEFERRED" not in note


def test_upstream_zero_and_nonzero_call_shapes_are_pinned() -> None:
    committed = json.loads(CALL_SHAPES_PATH.read_text(encoding="utf-8"))
    assert committed["schema_version"] == (
        "newsroom.graphiti-combined-temporal-call-shapes.v1"
    )
    assert committed["graphiti_core_version"] == "0.29.3"
    assert tuple(committed["zero_edge"]) == ("CombinedExtraction",)
    assert tuple(committed["nonzero_edge"]) == (
        "CombinedExtraction",
        "BatchEdgeTimestamps",
    )


def test_segment_source_rejects_non_positive_max_bytes() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        segment_source("hello", max_bytes=0)
    with pytest.raises(ValueError, match="positive integer"):
        segment_source("hello", max_bytes=-1)
    with pytest.raises(ValueError, match="positive integer"):
        segment_source("hello", max_bytes=True)
    parts = segment_source("ab", max_bytes=1)
    assert [item.text for item in parts] == ["a", "b"]
    with pytest.raises(ValueError, match="valid UTF-8"):
        segment_source("漢", max_bytes=1)
    han = segment_source("漢", max_bytes=3)
    assert [item.text for item in han] == ["漢"]


def test_raw_receipt_is_exact_and_survives_malformed_mapping() -> None:
    revision = fixture("pair-current").revision
    empty = extract_combined_temporal(revision, transport=_FakeTransport([]))
    one = extract_combined_temporal(revision, transport=_FakeTransport([1]))
    two = extract_combined_temporal(revision, transport=_FakeTransport([2]))
    assert empty.raw_output_digest != one.raw_output_digest
    assert one.raw_output_digest != two.raw_output_digest
    assert empty.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    floated = extract_combined_temporal(
        revision,
        transport=_FakeTransport({"entities": [], "facts": [], "x": 1.5}),
    )
    assert floated.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert floated.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    assert floated.raw_output_digest is not None
    assert floated.raw_output_digest.startswith("sha256:")


def test_content_digest_follows_the_existing_chunk_pattern() -> None:
    revision = fixture("pair-current").revision
    assert revision.content_digest == content_digest(
        headline="", body=revision.body, canonical_url=""
    )


def test_prompt_or_schema_binding_mints_a_new_ingest_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaf, case = _extract("pair-current")
    shifted = extract_combined_temporal(
        replace(case.revision, predecessor_revision_id="other-rev"),
        transport=_FakeTransport(case.gold),
        pipeline=_PIPELINE,
    )
    assert shifted.ingest_id != leaf.ingest_id
    assert {node.uuid for node in shifted.nodes} != {node.uuid for node in leaf.nodes}
    assert {edge.uuid for edge in shifted.edges} != {edge.uuid for edge in leaf.edges}
    monkeypatch.setattr(
        "newsroom.graphiti_adapter.combined_temporal_contract.SCHEMA_DIGEST",
        "sha256:" + "ab" * 32,
    )
    schema_shifted = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
        pipeline=_PIPELINE,
    )
    assert schema_shifted.ingest_id != leaf.ingest_id
    assert {node.uuid for node in schema_shifted.nodes} != {
        node.uuid for node in leaf.nodes
    }
    assert configuration_digest() == leaf.configuration_digest


def test_generation_and_episode_identity_are_bound_to_the_ingest_key() -> None:
    revision = fixture("pair-current").revision
    assert revision.group_id == GRAPHITI_WORKSPACE_GROUP
    assert replace(revision, group_id="other-generation").ingest_id != revision.ingest_id
    assert replace(revision, episode_uuid="other-episode").ingest_id != revision.ingest_id


def test_pipeline_failure_retains_rollback_outcome() -> None:
    class _FailedPipeline(_ProviderFreePipeline):
        def execute(self, **_kwargs: Any) -> CombinedTemporalPipelineResult:
            raise CombinedTemporalPipelineError(
                "embed failed",
                graph_effect_attempted=True,
                rollback_completed=True,
            )

    case = fixture("pair-current")
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
        pipeline=_FailedPipeline(),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.PIPELINE_FAILED
    assert leaf.embedding_skipped is False
    assert leaf.journal_skipped is False
    assert leaf.rollback_skipped is False
    assert leaf.graph_effect_attempted is True
    assert leaf.nodes == ()
    assert leaf.edges == ()


def test_unknown_pipeline_failure_does_not_fabricate_effect_evidence() -> None:
    class _UnknownPipeline(_ProviderFreePipeline):
        def execute(self, **_kwargs: Any) -> CombinedTemporalPipelineResult:
            raise RuntimeError("unknown pre-effect failure")

    case = fixture("pair-current")
    with pytest.raises(RuntimeError, match="unknown pre-effect failure"):
        extract_combined_temporal(
            case.revision,
            transport=_FakeTransport(case.gold),
            pipeline=_UnknownPipeline(),
        )


def test_partial_pipeline_is_rejected_before_provider_work() -> None:
    class _PartialPipeline:
        def execute(self, **_kwargs: Any) -> CombinedTemporalPipelineResult:
            raise AssertionError("pipeline must not execute")

    class _NoCallTransport:
        def generate_response(self, **_kwargs: Any) -> CombinedTemporalTransportResult:
            raise AssertionError("provider must not execute")

    with pytest.raises(CombinedTemporalPipelineError, match="pipeline is incomplete"):
        extract_combined_temporal(
            fixture("pair-current").revision,
            transport=_NoCallTransport(),
            pipeline=_PartialPipeline(),
        )


def test_transport_failure_durably_completes_the_prepared_attempt() -> None:
    class _Journal(_ProviderFreePipeline):
        completed = False

        def complete_failure(
            self, receipt: Mapping[str, object]
        ) -> Mapping[str, object]:
            self.completed = True
            return receipt

    class _FailedTransport:
        def generate_response(self, **_kwargs: Any) -> CombinedTemporalTransportResult:
            raise RuntimeError("transport failed")

    pipeline = _Journal()
    leaf = extract_combined_temporal(
        fixture("pair-current").revision,
        transport=_FailedTransport(),
        pipeline=pipeline,
    )

    assert pipeline.completed is True
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.PIPELINE_FAILED
    assert leaf.journal_skipped is False


@pytest.mark.parametrize(
    "name",
    ("explicit-valid-at", "explicit-invalid-at", "relative-date"),
)
def test_omitted_temporal_bounds_fail_when_evidence_has_a_cue(name: str) -> None:
    case = fixture(name)
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["valid_at"] = None
    payload["facts"][0]["invalid_at"] = None
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(payload),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID
    assert leaf.graph_effect_attempted is False


def test_duplicate_json_facts_key_is_a_typed_failure() -> None:
    leaf = extract_combined_temporal(
        fixture("pair-current").revision,
        transport=_FakeTransport(
            '{"entities":[],"facts":[{"bad":true}],"facts":[]}'
        ),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    assert leaf.payload is None


def test_huge_json_integer_is_a_typed_failure() -> None:
    leaf = extract_combined_temporal(
        fixture("pair-current").revision,
        transport=_FakeTransport(
            '{"entities":[],"facts":[],"x":' + ("1" * 5_000) + "}"
        ),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    assert leaf.payload is None


@pytest.mark.parametrize(
    "name",
    ("explicit-valid-at", "explicit-invalid-at", "relative-date"),
)
def test_temporal_bounds_cannot_be_swapped(name: str) -> None:
    case = fixture(name)
    payload = json.loads(json.dumps(case.gold))
    fact = payload["facts"][0]
    fact["valid_at"], fact["invalid_at"] = fact["invalid_at"], fact["valid_at"]
    leaf = extract_combined_temporal(case.revision, transport=_FakeTransport(payload))
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.TEMPORAL_INVALID


def test_entity_name_tokens_cannot_masquerade_as_a_relation_type() -> None:
    case = fixture("pair-current")
    payload = json.loads(json.dumps(case.gold))
    payload["facts"][0]["relation_type"] = "LEGISLATIVE_COUNCIL"
    leaf = extract_combined_temporal(case.revision, transport=_FakeTransport(payload))
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED


def test_nonzero_extraction_requires_an_explicit_pipeline() -> None:
    case = fixture("pair-current")
    leaf = extract_combined_temporal(
        case.revision,
        transport=_FakeTransport(case.gold),
    )
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_ATTEMPT_FAILURE
    assert leaf.failure_code is CombinedTemporalFailureCode.PIPELINE_FAILED
    assert leaf.embedding_skipped is True
    assert leaf.journal_skipped is True
