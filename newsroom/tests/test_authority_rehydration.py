from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest

from newsroom.authority import AuthenticationError, HydrationRequest, ObjectAdmissionDenied, ObjectIntegrityError
from .authority_a2b_helpers import MutableClock, admit, open_object_system
from .authority_helpers import FIXED_NOW, proof


def _counts(path):
    with sqlite3.connect(path) as connection:
        return tuple(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                     for table in ('object_access_decisions', 'authentication_contexts',
                                   'authorization_requests', 'authorization_decisions'))


def test_rehydrate_reuses_exact_receipt_without_recording_diagnostic_reads(tmp_path):
    path = tmp_path / 'authority.sqlite3'
    with open_object_system(path) as system:
        admission = admit(system, data=b'retained source bytes').admission
        request = HydrationRequest(admission.admission_id, 'project.discovery')
        first = system.objects.rehydrate(request, proof=proof())
        before = _counts(path)
        for _ in range(4):
            retained = system.objects.rehydrate(request, proof=proof())
            assert retained == first
        assert _counts(path) == before
        fresh = system.objects.hydrate(request, proof=proof())
        assert fresh.decision.access_decision_id != first.decision.access_decision_id
        assert _counts(path) == tuple(n + 1 for n in before)
        ranged = system.objects.rehydrate(
            HydrationRequest(admission.admission_id, 'project.discovery', offset=1, length=3), proof=proof())
        assert ranged.data == b'eta'
        assert ranged.decision.access_decision_id != fresh.decision.access_decision_id
    with open_object_system(path) as reopened:
        before = _counts(path)
        assert reopened.objects.rehydrate(request, proof=proof()) == fresh
        assert _counts(path) == before


def test_historical_access_receipt_remains_bound_after_a_fresh_read(tmp_path):
    with open_object_system(tmp_path / "authority.sqlite3") as system:
        admission = admit(system, data=b"retained source bytes").admission
        request = HydrationRequest(admission.admission_id, "project.discovery")
        first = system.objects.hydrate(request, proof=proof()).decision
        latest = system.objects.hydrate(request, proof=proof()).decision
        assert latest.access_decision_id != first.access_decision_id
        assert system.objects.access_decision(
            first.access_decision_id,
            admission_id=admission.admission_id,
            purpose="project.discovery",
            proof=proof(),
        ) == first


def test_rehydrate_still_authenticates_and_checks_revocation(tmp_path):
    path = tmp_path / 'authority.sqlite3'
    with open_object_system(path) as system:
        admission = admit(system).admission
        request = HydrationRequest(admission.admission_id, 'project.discovery')
        system.objects.rehydrate(request, proof=proof())
        with pytest.raises(AuthenticationError):
            system.objects.rehydrate(request, proof=proof(credential='wrong-token'))
        system.objects.revoke(admission.admission_id, reason_code='REVOKED', idempotency_key='revoke', proof=proof())
        before = _counts(path)
        with pytest.raises(ObjectAdmissionDenied):
            system.objects.rehydrate(request, proof=proof())
        assert _counts(path) == before


def test_rehydrate_rechecks_current_rights_expiry(tmp_path):
    clock = MutableClock(FIXED_NOW)
    with open_object_system(tmp_path / 'authority.sqlite3', clock=clock) as system:
        admission = admit(system, admission_type='source.short').admission
        request = HydrationRequest(admission.admission_id, 'project.discovery')
        system.objects.rehydrate(request, proof=proof())
        clock.current = type(FIXED_NOW)(FIXED_NOW.value + timedelta(seconds=31))
        with pytest.raises(ObjectAdmissionDenied):
            system.objects.rehydrate(request, proof=proof())


@pytest.mark.parametrize('fault_type', ('expiry', 'bytes'))
def test_rehydrate_rechecks_rights_and_pinned_bytes_after_read(tmp_path, fault_type):
    clock = MutableClock(FIXED_NOW)
    root = tmp_path / 'objects'
    armed = False

    def fault(checkpoint):
        if not armed or checkpoint != 'after_range_read_before_rehash':
            return
        if fault_type == 'expiry':
            clock.current = type(FIXED_NOW)(FIXED_NOW.value + timedelta(seconds=31))
        else:
            [path] = [path for path in (root / 'objects').rglob('*') if path.is_file()]
            path.chmod(0o600)
            path.write_bytes(b'tampered source bytes')
            path.chmod(0o400)

    path = tmp_path / 'authority.sqlite3'
    with open_object_system(path, object_root=root, clock=clock, fault_hook=fault) as system:
        admission = admit(system, admission_type='source.short').admission
        request = HydrationRequest(admission.admission_id, 'project.discovery')
        system.objects.rehydrate(request, proof=proof())
        before = _counts(path)
        armed = True
        with pytest.raises(ObjectAdmissionDenied if fault_type == 'expiry' else ObjectIntegrityError):
            system.objects.rehydrate(request, proof=proof())
        assert _counts(path) == before


def test_rehydrate_rejects_rebound_request_for_another_admission(tmp_path):
    import json
    from newsroom.authority import AuthorityPersistenceError, canonical_json_bytes
    from newsroom.authority.canonical import digest_bytes

    path = tmp_path / 'authority.sqlite3'
    with open_object_system(path) as system:
        first = admit(system, key='one', data=b'one').admission
        second = admit(system, key='two', data=b'two').admission
        request = HydrationRequest(first.admission_id, 'project.discovery')
        first_read = system.objects.hydrate(request, proof=proof())
        second_read = system.objects.hydrate(HydrationRequest(second.admission_id, 'project.discovery'), proof=proof())
        with sqlite3.connect(path) as conn:
            trigger, = conn.execute("SELECT sql FROM sqlite_master WHERE name='immutable_object_access_decisions_update'").fetchone()
            raw, = conn.execute('SELECT canonical_bytes FROM object_access_decisions WHERE access_decision_id=?',
                                (str(first_read.decision.access_decision_id),)).fetchone()
            record = json.loads(raw)
            fields = ('authentication_context_id', 'authorization_request_digest', 'authorization_decision_id')
            changed = tuple(str(getattr(second_read.decision, field)) for field in fields)
            record.update(zip(fields, changed))
            raw = canonical_json_bytes(record)
            conn.execute('DROP TRIGGER immutable_object_access_decisions_update')
            conn.execute('UPDATE object_access_decisions SET authentication_context_id=?,authorization_request_digest=?,authorization_decision_id=?,canonical_bytes=?,canonical_digest=? WHERE access_decision_id=?',
                         (*changed, raw, digest_bytes(raw), str(first_read.decision.access_decision_id)))
            conn.execute(trigger)
        with pytest.raises(AuthorityPersistenceError, match='request semantics'):
            system.objects.rehydrate(request, proof=proof())
