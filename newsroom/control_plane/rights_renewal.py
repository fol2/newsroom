"""Renew unchanged Control Plane rights-review packets before they expire."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.graphiti_adapter.evaluation_packet import (
    GRAPHITI_EVALUATION_DESTINATION_TOKENS,
)
from newsroom.increment9.rights import (
    EMITTED_GATES,
    FIXTURE_DESTINATIONS,
    FIXTURE_FAMILIES,
    FIXTURE_NOW,
    GATE_ID,
    HK_01_GATE_ID,
    HK_02_GATE_ID,
    HK_04_GATE_ID,
    RAD_01_GATE_ID,
    RAD_01_RETIRED_ENDPOINT,
    RAD_02_GATE_ID,
    UK_02_GATE_ID,
    UK_03_GATE_ID,
    UK_05_GATE_ID,
    UK_10_GATE_ID,
    UK_10_RETIRED_ENDPOINT,
    assess_rights,
    bound_terms_identity,
    fixture_inventory,
    fixture_review,
)

RIGHTS_VALIDITY = timedelta(days=30)
RIGHTS_RENEWAL_LEAD = timedelta(days=7)
AUTOMATIC_RIGHTS_DESTINATIONS = tuple(
    sorted({*FIXTURE_DESTINATIONS, *GRAPHITI_EVALUATION_DESTINATION_TOKENS})
)

RIGHTS_ARGUMENT_BY_GATE = {
    GATE_ID: "rights",
    UK_02_GATE_ID: "rights_uk_02",
    UK_03_GATE_ID: "rights_uk_03",
    UK_05_GATE_ID: "rights_uk_05",
    UK_10_GATE_ID: "rights_uk_10",
    HK_01_GATE_ID: "rights_hk_01",
    HK_02_GATE_ID: "rights_hk_02",
    HK_04_GATE_ID: "rights_hk_04",
    RAD_01_GATE_ID: "rights_rad_01",
    RAD_02_GATE_ID: "rights_rad_02",
}

# Exact retired aliases that remain sealed historical packets. Recognise only
# these migrations as renewable stale authority; never reuse the aliases.
RETIRED_ENDPOINT_MIGRATIONS = {
    UK_10_GATE_ID: UK_10_RETIRED_ENDPOINT,
    RAD_01_GATE_ID: RAD_01_RETIRED_ENDPOINT,
}

PacketClass = Literal["AUTO_CURRENT", "HISTORICAL_CURRENT", "HISTORICAL_RETIRED"]


class RightsRenewalError(RuntimeError):
    """A retained packet cannot safely be reused or renewed."""


def _timestamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _latest_packet_rows(
    store_path: str,
) -> tuple[tuple[str, str, str], ...] | None:
    path = Path(store_path)
    if not path.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RightsRenewalError("rights packet store is unavailable") from exc
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "proving_runs" not in tables:
            return None
        latest = connection.execute(
            "SELECT run_id FROM proving_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            return None
        if "proving_rights_packets" not in tables:
            raise RightsRenewalError("retained rights packet set is incomplete")
        return tuple(
            (str(gate_id), str(packet_digest), str(packet_json))
            for gate_id, packet_digest, packet_json in connection.execute(
                """
                SELECT gate_id, packet_digest, packet_json
                FROM proving_rights_packets
                WHERE run_id=?
                ORDER BY gate_id
                """,
                (latest[0],),
            )
        )
    except sqlite3.Error as exc:
        raise RightsRenewalError("rights packet store is unavailable") from exc
    finally:
        connection.close()


def _exact_current_automatic_renewal_contract(
    gate_id: str, packet: Mapping[str, object]
) -> bool:
    """True only when a current packet equals the automatic 30-day contract."""

    now = packet.get("now")
    if type(now) is not str:
        return False
    try:
        issued = _instant(now)
    except (TypeError, ValueError):
        return False
    expected = fixture_inventory(
        gate=gate_id,
        destinations=AUTOMATIC_RIGHTS_DESTINATIONS,
        now=now,
        issued_at=now,
        expires_at=_timestamp(issued + RIGHTS_VALIDITY),
    )
    return dict(packet) == expected


def _exact_historical_current_packet(
    gate_id: str, packet: Mapping[str, object]
) -> bool:
    """True only when a current packet equals the original fixture inventory."""

    return dict(packet) == fixture_inventory(gate=gate_id)


def _renewable_retired_endpoint_packet(
    gate_id: str, packet: Mapping[str, object]
) -> bool:
    """True only for sealed packets bound to one explicit retired alias."""

    retired = RETIRED_ENDPOINT_MIGRATIONS.get(gate_id)
    if retired is None:
        return False
    if packet.get("now") != FIXTURE_NOW:
        return False
    if packet.get("bound_terms") != bound_terms_identity(gate=gate_id):
        return False
    reviews = packet.get("reviews")
    if type(reviews) not in (tuple, list) or len(reviews) != 3:
        return False
    expected_by_family = {
        family: fixture_review(family, gate=gate_id, endpoint=retired)
        for family in FIXTURE_FAMILIES
    }
    seen: set[str] = set()
    for item in reviews:
        if type(item) is not dict:
            return False
        family = item.get("reviewer_family")
        if type(family) is not str or family not in expected_by_family:
            return False
        if family in seen:
            return False
        seen.add(family)
        if dict(item) != expected_by_family[family]:
            return False
    return seen == set(FIXTURE_FAMILIES)


def _classify_packet(
    gate_id: str, packet: Mapping[str, object]
) -> PacketClass | None:
    if _exact_current_automatic_renewal_contract(gate_id, packet):
        return "AUTO_CURRENT"
    if _exact_historical_current_packet(gate_id, packet):
        return "HISTORICAL_CURRENT"
    if _renewable_retired_endpoint_packet(gate_id, packet):
        return "HISTORICAL_RETIRED"
    return None


def _validated_packets(
    rows: tuple[tuple[str, str, str], ...],
) -> tuple[dict[str, dict[str, object]], bool]:
    packets: dict[str, dict[str, object]] = {}
    classifications: dict[str, PacketClass] = {}
    for gate_id, packet_digest, packet_json in rows:
        try:
            raw = json.loads(packet_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RightsRenewalError("retained rights packet is malformed") from exc
        if type(raw) is not dict:
            raise RightsRenewalError("retained rights packet is malformed")
        packet = dict(raw)
        try:
            computed_digest = digest_bytes(canonical_json_bytes(packet))
        except (TypeError, ValueError, UnicodeError) as exc:
            raise RightsRenewalError("retained rights packet is malformed") from exc
        if computed_digest != packet_digest:
            raise RightsRenewalError("retained rights packet digest differs")
        if gate_id not in EMITTED_GATES:
            raise RightsRenewalError("retained rights packet set is incomplete")
        if packet.get("bound_terms") != bound_terms_identity(gate=gate_id):
            raise RightsRenewalError("retained rights terms identity differs")
        packet_class = _classify_packet(gate_id, packet)
        if packet_class is None:
            raise RightsRenewalError("retained rights packet is not validly sealed")
        verdict = assess_rights(gate_id, inventory=packet)
        if packet_class in ("AUTO_CURRENT", "HISTORICAL_CURRENT"):
            if verdict.status != "PASS":
                raise RightsRenewalError("retained rights packet is not validly sealed")
        elif (
            verdict.reason != "binding mismatch"
            or not _renewable_retired_endpoint_packet(gate_id, packet)
        ):
            raise RightsRenewalError("retained rights packet is not validly sealed")
        packets[gate_id] = packet
        classifications[gate_id] = packet_class
    if set(packets) != EMITTED_GATES:
        raise RightsRenewalError("retained rights packet set is incomplete")
    class_values = set(classifications.values())
    if class_values == {"AUTO_CURRENT"}:
        return packets, False
    if class_values <= {"HISTORICAL_CURRENT", "HISTORICAL_RETIRED"}:
        if "HISTORICAL_RETIRED" in class_values:
            return packets, True
        raise RightsRenewalError("retained rights packet is not validly sealed")
    raise RightsRenewalError("retained rights packet is not validly sealed")


def _renewed_packets(now: datetime) -> dict[str, dict[str, object]]:
    issued_at = _timestamp(now)
    expires_at = _timestamp(now + RIGHTS_VALIDITY)
    return {
        gate_id: fixture_inventory(
            gate=gate_id,
            destinations=AUTOMATIC_RIGHTS_DESTINATIONS,
            now=issued_at,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        for gate_id in sorted(EMITTED_GATES)
    }


def _needs_renewal(
    packets: Mapping[str, Mapping[str, object]], *, now: datetime
) -> bool:
    renewal_boundary = now + RIGHTS_RENEWAL_LEAD
    renewal_required = False
    for gate_id, packet in packets.items():
        verdict = assess_rights(gate_id, inventory=packet)
        if verdict.status != "PASS":
            if (
                verdict.reason == "binding mismatch"
                and _renewable_retired_endpoint_packet(gate_id, packet)
            ):
                renewal_required = True
                continue
            raise RightsRenewalError("retained rights packet is not validly sealed")
        if not _exact_current_automatic_renewal_contract(gate_id, packet):
            raise RightsRenewalError("retained rights packet is not validly sealed")
        packet_now = packet.get("now")
        if type(packet_now) is not str:
            raise RightsRenewalError("retained rights packet is not validly sealed")
        if _instant(packet_now) > now:
            raise RightsRenewalError("retained rights packet is not validly sealed")
        if verdict.expires_at is None:
            raise RightsRenewalError("retained rights expiry is absent")
        if _instant(verdict.expires_at) <= renewal_boundary:
            renewal_required = True
    return renewal_required


def automatic_rights_arguments(
    *, proving_store: str, now: datetime
) -> dict[str, object]:
    """Return one complete reusable or renewed rights packet set.

    Renewal preserves the accepted fixture review contract. It does not claim
    that autonomous risk acceptance is permission from a source owner.
    Reuse or automatic renewal requires every retained packet to exactly equal
    the dynamic 30-day automatic contract. A one-time whole-set migration is
    permitted only when every packet is a sealed historical current or retired
    fixture and at least one retired UK-10 or RAD-01 alias is present; mixed
    auto/historical sets and all-current historical sets fail closed.
    """

    instant = now.astimezone(UTC)
    rows = _latest_packet_rows(proving_store)
    if rows is None:
        packets = _renewed_packets(instant)
    else:
        packets, stale = _validated_packets(rows)
        if stale or _needs_renewal(packets, now=instant):
            packets = _renewed_packets(instant)
    arguments: dict[str, object] = {
        RIGHTS_ARGUMENT_BY_GATE[gate_id]: packet
        for gate_id, packet in packets.items()
    }
    arguments["now"] = _timestamp(instant)
    return arguments


__all__ = [
    "RIGHTS_RENEWAL_LEAD",
    "RIGHTS_VALIDITY",
    "AUTOMATIC_RIGHTS_DESTINATIONS",
    "RETIRED_ENDPOINT_MIGRATIONS",
    "RIGHTS_ARGUMENT_BY_GATE",
    "RightsRenewalError",
    "automatic_rights_arguments",
]
