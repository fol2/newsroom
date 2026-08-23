"""Increment 9P proving live source store.

Fetches the frozen OD-001 public endpoints and retains Source Observations in
an isolated SQLite file. No publication, Graphiti, Neo4j, embeddings, OpenRouter
or Hermes daemon. Loading this module performs no network I/O.
"""

from __future__ import annotations

import json
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable
from urllib.parse import urlsplit

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.effective_revision import (
    create_effective_revision_schema,
    retain_observation_revision_first_seen,
)
from newsroom.increment9.prospective_run_authority import (
    GATE_ID as RUN_AUTHORITY_GATE,
    RunAuthorityResolver,
    assess_run_authority,
)
from newsroom.increment9.rights import (
    BINDINGS,
    GATE_ID as RIGHTS_UK_01,
    HK_01_GATE_ID as RIGHTS_HK_01,
    HK_02_GATE_ID as RIGHTS_HK_02,
    HK_04_GATE_ID as RIGHTS_HK_04,
    RAD_01_GATE_ID as RIGHTS_RAD_01,
    RAD_02_GATE_ID as RIGHTS_RAD_02,
    UK_02_GATE_ID as RIGHTS_UK_02,
    UK_03_GATE_ID as RIGHTS_UK_03,
    UK_05_GATE_ID as RIGHTS_UK_05,
    UK_10_GATE_ID as RIGHTS_UK_10,
    assess_rights,
)

SCHEMA_VERSION = "newsroom.increment9.proving-store.v1"
USER_AGENT = "Newsroom-9P-Proving/1.0"
MAX_BODY_BYTES = 1_048_576
TIMEOUT_SECONDS = 20
MAX_REDIRECTS = 3
FETCH_MAX_ATTEMPTS = 3
FETCH_RETRY_DELAYS_SECONDS = (0.25, 1.0)
SOURCE_RETRY_SECONDS = 300
FORBIDDEN_STORE_MARKERS = ("news_pool.sqlite3", "production")

_PORTFOLIO_GATE_ORDER = (
    RIGHTS_UK_01,
    RIGHTS_UK_02,
    RIGHTS_UK_03,
    RIGHTS_UK_05,
    RIGHTS_UK_10,
    RIGHTS_HK_01,
    RIGHTS_HK_02,
    RIGHTS_HK_04,
    RIGHTS_RAD_01,
    RIGHTS_RAD_02,
)
PORTFOLIO: tuple[tuple[str, str], ...] = tuple(
    (BINDINGS[gate_id][0], BINDINGS[gate_id][2])
    for gate_id in _PORTFOLIO_GATE_ORDER
)
SOURCE_IDS = tuple(item[0] for item in PORTFOLIO)
SOURCE_URLS = {item[0]: item[1] for item in PORTFOLIO}
ALLOWED_HOSTS = frozenset(urlsplit(url).hostname or "" for _, url in PORTFOLIO)

PROVING_MAX_FETCH_BUDGET_SECONDS = len(SOURCE_IDS) * (
    FETCH_MAX_ATTEMPTS * TIMEOUT_SECONDS
    + sum(FETCH_RETRY_DELAYS_SECONDS[: FETCH_MAX_ATTEMPTS - 1])
)
PROVING_WRITE_TIMEOUT_MARGIN_SECONDS = 30.0
PROVING_WRITE_TIMEOUT_SECONDS = (
    PROVING_MAX_FETCH_BUDGET_SECONDS + PROVING_WRITE_TIMEOUT_MARGIN_SECONDS
)

PROVING_GATES = (
    "PORTFOLIO_BOUND",
    "EGRESS_ALLOWLIST_ENFORCED",
    "NO_PUBLICATION",
    "KILL_SWITCH_READY",
    "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
    "PROSPECTIVE_RUN_AUTHORITY",
    *_PORTFOLIO_GATE_ORDER,
    "OPENROUTER_UNUSED",
)
GLOBAL_PROVING_GATES = frozenset(
    gate_id for gate_id in PROVING_GATES if not gate_id.startswith("RIGHTS_")
)
RIGHTS_GATE_BY_SOURCE = {
    BINDINGS[gate_id][0]: gate_id for gate_id in _PORTFOLIO_GATE_ORDER
}

