from pathlib import Path
import sqlite3

import pytest
import newsroom.increment9.proving as proving_module
from newsroom.increment9.prospective_run_authority import persist_authorised_chain
from newsroom.increment9.proving import (
    ALLOWED_HOSTS,
    FETCH_MAX_ATTEMPTS,
    FETCH_RETRY_DELAYS_SECONDS,
    GLOBAL_PROVING_GATES,
    Observation,
    PORTFOLIO,
    PROVING_MAX_FETCH_BUDGET_SECONDS,
    PROVING_WRITE_TIMEOUT_MARGIN_SECONDS,
    PROVING_WRITE_TIMEOUT_SECONDS,
    SOURCE_IDS,
    SOURCE_URLS,
    TIMEOUT_SECONDS,
    ProvingError,
    SourceHealthStatus,
    assess,
    assess_content,
    assert_allowed_url,
    assert_allowed_redirect,
    list_observations,
    list_source_health,
    report_json,
    run_proving,
)
from newsroom.increment9.rights import (
    FIXTURE_NOW,
    HK_01_GATE_ID,
    HK_02_GATE_ID,
    HK_04_GATE_ID,
    RAD_01_GATE_ID,
    RAD_02_GATE_ID,
    UK_02_GATE_ID,
    UK_03_GATE_ID,
    UK_05_GATE_ID,
    UK_10_GATE_ID,
    fixture_inventory as rights_inventory,
)


def _rights_inventories() -> dict[str, object]:
    return {
        "rights": rights_inventory(),
        "rights_uk_02": rights_inventory(gate=UK_02_GATE_ID),
        "rights_uk_03": rights_inventory(gate=UK_03_GATE_ID),
        "rights_uk_05": rights_inventory(gate=UK_05_GATE_ID),
        "rights_uk_10": rights_inventory(gate=UK_10_GATE_ID),
        "rights_hk_01": rights_inventory(gate=HK_01_GATE_ID),
        "rights_hk_02": rights_inventory(gate=HK_02_GATE_ID),
        "rights_hk_04": rights_inventory(gate=HK_04_GATE_ID),
        "rights_rad_01": rights_inventory(gate=RAD_01_GATE_ID),
        "rights_rad_02": rights_inventory(gate=RAD_02_GATE_ID),
        "now": FIXTURE_NOW,
    }


def _fetch_ok(url: str) -> tuple[int, bytes]:
    if "/api/" in url or "opendata" in url:
        return 200, b'{"title":"x","updated_at":"1"}'
    return 200, b"<feed><entry><title>a</title></entry></feed>"


def test_proving_write_timeout_exceeds_portfolio_fetch_budget_and_is_bounded():
    per_source = (
        FETCH_MAX_ATTEMPTS * TIMEOUT_SECONDS
        + sum(FETCH_RETRY_DELAYS_SECONDS[: FETCH_MAX_ATTEMPTS - 1])
    )
    assert PROVING_MAX_FETCH_BUDGET_SECONDS == len(SOURCE_IDS) * per_source
    assert PROVING_WRITE_TIMEOUT_SECONDS > PROVING_MAX_FETCH_BUDGET_SECONDS
    assert (
        PROVING_WRITE_TIMEOUT_SECONDS
        == PROVING_MAX_FETCH_BUDGET_SECONDS + PROVING_WRITE_TIMEOUT_MARGIN_SECONDS
    )
    assert 0 < PROVING_WRITE_TIMEOUT_MARGIN_SECONDS < PROVING_WRITE_TIMEOUT_SECONDS


