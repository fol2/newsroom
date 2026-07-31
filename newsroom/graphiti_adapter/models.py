from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from newsroom.authority.canonical import (
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
)
from newsroom.authority.objects import ObjectAccessDecisionId
from newsroom.authority.types import EventId, ObjectAdmissionId, UtcTimestamp
from newsroom.extraction.models import (
    ExtractionPassageInput,
    ExtractionUsage,
    ExtractionRunRequest,
    ExtractorContractRequest,
    ProducedExtraction,
    ProposalDraft,
)
from newsroom.extraction.types import (
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputId,
    ExtractionPassageId,
    ExtractionRunId,
    ExtractionRunVersionId,
    ExtractorContractId,
    FixtureExtractionCase,
    ProposalSetId,
    VersionedExtractionComponent,
)
from newsroom.sources import (
    DiscoveryRepresentationId,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceItemId,
    SourceRevisionId,
)

from .types import (
    GraphitiAdapterConfigurationId,
    GraphitiAdapterContractError,
    GraphitiAdapterOutcome,
    GraphitiAttemptId,
    GraphitiCleanupReason,
    GraphitiCleanupReceiptId,
    GraphitiCredentialClass,
    GraphitiEgressPolicy,
    GraphitiExecutionProfile,
    GraphitiInputManifestId,
    GraphitiReplayEligibility,
    GraphitiReplayError,
    GraphitiReplaySourceId,
    GraphitiRuntimeMode,
    GraphitiRuntimeNotAuthorized,
    GraphitiWorkspaceId,
    GraphitiWorkspacePolicyId,
    GraphitiWorkspaceState,
    digest,
    integer,
    reject_private_graph_state,
    text,
    token,
)


REAL_GRAPHITI_RUNTIME_ENABLED = False


