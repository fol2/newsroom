from __future__ import annotations

import atexit

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from threading import RLock
from typing import Callable

from newsroom.authority import (
    AuthenticationProof,
    EventId,
    EventReadPolicy,
    MetadataClass,
    ObjectAdmissionId,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    TrustScope,
    UtcTimestamp,
)
from newsroom.authority.policy import CommandRegistry, PayloadSchemaRegistry
from newsroom.relations import (
    FixturePassageObject,
    INTEGRATED_FIXTURE_V2,
    IntegratedFixtureV2BindingId,
    IntegratedFixtureV2BindingRequest,
    RelationDecisionAction,
    RelationDecisionRequest,
    RelationProposal,
    RelationProposalId,
    RelationReadPolicy,
    merge_relation_authority_registries,
    open_governed_relation_authority_system,
    sorted_passage_objects,
)

from .authority_a2b_helpers import admit, open_object_system
from .authority_event_helpers import payload_schemas, registry_v1


RELATION_NOW = UtcTimestamp.parse("2042-03-12T12:00:00.000000Z")
BINDING_ID = IntegratedFixtureV2BindingId.parse(
    "00000000-0000-4000-8000-000000002101"
)
PROPOSAL_ID = RelationProposalId.parse(
    "00000000-0000-4000-8000-000000002104"
)
SECOND_PROPOSAL_ID = RelationProposalId.parse(
    "00000000-0000-4000-8000-000000002105"
)


@dataclass(slots=True)
class RelationClock:
    current: UtcTimestamp = RELATION_NOW

    def __call__(self) -> UtcTimestamp:
        return self.current


@dataclass(frozen=True, slots=True)
class SeededFixtureObjects:
    binding_request: IntegratedFixtureV2BindingRequest
    admission_by_passage_id: dict[str, ObjectAdmissionId]
    manifest_admission_id: ObjectAdmissionId
    tombstone_event_id: EventId | None
    commands: CommandRegistry
    schemas: PayloadSchemaRegistry


_SEED_TEMPLATE_LOCK = RLock()
_SEED_TEMPLATE_ROOT: Path | None = None
_SEED_TEMPLATES: dict[bool, tuple[Path, Path, SeededFixtureObjects]] = {}


def _cleanup_seed_templates() -> None:
    global _SEED_TEMPLATE_ROOT
    with _SEED_TEMPLATE_LOCK:
        root = _SEED_TEMPLATE_ROOT
        _SEED_TEMPLATES.clear()
        _SEED_TEMPLATE_ROOT = None
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


atexit.register(_cleanup_seed_templates)


def proof(*, credential: str = "token-1") -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential=credential)


def scopes() -> frozenset[str]:
    return frozenset(
        {
            "authority.observed.write",
            "authority.admitted.write",
            "authority.fixture.events.read",
            "authority.objects.admit",
            "authority.objects.read",
            "authority.objects.manage",
            "authority.objects.lifecycle.write",
            "authority.fixture.v2.bind",
            "authority.relation.propose",
            "authority.relation.admit",
            "authority.relation.metadata.read",
            "authority.relation.project",
        }
    )


def authenticator() -> StaticAuthenticator:
    return StaticAuthenticator(
        credentials={"token-1": StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )


def authorizer(
    *, granted_scopes: frozenset[str] | None = None
) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="relation-authz-v1",
        grants_by_principal={
            "principal.alpha": scopes() if granted_scopes is None else granted_scopes
        },
    )


def event_read_policy() -> EventReadPolicy:
    return EventReadPolicy(
        policy_id="relation-authority-events-v1",
        purpose="relation.authority.audit",
        required_scope="authority.fixture.events.read",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        allowed_security_scopes=frozenset(
            {
                "authority.internal",
                "authority.protected",
                "authority.object_lifecycle",
                "authority.projection",
                "authority.integrated",
                "authority.relation",
            }
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED, TrustScope.PROPOSED, TrustScope.ADMITTED}
        ),
        metadata_classes=frozenset(
            {
                MetadataClass.ROUTING,
                MetadataClass.PROVENANCE,
                MetadataClass.RESULT,
            }
        ),
        minimum_ledger_seq=1,
        max_results=1000,
    )


def relation_read_policy() -> RelationReadPolicy:
    return RelationReadPolicy(
        policy_id="relation-projector-v1",
        purpose="relation.projection",
        metadata_required_scope="authority.relation.metadata.read",
        projection_required_scope="authority.relation.project",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=2000,
    )


def base_registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    return registry_v1(), payload_schemas()


