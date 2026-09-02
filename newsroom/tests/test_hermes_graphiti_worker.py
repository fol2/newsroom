from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsroom.authority.canonical import digest_canonical
from newsroom.control_plane.graphiti_events import GraphitiProcessResult


GRAPH_DESTINATION_ID = "sha256:" + "9" * 64


def _arguments(*extra: str) -> list[str]:
    return [
        "--event-id",
        "event-1",
        "--ledger-seq",
        "7",
        "--max-reserved-gbp-microunits",
        "500000",
        *extra,
    ]


def test_exact_event_is_preflighted_time_bounded_and_fallback_free(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    captured: dict[str, object] = {}

    class Runner:
        pass

    def qualify(**kwargs: object) -> dict[str, object]:
        captured["preflight"] = kwargs
        return {
            "evidence_digest": "sha256:" + "a" * 64,
            "resolved_units": [{"ingest_id": "ingest-1"}],
        }

    def consume(**kwargs: object) -> GraphitiProcessResult:
        captured["consume"] = kwargs
        return GraphitiProcessResult("event-1", 7, "TERMINAL", 1)

    monkeypatch.setattr(worker, "qualify_fresh_graphiti_event", qualify)
    monkeypatch.setattr(worker, "consume_next_graphiti_event", consume)
    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)

    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=Runner(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )
    assert (
        worker.main(
            _arguments("--max-runtime-seconds", "45"),
            runtime=runtime,
        )
        == 0
    )

    assert captured["preflight"] == {
        "proving_store": str(worker.CANONICAL_PROVING_STORE),
        "unpublished_store": str(worker.CANONICAL_UNPUBLISHED_STORE),
        "event_id": "event-1",
        "ledger_seq": 7,
    }
    consumed = captured["consume"]
    assert isinstance(consumed, dict)
    assert consumed["event_id"] == "event-1"
    assert consumed["require_fresh"] is True
    assert consumed["recover_model_usage"] is False
    assert consumed["max_dispatch_seconds"] == 45
    assert consumed["prepared_event_preflight"] == {
        "evidence_digest": "sha256:" + "a" * 64,
        "resolved_units": [{"ingest_id": "ingest-1"}],
    }
    assert consumed["max_reserved_gbp_microunits"] == 500000
    assert consumed["graphiti"] is runtime.graphiti
    assert consumed["graphiti_admission_factory"] is runtime.admission_factory
    assert consumed["require_graphiti_admission"] is True
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [body["event"] for body in bodies] == [
        "GRAPHITI_EVENT_PREFLIGHT",
        "GRAPHITI_EVENT_RESULT",
        "GRAPHITI_WORKER_STOPPED",
    ]
    assert bodies[-1]["reason"] == "EXACT_EVENT_TERMINAL"
    assert bodies[-1]["completed_events"] == 1


def test_runtime_composes_existing_4a_4d_4b_4c_4e_authorities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts import hermes_graphiti_worker as worker
    from newsroom.tests.authority_helpers import proof
    from newsroom.tests.test_graphiti_increment4_system import (
        TrackingMemoryNeo4jAdapter,
        _open,
    )

    captured: dict[str, object] = {}

    def runner(**kwargs: object) -> object:
        captured["runner"] = kwargs
        return object()

    def admission(connection: object, **kwargs: object) -> object:
        captured["connection"] = connection
        captured["admission"] = kwargs
        return object()

    monkeypatch.setattr(worker, "EvaluationGraphitiRunner", runner)
    monkeypatch.setattr(
        worker,
        "compose_existing_graphiti_admission_consumer",
        admission,
    )
    authority_system = _open(tmp_path, TrackingMemoryNeo4jAdapter())
    authority_proof = proof()
    try:
        with pytest.raises(ValueError, match="path differs"):
            worker.compose_governed_graphiti_worker_runtime(
                authority_system=authority_system,
                expected_authority_store_path=str(tmp_path / "different.sqlite3"),
                authority_store_descriptor_digest="sha256:" + "a" * 64,
                proof=authority_proof,
                max_attempts=1,
            )

        runtime = worker.compose_governed_graphiti_worker_runtime(
            authority_system=authority_system,
            expected_authority_store_path=str(tmp_path / "authority.sqlite3"),
            authority_store_descriptor_digest="sha256:" + "a" * 64,
            proof=authority_proof,
            max_attempts=1,
        )
        connection = sqlite3.connect(":memory:")
        assert runtime.admission_factory(connection) is not None
        assert runtime.authority_store_source_path == str(
            (tmp_path / "authority.sqlite3").resolve()
        )
        assert runtime.authority_store_descriptor_digest == "sha256:" + "a" * 64
        assert runtime.graph_destination_id == authority_system.graph_destination_id

        assert captured["runner"] == {
            "fallback_permitted": False,
            "proposal_adapter": authority_system.graphiti,
            "extraction_records": authority_system.extraction,
            "proof": authority_proof,
        }
        assert captured["connection"] is connection
        assert captured["admission"] == {
            "adapter": authority_system.graphiti,
            "extraction": authority_system.extraction,
            "objects": authority_system.objects,
            "entities": authority_system.entities,
            "relations": authority_system.relations,
            "increment4": authority_system.increment4,
            "proof": authority_proof,
            "max_attempts": 1,
        }
        connection.close()
    finally:
        authority_system.close()


