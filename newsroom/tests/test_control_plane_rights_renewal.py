from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.intake import run_intake
from newsroom.control_plane.rights_renewal import (
    AUTOMATIC_RIGHTS_DESTINATIONS,
    RETIRED_ENDPOINT_MIGRATIONS,
    RIGHTS_ARGUMENT_BY_GATE,
    RIGHTS_RENEWAL_LEAD,
    RIGHTS_VALIDITY,
    RightsRenewalError,
    automatic_rights_arguments,
)
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EVALUATION_DESTINATION_TOKENS,
)
from newsroom.increment9.proving import GateStatus
from newsroom.increment9.proving import assess as proving_assess
from newsroom.increment9.rights import (
    BINDINGS,
    EMITTED_GATES,
    FIXTURE_FAMILIES,
    FIXTURE_HMAC_KEY,
    FIXTURE_NOW,
    RAD_01_GATE_ID,
    UK_10_GATE_ID,
    assess_rights,
    bound_terms_identity,
    fixture_inventory,
    fixture_review,
)

_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:example:1</id>
    <title>Home Office update</title>
    <link href="https://www.gov.uk/example-1"/>
    <summary>A retained proving item.</summary>
  </entry>
</feed>
"""
_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <guid>hk-1</guid>
    <title>香港政府新聞</title>
    <link>https://www.news.gov.hk/a</link>
    <description>保留來源正文。</description>
  </item>
</channel></rss>
""".encode("utf-8")
_JSON_DOC = b'{"title":"BNO visa","base_path":"/british-national-overseas-bno-visa","content_id":"abc","description":"Apply for a visa."}'


def _timestamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _packets(arguments: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        gate_id: dict(arguments[argument])
        for gate_id, argument in RIGHTS_ARGUMENT_BY_GATE.items()
        if isinstance(arguments[argument], dict)
    }