def relation_registries() -> tuple[CommandRegistry, PayloadSchemaRegistry]:
    commands, schemas = base_registries()
    return merge_relation_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )


def open_fixture_object_system(
    database: Path,
    *,
    object_root: Path,
    clock: Callable[[], UtcTimestamp] | None = None,
    granted_scopes: frozenset[str] | None = None,
):
    commands, schemas = relation_registries()
    return open_object_system(
        database,
        object_root=object_root,
        scopes=scopes() if granted_scopes is None else granted_scopes,
        authenticator=authenticator(),
        authorizer=authorizer(granted_scopes=granted_scopes),
        clock=clock or (lambda: RELATION_NOW),
        command_registry=commands,
        payload_schema_registry=schemas,
    )


def _seed_fixture_objects_uncached(
    database: Path,
    *,
    object_root: Path,
    clock: Callable[[], UtcTimestamp] | None = None,
    tombstone_negative: bool = True,
) -> SeededFixtureObjects:
    commands, schemas = relation_registries()
    system = open_object_system(
        database,
        object_root=object_root,
        scopes=scopes(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        clock=clock or (lambda: RELATION_NOW),
        command_registry=commands,
        payload_schema_registry=schemas,
    )
    try:
        manifest = admit(
            system,
            data=INTEGRATED_FIXTURE_V2.canonical_bytes,
            key="integrated-fixture-v2-manifest",
        ).admission
        passage_objects: list[FixturePassageObject] = []
        admission_by_passage_id: dict[str, ObjectAdmissionId] = {}
        for passage in INTEGRATED_FIXTURE_V2.passages:
            admission = admit(
                system,
                data=passage.canonical_bytes,
                key=f"integrated-fixture-v2-passage:{passage.passage_id}",
            ).admission
            admission_by_passage_id[passage.passage_id] = admission.admission_id
            passage_objects.append(
                FixturePassageObject(
                    passage_id=passage.passage_id,
                    admission_id=admission.admission_id,
                    blob_digest=passage.blob_digest,
                )
            )
        tombstone_event_id = None
        if tombstone_negative:
            tombstoned = INTEGRATED_FIXTURE_V2.passage_by_id[
                INTEGRATED_FIXTURE_V2.tombstoned_negative_passage_id
            ]
            tombstoned_admission_id = admission_by_passage_id[
                tombstoned.passage_id
            ]
            system.objects.revoke(
                tombstoned_admission_id,
                reason_code="FIXTURE_NEGATIVE_REVOKED",
                idempotency_key="integrated-fixture-v2-negative-revoke",
                proof=proof(),
            )
            deletion = system.objects.request_deletion(
                tombstoned.blob_digest,
                reason_code="FIXTURE_NEGATIVE_DELETE",
                idempotency_key="integrated-fixture-v2-negative-delete",
                proof=proof(),
            )
            tombstone = system.objects.tombstone(
                deletion.deletion_id,
                reason_code="FIXTURE_NEGATIVE_TOMBSTONE",
                idempotency_key="integrated-fixture-v2-negative-tombstone",
                proof=proof(),
            )
            tombstone_event_id = tombstone.event_id
        binding_request = IntegratedFixtureV2BindingRequest(
            binding_id=BINDING_ID,
            fixture_id=INTEGRATED_FIXTURE_V2.fixture_id,
            schema_version=INTEGRATED_FIXTURE_V2.schema_version,
            fixture_digest=INTEGRATED_FIXTURE_V2.manifest_digest,
            manifest_admission_id=manifest.admission_id,
            manifest_blob_digest=manifest.blob.blob_digest,
            passage_objects=sorted_passage_objects(passage_objects),
            idempotency_key="integrated-fixture-v2-binding",
        )
        return SeededFixtureObjects(
            binding_request=binding_request,
            admission_by_passage_id=admission_by_passage_id,
            manifest_admission_id=manifest.admission_id,
            tombstone_event_id=tombstone_event_id,
            commands=commands,
            schemas=schemas,
        )
    finally:
        system.close()


def _seed_template(
    *, tombstone_negative: bool
) -> tuple[Path, Path, SeededFixtureObjects]:
    global _SEED_TEMPLATE_ROOT
    with _SEED_TEMPLATE_LOCK:
        existing = _SEED_TEMPLATES.get(tombstone_negative)
        if existing is not None:
            return existing
        if _SEED_TEMPLATE_ROOT is None:
            _SEED_TEMPLATE_ROOT = Path(
                tempfile.mkdtemp(prefix="newsroom-relation-fixture-")
            )
        template_root = _SEED_TEMPLATE_ROOT / (
            "with-tombstone" if tombstone_negative else "without-tombstone"
        )
        template_root.mkdir(mode=0o700)
        database = template_root / "authority.sqlite3"
        object_root = template_root / "objects"
        seeded = _seed_fixture_objects_uncached(
            database,
            object_root=object_root,
            tombstone_negative=tombstone_negative,
        )
        template = (database, object_root, seeded)
        _SEED_TEMPLATES[tombstone_negative] = template
        return template


def _clone_seed_template(
    database: Path,
    *,
    object_root: Path,
    tombstone_negative: bool,
) -> SeededFixtureObjects:
    template_database, template_objects, seeded = _seed_template(
        tombstone_negative=tombstone_negative
    )
    if database.exists() or database.is_symlink():
        raise FileExistsError(database)
    if object_root.exists() or object_root.is_symlink():
        raise FileExistsError(object_root)
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(template_database, database)
        shutil.copytree(
            template_objects,
            object_root,
            copy_function=shutil.copy2,
        )
    except Exception:
        database.unlink(missing_ok=True)
        shutil.rmtree(object_root, ignore_errors=True)
        raise
    return SeededFixtureObjects(
        binding_request=seeded.binding_request,
        admission_by_passage_id=dict(seeded.admission_by_passage_id),
        manifest_admission_id=seeded.manifest_admission_id,
        tombstone_event_id=seeded.tombstone_event_id,
        commands=seeded.commands,
        schemas=seeded.schemas,
    )


def seed_fixture_objects(
    database: Path,
    *,
    object_root: Path,
    clock: Callable[[], UtcTimestamp] | None = None,
    tombstone_negative: bool = True,
) -> SeededFixtureObjects:
    """Create isolated relation fixture authority with a fast closed-store clone.

    The default deterministic fixture has identical immutable authority in every
    test. Build that authority once per test process, close it, and copy the
    SQLite database plus governed-object directory into each test's private
    ``tmp_path``. Every test still opens and validates its own database and can
    mutate it independently. Tests with a custom clock continue through the
    uncached construction path because their retained chronology is part of the
    scenario under test.
    """

    if clock is not None:
        return _seed_fixture_objects_uncached(
            database,
            object_root=object_root,
            clock=clock,
            tombstone_negative=tombstone_negative,
        )
    return _clone_seed_template(
        database,
        object_root=object_root,
        tombstone_negative=tombstone_negative,
    )


def open_relation_system(
    database: Path,
    *,
    clock: Callable[[], UtcTimestamp] | None = None,
    granted_scopes: frozenset[str] | None = None,
):
    commands, schemas = base_registries()
    return open_governed_relation_authority_system(
        path=database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=authenticator(),
        authorizer=authorizer(granted_scopes=granted_scopes),
        event_read_policy=event_read_policy(),
        relation_read_policy=relation_read_policy(),
        clock=clock or (lambda: RELATION_NOW),
    )


def bind_fixture_and_propose(
    database: Path,
    seeded: SeededFixtureObjects,
    *,
    proposal_id: RelationProposalId = PROPOSAL_ID,
    proposal_key: str = "integrated-fixture-v2-development-proposal",
    clock: Callable[[], UtcTimestamp] | None = None,
) -> RelationProposal:
    system = open_relation_system(database, clock=clock)
    try:
        system.relations.bind_fixture(seeded.binding_request, proof=proof())
        return system.relations.propose(
            INTEGRATED_FIXTURE_V2.relation.request(
                proposal_id=proposal_id,
                fixture_binding_id=BINDING_ID,
                idempotency_key=proposal_key,
            ),
            proof=proof(),
        )
    finally:
        system.close()


def decision_request(
    proposal: RelationProposal,
    *,
    action: RelationDecisionAction,
    expected_version: int = 0,
    previous_decision_id=None,
    successor_proposal_id=None,
    key: str | None = None,
) -> RelationDecisionRequest:
    return RelationDecisionRequest(
        proposal_id=proposal.proposal_id,
        action=action,
        expected_proposal_digest=proposal.proposal_digest,
        expected_decision_version=expected_version,
        expected_previous_decision_id=previous_decision_id,
        reason_code=f"FIXTURE_{action.value}",
        decision_policy_version="relation-admission-policy-v1",
        successor_proposal_id=successor_proposal_id,
        idempotency_key=key or f"relation-decision:{action.value.lower()}:{expected_version}",
    )