@dataclass(frozen=True, slots=True)
class GraphitiWorkspacePolicy:
    policy_id: GraphitiWorkspacePolicyId
    policy_version: str
    namespace_prefix: str
    max_workspace_bytes: int
    max_private_nodes: int
    max_private_relations: int
    egress_policy: GraphitiEgressPolicy
    credential_class: GraphitiCredentialClass
    cleanup_required: bool = True
    persistent_state_allowed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, GraphitiWorkspacePolicyId):
            raise GraphitiAdapterContractError("workspace policy identity must be typed")
        token(self.policy_version, field="graphiti_workspace_policy_version")
        token(self.namespace_prefix, field="graphiti_workspace_namespace_prefix")
        integer(
            self.max_workspace_bytes,
            field="graphiti_workspace_max_bytes",
            minimum=1,
            maximum=256 * 1024 * 1024,
        )
        integer(
            self.max_private_nodes,
            field="graphiti_workspace_max_private_nodes",
            minimum=1,
            maximum=100_000,
        )
        integer(
            self.max_private_relations,
            field="graphiti_workspace_max_private_relations",
            minimum=1,
            maximum=200_000,
        )
        if not isinstance(self.egress_policy, GraphitiEgressPolicy):
            raise GraphitiAdapterContractError("workspace egress policy must be typed")
        if not isinstance(self.credential_class, GraphitiCredentialClass):
            raise GraphitiAdapterContractError("workspace credential class must be typed")
        if self.cleanup_required is not True:
            raise GraphitiAdapterContractError(
                "proposal workspaces must require deterministic cleanup"
            )
        if self.persistent_state_allowed is not False:
            raise GraphitiAdapterContractError(
                "proposal workspace cannot become persistent authority"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "policy_id": str(self.policy_id),
            "policy_version": self.policy_version,
            "namespace_prefix": self.namespace_prefix,
            "max_workspace_bytes": self.max_workspace_bytes,
            "max_private_nodes": self.max_private_nodes,
            "max_private_relations": self.max_private_relations,
            "egress_policy": self.egress_policy.value,
            "credential_class": self.credential_class.value,
            "cleanup_required": self.cleanup_required,
            "persistent_state_allowed": self.persistent_state_allowed,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class RealGraphitiRuntimeAuthority:
    authority_decision_digest: str
    framework_release: str
    model_release: str
    embedding_release: str
    destination_contract_digest: str
    data_processing_terms_digest: str
    prompt_contract_digest: str
    output_schema_contract_digest: str
    permitted_expression_digest: str
    rights_privacy_retention_digest: str
    workspace_security_digest: str
    egress_credential_digest: str
    budget_digest: str
    evaluation_plan_digest: str
    rollback_digest: str

    def __post_init__(self) -> None:
        digest(
            self.authority_decision_digest,
            field="graphiti_runtime_authority_decision_digest",
        )
        token(self.framework_release, field="graphiti_framework_release")
        token(self.model_release, field="graphiti_model_release")
        token(self.embedding_release, field="graphiti_embedding_release")
        for name, value in (
            ("destination_contract_digest", self.destination_contract_digest),
            ("data_processing_terms_digest", self.data_processing_terms_digest),
            ("prompt_contract_digest", self.prompt_contract_digest),
            ("output_schema_contract_digest", self.output_schema_contract_digest),
            ("permitted_expression_digest", self.permitted_expression_digest),
            ("rights_privacy_retention_digest", self.rights_privacy_retention_digest),
            ("workspace_security_digest", self.workspace_security_digest),
            ("egress_credential_digest", self.egress_credential_digest),
            ("budget_digest", self.budget_digest),
            ("evaluation_plan_digest", self.evaluation_plan_digest),
            ("rollback_digest", self.rollback_digest),
        ):
            digest(value, field=f"graphiti_runtime_{name}")

    def canonical_value(self) -> dict[str, str]:
        return {
            "authority_decision_digest": self.authority_decision_digest,
            "framework_release": self.framework_release,
            "model_release": self.model_release,
            "embedding_release": self.embedding_release,
            "destination_contract_digest": self.destination_contract_digest,
            "data_processing_terms_digest": self.data_processing_terms_digest,
            "prompt_contract_digest": self.prompt_contract_digest,
            "output_schema_contract_digest": self.output_schema_contract_digest,
            "permitted_expression_digest": self.permitted_expression_digest,
            "rights_privacy_retention_digest": self.rights_privacy_retention_digest,
            "workspace_security_digest": self.workspace_security_digest,
            "egress_credential_digest": self.egress_credential_digest,
            "budget_digest": self.budget_digest,
            "evaluation_plan_digest": self.evaluation_plan_digest,
            "rollback_digest": self.rollback_digest,
        }


@dataclass(frozen=True, slots=True)
class GraphitiAdapterConfiguration:
    configuration_id: GraphitiAdapterConfigurationId
    runtime_mode: GraphitiRuntimeMode
    execution_profile: GraphitiExecutionProfile
    framework: VersionedExtractionComponent
    model: VersionedExtractionComponent
    embedding: VersionedExtractionComponent
    prompt: VersionedExtractionComponent
    output_schema: VersionedExtractionComponent
    code: VersionedExtractionComponent
    normalisation: VersionedExtractionComponent
    temporal_policy: VersionedExtractionComponent
    adapter_policy: VersionedExtractionComponent
    extractor_contract_id: ExtractorContractId
    extractor_contract_digest: str
    workspace_policy: GraphitiWorkspacePolicy
    fixture_case: FixtureExtractionCase | None
    real_runtime_authority: RealGraphitiRuntimeAuthority | None
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.configuration_id, GraphitiAdapterConfigurationId):
            raise GraphitiAdapterContractError(
                "adapter configuration identity must be typed"
            )
        if not isinstance(self.runtime_mode, GraphitiRuntimeMode):
            raise GraphitiAdapterContractError("adapter runtime mode must be typed")
        if not isinstance(self.execution_profile, GraphitiExecutionProfile):
            raise GraphitiAdapterContractError(
                "adapter execution profile must be typed"
            )
        for name in (
            "framework",
            "model",
            "embedding",
            "prompt",
            "output_schema",
            "code",
            "normalisation",
            "temporal_policy",
            "adapter_policy",
        ):
            if not isinstance(getattr(self, name), VersionedExtractionComponent):
                raise GraphitiAdapterContractError(
                    f"adapter {name} component must be typed"
                )
        if not isinstance(self.extractor_contract_id, ExtractorContractId):
            raise GraphitiAdapterContractError(
                "adapter extractor contract identity must be typed"
            )
        digest(
            self.extractor_contract_digest,
            field="adapter_extractor_contract_digest",
        )
        if not isinstance(self.workspace_policy, GraphitiWorkspacePolicy):
            raise GraphitiAdapterContractError("adapter workspace policy must be typed")
        text(
            self.idempotency_key,
            field="idempotency_key",
            maximum_bytes=256,
        )

        if self.runtime_mode is GraphitiRuntimeMode.DETERMINISTIC_FAKE:
            if self.execution_profile is not GraphitiExecutionProfile.QUALIFICATION:
                raise GraphitiAdapterContractError(
                    "deterministic fake is valid only in qualification profile"
                )
            if not isinstance(self.fixture_case, FixtureExtractionCase):
                raise GraphitiAdapterContractError(
                    "deterministic fake requires an approved fixture case"
                )
            if self.real_runtime_authority is not None:
                raise GraphitiAdapterContractError(
                    "deterministic fake cannot carry real runtime authority"
                )
            self._require_offline_workspace()
        elif self.runtime_mode is GraphitiRuntimeMode.APPROVED_REPLAY:
            if self.execution_profile is not GraphitiExecutionProfile.REPLAY:
                raise GraphitiAdapterContractError(
                    "approved replay is valid only in replay profile"
                )
            if self.fixture_case is not None:
                raise GraphitiAdapterContractError(
                    "approved replay cannot select a fixture producer case"
                )
            if self.real_runtime_authority is not None:
                raise GraphitiAdapterContractError(
                    "approved replay cannot carry real runtime authority"
                )
            self._require_offline_workspace()
        else:
            if self.execution_profile not in {
                GraphitiExecutionProfile.EVALUATION,
                GraphitiExecutionProfile.PRODUCTION,
            }:
                raise GraphitiAdapterContractError(
                    "real Graphiti requires evaluation or production profile"
                )
            if self.fixture_case is not None:
                raise GraphitiAdapterContractError(
                    "real Graphiti cannot use a deterministic fixture case"
                )
            if not isinstance(
                self.real_runtime_authority, RealGraphitiRuntimeAuthority
            ):
                raise GraphitiAdapterContractError(
                    "real Graphiti requires a complete owner runtime authority packet"
                )
            if (
                self.workspace_policy.egress_policy
                is not GraphitiEgressPolicy.APPROVED_PROVIDER_ONLY
                or self.workspace_policy.credential_class
                is not GraphitiCredentialClass.PROPOSAL_WORKSPACE_ONLY
            ):
                raise GraphitiAdapterContractError(
                    "real Graphiti requires isolated provider-only egress and credentials"
                )

    def _require_offline_workspace(self) -> None:
        if (
            self.workspace_policy.egress_policy is not GraphitiEgressPolicy.DENY_ALL
            or self.workspace_policy.credential_class
            is not GraphitiCredentialClass.NONE
        ):
            raise GraphitiAdapterContractError(
                "fake and replay workspaces require deny-all egress and no credentials"
            )

    def require_execution_authorized(self) -> None:
        if self.runtime_mode is GraphitiRuntimeMode.REAL_GRAPHITI:
            if not REAL_GRAPHITI_RUNTIME_ENABLED:
                raise GraphitiRuntimeNotAuthorized(
                    "real Graphiti/model execution remains disabled and unqualified"
                )

    def canonical_value(self) -> dict[str, object]:
        value: dict[str, object] = {
            "configuration_id": str(self.configuration_id),
            "runtime_mode": self.runtime_mode.value,
            "execution_profile": self.execution_profile.value,
            "framework": self.framework.canonical_value(),
            "model": self.model.canonical_value(),
            "embedding": self.embedding.canonical_value(),
            "prompt": self.prompt.canonical_value(),
            "output_schema": self.output_schema.canonical_value(),
            "code": self.code.canonical_value(),
            "normalisation": self.normalisation.canonical_value(),
            "temporal_policy": self.temporal_policy.canonical_value(),
            "adapter_policy": self.adapter_policy.canonical_value(),
            "extractor_contract_id": str(self.extractor_contract_id),
            "extractor_contract_digest": self.extractor_contract_digest,
            "workspace_policy": self.workspace_policy.canonical_value(),
            "fixture_case": None if self.fixture_case is None else self.fixture_case.value,
            "real_runtime_authority": (
                None
                if self.real_runtime_authority is None
                else self.real_runtime_authority.canonical_value()
            ),
        }
        reject_private_graph_state(value)
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        value = self.canonical_value().copy()
        value.pop("configuration_id")
        return digest_canonical(value)


