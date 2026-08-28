"""Provider-free #790 Step 16 governed proposal projection reproductions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.types import UtcTimestamp
from newsroom.graphiti_adapter.combined_temporal_contract import (
    SourceRevisionInput,
    build_compact_prompt,
)
from newsroom.graphiti_adapter.combined_temporal_evidence import segment_source
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CombinedTemporalOutcome,
    CombinedTemporalTransportResult,
    extract_combined_temporal,
)
from newsroom.graphiti_adapter.combined_temporal_projection import (
    ATOM_LOCAL_FAILURE_CODES,
    FACT_LOOP_ATOM_LOCAL_CODES,
    PAYLOAD_FATAL_FAILURE_CODES,
    PROJECTION_POLICY_VERSION,
    classify_combined_temporal_failure,
    project_governed_proposals,
)
from newsroom.graphiti_adapter.combined_temporal_response import (
    parse_payload,
    raw_digest,
)
from newsroom.graphiti_adapter.combined_temporal_types import (
    CombinedTemporalError,
    CombinedTemporalFailureCode,
)
from newsroom.graphiti_adapter.evaluation_packet import GRAPHITI_CORE_RELEASE

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "issue_790_step13_15_raw"


def _load_step(step: int) -> dict:
    return json.loads((_FIXTURES / f"step{step}.json").read_text(encoding="utf-8"))


def _revision(body: str, reference_time: str) -> SourceRevisionInput:
    return SourceRevisionInput(
        body=body,
        revision_id="rev-step16",
        source_id="src-step16",
        item_key="item-step16",
        representation_digest="sha256:" + "ab" * 32,
        published_at=reference_time,
        updated_at=None,
        observed_at=reference_time,
        ingested_at=reference_time,
    )


class _FakeTransport:
    def __init__(self, raw: object) -> None:
        self.raw = raw
        self.calls = 0

    def generate_response(self, **kwargs: object) -> CombinedTemporalTransportResult:
        del kwargs
        self.calls += 1
        return CombinedTemporalTransportResult(
            raw=self.raw,
            framework_version=GRAPHITI_CORE_RELEASE,
            model_version="composer-2.5",
            token_usage={"basis": "PROVIDER_REPORTED", "output_tokens": 32},
            provider_cost=None,
        )


class _NullPipeline:
    def prepare_attempt(self) -> None:
        return None

    def complete_failure(self, terminal: dict[str, object]) -> dict[str, object]:
        return dict(terminal)

    def execute(self, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            nodes=kwargs["nodes"],
            edges=kwargs["edges"],
            guarded_edges=(),
            node_resolutions=(),
            graph_effect_attempted=False,
            embedding_skipped=True,
            journal_skipped=True,
            rollback_skipped=True,
            completed_receipt=None,
        )


def test_failure_codes_are_explicitly_classified() -> None:
    for code in ATOM_LOCAL_FAILURE_CODES:
        assert (
            classify_combined_temporal_failure(code, grain="fact_loop") == "atom_local"
        )
    for code in (
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ):
        assert (
            classify_combined_temporal_failure(code, grain="fact_loop") == "atom_local"
        )
        assert classify_combined_temporal_failure(code, grain="payload") == (
            "payload_fatal"
        )
    for code in PAYLOAD_FATAL_FAILURE_CODES - FACT_LOOP_ATOM_LOCAL_CODES:
        assert (
            classify_combined_temporal_failure(code, grain="payload") == "payload_fatal"
        )
        assert (
            classify_combined_temporal_failure(code, grain="fact_loop")
            == "payload_fatal"
        )
    with pytest.raises(ValueError):
        classify_combined_temporal_failure(CombinedTemporalFailureCode.NONE)


def test_step13_retained_raw_rejects_to_zero_proposal_success() -> None:
    fix = _load_step(13)
    assert raw_digest(fix["raw"]) == fix["provider_raw_digest"]
    segs = segment_source(fix["source_body"])
    ref = UtcTimestamp.parse(fix["reference_time"]).value
    projected = project_governed_proposals(
        fix["raw"],
        segs,
        ref,
        raw_provider_digest=fix["provider_raw_digest"],
    )
    assert projected.receipt["accepted_count"] == 0
    assert projected.receipt["rejected_count"] >= 1
    assert projected.receipt["orphan_removed_count"] >= 1
    assert projected.payload == {"entities": [], "facts": []}
    assert all(
        item["reason_code"] == "EVIDENCE_UNRESOLVED"
        for item in projected.receipt["atom_actions"]
    )

    transport = _FakeTransport(fix["raw"])
    leaf = extract_combined_temporal(
        _revision(fix["source_body"], fix["reference_time"]),
        transport=transport,
        pipeline=_NullPipeline(),
    )
    assert transport.calls == 1
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
    assert leaf.payload == {"entities": [], "facts": []}
    assert leaf.raw_output_digest == fix["provider_raw_digest"]
    assert isinstance(leaf.transport_calls[0].get("raw_output_digest"), str)


class _CapturingPipeline(_NullPipeline):
    def __init__(self) -> None:
        self.last_receipt: dict[str, object] | None = None

    def execute(self, **kwargs: object) -> SimpleNamespace:
        receipt = kwargs.get("receipt")
        self.last_receipt = dict(receipt) if isinstance(receipt, dict) else None
        return super().execute(**kwargs)


def test_steps14_and15_stuffing_ignored_and_null_projected() -> None:
    for step in (14, 15):
        fix = _load_step(step)
        assert raw_digest(fix["raw"]) == fix["provider_raw_digest"]
        segs = segment_source(fix["source_body"])
        ref = UtcTimestamp.parse(fix["reference_time"]).value
        projected = project_governed_proposals(
            fix["raw"],
            segs,
            ref,
            raw_provider_digest=fix["provider_raw_digest"],
        )
        assert projected.receipt["rejected_count"] == 0
        assert projected.receipt["accepted_count"] == len(fix["raw"]["facts"])
        assert all(
            fact["valid_at"] is None and fact["invalid_at"] is None
            for fact in projected.payload["facts"]
        )
        for action in projected.receipt["atom_actions"]:
            assert action["projected_temporal"] == {
                "valid_at": None,
                "invalid_at": None,
            }
        pipeline = _CapturingPipeline()
        leaf = extract_combined_temporal(
            _revision(fix["source_body"], fix["reference_time"]),
            transport=_FakeTransport(fix["raw"]),
            pipeline=pipeline,
        )
        assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_WITH_PROPOSALS
        assert pipeline.last_receipt is not None
        bound = pipeline.last_receipt["projection_receipt"]
        assert isinstance(bound, dict)
        assert bound["projection_policy_version"] == PROJECTION_POLICY_VERSION
        assert bound["projection_receipt_digest"] == projected.receipt[
            "projection_receipt_digest"
        ]
        assert bound["raw_provider_output_digest"] == fix["provider_raw_digest"]
        again = project_governed_proposals(
            fix["raw"],
            segs,
            ref,
            raw_provider_digest=fix["provider_raw_digest"],
        )
        assert again.receipt == projected.receipt


@pytest.mark.parametrize(
    ("body", "fact", "expected_valid"),
    [
        (
            "Alice asked Bob about the curriculum on 2026-08-21T12:30:00Z.",
            "Alice asked Bob about the curriculum on 2026-08-21T12:30:00Z",
            "2026-08-21T12:30:00Z",
        ),
        (
            "Alice asked Bob about the curriculum on 21 August 2026.",
            "Alice asked Bob about the curriculum on 21 August 2026",
            "2026-08-21T00:00:00Z",
        ),
        (
            "Alice asked Bob about the curriculum on 2026年8月21日.",
            "Alice asked Bob about the curriculum on 2026年8月21日",
            "2026-08-21T00:00:00Z",
        ),
        (
            "Alice asked Bob about the curriculum yesterday.",
            "Alice asked Bob about the curriculum yesterday",
            "2026-08-25T05:28:42Z",
        ),
    ],
)
def test_temporal_cues_derive_even_when_raw_hint_wrong(
    body: str, fact: str, expected_valid: str
) -> None:
    ref = datetime(2026, 8, 26, 5, 28, 42, tzinfo=UTC)
    payload = {
        "entities": [
            {
                "local_id": 0,
                "name": "Alice",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
            {
                "local_id": 1,
                "name": "Bob",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": fact,
                "valid_at": "1999-01-01T00:00:00Z",
                "invalid_at": None,
                "evidence_segment_ids": [0],
            }
        ],
    }
    projected = project_governed_proposals(payload, segment_source(body), ref)
    assert projected.receipt["accepted_count"] == 1
    assert projected.payload["facts"][0]["valid_at"] == expected_valid
    assert projected.receipt["atom_actions"][0]["raw_temporal"]["valid_at"] == (
        "1999-01-01T00:00:00Z"
    )


def test_mixed_candidate_set_keeps_valid_and_rejects_invalid() -> None:
    body = (
        "Alice asked Bob about the curriculum on 2026-08-21. "
        "Carol met Dave without a grounded date."
    )
    # Build contiguous verbatim facts from the segmented body.
    segs = segment_source(body)
    retained = "".join(item.text for item in segs)
    good_fact = "Alice asked Bob about the curriculum on 2026-08-21"
    bad_fact = "starting sexual relationship with woman"
    assert good_fact in retained
    payload = {
        "entities": [
            {"local_id": 0, "name": "Alice", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 1, "name": "Bob", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 2, "name": "Carol", "entity_type_id": 0, "evidence_segment_ids": [0]},
            {"local_id": 3, "name": "Dave", "entity_type_id": 0, "evidence_segment_ids": [0]},
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": good_fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
            {
                "source_local_id": 2,
                "target_local_id": 3,
                "relation_type": "MET",
                "fact": bad_fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
        ],
    }
    projected = project_governed_proposals(
        payload, segs, datetime(2026, 8, 26, 5, 28, 42, tzinfo=UTC)
    )
    assert projected.receipt["accepted_count"] == 1
    assert projected.receipt["rejected_count"] == 1
    assert len(projected.payload["facts"]) == 1
    assert projected.payload["facts"][0]["fact"] == good_fact
    assert {item["local_id"] for item in projected.payload["entities"]} == {0, 1}
    assert projected.receipt["orphan_removed_count"] == 2


def test_mixed_fact_local_identity_defect_keeps_valid_sibling() -> None:
    body = "Alice asked Bob about the curriculum on 2026-08-21."
    segs = segment_source(body)
    good_fact = "Alice asked Bob about the curriculum on 2026-08-21"
    payload = {
        "entities": [
            {
                "local_id": 0,
                "name": "Alice",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
            {
                "local_id": 1,
                "name": "Bob",
                "entity_type_id": 0,
                "evidence_segment_ids": [0],
            },
        ],
        "facts": [
            {
                "source_local_id": 0,
                "target_local_id": 1,
                "relation_type": "ASKED",
                "fact": good_fact,
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
            {
                "source_local_id": "1",
                "target_local_id": 0,
                "relation_type": "ASKED",
                "fact": "Bob asked Alice about the curriculum on 2026-08-21",
                "valid_at": None,
                "invalid_at": None,
                "evidence_segment_ids": [0],
            },
        ],
    }
    projected = project_governed_proposals(
        payload, segs, datetime(2026, 8, 26, 5, 28, 42, tzinfo=UTC)
    )
    assert projected.receipt["accepted_count"] == 1
    assert projected.receipt["rejected_count"] == 1
    assert projected.payload["facts"][0]["fact"] == good_fact
    rejected = [
        item
        for item in projected.receipt["atom_actions"]
        if item["action"] == "reject"
    ]
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "IDENTITY_INVALID"


def test_payload_fatal_corruption_still_fails_closed() -> None:
    with pytest.raises(CombinedTemporalError) as exc:
        parse_payload('{"entities":[]')
    assert exc.value.code is CombinedTemporalFailureCode.MALFORMED_OBJECT
    assert classify_combined_temporal_failure(exc.value.code) == "payload_fatal"

    with pytest.raises(CombinedTemporalError) as exc:
        parse_payload({"entities": [], "facts": [], "extra": 1})
    assert exc.value.code is CombinedTemporalFailureCode.MALFORMED_OBJECT

    body = "Alice asked Bob about the curriculum."
    segs = segment_source(body)
    ref = datetime(2026, 8, 26, tzinfo=UTC)
    with pytest.raises(CombinedTemporalError) as exc:
        project_governed_proposals(
            {
                "entities": [
                    {
                        "local_id": 0,
                        "name": "Alice",
                        "entity_type_id": 0,
                        "evidence_segment_ids": [0],
                    },
                    {
                        "local_id": 0,
                        "name": "Bob",
                        "entity_type_id": 0,
                        "evidence_segment_ids": [0],
                    },
                ],
                "facts": [],
            },
            segs,
            ref,
        )
    assert exc.value.code is CombinedTemporalFailureCode.IDENTITY_INVALID
    assert classify_combined_temporal_failure(exc.value.code) == "payload_fatal"


def test_prompt_drops_reference_time_cueing() -> None:
    prompt = build_compact_prompt(
        _revision("Alice asked Bob.", "2026-08-26T00:00:00Z")
    ).text
    assert "REFERENCE_TIME:" not in prompt
    assert "TEMPORAL_BASIS:" not in prompt
    assert "TEMPORAL_POLICY:" not in prompt
    assert "Put valid_at and invalid_at on each fact as null" in prompt


def test_zero_proposal_success_is_one_provider_call() -> None:
    fix = _load_step(13)
    transport = _FakeTransport(fix["raw"])
    leaf = extract_combined_temporal(
        _revision(fix["source_body"], fix["reference_time"]),
        transport=transport,
        pipeline=_NullPipeline(),
    )
    assert transport.calls == 1
    assert leaf.outcome is CombinedTemporalOutcome.TERMINAL_SUCCESS_ZERO_PROPOSALS
    assert leaf.invocation_count == 1