def _retain(
    proving: Path, arguments: dict[str, object], *, run_id: str
) -> None:
    connection = sqlite3.connect(proving)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS proving_runs(
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                publication INTEGER NOT NULL DEFAULT 0,
                public_dispatch INTEGER NOT NULL DEFAULT 0,
                openrouter_invoked INTEGER NOT NULL DEFAULT 0,
                spend_gbp_minor INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS proving_rights_packets(
                run_id TEXT NOT NULL,
                gate_id TEXT NOT NULL,
                packet_digest TEXT NOT NULL,
                packet_json TEXT NOT NULL,
                assessed_at TEXT NOT NULL,
                PRIMARY KEY(run_id, gate_id)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO proving_runs(
                run_id, started_at, publication, public_dispatch,
                openrouter_invoked, spend_gbp_minor
            ) VALUES(?,?,0,0,0,0)
            """,
            (run_id, str(arguments["now"])),
        )
        for gate_id, packet in _packets(arguments).items():
            encoded = canonical_json_bytes(packet)
            connection.execute(
                "INSERT INTO proving_rights_packets VALUES(?,?,?,?,?)",
                (
                    run_id,
                    gate_id,
                    digest_bytes(encoded),
                    encoded.decode("utf-8"),
                    str(arguments["now"]),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _sign(proving: Path, instant: datetime, *, run_id: str) -> dict[str, object]:
    arguments = automatic_rights_arguments(proving_store=str(proving), now=instant)
    _retain(proving, arguments, run_id=run_id)
    return arguments


def _latest_persisted_packets(proving: Path) -> dict[str, dict[str, object]]:
    run_id = _latest_run_id(proving)
    connection = sqlite3.connect(proving)
    try:
        rows = connection.execute(
            """
            SELECT gate_id, packet_json FROM proving_rights_packets
            WHERE run_id=? ORDER BY gate_id
            """,
            (run_id,),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == len(EMITTED_GATES)
    return {
        str(gate_id): json.loads(str(packet_json)) for gate_id, packet_json in rows
    }


def _seal_totals(packets: Mapping[str, Mapping[str, object]]) -> tuple[int, int]:
    seals: list[str] = []
    for packet in packets.values():
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        seals.extend(str(item["seal"]) for item in reviews)
    return len(seals), len(set(seals))


def _proving_run_count(proving: Path) -> int:
    connection = sqlite3.connect(proving)
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "proving_runs" not in tables:
            return 0
        row = connection.execute("SELECT COUNT(*) FROM proving_runs").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def _latest_run_id(proving: Path) -> str:
    connection = sqlite3.connect(proving)
    try:
        row = connection.execute(
            "SELECT run_id FROM proving_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return str(row[0])


def _update_latest_packet(
    proving: Path,
    *,
    gate_id: str = "RIGHTS_UK-01",
    packet_json: str | None = None,
    packet_digest: str | None = None,
    mutate: Callable[[dict[str, object]], None] | None = None,
) -> None:
    run_id = _latest_run_id(proving)
    connection = sqlite3.connect(proving)
    try:
        current_json, current_digest = connection.execute(
            """
            SELECT packet_json, packet_digest FROM proving_rights_packets
            WHERE run_id=? AND gate_id=?
            """,
            (run_id, gate_id),
        ).fetchone()
        if mutate is not None:
            packet = json.loads(str(current_json))
            mutate(packet)
            encoded = canonical_json_bytes(packet)
            packet_json = encoded.decode("utf-8")
            packet_digest = digest_bytes(encoded)
        connection.execute(
            """
            UPDATE proving_rights_packets
            SET packet_json=?, packet_digest=?
            WHERE run_id=? AND gate_id=?
            """,
            (
                str(current_json if packet_json is None else packet_json),
                str(current_digest if packet_digest is None else packet_digest),
                run_id,
                gate_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_fresh_store_auto_signs_one_thirty_day_packet_set(tmp_path: Path) -> None:
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    arguments = automatic_rights_arguments(
        proving_store=str(tmp_path / "proving.sqlite3"), now=now
    )

    packets = _packets(arguments)
    assert set(packets) == EMITTED_GATES
    assert arguments["now"] == _timestamp(now)
    assert AUTOMATIC_RIGHTS_DESTINATIONS == tuple(
        sorted({"TEN_APPROVED_SOURCE_ENDPOINTS", *GRAPHITI_EVALUATION_DESTINATION_TOKENS})
    )
    seals: list[str] = []
    for gate_id, packet in packets.items():
        verdict = assess_rights(gate_id, inventory=packet, now=_timestamp(now))
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        assert verdict.status == "PASS"
        assert verdict.expires_at == _timestamp(now + RIGHTS_VALIDITY)
        assert verdict.destinations == AUTOMATIC_RIGHTS_DESTINATIONS
        assert GRAPHITI_EVALUATION_DESTINATION_TOKENS <= set(verdict.destinations)
        assert len(reviews) == 3
        assert {item["reviewer_family"] for item in reviews} == set(FIXTURE_FAMILIES)
        seals.extend(str(item["seal"]) for item in reviews)
    assert len(seals) == 30
    assert len(set(seals)) == 30


def test_retained_packets_are_reused_until_the_seven_day_renewal_boundary(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    signed_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    signed = _sign(proving, signed_at, run_id="run-signed")
    signed_packets = {
        gate_id: canonical_json_bytes(packet)
        for gate_id, packet in _packets(signed).items()
    }

    before_boundary = signed_at + RIGHTS_VALIDITY - RIGHTS_RENEWAL_LEAD - timedelta(
        microseconds=1
    )
    reused = automatic_rights_arguments(
        proving_store=str(proving), now=before_boundary
    )
    reused_packets = _packets(reused)
    assert set(reused_packets) == EMITTED_GATES
    for gate_id, packet in reused_packets.items():
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        assert reviews[0]["issued_at"] == _timestamp(signed_at)
        assert canonical_json_bytes(packet) == signed_packets[gate_id]

    at_boundary = signed_at + RIGHTS_VALIDITY - RIGHTS_RENEWAL_LEAD
    renewed = automatic_rights_arguments(proving_store=str(proving), now=at_boundary)
    for gate_id, packet in _packets(renewed).items():
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        assert reviews[0]["issued_at"] == _timestamp(at_boundary)
        assert reviews[0]["expires_at"] == _timestamp(at_boundary + RIGHTS_VALIDITY)
        assert canonical_json_bytes(packet) != signed_packets[gate_id]


def test_renewal_boundary_still_rejects_a_later_future_dated_packet(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    signed_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    _sign(proving, signed_at, run_id="run-signed")
    at_boundary = signed_at + RIGHTS_VALIDITY - RIGHTS_RENEWAL_LEAD
    future = automatic_rights_arguments(
        proving_store=str(tmp_path / "future.sqlite3"),
        now=at_boundary + timedelta(days=1),
    )
    future_packet = _packets(future)["RIGHTS_UK-01"]
    encoded = canonical_json_bytes(future_packet)
    _update_latest_packet(
        proving,
        gate_id="RIGHTS_UK-01",
        packet_json=encoded.decode("utf-8"),
        packet_digest=digest_bytes(encoded),
    )

    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(proving_store=str(proving), now=at_boundary)


def test_expired_retained_packets_are_renewed_and_rights_gates_recover(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    signed_at = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    _sign(proving, signed_at, run_id="run-expired")

    recovered_at = signed_at + RIGHTS_VALIDITY + timedelta(days=1)
    recovered = automatic_rights_arguments(
        proving_store=str(proving), now=recovered_at
    )
    packets = _packets(recovered)
    reviews = packets["RIGHTS_UK-01"]["reviews"]
    assert isinstance(reviews, list)
    assert reviews[0]["issued_at"] == _timestamp(recovered_at)
    rights_kwargs = {
        argument: packets[gate_id]
        for gate_id, argument in RIGHTS_ARGUMENT_BY_GATE.items()
    }
    gates = proving_assess(
        run_id="run-recovered",
        kill_switch=False,
        no_emergency_stop=True,
        now=_timestamp(recovered_at),
        **rights_kwargs,
    )
    rights = [gate for gate in gates if gate.gate_id.startswith("RIGHTS_")]
    assert len(rights) == 10
    assert {gate.status for gate in rights} == {GateStatus.PASS}


def test_tampered_or_drifted_retained_packet_fails_closed(tmp_path: Path) -> None:
    proving = tmp_path / "proving.sqlite3"
    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    _sign(proving, now, run_id="run-terms")

    def drift_terms(packet: dict[str, object]) -> None:
        bound = packet["bound_terms"]
        assert isinstance(bound, dict)
        bound["terms_url"] = "https://changed.example/terms"

    _update_latest_packet(proving, mutate=drift_terms)

    with pytest.raises(RightsRenewalError, match="terms identity differs"):
        automatic_rights_arguments(
            proving_store=str(proving), now=now + timedelta(days=1)
        )


def _retained_pair(tmp_path: Path) -> tuple[Path, datetime]:
    proving = tmp_path / "proving.sqlite3"
    first_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    _sign(proving, first_at, run_id="run-first")
    _sign(proving, first_at + timedelta(minutes=5), run_id="run-second")
    return proving, first_at + timedelta(minutes=10)


def test_malformed_retained_packet_fails_closed(tmp_path: Path) -> None:
    proving, later = _retained_pair(tmp_path)
    _update_latest_packet(proving, packet_json="{")
    with pytest.raises(RightsRenewalError, match="malformed"):
        automatic_rights_arguments(proving_store=str(proving), now=later)


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    proving, later = _retained_pair(tmp_path)
    _update_latest_packet(
        proving,
        packet_json='{"bound_terms":{},"now":"x","reviews":[]}',
        packet_digest="sha256:" + "0" * 64,
    )
    with pytest.raises(RightsRenewalError, match="digest differs"):
        automatic_rights_arguments(proving_store=str(proving), now=later)


def test_invalid_seal_fails_closed(tmp_path: Path) -> None:
    proving, later = _retained_pair(tmp_path)

    def break_seal(packet: dict[str, object]) -> None:
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        reviews[0]["seal"] = "hmac-sha256:" + "0" * 64

    _update_latest_packet(proving, mutate=break_seal)
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(proving_store=str(proving), now=later)


def test_incomplete_latest_packet_set_does_not_fall_back(tmp_path: Path) -> None:
    proving, later = _retained_pair(tmp_path)
    second_id = _latest_run_id(proving)

    connection = sqlite3.connect(proving)
    try:
        connection.execute(
            """
            DELETE FROM proving_rights_packets
            WHERE run_id=? AND gate_id='RIGHTS_UK-01'
            """,
            (second_id,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RightsRenewalError, match="packet set is incomplete"):
        automatic_rights_arguments(proving_store=str(proving), now=later)

    connection = sqlite3.connect(proving)
    try:
        connection.execute(
            "DELETE FROM proving_rights_packets WHERE run_id=?",
            (second_id,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RightsRenewalError, match="packet set is incomplete"):
        automatic_rights_arguments(proving_store=str(proving), now=later)


def _legacy_expired_packets() -> dict[str, dict[str, object]]:
    packets: dict[str, dict[str, object]] = {}
    for gate_id in sorted(EMITTED_GATES):
        retired = RETIRED_ENDPOINT_MIGRATIONS.get(gate_id)
        if retired is None:
            packets[gate_id] = fixture_inventory(gate=gate_id)
            continue
        packets[gate_id] = {
            "bound_terms": bound_terms_identity(gate=gate_id),
            "now": FIXTURE_NOW,
            "reviews": [
                fixture_review(family, gate=gate_id, endpoint=retired)
                for family in FIXTURE_FAMILIES
            ],
        }
    return packets


def _retain_legacy(proving: Path, *, run_id: str) -> None:
    packets = _legacy_expired_packets()
    arguments: dict[str, object] = {
        RIGHTS_ARGUMENT_BY_GATE[gate_id]: packet
        for gate_id, packet in packets.items()
    }
    arguments["now"] = FIXTURE_NOW
    _retain(proving, arguments, run_id=run_id)


def _reseal_first_review(
    packet: dict[str, object],
    *,
    endpoint: str | None = None,
    **changes: object,
) -> None:
    reviews = packet["reviews"]
    assert isinstance(reviews, list)
    first = dict(reviews[0])
    if endpoint is not None:
        first["endpoint"] = endpoint
    for key, value in changes.items():
        first[key] = value
    unsigned = {key: value for key, value in first.items() if key != "seal"}
    first["seal"] = "hmac-sha256:" + hmac.new(
        FIXTURE_HMAC_KEY,
        canonical_json_bytes(unsigned),
        hashlib.sha256,
    ).hexdigest()
    reviews[0] = first


def _legacy_fetch(url: str) -> tuple[int, bytes]:
    if "atom" in url:
        return 200, _ATOM
    if url.endswith(".xml") or "rss" in url.lower() or "WarningsRSS" in url:
        return 200, _RSS
    return 200, _JSON_DOC


def test_legacy_retired_endpoint_sqlite_packets_recover_current_bindings(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    _retain_legacy(proving, run_id="run-legacy-retired")
    recovered_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

    recovered = automatic_rights_arguments(
        proving_store=str(proving), now=recovered_at
    )
    packets = _packets(recovered)
    assert set(packets) == EMITTED_GATES
    assert recovered["now"] == _timestamp(recovered_at)
    seals: list[str] = []
    for gate_id, packet in packets.items():
        verdict = assess_rights(
            gate_id, inventory=packet, now=_timestamp(recovered_at)
        )
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        assert verdict.status == "PASS"
        assert verdict.expires_at == _timestamp(recovered_at + RIGHTS_VALIDITY)
        assert verdict.destinations == AUTOMATIC_RIGHTS_DESTINATIONS
        assert reviews[0]["issued_at"] == _timestamp(recovered_at)
        assert reviews[0]["endpoint"] == BINDINGS[gate_id][2]
        assert reviews[0]["endpoint"] != RETIRED_ENDPOINT_MIGRATIONS.get(gate_id)
        seals.extend(str(item["seal"]) for item in reviews)
    assert len(seals) == 30
    assert len(set(seals)) == 30
    assert packets[UK_10_GATE_ID]["reviews"][0]["endpoint"] == BINDINGS[UK_10_GATE_ID][2]
    assert packets[RAD_01_GATE_ID]["reviews"][0]["endpoint"] == BINDINGS[RAD_01_GATE_ID][2]

    report = run_intake(
        proving_store=str(proving),
        fetch=_legacy_fetch,
        clock=lambda: recovered_at,
    )
    assert report.authorised
    assert report.complete
    assert report.sources == 10
    assert report.ok == 10
    assert report.health == "ACTIVE"
    assert report.active == 10
    assert report.degraded == 0
    assert report.held == 0
    assert report.blocked == 0
    assert report.proving_run_id.startswith("proving-9p-private-beta-")

    persisted = _latest_persisted_packets(proving)
    assert set(persisted) == EMITTED_GATES
    seal_total, unique_seals = _seal_totals(persisted)
    assert seal_total == 30
    assert unique_seals == 30
    for gate_id, packet in persisted.items():
        verdict = assess_rights(
            gate_id, inventory=packet, now=_timestamp(recovered_at)
        )
        assert verdict.status == "PASS"
        assert verdict.destinations == AUTOMATIC_RIGHTS_DESTINATIONS
        reviews = packet["reviews"]
        assert isinstance(reviews, list)
        assert reviews[0]["issued_at"] == _timestamp(recovered_at)
        assert reviews[0]["endpoint"] == BINDINGS[gate_id][2]
    first_digests = {
        gate_id: digest_bytes(canonical_json_bytes(packet))
        for gate_id, packet in persisted.items()
    }

    second = run_intake(
        proving_store=str(proving),
        fetch=_legacy_fetch,
        clock=lambda: recovered_at,
    )
    assert second.proving_run_id != report.proving_run_id
    assert second.authorised
    assert second.health == "ACTIVE"
    assert second.active == 10
    assert second.degraded == 0
    assert second.held == 0
    assert second.blocked == 0
    reused = _latest_persisted_packets(proving)
    reused_digests = {
        gate_id: digest_bytes(canonical_json_bytes(packet))
        for gate_id, packet in reused.items()
    }
    assert reused_digests == first_digests
    assert _proving_run_count(proving) == 3


def test_existing_empty_sqlite_without_proving_runs_fresh_signs(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    connection = sqlite3.connect(proving)
    try:
        connection.executescript(
            """
            CREATE TABLE proving_runs(
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                publication INTEGER NOT NULL DEFAULT 0,
                public_dispatch INTEGER NOT NULL DEFAULT 0,
                openrouter_invoked INTEGER NOT NULL DEFAULT 0,
                spend_gbp_minor INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    arguments = automatic_rights_arguments(proving_store=str(proving), now=now)
    packets = _packets(arguments)
    assert set(packets) == EMITTED_GATES
    assert arguments["now"] == _timestamp(now)
    seal_total, unique_seals = _seal_totals(packets)
    assert seal_total == 30
    assert unique_seals == 30
    for gate_id, packet in packets.items():
        verdict = assess_rights(gate_id, inventory=packet, now=_timestamp(now))
        assert verdict.status == "PASS"
        assert verdict.expires_at == _timestamp(now + RIGHTS_VALIDITY)
        assert verdict.destinations == AUTOMATIC_RIGHTS_DESTINATIONS
    assert _proving_run_count(proving) == 0


def test_arbitrary_endpoint_drift_on_legacy_sqlite_packets_fails_closed(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    _retain_legacy(proving, run_id="run-legacy-drift")

    def drift_uk_01(packet: dict[str, object]) -> None:
        _reseal_first_review(
            packet, endpoint="https://example.invalid/drifted-uk-01"
        )

    _update_latest_packet(proving, gate_id="RIGHTS_UK-01", mutate=drift_uk_01)
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(
            proving_store=str(proving),
            now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        )

    proving_uk10 = tmp_path / "proving-uk10.sqlite3"
    _retain_legacy(proving_uk10, run_id="run-legacy-uk10-drift")

    def drift_uk_10(packet: dict[str, object]) -> None:
        _reseal_first_review(
            packet, endpoint="https://example.invalid/drifted-uk-10"
        )

    _update_latest_packet(
        proving_uk10, gate_id=UK_10_GATE_ID, mutate=drift_uk_10
    )
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(
            proving_store=str(proving_uk10),
            now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("gate_id", "field", "value"),
    [
        (UK_10_GATE_ID, "destinations", ["OTHER_DESTINATION"]),
        (UK_10_GATE_ID, "retention", "OTHER_RETENTION"),
        (UK_10_GATE_ID, "access_method", "OTHER_ACCESS_METHOD"),
        (UK_10_GATE_ID, "data_class", "OTHER_DATA_CLASS"),
        (UK_10_GATE_ID, "reviewer_family", "OTHER_FAMILY"),
        (RAD_01_GATE_ID, "destinations", ["OTHER_DESTINATION"]),
        (RAD_01_GATE_ID, "retention", "OTHER_RETENTION"),
        (RAD_01_GATE_ID, "access_method", "OTHER_ACCESS_METHOD"),
        (RAD_01_GATE_ID, "data_class", "OTHER_DATA_CLASS"),
        (RAD_01_GATE_ID, "reviewer_family", "OTHER_FAMILY"),
    ],
)
def test_resealed_legacy_retired_endpoint_drift_fails_closed(
    tmp_path: Path,
    gate_id: str,
    field: str,
    value: object,
) -> None:
    proving = tmp_path / f"proving-{gate_id.lower()}.sqlite3"
    _retain_legacy(proving, run_id=f"run-legacy-{gate_id.lower()}-drift")

    def drift(packet: dict[str, object]) -> None:
        _reseal_first_review(packet, **{field: value})

    _update_latest_packet(proving, gate_id=gate_id, mutate=drift)
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(
            proving_store=str(proving),
            now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        )


_CURRENT_ENDPOINT_DRIFT_CASES = (
    (UK_10_GATE_ID, "destinations", ["TEN_APPROVED_SOURCE_ENDPOINTS"]),
    (UK_10_GATE_ID, "destinations", ["OTHER_DESTINATION"]),
    (UK_10_GATE_ID, "retention", "OTHER_RETENTION"),
    (UK_10_GATE_ID, "access_method", "OTHER_ACCESS_METHOD"),
    (UK_10_GATE_ID, "data_class", "OTHER_DATA_CLASS"),
    (UK_10_GATE_ID, "reviewer_family", "OTHER_FAMILY"),
    (UK_10_GATE_ID, "reviewer_id", "reviewer-other-id"),
    (UK_10_GATE_ID, "unexpected_field", "unexpected"),
    (RAD_01_GATE_ID, "destinations", ["TEN_APPROVED_SOURCE_ENDPOINTS"]),
    (RAD_01_GATE_ID, "destinations", ["OTHER_DESTINATION"]),
    (RAD_01_GATE_ID, "retention", "OTHER_RETENTION"),
    (RAD_01_GATE_ID, "access_method", "OTHER_ACCESS_METHOD"),
    (RAD_01_GATE_ID, "data_class", "OTHER_DATA_CLASS"),
    (RAD_01_GATE_ID, "reviewer_family", "OTHER_FAMILY"),
    (RAD_01_GATE_ID, "reviewer_id", "reviewer-other-id"),
    (RAD_01_GATE_ID, "unexpected_field", "unexpected"),
)


@pytest.mark.parametrize("at_renewal_boundary", [False, True])
@pytest.mark.parametrize(("gate_id", "field", "value"), _CURRENT_ENDPOINT_DRIFT_CASES)
def test_resealed_current_endpoint_drift_fails_closed_without_minting(
    tmp_path: Path,
    gate_id: str,
    field: str,
    value: object,
    at_renewal_boundary: bool,
) -> None:
    proving = tmp_path / f"proving-{gate_id.lower()}-current.sqlite3"
    signed_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    _sign(proving, signed_at, run_id="run-current-drift")

    def drift(packet: dict[str, object]) -> None:
        _reseal_first_review(packet, **{field: value})

    _update_latest_packet(proving, gate_id=gate_id, mutate=drift)
    if at_renewal_boundary:
        instant = signed_at + RIGHTS_VALIDITY - RIGHTS_RENEWAL_LEAD
    else:
        instant = (
            signed_at + RIGHTS_VALIDITY - RIGHTS_RENEWAL_LEAD - timedelta(microseconds=1)
        )
    before_runs = _proving_run_count(proving)
    before_packets = _latest_persisted_packets(proving)
    before_digests = {
        retained_gate: digest_bytes(canonical_json_bytes(packet))
        for retained_gate, packet in before_packets.items()
    }

    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(proving_store=str(proving), now=instant)

    assert _proving_run_count(proving) == before_runs
    retained = _latest_persisted_packets(proving)
    assert {
        retained_gate: digest_bytes(canonical_json_bytes(packet))
        for retained_gate, packet in retained.items()
    } == before_digests


def test_arbitrary_endpoint_drift_blocks_intake_without_proving_run_or_fetch(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving.sqlite3"
    _retain_legacy(proving, run_id="run-legacy-intake-drift")
    drift_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

    def drift_uk_01(packet: dict[str, object]) -> None:
        _reseal_first_review(
            packet, endpoint="https://example.invalid/drifted-uk-01"
        )

    _update_latest_packet(proving, gate_id="RIGHTS_UK-01", mutate=drift_uk_01)
    fetch_calls: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        fetch_calls.append(url)
        raise AssertionError("provider fetch must not run when rights renewal fails closed")

    before_runs = _proving_run_count(proving)
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        run_intake(
            proving_store=str(proving),
            fetch=fetch,
            clock=lambda: drift_at,
        )
    assert fetch_calls == []
    assert _proving_run_count(proving) == before_runs


def _all_historical_current_packets() -> dict[str, dict[str, object]]:
    return {gate_id: fixture_inventory(gate=gate_id) for gate_id in sorted(EMITTED_GATES)}


def test_mixed_auto_and_historical_packets_fail_closed(tmp_path: Path) -> None:
    proving = tmp_path / "proving-mixed.sqlite3"
    signed_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    _sign(proving, signed_at, run_id="run-mixed-auto-historical")
    legacy = _legacy_expired_packets()

    def replace_with_historical_current(packet: dict[str, object]) -> None:
        packet.clear()
        packet.update(legacy["RIGHTS_UK-01"])

    _update_latest_packet(proving, gate_id="RIGHTS_UK-01", mutate=replace_with_historical_current)
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(
            proving_store=str(proving),
            now=signed_at + timedelta(days=1),
        )


def test_future_dated_exact_auto_packets_fail_closed_without_minting(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving-future-auto.sqlite3"
    real_now = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    future_at = real_now + timedelta(days=5)
    future_ts = _timestamp(future_at)
    expires_ts = _timestamp(future_at + RIGHTS_VALIDITY)
    packets = {
        gate_id: fixture_inventory(
            gate=gate_id,
            destinations=AUTOMATIC_RIGHTS_DESTINATIONS,
            now=future_ts,
            issued_at=future_ts,
            expires_at=expires_ts,
        )
        for gate_id in sorted(EMITTED_GATES)
    }
    arguments: dict[str, object] = {
        RIGHTS_ARGUMENT_BY_GATE[gate_id]: packet
        for gate_id, packet in packets.items()
    }
    arguments["now"] = future_ts
    _retain(proving, arguments, run_id="run-future-auto")

    before_runs = _proving_run_count(proving)
    before_packets = _latest_persisted_packets(proving)
    before_digests = {
        gate_id: digest_bytes(canonical_json_bytes(packet))
        for gate_id, packet in before_packets.items()
    }

    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(proving_store=str(proving), now=real_now)

    assert _proving_run_count(proving) == before_runs
    retained = _latest_persisted_packets(proving)
    assert {
        gate_id: digest_bytes(canonical_json_bytes(packet))
        for gate_id, packet in retained.items()
    } == before_digests


def test_all_historical_current_without_retired_fail_closed(
    tmp_path: Path,
) -> None:
    proving = tmp_path / "proving-all-historical-current.sqlite3"
    packets = _all_historical_current_packets()
    arguments: dict[str, object] = {
        RIGHTS_ARGUMENT_BY_GATE[gate_id]: packet
        for gate_id, packet in packets.items()
    }
    arguments["now"] = FIXTURE_NOW
    _retain(proving, arguments, run_id="run-all-historical-current")
    with pytest.raises(RightsRenewalError, match="not validly sealed"):
        automatic_rights_arguments(
            proving_store=str(proving),
            now=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        )