@dataclass(frozen=True, slots=True)
class GraphitiManifestPassage:
    passage_id: ExtractionPassageId
    admission_id: ObjectAdmissionId
    access_decision_id: ObjectAccessDecisionId
    hydration_policy_contract_digest: str
    principal_id: str
    authority_domain: str
    purpose: str
    object_class: str
    allowed_use: str
    security_scope: str
    retention_scope: str
    byte_offset: int
    byte_length: int
    blob_digest: str
    text_digest: str
    language: str

    def __post_init__(self) -> None:
        if not isinstance(self.passage_id, ExtractionPassageId):
            raise GraphitiAdapterContractError("manifest passage identity must be typed")
        if not isinstance(self.admission_id, ObjectAdmissionId):
            raise GraphitiAdapterContractError("manifest admission identity must be typed")
        if not isinstance(self.access_decision_id, ObjectAccessDecisionId):
            raise GraphitiAdapterContractError(
                "manifest access decision identity must be typed"
            )
        digest(
            self.hydration_policy_contract_digest,
            field="manifest_hydration_policy_contract_digest",
        )
        for name, value in (
            ("manifest_principal_id", self.principal_id),
            ("manifest_authority_domain", self.authority_domain),
            ("manifest_purpose", self.purpose),
            ("manifest_object_class", self.object_class),
            ("manifest_allowed_use", self.allowed_use),
        ):
            token(value, field=name)
        text(self.security_scope, field="manifest_security_scope", maximum_bytes=256)
        text(
            self.retention_scope,
            field="manifest_retention_scope",
            maximum_bytes=256,
        )
        integer(
            self.byte_offset,
            field="manifest_byte_offset",
            minimum=0,
            maximum=16 * 1024 * 1024,
        )
        integer(
            self.byte_length,
            field="manifest_byte_length",
            minimum=1,
            maximum=16 * 1024 * 1024,
        )
        digest(self.blob_digest, field="manifest_blob_digest")
        digest(self.text_digest, field="manifest_text_digest")
        text(self.language, field="manifest_language", maximum_bytes=35)
        if self.byte_offset != 0 or self.blob_digest != self.text_digest:
            raise GraphitiAdapterContractError(
                "adapter manifest passage must bind one complete admitted object"
            )

    @classmethod
    def from_extraction(cls, value: ExtractionPassageInput) -> "GraphitiManifestPassage":
        if not isinstance(value, ExtractionPassageInput):
            raise GraphitiAdapterContractError(
                "adapter manifest needs typed extraction passages"
            )
        return cls(
            passage_id=value.passage_id,
            admission_id=value.admission_id,
            access_decision_id=value.access_decision_id,
            hydration_policy_contract_digest=value.hydration_policy_contract_digest,
            principal_id=value.principal_id,
            authority_domain=value.authority_domain,
            purpose=value.purpose,
            object_class=value.object_class,
            allowed_use=value.allowed_use,
            security_scope=value.security_scope,
            retention_scope=value.retention_scope,
            byte_offset=value.byte_offset,
            byte_length=value.byte_length,
            blob_digest=value.blob_digest,
            text_digest=value.text_digest,
            language=value.language,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "passage_id": str(self.passage_id),
            "admission_id": str(self.admission_id),
            "access_decision_id": str(self.access_decision_id),
            "hydration_policy_contract_digest": self.hydration_policy_contract_digest,
            "principal_id": self.principal_id,
            "authority_domain": self.authority_domain,
            "purpose": self.purpose,
            "object_class": self.object_class,
            "allowed_use": self.allowed_use,
            "security_scope": self.security_scope,
            "retention_scope": self.retention_scope,
            "byte_offset": self.byte_offset,
            "byte_length": self.byte_length,
            "blob_digest": self.blob_digest,
            "text_digest": self.text_digest,
            "language": self.language,
        }


