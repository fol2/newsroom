"""Exact source identity reconstruction without repeated full-body hashing."""

from dataclasses import asdict, replace

import pytest

from newsroom.control_plane import corpus
from newsroom.tests.test_graphiti_operational_readiness import _unit


def _original_identity(unit):
    # Original public-property composition is the independent compatibility oracle.
    return corpus.ingest_key(
        source_id=unit.source_id, item_key=unit.item_key,
        content_digest_value=unit.revision_digest, revision_id=unit.revision_id,
        representation_digest=unit.representation_digest,
        published_at=unit.published_at, updated_at=unit.updated_at,
        chunk_ordinal=unit.chunk_ordinal,
    )


@pytest.mark.parametrize("with_authority", (True, False))
def test_ingest_identity_hashes_current_content_once_per_independent_read(monkeypatch, with_authority):
    unit = _unit()
    if not with_authority:
        unit = replace(unit, authority=None)
    expected, wire = _original_identity(unit), asdict(unit)
    calls = []
    original = corpus.content_digest

    def counted(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(corpus, "content_digest", counted)
    assert unit.ingest_id == expected
    assert len(calls) == 1
    assert unit.ingest_id == expected
    assert len(calls) == 2  # No cross-read memo or fields added to retained asdict.
    assert asdict(unit) == wire


@pytest.mark.parametrize("with_authority", (True, False))
@pytest.mark.parametrize("field,value", [
    ("source_id", "UK-05"), ("item_key", "different-item"),
    ("headline", "Current headlinE"),
    ("body", "current body with exact retained bytes."),
    ("canonical_url", "https://example.test/current-iteM"),
    ("published_at", "2026-09-03T10:00:00.000000Z"),
    ("updated_at", "2026-09-04T10:00:00.000000Z"), ("chunk_ordinal", 2),
])
def test_ingest_identity_preserves_exact_recipe_and_input_sensitivity(with_authority, field, value):
    unit = _unit()
    if not with_authority:
        unit = replace(unit, authority=None)
    changed = replace(unit, **{field: value})
    assert changed.ingest_id == _original_identity(changed)
    assert changed.ingest_id != unit.ingest_id


@pytest.mark.parametrize("with_authority", (True, False))
@pytest.mark.parametrize("field,value", [
    ("body", "invalid\ud800"), ("headline", "invalid\udfff"),
    ("canonical_url", "invalid\ud800"), ("source_id", "invalid\ud800"),
    ("published_at", "invalid\ud800"), ("chunk_ordinal", float("nan")),
    ("body", object()),
])
def test_ingest_identity_preserves_invalid_input_error(with_authority, field, value):
    unit = _unit()
    if not with_authority:
        unit = replace(unit, authority=None)
    unit = replace(unit, **{field: value})
    with pytest.raises(ValueError) as previous:
        _original_identity(unit)
    with pytest.raises(type(previous.value)) as current:
        _ = unit.ingest_id
    assert str(current.value) == str(previous.value)


def test_ingest_identity_reads_current_authority_without_caching_its_records():
    unit = _unit()
    original = unit.ingest_id
    # Authority records are mutable; identity does not replace their downstream
    # validation, cache them, or add private fields to the retained wire shape.
    unit.authority.records[0]["diagnostic"] = "changed"
    assert unit.ingest_id == original == _original_identity(unit)
    changed_authority = replace(unit.authority, revision_id="00000000-0000-4000-8000-000000000123")
    object.__setattr__(unit, "authority", changed_authority)
    assert unit.revision_id == changed_authority.revision_id
    assert unit.ingest_id == _original_identity(unit) != original
    original = unit.ingest_id
    object.__setattr__(unit, "body", unit.body.replace("Current", "current"))
    assert unit.ingest_id == _original_identity(unit) != original


def test_authority_free_identity_preserves_invalid_rights_identity_rejection():
    unit = replace(_unit(), authority=None, proving_run_id="invalid\ud800")
    with pytest.raises(ValueError) as previous:
        _original_identity(unit)
    with pytest.raises(type(previous.value)) as current:
        _ = unit.ingest_id
    assert str(current.value) == str(previous.value)