def test_portfolio_is_exactly_od001_ten():
    assert SOURCE_IDS == (
        "UK-01",
        "UK-02",
        "UK-03",
        "UK-05",
        "UK-10",
        "HK-01",
        "HK-02",
        "HK-04",
        "RAD-01",
        "RAD-02",
    )
    assert len(PORTFOLIO) == 10
    for _, url in PORTFOLIO:
        assert_allowed_url(url)
    assert "www.gov.uk" in ALLOWED_HOSTS
    assert "www.metoffice.gov.uk" in ALLOWED_HOSTS
    assert "rthk9.rthk.hk" in ALLOWED_HOSTS
    with pytest.raises(ProvingError, match="allowlist"):
        assert_allowed_url("https://discord.com/")
    assert_allowed_redirect(
        "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK"
    )
    with pytest.raises(ProvingError, match="https"):
        assert_allowed_redirect("http://rthk9.rthk.hk/rthk/news/rss/c_expressnews_clocal.xml")
    with pytest.raises(ProvingError, match="allowlist"):
        assert_allowed_redirect("https://discord.com/api")


def test_assess_fails_closed_without_stop_attestation_and_with_kill():
    blocked = assess(run_id="r1", kill_switch=False, no_emergency_stop=False)
    by_id = {g.gate_id: g.status.value for g in blocked}
    assert by_id["NO_ACTIVE_HUMAN_EMERGENCY_STOP"] == "FAIL"
    assert by_id["PROSPECTIVE_RUN_AUTHORITY"] == "FAIL"
    assert by_id["RIGHTS_UK-01"] == "FAIL"
    assert by_id["RIGHTS_UK-02"] == "FAIL"
    assert by_id["RIGHTS_UK-03"] == "FAIL"
    assert by_id["RIGHTS_UK-05"] == "FAIL"
    assert by_id["RIGHTS_UK-10"] == "FAIL"
    assert by_id["RIGHTS_HK-01"] == "FAIL"
    assert by_id["RIGHTS_HK-02"] == "FAIL"
    assert by_id["RIGHTS_HK-04"] == "FAIL"
    assert by_id["RIGHTS_RAD-01"] == "FAIL"
    assert by_id["RIGHTS_RAD-02"] == "FAIL"
    killed = assess(run_id="r1", kill_switch=True, no_emergency_stop=True)
    by_id = {g.gate_id: g.status.value for g in killed}
    assert by_id["KILL_SWITCH_READY"] == "FAIL"
    assert by_id["PROSPECTIVE_RUN_AUTHORITY"] == "FAIL"
    assert by_id["RIGHTS_UK-01"] == "FAIL"
    assert by_id["RIGHTS_UK-02"] == "FAIL"
    assert by_id["RIGHTS_UK-03"] == "FAIL"
    assert by_id["RIGHTS_UK-05"] == "FAIL"
    assert by_id["RIGHTS_UK-10"] == "FAIL"
    assert by_id["RIGHTS_HK-01"] == "FAIL"
    assert by_id["RIGHTS_HK-02"] == "FAIL"
    assert by_id["RIGHTS_HK-04"] == "FAIL"
    assert by_id["RIGHTS_RAD-01"] == "FAIL"
    assert by_id["RIGHTS_RAD-02"] == "FAIL"
    chain = persist_authorised_chain(run_id="r1")
    ok = assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        run_authority=chain.resolver,
        **_rights_inventories(),
    )
    assert all(g.status.value == "PASS" for g in ok)


def test_fetch_is_blocked_until_gates_pass(tmp_path: Path):
    store = str(tmp_path / "proving.sqlite3")
    fetched: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        fetched.append(url)
        return _fetch_ok(url)

    blocked = run_proving(
        store_path=store,
        run_id="r1",
        fetched_at="2026-08-16T20:00:00.000000Z",
        kill_switch=False,
        no_emergency_stop=False,
        fetch=fetch,
    )
    assert not blocked.authorised and blocked.observations == ()
    assert fetched == []
    assert {item.status for item in blocked.source_health} == {
        SourceHealthStatus.BLOCKED
    }
    assert list_observations(store) == ()
    connection = __import__("sqlite3").connect(store)
    failed = connection.execute(
        "SELECT COUNT(*) FROM proving_gates WHERE run_id='r1' AND status='FAIL'"
    ).fetchone()[0]
    run = connection.execute(
        "SELECT run_id FROM proving_runs WHERE run_id='r1'"
    ).fetchone()
    connection.close()
    assert failed > 0
    assert run == ("r1",)