@dataclass(frozen=True, slots=True)
class GraphitiInputManifest:
    manifest_id: GraphitiInputManifestId
    configuration_id: GraphitiAdapterConfigurationId
    configuration_digest: str
    extractor_contract_id: ExtractorContractId
    extractor_contract_digest: str
    run_id: ExtractionRunId
    requested_run_version_id: ExtractionRunVersionId
    requested_version_number: int
    definition_id: SourceDefinitionId
    definition_version_id: SourceDefinitionVersionId
    item_id: SourceItemId
    revision_id: SourceRevisionId
    representation_id: DiscoveryRepresentationId
    input_binding_digest: str
    passages: tuple[GraphitiManifestPassage, ...]

    def __post_init__(self) -> None:
        typed = (
            (self.manifest_id, GraphitiInputManifestId, "manifest identity"),
            (
                self.configuration_id,
                GraphitiAdapterConfigurationId,
                "manifest configuration identity",
            ),
            (self.extractor_contract_id, ExtractorContractId, "extractor contract"),
            (self.run_id, ExtractionRunId, "manifest run identity"),
            (
                self.requested_run_version_id,
                ExtractionRunVersionId,
                "manifest requested run version",
            ),
            (self.definition_id, SourceDefinitionId, "manifest definition"),
            (
                self.definition_version_id,
                SourceDefinitionVersionId,
                "manifest definition version",
            ),
            (self.item_id, SourceItemId, "manifest source item"),
            (self.revision_id, SourceRevisionId, "manifest source revision"),
            (
                self.representation_id,
                DiscoveryRepresentationId,
                "manifest representation",
            ),
        )
        for value, expected, label in typed:
            if not isinstance(value, expected):
                raise GraphitiAdapterContractError(f"{label} must be typed")
        digest(self.configuration_digest, field="manifest_configuration_digest")
        digest(
            self.extractor_contract_digest,
            field="manifest_extractor_contract_digest",
        )
        digest(self.input_binding_digest, field="manifest_input_binding_digest")
        integer(
            self.requested_version_number,
            field="manifest_requested_version_number",
            minimum=1,
            maximum=1_000_000,
        )
        if not isinstance(self.passages, tuple) or not self.passages:
            raise GraphitiAdapterContractError("adapter manifest needs exact passages")
        if any(not isinstance(item, GraphitiManifestPassage) for item in self.passages):
            raise GraphitiAdapterContractError("adapter manifest passages must be typed")
        expected = tuple(sorted(self.passages, key=lambda item: str(item.passage_id)))
        if self.passages != expected:
            raise GraphitiAdapterContractError(
                "adapter manifest passages must be sorted by identity"
            )
        if len({item.passage_id for item in self.passages}) != len(self.passages):
            raise GraphitiAdapterContractError(
                "adapter manifest passage identities must be unique"
            )

    @classmethod
    def from_run_request(
        cls,
        *,
        manifest_id: GraphitiInputManifestId,
        configuration: GraphitiAdapterConfiguration,
        contract: ExtractorContractRequest,
        request: ExtractionRunRequest,
    ) -> "GraphitiInputManifest":
        if not isinstance(configuration, GraphitiAdapterConfiguration):
            raise GraphitiAdapterContractError("adapter configuration must be typed")
        if not isinstance(contract, ExtractorContractRequest):
            raise GraphitiAdapterContractError("extractor contract must be typed")
        if not isinstance(request, ExtractionRunRequest):
            raise GraphitiAdapterContractError("extraction request must be typed")
        if configuration.extractor_contract_id != contract.contract_id:
            raise GraphitiAdapterContractError(
                "adapter configuration names a different extractor contract"
            )
        if configuration.extractor_contract_digest != contract.digest:
            raise GraphitiAdapterContractError(
                "adapter configuration extractor contract digest differs"
            )
        if request.contract_id != contract.contract_id:
            raise GraphitiAdapterContractError(
                "adapter request names a different extractor contract"
            )
        binding = request.input_binding
        return cls(
            manifest_id=manifest_id,
            configuration_id=configuration.configuration_id,
            configuration_digest=configuration.canonical_digest,
            extractor_contract_id=contract.contract_id,
            extractor_contract_digest=contract.digest,
            run_id=request.run_id,
            requested_run_version_id=request.run_version_id,
            requested_version_number=request.version_number,
            definition_id=binding.definition_id,
            definition_version_id=binding.definition_version_id,
            item_id=binding.item_id,
            revision_id=binding.revision_id,
            representation_id=binding.representation_id,
            input_binding_digest=binding.digest,
            passages=tuple(
                GraphitiManifestPassage.from_extraction(item)
                for item in binding.passages
            ),
        )

    def canonical_value(self) -> dict[str, object]:
        value = {
            "manifest_id": str(self.manifest_id),
            "configuration_id": str(self.configuration_id),
            "configuration_digest": self.configuration_digest,
            "extractor_contract_id": str(self.extractor_contract_id),
            "extractor_contract_digest": self.extractor_contract_digest,
            "run_id": str(self.run_id),
            "requested_run_version_id": str(self.requested_run_version_id),
            "requested_version_number": self.requested_version_number,
            "definition_id": str(self.definition_id),
            "definition_version_id": str(self.definition_version_id),
            "item_id": str(self.item_id),
            "revision_id": str(self.revision_id),
            "representation_id": str(self.representation_id),
            "input_binding_digest": self.input_binding_digest,
            "passages": [item.canonical_value() for item in self.passages],
        }
        reject_private_graph_state(value)
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class GraphitiWorkspaceDescriptor:
    workspace_id: GraphitiWorkspaceId
    configuration_id: GraphitiAdapterConfigurationId
    policy_id: GraphitiWorkspacePolicyId
    policy_digest: str
    namespace: str
    created_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_id, GraphitiWorkspaceId):
            raise GraphitiAdapterContractError("workspace identity must be typed")
        if not isinstance(self.configuration_id, GraphitiAdapterConfigurationId):
            raise GraphitiAdapterContractError(
                "workspace configuration identity must be typed"
            )
        if not isinstance(self.policy_id, GraphitiWorkspacePolicyId):
            raise GraphitiAdapterContractError("workspace policy identity must be typed")
        digest(self.policy_digest, field="workspace_policy_digest")
        token(self.namespace, field="graphiti_workspace_namespace")
        if not isinstance(self.created_at, UtcTimestamp):
            raise GraphitiAdapterContractError("workspace creation time must be typed")

    def canonical_value(self) -> dict[str, object]:
        return {
            "workspace_id": str(self.workspace_id),
            "configuration_id": str(self.configuration_id),
            "policy_id": str(self.policy_id),
            "policy_digest": self.policy_digest,
            "namespace": self.namespace,
            "created_at": self.created_at.to_text(),
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class GraphitiCleanupReceipt:
    receipt_id: GraphitiCleanupReceiptId
    workspace_id: GraphitiWorkspaceId
    final_state: GraphitiWorkspaceState
    reason: GraphitiCleanupReason
    private_node_count: int
    private_relation_count: int
    file_count: int
    byte_count: int
    workspace_absent: bool
    recorded_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, GraphitiCleanupReceiptId):
            raise GraphitiAdapterContractError("cleanup receipt identity must be typed")
        if not isinstance(self.workspace_id, GraphitiWorkspaceId):
            raise GraphitiAdapterContractError("cleanup workspace identity must be typed")
        if self.final_state not in {
            GraphitiWorkspaceState.CLEANED,
            GraphitiWorkspaceState.LOST,
        }:
            raise GraphitiAdapterContractError(
                "cleanup receipt requires CLEANED or LOST final state"
            )
        if not isinstance(self.reason, GraphitiCleanupReason):
            raise GraphitiAdapterContractError("cleanup reason must be typed")
        for name, value, maximum in (
            ("cleanup_private_node_count", self.private_node_count, 100_000),
            (
                "cleanup_private_relation_count",
                self.private_relation_count,
                200_000,
            ),
            ("cleanup_file_count", self.file_count, 10_000),
            ("cleanup_byte_count", self.byte_count, 256 * 1024 * 1024),
        ):
            integer(value, field=name, minimum=0, maximum=maximum)
        if self.workspace_absent is not True:
            raise GraphitiAdapterContractError(
                "cleanup receipt must prove workspace state is absent"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise GraphitiAdapterContractError("cleanup time must be typed")
        if (
            self.final_state is GraphitiWorkspaceState.LOST
            and self.reason is not GraphitiCleanupReason.SIMULATED_LOSS
        ):
            raise GraphitiAdapterContractError(
                "LOST workspace state requires simulated-loss reason"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "receipt_id": str(self.receipt_id),
            "workspace_id": str(self.workspace_id),
            "final_state": self.final_state.value,
            "reason": self.reason.value,
            "private_node_count": self.private_node_count,
            "private_relation_count": self.private_relation_count,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "workspace_absent": self.workspace_absent,
            "recorded_at": self.recorded_at.to_text(),
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class GraphitiReplaySource:
    replay_source_id: GraphitiReplaySourceId
    source_attempt_id: GraphitiAttemptId
    source_run_version_id: ExtractionRunVersionId
    source_output_id: ExtractionOutputId
    source_proposal_set_id: ProposalSetId | None
    eligibility: GraphitiReplayEligibility
    output_canonical_digest: str
    proposal_set_canonical_digest: str | None
    replay_payload_digest: str
    approval_event_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.replay_source_id, GraphitiReplaySourceId):
            raise GraphitiAdapterContractError("replay source identity must be typed")
        if not isinstance(self.source_attempt_id, GraphitiAttemptId):
            raise GraphitiAdapterContractError("source attempt identity must be typed")
        if not isinstance(self.source_run_version_id, ExtractionRunVersionId):
            raise GraphitiAdapterContractError("source run version must be typed")
        if not isinstance(self.source_output_id, ExtractionOutputId):
            raise GraphitiAdapterContractError("source output identity must be typed")
        if self.source_proposal_set_id is not None and not isinstance(
            self.source_proposal_set_id, ProposalSetId
        ):
            raise GraphitiAdapterContractError("source proposal set must be typed")
        if not isinstance(self.eligibility, GraphitiReplayEligibility):
            raise GraphitiAdapterContractError("replay eligibility must be typed")
        digest(self.output_canonical_digest, field="replay_output_canonical_digest")
        if self.proposal_set_canonical_digest is not None:
            digest(
                self.proposal_set_canonical_digest,
                field="replay_proposal_set_canonical_digest",
            )
        digest(self.replay_payload_digest, field="replay_payload_digest")
        digest(self.approval_event_digest, field="replay_approval_event_digest")
        if self.eligibility is GraphitiReplayEligibility.MALFORMED_OUTPUT:
            if (
                self.source_proposal_set_id is not None
                or self.proposal_set_canonical_digest is not None
            ):
                raise GraphitiAdapterContractError(
                    "malformed-output replay cannot reference a proposal set"
                )
        elif (
            self.source_proposal_set_id is None
            or self.proposal_set_canonical_digest is None
        ):
            raise GraphitiAdapterContractError(
                "complete and partial replay require a retained proposal set"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "replay_source_id": str(self.replay_source_id),
            "source_attempt_id": str(self.source_attempt_id),
            "source_run_version_id": str(self.source_run_version_id),
            "source_output_id": str(self.source_output_id),
            "source_proposal_set_id": (
                None
                if self.source_proposal_set_id is None
                else str(self.source_proposal_set_id)
            ),
            "eligibility": self.eligibility.value,
            "output_canonical_digest": self.output_canonical_digest,
            "proposal_set_canonical_digest": self.proposal_set_canonical_digest,
            "replay_payload_digest": self.replay_payload_digest,
            "approval_event_digest": self.approval_event_digest,
        }

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


@dataclass(frozen=True, slots=True)
class GraphitiReplayApprovalRequest:
    replay_source_id: GraphitiReplaySourceId
    source_attempt_id: GraphitiAttemptId
    source_run_version_id: ExtractionRunVersionId
    source_output_id: ExtractionOutputId
    source_proposal_set_id: ProposalSetId | None
    eligibility: GraphitiReplayEligibility
    expected_output_canonical_digest: str
    expected_proposal_set_canonical_digest: str | None
    expected_replay_payload_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.replay_source_id, GraphitiReplaySourceId):
            raise GraphitiAdapterContractError("replay approval identity must be typed")
        if not isinstance(self.source_attempt_id, GraphitiAttemptId):
            raise GraphitiAdapterContractError("replay approval attempt must be typed")
        if not isinstance(self.source_run_version_id, ExtractionRunVersionId):
            raise GraphitiAdapterContractError("replay approval run version must be typed")
        if not isinstance(self.source_output_id, ExtractionOutputId):
            raise GraphitiAdapterContractError("replay approval output must be typed")
        if self.source_proposal_set_id is not None and not isinstance(
            self.source_proposal_set_id, ProposalSetId
        ):
            raise GraphitiAdapterContractError(
                "replay approval proposal set must be typed"
            )
        if not isinstance(self.eligibility, GraphitiReplayEligibility):
            raise GraphitiAdapterContractError(
                "replay approval eligibility must be typed"
            )
        digest(
            self.expected_output_canonical_digest,
            field="replay_approval_output_canonical_digest",
        )
        if self.expected_proposal_set_canonical_digest is not None:
            digest(
                self.expected_proposal_set_canonical_digest,
                field="replay_approval_proposal_set_canonical_digest",
            )
        digest(
            self.expected_replay_payload_digest,
            field="replay_approval_payload_digest",
        )
        text(self.idempotency_key, field="idempotency_key", maximum_bytes=256)
        if self.eligibility is GraphitiReplayEligibility.MALFORMED_OUTPUT:
            if (
                self.source_proposal_set_id is not None
                or self.expected_proposal_set_canonical_digest is not None
            ):
                raise GraphitiAdapterContractError(
                    "malformed replay approval cannot name a proposal set"
                )
        elif (
            self.source_proposal_set_id is None
            or self.expected_proposal_set_canonical_digest is None
        ):
            raise GraphitiAdapterContractError(
                "complete and partial replay approval require a proposal set"
            )

    def canonical_value(self) -> dict[str, object]:
        return {
            "replay_source_id": str(self.replay_source_id),
            "source_attempt_id": str(self.source_attempt_id),
            "source_run_version_id": str(self.source_run_version_id),
            "source_output_id": str(self.source_output_id),
            "source_proposal_set_id": (
                None
                if self.source_proposal_set_id is None
                else str(self.source_proposal_set_id)
            ),
            "eligibility": self.eligibility.value,
            "expected_output_canonical_digest": (
                self.expected_output_canonical_digest
            ),
            "expected_proposal_set_canonical_digest": (
                self.expected_proposal_set_canonical_digest
            ),
            "expected_replay_payload_digest": self.expected_replay_payload_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class GraphitiAdapterConfigurationRecord:
    configuration: GraphitiAdapterConfiguration
    authority_event_id: EventId
    aggregate_version: int
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, GraphitiAdapterConfiguration):
            raise GraphitiAdapterContractError(
                "retained adapter configuration must be typed"
            )
        if not isinstance(self.authority_event_id, EventId):
            raise GraphitiAdapterContractError(
                "configuration authority event must be typed"
            )
        if self.aggregate_version != 1:
            raise GraphitiAdapterContractError(
                "adapter configuration authority is immutable"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise GraphitiAdapterContractError(
                "configuration recording time must be typed"
            )
        if not isinstance(self.replayed, bool):
            raise GraphitiAdapterContractError(
                "configuration replay flag must be boolean"
            )


@dataclass(frozen=True, slots=True)
class GraphitiAttemptRecord:
    attempt_id: GraphitiAttemptId
    run_id: ExtractionRunId
    run_version_id: ExtractionRunVersionId
    attempt_number: int
    previous_attempt_id: GraphitiAttemptId | None
    configuration_id: GraphitiAdapterConfigurationId
    configuration_digest: str
    workspace_id: GraphitiWorkspaceId
    manifest_id: GraphitiInputManifestId
    outcome: GraphitiAdapterOutcome
    failure_code: str
    started_at: UtcTimestamp
    ended_at: UtcTimestamp
    usage: ExtractionUsage
    output_id: ExtractionOutputId | None
    proposal_set_id: ProposalSetId | None
    cleanup_receipt: GraphitiCleanupReceipt
    authority_event_id: EventId
    recorded_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        typed = (
            (self.attempt_id, GraphitiAttemptId, "attempt identity"),
            (self.run_id, ExtractionRunId, "attempt run"),
            (self.run_version_id, ExtractionRunVersionId, "attempt run version"),
            (
                self.configuration_id,
                GraphitiAdapterConfigurationId,
                "attempt configuration",
            ),
            (self.workspace_id, GraphitiWorkspaceId, "attempt workspace"),
            (self.manifest_id, GraphitiInputManifestId, "attempt manifest"),
            (self.authority_event_id, EventId, "attempt authority event"),
        )
        for value, expected, label in typed:
            if not isinstance(value, expected):
                raise GraphitiAdapterContractError(f"{label} must be typed")
        integer(
            self.attempt_number,
            field="retained_graphiti_attempt_number",
            minimum=1,
            maximum=1_000_000,
        )
        if self.previous_attempt_id is not None and not isinstance(
            self.previous_attempt_id, GraphitiAttemptId
        ):
            raise GraphitiAdapterContractError(
                "retained previous attempt identity must be typed"
            )
        digest(self.configuration_digest, field="retained_configuration_digest")
        if not isinstance(self.outcome, GraphitiAdapterOutcome):
            raise GraphitiAdapterContractError("retained adapter outcome must be typed")
        token(self.failure_code, field="retained_adapter_failure_code")
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.ended_at, UtcTimestamp
        ):
            raise GraphitiAdapterContractError("retained attempt times must be typed")
        if self.started_at.value > self.ended_at.value:
            raise GraphitiAdapterContractError(
                "retained adapter attempt cannot end before it starts"
            )
        if not isinstance(self.usage, ExtractionUsage):
            raise GraphitiAdapterContractError("retained adapter usage must be typed")
        if self.output_id is not None and not isinstance(
            self.output_id, ExtractionOutputId
        ):
            raise GraphitiAdapterContractError("retained output identity must be typed")
        if self.proposal_set_id is not None and not isinstance(
            self.proposal_set_id, ProposalSetId
        ):
            raise GraphitiAdapterContractError(
                "retained proposal set identity must be typed"
            )
        if not isinstance(self.cleanup_receipt, GraphitiCleanupReceipt):
            raise GraphitiAdapterContractError(
                "retained cleanup receipt must be typed"
            )
        if self.cleanup_receipt.workspace_id != self.workspace_id:
            raise GraphitiAdapterContractError(
                "retained cleanup receipt names a different workspace"
            )
        if not isinstance(self.recorded_at, UtcTimestamp):
            raise GraphitiAdapterContractError(
                "retained attempt recording time must be typed"
            )
        if self.recorded_at.value < self.ended_at.value:
            raise GraphitiAdapterContractError(
                "adapter attempt must be recorded after execution"
            )
        if self.outcome.may_reference_output != (self.output_id is not None):
            raise GraphitiAdapterContractError(
                "retained adapter output authority differs from outcome"
            )
        if self.outcome.may_reference_proposals != (
            self.proposal_set_id is not None
        ):
            if not (
                self.outcome is GraphitiAdapterOutcome.PARTIAL
                and self.proposal_set_id is None
            ):
                raise GraphitiAdapterContractError(
                    "retained adapter proposal authority differs from outcome"
                )
        if not isinstance(self.replayed, bool):
            raise GraphitiAdapterContractError(
                "retained attempt replay flag must be boolean"
            )

    @property
    def terminal(self) -> bool:
        return self.outcome.terminal


