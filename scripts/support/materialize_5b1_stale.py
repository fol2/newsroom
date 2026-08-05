from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


contracts = ROOT / "newsroom/increment5/branch_contracts.py"
replace_once(
    contracts,
    'class BranchExclusionReason(StrEnum):\n    RIGHTS_NOT_CURRENT = "RIGHTS_NOT_CURRENT"\n',
    'class BranchExclusionReason(StrEnum):\n'
    '    RIGHTS_NOT_CURRENT = "RIGHTS_NOT_CURRENT"\n'
    '    STALE_SOURCE_VERSION = "STALE_SOURCE_VERSION"\n',
)

queries = ROOT / "newsroom/increment5/exact_queries.py"
query_text = queries.read_text(encoding="utf-8")
for name, alias in (
    ("_SOURCE_NATIVE_QUERY", "i"),
    ("_SOURCE_REVISION_ID_QUERY", "r"),
    ("_SOURCE_NATIVE_REVISION_QUERY", "r"),
    ("_REPRESENTATION_QUERY", "d"),
):
    pattern = re.compile(rf'({re.escape(name)} = """\n.*?\n""")', re.DOTALL)
    match = pattern.search(query_text)
    if match is None:
        raise SystemExit(f"missing query block {name}")
    block = match.group(1)
    old_identity = (
        f"       {alias}.definition_id || ':' || h.current_version_id "
        "AS source_identity,"
    )
    new_identity = (
        f"       {alias}.definition_id || ':' || {alias}.definition_version_id "
        "AS source_identity,"
    )
    if block.count(old_identity) != 1:
        raise SystemExit(f"{name}: source identity boundary changed")
    block = block.replace(old_identity, new_identity, 1)

    old_policy = (
        "       v.allowed_use AS allowed_use,\n"
        "       v.lifecycle_stage AS lifecycle_state,\n"
        "       NULL AS valid_from,"
    )
    new_policy = (
        "       v.allowed_use AS allowed_use,\n"
        "       v.lifecycle_stage AS lifecycle_state,\n"
        "       CASE\n"
        "         WHEN h.current_version_id IS NOT NULL AND v.version_id IS NOT NULL\n"
        "         THEN 1 ELSE 0\n"
        "       END AS source_policy_available,\n"
        f"       CASE WHEN {alias}.definition_version_id=h.current_version_id "
        "THEN 1 ELSE 0 END\n"
        "         AS source_version_current,\n"
        "       NULL AS valid_from,"
    )
    if block.count(old_policy) != 1:
        raise SystemExit(f"{name}: policy columns boundary changed")
    block = block.replace(old_policy, new_policy, 1)

    for old_join, new_join in (
        (
            "JOIN source_definition_version_heads AS h",
            "LEFT JOIN source_definition_version_heads AS h",
        ),
        (
            "JOIN source_definition_versions AS v",
            "LEFT JOIN source_definition_versions AS v",
        ),
    ):
        if block.count(old_join) != 1:
            raise SystemExit(f"{name}: join boundary changed: {old_join}")
        block = block.replace(old_join, new_join, 1)

    query_text = query_text[: match.start()] + block + query_text[match.end() :]
queries.write_text(query_text, encoding="utf-8")

retriever = ROOT / "newsroom/increment5/exact_retriever.py"
retriever_text = retriever.read_text(encoding="utf-8")
if 'reason_code="SOURCE_VERSION_STALE"' not in retriever_text:
    needle = (
        "                if not hits and exclusions:\n"
        "                    reason = (\n"
    )
    replacement = (
        "                if not hits and exclusions:\n"
        "                    if all(\n"
        "                        item.reason\n"
        "                        is BranchExclusionReason.STALE_SOURCE_VERSION\n"
        "                        for item in exclusions\n"
        "                    ):\n"
        "                        return self._exact_receipt(\n"
        "                            request,\n"
        "                            start_ns=start_ns,\n"
        "                            outcome=BranchOutcome.STALE,\n"
        "                            reason_code=\"SOURCE_VERSION_STALE\",\n"
        "                            authority_watermark=watermark,\n"
        "                            exclusions=exclusions,\n"
        "                        )\n"
        "                    reason = (\n"
    )
    if retriever_text.count(needle) != 1:
        raise SystemExit("exact_retriever: no-hits boundary changed")
    retriever_text = retriever_text.replace(needle, replacement, 1)

if '"source_policy_available" in keys' not in retriever_text:
    needle = (
        '        for row in rows:\n'
        '            authority_kind = str(row["authority_kind"])\n'
        '            authority_id = str(row["authority_id"])\n'
        '            allowed_use = str(row["allowed_use"] or "").upper()\n'
        '            lifecycle = str(row["lifecycle_state"] or "").upper()\n'
    )
    replacement = (
        '        for row in rows:\n'
        '            keys = frozenset(row.keys())\n'
        '            authority_kind = str(row["authority_kind"])\n'
        '            authority_id = str(row["authority_id"])\n'
        '            if "source_policy_available" in keys:\n'
        '                policy_available = row["source_policy_available"]\n'
        '                if (\n'
        '                    isinstance(policy_available, bool)\n'
        '                    or not isinstance(policy_available, int)\n'
        '                    or policy_available not in {0, 1}\n'
        '                ):\n'
        '                    raise Increment5BranchContractError(\n'
        '                        "source policy availability flag is malformed"\n'
        '                    )\n'
        '                if policy_available == 0:\n'
        '                    raise Increment5BranchContractError(\n'
        '                        "current Source Definition policy is unavailable"\n'
        '                    )\n'
        '            allowed_use = str(row["allowed_use"] or "").upper()\n'
        '            lifecycle = str(row["lifecycle_state"] or "").upper()\n'
    )
    if retriever_text.count(needle) != 1:
        raise SystemExit("exact_retriever: row-admission boundary changed")
    retriever_text = retriever_text.replace(needle, replacement, 1)

if 'version_current = row["source_version_current"]' not in retriever_text:
    needle = '                continue\n            valid_from = row["valid_from"]\n'
    replacement = (
        '                continue\n'
        '            if "source_version_current" in keys:\n'
        '                version_current = row["source_version_current"]\n'
        '                if (\n'
        '                    isinstance(version_current, bool)\n'
        '                    or not isinstance(version_current, int)\n'
        '                    or version_current not in {0, 1}\n'
        '                ):\n'
        '                    raise Increment5BranchContractError(\n'
        '                        "source version current flag is malformed"\n'
        '                    )\n'
        '                if version_current == 0:\n'
        '                    exclusions.append(\n'
        '                        BranchExclusion(\n'
        '                            authority_kind=authority_kind,\n'
        '                            authority_id=authority_id,\n'
        '                            reason=BranchExclusionReason.STALE_SOURCE_VERSION,\n'
        '                        )\n'
        '                    )\n'
        '                    continue\n'
        '            valid_from = row["valid_from"]\n'
    )
    if retriever_text.count(needle) != 1:
        raise SystemExit("exact_retriever: source-version boundary changed")
    retriever_text = retriever_text.replace(needle, replacement, 1)
retriever.write_text(retriever_text, encoding="utf-8")

new_test = ROOT / "newsroom/tests/test_increment5b1_stale_source_version.py"
if new_test.exists():
    raise SystemExit(f"refusing to overwrite existing {new_test}")
new_test.write_text(
    '''from __future__ import annotations

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
''',
    encoding="utf-8",
)
