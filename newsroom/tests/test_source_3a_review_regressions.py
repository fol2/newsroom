from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import TimePrecision
from newsroom.sources import (
    CoverageContribution,
    PortfolioFunction,
    SourceContractError,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceItemIdentityKind,
    SourceItemRequest,
    SourceRevisionId,
    SourceSemanticCollision,
    SourceTime,
    VersionedPolicyRef,
)

from .source_3a_helpers import (
    DEFINITION_ID,
    ITEM_ID,
    REVISION_1_ID,
    REVISION_2_ID,
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


def _seed_lineage(database):
    system = open_source_system(database)
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())
    system.sources.register_item(item_request(), proof=proof())
    system.sources.record_definition_version(
        version_request(
  version_id=VERSION_2_ID,
  version_number=2,
  previous_version_id=VERSION_1_ID,
  locator="fixture://increment-3a/maintained-guidance-v2",
  key="source-definition-version-v2-review",
        ),
        proof=proof(),
    )
    system.sources.decide_locator_continuity(
        locator_decision_request(), proof=proof()
    )
    system.sources.record_revision(revision_request(), proof=proof())
    system.sources.record_representation(
        representation_request(), proof=proof()
    )
    system.sources.record_occurrence(occurrence_request(), proof=proof())
    return system


def test_item_and_revision_identity_ignore_policy_metadata() -> None:
    item = item_request()
    item_reprocessed = replace(
        item,
        identity_policy=VersionedPolicyRef("fixture-item-identity", "v2"),
        uncertainties=("Policy wording changed; logical item did not.",),
    )
    assert item_reprocessed.identity_digest == item.identity_digest

    revision = revision_request()
    revision_reprocessed = replace(
        revision,
        revision_policy=VersionedPolicyRef("fixture-revision-rule", "v2"),
        canonicalizer_version="fixture-canonicalizer-v2",
    )
    assert revision_reprocessed.revision_identity_digest == revision.revision_identity_digest


def test_source_time_requires_canonical_typed_values() -> None:
    assert SourceTime(TimePrecision.DATE_ONLY, "2042-03-12").value == "2042-03-12"
    with pytest.raises(SourceContractError):
        SourceTime(TimePrecision.DATE_ONLY, "2042-3-12")
    with pytest.raises(SourceContractError):
        SourceTime(TimePrecision.EXACT, "2042-03-12T10:00:00+00:00")
    with pytest.raises(SourceContractError):
        SourceTime(TimePrecision.APPROXIMATE, "approximately noon")


def test_mixed_anchor_comparator_does_not_corrupt_active_mapping() -> None:
    request = version_request()
    mixed = replace(
        request,
        portfolio_functions=(
  PortfolioFunction.ANCHOR,
  PortfolioFunction.COMPARATOR,
        ),
    )
    assert mixed.coverage_mappings[0].contribution is CoverageContribution.REVISION_VISIBILITY

    comparator_active = replace(
        request,
        coverage_mappings=(
  replace(
      request.coverage_mappings[0],
      contribution=CoverageContribution.COMPARATOR,
  ),
        ),
    )
    with pytest.raises(SourceContractError, match="Active coverage"):
        comparator_active.__post_init__()


def test_source_version_can_explicitly_revert_but_not_emit_a_noop(tmp_path) -> None:
    system = open_source_system(tmp_path / "authority.sqlite3")
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())

    noop = version_request(
        version_id=SourceDefinitionVersionId.new(),
        version_number=2,
        previous_version_id=VERSION_1_ID,
        key="source-version-noop",
    )
    with pytest.raises(SourceSemanticCollision, match="no-op"):
        system.sources.record_definition_version(noop, proof=proof())

    system.sources.record_definition_version(
        version_request(
  version_id=VERSION_2_ID,
  version_number=2,
  previous_version_id=VERSION_1_ID,
  locator="fixture://increment-3a/maintained-guidance-v2",
  key="source-version-forward",
        ),
        proof=proof(),
    )
    reverted_id = SourceDefinitionVersionId.new()
    reverted = system.sources.record_definition_version(
        version_request(
  version_id=reverted_id,
  version_number=3,
  previous_version_id=VERSION_2_ID,
  locator="fixture://increment-3a/maintained-guidance-v1",
  key="source-version-revert",
        ),
        proof=proof(),
    )
    assert reverted.request.version_id == reverted_id
    assert system.sources.current_summary(DEFINITION_ID, proof=proof()).version_id == reverted_id
    system.close()


