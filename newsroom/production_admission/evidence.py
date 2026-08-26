"""Canonical evidence manifests and signed gate attestations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._shared import (
    AuthenticationKey,
    KeyClass,
    ProductionAdmissionError,
    _boolean,
    _canonical_document,
    _digest,
    _git_sha,
    _nonnegative_integer,
    _optional_digest,
    _seal,
    _timestamp,
    _token,
    _verify_seal,
)
from .gate_evidence import ProductionGateEvidence
from .identities import (
    BoundArtifact,
    BoundArtifactRole,
    ProductionGateId,
    ProductionIdentitySet,
    ReadinessStatus,
    _publication_spec_digests,
)


@dataclass(frozen=True, slots=True)
class ProductionEvidenceManifest:
    identity_set: ProductionIdentitySet
    gate_evidence: Mapping[ProductionGateId, ProductionGateEvidence]
    bound_artifacts: tuple[BoundArtifact, ...]
    accepted_publication_spec_digests: Mapping[str, str]
    fixture_admission_digest: str
    fixture_admission_inherited: bool
    readiness_provider_calls: int
    readiness_publication_effects: int
    readiness_production_mutations: int
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        identity_set: ProductionIdentitySet,
        gate_evidence: Mapping[ProductionGateId, ProductionGateEvidence],
        bound_artifacts: Sequence[BoundArtifact],
        accepted_publication_spec_digests: Mapping[str, str],
        fixture_admission_digest: str,
        fixture_admission_inherited: bool,
        readiness_provider_calls: int,
        readiness_publication_effects: int,
        readiness_production_mutations: int,
    ) -> ProductionEvidenceManifest:
        reconstructed = ProductionIdentitySet.from_canonical_bytes(
            identity_set.canonical_bytes
        )
        if reconstructed != identity_set:
            raise ProductionAdmissionError("production identity set is forged")
        checked_bound = tuple(sorted(bound_artifacts, key=lambda item: item.role.value))
        if len({item.role for item in checked_bound}) != len(checked_bound):
            raise ProductionAdmissionError("bound artifact roles must be unique")
        if any(
            BoundArtifact.from_value(item.canonical_value()) != item
            for item in checked_bound
        ):
            raise ProductionAdmissionError("bound artifact is forged")
        checked_publication_specs = _publication_spec_digests(
            accepted_publication_spec_digests
        )
        checked_gate_evidence: dict[ProductionGateId, ProductionGateEvidence] = {}
        for raw_gate, raw_evidence in gate_evidence.items():
            if not isinstance(raw_gate, ProductionGateId) or not isinstance(
                raw_evidence, ProductionGateEvidence
            ):
                raise ProductionAdmissionError("gate evidence key differs")
            reconstructed_evidence = ProductionGateEvidence.from_canonical_bytes(
                raw_evidence.canonical_bytes,
                identity_set=identity_set,
                bound_artifacts=checked_bound,
                accepted_publication_spec_digests=checked_publication_specs,
            )
            if (
                reconstructed_evidence != raw_evidence
                or raw_evidence.gate_id is not raw_gate
            ):
                raise ProductionAdmissionError("production gate evidence is forged")
            checked_gate_evidence[raw_gate] = raw_evidence
        inherited = _boolean(fixture_admission_inherited, "fixture_admission_inherited")
        provider_calls = _nonnegative_integer(
            readiness_provider_calls, "readiness_provider_calls"
        )
        publication_effects = _nonnegative_integer(
            readiness_publication_effects, "readiness_publication_effects"
        )
        production_mutations = _nonnegative_integer(
            readiness_production_mutations, "readiness_production_mutations"
        )
        value = {
            "schema_version": "newsroom.production-evidence-manifest.v1",
            "identity_set": dict(identity_set.canonical_value()),
            "gate_evidence": {
                gate_id.value: dict(evidence.canonical_value())
                for gate_id, evidence in sorted(
                    checked_gate_evidence.items(), key=lambda item: item[0].value
                )
            },
            "bound_artifacts": [item.canonical_value() for item in checked_bound],
            "accepted_publication_spec_digests": dict(checked_publication_specs),
            "fixture_admission_digest": _digest(
                fixture_admission_digest, "fixture_admission_digest"
            ),
            "fixture_admission_inherited": inherited,
            "readiness_provider_calls": provider_calls,
            "readiness_publication_effects": publication_effects,
            "readiness_production_mutations": production_mutations,
        }
        raw = canonical_json_bytes(value)
        return cls(
            identity_set,
            MappingProxyType(checked_gate_evidence),
            checked_bound,
            checked_publication_specs,
            str(value["fixture_admission_digest"]),
            inherited,
            provider_calls,
            publication_effects,
            production_mutations,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> ProductionEvidenceManifest:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "identity_set",
            "gate_evidence",
            "bound_artifacts",
            "accepted_publication_spec_digests",
            "fixture_admission_digest",
            "fixture_admission_inherited",
            "readiness_provider_calls",
            "readiness_publication_effects",
            "readiness_production_mutations",
        }
        identity_value = value.get("identity_set")
        gate_values = value.get("gate_evidence")
        bound_values = value.get("bound_artifacts")
        publication_spec_values = value.get("accepted_publication_spec_digests")
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-evidence-manifest.v1"
            or not isinstance(identity_value, dict)
            or not isinstance(gate_values, dict)
            or not isinstance(bound_values, list)
            or not isinstance(publication_spec_values, dict)
        ):
            raise ProductionAdmissionError("production evidence manifest fields differ")
        identity_set = ProductionIdentitySet.from_canonical_bytes(
            canonical_json_bytes(identity_value)
        )
        checked_bound = tuple(BoundArtifact.from_value(item) for item in bound_values)
        checked_publication_specs = _publication_spec_digests(publication_spec_values)
        checked_gates: dict[ProductionGateId, ProductionGateEvidence] = {}
        for raw_gate, raw_evidence in gate_values.items():
            try:
                gate_id = ProductionGateId(raw_gate)
            except (TypeError, ValueError) as exc:
                raise ProductionAdmissionError("gate evidence key differs") from exc
            if not isinstance(raw_evidence, dict):
                raise ProductionAdmissionError("gate evidence value differs")
            checked_gates[gate_id] = ProductionGateEvidence.from_canonical_bytes(
                canonical_json_bytes(raw_evidence),
                identity_set=identity_set,
                bound_artifacts=checked_bound,
                accepted_publication_spec_digests=checked_publication_specs,
            )
        rebuilt = cls.build(
            identity_set=identity_set,
            gate_evidence=checked_gates,
            bound_artifacts=checked_bound,
            accepted_publication_spec_digests=checked_publication_specs,
            fixture_admission_digest=_digest(
                value["fixture_admission_digest"], "fixture_admission_digest"
            ),
            fixture_admission_inherited=_boolean(
                value["fixture_admission_inherited"],
                "fixture_admission_inherited",
            ),
            readiness_provider_calls=_nonnegative_integer(
                value["readiness_provider_calls"], "readiness_provider_calls"
            ),
            readiness_publication_effects=_nonnegative_integer(
                value["readiness_publication_effects"],
                "readiness_publication_effects",
            ),
            readiness_production_mutations=_nonnegative_integer(
                value["readiness_production_mutations"],
                "readiness_production_mutations",
            ),
        )
        if rebuilt.canonical_bytes != raw:
            raise ProductionAdmissionError(
                "production evidence manifest is non-canonical"
            )
        return rebuilt

    def canonical_value(self) -> Mapping[str, object]:
        return _canonical_document(self.canonical_bytes)

    @property
    def gate_artifact_digests(self) -> Mapping[ProductionGateId, str]:
        return MappingProxyType(
            {
                gate_id: evidence.digest
                for gate_id, evidence in self.gate_evidence.items()
            }
        )


@dataclass(frozen=True, slots=True)
class GateAttestation:
    gate_id: ProductionGateId
    evidence_manifest_digest: str
    gate_artifact_digest: str | None
    exact_main_sha: str
    exact_main_tree: str
    identity_set_digest: str
    status: ReadinessStatus
    blockers: tuple[str, ...]
    issuer_identity: str
    sealed_at: str
    signing_key_id: str
    signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str

    @classmethod
    def build(
        cls,
        *,
        gate_id: ProductionGateId,
        evidence_manifest: ProductionEvidenceManifest,
        status: ReadinessStatus,
        blockers: Sequence[str],
        issuer_identity: str,
        sealed_at: str,
        signing_key: AuthenticationKey,
    ) -> GateAttestation:
        signing_key.require_production_trust_root(KeyClass.EVIDENCE_AUTHORITY)
        if not isinstance(gate_id, ProductionGateId):
            raise ProductionAdmissionError("gate attestation gate differs")
        if not isinstance(status, ReadinessStatus):
            raise ProductionAdmissionError("gate attestation status differs")
        checked_blockers = tuple(sorted({_token(item, "blocker") for item in blockers}))
        if status is ReadinessStatus.PASS and checked_blockers:
            raise ProductionAdmissionError("passing gate attestation has blockers")
        if status is ReadinessStatus.BLOCKED and not checked_blockers:
            raise ProductionAdmissionError("blocked gate attestation needs a blocker")
        artifact_digest = evidence_manifest.gate_artifact_digests.get(gate_id)
        if status is ReadinessStatus.PASS and artifact_digest is None:
            raise ProductionAdmissionError("passing gate attestation lacks evidence")
        gate_evidence = evidence_manifest.gate_evidence.get(gate_id)
        if (
            status is ReadinessStatus.PASS
            and gate_evidence is not None
            and gate_evidence.blockers
        ):
            raise ProductionAdmissionError(
                "passing gate attestation has failing retained evidence"
            )
        unsigned = {
            "schema_version": "newsroom.production-gate-attestation.v1",
            "gate_id": gate_id.value,
            "evidence_manifest_digest": evidence_manifest.digest,
            "gate_artifact_digest": artifact_digest,
            **evidence_manifest.identity_set.freeze.canonical_value(),
            "identity_set_digest": evidence_manifest.identity_set.digest,
            "status": status.value,
            "blockers": list(checked_blockers),
            "issuer_identity": _token(issuer_identity, "issuer_identity"),
            "sealed_at": _timestamp(sealed_at, "sealed_at"),
            "signing_key_id": signing_key.key_id,
            "signing_key_class": signing_key.key_class.value,
        }
        seal = _seal(unsigned, signing_key.secret)
        value = {**unsigned, "seal": seal}
        raw = canonical_json_bytes(value)
        return cls(
            gate_id,
            evidence_manifest.digest,
            artifact_digest,
            evidence_manifest.identity_set.freeze.exact_main_sha,
            evidence_manifest.identity_set.freeze.exact_main_tree,
            evidence_manifest.identity_set.digest,
            status,
            checked_blockers,
            str(unsigned["issuer_identity"]),
            str(unsigned["sealed_at"]),
            signing_key.key_id,
            signing_key.key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> GateAttestation:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "gate_id",
            "evidence_manifest_digest",
            "gate_artifact_digest",
            "exact_main_sha",
            "exact_main_tree",
            "identity_set_digest",
            "status",
            "blockers",
            "issuer_identity",
            "sealed_at",
            "signing_key_id",
            "signing_key_class",
            "seal",
        }
        blockers = value.get("blockers")
        if (
            set(value) != required
            or value["schema_version"] != "newsroom.production-gate-attestation.v1"
            or not isinstance(value["gate_id"], str)
            or not isinstance(value["status"], str)
            or not isinstance(value["signing_key_class"], str)
            or not isinstance(blockers, list)
            or not all(isinstance(item, str) for item in blockers)
        ):
            raise ProductionAdmissionError("gate attestation fields differ")
        try:
            gate_id = ProductionGateId(value["gate_id"])
            status = ReadinessStatus(value["status"])
            key_class = KeyClass(value["signing_key_class"])
        except (TypeError, ValueError) as exc:
            raise ProductionAdmissionError("gate attestation value differs") from exc
        checked_blockers = tuple(sorted({_token(item, "blocker") for item in blockers}))
        if checked_blockers != tuple(blockers):
            raise ProductionAdmissionError(
                "gate attestation blockers are non-canonical"
            )
        if status is ReadinessStatus.PASS and checked_blockers:
            raise ProductionAdmissionError("passing gate attestation has blockers")
        if status is ReadinessStatus.BLOCKED and not checked_blockers:
            raise ProductionAdmissionError("blocked gate attestation needs a blocker")
        seal = value["seal"]
        if not isinstance(seal, str):
            raise ProductionAdmissionError("gate attestation seal differs")
        return cls(
            gate_id,
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _optional_digest(value["gate_artifact_digest"], "gate_artifact_digest"),
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            status,
            checked_blockers,
            _token(value["issuer_identity"], "issuer_identity"),
            _timestamp(value["sealed_at"], "sealed_at"),
            _token(value["signing_key_id"], "signing_key_id"),
            key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    def verify(self, trusted_keys: Mapping[str, AuthenticationKey]) -> None:
        reconstructed = GateAttestation.from_canonical_bytes(self.canonical_bytes)
        if reconstructed != self:
            raise ProductionAdmissionError("gate attestation is forged")
        key = trusted_keys.get(self.signing_key_id)
        if key is None or self.signing_key_class is not KeyClass.EVIDENCE_AUTHORITY:
            raise ProductionAdmissionError("gate attestation key is untrusted")
        key.require_production_trust_root(
            KeyClass.EVIDENCE_AUTHORITY,
            expected_key_id=self.signing_key_id,
        )
        _verify_seal(_canonical_document(self.canonical_bytes), secret=key.secret)


def _bound_artifact(
    manifest: ProductionEvidenceManifest, role: BoundArtifactRole
) -> BoundArtifact:
    matches = tuple(item for item in manifest.bound_artifacts if item.role is role)
    if len(matches) != 1:
        raise ProductionAdmissionError(f"bound artifact {role.value} is not exact")
    return matches[0]
