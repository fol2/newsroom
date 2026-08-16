from pathlib import Path
import pytest
from newsroom.increment9.proving import (
    ALLOWED_HOSTS,
    PORTFOLIO,
    SOURCE_IDS,
    ProvingError,
    assess,
    assert_allowed_url,
    assert_allowed_redirect,
    list_observations,
    report_json,
    run_proving,
)


def _fetch_ok(url: str) -> tuple[int, bytes]:
    if "/api/" in url or "opendata" in url:
        return 200, b'{"id":"x","updated":"1"}'
    return 200, b"<feed><entry><title>a</title></entry></feed>"


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
    assert {g.gate_id: g.status.value for g in blocked}["NO_ACTIVE_HUMAN_EMERGENCY_STOP"] == "FAIL"
    killed = assess(run_id="r1", kill_switch=True, no_emergency_stop=True)
    assert {g.gate_id: g.status.value for g in killed}["KILL_SWITCH_READY"] == "FAIL"
    ok = assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    assert all(g.status.value == "PASS" for g in ok)


def test_fetch_is_blocked_until_gates_pass(tmp_path: Path):
    store = str(tmp_path / "proving.sqlite3")
    blocked = run_proving(
        store_path=store,
        run_id="r1",
        fetched_at="2026-08-16T20:00:00.000000Z",
        kill_switch=False,
        no_emergency_stop=False,
        fetch=_fetch_ok,
    )
    assert not blocked.authorised and blocked.observations == ()
    assert list_observations(store) == ()


def test_fetch_stores_ten_observations_without_publication(tmp_path: Path):
    store = str(tmp_path / "proving.sqlite3")
    report = run_proving(
        store_path=store,
        run_id="r1",
        fetched_at="2026-08-16T20:00:00.000000Z",
        kill_switch=False,
        no_emergency_stop=True,
        fetch=_fetch_ok,
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
    payload = report_json(report)
    assert b'"publication":false' in payload
    assert b"openrouter" in payload


def test_production_and_news_pool_paths_are_rejected(tmp_path: Path):
    with pytest.raises(ProvingError, match="news_pool"):
        run_proving(
            store_path=str(tmp_path / "news_pool.sqlite3"),
            run_id="r1",
            fetched_at="2026-08-16T20:00:00.000000Z",
            kill_switch=False,
            no_emergency_stop=True,
            fetch=_fetch_ok,
        )