Fetcher = Callable[[str], tuple[int, bytes]]


class ProvingError(ValueError):
    """Proving store input, gate or fetch failed closed."""


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class SourceHealthStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    HELD = "HELD"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Gate:
    gate_id: str
    status: GateStatus
    reason: str


@dataclass(frozen=True, slots=True)
class ContentAssessment:
    usable: bool
    item_count: int
    error: str | None


@dataclass(frozen=True, slots=True)
class Observation:
    source_id: str
    url: str
    fetched_at: str
    status_code: int
    body_digest: str
    item_count: int
    error: str | None


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: str
    run_id: str
    status: SourceHealthStatus
    endpoint: str
    attempts: int
    reason: str | None
    next_retry_at: str | None
    recovered_at: str | None


@dataclass(frozen=True, slots=True)
class ProvingReport:
    run_id: str
    publication: bool
    public_dispatch: bool
    openrouter_invoked: bool
    spend_gbp_minor: int
    gates: tuple[Gate, ...]
    observations: tuple[Observation, ...]
    source_health: tuple[SourceHealth, ...] = ()

    @property
    def authorised(self) -> bool:
        return all(gate.status is GateStatus.PASS for gate in self.gates)

    @property
    def complete(self) -> bool:
        seen = {
            item.source_id
            for item in self.observations
            if item.status_code == 200 and item.error is None
        }
        return self.authorised and seen == set(SOURCE_IDS)


class _AllowlistedHttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hops = int(getattr(req, "proving_hops", 0)) + 1
        if hops > MAX_REDIRECTS:
            raise ProvingError("too many redirects")
        assert_allowed_redirect(newurl)
        nxt = urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl
        )
        if nxt is not None:
            nxt.proving_hops = hops
        return nxt


def _host(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProvingError("only https URLs with a host are permitted")
    return parsed.hostname.lower()


def assert_allowed_url(url: str) -> str:
    host = _host(url)
    if host not in ALLOWED_HOSTS:
        raise ProvingError(f"host not on proving allowlist: {host}")
    return host


def assert_allowed_redirect(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ProvingError("redirects must stay on https")
    return assert_allowed_url(url)


def _json_url(url: str) -> bool:
    path_query = urlsplit(url).path + urlsplit(url).query
    return (
        "json" in path_query
        or url.endswith(".json")
        or "opendata" in url
        or "/api/" in url
    )


def _xml_root_tag(root: ET.Element) -> str:
    tag = root.tag
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    return tag.lower()


def _feed_item_count(root: ET.Element) -> int:
    count = 0
    for element in root.iter():
        tag = element.tag
        if "}" in tag:
            tag = tag.rsplit("}", 1)[-1]
        if tag.lower() in {"item", "entry"}:
            count += 1
    return count


def _parsed_item_count(url: str, body: bytes) -> int:
    from newsroom.control_plane.items import parse_observation

    source_id = next(
        (source_id for source_id, source_url in SOURCE_URLS.items() if source_url == url),
        "CONTENT-ASSESSMENT",
    )
    return len(parse_observation(source_id=source_id, url=url, body=body))


def assess_content(url: str, body: bytes) -> ContentAssessment:
    if not body:
        return ContentAssessment(False, 0, "content-empty")
    if _json_url(url):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return ContentAssessment(False, 0, "content-non-utf8")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return ContentAssessment(False, 0, "content-malformed-json")
        if isinstance(value, list):
            expected_count = len(value)
        if isinstance(value, dict):
            if not value:
                return ContentAssessment(True, 0, None)
            status = value.get("status")
            if (
                "error" in value
                or "errors" in value
                or (
                    isinstance(status, str)
                    and status.strip().lower() in {"error", "failed", "failure"}
                )
            ):
                return ContentAssessment(False, 0, "content-malformed-json")
            expected_count = (
                1
                if any(key in value for key in ("title", "name", "code", "base_path"))
                else len(value)
            )
        elif not isinstance(value, list):
            return ContentAssessment(False, 0, "content-malformed-json")
        item_count = _parsed_item_count(url, body)
        if item_count != expected_count:
            return ContentAssessment(False, 0, "content-malformed-json")
        return ContentAssessment(True, item_count, None)
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, LookupError):
        return ContentAssessment(False, 0, "content-malformed-xml")
    root_tag = _xml_root_tag(root)
    if root_tag not in {"rss", "feed"}:
        return ContentAssessment(False, 0, f"content-unexpected-root:{root_tag}")
    item_count = _feed_item_count(root)
    if _parsed_item_count(url, body) != item_count:
        return ContentAssessment(False, 0, "content-malformed-xml")
    return ContentAssessment(True, item_count, None)


def default_fetch(url: str) -> tuple[int, bytes]:
    assert_allowed_url(url)
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    request.proving_hops = 0
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _AllowlistedHttpsRedirect(),
    )
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200))
            body = response.read(MAX_BODY_BYTES + 1)
    except ProvingError:
        raise
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BODY_BYTES + 1) if exc.fp else b""
        if len(body) > MAX_BODY_BYTES:
            raise ProvingError("response exceeds proving body bound") from exc
        return int(exc.code), body
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise ProvingError(f"transport failed: {exc}") from exc
    if len(body) > MAX_BODY_BYTES:
        raise ProvingError("response exceeds proving body bound")
    return status, body


