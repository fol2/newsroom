"""Lossless content-addressed proving storage and explicit migration."""

import sqlite3

import pytest

from newsroom.authority.canonical import digest_bytes
from newsroom.increment9 import proving


BODY = b'<rss><channel><item><title>Retained</title><link>https://example.test/a</link></item></channel></rss>'
AT = '2026-09-01T00:00:00.000000Z'


def _put(connection, run='r1', source='UK-01', body=BODY, digest=None):
    connection.execute('INSERT OR IGNORE INTO proving_runs(run_id,started_at) VALUES(?,?)', (run, AT))
    observation = proving.Observation(source, 'https://example.test/feed.xml', AT, 200, digest or digest_bytes(body), 1, None)
    proving._put(connection, run, AT, observation, body)


def test_shared_body_preserves_every_observation_and_first_seen(tmp_path):
    connection = proving._connect(str(tmp_path / 'proving.sqlite3'))
    with connection:
        for run, source in [('r1', 'UK-01'), ('r2', 'UK-01'), ('r2', 'HK-01')]:
            _put(connection, run, source)
    assert connection.execute('SELECT COUNT(*) FROM proving_bodies').fetchone() == (1,)
    assert connection.execute('SELECT COUNT(*) FROM proving_observations').fetchone() == (3,)
    assert connection.execute('SELECT COUNT(*) FROM proving_revision_first_seen').fetchone() == (2,)
    assert proving.resolve_observation_body(connection, digest_bytes(BODY)) == BODY
    assert 'body' not in {row[1] for row in connection.execute('PRAGMA table_info(proving_observations)')}
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute('DELETE FROM proving_bodies')
    connection.close()


def test_digest_mismatch_and_conflict_leave_no_partial_observation(tmp_path):
    connection = proving._connect(str(tmp_path / 'proving.sqlite3'))
    connection.execute('INSERT INTO proving_runs(run_id,started_at) VALUES(?,?)', ('r1', AT))
    with pytest.raises(ValueError, match='digest'):
        _put(connection, digest=digest_bytes(b'wrong'))
    assert connection.execute('SELECT COUNT(*) FROM proving_bodies').fetchone() == (0,)
    connection.execute('INSERT INTO proving_bodies VALUES(?,?)', (digest_bytes(BODY), b'corrupt'))
    with pytest.raises(ValueError, match='conflict'):
        _put(connection)
    assert connection.execute('SELECT COUNT(*) FROM proving_observations').fetchone() == (0,)
    connection.close()


@pytest.mark.parametrize('body', [None, 'text', b'wrong'])
def test_body_resolution_refuses_missing_non_blob_and_mismatch(tmp_path, body):
    connection = proving._connect(str(tmp_path / 'proving.sqlite3'))
    if body is not None:
        connection.execute('INSERT INTO proving_bodies VALUES(?,?)', (digest_bytes(BODY), body))
    with pytest.raises(ValueError, match='body'):
        proving.resolve_observation_body(connection, digest_bytes(BODY))
    connection.close()


def test_put_rolls_back_body_if_metadata_or_first_seen_fails(tmp_path, monkeypatch):
    connection = proving._connect(str(tmp_path / 'proving.sqlite3'))
    def fail(*args, **kwargs):
        raise RuntimeError('injected first-seen failure')
    monkeypatch.setattr(proving, 'retain_observation_revision_first_seen', fail)
    with pytest.raises(RuntimeError, match='injected'):
        _put(connection)
    assert connection.execute('SELECT COUNT(*) FROM proving_bodies').fetchone() == (0,)
    assert connection.execute('SELECT COUNT(*) FROM proving_observations').fetchone() == (0,)
    connection.close()


def _legacy(path, *, corrupt=None):
    from newsroom.increment9.proving_store_schema import _V1_SCHEMA
    from newsroom.effective_revision import create_effective_revision_schema
    connection = sqlite3.connect(path)
    connection.executescript(_V1_SCHEMA)
    create_effective_revision_schema(connection)
    connection.execute('CREATE TABLE unrelated_extension(value TEXT)')
    connection.execute("INSERT INTO unrelated_extension VALUES('keep')")
    for run, source in [('r1', 'UK-01'), ('r2', 'UK-01'), ('r2', 'HK-01')]:
        connection.execute('INSERT OR IGNORE INTO proving_runs(run_id,started_at) VALUES(?,?)', (run, AT))
        connection.execute('INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)',
                           (source, run, AT, 'https://example.test/feed.xml', 200, digest_bytes(BODY), BODY if corrupt is None else corrupt, 1, None))
    connection.execute("INSERT INTO proving_gates VALUES('r1','KEEP','PASS','retained')")
    connection.execute("INSERT INTO proving_rights_packets VALUES('r1','KEEP','digest','{}',?)", (AT,))
    connection.execute("INSERT INTO proving_source_health VALUES('UK-01','r1','ACTIVE','endpoint',1,NULL,NULL,NULL)")
    connection.execute("INSERT INTO proving_revision_first_seen VALUES('UK-01','item','revision',?)", (AT,))
    connection.execute("INSERT INTO proving_effective_pull_first_seen VALUES('UK-01','item','revision','','',?)", (AT,))
    connection.execute("INSERT INTO proving_backfill_watermark VALUES('2026-08-01T00:00:00.000000Z')")
    connection.commit()
    return connection


