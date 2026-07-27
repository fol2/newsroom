from __future__ import annotations

from pathlib import Path
from textwrap import dedent


MIGRATIONS = Path("newsroom/authority/migrations.py")
SOURCE_LIFECYCLE = Path(
    "newsroom/tests/test_source_3a_lifecycle_integrity.py"
)
MIGRATION_TEST = Path("newsroom/tests/test_check_3c_migrations.py")


def _single_index(lines: list[str], value: str, *, after: int = 0) -> int:
    matches = [
        index
        for index, line in enumerate(lines)
        if index >= after and line == value
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"expected one {value!r} after line {after}, found {matches}"
        )
    return matches[0]


def _insert_check_migration_import(lines: list[str]) -> None:
    marker = _single_index(lines, "from .canonical import digest_canonical\n")
    block = [
        "from .check_migrations import (\n",
        "    CHECK_AUTHORITY_MIGRATION,\n",
        "    CHECK_AUTHORITY_MIGRATION_CHECKSUM,\n",
        "    CHECK_AUTHORITY_MIGRATION_NAME,\n",
        "    CHECK_AUTHORITY_MIGRATION_STATEMENTS,\n",
        "    CHECK_AUTHORITY_SCHEMA_VERSION,\n",
        ")\n",
    ]
    lines[marker + 1 : marker + 1] = block


def _activate_schema_head(lines: list[str]) -> None:
    marker = _single_index(
        lines,
        "SCHEMA_VERSION = SOURCE_REGISTRY_SCHEMA_VERSION\n",
    )
    lines[marker] = "SCHEMA_VERSION = CHECK_AUTHORITY_SCHEMA_VERSION\n"


def _update_migration_docstring(lines: list[str]) -> None:
    first = _single_index(
        lines,
        "    Fresh schema creation is all-or-nothing across the A2a and A2b migration\n",
    )
    second = _single_index(
        lines,
        "    records.  Upgrading an A2a schema applies only v2.\n",
        after=first,
    )
    if second != first + 1:
        raise SystemExit("migration docstring lines are no longer adjacent")
    lines[first : second + 1] = [
        "    Fresh schema creation is all-or-nothing across every retained authority\n",
        "    migration. Existing v10 source registries upgrade only through checked v11.\n",
    ]


def _insert_v11_application(lines: list[str]) -> None:
    marker = _single_index(
        lines,
        "            current = SOURCE_REGISTRY_SCHEMA_VERSION\n",
    )
    block = [
        "        if current == SOURCE_REGISTRY_SCHEMA_VERSION:\n",
        "            for statement in CHECK_AUTHORITY_MIGRATION_STATEMENTS:\n",
        "                conn.execute(statement)\n",
        "            conn.execute(\n",
        "                \"INSERT INTO authority_migrations(\"\n",
        "                \"version,name,checksum,applied_at) \"\n",
        "                \"VALUES(?,?,?,?)\",\n",
        "                (\n",
        "                    CHECK_AUTHORITY_SCHEMA_VERSION,\n",
        "                    CHECK_AUTHORITY_MIGRATION_NAME,\n",
        "                    CHECK_AUTHORITY_MIGRATION_CHECKSUM,\n",
        "                    applied_at,\n",
        "                ),\n",
        "            )\n",
        "            current = CHECK_AUTHORITY_SCHEMA_VERSION\n",
    ]
    lines[marker + 1 : marker + 1] = block


def _extend_migration_catalogue(lines: list[str]) -> None:
    section = _single_index(
        lines,
        "MIGRATIONS: tuple[MigrationRecord | object, ...] = (\n",
    )
    marker = _single_index(
        lines,
        "    SOURCE_REGISTRY_MIGRATION,\n",
        after=section,
    )
    lines.insert(marker + 1, "    CHECK_AUTHORITY_MIGRATION,\n")


def _extend_expected_history(lines: list[str]) -> None:
    section = _single_index(
        lines,
        "EXPECTED_MIGRATION_HISTORY: tuple[tuple[int, str, str], ...] = (\n",
    )
    checksum = _single_index(
        lines,
        "        SOURCE_REGISTRY_MIGRATION_CHECKSUM,\n",
        after=section,
    )
    closing_candidates = [
        index
        for index in range(checksum + 1, len(lines))
        if lines[index] == "    ),\n"
    ]
    if not closing_candidates:
        raise SystemExit("source migration history tuple has no closing line")
    closing = closing_candidates[0]
    lines[closing + 1 : closing + 1] = [
        "    (\n",
        "        CHECK_AUTHORITY_SCHEMA_VERSION,\n",
        "        CHECK_AUTHORITY_MIGRATION_NAME,\n",
        "        CHECK_AUTHORITY_MIGRATION_CHECKSUM,\n",
        "    ),\n",
    ]


def _patch_migrations() -> None:
    lines = MIGRATIONS.read_text(encoding="utf-8").splitlines(keepends=True)
    _insert_check_migration_import(lines)
    _activate_schema_head(lines)
    _update_migration_docstring(lines)
    _insert_v11_application(lines)
    _extend_migration_catalogue(lines)
    _extend_expected_history(lines)
    MIGRATIONS.write_text("".join(lines), encoding="utf-8")