def _retryable_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status <= 599


def _fetch_with_repair(
    fetcher: Fetcher,
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, bytes, str | None, int]:
    """Retry transient source failures before returning a degraded result."""

    last_error: str | None = None
    status, body = 0, b""
    for attempt in range(1, FETCH_MAX_ATTEMPTS + 1):
        try:
            status, body = fetcher(url)
        except ProvingError as exc:
            status, body, last_error = 0, b"", str(exc)
        else:
            if status == 200:
                assessment = assess_content(url, body)
                if assessment.usable:
                    return status, body, None, attempt
                last_error = assessment.error or "content-unusable"
            else:
                last_error = f"http-{status}"
                if not _retryable_status(status):
                    return status, body, last_error, attempt
        if attempt < FETCH_MAX_ATTEMPTS:
            sleep(FETCH_RETRY_DELAYS_SECONDS[attempt - 1])
    return status, body, last_error, FETCH_MAX_ATTEMPTS


def _rights_packets(
    *,
    rights: object | None,
    rights_uk_02: object | None,
    rights_uk_03: object | None,
    rights_uk_05: object | None,
    rights_uk_10: object | None,
    rights_hk_01: object | None,
    rights_hk_02: object | None,
    rights_hk_04: object | None,
    rights_rad_01: object | None,
    rights_rad_02: object | None,
) -> dict[str, object | None]:
    return {
        RIGHTS_UK_01: rights,
        RIGHTS_UK_02: rights_uk_02,
        RIGHTS_UK_03: rights_uk_03,
        RIGHTS_UK_05: rights_uk_05,
        RIGHTS_UK_10: rights_uk_10,
        RIGHTS_HK_01: rights_hk_01,
        RIGHTS_HK_02: rights_hk_02,
        RIGHTS_HK_04: rights_hk_04,
        RIGHTS_RAD_01: rights_rad_01,
        RIGHTS_RAD_02: rights_rad_02,
    }


def _rights_gate(gate_id: str, inventory: object | None, now: str | None) -> Gate:
    verdict = assess_rights(gate_id, inventory=inventory, now=now)
    status = GateStatus.PASS if verdict.status == "PASS" else GateStatus.FAIL
    return Gate(gate_id, status, verdict.reason)