def test_exact_event_not_claimed_is_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    assert worker._run(consume=lambda: None) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies[-1]["reason"] == "EXACT_EVENT_NOT_CLAIMED"


def test_exact_event_execution_refusal_is_structured_and_terminal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    assert worker._run(consume=lambda: (_ for _ in ()).throw(ValueError("drift"))) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies[0]["reason"] == "EXACT_EVENT_EXECUTION_REFUSED"
    assert bodies[1]["failure_type"] == "ValueError"


@pytest.mark.parametrize(
    "state",
    ["RIGHTS_HELD", "RETRY_HELD", "CONFIGURATION_HELD", "DEAD_LETTER"],
)
def test_non_terminal_result_stops_without_another_selection(state: str) -> None:
    from scripts import hermes_graphiti_worker as worker

    calls: list[object] = []

    def consume() -> GraphitiProcessResult:
        calls.append("consume")
        return GraphitiProcessResult("event-1", 1, state, 1)

    assert worker._run(consume=consume) == 2
    assert calls == ["consume"]


def test_preflight_refusal_has_no_runner_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)
    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("not fresh")),
    )
    monkeypatch.setattr(
        worker,
        "consume_next_graphiti_event",
        lambda **_kwargs: pytest.fail("dispatch reached after refused preflight"),
    )

    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )
    assert worker.main(_arguments(), runtime=runtime) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies[0]["reason"] == "PREFLIGHT_REFUSED"
    assert bodies[1]["failure_type"] == "ValueError"


def test_conservative_spend_bound_refuses_before_runner_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    monkeypatch.setattr(worker, "ensure_control_plane_state_root", lambda: None)
    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **_kwargs: {
            "resolved_units": [
                {"ingest_id": "ingest-1"},
                {"ingest_id": "ingest-2"},
            ]
        },
    )
    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )
    assert worker.main(_arguments(), runtime=runtime) == 2
    bodies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert bodies == [
        {
            "event": "GRAPHITI_WORKER_STOPPED",
            "reason": "RESERVED_SPEND_BOUND_EXCEEDED",
            "completed_events": 0,
            "result": None,
            "public_dispatch": False,
            "auto_publish": False,
        }
    ]


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["--event-id", "event-1"],
        ["--ledger-seq", "1"],
        _arguments("--max-runtime-seconds", "0"),
        _arguments("--max-runtime-seconds", "nan"),
        _arguments("--max-runtime-seconds", "inf"),
        [
            "--event-id",
            "event-1",
            "--ledger-seq",
            "0",
            "--max-reserved-gbp-microunits",
            "500000",
        ],
        [
            "--event-id",
            "event-1",
            "--ledger-seq",
            "1",
            "--max-reserved-gbp-microunits",
            "0",
        ],
    ),
)
def test_worker_refuses_missing_or_invalid_bounds(argv: list[str]) -> None:
    from scripts import hermes_graphiti_worker as worker

    with pytest.raises(SystemExit):
        worker.main(argv)


def test_unconfigured_authority_stops_before_preflight_or_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **_kwargs: pytest.fail("preflight reached without authority runtime"),
    )

    assert worker.main(_arguments()) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == (
        "AUTHORITY_COMPOSITION_UNCONFIGURED"
    )