def _snapshot(connection):
    return {name: sorted(connection.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if name not in ('proving_observations', 'proving_bodies')}


def test_explicit_migration_preserves_metadata_auxiliary_records_and_readonly_resolution(tmp_path):
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies, physical_store_version
    path = tmp_path / 'legacy.sqlite3'
    connection = _legacy(path)
    before = _snapshot(connection)
    observations = connection.execute('SELECT source_id,run_id,fetched_at,url,status_code,body_digest,item_count,error FROM proving_observations ORDER BY rowid').fetchall()
    assert physical_store_version(connection) == 1
    with pytest.raises(proving.ProvingError, match='explicit'):
        proving._connect(str(path))
    assert migrate_proving_bodies(connection) == {'observations': 3, 'bodies': 1, 'physical_store_version': 2}
    assert connection.execute('SELECT * FROM proving_observations ORDER BY rowid').fetchall() == observations
    assert {key: _snapshot(connection)[key] for key in before} == before
    assert connection.execute('SELECT * FROM proving_revision_first_seen').fetchall() == [('UK-01', 'item', 'revision', AT)]
    assert physical_store_version(connection) == 2
    connection.close()
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as readonly:
        assert proving.resolve_observation_body(readonly, digest_bytes(BODY)) == BODY
    with sqlite3.connect(':memory:') as attached:
        attached.execute('ATTACH DATABASE ? AS "odd""schema"', (str(path),))
        assert proving.resolve_observation_body(attached, digest_bytes(BODY), schema='odd"schema') == BODY


@pytest.mark.parametrize('corrupt', ['text', b'wrong'])
def test_migration_corrupt_body_rolls_back_exact_old_layout(tmp_path, corrupt):
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies, physical_store_version
    connection = _legacy(tmp_path / 'legacy.sqlite3', corrupt=corrupt)
    before = list(connection.iterdump())
    with pytest.raises(ValueError, match='body'):
        migrate_proving_bodies(connection)
    assert list(connection.iterdump()) == before
    assert physical_store_version(connection) == 1
    connection.close()


def test_migration_injected_failure_after_swap_rolls_back_ddl_and_rows(tmp_path):
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies, physical_store_version
    connection = _legacy(tmp_path / 'legacy.sqlite3')
    before = list(connection.iterdump())
    def deny_version(action, arg1, arg2, *_):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_PRAGMA and arg1 == 'user_version' and arg2 == '2' else sqlite3.SQLITE_OK
    connection.set_authorizer(deny_version)
    with pytest.raises(sqlite3.DatabaseError):
        migrate_proving_bodies(connection)
    connection.set_authorizer(None)
    assert list(connection.iterdump()) == before
    assert physical_store_version(connection) == 1
    connection.close()


@pytest.mark.parametrize('mutation', [
    'PRAGMA user_version=99',
    'CREATE TABLE proving_bodies(body_digest TEXT PRIMARY KEY, body BLOB NOT NULL) WITHOUT ROWID',
    'ALTER TABLE proving_observations ADD COLUMN surprise TEXT',
    'DROP TABLE proving_source_health',
])
def test_migration_rejects_newer_hybrid_and_malformed_layouts_without_mutation(tmp_path, mutation):
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies
    connection = _legacy(tmp_path / 'legacy.sqlite3')
    connection.execute(mutation)
    connection.commit()
    before = list(connection.iterdump())
    with pytest.raises(ValueError):
        migrate_proving_bodies(connection)
    assert list(connection.iterdump()) == before
    connection.close()


def test_migration_compares_exact_bytes_on_shared_digest_conflict(tmp_path, monkeypatch):
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies
    connection = _legacy(tmp_path / 'legacy.sqlite3')
    connection.execute("UPDATE proving_observations SET body=? WHERE run_id='r2'", (b'collision',))
    connection.commit()
    before = list(connection.iterdump())
    monkeypatch.setattr(proving, 'digest_bytes', lambda body: digest_bytes(BODY))
    with pytest.raises(ValueError, match='conflict'):
        migrate_proving_bodies(connection)
    assert list(connection.iterdump()) == before
    connection.close()


def test_migrated_and_fresh_first_seen_and_backlog_plans_are_equivalent(tmp_path):
    from datetime import UTC, datetime
    from newsroom.control_plane.backlog_reconciliation import _build_plan, _census_proving, _usable_observation_rows
    from newsroom.effective_revision import backfill_missing_first_seen
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies

    legacy = _legacy(tmp_path / 'legacy.sqlite3')
    fresh = proving._connect(str(tmp_path / 'fresh.sqlite3'))
    for (table,) in legacy.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='unrelated_extension'"):
        for row in legacy.execute(f'SELECT * FROM "{table}"'):
            if table == 'proving_observations':
                proving._store_body(fresh, row[5], row[6])
                row = (*row[:6], *row[7:])
            fresh.execute(f'INSERT INTO "{table}" VALUES({",".join("?" for _ in row)})', row)
    fresh.commit()
    old_census = _census_proving(legacy)
    migrate_proving_bodies(legacy)
    assert _census_proving(legacy) == old_census == _census_proving(fresh)
    assert _usable_observation_rows(legacy) == _usable_observation_rows(fresh)
    assert backfill_missing_first_seen(legacy) == backfill_missing_first_seen(fresh)
    at = datetime(2026, 9, 2, tzinfo=UTC)
    assert _build_plan(legacy, None, evaluated_at=at) == _build_plan(fresh, None, evaluated_at=at)
    legacy.close()
    fresh.close()


def test_representative_sqlite_fixture_reclaims_only_repeated_body_pages(tmp_path):
    from newsroom.increment9.proving_store_schema import _V1_SCHEMA, migrate_proving_bodies
    from newsroom.effective_revision import create_effective_revision_schema

    path = tmp_path / 'repeated.sqlite3'
    connection = sqlite3.connect(path)
    connection.executescript(_V1_SCHEMA)
    create_effective_revision_schema(connection)
    for index in range(120):
        body = (f'<rss><channel><title>Fixture {index % 12}</title><description>'
                + 'Retained source material. ' * 1310 + '</description></channel></rss>').encode()
        run = f'run-{index}'
        connection.execute('INSERT INTO proving_runs(run_id,started_at) VALUES(?,?)', (run, AT))
        connection.execute('INSERT INTO proving_observations VALUES(?,?,?,?,?,?,?,?,?)',
                           ('UK-01', run, AT, 'https://example.test/feed.xml', 200, digest_bytes(body), body, 1, None))
    connection.commit()
    connection.execute('VACUUM')
    before = path.stat().st_size
    old_count = connection.execute('SELECT COUNT(*) FROM proving_observations').fetchone()[0]
    assert migrate_proving_bodies(connection)['bodies'] == 12
    assert path.stat().st_size >= before  # Logical sharing alone is not physical reclamation.
    connection.execute('VACUUM')
    after = path.stat().st_size
    assert after < before // 2
    assert connection.execute('SELECT COUNT(*) FROM proving_observations').fetchone()[0] == old_count == 120
    assert connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    print({'scope': 'synthetic SQLite fixture only', 'observations': 120, 'bodies': 12,
           'before_bytes': before, 'after_vacuum_bytes': after, 'reclaimed_bytes': before - after})
    connection.close()


@pytest.mark.parametrize("table", ["related", "sqlitexrelated"])
def test_migration_rejects_related_cascade_extension_without_losing_rows(tmp_path, table):
    from newsroom.increment9.proving_store_schema import migrate_proving_bodies
    connection = _legacy(tmp_path / 'legacy.sqlite3')
    connection.execute(f'CREATE TABLE {table}(run_id TEXT,source_id TEXT,body_digest TEXT, '
                       'FOREIGN KEY(run_id,source_id,body_digest) '
                       'REFERENCES proving_observations(run_id,source_id,body_digest) ON DELETE CASCADE)')
    connection.execute(f'INSERT INTO {table} SELECT run_id,source_id,body_digest FROM proving_observations')
    connection.commit()
    before = list(connection.iterdump())
    with pytest.raises(ValueError, match='related objects'):
        migrate_proving_bodies(connection)
    assert list(connection.iterdump()) == before
    connection.close()
