from __future__ import annotations

import json
import sqlite3

import pytest

from newsroom.authority import AuthorityPersistenceError, canonical_json_bytes
from newsroom.authority import security_record_migrations as migration
from newsroom.authority.canonical import digest_bytes
from newsroom.authority.migrations import apply_pending_migrations, schema_fingerprint

from .authority_event_helpers import open_test_system
from .authority_helpers import command, proof
from .graphiti_adapter_4d_migration_helpers import _drop_v37_security_record_schema


def test_current_security_storage_is_compact_with_exact_public_provenance(tmp_path):
    path = tmp_path / 'authority.sqlite3'
    original_command = command(key='compact-one')
    with open_test_system(path) as system:
        result = system.commands.execute(original_command, proof=proof())
        before = system.events.provenance(result.event_id, proof=proof())
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 37
        auth = connection.execute('SELECT * FROM authentication_contexts').fetchone()
        request = connection.execute('SELECT * FROM authorization_requests').fetchone()
        assert bytes(auth['storage_context_marker']) == b'v37'
        assert bytes(request['canonical_bytes']) == before.authorization_request.canonical_bytes
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    with open_test_system(path) as system:
        after = system.events.provenance(result.event_id, proof=proof())
        replay = system.commands.execute(original_command, proof=proof())
        system.commands.execute(command(key='compact-two'), proof=proof())
    assert replay.replayed
    assert after == before
    assert digest_bytes(after.authentication.canonical_bytes) == after.authentication.canonical_digest
    assert digest_bytes(after.authorization_request.canonical_bytes) == after.authorization_request.canonical_record_digest
    assert canonical_json_bytes(json.loads(after.authorization_request.canonical_bytes)) == before.authorization_request.canonical_bytes


def _v36_path(tmp_path, *, count=2):
    path = tmp_path / 'old.sqlite3'
    commands = tuple(command(key=f'old-{index}') for index in range(count))
    with open_test_system(path) as system:
        results = tuple(system.commands.execute(item, proof=proof()) for item in commands)
        originals = tuple(system.events.provenance(item.event_id, proof=proof()) for item in results)
    with sqlite3.connect(path) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        _drop_v37_security_record_schema(connection)
        assert schema_fingerprint(connection) == migration.SECURITY_RECORD_PREDECESSOR_FINGERPRINT
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
    return path, commands, originals


def _state(connection):
    return (connection.execute('PRAGMA user_version').fetchone()[0], schema_fingerprint(connection),
            tuple(connection.execute('SELECT * FROM authority_migrations ORDER BY version')),
            tuple(connection.execute('SELECT * FROM authentication_contexts ORDER BY authentication_context_id')),
            tuple(connection.execute('SELECT * FROM authorization_requests ORDER BY request_digest')))


def _change(connection, table, sql, parameters=()):
    name = f'immutable_{table}_update'
    guard = connection.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
    connection.execute(f'DROP TRIGGER {name}')
    connection.execute(sql, parameters)
    connection.execute(guard)


def test_v36_upgrade_preserves_provenance_replay_and_leaves_requests_unchanged(tmp_path):
    path, commands, originals = _v36_path(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute('SELECT * FROM authorization_requests LIMIT 1').fetchone())
        value = json.loads(row['canonical_bytes'])
        value['future_extension'] = {'unicode': '證據', 'nullable': None, 'items': [1, True]}
        value.pop('request_digest')
        unsigned = canonical_json_bytes(value)
        value['request_digest'] = digest_bytes(unsigned)
        full = canonical_json_bytes(value)
        row.update(request_digest=value['request_digest'], canonical_bytes=full, canonical_record_digest=digest_bytes(full))
        connection.execute('INSERT INTO authorization_requests VALUES(?,?,?,?,?,?,?,?,?)', tuple(row.values()))
    with open_test_system(path) as system:
        for original in originals:
            assert system.events.provenance(original.event.event_id, proof=proof()) == original
        assert system.commands.execute(commands[0], proof=proof()).replayed
    from newsroom.authority._event_store import _EventAuthorityStore
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        retained = connection.execute('SELECT * FROM authorization_requests WHERE request_digest=?', (value['request_digest'],)).fetchone()
        reader = object.__new__(_EventAuthorityStore)
        assert reader._request_record_from_row(retained).canonical_bytes == full
        assert bytes(retained['canonical_bytes']) == full
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('tamper', ('context_json', 'context_index', 'context_digest'))
def test_v36_corruption_rejected_before_conversion_with_atomic_rollback(tmp_path, tamper):
    path, _, _ = _v36_path(tmp_path)
    with sqlite3.connect(path) as connection:
        table = 'authentication_contexts'
        if tamper == 'context_json':
            sql, parameters = f'UPDATE {table} SET canonical_bytes=?', (b'{ }',)
        elif tamper == 'context_index':
            sql, parameters = f'UPDATE {table} SET principal_id=?', ('changed',)
        else:
            sql, parameters = f'UPDATE {table} SET canonical_digest=?', ('sha256:' + 'f'*64,)
        _change(connection, table, sql + ' WHERE rowid=(SELECT max(rowid) FROM authentication_contexts)', parameters)
        connection.commit()
        before = _state(connection)
        updates = []
        connection.set_trace_callback(lambda sql: updates.append(sql) if sql.startswith(
            'UPDATE authentication_contexts SET canonical_bytes='
        ) else None)
        with pytest.raises(sqlite3.IntegrityError):
            apply_pending_migrations(connection, applied_at='2026-09-13T00:00:00.000000Z')
        assert updates == []
        assert _state(connection) == before


