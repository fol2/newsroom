from datetime import UTC, datetime
from dataclasses import replace

import pytest

from newsroom.authority import HydrationRequest, ObjectAdmissionId
from newsroom.authority.canonical import digest_bytes
from newsroom.control_plane import native_source_rights as rights
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
            stop_check=lambda: None, fetch=fetch,
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


def test_terms_stop_and_unavailable_do_not_create_a_permission(tmp_path, monkeypatch):
    with open_native_runtime(**_args(tmp_path, monkeypatch)) as runtime:
        def fail(_url): raise OSError("test transport unavailable")
        evidence = rights.observe_portfolio_terms(objects=runtime.authority.objects, proof=runtime.proof,
                                                  stop_check=lambda: None, fetch=fail)
        portfolio = rights.NativePortfolioRights(_licence(), evidence)
        assert all(value.reason == "SOURCE_TERMS_UNAVAILABLE" for value in evidence.values())
        assert all(portfolio.for_source(source_id=source, definition_url=SOURCE_URLS[source]).decision == "HOLD" for source in evidence)
        def stop(): raise VetoError("owner stop")
        with pytest.raises(VetoError):
            rights.observe_portfolio_terms(objects=runtime.authority.objects, proof=runtime.proof,
                                            stop_check=stop, fetch=lambda _: pytest.fail("fetch after stop"))
