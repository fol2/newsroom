from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from newsroom.authority import (
    AuthenticationProof,
    HydrationRequest,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
    UtcTimestamp,
)
from newsroom.authority.extraction_system import (
    open_governed_extraction_authority_system,
)
from newsroom.extraction import (
    ExtractionBudget,
    ExtractionInputBinding,
    ExtractionPassageId,
    ExtractionPassageInput,
    ExtractionReadPolicy,
    ExtractionRunId,
    ExtractionRunRequest,
    ExtractionRunVersionId,
    ExtractorContractId,
    FixtureExtractionCase,
    deterministic_fixture_contract_request,
)
from newsroom.sources.policy import merge_source_registry_authority_registries
from newsroom.authority.object_policy import merge_authority_registries

from .authority_a2b_helpers import admit, open_object_system
from .source_3a_helpers import (
    DEFINITION_ID,
    ITEM_ID,
    REPRESENTATION_1_ID,
    REVISION_1_ID,
    SOURCE_NOW,
    VERSION_1_ID,
    VERSION_2_ID,
    base_registries,
    definition_request,
    item_request,
    locator_decision_request,
    open_source_system,
    proof,
    representation_request,
    revision_request,
    version_request,
)

CONTRACT_ID = ExtractorContractId.parse(
    "00000000-0000-4000-8000-000000004101"
)
RUN_ID = ExtractionRunId.parse("00000000-0000-4000-8000-000000004102")
RUN_VERSION_1_ID = ExtractionRunVersionId.parse(
    "00000000-0000-4000-8000-000000004103"
)
RUN_VERSION_2_ID = ExtractionRunVersionId.parse(
    "00000000-0000-4000-8000-000000004104"
)
EN_PASSAGE_ID = ExtractionPassageId.parse(
    "00000000-0000-4000-8000-000000004105"
)
ZH_PASSAGE_ID = ExtractionPassageId.parse(
    "00000000-0000-4000-8000-000000004106"
)


@dataclass(frozen=True, slots=True)
class ExtractionFixtureState:
    database: Path
    object_root: Path
    commands: object
    schemas: object
    input_binding: ExtractionInputBinding


def extraction_proof() -> AuthenticationProof:
    return AuthenticationProof(method="STATIC_TOKEN", credential="token-1")


def extraction_scopes() -> frozenset[str]:
    return frozenset(
        {
            "authority.extraction.manage",
            "authority.extraction.execute",
            "authority.extraction.read",
            "authority.extraction.read_proposals",
            "authority.extraction.read_raw",
        }
    )


def extraction_authenticator() -> StaticAuthenticator:
    return StaticAuthenticator(
        credentials={"token-1": StaticPrincipal("principal.alpha")},
        authority_domain="newsroom.authority",
    )


def extraction_authorizer(
    *, granted_scopes: frozenset[str] | None = None
) -> StaticAuthorizer:
    return StaticAuthorizer(
        policy_version="extraction-authority-authz-v1",
        grants_by_principal={
            "principal.alpha": (
                extraction_scopes()
                if granted_scopes is None
                else granted_scopes
            )
        },
    )


def extraction_read_policy() -> ExtractionReadPolicy:
    return ExtractionReadPolicy(
        policy_id="increment-4a-extraction-read-v1",
        purpose="extraction.authority.audit",
        metadata_required_scope="authority.extraction.read",
        proposal_required_scope="authority.extraction.read_proposals",
        raw_output_required_scope="authority.extraction.read_raw",
        allowed_principal_ids=frozenset({"principal.alpha"}),
        max_results=100,
    )