def _patch_source_lifecycle() -> None:
    lines = SOURCE_LIFECYCLE.read_text(encoding="utf-8").splitlines(
        keepends=True
    )
    persistence = _single_index(
        lines,
        "from newsroom.authority.persistence import AuthorityPersistenceError\n",
    )
    lines.insert(
        persistence,
        "from newsroom.authority.migrations import SCHEMA_VERSION\n",
    )
    function = _single_index(
        lines,
        "def test_checked_source_registry_migration_is_v10_and_reopenable(\n",
    )
    lines[function] = (
        "def test_checked_source_registry_migration_is_retained_in_v11(\n"
    )
    pragma = _single_index(
        lines,
        '        assert conn.execute("PRAGMA user_version").fetchone()[0] == (\n',
    )
    version = _single_index(
        lines,
        "            SOURCE_REGISTRY_SCHEMA_VERSION\n",
        after=pragma,
    )
    if version != pragma + 1:
        raise SystemExit("source migration user-version assertion changed shape")
    lines[version] = "            SCHEMA_VERSION\n"
    SOURCE_LIFECYCLE.write_text("".join(lines), encoding="utf-8")


def _write_migration_test() -> None:
    MIGRATION_TEST.write_text(
        dedent(
            '''\
            from __future__ import annotations

            import sqlite3

            import pytest

            from newsroom.authority.check_migrations import (
                CHECK_AUTHORITY_MIGRATION_CHECKSUM,
                CHECK_AUTHORITY_MIGRATION_NAME,
                CHECK_AUTHORITY_SCHEMA_VERSION,
            )
            from newsroom.authority.migrations import (
                EXPECTED_MIGRATION_HISTORY,
                SCHEMA_VERSION,
            )
            from newsroom.authority.persistence import AuthoritySchemaError

            from .source_3a_helpers import open_source_system


            CHECK_TABLES = frozenset(
                {
                    "check_requests",
                    "check_attempts",
                    "check_outcomes",
                    "baseline_decisions",
                    "baseline_manifest_entries",
                    "baseline_decision_heads",
                    "observable_transitions",
                    "operational_findings",
                    "operational_finding_occurrences",
                    "discovery_occurrence_check_links",
                }
            )
            REQUIRED_TRIGGERS = frozenset(
                {
                    "check_request_source_contract_guard",
                    "check_request_coverage_guard",
                    "check_attempt_exact_predecessor_guard",
                    "baseline_decision_chain_guard",
                    "baseline_head_update_guard",
                    "observable_transition_source_contract_guard",
                    "discovery_occurrence_check_link",
                    "immutable_check_outcomes_update",
                    "immutable_observable_transitions_delete",
                }
            )


            def test_checked_v11_migration_creates_and_reopens_exact_schema(
                tmp_path,
            ) -> None:
                database = tmp_path / "authority.sqlite3"
                open_source_system(database).close()

                conn = sqlite3.connect(database)
                try:
                    assert conn.execute("PRAGMA user_version").fetchone()[0] == (
                        CHECK_AUTHORITY_SCHEMA_VERSION
                    )
                    assert SCHEMA_VERSION == CHECK_AUTHORITY_SCHEMA_VERSION
                    row = conn.execute(
                        "SELECT name,checksum FROM authority_migrations "
                        "WHERE version=?",
                        (CHECK_AUTHORITY_SCHEMA_VERSION,),
                    ).fetchone()
                    assert row == (
                        CHECK_AUTHORITY_MIGRATION_NAME,
                        CHECK_AUTHORITY_MIGRATION_CHECKSUM,
                    )
                    tables = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    triggers = {
                        str(row[0])
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='trigger'"
                        ).fetchall()
                    }
                    assert CHECK_TABLES <= tables
                    assert REQUIRED_TRIGGERS <= triggers
                finally:
                    conn.close()

                assert EXPECTED_MIGRATION_HISTORY[-1] == (
                    CHECK_AUTHORITY_SCHEMA_VERSION,
                    CHECK_AUTHORITY_MIGRATION_NAME,
                    CHECK_AUTHORITY_MIGRATION_CHECKSUM,
                )
                open_source_system(database).close()


            def test_startup_rejects_v11_migration_history_tampering(
                tmp_path,
            ) -> None:
                database = tmp_path / "authority.sqlite3"
                open_source_system(database).close()

                conn = sqlite3.connect(database)
                try:
                    trigger_sql = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='trigger' "
                        "AND name=?",
                        ("immutable_authority_migrations_update",),
                    ).fetchone()[0]
                    conn.execute(
                        "DROP TRIGGER immutable_authority_migrations_update"
                    )
                    conn.execute(
                        "UPDATE authority_migrations SET checksum=? "
                        "WHERE version=?",
                        (
                            "sha256:" + "0" * 64,
                            CHECK_AUTHORITY_SCHEMA_VERSION,
                        ),
                    )
                    conn.execute(trigger_sql)
                    conn.commit()
                finally:
                    conn.close()

                with pytest.raises(
                    AuthoritySchemaError,
                    match="migration history",
                ):
                    open_source_system(database)
            '''
        ),
        encoding="utf-8",
    )


def main() -> None:
    _patch_migrations()
    _patch_source_lifecycle()
    _write_migration_test()


if __name__ == "__main__":
    main()
