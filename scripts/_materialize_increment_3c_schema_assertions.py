from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one reviewed replacement, found {count}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/tests/test_complete_projection_2b_migrations.py",
        "    assert SCHEMA_VERSION == 10\n",
        "    assert SCHEMA_VERSION >= COMPLETE_PROJECTION_SCHEMA_VERSION\n",
    )
    replace_once(
        "newsroom/tests/test_increment_2d_candidate_authority.py",
        '        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 10\n',
        '        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION\n',
    )
    replace_once(
        "newsroom/tests/test_increment_2d_migrations.py",
        "    assert SCHEMA_VERSION == 10\n",
        "    assert SCHEMA_VERSION >= DEVELOPMENT_CANDIDATE_SCHEMA_VERSION\n",
    )
    projection = "newsroom/tests/test_projection_b1_migrations.py"
    replace_once(
        projection,
        "from newsroom.projection import (\n",
        "from newsroom.authority.migrations import SCHEMA_VERSION\n"
        "from newsroom.projection import (\n",
    )
    replace_once(
        projection,
        '        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10\n',
        '        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION\n',
    )
    replace_once(
        projection,
        '            (10, "source_registry_authority_v10"),\n',
        '            (10, "source_registry_authority_v10"),\n'
        '            (11, "check_transition_authority_v11"),\n',
    )
    replace_once(
        "newsroom/tests/test_relation_2a_contracts.py",
        "    assert SCHEMA_VERSION == 10\n",
        "    assert SCHEMA_VERSION >= COMPLETE_PROJECTION_SCHEMA_VERSION\n",
    )
    replace_once(
        "newsroom/tests/test_retrieval_2c_migrations.py",
        "    assert SCHEMA_VERSION == 10\n",
        "    assert SCHEMA_VERSION >= HYBRID_RETRIEVAL_SCHEMA_VERSION\n",
    )


if __name__ == "__main__":
    main()
