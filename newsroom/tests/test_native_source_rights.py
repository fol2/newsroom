import json
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from newsroom.authority import HydrationRequest, ObjectAdmissionId
from newsroom.authority.canonical import digest_bytes
from newsroom.control_plane import native_source_rights as rights
from newsroom.control_plane import cycle
from newsroom.control_plane.native_runtime import open_native_runtime
from newsroom.control_plane.veto import VetoError
from newsroom.increment9.proving import SOURCE_URLS
from newsroom.tests.test_native_runtime import _args
from newsroom.tests.test_native_source_intake import _licence


def test_observed_rights_retain_real_terms_and_keep_source_local_holds(tmp_path, monkeypatch):
    bodies = {}
    terms = {}
    for source, entries in rights.TERMS.items():
        terms[source] = []
        for index, (url, _digest) in enumerate(entries):
            text = f"Reviewed test terms for {source} {index}"
            raw = (f'<div class="inner_page_content_container">{text}</div>' if source == "HK-04"
                   else f"<main>{text}</main>").encode()
            bodies[url] = raw
            terms[source].append((url, rights.terms_text_digest(source, raw)))
        terms[source] = tuple(terms[source])
    monkeypatch.setattr(rights, "TERMS", terms)
    calls = []
    def fetch(url):
        calls.append(url)
        return bodies[url]
    with open_native_runtime(**_args(tmp_path, monkeypatch)) as runtime:
        evidence = rights.observe_portfolio_terms(
            objects=runtime.authority.objects, proof=runtime.proof,
            stop_check=lambda: None, stop_fence=nullcontext, fetch=fetch,
            clock=lambda: datetime(2026, 9, 8, 15, tzinfo=UTC),
        )
        portfolio = rights.NativePortfolioRights(_licence(), evidence)
        assert len(calls) == 7 and set(evidence) == set(rights.TERMS)
        for source, entry in evidence.items():
            expected = "HOLD" if source in rights.RESTRICTIONS else "PERMITTED"
            assert portfolio.for_source(source_id=source, definition_url=SOURCE_URLS[source]).decision == expected
            for url, digest, admission, _access in entry.observations:
                retained = runtime.authority.objects.hydrate(
                    HydrationRequest(ObjectAdmissionId.parse(admission), "evidence.source"), proof=runtime.proof,
                )
                assert retained.data == bodies[url] and digest_bytes(retained.data) == digest
        assert portfolio.for_source(source_id="HK-02", definition_url=SOURCE_URLS["RAD-02"]).decision == "HOLD"
        with pytest.raises(ValueError, match="incomplete"):
            replace(evidence["HK-02"], observations=())
        with pytest.raises(ValueError, match="restriction"):
            replace(evidence["RAD-02"], reason="REVIEWED_REUSE_PERMITTED")
        hk02_url = rights.TERMS["HK-02"][0][0]
        bodies[hk02_url] = b"<main>Changed HK Observatory terms</main>"
        changed = rights.observe_portfolio_terms(
            objects=runtime.authority.objects, proof=runtime.proof,
            stop_check=lambda: None, stop_fence=nullcontext, fetch=fetch,
            clock=lambda: datetime(2026, 9, 8, 15, 5, tzinfo=UTC),
        )
        refreshed = rights.NativePortfolioRights(_licence(), changed)
        assert changed["HK-02"].reason == "SOURCE_TERMS_CHANGED"
        assert refreshed.for_source(
            source_id="HK-02", definition_url=SOURCE_URLS["HK-02"],
        ).decision == "HOLD"
        assert refreshed.for_source(
            source_id="UK-10", definition_url=SOURCE_URLS["UK-10"],
        ).decision == "PERMITTED"
        assessment = refreshed.for_source(
            source_id="HK-02", definition_url=SOURCE_URLS["HK-02"],
        )
        snapshot = rights.retain_rights_snapshot(
            objects=runtime.authority.objects, proof=runtime.proof,
            source_id="HK-02", definition_url=SOURCE_URLS["HK-02"],
            assessment=assessment, observed_at=changed["HK-02"].observed_at,
            reason=changed["HK-02"].reason,
            observations=changed["HK-02"].observations,
        )
        for admission, digest in (
            (snapshot.assessment_admission_id, snapshot.assessment_blob_digest),
            (snapshot.observation_admission_id, snapshot.observation_blob_digest),
        ):
            retained = runtime.authority.objects.hydrate(
                HydrationRequest(ObjectAdmissionId.parse(admission), "evidence.source"),
                proof=runtime.proof,
            )
            assert digest_bytes(retained.data) == digest
        later = rights.retain_rights_snapshot(
            objects=runtime.authority.objects, proof=runtime.proof,
            source_id="HK-02", definition_url=SOURCE_URLS["HK-02"],
            assessment=assessment, observed_at="2026-09-08T15:10:00+00:00",
            reason=changed["HK-02"].reason,
            observations=changed["HK-02"].observations,
        )
        assert later.assessment_admission_id == snapshot.assessment_admission_id
        assert later.assessment_blob_digest == snapshot.assessment_blob_digest
        assert later.observation_admission_id != snapshot.observation_admission_id
        assert later.observation_blob_digest != snapshot.observation_blob_digest
        observation = runtime.authority.objects.hydrate(
            HydrationRequest(
                ObjectAdmissionId.parse(later.observation_admission_id),
                "evidence.source",
            ), proof=runtime.proof,
        )
        assert json.loads(observation.data)["observed_at"] == (
            "2026-09-08T15:10:00+00:00"
        )


