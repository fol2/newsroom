from __future__ import annotations

from dataclasses import replace

import pytest

from newsroom.sources import (
    DiscoveryOccurrenceKind,
    SourceDefinitionVersionId,
    SourceSemanticCollision,
    SourceVersionConflict,
)

from .source_3a_helpers import (
    CHECK_2_ID,
    DEFINITION_ID,
    OCCURRENCE_2_ID,
    REPRESENTATION_2_ID,
    REVISION_1_ID,
    VERSION_1_ID,
    VERSION_2_ID,
    definition_request,
    item_request,
    locator_decision_request,
    occurrence_request,
    open_source_system,
    proof,
    representation_request,
    revision_request,
    scopes,
    version_request,
)


def _seed_source(system):
    definition = system.sources.register_definition(
        definition_request(), proof=proof()
    )
    version_1 = system.sources.record_definition_version(
        version_request(), proof=proof()
    )
    item = system.sources.register_item(item_request(), proof=proof())
    version_2 = system.sources.record_definition_version(
        version_request(
            version_id=VERSION_2_ID,
            version_number=2,
            previous_version_id=VERSION_1_ID,
            locator="fixture://increment-3a/maintained-guidance-v2",
            key="source-definition-version-v2",
        ),
        proof=proof(),
    )
    decision = system.sources.decide_locator_continuity(
        locator_decision_request(), proof=proof()
    )
    return definition, version_1, item, version_2, decision


def test_source_registry_commits_replays_and_reopens_exact_lineage(
    tmp_path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_source_system(database)
    definition, version_1, item, version_2, decision = _seed_source(system)

    replay = system.sources.register_definition(
        definition_request(), proof=proof()
    )
    assert replay.replayed is True
    assert replay.event_id == definition.event_id

    revision = system.sources.record_revision(
        revision_request(), proof=proof()
    )
    representation = system.sources.record_representation(
        representation_request(), proof=proof()
    )
    occurrence_1 = system.sources.record_occurrence(
        occurrence_request(), proof=proof()
    )
    representation_2 = system.sources.record_representation(
        representation_request(
            representation_id=REPRESENTATION_2_ID,
            parser_version="fixture-parser-v2",
            digest_character="c",
            key="source-representation-v2",
        ),
        proof=proof(),
    )
    occurrence_2 = system.sources.record_occurrence(
        occurrence_request(
            occurrence_id=OCCURRENCE_2_ID,
            check_outcome_id=CHECK_2_ID,
            representation_id=REPRESENTATION_2_ID,
            kind=DiscoveryOccurrenceKind.REOBSERVED,
            key="source-occurrence-v2",
        ),
        proof=proof(),
    )

    summary = system.sources.current_summary(DEFINITION_ID, proof=proof())
    assert summary.version_id == VERSION_2_ID
    assert summary.version_number == 2
    assert not hasattr(summary, "locator")
    details = system.sources.version_details(VERSION_2_ID, proof=proof())
    assert details.request.locator.endswith("maintained-guidance-v2")
    assert decision.request.related_item_id == item.request.item_id
    assert representation.request.revision_id == revision.request.revision_id
    assert representation_2.request.parser_version == "fixture-parser-v2"
    assert occurrence_1.request.revision_id == REVISION_1_ID
    assert occurrence_2.request.kind is DiscoveryOccurrenceKind.REOBSERVED
    assert len(
        system.sources.occurrences(
            REVISION_1_ID, limit=10, proof=proof()
        )
    ) == 2
    system.close()

    reopened = open_source_system(database)
    assert reopened.sources.definition(DEFINITION_ID, proof=proof()).event_id == (
        definition.event_id
    )
    assert reopened.sources.current_summary(
        DEFINITION_ID, proof=proof()
    ).version_id == VERSION_2_ID
    assert len(
        reopened.sources.occurrences(
            REVISION_1_ID, limit=10, proof=proof()
        )
    ) == 2
    reopened.close()


def test_sensitive_version_read_requires_distinct_scope(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_source_system(database)
    _seed_source(system)
    system.close()

    metadata_only = scopes() - frozenset(
        {"authority.sources.read_sensitive"}
    )
    restricted = open_source_system(
        database, granted_scopes=metadata_only
    )
    assert restricted.sources.current_summary(
        DEFINITION_ID, proof=proof()
    ).version_id == VERSION_2_ID
    with pytest.raises(PermissionError):
        restricted.sources.version_details(VERSION_2_ID, proof=proof())
    with pytest.raises(PermissionError):
        restricted.sources.version_details(
            SourceDefinitionVersionId.new(), proof=proof()
        )
    restricted.close()


def test_stale_source_version_and_duplicate_revision_fail_closed(
    tmp_path,
) -> None:
    system = open_source_system(tmp_path / "authority.sqlite3")
    _seed_source(system)

    stale = version_request(
        version_id=SourceDefinitionVersionId.new(),
        version_number=2,
        previous_version_id=VERSION_1_ID,
        locator="fixture://increment-3a/stale",
        key="stale-source-version",
    )
    with pytest.raises(SourceVersionConflict):
        system.sources.record_definition_version(stale, proof=proof())

    first = revision_request()
    system.sources.record_revision(first, proof=proof())
    duplicate_state = replace(
        first,
        revision_id=first.revision_id.new(),
        idempotency_key="duplicate-source-state",
    )
    with pytest.raises(SourceSemanticCollision):
        system.sources.record_revision(duplicate_state, proof=proof())
    system.close()


def test_one_parser_slot_cannot_emit_conflicting_representation(
    tmp_path,
) -> None:
    system = open_source_system(tmp_path / "authority.sqlite3")
    _seed_source(system)
    system.sources.record_revision(revision_request(), proof=proof())
    first = representation_request()
    system.sources.record_representation(first, proof=proof())
    conflicting = replace(
        first,
        representation_id=REPRESENTATION_2_ID,
        representation_digest="sha256:" + "f" * 64,
        idempotency_key="conflicting-parser-slot",
    )
    with pytest.raises(SourceSemanticCollision):
        system.sources.record_representation(conflicting, proof=proof())
    system.close()
