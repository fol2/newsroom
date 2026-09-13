"""Exact-content scope validation reuse, not decision or store-state trust."""

from __future__ import annotations

import pytest

from newsroom.authority import AuthorityPersistenceError, canonical_json_bytes
from newsroom.authority.canonical import digest_bytes

from .authority_helpers import command, make_service, proof
from .test_authority_security_records import _stored_decision_row
from .test_authority_streamed_open import _store


@pytest.fixture
def store(tmp_path):
    with _store(tmp_path / "authority.sqlite3", make_service()) as value:
        yield value


def _scope(data):
    return {"canonical_bytes": data, "scope_content_digest": digest_bytes(data)}


def _decodes(store, monkeypatch):
    decoded = []
    original = store._decode_canonical

    def decode(data):
        decoded.append(data)
        return original(data)

    monkeypatch.setattr(store, "_decode_canonical", decode)
    return decoded


def test_exact_repeats_decode_once_and_return_independent_lists(store, monkeypatch):
    decoded = _decodes(store, monkeypatch)
    row = _scope(b'["authority.first","authority.second"]')
    first = store._scope_content_from_row(row)
    first.append("not retained")
    second = store._scope_content_from_row(row)
    second[0] = "also not retained"
    assert store._scope_content_from_row(row) == ["authority.first", "authority.second"]
    assert decoded == [row["canonical_bytes"]]
    assert all(type(value) is tuple for value in store._validated_scope_contents.values())


def test_repeated_decision_still_hashes_its_exact_bytes(store, monkeypatch):
    import newsroom.authority._event_store_read as reader

    decoded = _decodes(store, monkeypatch)
    row = _stored_decision_row()
    hashed = []
    original = reader.digest_bytes

    def digest(data):
        hashed.append(data)
        return original(data)

    monkeypatch.setattr(reader, "digest_bytes", digest)
    for _ in range(3):
        result = store._decision_record_from_row(row, selected_scope_bytes=row["scope_bytes"])
        assert result.canonical_bytes == row["canonical_bytes"]
        assert result.canonical_digest == row["canonical_digest"]
    assert decoded == [row["scope_bytes"]]
    assert hashed.count(row["scope_bytes"]) == 1
    assert hashed.count(row["canonical_bytes"]) == 3


@pytest.mark.parametrize("change", ["digest", "same_length_bytes", "redigested_bytes"])
def test_changed_content_or_claim_misses_and_keeps_decision_check(store, monkeypatch, change):
    decoded = _decodes(store, monkeypatch)
    row = _stored_decision_row()
    data = row["scope_bytes"]
    store._decision_record_from_row(row, selected_scope_bytes=data)
    if change == "digest":
        row["scope_content_digest"] = "sha256:" + "0" * 64
    else:
        data = data.replace(b"second", b"seconx")
        assert len(data) == len(row["scope_bytes"]) and data != row["scope_bytes"]
        if change == "redigested_bytes":
            row["scope_content_digest"] = digest_bytes(data)
    expected = "decision is not canonical" if change == "redigested_bytes" else "scopes digest differs"
    for _ in range(2):
        with pytest.raises(AuthorityPersistenceError, match=expected):
            store._decision_record_from_row(row, selected_scope_bytes=data)
    assert decoded == [row["scope_bytes"]] + ([data] if change == "redigested_bytes" else [])


@pytest.mark.parametrize(("data", "message"), [
    (b'[ "scope" ]', "JSON is not canonical"),
    (b'["\\u0073cope"]', "JSON is not canonical"),
    (b'{"scope":"value"}', "scopes are invalid"),
    (b'null', "scopes are invalid"),
    (b'[1]', "scopes are invalid"),
    (b'[true]', "scopes are invalid"),
    (b'not-json', "canonical JSON is invalid"),
])
def test_invalid_scope_content_is_never_cached(store, monkeypatch, data, message):
    decoded = _decodes(store, monkeypatch)
    row = _scope(data)
    for _ in range(2):
        with pytest.raises(AuthorityPersistenceError, match=message):
            store._scope_content_from_row(row)
    assert decoded == [data, data]


@pytest.mark.parametrize("size", [4096, 4097])
def test_only_small_scope_bytes_are_cached(store, monkeypatch, size):
    decoded = _decodes(store, monkeypatch)
    data = canonical_json_bytes(["x" * (size - 4)])
    assert len(data) == size
    for _ in range(2):
        assert store._scope_content_from_row(_scope(data)) == ["x" * (size - 4)]
    assert decoded == [data] * (1 if size == 4096 else 2)
    if size > 4096:
        assert not getattr(store, "_validated_scope_contents", {})


def test_cache_is_per_store_bounded_to_eight_and_evicts_oldest_use(store, monkeypatch, tmp_path):
    decoded = _decodes(store, monkeypatch)
    rows = [_scope(canonical_json_bytes([f"scope.{index}"])) for index in range(9)]
    for row in rows[:8]:
        store._scope_content_from_row(row)
    store._scope_content_from_row(rows[0])
    store._scope_content_from_row(rows[8])
    store._scope_content_from_row(rows[0])
    store._scope_content_from_row(rows[1])
    assert decoded == [row["canonical_bytes"] for row in rows] + [rows[1]["canonical_bytes"]]
    assert len(store._validated_scope_contents) == 8
    with _store(tmp_path / "separate.sqlite3", make_service()) as separate:
        separate_decodes = _decodes(separate, monkeypatch)
        separate._scope_content_from_row(rows[0])
        assert separate_decodes == [rows[0]["canonical_bytes"]]
        assert separate._validated_scope_contents is not store._validated_scope_contents


def test_warm_store_and_reopen_both_reject_changed_retained_scope(tmp_path):
    service = make_service()
    path = tmp_path / "tampered.sqlite3"
    with _store(path, service) as store:
        store.commit(service._authorize_for_commit(command(key="scope-warm"), proof=proof()))
        connection = store._connection
        row = connection.execute("SELECT * FROM authorization_scope_contents LIMIT 1").fetchone()
        store._scope_content_from_row(row)
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_authorization_scope_contents_update'"
        ).fetchone()[0]
        changed = bytes(row["canonical_bytes"]).replace(b"observed", b"observxd", 1)
        assert changed != row["canonical_bytes"] and len(changed) == len(row["canonical_bytes"])
        connection.execute("DROP TRIGGER immutable_authorization_scope_contents_update")
        connection.execute(
            "UPDATE authorization_scope_contents SET canonical_bytes=? WHERE scope_content_digest=?",
            (changed, row["scope_content_digest"]),
        )
        connection.execute(trigger)
        connection.commit()
        with pytest.raises(AuthorityPersistenceError, match="scopes digest differs"):
            store._validate_immutable_records(connection)
    with pytest.raises(AuthorityPersistenceError, match="scopes digest differs"):
        _store(path, service)


def test_empty_scope_list_is_a_cached_value_not_a_miss(store, monkeypatch):
    decoded = _decodes(store, monkeypatch)
    for _ in range(2):
        assert store._scope_content_from_row(_scope(b"[]")) == []
    assert decoded == [b"[]"]