def test_fetch_stores_ten_observations_without_publication(tmp_path: Path):
    store = str(tmp_path / "proving.sqlite3")
    unauthorised = run_proving(
        store_path=store,
        run_id="r1",
        fetched_at="2026-08-16T20:00:00.000000Z",
        kill_switch=False,
        no_emergency_stop=True,
        fetch=_fetch_ok,
    )
    assert not unauthorised.authorised and unauthorised.observations == ()
    assert list_observations(store) == ()
    chain = persist_authorised_chain(run_id="r2")
    report = run_proving(
        store_path=store,
        run_id="r2",
        fetched_at="2026-08-16T20:00:00.000000Z",
        kill_switch=False,
        no_emergency_stop=True,
        fetch=_fetch_ok,
        run_authority=chain.resolver,
        **_rights_inventories(),
    )
    assert report.complete
    assert report.publication is False
    assert report.public_dispatch is False
    assert report.openrouter_invoked is False
    assert report.spend_gbp_minor == 0
    assert tuple(item.source_id for item in report.observations) == SOURCE_IDS
    assert all(item.status_code == 200 for item in report.observations)
    retained = list_observations(store)
    assert len(retained) == 10
    connection = __import__("sqlite3").connect(store)
    stored_gates = connection.execute(
        "SELECT COUNT(*) FROM proving_gates WHERE run_id='r2'"
    ).fetchone()[0]
    retained_revisions = connection.execute(
        "SELECT COUNT(*) FROM proving_revision_first_seen"
    ).fetchone()[0]
    connection.close()
    assert stored_gates == len(report.gates)
    assert retained_revisions == 10
    payload = report_json(report)
    assert b'"publication":false' in payload
    assert b"openrouter" in payload
    assert all(
        item.status is SourceHealthStatus.ACTIVE for item in report.source_health
    )
    assert all(item.attempts == 1 for item in report.source_health)
    assert all(
        item.recovered_at == "2026-08-16T20:00:00.000000Z"
        for item in report.source_health
    )


def test_one_expired_source_is_held_while_nine_continue(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id="partial-rights")
    rights = _rights_inventories()
    rights["rights_uk_10"] = rights_inventory(
        gate=UK_10_GATE_ID,
        expires_at="2026-08-18T12:00:00.000000Z",
    )
    fetched: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        fetched.append(url)
        return _fetch_ok(url)

    report = run_proving(
        store_path=store,
        run_id="partial-rights",
        fetched_at=FIXTURE_NOW,
        kill_switch=False,
        no_emergency_stop=True,
        fetch=fetch,
        run_authority=chain.resolver,
        **rights,
    )

    assert not report.authorised
    assert not report.complete
    assert SOURCE_URLS["UK-10"] not in fetched
    assert len(fetched) == 9
    assert {item.source_id for item in report.observations} == set(SOURCE_IDS) - {
        "UK-10"
    }
    health = {item.source_id: item for item in report.source_health}
    assert health["UK-10"].status is SourceHealthStatus.HELD
    assert health["UK-10"].attempts == 0
    assert health["UK-10"].next_retry_at is not None
    assert all(
        item.status is SourceHealthStatus.ACTIVE
        for source_id, item in health.items()
        if source_id != "UK-10"
    )


def test_transient_source_failure_repairs_before_isolation(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id="transient")
    attempts: dict[str, int] = {}
    delays: list[float] = []

    def transient_fetch(url: str) -> tuple[int, bytes]:
        attempts[url] = attempts.get(url, 0) + 1
        if url == SOURCE_URLS["UK-01"] and attempts[url] < 3:
            raise ProvingError("temporary transport failure")
        return _fetch_ok(url)

    report = run_proving(
        store_path=store,
        run_id="transient",
        fetched_at=FIXTURE_NOW,
        kill_switch=False,
        no_emergency_stop=True,
        fetch=transient_fetch,
        run_authority=chain.resolver,
        retry_sleep=delays.append,
        **_rights_inventories(),
    )

    assert report.complete
    health = {item.source_id: item for item in report.source_health}
    assert health["UK-01"].status is SourceHealthStatus.ACTIVE
    assert health["UK-01"].attempts == 3
    assert health["UK-01"].recovered_at is None
    assert attempts[SOURCE_URLS["UK-01"]] == 3
    assert delays == list(FETCH_RETRY_DELAYS_SECONDS)


