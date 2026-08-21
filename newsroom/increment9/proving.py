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
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from urllib.parse import urlsplit

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.prospective_run_authority import (
    GATE_ID as RUN_AUTHORITY_GATE,
    RunAuthorityResolver,
    assess_run_authority,
)
from newsroom.increment9.rights import (
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
PROVING_WRITE_TIMEOUT_SECONDS = 205.0
FORBIDDEN_STORE_MARKERS = ("news_pool.sqlite3", "production")

# OD-001 portfolio. Endpoints from docs/research/2026-07-15-concrete-news-source-map.md
PORTFOLIO: tuple[tuple[str, str], ...] = (
    (
        "UK-01",
        "https://www.gov.uk/search/all.atom?organisations%5B%5D=home-office&organisations%5B%5D=uk-visas-and-immigration&order=updated-newest",
    ),
    ("UK-02", "https://www.gov.uk/api/content/british-national-overseas-bno-visa"),
    ("UK-03", "https://www.gov.uk/api/content/guidance/immigration-rules"),
    (
        "UK-05",
        "https://www.gov.uk/search/all.atom?organisations%5B%5D=department-for-education&organisations%5B%5D=ofqual&order=updated-newest",
    ),
    (
        "UK-10",
        "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK",
    ),
    ("HK-01", "https://www.news.gov.hk/tc/common/html/topstories.rss.xml"),
    (
        "HK-02",
        "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc",
    ),
    ("HK-04", "https://www.edb.gov.hk/tc/whats_new_rss.xml"),
    ("RAD-01", "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"),
    ("RAD-02", "https://feeds.bbci.co.uk/news/uk/rss.xml"),
)
SOURCE_IDS = tuple(item[0] for item in PORTFOLIO)
SOURCE_URLS = {item[0]: item[1] for item in PORTFOLIO}
ALLOWED_HOSTS = frozenset(urlsplit(url).hostname or "" for _, url in PORTFOLIO)

PROVING_GATES = (
    "PORTFOLIO_BOUND",
    "EGRESS_ALLOWLIST_ENFORCED",
    "NO_PUBLICATION",
    "KILL_SWITCH_READY",
    "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
    "PROSPECTIVE_RUN_AUTHORITY",
    "RIGHTS_UK-01",
    "RIGHTS_UK-02",
    "RIGHTS_UK-03",
    "RIGHTS_UK-05",
    "RIGHTS_UK-10",
    "RIGHTS_HK-01",
    "RIGHTS_HK-02",
    "RIGHTS_HK-04",
    "RIGHTS_RAD-01",
    "RIGHTS_RAD-02",
    "OPENROUTER_UNUSED",
)

Fetcher = Callable[[str], tuple[int, bytes]]


class ProvingError(ValueError):
    """Proving store input, gate or fetch failed closed."""


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class Gate:
    gate_id: str
    status: GateStatus
    reason: str


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
class ProvingReport:
    run_id: str
    publication: bool
    public_dispatch: bool
    openrouter_invoked: bool
    spend_gbp_minor: int
    gates: tuple[Gate, ...]
    observations: tuple[Observation, ...]

    @property
    def authorised(self) -> bool:
        return all(gate.status is GateStatus.PASS for gate in self.gates)

    @property
    def complete(self) -> bool:
        seen = {item.source_id for item in self.observations if item.status_code == 200}
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


def _item_count(url: str, body: bytes) -> int:
    text = body.decode("utf-8", errors="replace")
    if "json" in (urlsplit(url).path + urlsplit(url).query) or url.endswith(".json") or "opendata" in url or "/api/" in url:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return 0
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        return 1
    return text.count("<entry") + text.count("<item")


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
    authority_status = (
        GateStatus.PASS if verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_verdict = assess_rights(RIGHTS_UK_01, inventory=rights, now=now)
    rights_status = (
        GateStatus.PASS if rights_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_uk_02_verdict = assess_rights(
        RIGHTS_UK_02, inventory=rights_uk_02, now=now
    )
    rights_uk_02_status = (
        GateStatus.PASS if rights_uk_02_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_uk_03_verdict = assess_rights(
        RIGHTS_UK_03, inventory=rights_uk_03, now=now
    )
    rights_uk_03_status = (
        GateStatus.PASS if rights_uk_03_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_uk_05_verdict = assess_rights(
        RIGHTS_UK_05, inventory=rights_uk_05, now=now
    )
    rights_uk_05_status = (
        GateStatus.PASS if rights_uk_05_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_uk_10_verdict = assess_rights(
        RIGHTS_UK_10, inventory=rights_uk_10, now=now
    )
    rights_uk_10_status = (
        GateStatus.PASS if rights_uk_10_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_hk_01_verdict = assess_rights(
        RIGHTS_HK_01, inventory=rights_hk_01, now=now
    )
    rights_hk_01_status = (
        GateStatus.PASS if rights_hk_01_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_hk_02_verdict = assess_rights(
        RIGHTS_HK_02, inventory=rights_hk_02, now=now
    )
    rights_hk_02_status = (
        GateStatus.PASS if rights_hk_02_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_hk_04_verdict = assess_rights(
        RIGHTS_HK_04, inventory=rights_hk_04, now=now
    )
    rights_hk_04_status = (
        GateStatus.PASS if rights_hk_04_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_rad_01_verdict = assess_rights(
        RIGHTS_RAD_01, inventory=rights_rad_01, now=now
    )
    rights_rad_01_status = (
        GateStatus.PASS if rights_rad_01_verdict.status == "PASS" else GateStatus.FAIL
    )
    rights_rad_02_verdict = assess_rights(
        RIGHTS_RAD_02, inventory=rights_rad_02, now=now
    )
    rights_rad_02_status = (
        GateStatus.PASS if rights_rad_02_verdict.status == "PASS" else GateStatus.FAIL
    )
    return (
        Gate("PORTFOLIO_BOUND", GateStatus.PASS if SOURCE_IDS == tuple(item[0] for item in PORTFOLIO) else GateStatus.FAIL, "OD-001 ten"),
        Gate("EGRESS_ALLOWLIST_ENFORCED", GateStatus.PASS if allowlist_ok else GateStatus.FAIL, ",".join(sorted(ALLOWED_HOSTS))),
        Gate("NO_PUBLICATION", GateStatus.PASS, "publication remains false"),
        Gate("KILL_SWITCH_READY", GateStatus.FAIL if kill_switch else GateStatus.PASS, "kill" if kill_switch else "clear"),
        Gate(
            "NO_ACTIVE_HUMAN_EMERGENCY_STOP",
            GateStatus.PASS if no_emergency_stop else GateStatus.FAIL,
            "attested" if no_emergency_stop else "attestation required",
        ),
        Gate(RUN_AUTHORITY_GATE, authority_status, verdict.reason),
        Gate(RIGHTS_UK_01, rights_status, rights_verdict.reason),
        Gate(RIGHTS_UK_02, rights_uk_02_status, rights_uk_02_verdict.reason),
        Gate(RIGHTS_UK_03, rights_uk_03_status, rights_uk_03_verdict.reason),
        Gate(RIGHTS_UK_05, rights_uk_05_status, rights_uk_05_verdict.reason),
        Gate(RIGHTS_UK_10, rights_uk_10_status, rights_uk_10_verdict.reason),
        Gate(RIGHTS_HK_01, rights_hk_01_status, rights_hk_01_verdict.reason),
        Gate(RIGHTS_HK_02, rights_hk_02_status, rights_hk_02_verdict.reason),
        Gate(RIGHTS_HK_04, rights_hk_04_status, rights_hk_04_verdict.reason),
        Gate(RIGHTS_RAD_01, rights_rad_01_status, rights_rad_01_verdict.reason),
        Gate(RIGHTS_RAD_02, rights_rad_02_status, rights_rad_02_verdict.reason),
        Gate("OPENROUTER_UNUSED", GateStatus.PASS, "proving must not call OpenRouter"),
    )


def _connect(path: str) -> sqlite3.Connection:
    lowered = path.lower()
    if any(marker in lowered for marker in FORBIDDEN_STORE_MARKERS):
        raise ProvingError("proving store must not alias production or news_pool")
    connection = sqlite3.connect(path, timeout=PROVING_WRITE_TIMEOUT_SECONDS)
    connection.execute(
        f"PRAGMA busy_timeout={int(PROVING_WRITE_TIMEOUT_SECONDS * 1_000)}"
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
        """
    )
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
) -> ProvingReport:
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
                connection,
                run_id,
                now or fetched_at,
                {
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
                },
            )
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ProvingError("proving run_id already retained") from exc
        if any(gate.status is GateStatus.FAIL for gate in gates):
            connection.commit()
            return ProvingReport(run_id, False, False, False, 0, gates, ())
        fetcher = default_fetch if fetch is None else fetch
        observations: list[Observation] = []
        for source_id, url in PORTFOLIO:
            assert_allowed_url(url)
            try:
                status, body = fetcher(url)
                error = None if status == 200 else f"http-{status}"
            except ProvingError as exc:
                status, body, error = 0, b"", str(exc)
            observation = Observation(
                source_id=source_id,
                url=url,
                fetched_at=fetched_at,
                status_code=status,
                body_digest=digest_bytes(body),
                item_count=_item_count(url, body) if status == 200 else 0,
                error=error,
            )
            _put(connection, run_id, fetched_at, observation, body)
            observations.append(observation)
        connection.commit()
        return ProvingReport(run_id, False, False, False, 0, gates, tuple(observations))
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
    }
    return canonical_json_bytes(payload)