@dataclass(frozen=True, slots=True)
class GraphitiReplaySourceRecord:
    source: GraphitiReplaySource
    authority_event_id: EventId
    aggregate_version: int
    approved_at: UtcTimestamp
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source, GraphitiReplaySource):
            raise GraphitiAdapterContractError(
                "retained replay source must be typed"
            )
        if not isinstance(self.authority_event_id, EventId):
            raise GraphitiAdapterContractError(
                "replay approval event must be typed"
            )
        if self.aggregate_version != 1:
            raise GraphitiAdapterContractError("replay approval authority is immutable")
        if not isinstance(self.approved_at, UtcTimestamp):
            raise GraphitiAdapterContractError("replay approval time must be typed")
        if not isinstance(self.replayed, bool):
            raise GraphitiAdapterContractError(
                "replay approval replay flag must be boolean"
            )


@dataclass(frozen=True, slots=True)
class ApprovedReplayBundle:
    source: GraphitiReplaySource
    produced: ProducedExtraction = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.source, GraphitiReplaySource):
            raise GraphitiAdapterContractError("replay source must be typed")
        if not isinstance(self.produced, ProducedExtraction):
            raise GraphitiAdapterContractError("replay produced value must be typed")
        eligibility = {
            ExtractionOutcome.SUCCESS: GraphitiReplayEligibility.COMPLETE,
            ExtractionOutcome.PARTIAL: GraphitiReplayEligibility.PARTIAL,
            ExtractionOutcome.INVALID_OUTPUT: GraphitiReplayEligibility.MALFORMED_OUTPUT,
        }.get(self.produced.outcome)
        if eligibility is None or eligibility is not self.source.eligibility:
            raise GraphitiReplayError(
                "replay source outcome is not eligible or differs from retained output"
            )
        if self.produced.raw_output_digest != self.source.output_canonical_digest:
            raise GraphitiReplayError(
                "approved replay output digest differs from retained authority"
            )
        payload_digest = digest_canonical(
            {
                "outcome": self.produced.outcome.value,
                "failure_code": self.produced.failure_code.value,
                "validation": (
                    None
                    if self.produced.validation is None
                    else self.produced.validation.value
                ),
                "raw_output_digest": self.produced.raw_output_digest,
                "proposals": [item.canonical_value() for item in self.produced.proposals],
                "usage": self.produced.usage.canonical_value(),
            }
        )
        if payload_digest != self.source.replay_payload_digest:
            raise GraphitiReplayError(
                "approved replay payload digest differs from retained authority"
            )