def test_duplicate_item_basis_and_native_revision_token_fail_closed(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = _seed_lineage(database)

    duplicate_item = replace(
        item_request(version_id=VERSION_2_ID),
        item_id=SourceItemId.new(),
        uncertainties=("Uncertainty wording changed only.",),
        idempotency_key="duplicate-item-basis",
    )
    with pytest.raises(SourceSemanticCollision):
        system.sources.register_item(duplicate_item, proof=proof())

    first = revision_request()
    conflicting_token = replace(
        first,
        revision_id=REVISION_2_ID,
        prior_revision_id=REVISION_1_ID,
        permitted_state_digest="sha256:" + "b" * 64,
        idempotency_key="conflicting-native-revision-token",
    )
    with pytest.raises(SourceSemanticCollision, match="revision token"):
        system.sources.record_revision(conflicting_token, proof=proof())
    system.close()


def test_source_native_item_identifier_is_unique_across_identity_shape(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_source_system(database)
    system.sources.register_definition(definition_request(), proof=proof())
    system.sources.record_definition_version(version_request(), proof=proof())
    first = SourceItemRequest(
        item_id=ITEM_ID,
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_1_ID,
        identity_kind=SourceItemIdentityKind.SOURCE_NATIVE,
        identity_policy=VersionedPolicyRef("fixture-item-identity", "v1"),
        source_native_id="native-item-1",
        identity_components=(),
        uncertainties=(),
        idempotency_key="native-item-first",
    )
    system.sources.register_item(first, proof=proof())
    second = replace(
        first,
        item_id=SourceItemId.new(),
        identity_components=(),
        uncertainties=("Later uncertainty must not duplicate native identity.",),
        idempotency_key="native-item-second",
    )
    with pytest.raises(SourceSemanticCollision, match="source-native item"):
        system.sources.register_item(second, proof=proof())
    system.close()


def test_metadata_scope_cannot_read_native_item_or_revision_details(tmp_path) -> None:
    database = tmp_path / "authority.sqlite3"
    system = _seed_lineage(database)
    system.close()

    restricted = open_source_system(
        database,
        granted_scopes=scopes() - frozenset({"authority.sources.read_sensitive"}),
    )
    assert restricted.sources.current_summary(DEFINITION_ID, proof=proof()).version_id == VERSION_2_ID
    with pytest.raises(PermissionError):
        restricted.sources.item(ITEM_ID, proof=proof())
    with pytest.raises(PermissionError):
        restricted.sources.revision(REVISION_1_ID, proof=proof())
    restricted.close()


@pytest.mark.parametrize(
    ("trigger", "statement", "parameters"),
    (
        (
  "immutable_source_item_update",
  "UPDATE source_items SET identity_policy_version='tampered' WHERE item_id=?",
  (str(ITEM_ID),),
        ),
        (
  "immutable_source_locator_decision_update",
  "UPDATE source_locator_continuity_decisions SET rationale='tampered'",
  (),
        ),
        (
  "immutable_source_revision_update",
  "UPDATE source_revisions SET canonicalizer_version='tampered' WHERE revision_id=?",
  (str(REVISION_1_ID),),
        ),
        (
  "immutable_discovery_representation_update",
  "UPDATE discovery_representations SET parser_version='tampered'",
  (),
        ),
        (
  "immutable_discovery_occurrence_update",
  "UPDATE discovery_occurrences SET receipt_digest=?",
  ("sha256:" + "0" * 64,),
        ),
        (
  "immutable_source_coverage_update",
  "UPDATE source_version_coverage_mappings SET limitations_bytes=?",
  (b"[]",),
        ),
    ),
)
def test_startup_rejects_normalized_sql_tamper(
    tmp_path,
    trigger: str,
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = _seed_lineage(database)
    system.close()

    conn = sqlite3.connect(database)
    try:
        trigger_sql = conn.execute(
  "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
  (trigger,),
        ).fetchone()[0]
        conn.execute(f"DROP TRIGGER {trigger}")
        conn.execute(statement, parameters)
        conn.execute(trigger_sql)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(AuthorityPersistenceError, match="differs from canonical"):
        open_source_system(database)
