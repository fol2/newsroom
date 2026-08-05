from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from newsroom.increment5.branch_contracts import (
    BranchExclusionReason,
    BranchOutcome,
    ExactLookupKind,
)

from .increment5b1_helpers import _digest, _request, _system


def _advance_source_a_to_permitted_version(authority: Path) -> None:
    with sqlite3.connect(authority) as connection:
        connection.execute(
            "INSERT INTO source_definition_versions VALUES(?,?,?,?)",
            (
                "source-v1-current",
                "source-a",
                "RETRIEVAL_ALLOWED",
                "PRODUCTION_ELIGIBLE",
            ),
        )
        connection.execute(
            "UPDATE source_definition_version_heads SET current_version_id=? "
            "WHERE definition_id=?",
            ("source-v1-current", "source-a"),
        )


@pytest.mark.parametrize(
    ("kind", "value", "authority_scope_id", "expected_authority_id"),
    [
        (ExactLookupKind.SOURCE_NATIVE_ID, "native-42", "source-a", "item-a"),
        (ExactLookupKind.SOURCE_REVISION_ID, "revision-a", None, "revision-a"),
        (
            ExactLookupKind.SOURCE_NATIVE_REVISION_TOKEN,
            "native-revision-a",
            "item-a",
            "revision-a",
        ),
        (
            ExactLookupKind.REPRESENTATION_ID,
            "representation-a",
            None,
            "representation-a",
        ),
    ],
)
def test_permitted_current_version_change_marks_old_source_rows_stale(
    tmp_path: Path,
    kind: ExactLookupKind,
    value: str,
    authority_scope_id: str | None,
    expected_authority_id: str,
) -> None:
    authority, _journal, system = _system(tmp_path)
    _advance_source_a_to_permitted_version(authority)
    result = system.retrieve(
        _request(
            key=f"stale-version-{kind.value.lower()}",
            kind=kind,
            value=value,
            authority_scope_id=authority_scope_id,
        )
    ).receipt
    assert result.outcome is BranchOutcome.STALE
    assert result.reason_code == "SOURCE_VERSION_STALE"
    assert not result.hits
    assert [(item.authority_id, item.reason) for item in result.exclusions] == [
        (expected_authority_id, BranchExclusionReason.STALE_SOURCE_VERSION)
    ]


def test_current_and_stale_source_items_remain_distinguishable(tmp_path: Path) -> None:
    authority, _journal, system = _system(tmp_path)
    _advance_source_a_to_permitted_version(authority)
    with sqlite3.connect(authority) as connection:
        connection.execute(
            "INSERT INTO source_items VALUES(?,?,?,?,?,?)",
            (
                "item-current",
                "source-a",
                "source-v1-current",
                "native-42",
                _digest("item-current"),
                "event-current",
            ),
        )
    result = system.retrieve(
        _request(
            key="mixed-source-version",
            value="native-42",
            authority_scope_id="source-a",
        )
    ).receipt
    assert result.outcome is BranchOutcome.COMPLETE
    assert result.reason_code == "OK_WITH_EXCLUSIONS"
    assert [item.authority_id for item in result.hits] == ["item-current"]
    assert result.hits[0].source_identity == "source-a:source-v1-current"
    assert [(item.authority_id, item.reason) for item in result.exclusions] == [
        ("item-a", BranchExclusionReason.STALE_SOURCE_VERSION)
    ]


def test_current_rights_blocking_precedes_source_version_staleness(tmp_path: Path) -> None:
    authority, _journal, system = _system(tmp_path)
    with sqlite3.connect(authority) as connection:
        connection.execute(
            "INSERT INTO source_definition_versions VALUES(?,?,?,?)",
            ("source-v1-revoked", "source-a", "PROHIBITED", "RETIRED"),
        )
        connection.execute(
            "UPDATE source_definition_version_heads SET current_version_id=? "
            "WHERE definition_id=?",
            ("source-v1-revoked", "source-a"),
        )
    result = system.retrieve(
        _request(
            key="stale-but-rights-blocked",
            value="native-42",
            authority_scope_id="source-a",
        )
    ).receipt
    assert result.outcome is BranchOutcome.POLICY_BLOCKED
    assert result.reason_code == "RIGHTS_BLOCKED"
    assert not result.hits
    assert result.exclusions[0].reason is BranchExclusionReason.RIGHTS_NOT_CURRENT


def test_missing_current_source_policy_is_integrity_unavailable(tmp_path: Path) -> None:
    authority, _journal, system = _system(tmp_path)
    with sqlite3.connect(authority) as connection:
        connection.execute(
            "DELETE FROM source_definition_version_heads WHERE definition_id=?",
            ("source-a",),
        )
    result = system.retrieve(
        _request(
            key="missing-current-source-policy",
            value="native-42",
            authority_scope_id="source-a",
        )
    ).receipt
    assert result.outcome is BranchOutcome.UNAVAILABLE
    assert result.reason_code == "AUTHORITY_INTEGRITY_ERROR"
    assert not result.hits