def test_degraded_source_records_retry_then_recovery(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    first_chain = persist_authorised_chain(run_id="degraded")

    def degraded_fetch(url: str) -> tuple[int, bytes]:
        if url == SOURCE_URLS["UK-01"]:
            return 503, b""
        return _fetch_ok(url)

    first = run_proving(
        store_path=store,
        run_id="degraded",
        fetched_at="2026-08-18T12:00:00.000000Z",
        kill_switch=False,
        no_emergency_stop=True,
        fetch=degraded_fetch,
        run_authority=first_chain.resolver,
        retry_sleep=lambda _seconds: None,
        **_rights_inventories(),
    )
    first_health = {item.source_id: item for item in first.source_health}
    assert first_health["UK-01"].status is SourceHealthStatus.DEGRADED
    assert first_health["UK-01"].attempts == 3
    assert first_health["UK-01"].reason == "http-503"
    assert first_health["UK-01"].next_retry_at == "2026-08-18T12:05:00.000000Z"
    assert first_health["UK-01"].recovered_at is None

    second_chain = persist_authorised_chain(run_id="recovered")
    second = run_proving(
        store_path=store,
        run_id="recovered",
        fetched_at="2026-08-18T12:05:00.000000Z",
        kill_switch=False,
        no_emergency_stop=True,
        fetch=_fetch_ok,
        run_authority=second_chain.resolver,
        **_rights_inventories(),
    )
    second_health = {item.source_id: item for item in second.source_health}
    assert second_health["UK-01"].status is SourceHealthStatus.ACTIVE
    assert second_health["UK-01"].recovered_at == "2026-08-18T12:05:00.000000Z"
    assert second_health["UK-01"].next_retry_at is None


def test_global_gate_failure_blocks_all_sources(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id="global-block")
    fetched: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        fetched.append(url)
        return _fetch_ok(url)

    report = run_proving(
        store_path=store,
        run_id="global-block",
        fetched_at=FIXTURE_NOW,
        kill_switch=True,
        no_emergency_stop=True,
        fetch=fetch,
        run_authority=chain.resolver,
        **_rights_inventories(),
    )

    assert fetched == []
    assert report.observations == ()
    assert not report.authorised
    assert "RIGHTS_UK-01" not in GLOBAL_PROVING_GATES
    assert "KILL_SWITCH_READY" in GLOBAL_PROVING_GATES
    assert len(report.source_health) == 10
    assert all(
        item.status is SourceHealthStatus.BLOCKED for item in report.source_health
    )
    assert all(
        "KILL_SWITCH_READY" in (item.reason or "") for item in report.source_health
    )


def test_source_health_survives_store_reopen(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id="durable-health")
    rights = _rights_inventories()
    rights["rights_uk_10"] = rights_inventory(
        gate=UK_10_GATE_ID,
        expires_at="2026-08-18T12:00:00.000000Z",
    )
    report = run_proving(
        store_path=store,
        run_id="durable-health",
        fetched_at=FIXTURE_NOW,
        kill_switch=False,
        no_emergency_stop=True,
        fetch=_fetch_ok,
        run_authority=chain.resolver,
        **rights,
    )
    retained = list_source_health(store)
    assert {item.source_id: item.status for item in retained} == {
        item.source_id: item.status for item in report.source_health
    }
    by_id = {item.source_id: item for item in retained}
    assert by_id["UK-10"].status is SourceHealthStatus.HELD
    assert sum(
        item.status is SourceHealthStatus.ACTIVE for item in retained
    ) == 9
    connection = sqlite3.connect(store)
    rows = connection.execute(
        "SELECT source_id, status FROM proving_source_health WHERE run_id=?",
        ("durable-health",),
    ).fetchall()
    connection.close()
    assert len(rows) == 10
    assert ("UK-10", "HELD") in rows


def test_duplicate_run_id_does_not_replace_failed_gates(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    first = run_proving(
        store_path=store,
        run_id="r1",
        fetched_at="2026-08-16T20:00:00.000000Z",
        kill_switch=True,
        no_emergency_stop=True,
        fetch=_fetch_ok,
    )
    assert not first.authorised
    chain = persist_authorised_chain(run_id="r1")
    with pytest.raises(ProvingError, match="already retained"):
        run_proving(
            store_path=store,
            run_id="r1",
            fetched_at="2026-08-16T20:01:00.000000Z",
            kill_switch=False,
            no_emergency_stop=True,
            fetch=_fetch_ok,
            run_authority=chain.resolver,
            **_rights_inventories(),
        )
    connection = __import__("sqlite3").connect(store)
    kill = connection.execute(
        "SELECT status FROM proving_gates "
        "WHERE run_id='r1' AND gate_id='KILL_SWITCH_READY'"
    ).fetchone()
    connection.close()
    assert kill == ("FAIL",)


def test_writer_lock_after_connect_is_normalised_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = str(tmp_path / "post-connect-lock.sqlite3")
    original_connect = proving_module._connect
    blockers: list[sqlite3.Connection] = []
    monkeypatch.setattr(proving_module, "PROVING_WRITE_TIMEOUT_SECONDS", 0.01)

    def connect_then_lock(path: str) -> sqlite3.Connection:
        connection = original_connect(path)
        blocker = sqlite3.connect(path)
        blocker.execute("BEGIN IMMEDIATE")
        blockers.append(blocker)
        return connection

    monkeypatch.setattr(proving_module, "_connect", connect_then_lock)
    try:
        with pytest.raises(ProvingError, match="writer lock timed out"):
            run_proving(
                store_path=store,
                run_id="locked-run",
                fetched_at="2026-08-21T00:00:00.000000Z",
                kill_switch=True,
                no_emergency_stop=True,
            )
    finally:
        for blocker in blockers:
            blocker.rollback()
            blocker.close()


def test_proving_cli_default_writes_the_shared_canonical_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.increment9_proving_store as proving_cli

    observed: list[str] = []

    def capture_list(store_path: str) -> tuple[Observation, ...]:
        observed.append(store_path)
        return ()

    monkeypatch.setattr(proving_cli, "list_observations", capture_list)
    assert proving_cli.main(["list"]) == 0
    assert observed == [proving_cli.DEFAULT_PROVING_STORE]


def test_proving_cli_fetch_retains_complete_renewable_rights_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.increment9_proving_store as proving_cli

    store = tmp_path / "proving.sqlite3"
    monkeypatch.delenv("NEWSROOM_PROVING_KILL", raising=False)
    monkeypatch.setattr(proving_cli, "ensure_control_plane_state_root", lambda: None)
    monkeypatch.setattr(proving_module, "default_fetch", _fetch_ok)

    assert proving_cli.main(
        [
            "fetch",
            "--store",
            str(store),
            "--run-id",
            "standalone-fetch",
            "--attest-no-emergency-stop",
        ]
    ) == 0

    connection = sqlite3.connect(store)
    packet_count = connection.execute(
        "SELECT COUNT(*) FROM proving_rights_packets WHERE run_id='standalone-fetch'"
    ).fetchone()
    connection.close()
    assert packet_count == (10,)


def test_production_and_news_pool_paths_are_rejected(tmp_path: Path):
    chain = persist_authorised_chain(run_id="r1")
    with pytest.raises(ProvingError, match="news_pool"):
        run_proving(
            store_path=str(tmp_path / "news_pool.sqlite3"),
            run_id="r1",
            fetched_at="2026-08-16T20:00:00.000000Z",
            kill_switch=False,
            no_emergency_stop=True,
            fetch=_fetch_ok,
            run_authority=chain.resolver,
            **_rights_inventories(),
        )


@pytest.mark.parametrize(
    ("url", "body", "expected_error"),
    [
        (SOURCE_URLS["UK-02"], b"", "content-empty"),
        (SOURCE_URLS["UK-02"], b"{not-json", "content-malformed-json"),
        (
            SOURCE_URLS["UK-02"],
            b'{"error":"rate limited"}',
            "content-malformed-json",
        ),
        (
            SOURCE_URLS["UK-02"],
            b'{"error":{"code":"rate_limit"}}',
            "content-malformed-json",
        ),
        (
            SOURCE_URLS["UK-02"],
            b'{"errors":[{"code":"rate_limit"}]}',
            "content-malformed-json",
        ),
        (
            SOURCE_URLS["UK-02"],
            b'{"status":"error","code":"rate_limit"}',
            "content-malformed-json",
        ),
        (SOURCE_URLS["UK-02"], b"[1,2]", "content-malformed-json"),
        (
            SOURCE_URLS["UK-02"],
            b'[{"title":"One"},{}]',
            "content-malformed-json",
        ),
        (
            SOURCE_URLS["HK-02"],
            b'{"good":{"code":"TC1"},"bad":{}}',
            "content-malformed-json",
        ),
        (SOURCE_URLS["UK-02"], b'{"title":"<br>"}', "content-malformed-json"),
        (SOURCE_URLS["UK-01"], b"<rss><channel>", "content-malformed-xml"),
        (
            SOURCE_URLS["UK-01"],
            b'<?xml version="1.0" encoding="x-unknown"?><rss/>',
            "content-malformed-xml",
        ),
        (
            SOURCE_URLS["UK-01"],
            b"<rss><channel><item/></channel></rss>",
            "content-malformed-xml",
        ),
        (
            SOURCE_URLS["UK-01"],
            b"<rss><channel><item><title>&lt;br&gt;</title></item></channel></rss>",
            "content-malformed-xml",
        ),
        (
            SOURCE_URLS["UK-01"],
            (
                "<rss><channel><item>"
                + "&lt;br&gt;" * 60
                + "Useful headline</item></channel></rss>"
            ).encode(),
            "content-malformed-xml",
        ),
        (
            SOURCE_URLS["UK-01"],
            b"<rss><channel><item><title>One</title></item><item/></channel></rss>",
            "content-malformed-xml",
        ),
        (
            SOURCE_URLS["UK-01"],
            b"<html><body>blocked</body></html>",
            "content-unexpected-root:html",
        ),
    ],
)
def test_assess_content_rejects_unusable_payloads(
    url: str, body: bytes, expected_error: str
) -> None:
    assessment = assess_content(url, body)
    assert not assessment.usable
    assert assessment.item_count == 0
    assert assessment.error == expected_error


@pytest.mark.parametrize(
    ("url", "body", "expected_count"),
    [
        (SOURCE_URLS["UK-02"], b"{}", 0),
        (SOURCE_URLS["UK-02"], b"[]", 0),
        (SOURCE_URLS["UK-02"], b'[{"title":"One"}]', 1),
        (SOURCE_URLS["HK-02"], b'{"warning":{"code":"TC1"}}', 1),
        (
            SOURCE_URLS["UK-01"],
            b"<rss><channel><item><description>Fallback headline</description></item></channel></rss>",
            1,
        ),
        (
            SOURCE_URLS["UK-01"],
            b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>',
            0,
        ),
        (
            SOURCE_URLS["UK-01"],
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
            0,
        ),
    ],
)
def test_assess_content_accepts_valid_structured_payloads(
    url: str, body: bytes, expected_count: int
) -> None:
    assessment = assess_content(url, body)
    assert assessment.usable
    assert assessment.item_count == expected_count
    assert assessment.error is None


def test_assess_content_honours_declared_xml_encoding() -> None:
    body = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        '<rss version="2.0"><channel><item><title>Caf\u00e9</title></item></channel></rss>'
    ).encode("iso-8859-1")

    assessment = assess_content(SOURCE_URLS["UK-01"], body)

    assert assessment.usable
    assert assessment.item_count == 1
    assert assessment.error is None


@pytest.mark.parametrize(
    ("source_id", "bad_body"),
    [
        ("UK-02", b""),
        ("UK-02", b"{bad"),
        ("UK-01", b"<rss><open"),
        ("UK-01", b"<html><body>error</body></html>"),
    ],
)
def test_unusable_content_degrades_after_three_attempts_without_global_block(
    tmp_path: Path, source_id: str, bad_body: bytes
) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id=f"bad-{source_id}")
    target_url = SOURCE_URLS[source_id]
    attempts: dict[str, int] = {}
    delays: list[float] = []

    def fetch(url: str) -> tuple[int, bytes]:
        attempts[url] = attempts.get(url, 0) + 1
        if url == target_url:
            return 200, bad_body
        return _fetch_ok(url)

    report = run_proving(
        store_path=store,
        run_id=f"bad-{source_id}",
        fetched_at=FIXTURE_NOW,
        kill_switch=False,
        no_emergency_stop=True,
        fetch=fetch,
        run_authority=chain.resolver,
        retry_sleep=delays.append,
        **_rights_inventories(),
    )

    health = {item.source_id: item for item in report.source_health}
    observation = next(item for item in report.observations if item.source_id == source_id)
    assert attempts[target_url] == FETCH_MAX_ATTEMPTS
    assert delays == list(FETCH_RETRY_DELAYS_SECONDS)
    assert observation.status_code == 200
    assert observation.error is not None
    assert observation.item_count == 0
    assert health[source_id].status is SourceHealthStatus.DEGRADED
    assert health[source_id].attempts == FETCH_MAX_ATTEMPTS
    assert health[source_id].reason == observation.error
    assert not report.complete
    assert sum(
        item.status is SourceHealthStatus.ACTIVE for item in report.source_health
    ) == len(SOURCE_IDS) - 1