def test_terms_stop_and_unavailable_do_not_create_a_permission(tmp_path, monkeypatch):
    with open_native_runtime(**_args(tmp_path, monkeypatch)) as runtime:
        def fail(_url): raise OSError("test transport unavailable")
        evidence = rights.observe_portfolio_terms(objects=runtime.authority.objects, proof=runtime.proof,
                                                  stop_check=lambda: None, stop_fence=nullcontext, fetch=fail)
        portfolio = rights.NativePortfolioRights(_licence(), evidence)
        assert all(value.reason == "SOURCE_TERMS_UNAVAILABLE" for value in evidence.values())
        assert all(portfolio.for_source(source_id=source, definition_url=SOURCE_URLS[source]).decision == "HOLD" for source in evidence)
        def stop(): raise VetoError("owner stop")
        with pytest.raises(VetoError):
            rights.observe_portfolio_terms(objects=runtime.authority.objects, proof=runtime.proof,
                                            stop_check=stop, stop_fence=nullcontext,
                                            fetch=lambda _: pytest.fail("fetch after stop"))


def test_parallel_terms_fetches_share_one_real_owner_stop_fence(
    tmp_path, monkeypatch,
):
    bodies = {}
    terms = {}
    for source_id in rights.TERMS:
        url = rights.TERMS[source_id][0][0]
        text = f"Concurrent terms for {source_id}"
        raw = (
            f'<div class="inner_page_content_container">{text}</div>'
            if source_id == "HK-04" else f"<main>{text}</main>"
        ).encode()
        bodies[url] = raw
        terms[source_id] = ((url, rights.terms_text_digest(source_id, raw)),)
    monkeypatch.setattr(rights, "TERMS", terms)
    monkeypatch.setattr(cycle, "_PROVING_FENCE_TIMEOUT_SECONDS", 0.05)

    proving = tmp_path / "proving.sqlite3"
    with sqlite3.connect(proving) as database:
        database.executescript(
            """
            CREATE TABLE proving_runs(run_id TEXT PRIMARY KEY);
            CREATE TABLE proving_gates(
                run_id TEXT NOT NULL, gate_id TEXT NOT NULL, status TEXT NOT NULL
            );
            INSERT INTO proving_runs VALUES('run-1');
            INSERT INTO proving_gates VALUES(
                'run-1', 'NO_ACTIVE_HUMAN_EMERGENCY_STOP', 'PASS'
            );
            """
        )

    fence_entries = 0

    @contextmanager
    def owner_stop_fence():
        nonlocal fence_entries
        fence_entries += 1
        with cycle.owner_emergency_stop_fence(str(proving)):
            yield

    all_fetches_entered = threading.Event()
    state_lock = threading.Lock()
    active = maximum_active = 0

    def fetch(url):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == len(terms):
                all_fetches_entered.set()
        try:
            assert all_fetches_entered.wait(0.5)
            return bodies[url]
        finally:
            with state_lock:
                active -= 1

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o700)
    with open_native_runtime(**_args(runtime_root, monkeypatch)) as runtime:
        evidence = rights.observe_portfolio_terms(
            objects=runtime.authority.objects, proof=runtime.proof,
            stop_check=lambda: None, stop_fence=owner_stop_fence, fetch=fetch,
            clock=lambda: datetime(2026, 9, 8, 15, tzinfo=UTC),
        )

    assert set(evidence) == set(terms)
    assert fence_entries == 1
    assert maximum_active == len(terms)