def assess(
    *,
    run_id: str,
    kill_switch: bool,
    no_emergency_stop: bool,
    run_authority: RunAuthorityResolver | None = None,
    rights: object | None = None,
    rights_uk_02: object | None = None,
    rights_uk_03: object | None = None,
    rights_uk_05: object | None = None,
    rights_uk_10: object | None = None,
    rights_hk_01: object | None = None,
    rights_hk_02: object | None = None,
    rights_hk_04: object | None = None,
    rights_rad_01: object | None = None,
    rights_rad_02: object | None = None,
    now: str | None = None,
) -> tuple[Gate, ...]:
    if type(run_id) is not str or not run_id.strip():
        raise ProvingError("run_id is required")
    hosts = tuple(_host(url) for url in SOURCE_URLS.values())
    allowlist_ok = set(hosts) <= ALLOWED_HOSTS and len(SOURCE_IDS) == 10
    verdict = assess_run_authority(run_id, resolver=run_authority)
    packets = _rights_packets(
        rights=rights,
        rights_uk_02=rights_uk_02,
        rights_uk_03=rights_uk_03,
        rights_uk_05=rights_uk_05,
        rights_uk_10=rights_uk_10,
        rights_hk_01=rights_hk_01,
        rights_hk_02=rights_hk_02,
        rights_hk_04=rights_hk_04,
        rights_rad_01=rights_rad_01,
        rights_rad_02=rights_rad_02,
    )
    return (
        Gate(
            "PORTFOLIO_BOUND",
            GateStatus.PASS
            if SOURCE_IDS == tuple(item[0] for item in PORTFOLIO)
            else GateStatus.FAIL,
            "OD-001 ten",
        ),
        Gate(
            "EGRESS_ALLOWLIST_ENFORCED",
            GateStatus.PASS if allowlist_ok else GateStatus.FAIL,
            ",".join(sorted(ALLOWED_HOSTS)),
        ),
        Gate("NO_PUBLICATION", GateStatus.PASS, "publication remains false"),
        Gate(
            "KILL_SWITCH_READY",
            GateStatus.FAIL if kill_switch else GateStatus.PASS,
            "kill" if kill_switch else "clear",
        ),
        Gate(
            "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
            GateStatus.PASS if no_emergency_stop else GateStatus.FAIL,
            "attested" if no_emergency_stop else "attestation required",
        ),
        Gate(
            RUN_AUTHORITY_GATE,
            GateStatus.PASS if verdict.status == "PASS" else GateStatus.FAIL,
            verdict.reason,
        ),
        *(
            _rights_gate(gate_id, packets[gate_id], now)
            for gate_id in _PORTFOLIO_GATE_ORDER
        ),
        Gate("OPENROUTER_UNUSED", GateStatus.PASS, "proving must not call OpenRouter"),
    )