def test_campaign_cli_requires_injected_runtime_and_f4_fence_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    packet_path = tmp_path / "missing.json"
    monkeypatch.setattr(
        worker,
        "_current_git_identity",
        lambda: pytest.fail("git identity reached without campaign authority"),
    )

    assert worker.main(["--campaign-packet", str(packet_path)]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == (
        "CAMPAIGN_AUTHORITY_UNCONFIGURED"
    )


def test_campaign_cli_executes_exact_packet_through_injected_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    packet = {"packet_digest": "sha256:" + "a" * 64}
    packet_path = tmp_path / "campaign.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )
    fence = lambda _packet: None
    captured: dict[str, object] = {}

    monkeypatch.setattr(worker, "_current_git_identity", lambda: ("head", "tree"))

    def run(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"state": "CAMPAIGN_COMPLETE"}

    monkeypatch.setattr(worker, "run_bounded_campaign", run)

    assert (
        worker.main(
            ["--campaign-packet", str(packet_path)],
            runtime=runtime,
            owner_f4_fence=fence,
        )
        == 0
    )
    assert captured == {
        "packet": packet,
        "proving_store": str(worker.CANONICAL_PROVING_STORE),
        "unpublished_store": str(worker.CANONICAL_UNPUBLISHED_STORE),
        "runtime": runtime,
        "head_sha": "head",
        "tree_sha": "tree",
        "owner_f4_fence": fence,
    }
    assert json.loads(capsys.readouterr().out) == {
        "event": "GRAPHITI_CAMPAIGN_RESULT",
        "result": {"state": "CAMPAIGN_COMPLETE"},
        "public_dispatch": False,
        "auto_publish": False,
    }


def test_campaign_cli_stop_reports_durable_partial_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import hermes_graphiti_worker as worker

    unpublished = tmp_path / "unpublished.sqlite3"
    connection = worker.connect(str(unpublished))
    connection.executemany(
        "INSERT INTO unpublished_graphiti_revision_events("
        "event_id,ledger_seq,ledger_digest,source_id,item_key,revision_digest,"
        "landed_at,manifest_json,manifest_digest,unit_count,projector_version,"
        "projection_generation,state,attempt_count,available_at,"
        "provider_dispatched,terminal_at,proposal_count,last_failure_code"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            (
                "event-1",
                1,
                "ledger-1",
                "source",
                "item-1",
                "revision-1",
                "2026-09-01T12:00:00Z",
                "{}",
                "manifest-1",
                1,
                "projector",
                "generation",
                "TERMINAL",
                1,
                "2026-09-01T12:00:00Z",
                1,
                "2026-09-01T12:00:01Z",
                1,
                None,
            ),
            (
                "event-2",
                2,
                "ledger-2",
                "source",
                "item-2",
                "revision-2",
                "2026-09-01T12:00:00Z",
                "{}",
                "manifest-2",
                1,
                "projector",
                "generation",
                "RUNNING",
                1,
                "2026-09-01T12:00:00Z",
                1,
                None,
                None,
                None,
            ),
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_spend("
        "spend_id,ingest_id,attempt_number,proving_run_id,generation_id,"
        "reserved_gbp_microunits,actual_usd_microunits,"
        "actual_gbp_microunits,usage_basis,status,provider_usage_json,"
        "dispatch_owner,dispatch_lease_expires_at,at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "spend-1",
            "ingest-1",
            1,
            "run",
            "generation",
            100,
            23,
            23,
            "PROVIDER_REPORTED",
            "RECONCILED",
            "{}",
            None,
            None,
            "2026-09-01T12:00:01Z",
        ),
    )
    connection.commit()
    connection.close()
    packet = {
        "packet_digest": "sha256:" + "a" * 64,
        "bounded_campaign": {
            "cohort": {
                "events": [
                    {
                        "event_id": "event-1",
                        "ledger_seq": 1,
                        "ingest_ids": ["ingest-1"],
                    },
                    {
                        "event_id": "event-2",
                        "ledger_seq": 2,
                        "ingest_ids": ["ingest-2"],
                    },
                ]
            }
        },
    }
    packet_path = tmp_path / "campaign.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )
    monkeypatch.setattr(worker, "_current_git_identity", lambda: ("head", "tree"))
    monkeypatch.setattr(
        worker,
        "run_bounded_campaign",
        lambda **_kwargs: (_ for _ in ()).throw(
            worker.GraphitiCampaignStop("event 2 stopped")
        ),
    )

    assert (
        worker.main(
            [
                "--campaign-packet",
                str(packet_path),
                "--unpublished",
                str(unpublished),
            ],
            runtime=runtime,
            owner_f4_fence=lambda _packet: None,
        )
        == 2
    )
    body = json.loads(capsys.readouterr().out)
    assert body["event"] == "GRAPHITI_CAMPAIGN_STOPPED"
    report = body["result"]
    assert report["packet_digest"] == packet["packet_digest"]
    assert report["stage"] == "EXTRACTION_RECORDED"
    assert report["selected_event_count"] == 2
    assert report["completed_event_count"] == 1
    assert report["terminal_event_count"] == 1
    assert report["attempted_event_count"] == 2
    assert report["provider_dispatched_event_count"] == 2
    assert report["spend"] == {
        "row_count": 1,
        "status_counts": {"RECONCILED": 1},
        "reconciled_actual_gbp_microunits": 23,
        "actual_gbp_complete": False,
        "actual_gbp_microunits": None,
    }
    assert [item["state"] for item in report["events"]] == [
        "TERMINAL",
        "RUNNING",
    ]


def test_campaign_stop_report_attributes_all_hold_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import hermes_graphiti_worker as worker

    unpublished = tmp_path / "unpublished.sqlite3"
    connection = worker.connect(str(unpublished))
    connection.execute(
        "INSERT INTO unpublished_graphiti_revision_events("
        "event_id,ledger_seq,ledger_digest,source_id,item_key,revision_digest,"
        "landed_at,manifest_json,manifest_digest,unit_count,projector_version,"
        "projection_generation,state,attempt_count,available_at,"
        "provider_dispatched,terminal_at,proposal_count"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "event-1",
            1,
            "ledger-1",
            "source",
            "item-1",
            "revision-1",
            "2026-09-01T12:00:00Z",
            "{}",
            "manifest-1",
            1,
            "projector",
            "generation",
            "TERMINAL",
            1,
            "2026-09-01T12:00:00Z",
            1,
            "2026-09-01T12:00:01Z",
            1,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_spend("
        "spend_id,ingest_id,attempt_number,proving_run_id,generation_id,"
        "reserved_gbp_microunits,actual_usd_microunits,"
        "actual_gbp_microunits,usage_basis,status,provider_usage_json,"
        "dispatch_owner,dispatch_lease_expires_at,at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "spend-1",
            "ingest-1",
            1,
            "run",
            "generation",
            100,
            0,
            0,
            "PROVIDER_REPORTED",
            "RECONCILED",
            "{}",
            None,
            None,
            "2026-09-01T12:00:01Z",
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_admission_queue("
        "proposal_key,ingest_id,source_revision_id,source_receipt_digest,"
        "proposal_digest,proposal_kind,request_json,request_digest,state,"
        "created_at,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "proposal-1",
            "ingest-1",
            "revision-1",
            "receipt-1",
            "proposal-digest-1",
            "ENTITY_MENTION",
            "{}",
            "request-digest-1",
            "TERMINAL",
            "2026-09-01T12:00:01Z",
            "2026-09-01T12:00:01Z",
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_admission_decisions("
        "proposal_key,action,decision_id,authority_ledger_seq,reason_code,"
        "authority_receipt_digest,decision_json,decision_digest,decided_at"
        ") VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "proposal-1",
            "HOLD",
            "decision-1",
            1,
            "AMBIGUOUS",
            "authority-receipt-1",
            "{}",
            "decision-digest-1",
            "2026-09-01T12:00:01Z",
        ),
    )
    generation_id = "00000000-0000-4000-8000-000000000895"
    reconciliation_digest = "sha256:" + "c" * 64
    reconciliation = {
        "generation_id": generation_id,
        "expected_effect_ids": [],
        "actual_effect_ids": [],
        "authority_watermark": 1,
        "receipt_digest": reconciliation_digest,
        "projector_family_id": "graph.increment4.admitted",
        "provider_model_calls": 0,
    }
    connection.execute(
        "INSERT INTO unpublished_graphiti_projection_reconciliations("
        "receipt_digest,projector_family_id,generation_id,authority_watermark,"
        "receipt_json,reconciled_at"
        ") VALUES(?,?,?,?,?,?)",
        (
            reconciliation_digest,
            "graph.increment4.admitted",
            generation_id,
            1,
            json.dumps(reconciliation),
            "2026-09-01T12:00:02Z",
        ),
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(
        worker,
        "_campaign_decided_generation_identity",
        lambda _connection, *, ingest_ids: (
            "sha256:" + "b" * 64,
            generation_id,
        ),
    )
    packet = {
        "packet_digest": "sha256:" + "a" * 64,
        "bounded_campaign": {
            "cohort": {
                "events": [
                    {
                        "event_id": "event-1",
                        "ledger_seq": 1,
                        "ingest_ids": ["ingest-1"],
                    }
                ]
            }
        },
    }

    report = worker._campaign_stop_report(
        packet=packet,
        unpublished_store=str(unpublished),
        failure=worker.GraphitiCampaignStop("wall time reached"),
    )

    assert report["stage"] == "PROJECTION_RECORDED"
    assert report["admission"]["projection_receipt_count"] == 0
    assert report["generation"] == {
        "cohort_digest": "sha256:" + "b" * 64,
        "generation_id": generation_id,
        "reconciliation_count": 1,
        "reconciliations": [
            {
                "receipt_digest": reconciliation_digest,
                "projector_family_id": "graph.increment4.admitted",
                "generation_id": generation_id,
                "authority_watermark": 1,
                "expected_effect_ids": [],
                "actual_effect_ids": [],
                "reconciled_at": "2026-09-01T12:00:02Z",
            }
        ],
        "reconciliation_attribution_complete": True,
    }


def test_campaign_receipt_requires_exact_attempt_and_reconciled_spend(
    tmp_path: Path,
) -> None:
    from scripts import hermes_graphiti_worker as worker

    path = tmp_path / "unpublished.sqlite3"
    connection = worker.connect(str(path))
    embedding = {
        "usage_basis": "PROVIDER_REPORTED",
        "cost_usd_microunits": 3,
        "embedding_tokens": 5,
        "request_count": 1,
        "requests": [
            {
                "provider": "embedding-provider",
                "model": "embedding",
                "outcome": "COMPLETE",
                "cost_reported": True,
                "cost_usd_microunits": 3,
                "model_invocation_id": "embedding-invocation",
            }
        ],
    }
    receipt = {
        "ingest_id": "ingest-1",
        "outcome": "COMPLETE",
        "failure_code": "NONE",
        "proposal_count": 0,
        "attempt_number": 1,
        "provider_attempt_number": 1,
        "chat_invocations": [
            {
                "provider": "provider",
                "model": "model",
                "outcome": "COMPLETE",
                "model_invocation_id": "chat-invocation",
                "usage": {"usage_basis": "PROVIDER_REPORTED"},
                "transport_qualification": {"max_retries": 0},
            }
        ],
        "embedding_usage": embedding,
        "accounting": {
            "spend_id": "ingest-1:1",
            "status": "RECONCILED",
            "usage_basis": "PROVIDER_REPORTED",
            "actual_usd_microunits": 3,
            "actual_gbp_microunits": 3,
            "unused_reservation_released": True,
        },
    }
    receipt_digest = digest_canonical(receipt)
    receipt = {**receipt, "receipt_digest": receipt_digest}
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
    connection.execute(
        "INSERT INTO unpublished_graphiti_ingest VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "ingest-1",
            "source",
            "item",
            "COMPLETE",
            0,
            0,
            0,
            "NONE",
            "PUBLICATION_TIME",
            "2026-09-01T12:00:00Z",
            "generation",
            receipt_digest,
            "2026-09-01T12:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_receipts VALUES(?,?)",
        ("ingest-1", encoded),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_attempt_receipts VALUES(?,?,?,?,?,?)",
        (
            "ingest-1",
            1,
            "COMPLETE",
            receipt_digest,
            encoded,
            "2026-09-01T12:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_spend VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "ingest-1:1",
            "ingest-1",
            1,
            "run",
            "generation",
            500_000,
            3,
            3,
            "PROVIDER_REPORTED",
            "RECONCILED",
            json.dumps(embedding, sort_keys=True),
            None,
            None,
            "2026-09-01T12:00:00Z",
        ),
    )
    connection.commit()
    connection.close()

    evidence = worker._campaign_receipt_evidence(
        str(path),
        ingest_ids=("ingest-1",),
        provider={
            "provider_id": "provider",
            "model_id": "model",
            "embedding_provider_id": "embedding-provider",
            "embedding_model_id": "embedding",
        },
    )
    assert evidence == {
        "proposal_count": 0,
        "chat_invocation_count": 1,
        "embedding_request_count": 1,
        "fallback_count": 0,
        "retry_count": 0,
        "actual_gbp_microunits": 3,
    }
    with pytest.raises(
        worker.GraphitiCampaignStop,
        match="already have retained effects",
    ):
        worker._assert_fresh_campaign_ingests(
            str(path), ingest_ids=("ingest-1",)
        )

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE unpublished_graphiti_spend SET status='UNRECONCILED'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(worker.GraphitiCampaignStop, match="spend accounting drifted"):
        worker._campaign_receipt_evidence(
            str(path),
            ingest_ids=("ingest-1",),
            provider={
                "provider_id": "provider",
                "model_id": "model",
                "embedding_provider_id": "embedding-provider",
                "embedding_model_id": "embedding",
            },
        )


def test_campaign_completion_proves_fixed_operational_objectives(
    tmp_path: Path,
) -> None:
    from scripts import hermes_graphiti_worker as worker

    connection = worker.connect(str(tmp_path / "unpublished.sqlite3"))
    connection.execute(
        "INSERT INTO unpublished_graphiti_revision_events("
        "event_id,ledger_seq,ledger_digest,source_id,item_key,revision_digest,"
        "published_at,updated_at,landed_at,manifest_json,manifest_digest,"
        "unit_count,projector_version,projection_generation,state,attempt_count,"
        "available_at,provider_dispatched,terminal_at,proposal_count) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "event-1",
            7,
            "ledger-digest",
            "source",
            "item",
            "revision",
            "",
            "",
            "2026-09-01T12:00:00Z",
            "{}",
            "manifest-digest",
            1,
            "projector",
            "generation",
            "TERMINAL",
            1,
            "2026-09-01T12:00:00Z",
            1,
            "2026-09-01T12:00:05Z",
            1,
        ),
    )
    connection.execute(
        "INSERT INTO unpublished_graphiti_projection_reconciliations "
        "VALUES(?,?,?,?,?,?)",
        (
            "reconciliation-receipt",
            "graph.increment4.admitted",
            "generation-1",
            9,
            "{}",
            "2026-09-01T12:00:06Z",
        ),
    )
    evidence = worker._campaign_completion_evidence(
        connection,
        events=[{"event_id": "event-1", "ledger_seq": 7}],
        reconciliation_ids_before=frozenset(),
        proposal_count=1,
        elapsed_seconds=6.0,
        wall_time_cap=60,
    )

    assert evidence["watermark"] == {
        "target": "selected cohort terminal",
        "terminal_ledger_seq": 7,
        "passed": True,
    }
    assert evidence["backlog"]["remaining_selected_events"] == 0
    assert evidence["velocity"]["completed_events"] == 1
    assert evidence["lag"]["passed"] is True
    assert evidence["reconciliation"]["new_generation_ids"] == ["generation-1"]
    connection.close()


def _campaign() -> dict[str, object]:
    return {
        "source_snapshot_digests": {
            "proving": "proving-snapshot",
            "unpublished": "unpublished-snapshot",
            "authority": "sha256:" + "a" * 64,
        },
        "cohort": {
            "events": [
                {
                    "event_id": "event-1",
                    "ledger_seq": 1,
                    "manifest_digest": "manifest-1",
                    "ingest_ids": ["ingest-1"],
                },
                {
                    "event_id": "event-2",
                    "ledger_seq": 2,
                    "manifest_digest": "manifest-2",
                    "ingest_ids": ["ingest-2"],
                },
            ]
        },
        "provider": {
            "provider_id": "provider",
            "model_id": "model",
            "embedding_provider_id": "embedding-provider",
            "embedding_model_id": "embedding",
        },
        "graph": {
            "destination_id": GRAPH_DESTINATION_ID,
            "family_id": "graph.increment4.admitted",
        },
        "graph_destination_readback": {"generation_id": "generation"},
        "caps": {
            "per_event": {
                "proposals": 2,
                "entity_admits": 1,
                "relation_admits": 1,
                "effects": 2,
                "retries": 0,
                "fallbacks": 0,
            },
            "total": {
                "events": 2,
                "proposals": 2,
                "entity_admits": 1,
                "relation_admits": 1,
                "effects": 2,
                "retries": 0,
                "fallbacks": 0,
                "wall_time_seconds": 120,
                "spend_gbp_microunits": 1_000_000,
            },
            "rate": {"events_per_minute": 60},
        },
        "ramp": {
            "phases": [
                {
                    "phase_id": "one",
                    "event_limit": 1,
                    "entry_conditions": [
                        "EXACT_SNAPSHOT_AND_IDENTITY_RECONFIRMED",
                        "OWNER_F4_GO_RETAINED",
                    ],
                    "advance_conditions": [
                        "ALL_EXACT_RECEIPTS_RECONCILED",
                        "CAPS_AND_ACCOUNTING_RECONCILED",
                        "NO_STOP_CONDITION_OBSERVED",
                    ],
                },
                {
                    "phase_id": "two",
                    "event_limit": 2,
                    "entry_conditions": [
                        "EXACT_SNAPSHOT_AND_IDENTITY_RECONFIRMED",
                        "OWNER_F4_GO_RETAINED",
                    ],
                    "advance_conditions": [
                        "ALL_EXACT_RECEIPTS_RECONCILED",
                        "CAPS_AND_ACCOUNTING_RECONCILED",
                        "NO_STOP_CONDITION_OBSERVED",
                    ],
                },
            ]
        },
        "success_objectives": {
            "watermark": "selected cohort terminal",
            "backlog": 0,
            "velocity": "positive",
            "lag": "bounded",
            "reconciliation": "exact",
        },
    }


def test_bounded_campaign_extracts_all_events_then_decides_and_projects_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import hermes_graphiti_worker as worker

    campaign = _campaign()
    packet = {
        "packet_digest": "sha256:" + "a" * 64,
        "code_identity": {"head_sha": "head", "tree_sha": "tree"},
        "store_snapshots": {
            "authority": {
                "source_path": "/authority.sqlite3",
                "descriptor_digest": "sha256:" + "a" * 64,
            }
        },
    }
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        worker,
        "validate_graphiti_campaign_packet",
        lambda value: campaign if value is packet else pytest.fail("wrong packet"),
    )

    def qualify(**kwargs: object) -> dict[str, object]:
        event_id = str(kwargs["event_id"])
        suffix = event_id.removeprefix("event-")
        return {
            "event_id": event_id,
            "ledger_seq": int(suffix),
            "event_manifest_digest": f"manifest-{suffix}",
            "resolved_units": [{"ingest_id": f"ingest-{suffix}"}],
        }

    def consume(**kwargs: object) -> GraphitiProcessResult:
        event_id = str(kwargs["event_id"])
        calls.append(("extract", event_id))
        assert kwargs["defer_graphiti_admission"] is True
        assert kwargs["require_graphiti_admission"] is True
        return GraphitiProcessResult(
            event_id,
            int(event_id.removeprefix("event-")),
            "TERMINAL",
            1,
        )

    monkeypatch.setattr(worker, "qualify_fresh_graphiti_event", qualify)
    monkeypatch.setattr(
        worker,
        "graphiti_store_snapshot_digests",
        lambda **_kwargs: campaign["source_snapshot_digests"],
    )
    monkeypatch.setattr(
        worker,
        "_assert_fresh_campaign_ingests",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(worker, "consume_next_graphiti_event", consume)
    monkeypatch.setattr(
        worker,
        "_campaign_receipt_evidence",
        lambda *_args, **_kwargs: {
            "proposal_count": 1,
            "chat_invocation_count": 1,
            "embedding_request_count": 1,
            "fallback_count": 0,
            "retry_count": 0,
            "actual_gbp_microunits": 1,
        },
    )
    before = (
        ("ingest-1", "ENTITY_MENTION", None),
        ("ingest-2", "RELATION", None),
    )
    after = (
        ("ingest-1", "ENTITY_MENTION", "ADMIT"),
        ("ingest-2", "RELATION", "ADMIT"),
    )
    admission_reads = iter((before, after))
    monkeypatch.setattr(
        worker,
        "_campaign_admission_rows",
        lambda *_args, **_kwargs: next(admission_reads),
    )
    monkeypatch.setattr(
        worker,
        "_campaign_reconciliation_ids",
        lambda _connection: frozenset(),
    )
    objective_evidence = {
        "watermark": {"passed": True},
        "backlog": {"passed": True},
        "velocity": {"passed": True},
        "lag": {"passed": True},
        "reconciliation": {"passed": True},
    }
    monkeypatch.setattr(
        worker,
        "_campaign_completion_evidence",
        lambda *_args, **_kwargs: objective_evidence,
    )
    connection = sqlite3.connect(":memory:")
    monkeypatch.setattr(worker, "connect", lambda _path: connection)

    class Admission:
        def enqueue_complete_receipts(self, *, ingest_ids):
            calls.append(("enqueue", ingest_ids))

        def drain(self, **kwargs: object):
            assert [item for item in calls if item[0] == "extract"] == [
                ("extract", "event-1"),
                ("extract", "event-2"),
            ]
            assert kwargs["stop_on_failure"] is True
            calls.append(("drain", kwargs["ingest_ids"]))
            return SimpleNamespace(failed=0, dead_lettered=0)

        def finalise_decided_cohort(self, *, ingest_ids):
            calls.append(("generation", ingest_ids))
            return SimpleNamespace(failed=0, dead_lettered=0, projected=2)

    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: Admission(),
        graph_state_fence=lambda _campaign: (
            calls.append(("gate", "graph")) or {}
        ),
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )

    def owner_fence(value: object) -> None:
        assert value is packet
        calls.append(("gate", "owner"))

    report = worker.run_bounded_campaign(
        packet=packet,
        proving_store="proving",
        unpublished_store="unpublished",
        runtime=runtime,
        head_sha="head",
        tree_sha="tree",
        owner_f4_fence=owner_fence,
        monotonic=lambda: 0.0,
        sleep=lambda _delay: None,
    )

    assert calls == [
        ("gate", "owner"),
        ("gate", "graph"),
        ("extract", "event-1"),
        ("gate", "owner"),
        ("gate", "graph"),
        ("extract", "event-2"),
        ("gate", "owner"),
        ("gate", "graph"),
        ("enqueue", ("ingest-1", "ingest-2")),
        ("drain", ("ingest-1", "ingest-2")),
        ("generation", ("ingest-1", "ingest-2")),
    ]
    assert report["state"] == "CAMPAIGN_COMPLETE"
    assert report["event_count"] == 2
    assert report["entity_admits"] == 1
    assert report["relation_admits"] == 1
    assert report["success_objectives"] == objective_evidence
    assert [item["state"] for item in report["events"]] == [
        "EXTRACTION_TERMINAL_CAMPAIGN_PENDING",
        "EXTRACTION_TERMINAL_CAMPAIGN_PENDING",
    ]


def test_bounded_campaign_checks_owner_f4_before_graph_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import hermes_graphiti_worker as worker

    campaign = _campaign()
    packet = {
        "packet_digest": "sha256:" + "a" * 64,
        "code_identity": {"head_sha": "head", "tree_sha": "tree"},
        "store_snapshots": {
            "authority": {
                "source_path": "/authority.sqlite3",
                "descriptor_digest": "sha256:" + "a" * 64,
            }
        },
    }
    monkeypatch.setattr(
        worker,
        "validate_graphiti_campaign_packet",
        lambda value: campaign if value is packet else pytest.fail("wrong packet"),
    )
    monkeypatch.setattr(
        worker,
        "graphiti_store_snapshot_digests",
        lambda **_kwargs: campaign["source_snapshot_digests"],
    )
    monkeypatch.setattr(
        worker,
        "_assert_fresh_campaign_ingests",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **kwargs: {
            "event_manifest_digest": (
                f"manifest-{str(kwargs['event_id']).removeprefix('event-')}"
            ),
            "resolved_units": [
                {
                    "ingest_id": (
                        f"ingest-{str(kwargs['event_id']).removeprefix('event-')}"
                    )
                }
            ],
        },
    )
    monkeypatch.setattr(
        worker,
        "consume_next_graphiti_event",
        lambda **_kwargs: pytest.fail("dispatch reached after F4 stop"),
    )
    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: object(),
        graph_state_fence=lambda _campaign: pytest.fail(
            "graph readback reached before F4"
        ),
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )

    def stopped(_packet: Mapping[str, object]) -> None:
        raise worker.GraphitiCampaignStop("owner F4 stopped")

    with pytest.raises(worker.GraphitiCampaignStop, match="owner F4 stopped"):
        worker.run_bounded_campaign(
            packet=packet,
            proving_store="proving",
            unpublished_store="unpublished",
            runtime=runtime,
            head_sha="head",
            tree_sha="tree",
            owner_f4_fence=stopped,
            monotonic=lambda: 0.0,
            sleep=lambda _delay: None,
        )


def test_campaign_cap_stops_before_any_canonical_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import hermes_graphiti_worker as worker

    campaign = _campaign()
    campaign["caps"]["per_event"]["entity_admits"] = 0
    packet = {
        "packet_digest": "sha256:" + "a" * 64,
        "code_identity": {"head_sha": "head", "tree_sha": "tree"},
        "store_snapshots": {
            "authority": {
                "source_path": "/authority.sqlite3",
                "descriptor_digest": "sha256:" + "a" * 64,
            }
        },
    }
    monkeypatch.setattr(
        worker, "validate_graphiti_campaign_packet", lambda _value: campaign
    )
    monkeypatch.setattr(
        worker,
        "graphiti_store_snapshot_digests",
        lambda **_kwargs: campaign["source_snapshot_digests"],
    )
    monkeypatch.setattr(
        worker,
        "_assert_fresh_campaign_ingests",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        worker,
        "qualify_fresh_graphiti_event",
        lambda **kwargs: {
            "event_manifest_digest": (
                f"manifest-{str(kwargs['event_id']).removeprefix('event-')}"
            ),
            "resolved_units": [
                {
                    "ingest_id": (
                        f"ingest-{str(kwargs['event_id']).removeprefix('event-')}"
                    )
                }
            ],
        },
    )
    monkeypatch.setattr(
        worker,
        "consume_next_graphiti_event",
        lambda **kwargs: GraphitiProcessResult(
            str(kwargs["event_id"]),
            int(str(kwargs["event_id"]).removeprefix("event-")),
            "TERMINAL",
            1,
        ),
    )
    monkeypatch.setattr(
        worker,
        "_campaign_receipt_evidence",
        lambda *_args, **_kwargs: {
            "proposal_count": 1,
            "chat_invocation_count": 1,
            "embedding_request_count": 0,
            "fallback_count": 0,
            "retry_count": 0,
            "actual_gbp_microunits": 0,
        },
    )
    monkeypatch.setattr(
        worker,
        "_campaign_admission_rows",
        lambda *_args, **_kwargs: (
            ("ingest-1", "ENTITY_MENTION", None),
            ("ingest-2", "RELATION", None),
        ),
    )
    monkeypatch.setattr(
        worker,
        "_campaign_reconciliation_ids",
        lambda _connection: frozenset(),
    )
    connection = sqlite3.connect(":memory:")
    monkeypatch.setattr(worker, "connect", lambda _path: connection)

    class Admission:
        def enqueue_complete_receipts(self, *, ingest_ids):
            assert ingest_ids == ("ingest-1", "ingest-2")

        def drain(self, **_kwargs: object):
            pytest.fail("canonical admission occurred after cap stop")

    runtime = worker._mint_graphiti_campaign_runtime(
        graphiti=object(),
        admission_factory=lambda _connection: Admission(),
        graph_state_fence=lambda _campaign: {},
        graph_destination_id=GRAPH_DESTINATION_ID,
        authority_store_source_path="/authority.sqlite3",
        authority_store_descriptor_digest="sha256:" + "a" * 64,
    )
    with pytest.raises(worker.GraphitiCampaignStop, match="entity_admits cap"):
        worker.run_bounded_campaign(
            packet=packet,
            proving_store="proving",
            unpublished_store="unpublished",
            runtime=runtime,
            head_sha="head",
            tree_sha="tree",
            owner_f4_fence=lambda _packet: None,
            monotonic=lambda: 0.0,
            sleep=lambda _delay: None,
        )