@dataclass(frozen=True, slots=True)
class GraphitiAttemptRequest:
    attempt_id: GraphitiAttemptId
    attempt_number: int
    expected_previous_attempt_id: GraphitiAttemptId | None
    configuration: GraphitiAdapterConfiguration
    workspace_id: GraphitiWorkspaceId
    cleanup_receipt_id: GraphitiCleanupReceiptId
    manifest: GraphitiInputManifest
    extraction_contract: ExtractorContractRequest
    extraction_request: ExtractionRunRequest
    replay_source: GraphitiReplaySource | None
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_id, GraphitiAttemptId):
            raise GraphitiAdapterContractError("adapter attempt identity must be typed")
        integer(
            self.attempt_number,
            field="graphiti_attempt_number",
            minimum=1,
            maximum=1_000_000,
        )
        if self.expected_previous_attempt_id is not None and not isinstance(
            self.expected_previous_attempt_id, GraphitiAttemptId
        ):
            raise GraphitiAdapterContractError(
                "previous adapter attempt identity must be typed"
            )
        if self.attempt_number == 1:
            if self.expected_previous_attempt_id is not None:
                raise GraphitiAdapterContractError(
                    "initial adapter attempt cannot name a predecessor"
                )
        elif self.expected_previous_attempt_id is None:
            raise GraphitiAdapterContractError(
                "later adapter attempt requires the exact predecessor"
            )
        if not isinstance(self.configuration, GraphitiAdapterConfiguration):
            raise GraphitiAdapterContractError("attempt configuration must be typed")
        if not isinstance(self.workspace_id, GraphitiWorkspaceId):
            raise GraphitiAdapterContractError("attempt workspace identity must be typed")
        if not isinstance(self.cleanup_receipt_id, GraphitiCleanupReceiptId):
            raise GraphitiAdapterContractError(
                "attempt cleanup receipt identity must be typed"
            )
        if not isinstance(self.manifest, GraphitiInputManifest):
            raise GraphitiAdapterContractError("attempt manifest must be typed")
        if not isinstance(self.extraction_contract, ExtractorContractRequest):
            raise GraphitiAdapterContractError("attempt extractor contract must be typed")
        if not isinstance(self.extraction_request, ExtractionRunRequest):
            raise GraphitiAdapterContractError("attempt extraction request must be typed")
        text(self.idempotency_key, field="idempotency_key", maximum_bytes=256)
        if self.manifest.configuration_id != self.configuration.configuration_id:
            raise GraphitiAdapterContractError(
                "attempt manifest names a different configuration"
            )
        if self.manifest.configuration_digest != self.configuration.canonical_digest:
            raise GraphitiAdapterContractError(
                "attempt manifest configuration digest differs"
            )
        if self.manifest.requested_run_version_id != self.extraction_request.run_version_id:
            raise GraphitiAdapterContractError(
                "attempt manifest names a different requested run version"
            )
        if self.extraction_contract.contract_id != self.configuration.extractor_contract_id:
            raise GraphitiAdapterContractError(
                "attempt extractor contract differs from adapter configuration"
            )
        if self.extraction_contract.digest != self.configuration.extractor_contract_digest:
            raise GraphitiAdapterContractError(
                "attempt extractor contract digest differs from adapter configuration"
            )
        if self.configuration.runtime_mode is GraphitiRuntimeMode.APPROVED_REPLAY:
            if not isinstance(self.replay_source, GraphitiReplaySource):
                raise GraphitiAdapterContractError(
                    "approved replay attempt requires exact replay source authority"
                )
        elif self.replay_source is not None:
            raise GraphitiAdapterContractError(
                "only approved replay attempts can name replay source authority"
            )

    def canonical_value(self) -> dict[str, object]:
        value = {
            "attempt_id": str(self.attempt_id),
            "attempt_number": self.attempt_number,
            "expected_previous_attempt_id": (
                None
                if self.expected_previous_attempt_id is None
                else str(self.expected_previous_attempt_id)
            ),
            "configuration_id": str(self.configuration.configuration_id),
            "configuration_digest": self.configuration.canonical_digest,
            "workspace_id": str(self.workspace_id),
            "cleanup_receipt_id": str(self.cleanup_receipt_id),
            "manifest_id": str(self.manifest.manifest_id),
            "manifest_digest": self.manifest.canonical_digest,
            "extractor_contract_id": str(self.extraction_contract.contract_id),
            "extractor_contract_digest": self.extraction_contract.digest,
            "run_id": str(self.extraction_request.run_id),
            "requested_run_version_id": str(self.extraction_request.run_version_id),
            "requested_version_number": self.extraction_request.version_number,
            "replay_source_id": (
                None
                if self.replay_source is None
                else str(self.replay_source.replay_source_id)
            ),
            "replay_source_digest": (
                None
                if self.replay_source is None
                else self.replay_source.canonical_digest
            ),
        }
        reject_private_graph_state(value)
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def canonical_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class GraphitiAdapterExecution:
    attempt: GraphitiAttemptRequest
    outcome: GraphitiAdapterOutcome
    failure_code: str
    produced: ProducedExtraction = field(repr=False)
    workspace: GraphitiWorkspaceDescriptor = field(repr=False)
    cleanup_receipt: GraphitiCleanupReceipt
    started_at: UtcTimestamp
    ended_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, GraphitiAttemptRequest):
            raise GraphitiAdapterContractError("adapter execution attempt must be typed")
        if not isinstance(self.outcome, GraphitiAdapterOutcome):
            raise GraphitiAdapterContractError("adapter execution outcome must be typed")
        token(self.failure_code, field="graphiti_adapter_failure_code")
        if not isinstance(self.produced, ProducedExtraction):
            raise GraphitiAdapterContractError("adapter produced extraction must be typed")
        if not isinstance(self.workspace, GraphitiWorkspaceDescriptor):
            raise GraphitiAdapterContractError("adapter workspace must be typed")
        if not isinstance(self.cleanup_receipt, GraphitiCleanupReceipt):
            raise GraphitiAdapterContractError("adapter cleanup receipt must be typed")
        if self.workspace.workspace_id != self.attempt.workspace_id:
            raise GraphitiAdapterContractError(
                "adapter execution workspace differs from attempt"
            )
        if self.cleanup_receipt.workspace_id != self.workspace.workspace_id:
            raise GraphitiAdapterContractError(
                "adapter cleanup receipt names a different workspace"
            )
        if not isinstance(self.started_at, UtcTimestamp) or not isinstance(
            self.ended_at, UtcTimestamp
        ):
            raise GraphitiAdapterContractError("adapter execution times must be typed")
        if self.started_at.value > self.ended_at.value:
            raise GraphitiAdapterContractError(
                "adapter execution cannot end before it starts"
            )
        if self.outcome.may_reference_proposals != bool(self.produced.proposals):
            if self.outcome is GraphitiAdapterOutcome.PARTIAL and not self.produced.proposals:
                pass
            else:
                raise GraphitiAdapterContractError(
                    "adapter outcome proposal authority differs from produced extraction"
                )
        expected = adapter_outcome_for(self.produced)
        if expected is not self.outcome:
            raise GraphitiAdapterContractError(
                "adapter outcome differs from the extraction bridge result"
            )

    def canonical_value(self) -> dict[str, object]:
        value = {
            "attempt_id": str(self.attempt.attempt_id),
            "attempt_digest": self.attempt.canonical_digest,
            "outcome": self.outcome.value,
            "failure_code": self.failure_code,
            "produced_outcome": self.produced.outcome.value,
            "produced_failure_code": self.produced.failure_code.value,
            "usage": self.produced.usage.canonical_value(),
            "workspace_id": str(self.workspace.workspace_id),
            "workspace_digest": self.workspace.canonical_digest,
            "cleanup_receipt_id": str(self.cleanup_receipt.receipt_id),
            "cleanup_receipt_digest": self.cleanup_receipt.canonical_digest,
            "started_at": self.started_at.to_text(),
            "ended_at": self.ended_at.to_text(),
        }
        reject_private_graph_state(value)
        return value

    @property
    def canonical_digest(self) -> str:
        return digest_canonical(self.canonical_value())