def test_owner_stop_fence_is_reentrant_only_on_the_holding_thread(
    tmp_path, monkeypatch,
):
    proving = tmp_path / "proving-fence.sqlite3"
    with sqlite3.connect(proving) as database:
        database.executescript(
            """
            CREATE TABLE proving_runs(run_id TEXT PRIMARY KEY);
            CREATE TABLE proving_gates(
                run_id TEXT NOT NULL, gate_id TEXT NOT NULL, status TEXT NOT NULL
            );
            INSERT INTO proving_runs VALUES('run-1');
            INSERT INTO proving_gates VALUES(
                'run-1', 'NO_ACTIVE_HUMAN_EMERGENCY_STOP', 'PASS'
            );
            """
        )
    monkeypatch.setattr(cycle, "_PROVING_FENCE_TIMEOUT_SECONDS", 0.05)
    writer_errors = []

    def activate_from_another_thread():
        try:
            with sqlite3.connect(proving, timeout=0.05) as database:
                database.execute(
                    "UPDATE proving_gates SET status='FAIL' "
                    "WHERE gate_id='NO_ACTIVE_HUMAN_EMERGENCY_STOP'"
                )
        except sqlite3.OperationalError as exc:
            writer_errors.append(exc)

    with pytest.raises(RuntimeError, match="unwind fence"):
        with cycle.owner_emergency_stop_fence(str(proving)):
            with cycle.owner_emergency_stop_fence(str(proving.resolve())):
                cycle.assert_no_owner_emergency_stop(str(proving))
            # A child inheriting thread-local state must acquire its own lock.
            parent_pid = cycle.os.getpid()
            with monkeypatch.context() as child:
                child.setattr(cycle.os, "getpid", lambda: parent_pid + 1)
                with pytest.raises(VetoError, match="authority is unavailable"):
                    with cycle.owner_emergency_stop_fence(str(proving)):
                        pytest.fail("another process reused the parent fence")
            writer = threading.Thread(target=activate_from_another_thread)
            writer.start()
            writer.join(timeout=0.5)
            assert not writer.is_alive()
            assert len(writer_errors) == 1
            raise RuntimeError("unwind fence")

    with sqlite3.connect(proving) as database:
        database.execute(
            "UPDATE proving_gates SET status='FAIL' "
            "WHERE gate_id='NO_ACTIVE_HUMAN_EMERGENCY_STOP'"
        )
    with pytest.raises(VetoError, match="owner emergency stop"):
        with cycle.owner_emergency_stop_fence(str(proving)):
            pytest.fail("active owner stop entered the protected effect")


def test_portfolio_refresh_replaces_permitted_snapshot_without_timestamp_churn():
    first = rights.SourceTermsEvidence(
        "HK-02", "2026-09-08T10:00:00+00:00", "REVIEWED_REUSE_PERMITTED",
        ((rights.TERMS["HK-02"][0][0], "sha256:" + "1" * 64,
          "00000000-0000-4000-8000-000000000001", "access-1"),),
    )
    same = replace(first, observed_at="2026-09-08T10:05:00+00:00")
    unavailable = {
        source: rights.SourceTermsEvidence(
            source, "2026-09-08T10:05:00+00:00", "SOURCE_TERMS_UNAVAILABLE", (),
        )
        for source in rights.TERMS
    }
    unavailable["HK-02"] = same
    refs = {
        source: rights.RightsSnapshotReference(
            f"00000000-0000-4000-8000-{index:012d}", "sha256:" + "2" * 64,
            f"00000000-0000-4000-8001-{index:012d}", "sha256:" + "3" * 64,
        )
        for index, source in enumerate(SOURCE_URLS, 1)
    }
    snapshots = iter(((None, "GOVUK_LICENCE_REVIEW_HOLD", unavailable, refs),))
    portfolio = rights.NativePortfolioRights(
        _licence(), {"HK-02": first}, refresh_current=lambda: next(snapshots),
    )
    initial = portfolio.for_source(
        source_id="HK-02", definition_url=SOURCE_URLS["HK-02"],
    )
    assert initial.decision == "PERMITTED"
    assert first.digest == same.digest
    govuk = _licence()
    assert govuk.for_source(
        source_id="UK-01", definition_url=SOURCE_URLS["UK-01"],
    ).record_id == replace(
        govuk, observed_at="2026-09-08T10:05:00.000000Z",
    ).for_source(
        source_id="UK-01", definition_url=SOURCE_URLS["UK-01"],
    ).record_id
    portfolio.refresh()
    assert portfolio.for_source(
        source_id="HK-02", definition_url=SOURCE_URLS["HK-02"],
    ).decision == "PERMITTED"
    assert portfolio.for_source(
        source_id="UK-01", definition_url=SOURCE_URLS["UK-01"],
    ).decision == "HOLD"
    assert portfolio.reason_for("HK-02") == "REVIEWED_REUSE_PERMITTED"
    assert portfolio.reason_for("UK-01") == "GOVUK_LICENCE_REVIEW_HOLD"
