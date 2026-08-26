"""Owner authority, production admission sealing, minting and verification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._shared import (
    AuthenticationKey,
    FreezeIdentity,
    KeyClass,
    KeyProvenance,
    ProductionAdmissionError,
    _canonical_document,
    _digest,
    _git_sha,
    _seal,
    _timestamp,
    _token,
    _verify_seal,
)
from .evidence import GateAttestation, ProductionEvidenceManifest
from .identities import (
    PRODUCTION_GATE_IDS,
    BoundArtifactRole,
    IdentityClass,
    _publication_spec_digests,
)
from .owner import (
    OwnerAdmissionInstruction,
    OwnerIssueRecord,
    _verify_owner_instruction_binding,
)
from .readiness import ProductionReadinessReport, inspect_readiness


class ProductionAdmissionVerdict(StrEnum):
    PRODUCTION_OPERATIONAL_ADMITTED = "PRODUCTION_OPERATIONAL_ADMITTED"


def _canonical_digest_mapping(
    value: object, field: str, *, expected_keys: set[str]
) -> Mapping[str, str]:
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ProductionAdmissionError(f"{field} inventory differs")
    return MappingProxyType(
        {name: _digest(value[name], f"{field}.{name}") for name in sorted(value)}
    )


@dataclass(frozen=True, slots=True)
class _AdmissionEvidenceBinding:
    freeze: FreezeIdentity
    operational_manifest_digest: str
    identity_set_digest: str
    deployment_bytes_digest: str
    evidence_manifest_digest: str
    readiness_report_digest: str
    identity_digests: Mapping[str, str]
    identity_evaluation_evidence_digests: Mapping[str, str]
    gate_attestation_digests: Mapping[str, str]
    bound_evidence_digests: Mapping[str, str]
    accepted_publication_spec_digests: Mapping[str, str]
    fixture_admission_digest: str
    owner_instruction_id: str
    owner_instruction_digest: str
    authority_issue_snapshot_digest: str
    authority_issue_number: int
    authority_issue_url: str
    issuer_identity: str
    issued_at: str

    @classmethod
    def from_authority(
        cls,
        *,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        owner_instruction: OwnerAdmissionInstruction,
    ) -> _AdmissionEvidenceBinding:
        gate_evidence = {
            result.gate_id.value: result.evidence_digest for result in report.gates
        }
        if not report.ready_for_admission or any(
            item is None for item in gate_evidence.values()
        ):
            raise ProductionAdmissionError("ready report gate evidence differs")
        return cls(
            freeze=report.freeze,
            operational_manifest_digest=(
                evidence_manifest.identity_set.operational_manifest_digest
            ),
            identity_set_digest=evidence_manifest.identity_set.digest,
            deployment_bytes_digest=(
                evidence_manifest.identity_set.deployment_bytes_digest
            ),
            evidence_manifest_digest=evidence_manifest.digest,
            readiness_report_digest=report.digest,
            identity_digests=MappingProxyType(
                {
                    item.identity_class.value: item.identity_digest
                    for item in evidence_manifest.identity_set.identities
                }
            ),
            identity_evaluation_evidence_digests=MappingProxyType(
                {
                    item.identity_class.value: item.evaluation_evidence_digest
                    for item in evidence_manifest.identity_set.identities
                }
            ),
            gate_attestation_digests=MappingProxyType(
                {name: str(digest) for name, digest in gate_evidence.items()}
            ),
            bound_evidence_digests=MappingProxyType(
                {
                    item.role.value: item.artifact_digest
                    for item in evidence_manifest.bound_artifacts
                }
            ),
            accepted_publication_spec_digests=(
                evidence_manifest.accepted_publication_spec_digests
            ),
            fixture_admission_digest=evidence_manifest.fixture_admission_digest,
            owner_instruction_id=owner_instruction.instruction_id,
            owner_instruction_digest=owner_instruction.digest,
            authority_issue_snapshot_digest=(
                owner_instruction.authority_issue_snapshot.digest
            ),
            authority_issue_number=owner_instruction.authority_issue_number,
            authority_issue_url=owner_instruction.authority_issue_url,
            issuer_identity=owner_instruction.owner_identity,
            issued_at=owner_instruction.issued_at,
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            **self.freeze.canonical_value(),
            "operational_manifest_digest": self.operational_manifest_digest,
            "identity_set_digest": self.identity_set_digest,
            "deployment_bytes_digest": self.deployment_bytes_digest,
            "evidence_manifest_digest": self.evidence_manifest_digest,
            "readiness_report_digest": self.readiness_report_digest,
            "identity_digests": dict(self.identity_digests),
            "identity_evaluation_evidence_digests": dict(
                self.identity_evaluation_evidence_digests
            ),
            "gate_attestation_digests": dict(self.gate_attestation_digests),
            "bound_evidence_digests": dict(self.bound_evidence_digests),
            "accepted_publication_spec_digests": dict(
                self.accepted_publication_spec_digests
            ),
            "fixture_admission_digest": self.fixture_admission_digest,
            "owner_instruction_id": self.owner_instruction_id,
            "owner_instruction_digest": self.owner_instruction_digest,
            "authority_issue_snapshot_digest": self.authority_issue_snapshot_digest,
            "authority_issue_number": self.authority_issue_number,
            "authority_issue_url": self.authority_issue_url,
            "issuer_identity": self.issuer_identity,
            "issued_at": self.issued_at,
        }

    def matches(self, record: ProductionOperationalAdmission) -> bool:
        return (
            record.exact_main_sha == self.freeze.exact_main_sha
            and record.exact_main_tree == self.freeze.exact_main_tree
            and record.operational_manifest_digest == self.operational_manifest_digest
            and record.identity_set_digest == self.identity_set_digest
            and record.deployment_bytes_digest == self.deployment_bytes_digest
            and record.evidence_manifest_digest == self.evidence_manifest_digest
            and record.readiness_report_digest == self.readiness_report_digest
            and dict(record.identity_digests) == dict(self.identity_digests)
            and dict(record.identity_evaluation_evidence_digests)
            == dict(self.identity_evaluation_evidence_digests)
            and dict(record.gate_attestation_digests)
            == dict(self.gate_attestation_digests)
            and dict(record.bound_evidence_digests) == dict(self.bound_evidence_digests)
            and dict(record.accepted_publication_spec_digests)
            == dict(self.accepted_publication_spec_digests)
            and record.fixture_admission_digest == self.fixture_admission_digest
            and record.owner_instruction_id == self.owner_instruction_id
            and record.owner_instruction_digest == self.owner_instruction_digest
            and record.authority_issue_snapshot_digest
            == self.authority_issue_snapshot_digest
            and record.authority_issue_number == self.authority_issue_number
            and record.authority_issue_url == self.authority_issue_url
            and record.issuer_identity == self.issuer_identity
            and record.issued_at == self.issued_at
        )


@dataclass(frozen=True, slots=True)
class ProductionOperationalAdmission:
    verdict: ProductionAdmissionVerdict
    exact_main_sha: str
    exact_main_tree: str
    operational_manifest_digest: str
    identity_set_digest: str
    deployment_bytes_digest: str
    evidence_manifest_digest: str
    readiness_report_digest: str
    identity_digests: Mapping[str, str]
    identity_evaluation_evidence_digests: Mapping[str, str]
    gate_attestation_digests: Mapping[str, str]
    bound_evidence_digests: Mapping[str, str]
    accepted_publication_spec_digests: Mapping[str, str]
    fixture_admission_digest: str
    owner_instruction_id: str
    owner_instruction_digest: str
    authority_issue_snapshot_digest: str
    authority_issue_number: int
    authority_issue_url: str
    issuer_identity: str
    issued_at: str
    signing_key_id: str
    signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str
    admission_scope: str = "production"
    increment11r_authorised: bool = False
    production_activation_authorised: bool = False
    publication_authorised: bool = False
    public_dispatch_authorised: bool = False
    production_mutation_authorised: bool = False

    @classmethod
    def from_canonical_bytes(
        cls,
        raw: bytes,
        *,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        owner_instruction: OwnerAdmissionInstruction,
        trusted_owner_keys: Mapping[str, AuthenticationKey],
        trusted_production_keys: Mapping[str, AuthenticationKey],
    ) -> ProductionOperationalAdmission:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "verdict",
            "admission_scope",
            "exact_main_sha",
            "exact_main_tree",
            "operational_manifest_digest",
            "identity_set_digest",
            "deployment_bytes_digest",
            "evidence_manifest_digest",
            "readiness_report_digest",
            "identity_digests",
            "identity_evaluation_evidence_digests",
            "gate_attestation_digests",
            "bound_evidence_digests",
            "accepted_publication_spec_digests",
            "fixture_admission_digest",
            "owner_instruction_id",
            "owner_instruction_digest",
            "authority_issue_snapshot_digest",
            "authority_issue_number",
            "authority_issue_url",
            "issuer_identity",
            "issued_at",
            "signing_key_id",
            "signing_key_class",
            "increment11r_authorised",
            "production_activation_authorised",
            "publication_authorised",
            "public_dispatch_authorised",
            "production_mutation_authorised",
            "seal",
        }
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-operational-admission.v1"
            or value["verdict"]
            != ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED.value
            or value["admission_scope"] != "production"
            or value["signing_key_class"]
            != KeyClass.PRODUCTION_OPERATIONAL_ADMISSION.value
            or any(
                value[name] is not False
                for name in (
                    "increment11r_authorised",
                    "production_activation_authorised",
                    "publication_authorised",
                    "public_dispatch_authorised",
                    "production_mutation_authorised",
                )
            )
        ):
            raise ProductionAdmissionError("production admission fields differ")
        identity_names = {item.value for item in IdentityClass}
        gate_names = {item.value for item in PRODUCTION_GATE_IDS}
        bound_names = {item.value for item in BoundArtifactRole}
        identity_digests = _canonical_digest_mapping(
            value["identity_digests"],
            "identity_digests",
            expected_keys=identity_names,
        )
        identity_evidence = _canonical_digest_mapping(
            value["identity_evaluation_evidence_digests"],
            "identity_evaluation_evidence_digests",
            expected_keys=identity_names,
        )
        gate_evidence = _canonical_digest_mapping(
            value["gate_attestation_digests"],
            "gate_attestation_digests",
            expected_keys=gate_names,
        )
        bound_evidence = _canonical_digest_mapping(
            value["bound_evidence_digests"],
            "bound_evidence_digests",
            expected_keys=bound_names,
        )
        publication_spec_evidence = _publication_spec_digests(
            value["accepted_publication_spec_digests"]
        )
        issue_number = value["authority_issue_number"]
        seal = value["seal"]
        if (
            type(issue_number) is not int
            or issue_number <= 0
            or value["authority_issue_url"]
            != f"https://github.com/fol2/newsroom/issues/{issue_number}"
            or not isinstance(seal, str)
        ):
            raise ProductionAdmissionError("production admission authority differs")
        record = cls(
            ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED,
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            _digest(value["deployment_bytes_digest"], "deployment_bytes_digest"),
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _digest(value["readiness_report_digest"], "readiness_report_digest"),
            identity_digests,
            identity_evidence,
            gate_evidence,
            bound_evidence,
            publication_spec_evidence,
            _digest(value["fixture_admission_digest"], "fixture_admission_digest"),
            _digest(value["owner_instruction_id"], "owner_instruction_id"),
            _digest(value["owner_instruction_digest"], "owner_instruction_digest"),
            _digest(
                value["authority_issue_snapshot_digest"],
                "authority_issue_snapshot_digest",
            ),
            issue_number,
            _token(value["authority_issue_url"], "authority_issue_url"),
            _token(value["issuer_identity"], "issuer_identity"),
            _timestamp(value["issued_at"], "issued_at"),
            _token(value["signing_key_id"], "signing_key_id"),
            KeyClass.PRODUCTION_OPERATIONAL_ADMISSION,
            seal,
            raw,
            digest_bytes(raw),
        )
        _verify_owner_instruction_binding(
            instruction=owner_instruction,
            report=report,
            evidence_manifest=evidence_manifest,
            trusted_owner_keys=trusted_owner_keys,
        )
        binding = _AdmissionEvidenceBinding.from_authority(
            report=report,
            evidence_manifest=evidence_manifest,
            owner_instruction=owner_instruction,
        )
        if (
            not binding.matches(record)
            or record.signing_key_id != owner_instruction.production_signing_key_id
        ):
            raise ProductionAdmissionError("production admission binding differs")
        key = trusted_production_keys.get(record.signing_key_id)
        if (
            key is None
            or key.key_id != record.signing_key_id
            or key.key_class is not KeyClass.PRODUCTION_OPERATIONAL_ADMISSION
            or key.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT
        ):
            raise ProductionAdmissionError("production admission key is untrusted")
        _verify_seal(value, secret=key.secret)
        return record


def mint_production_operational_admission(
    *,
    freeze: FreezeIdentity,
    report: ProductionReadinessReport,
    evidence_manifest: ProductionEvidenceManifest,
    attestations: Sequence[GateAttestation],
    trusted_evidence_keys: Mapping[str, AuthenticationKey],
    owner_instruction: OwnerAdmissionInstruction,
    current_owner_issue: OwnerIssueRecord,
    trusted_owner_keys: Mapping[str, AuthenticationKey],
    production_signing_key: AuthenticationKey,
) -> ProductionOperationalAdmission:
    """Mint one deterministic admission only under the exact owner instruction."""

    reconstructed_report = inspect_readiness(
        freeze=freeze,
        evidence_manifest=evidence_manifest,
        attestations=attestations,
        trusted_evidence_keys=trusted_evidence_keys,
    )
    if reconstructed_report != report or not report.ready_for_admission:
        raise ProductionAdmissionError("production readiness report is not current")
    _verify_owner_instruction_binding(
        instruction=owner_instruction,
        report=report,
        evidence_manifest=evidence_manifest,
        trusted_owner_keys=trusted_owner_keys,
        current_owner_issue=current_owner_issue,
    )
    if (
        production_signing_key.key_class
        is not KeyClass.PRODUCTION_OPERATIONAL_ADMISSION
        or production_signing_key.key_id != owner_instruction.production_signing_key_id
    ):
        raise ProductionAdmissionError("production signing key differs")
    if production_signing_key.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT:
        raise ProductionAdmissionError(
            "production signing key provenance is ineligible"
        )

    binding = _AdmissionEvidenceBinding.from_authority(
        report=report,
        evidence_manifest=evidence_manifest,
        owner_instruction=owner_instruction,
    )
    unsigned = {
        "schema_version": "newsroom.production-operational-admission.v1",
        "verdict": (ProductionAdmissionVerdict.PRODUCTION_OPERATIONAL_ADMITTED.value),
        "admission_scope": "production",
        **binding.canonical_value(),
        "signing_key_id": production_signing_key.key_id,
        "signing_key_class": production_signing_key.key_class.value,
        "increment11r_authorised": False,
        "production_activation_authorised": False,
        "publication_authorised": False,
        "public_dispatch_authorised": False,
        "production_mutation_authorised": False,
    }
    seal = _seal(unsigned, production_signing_key.secret)
    raw = canonical_json_bytes({**unsigned, "seal": seal})
    return ProductionOperationalAdmission.from_canonical_bytes(
        raw,
        report=report,
        evidence_manifest=evidence_manifest,
        owner_instruction=owner_instruction,
        trusted_owner_keys=trusted_owner_keys,
        trusted_production_keys={production_signing_key.key_id: production_signing_key},
    )