def adapter_outcome_for(produced: ProducedExtraction) -> GraphitiAdapterOutcome:
    if not isinstance(produced, ProducedExtraction):
        raise GraphitiAdapterContractError("adapter bridge requires typed extraction")
    if produced.outcome is ExtractionOutcome.SUCCESS:
        return GraphitiAdapterOutcome.COMPLETE
    if produced.outcome is ExtractionOutcome.PARTIAL:
        return GraphitiAdapterOutcome.PARTIAL
    if produced.outcome is ExtractionOutcome.INVALID_OUTPUT:
        return GraphitiAdapterOutcome.MALFORMED_OUTPUT
    if produced.outcome is ExtractionOutcome.RETRYABLE_FAILURE:
        if produced.failure_code is ExtractionFailureCode.EXECUTION_TIMEOUT:
            return GraphitiAdapterOutcome.TIMEOUT
        return GraphitiAdapterOutcome.FAILED
    if produced.failure_code is ExtractionFailureCode.POLICY_BLOCKED:
        return GraphitiAdapterOutcome.POLICY_BLOCKED
    if produced.failure_code is ExtractionFailureCode.FIXTURE_BLOCKED:
        return GraphitiAdapterOutcome.PROVIDER_REJECTED
    return GraphitiAdapterOutcome.FAILED


class ProposalOnlyGraphitiAdapter(Protocol):
    def execute(
        self,
        *,
        attempt: GraphitiAttemptRequest,
        workspace_root: object,
    ) -> GraphitiAdapterExecution:
        ...


__all__ = [
    "ApprovedReplayBundle",
    "GraphitiAdapterConfiguration",
    "GraphitiAdapterConfigurationRecord",
    "GraphitiAdapterExecution",
    "GraphitiAttemptRecord",
    "GraphitiAttemptRequest",
    "GraphitiCleanupReceipt",
    "GraphitiInputManifest",
    "GraphitiManifestPassage",
    "GraphitiReplayApprovalRequest",
    "GraphitiReplaySource",
    "GraphitiReplaySourceRecord",
    "GraphitiWorkspaceDescriptor",
    "GraphitiWorkspacePolicy",
    "ProposalOnlyGraphitiAdapter",
    "REAL_GRAPHITI_RUNTIME_ENABLED",
    "RealGraphitiRuntimeAuthority",
    "adapter_outcome_for",
]