def _connect(path: str) -> sqlite3.Connection:
    # Import here: control_plane.__init__ loads cycle → Graphiti → this module.
    from newsroom.control_plane.sqlite_profile import apply_control_plane_sqlite_profile

    lowered = path.lower()
    if any(marker in lowered for marker in FORBIDDEN_STORE_MARKERS):
        raise ProvingError("proving store must not alias production or news_pool")
    connection = sqlite3.connect(path, timeout=PROVING_WRITE_TIMEOUT_SECONDS)
    apply_control_plane_sqlite_profile(
        connection,
        wal=None,
        busy_timeout_ms=int(PROVING_WRITE_TIMEOUT_SECONDS * 1_000),
    )
    deadline = time.monotonic() + PROVING_WRITE_TIMEOUT_SECONDS
    while True:
        try:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "wal":
                connection.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError as exc:
            remaining = deadline - time.monotonic()
            if "locked" not in str(exc).lower() or remaining <= 0:
                connection.close()
                raise ProvingError("proving store writer lock timed out") from exc
            time.sleep(min(0.05, remaining))
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS proving_runs(
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            publication INTEGER NOT NULL DEFAULT 0 CHECK(publication=0),
            public_dispatch INTEGER NOT NULL DEFAULT 0 CHECK(public_dispatch=0),
            openrouter_invoked INTEGER NOT NULL DEFAULT 0 CHECK(openrouter_invoked=0),
            spend_gbp_minor INTEGER NOT NULL DEFAULT 0 CHECK(spend_gbp_minor=0)
        );
        CREATE TABLE IF NOT EXISTS proving_observations(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            body_digest TEXT NOT NULL,
            body BLOB NOT NULL,
            item_count INTEGER NOT NULL,
            error TEXT,
            PRIMARY KEY(run_id, source_id, body_digest),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS proving_gates(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS proving_rights_packets(
            run_id TEXT NOT NULL,
            gate_id TEXT NOT NULL,
            packet_digest TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            assessed_at TEXT NOT NULL,
            PRIMARY KEY(run_id, gate_id),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS proving_source_health(
            source_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('ACTIVE','DEGRADED','HELD','BLOCKED')),
            endpoint TEXT NOT NULL,
            attempts INTEGER NOT NULL CHECK(attempts >= 0),
            reason TEXT,
            next_retry_at TEXT,
            recovered_at TEXT,
            PRIMARY KEY(run_id, source_id),
            FOREIGN KEY(run_id) REFERENCES proving_runs(run_id)
        );
        """
    )
    create_effective_revision_schema(connection)
    return connection


def rights_permitted_sources(
    connection: sqlite3.Connection, run_id: str
) -> frozenset[str]:
    names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "proving_gates" not in names:
        return frozenset()
    rows = connection.execute(
        "SELECT gate_id FROM proving_gates WHERE run_id=? AND status=?",
        (run_id, GateStatus.PASS.value),
    )
    permitted: set[str] = set()
    for (gate_id,) in rows:
        if not str(gate_id).startswith("RIGHTS_"):
            continue
        source_id = str(gate_id).removeprefix("RIGHTS_")
        if source_id in SOURCE_IDS:
            permitted.add(source_id)
    return frozenset(permitted)


def _put_gates(
    connection: sqlite3.Connection, run_id: str, gates: tuple[Gate, ...]
) -> None:
    for gate in gates:
        connection.execute(
            "INSERT INTO proving_gates VALUES(?,?,?,?)",
            (run_id, gate.gate_id, gate.status.value, gate.reason),
        )


def _put_rights_packets(
    connection: sqlite3.Connection,
    run_id: str,
    assessed_at: str,
    packets: dict[str, object | None],
) -> None:
    """Retain exact review packets for dispatch-time expiry evaluation."""

    for gate_id, packet in packets.items():
        if not isinstance(packet, dict):
            continue
        packet_bytes = canonical_json_bytes(packet)
        connection.execute(
            """
            INSERT INTO proving_rights_packets(
                run_id, gate_id, packet_digest, packet_json, assessed_at
            ) VALUES(?,?,?,?,?)
            """,
            (
                run_id,
                gate_id,
                digest_bytes(packet_bytes),
                packet_bytes.decode("utf-8"),
                assessed_at,
            ),
        )


def _put(connection: sqlite3.Connection, run_id: str, fetched_at: str, observation: Observation, body: bytes) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)",
        (
            observation.source_id,
            run_id,
            fetched_at,
            observation.url,
            observation.status_code,
            observation.body_digest,
            body,
            observation.item_count,
            observation.error,
        ),
    )
    if observation.status_code != 200 or observation.error is not None:
        return
    retain_observation_revision_first_seen(
        connection,
        source_id=observation.source_id,
        url=observation.url,
        body=body,
        observed_at=fetched_at,
    )


def _retry_at(fetched_at: str) -> str:
    instant = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=UTC
    )
    return (instant + timedelta(seconds=SOURCE_RETRY_SECONDS)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _health(
    *,
    source_id: str,
    run_id: str,
    status: SourceHealthStatus,
    endpoint: str,
    attempts: int,
    reason: str | None,
    fetched_at: str,
    recovered_at: str | None = None,
) -> SourceHealth:
    return SourceHealth(
        source_id=source_id,
        run_id=run_id,
        status=status,
        endpoint=endpoint,
        attempts=attempts,
        reason=reason,
        next_retry_at=(
            None if status is SourceHealthStatus.ACTIVE else _retry_at(fetched_at)
        ),
        recovered_at=recovered_at,
    )


def _recovered_at(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    run_id: str,
    current_status: SourceHealthStatus,
    fetched_at: str,
) -> str | None:
    if current_status is not SourceHealthStatus.ACTIVE:
        return None
    previous = connection.execute(
        """
        SELECT health.status
        FROM proving_source_health AS health
        JOIN proving_runs AS run ON run.run_id=health.run_id
        WHERE health.source_id=? AND health.run_id<>?
        ORDER BY run.rowid DESC
        LIMIT 1
        """,
        (source_id, run_id),
    ).fetchone()
    if previous is not None and str(previous[0]) != SourceHealthStatus.ACTIVE.value:
        return fetched_at
    return None


def _put_source_health(
    connection: sqlite3.Connection, health: SourceHealth
) -> None:
    connection.execute(
        """
        INSERT INTO proving_source_health(
            source_id, run_id, status, endpoint, attempts, reason,
            next_retry_at, recovered_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            health.source_id,
            health.run_id,
            health.status.value,
            health.endpoint,
            health.attempts,
            health.reason,
            health.next_retry_at,
            health.recovered_at,
        ),
    )


def run_proving(
    *,
    store_path: str,
    run_id: str,
    fetched_at: str,
    kill_switch: bool,
    no_emergency_stop: bool,
    fetch: Fetcher | None = None,
    run_authority: RunAuthorityResolver | None = None,
    rights: object | None = None,
    rights_uk_02: object | None = None,
    rights_uk_03: object | None = None,
    rights_uk_05: object | None = None,
    rights_uk_10: object | None = None,
    rights_hk_01: object | None = None,
    rights_hk_02: object | None = None,
    rights_hk_04: object | None = None,
    rights_rad_01: object | None = None,
    rights_rad_02: object | None = None,
    now: str | None = None,
    retry_sleep: Callable[[float], None] = time.sleep,
) -> ProvingReport:
    packets = _rights_packets(
        rights=rights,
        rights_uk_02=rights_uk_02,
        rights_uk_03=rights_uk_03,
        rights_uk_05=rights_uk_05,
        rights_uk_10=rights_uk_10,
        rights_hk_01=rights_hk_01,
        rights_hk_02=rights_hk_02,
        rights_hk_04=rights_hk_04,
        rights_rad_01=rights_rad_01,
        rights_rad_02=rights_rad_02,
    )
    gates = assess(
        run_id=run_id,
        kill_switch=kill_switch,
        no_emergency_stop=no_emergency_stop,
        run_authority=run_authority,
        rights=rights,
        rights_uk_02=rights_uk_02,
        rights_uk_03=rights_uk_03,
        rights_uk_05=rights_uk_05,
        rights_uk_10=rights_uk_10,
        rights_hk_01=rights_hk_01,
        rights_hk_02=rights_hk_02,
        rights_hk_04=rights_hk_04,
        rights_rad_01=rights_rad_01,
        rights_rad_02=rights_rad_02,
        now=now,
    )
    connection = _connect(store_path)
    try:
        try:
            connection.execute(
                """
                INSERT INTO proving_runs(
                    run_id, started_at, publication, public_dispatch,
                    openrouter_invoked, spend_gbp_minor
                ) VALUES(?,?,0,0,0,0)
                """,
                (run_id, fetched_at),
            )
            _put_gates(connection, run_id, gates)
            _put_rights_packets(
                connection, run_id, now or fetched_at, packets
            )
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ProvingError("proving run_id already retained") from exc
        gates_by_id = {gate.gate_id: gate.status for gate in gates}
        gate_reasons = {gate.gate_id: gate.reason for gate in gates}
        failed_global = tuple(
            gate_id
            for gate_id in sorted(GLOBAL_PROVING_GATES)
            if gates_by_id.get(gate_id) is not GateStatus.PASS
        )
        if failed_global:
            blocked = tuple(
                _health(
                    source_id=source_id,
                    run_id=run_id,
                    status=SourceHealthStatus.BLOCKED,
                    endpoint=url,
                    attempts=0,
                    reason="global gates: " + ",".join(failed_global),
                    fetched_at=fetched_at,
                )
                for source_id, url in PORTFOLIO
            )
            for item in blocked:
                _put_source_health(connection, item)
            connection.commit()
            return ProvingReport(
                run_id, False, False, False, 0, gates, (), blocked
            )
        fetcher = default_fetch if fetch is None else fetch
        observations: list[Observation] = []
        health_items: list[SourceHealth] = []
        for source_id, url in PORTFOLIO:
            rights_gate_id = RIGHTS_GATE_BY_SOURCE[source_id]
            if gates_by_id.get(rights_gate_id) is not GateStatus.PASS:
                held = _health(
                    source_id=source_id,
                    run_id=run_id,
                    status=SourceHealthStatus.HELD,
                    endpoint=url,
                    attempts=0,
                    reason=gate_reasons.get(rights_gate_id, "rights gate failed"),
                    fetched_at=fetched_at,
                )
                _put_source_health(connection, held)
                health_items.append(held)
                continue
            assert_allowed_url(url)
            status, body, error, attempts = _fetch_with_repair(
                fetcher, url, sleep=retry_sleep
            )
            item_count = 0
            if status == 200 and error is None:
                item_count = assess_content(url, body).item_count
            observation = Observation(
                source_id=source_id,
                url=url,
                fetched_at=fetched_at,
                status_code=status,
                body_digest=digest_bytes(body),
                item_count=item_count,
                error=error,
            )
            _put(connection, run_id, fetched_at, observation, body)
            observations.append(observation)
            health_status = (
                SourceHealthStatus.ACTIVE
                if status == 200 and error is None
                else SourceHealthStatus.DEGRADED
            )
            item = _health(
                source_id=source_id,
                run_id=run_id,
                status=health_status,
                endpoint=url,
                attempts=attempts,
                reason=error,
                fetched_at=fetched_at,
                recovered_at=_recovered_at(
                    connection,
                    source_id=source_id,
                    run_id=run_id,
                    current_status=health_status,
                    fetched_at=fetched_at,
                ),
            )
            _put_source_health(connection, item)
            health_items.append(item)
        connection.commit()
        return ProvingReport(
            run_id,
            False,
            False,
            False,
            0,
            gates,
            tuple(observations),
            tuple(health_items),
        )
    except sqlite3.OperationalError as exc:
        connection.rollback()
        if "locked" in str(exc).lower():
            raise ProvingError("proving store writer lock timed out") from exc
        raise
    finally:
        connection.close()


def list_observations(store_path: str) -> tuple[Observation, ...]:
    connection = _connect(store_path)
    try:
        rows = connection.execute(
            "SELECT source_id,url,fetched_at,status_code,body_digest,item_count,error "
            "FROM proving_observations ORDER BY fetched_at,source_id"
        ).fetchall()
    finally:
        connection.close()
    return tuple(Observation(*row) for row in rows)


def list_source_health(store_path: str, *, run_id: str | None = None) -> tuple[SourceHealth, ...]:
    connection = _connect(store_path)
    try:
        selected_run = run_id
        if selected_run is None:
            latest = connection.execute(
                "SELECT run_id FROM proving_runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if latest is None:
                return ()
            selected_run = str(latest[0])
        rows = connection.execute(
            """
            SELECT source_id, run_id, status, endpoint, attempts, reason,
                   next_retry_at, recovered_at
            FROM proving_source_health
            WHERE run_id=?
            ORDER BY source_id
            """,
            (selected_run,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(
        SourceHealth(
            source_id=str(row[0]),
            run_id=str(row[1]),
            status=SourceHealthStatus(str(row[2])),
            endpoint=str(row[3]),
            attempts=int(row[4]),
            reason=None if row[5] is None else str(row[5]),
            next_retry_at=None if row[6] is None else str(row[6]),
            recovered_at=None if row[7] is None else str(row[7]),
        )
        for row in rows
    )


def report_json(report: ProvingReport) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": report.run_id,
        "publication": report.publication,
        "public_dispatch": report.public_dispatch,
        "openrouter_invoked": report.openrouter_invoked,
        "spend_gbp_minor": report.spend_gbp_minor,
        "complete": report.complete,
        "gates": [{"gate_id": g.gate_id, "status": g.status.value, "reason": g.reason} for g in report.gates],
        "observations": [
            {
                "source_id": item.source_id,
                "url": item.url,
                "fetched_at": item.fetched_at,
                "status_code": item.status_code,
                "body_digest": item.body_digest,
                "item_count": item.item_count,
                "error": item.error,
            }
            for item in report.observations
        ],
        "source_health": [
            {
                "source_id": item.source_id,
                "status": item.status.value,
                "endpoint": item.endpoint,
                "attempts": item.attempts,
                "reason": item.reason,
                "next_retry_at": item.next_retry_at,
                "recovered_at": item.recovered_at,
            }
            for item in report.source_health
        ],
    }
    return canonical_json_bytes(payload)
