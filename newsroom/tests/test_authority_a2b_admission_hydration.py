from __future__ import annotations

import dataclasses
from datetime import timedelta
import inspect
import json
from pathlib import Path

import pytest

from newsroom.authority import (
    AuthenticationProof,
    BlobIdentity,
    HydrationPolicyContract,
    HydrationPolicyRegistry,
    HydrationRequest,
    ObjectAdmissionDefinition,
    ObjectAdmissionDenied,
    ObjectAdmissionRegistry,
    ObjectAdmissionRequest,
    ObjectHydrationDenied,
    RightsPolicyContract,
    RightsPolicyRegistry,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    UnknownObjectAdmissionDefinition,
    UtcTimestamp,
    digest_bytes,
)

from .authority_a2b_helpers import (
    MutableClock,
    _policy_registries,
    admit,
    open_object_system,
)
from .authority_helpers import FIXED_NOW, proof


def test_public_admission_accepts_only_request_source_and_proof(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        signature = inspect.signature(system.objects.admit)
        assert set(signature.parameters) == {
            "request",
            "source",
            "proof",
        }
        request_fields = set(ObjectAdmissionRequest.__dataclass_fields__)
        assert request_fields == {"admission_type", "idempotency_key"}
        prohibited = {
            "principal_id",
            "authority_domain",
            "now",
            "allowed",
            "rights_status",
            "object_class",
            "allowed_use",
            "security_scope",
            "retention_scope",
            "blob_digest",
            "size_bytes",
            "event_id",
        }
        assert prohibited.isdisjoint(request_fields)
    finally:
        system.close()


def test_authentication_and_authorization_happen_before_source_read(
    tmp_path: Path,
) -> None:
    class ExplodingSource:
        touched = False

        def read(self, _size: int) -> bytes:
            self.touched = True
            raise AssertionError("source was read before admission preflight")

    source = ExplodingSource()
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        scopes=frozenset(),
    )
    try:
        with pytest.raises(Exception):
            system.objects.admit(
                ObjectAdmissionRequest("source.capture", "denied"),
                source,
                proof=proof(),
            )
        assert source.touched is False
    finally:
        system.close()


def test_admission_rejects_final_principal_change_after_preflight(
    tmp_path: Path,
) -> None:
    class AlternatingAuthenticator:
        def __init__(self) -> None:
            self.calls = 0
            self.alpha = StaticAuthenticator(
                credentials={
                    "token-1": StaticPrincipal("principal.alpha")
                },
                authority_domain="newsroom.authority",
            )
            self.beta = StaticAuthenticator(
                credentials={
                    "token-1": StaticPrincipal("principal.beta")
                },
                authority_domain="newsroom.authority",
            )

        def authenticate(
            self, authentication_proof: object, *, now: UtcTimestamp
        ) -> object:
            self.calls += 1
            selected = self.alpha if self.calls == 1 else self.beta
            return selected.authenticate(authentication_proof, now=now)

    scopes = frozenset(
        {
            "authority.objects.admit",
            "authority.objects.lifecycle.write",
        }
    )
    object_root = tmp_path / "objects"
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        object_root=object_root,
        authenticator=AlternatingAuthenticator(),
        authorizer=StaticAuthorizer(
            policy_version="authz-v1",
            grants_by_principal={
                "principal.alpha": scopes,
                "principal.beta": scopes,
            },
        ),
    )
    try:
        with pytest.raises(Exception, match="differs from preflight authority"):
            admit(system, data=b"principal-bound", key="principal-switch")
        assert list((object_root / "staging").iterdir()) == []
        installed = object_root / "objects"
        assert not installed.exists() or not any(installed.rglob("*"))
    finally:
        system.close()


def test_preflight_authorization_decision_must_fall_inside_authentication_validity(
    tmp_path: Path,
) -> None:
    class OutOfWindowAuthorizer:
        def __init__(self) -> None:
            self.base = StaticAuthorizer(
                policy_version="authz-v1",
                grants_by_principal={
                    "principal.alpha": frozenset(
                        {"authority.objects.admit"}
                    )
                },
            )

        def authorize(
            self, context: object, request: object, *, now: UtcTimestamp
        ) -> object:
            decision = self.base.authorize(context, request, now=now)
            return dataclasses.replace(
                decision,
                decided_at=UtcTimestamp(
                    context.authenticated_at.value
                    - timedelta(microseconds=1)
                ),
            )

    class ExplodingSource:
        touched = False

        def read(self, _size: int) -> bytes:
            self.touched = True
            raise AssertionError("invalid authority must fail before staging")

    source = ExplodingSource()
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        authorizer=OutOfWindowAuthorizer(),
    )
    try:
        with pytest.raises(Exception, match="outside authentication validity"):
            system.objects.admit(
                ObjectAdmissionRequest("source.capture", "invalid-time"),
                source,
                proof=proof(),
            )
        assert source.touched is False
    finally:
        system.close()