@pytest.mark.parametrize('counter', ('validations', 'updates'))
def test_v37_validates_once_then_compacts_with_one_update(tmp_path, monkeypatch, counter):
    path, _, _ = _v36_path(tmp_path, count=3)
    validations = []
    updates = []
    validate = migration._validate_old_context

    def counted(row):
        validate(row)
        validations.append(row['authentication_context_id'])

    monkeypatch.setattr(migration, '_validate_old_context', counted)
    with sqlite3.connect(path) as connection:
        connection.set_trace_callback(lambda sql: updates.append(sql) if sql.startswith(
            'UPDATE authentication_contexts SET canonical_bytes='
        ) else None)
        apply_pending_migrations(connection, applied_at='2026-09-13T00:00:00.000000Z')
        if counter == 'validations':
            assert len(validations) == 3
        else:
            assert len(updates) == 1
        assert len(set(validations)) == 3
        assert connection.execute(
            'SELECT count(*) FROM authentication_contexts WHERE storage_context_marker=?',
            (b'v37',),
        ).fetchone()[0] == 3


def test_v37_conversion_failure_after_update_rolls_back_exactly(tmp_path):
    class FailedUpdate(sqlite3.Connection):
        converted = False

        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            if sql.startswith('UPDATE authentication_contexts SET canonical_bytes='):
                assert super().execute(
                    'SELECT count(*) FROM authentication_contexts WHERE canonical_bytes=?',
                    (b'v37',),
                ).fetchone()[0] > 0
                self.converted = True
                raise sqlite3.IntegrityError('injected after compacting contexts')
            return cursor

    path, _, _ = _v36_path(tmp_path)
    with sqlite3.connect(path, factory=FailedUpdate) as connection:
        before = _state(connection)
        with pytest.raises(sqlite3.IntegrityError, match='after compacting contexts'):
            apply_pending_migrations(connection, applied_at='2026-09-13T00:00:00.000000Z')
        assert connection.converted
        assert _state(connection) == before


@pytest.mark.parametrize('tamper', ('context_marker', 'context_index'))
def test_compact_reopen_preserves_all_integrity_checks(tmp_path, tamper):
    path = tmp_path / 'reopen.sqlite3'
    with open_test_system(path) as system:
        system.commands.execute(command(key='compact'), proof=proof())
    with sqlite3.connect(path) as connection:
        table = 'authentication_contexts'
        if tamper == 'context_marker':
            sql, parameters = 'UPDATE authentication_contexts SET storage_context_marker=?', (b'v36',)
        else:
            sql, parameters = f'UPDATE {table} SET principal_id=?', ('changed',)
        _change(connection, table, sql, parameters)
    with pytest.raises(AuthorityPersistenceError):
        with open_test_system(path):
            pass


@pytest.mark.parametrize('boundary', ('no_transaction', 'schema', 'history'))
def test_v37_requires_exact_atomic_predecessor(tmp_path, boundary):
    path, _, _ = _v36_path(tmp_path)
    with sqlite3.connect(path) as connection:
        history = tuple(tuple(row[:3]) for row in connection.execute('SELECT * FROM authority_migrations ORDER BY version'))
        if boundary == 'schema':
            connection.execute('CREATE INDEX unexpected_security_index ON authentication_contexts(principal_id)')
            connection.commit()
        before = _state(connection)
        if boundary != 'no_transaction':
            connection.execute('BEGIN EXCLUSIVE')
        with pytest.raises(sqlite3.DatabaseError, match='active transaction|exact checked'):
            migration.migrate_security_records(connection, expected_history=() if boundary == 'history' else history)
        connection.rollback()
        assert _state(connection) == before


@pytest.mark.parametrize(('version', 'expected_calls'), ((36, 0), (37, 1)))
def test_exact_prefix_invokes_v37_only_at_its_version(tmp_path, monkeypatch, version, expected_calls):
    from newsroom.authority import migrations
    from .authority_migration_compatibility import build_exact_prefix
    calls = 0
    original = migrations.migrate_security_records

    def counted(connection, *, expected_history):
        nonlocal calls
        calls += 1
        assert connection.in_transaction
        original(connection, expected_history=expected_history)
    monkeypatch.setattr(migrations, 'migrate_security_records', counted)
    build_exact_prefix(tmp_path / f'prefix-{version}.sqlite3', version)
    assert calls == expected_calls


def test_v37_downgrade_is_lossless_inside_callers_transaction(tmp_path):
    path = tmp_path / 'rollback.sqlite3'
    with open_test_system(path) as system:
        system.commands.execute(command(key='nested'), proof=proof())
    with sqlite3.connect(path, isolation_level=None) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        before = _state(connection)
        connection.execute('SAVEPOINT caller')
        _drop_v37_security_record_schema(connection)
        assert connection.in_transaction
        assert connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        assert schema_fingerprint(connection) == migration.SECURITY_RECORD_PREDECESSOR_FINGERPRINT
        connection.execute('ROLLBACK TO SAVEPOINT caller')
        connection.execute('RELEASE SAVEPOINT caller')
        assert _state(connection) == before