def test_unusable_content_recovers_on_third_attempt(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id="recover-content")
    target_url = SOURCE_URLS["UK-02"]
    attempts: dict[str, int] = {}

    def fetch(url: str) -> tuple[int, bytes]:
        attempts[url] = attempts.get(url, 0) + 1
        if url == target_url and attempts[url] < 3:
            return 200, b"{bad"
        return _fetch_ok(url)

    report = run_proving(
        store_path=store,
        run_id="recover-content",
        fetched_at=FIXTURE_NOW,
        kill_switch=False,
        no_emergency_stop=True,
        fetch=fetch,
        run_authority=chain.resolver,
        retry_sleep=lambda _seconds: None,
        **_rights_inventories(),
    )

    health = {item.source_id: item for item in report.source_health}
    observation = next(item for item in report.observations if item.source_id == "UK-02")
    assert attempts[target_url] == 3
    assert observation.status_code == 200
    assert observation.error is None
    assert observation.item_count == 1
    assert health["UK-02"].status is SourceHealthStatus.ACTIVE
    assert health["UK-02"].attempts == 3
    assert report.complete


def test_valid_empty_structured_payloads_complete_proving(tmp_path: Path) -> None:
    store = str(tmp_path / "proving.sqlite3")
    chain = persist_authorised_chain(run_id="empty-structured")

    def fetch(url: str) -> tuple[int, bytes]:
        if url == SOURCE_URLS["UK-02"]:
            return 200, b"{}"
        if url == SOURCE_URLS["UK-01"]:
            return (
                200,
                b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>',
            )
        return _fetch_ok(url)

    report = run_proving(
        store_path=store,
        run_id="empty-structured",
        fetched_at=FIXTURE_NOW,
        kill_switch=False,
        no_emergency_stop=True,
        fetch=fetch,
        run_authority=chain.resolver,
        **_rights_inventories(),
    )

    by_id = {item.source_id: item for item in report.observations}
    assert by_id["UK-02"].error is None
    assert by_id["UK-02"].item_count == 0
    assert by_id["UK-01"].error is None
    assert by_id["UK-01"].item_count == 0
    assert report.complete
    assert all(
        item.status is SourceHealthStatus.ACTIVE for item in report.source_health
    )