def test_known_rights_denial_happens_before_source_read(tmp_path: Path) -> None:
    class ExplodingSource:
        touched = False

        def read(self, _size: int) -> bytes:
            self.touched = True
            raise AssertionError("source was read before known rights denial")

    source = ExplodingSource()
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        with pytest.raises(ObjectAdmissionDenied, match="PROHIBITED"):
            system.objects.admit(
                ObjectAdmissionRequest("source.prohibited", "deny-rights"),
                source,
                proof=proof(),
            )
        assert source.touched is False
    finally:
        system.close()


def test_admission_commits_ordered_activation_and_replay_has_no_stage_leak(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    system = open_object_system(database, object_root=object_root)
    try:
        first = admit(system, data=b"same bytes", key="idem")
        second = admit(system, data=b"same bytes", key="idem")
        assert first.replayed is False
        assert second.replayed is True
        assert second.admission.admission_id == first.admission.admission_id
        assert first.admission.activation_event_id is not None
        events = system.events.after(0, limit=1000, proof=proof())
        activated = [
            item
            for item in events
            if item.event_type == "governed_object.admission.activated"
        ]
        assert len(activated) == 1
        assert activated[0].object_admission_id is None
        assert list((object_root / "staging").iterdir()) == []
        mode = (object_root / "objects" / first.admission.blob.blob_digest[7:9] / first.admission.blob.blob_digest[7:]).stat().st_mode
        assert mode & 0o222 == 0
    finally:
        system.close()


def test_same_blob_supports_distinct_governed_admissions(tmp_path: Path) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        discovery = admit(
            system,
            data=b"same exact bytes",
            key="discovery",
            admission_type="source.capture",
        ).admission
        publishing = admit(
            system,
            data=b"same exact bytes",
            key="publishing",
            admission_type="source.publish",
        ).admission
        assert discovery.blob == publishing.blob
        assert discovery.admission_id != publishing.admission_id
        assert discovery.allowed_use == "project.discovery"
        assert publishing.allowed_use == "publish.article"
        assert discovery.rights_decision_id != publishing.rights_decision_id
    finally:
        system.close()


def test_hydration_reauthenticates_enforces_scope_and_persists_decision(
    tmp_path: Path,
) -> None:
    system = open_object_system(tmp_path / "authority.sqlite3")
    try:
        admitted = admit(system, data=b"0123456789").admission
        hydrated = system.objects.hydrate(
            HydrationRequest(
                admission_id=admitted.admission_id,
                purpose="project.discovery",
                offset=2,
                length=4,
            ),
            proof=proof(),
        )
        assert hydrated.data == b"2345"
        assert hydrated.decision.principal_id == "principal.alpha"
        assert hydrated.decision.authority_domain == "newsroom.authority"
        assert hydrated.decision.retention_scope == admitted.retention_scope
        assert hydrated.decision.allowed_bytes == 4
        assert digest_bytes(hydrated.decision.state_cutoff_bytes) == (
            hydrated.decision.state_cutoff_digest
        )
        cutoff = json.loads(
            hydrated.decision.state_cutoff_bytes.decode("utf-8")
        )
        assert cutoff["admission_id"] == str(admitted.admission_id)
        assert cutoff["admission_state"] == "ACTIVE"
        assert cutoff["blob_state"] == "ACTIVE"
        assert cutoff["blob_integrity_state"] == "VERIFIED"
        assert cutoff["offset"] == 2
        assert cutoff["length"] == 4

        denied = AuthenticationProof(method="STATIC_TOKEN", credential="wrong")
        with pytest.raises(Exception):
            system.objects.hydrate(
                HydrationRequest(admitted.admission_id, "project.discovery"),
                proof=denied,
            )
    finally:
        system.close()


def test_non_range_hydration_policy_requires_the_complete_object(
    tmp_path: Path,
) -> None:
    rights, existing_hydration, existing_admissions = _policy_registries()
    old_contract = existing_hydration.contracts()[0]
    full_read_only = dataclasses.replace(
        old_contract,
        contract_version="hydration-full-read-v1",
        implementation_version="hydration-full-read-static-v1",
        allow_ranges=False,
    )
    hydration = HydrationPolicyRegistry((full_read_only,))
    definitions = tuple(
        dataclasses.replace(
            definition,
            hydration_policy_contract_digests=frozenset(
                {full_read_only.contract_digest}
            ),
        )
        for definition in existing_admissions.definitions()
    )
    admissions = ObjectAdmissionRegistry(
        definitions,
        rights_policies=rights,
        hydration_policies=hydration,
    )
    system = open_object_system(
        tmp_path / "authority.sqlite3",
        policy_registries=(rights, hydration, admissions),
    )
    try:
        admitted = admit(system, data=b"0123456789").admission
        with pytest.raises(ObjectHydrationDenied, match="complete object"):
            system.objects.hydrate(
                HydrationRequest(
                    admitted.admission_id,
                    "project.discovery",
                    offset=0,
                    length=4,
                ),
                proof=proof(),
            )
        hydrated = system.objects.hydrate(
            HydrationRequest(admitted.admission_id, "project.discovery"),
            proof=proof(),
        )
        assert hydrated.data == b"0123456789"
    finally:
        system.close()


def test_committed_admission_replay_survives_policy_rollout_without_source_read(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    v1 = _policy_registries()
    system = open_object_system(database, policy_registries=v1)
    first = admit(system, data=b"historical", key="rollout")
    system.close()

    old_rights, hydration, old_admissions = v1
    old_permitted = old_rights.resolve("source-permitted")
    permitted_v2 = dataclasses.replace(
        old_permitted,
        contract_version="rights-v2",
        implementation_version="rights-static-v2",
        reason_code="PERMITTED_V2",
    )
    rights = RightsPolicyRegistry(
        (*old_rights.contracts(), permitted_v2),
        current_versions={"source-permitted": "rights-v2"},
    )
    capture_v1 = old_admissions.resolve("source.capture")
    capture_v2 = dataclasses.replace(
        capture_v1,
        definition_version="admission-v2",
        rights_policy_contract_digest=permitted_v2.contract_digest,
    )
    admissions = ObjectAdmissionRegistry(
        (*old_admissions.definitions(), capture_v2),
        rights_policies=rights,
        hydration_policies=hydration,
        current_versions={"source.capture": "admission-v2"},
    )

    class ExplodingSource:
        touched = False

        def read(self, _size: int) -> bytes:
            self.touched = True
            raise AssertionError("committed replay must not touch source")

    source = ExplodingSource()
    reopened = open_object_system(
        database,
        policy_registries=(rights, hydration, admissions),
    )
    try:
        replay = reopened.objects.admit(
            ObjectAdmissionRequest("source.capture", "rollout"),
            source,
            proof=proof(),
        )
        assert replay.replayed is True
        assert source.touched is False
        assert replay.admission.admission_id == first.admission.admission_id
        assert replay.admission.definition_version == "admission-v1"
    finally:
        reopened.close()


def test_committed_admission_replay_still_requires_current_authorization(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_object_system(database)
    admit(system, data=b"already committed", key="current-denial")
    system.close()

    class ExplodingSource:
        touched = False

        def read(self, _size: int) -> bytes:
            self.touched = True
            raise AssertionError("denied replay must not touch source")

    source = ExplodingSource()
    denied = open_object_system(database, scopes=frozenset())
    try:
        with pytest.raises(Exception):
            denied.objects.admit(
                ObjectAdmissionRequest("source.capture", "current-denial"),
                source,
                proof=proof(),
            )
        assert source.touched is False
    finally:
        denied.close()


def test_rights_time_invariant_and_transaction_time_expiry(tmp_path: Path) -> None:
    clock = MutableClock(FIXED_NOW)
    system = open_object_system(
        tmp_path / "authority.sqlite3", clock=clock
    )
    try:
        admitted = admit(
            system,
            data=b"short-lived",
            key="short",
            admission_type="source.short",
        ).admission
        rights = system.objects  # public facade has no rights constructor
        assert not hasattr(rights, "create_rights_decision")

        # Valid until is exclusive.
        clock.current = UtcTimestamp(
            FIXED_NOW.value + timedelta(seconds=30)
        )
        with pytest.raises(
            (ObjectHydrationDenied, ObjectAdmissionDenied),
            match="EXPIRED|expired|RIGHTS",
        ):
            system.objects.hydrate(
                HydrationRequest(admitted.admission_id, "project.discovery"),
                proof=proof(),
            )
    finally:
        system.close()


def test_hydration_expiry_during_byte_read_fails_closed(
    tmp_path: Path,
) -> None:
    clock = MutableClock(FIXED_NOW)
    armed = False

    def fault(checkpoint: str) -> None:
        nonlocal armed
        if armed and checkpoint == "after_range_read_before_rehash":
            clock.current = UtcTimestamp(
                FIXED_NOW.value + timedelta(seconds=30)
            )

    database = tmp_path / "authority.sqlite3"
    system = open_object_system(
        database, clock=clock, fault_hook=fault
    )
    try:
        admitted = admit(
            system,
            data=b"short-lived",
            key="short-read-expiry",
            admission_type="source.short",
        ).admission
        armed = True
        with pytest.raises(
            (ObjectHydrationDenied, ObjectAdmissionDenied),
            match="EXPIRED|expired|RIGHTS",
        ):
            system.objects.hydrate(
                HydrationRequest(
                    admitted.admission_id, "project.discovery"
                ),
                proof=proof(),
            )
    finally:
        system.close()

    import sqlite3

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM object_access_decisions"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_blob_identity_contains_no_lifecycle_state() -> None:
    identity = BlobIdentity("sha256:" + "a" * 64, 10)
    assert set(identity.__dataclass_fields__) == {"blob_digest", "size_bytes"}



def test_final_authorization_decision_must_be_inside_authentication_window(
    tmp_path: Path,
) -> None:
    delegate = StaticAuthorizer(
        policy_version="authz-v1",
        grants_by_principal={
            "principal.alpha": frozenset(
                {
                    "authority.observed.write",
                    "authority.admitted.write",
                    "authority.events.read",
                    "authority.objects.admit",
                    "authority.objects.read",
                    "authority.objects.manage",
                    "authority.objects.lifecycle.write",
                }
            )
        },
    )

    class BackdatedFinalDecision:
        calls = 0

        def authorize(self, context, request, *, now):
            self.calls += 1
            decision = delegate.authorize(context, request, now=now)
            if self.calls == 2:
                return dataclasses.replace(
                    decision,
                    decided_at=UtcTimestamp(
                        context.authenticated_at.value - timedelta(seconds=1)
                    ),
                )
            return decision

    system = open_object_system(
        tmp_path / "authority.sqlite3",
        authorizer=BackdatedFinalDecision(),
    )
    try:
        with pytest.raises(PermissionError, match="authentication validity"):
            admit(system, data=b"backdated authz")
    finally:
        system.close()



def test_expired_active_rights_do_not_brick_restart_but_remain_unusable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    clock = MutableClock(FIXED_NOW)
    system = open_object_system(
        database, object_root=object_root, clock=clock
    )
    try:
        admission = admit(
            system,
            data=b"expires while offline",
            key="offline-expiry",
            admission_type="source.short",
        ).admission
    finally:
        system.close()

    clock.current = UtcTimestamp(
        FIXED_NOW.value + timedelta(seconds=31)
    )
    reopened = open_object_system(
        database, object_root=object_root, clock=clock
    )
    try:
        with pytest.raises(
            (ObjectHydrationDenied, ObjectAdmissionDenied),
            match="EXPIRED|expired|RIGHTS",
        ):
            reopened.objects.hydrate(
                HydrationRequest(
                    admission.admission_id, "project.discovery"
                ),
                proof=proof(),
            )
    finally:
        reopened.close()


def test_startup_requires_all_retained_object_contract_versions(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    initial = open_object_system(database)
    initial.close()

    old_rights, hydration, old_admissions = _policy_registries()
    old_permitted = old_rights.resolve("source-permitted")
    permitted_v2 = dataclasses.replace(
        old_permitted,
        contract_version="rights-v2-only",
        implementation_version="rights-static-v2-only",
        reason_code="PERMITTED_V2_ONLY",
    )
    rights = RightsPolicyRegistry((permitted_v2,))
    capture_v2 = dataclasses.replace(
        old_admissions.resolve("source.capture"),
        definition_version="admission-v2-only",
        rights_policy_contract_digest=permitted_v2.contract_digest,
    )
    admissions = ObjectAdmissionRegistry(
        (capture_v2,),
        rights_policies=rights,
        hydration_policies=hydration,
    )

    with pytest.raises(
        UnknownObjectAdmissionDefinition,
        match="source.capture/admission-v1",
    ):
        open_object_system(
            database,
            policy_registries=(rights, hydration, admissions),
        )
