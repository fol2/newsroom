from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.control_plane.corpus import CorpusAuthorityBinding, CorpusIngestUnit
from newsroom.control_plane.cycle import _bind_graphiti_unit_authority
from newsroom.control_plane.graphiti_events import GraphitiRevisionEvent
from newsroom.effective_revision import EffectiveRevisionIdentity
from newsroom.graphiti_adapter.identity import content_digest


def _unit() -> CorpusIngestUnit:
    observed_at = "2026-09-01T00:00:00.000000Z"
    headline = "Headline"
    body = "Body"
    canonical_url = "https://example.test/item"
    identity = EffectiveRevisionIdentity(
        source_id="UK-01",
        item_key="item-1",
        revision_digest=content_digest(
            headline=headline,
            body=body,
            canonical_url=canonical_url,
        ),
        first_observed_at=observed_at,
    )
    source_records = (
        {"record_type": "SOURCE_DEFINITION", "record_id": "definition-1"},
        {
            "record_type": "SOURCE_DEFINITION_VERSION",
            "record_id": "definition-version-1",
        },
        {"record_type": "SOURCE_ITEM", "record_id": "item-authority-1"},
        {
            "record_type": "SOURCE_REVISION",
            "record_id": "revision-authority-1",
        },
        {
            "record_type": "DISCOVERY_REPRESENTATION",
            "record_id": "representation-1",
        },
    )
    authority = CorpusAuthorityBinding(
        admission_id="thin-admission",
        access_decision_id="thin-access",
        definition_id="definition-1",
        definition_version_id="definition-version-1",
        item_id="item-authority-1",
        revision_id="revision-authority-1",
        representation_id="representation-1",
        records=(
            *source_records,
            {"record_type": "OBJECT_ADMISSION", "record_id": "thin-admission"},
            {
                "record_type": "OBJECT_ACCESS_DECISION",
                "record_id": "thin-access",
            },
        ),
    )
    return CorpusIngestUnit(
        source_id=identity.source_id,
        item_key=identity.item_key,
        headline=headline,
        body=body,
        canonical_url=canonical_url,
        observation_digest="sha256:observation",
        observed_at=observed_at,
        proving_run_id="run-1",
        effective_revision=identity,
        authority=authority,
        source_definition_url="https://example.test/feed",
        effective_pull_first_observed_at=observed_at,
    )


def _event(unit: CorpusIngestUnit) -> GraphitiRevisionEvent:
    return GraphitiRevisionEvent(
        event_id="sha256:" + "a" * 64,
        ledger_seq=1,
        source_id=unit.source_id,
        item_key=unit.item_key,
        revision_digest=unit.revision_digest,
        published_at=unit.published_at or "",
        updated_at=unit.updated_at or "",
        expected_unit_count=1,
        landed_ingest_ids=(unit.ingest_id,),
        landed_payload_digest="sha256:" + "b" * 64,
        unit_refs=(
            {
                "ingest_id": unit.ingest_id,
                "revision_id": unit.revision_id,
                "representation_digest": unit.representation_digest,
                "chunk_digest": unit.digest,
                "chunk_ordinal": unit.chunk_ordinal,
                "predecessor_ingest_id": unit.predecessor_ingest_id,
            },
        ),
        state="RUNNING",
        attempt_count=1,
        units=(),
    )


def test_runtime_authority_binding_changes_only_object_decision_ids() -> None:
    unit = _unit()
    bound_authority = replace(
        unit.authority,
        admission_id="canonical-admission",
        access_decision_id="canonical-access",
        records=(
            *unit.authority.records[:5],
            {
                "record_type": "OBJECT_ADMISSION",
                "record_id": "canonical-admission",
            },
            {
                "record_type": "OBJECT_ACCESS_DECISION",
                "record_id": "canonical-access",
            },
        ),
    )

    result = _bind_graphiti_unit_authority(
        event=_event(unit),
        units=(unit,),
        resolver=lambda value: replace(value, authority=bound_authority),
    )

    assert result[0].authority == bound_authority
    assert result[0].ingest_id == unit.ingest_id
    assert result[0].revision_id == unit.revision_id


@pytest.mark.parametrize(
    ("resolver", "message"),
    [
        (
            lambda unit: replace(unit, item_key="different-item"),
            "changed dispatch identity",
        ),
        (
            lambda unit: replace(
                unit,
                authority=replace(unit.authority, definition_id="different-source"),
            ),
            "changed source identity",
        ),
        (
            lambda unit: replace(unit, authority=None),
            "canonical authority is incomplete",
        ),
        (
            lambda unit: replace(
                unit,
                authority=replace(
                    unit.authority,
                    records=(*unit.authority.records, unit.authority.records[-1]),
                ),
            ),
            "canonical authority is incomplete",
        ),
    ],
)
def test_runtime_authority_binding_fails_closed_on_drift(
    resolver: object,
    message: str,
) -> None:
    unit = _unit()

    with pytest.raises((TypeError, ValueError), match=message):
        _bind_graphiti_unit_authority(
            event=_event(unit),
            units=(unit,),
            resolver=resolver,  # type: ignore[arg-type]
        )