def _seed_source(database: Path) -> None:
    system = open_source_system(database, clock=lambda: SOURCE_NOW)
    try:
        system.sources.register_definition(definition_request(), proof=proof())
        system.sources.record_definition_version(
            version_request(), proof=proof()
        )
        system.sources.register_item(item_request(), proof=proof())
        system.sources.record_definition_version(
            version_request(
                version_id=VERSION_2_ID,
                version_number=2,
                previous_version_id=VERSION_1_ID,
                locator="fixture://increment-3a/maintained-guidance-v2",
                key="source-definition-version-v2",
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
    finally:
        system.close()


def seed_extraction_fixture(root: Path) -> ExtractionFixtureState:
    database = root / "authority.sqlite3"
    object_root = root / "objects"
    _seed_source(database)
    base_commands, base_schemas = base_registries()
    source_commands, source_schemas = merge_source_registry_authority_registries(
        command_registry=base_commands,
        payload_schemas=base_schemas,
    )
    object_commands, object_schemas = merge_authority_registries(
        command_registry=source_commands,
        payload_schemas=source_schemas,
    )

    from newsroom.extraction import (
        FIXTURE_EN_TEXT,
        FIXTURE_ZH_HK_TEXT,
    )

    object_system = open_object_system(
        database,
        object_root=object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=object_commands,
        payload_schema_registry=object_schemas,
    )
    try:
        en_data = FIXTURE_EN_TEXT.encode("utf-8")
        zh_data = FIXTURE_ZH_HK_TEXT.encode("utf-8")
        en_admission = admit(
            object_system,
            data=en_data,
            key="increment-4a-admit-en",
        ).admission
        zh_admission = admit(
            object_system,
            data=zh_data,
            key="increment-4a-admit-zh-hk",
        ).admission
        en_hydrated = object_system.objects.hydrate(
            HydrationRequest(
                en_admission.admission_id,
                "project.discovery",
            ),
            proof=proof(),
        )
        zh_hydrated = object_system.objects.hydrate(
            HydrationRequest(
                zh_admission.admission_id,
                "project.discovery",
            ),
            proof=proof(),
        )
    finally:
        object_system.close()

    def passage(passage_id, admission, hydrated, language: str):
        decision = hydrated.decision
        return ExtractionPassageInput(
            passage_id=passage_id,
            admission_id=admission.admission_id,
            access_decision_id=decision.access_decision_id,
            hydration_policy_contract_digest=decision.policy_contract_digest,
            principal_id=decision.principal_id,
            authority_domain=decision.authority_domain,
            purpose=decision.purpose,
            object_class=decision.object_class,
            allowed_use=decision.allowed_use,
            security_scope=decision.security_scope,
            retention_scope=decision.retention_scope,
            byte_offset=decision.offset,
            byte_length=decision.allowed_bytes,
            blob_digest=admission.blob.blob_digest,
            text_digest=admission.blob.blob_digest,
            language=language,
            text=hydrated.data.decode("utf-8"),
        )

    binding = ExtractionInputBinding(
        definition_id=DEFINITION_ID,
        definition_version_id=VERSION_2_ID,
        item_id=ITEM_ID,
        revision_id=REVISION_1_ID,
        representation_id=REPRESENTATION_1_ID,
        passages=tuple(
            sorted(
                (
                    passage(EN_PASSAGE_ID, en_admission, en_hydrated, "en-GB"),
                    passage(ZH_PASSAGE_ID, zh_admission, zh_hydrated, "zh-HK"),
                ),
                key=lambda item: str(item.passage_id),
            )
        ),
    )
    return ExtractionFixtureState(
        database=database,
        object_root=object_root,
        commands=object_commands,
        schemas=object_schemas,
        input_binding=binding,
    )


def contract_request(
    *,
    contract_id: ExtractorContractId = CONTRACT_ID,
    fixture_case: FixtureExtractionCase = FixtureExtractionCase.BILINGUAL_COMPLETE,
    key: str = "increment-4a-contract-v1",
):
    return deterministic_fixture_contract_request(
        contract_id=contract_id,
        fixture_case=fixture_case,
        idempotency_key=key,
    )


def run_request(
    state: ExtractionFixtureState,
    *,
    run_id: ExtractionRunId = RUN_ID,
    run_version_id: ExtractionRunVersionId = RUN_VERSION_1_ID,
    version_number: int = 1,
    previous: ExtractionRunVersionId | None = None,
    contract_id: ExtractorContractId = CONTRACT_ID,
    key: str = "increment-4a-run-v1",
) -> ExtractionRunRequest:
    return ExtractionRunRequest(
        run_id=run_id,
        run_version_id=run_version_id,
        version_number=version_number,
        expected_previous_version_id=previous,
        contract_id=contract_id,
        input_binding=state.input_binding,
        budget=ExtractionBudget(
            timeout_ms=10_000,
            max_input_bytes=64 * 1024,
            max_output_bytes=256 * 1024,
            max_proposals=100,
            max_evidence_ranges=500,
            max_request_tokens=0,
            max_response_tokens=0,
            max_cost_microunits=0,
        ),
        idempotency_key=key,
    )


def open_extraction_system(
    state: ExtractionFixtureState,
    *,
    granted_scopes: frozenset[str] | None = None,
    clock=SOURCE_NOW,
):
    selected_clock = (lambda: clock) if isinstance(clock, UtcTimestamp) else clock
    return open_governed_extraction_authority_system(
        path=state.database,
        registry=state.commands,
        payload_schemas=state.schemas,
        authenticator=extraction_authenticator(),
        authorizer=extraction_authorizer(granted_scopes=granted_scopes),
        read_policy=extraction_read_policy(),
        clock=selected_clock,
    )
