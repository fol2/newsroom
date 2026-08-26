"""Human Accountable Owner issue snapshots and admission instructions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes

from ._shared import (
    AuthenticationKey,
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
from .evidence import ProductionEvidenceManifest, _bound_artifact
from .identities import BoundArtifactRole
from .readiness import ProductionReadinessReport

_NON_INSTRUCTION_ISSUES = frozenset({599, 760})
_OWNER_BINDING_PREFIX = "<!-- newsroom-production-admission-instruction-v1\n"
_OWNER_BINDING_SUFFIX = "\n-->"


def _owner_issue_binding_value(
    *,
    report: ProductionReadinessReport,
    evidence_manifest: ProductionEvidenceManifest,
    production_signing_key_id: str,
) -> dict[str, object]:
    shadow = _bound_artifact(evidence_manifest, BoundArtifactRole.SHADOW_CLOSEOUT)
    canary = _bound_artifact(
        evidence_manifest,
        BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
    )
    return {
        "schema_version": "newsroom.owner-production-admission-binding.v1",
        **report.freeze.canonical_value(),
        "evidence_manifest_digest": evidence_manifest.digest,
        "readiness_report_digest": report.digest,
        "operational_manifest_digest": (
            evidence_manifest.identity_set.operational_manifest_digest
        ),
        "identity_set_digest": evidence_manifest.identity_set.digest,
        "shadow_closeout_digest": shadow.artifact_digest,
        "canary_closeout_digest": canary.artifact_digest,
        "production_signing_key_id": _token(
            production_signing_key_id, "production_signing_key_id"
        ),
        "maximum_admissions": 1,
        "increment11r_authorised": False,
        "production_activation_authorised": False,
    }


def owner_issue_binding_marker(
    *,
    report: ProductionReadinessReport,
    evidence_manifest: ProductionEvidenceManifest,
    production_signing_key_id: str,
) -> str:
    """Render the exact machine-readable binding required in the owner issue."""

    value = _owner_issue_binding_value(
        report=report,
        evidence_manifest=evidence_manifest,
        production_signing_key_id=production_signing_key_id,
    )
    return (
        _OWNER_BINDING_PREFIX
        + canonical_json_bytes(value).decode("utf-8")
        + _OWNER_BINDING_SUFFIX
    )


@dataclass(frozen=True, slots=True)
class OwnerIssueRecord:
    """Current GitHub authority facts obtained independently of the instruction."""

    authority_issue_number: int
    authority_issue_url: str
    authority_issue_node_id: str
    authority_issue_updated_at: str
    owner_identity: str
    title: str
    body: str = field(repr=False)
    repository: str = "fol2/newsroom"
    author_association: str = "OWNER"
    issue_state: str = "OPEN"

    def __post_init__(self) -> None:
        if (
            type(self.authority_issue_number) is not int
            or self.authority_issue_number <= 0
            or self.repository != "fol2/newsroom"
            or self.author_association != "OWNER"
            or self.issue_state != "OPEN"
            or self.authority_issue_url
            != f"https://github.com/fol2/newsroom/issues/{self.authority_issue_number}"
        ):
            raise ProductionAdmissionError("owner issue authority differs")
        _token(self.authority_issue_node_id, "authority_issue_node_id")
        _timestamp(self.authority_issue_updated_at, "authority_issue_updated_at")
        _token(self.owner_identity, "owner_identity")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ProductionAdmissionError("owner issue title differs")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ProductionAdmissionError("owner issue body differs")

    @property
    def title_digest(self) -> str:
        return digest_bytes(self.title.encode("utf-8"))

    @property
    def body_digest(self) -> str:
        return digest_bytes(self.body.encode("utf-8"))

    @classmethod
    def from_github_api(cls, value: object) -> OwnerIssueRecord:
        if not isinstance(value, Mapping):
            raise ProductionAdmissionError("owner issue API record differs")
        issue_number = value.get("number")
        user = value.get("user")
        title = value.get("title")
        body = value.get("body")
        if (
            type(issue_number) is not int
            or issue_number <= 0
            or not isinstance(user, Mapping)
            or not isinstance(user.get("login"), str)
            or not isinstance(title, str)
            or not title
            or not isinstance(body, str)
            or not body
            or value.get("html_url")
            != f"https://github.com/fol2/newsroom/issues/{issue_number}"
            or value.get("author_association") != "OWNER"
            or value.get("state") != "open"
        ):
            raise ProductionAdmissionError("owner issue API authority differs")
        return cls(
            authority_issue_number=issue_number,
            authority_issue_url=_token(value["html_url"], "authority_issue_url"),
            authority_issue_node_id=_token(
                value.get("node_id"), "authority_issue_node_id"
            ),
            authority_issue_updated_at=_timestamp(
                value.get("updated_at"), "authority_issue_updated_at"
            ),
            owner_identity=f"github:{_token(user['login'], 'owner_login')}",
            title=title,
            body=body,
        )

    def verify_instruction_binding(
        self,
        *,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        production_signing_key_id: str,
    ) -> None:
        if self.body.count(_OWNER_BINDING_PREFIX) != 1:
            raise ProductionAdmissionError("owner issue instruction binding is absent")
        start = self.body.index(_OWNER_BINDING_PREFIX) + len(_OWNER_BINDING_PREFIX)
        end = self.body.find(_OWNER_BINDING_SUFFIX, start)
        if end < 0:
            raise ProductionAdmissionError("owner issue instruction binding is absent")
        retained = _canonical_document(self.body[start:end].encode("utf-8"))
        expected = _owner_issue_binding_value(
            report=report,
            evidence_manifest=evidence_manifest,
            production_signing_key_id=production_signing_key_id,
        )
        if dict(retained) != expected:
            raise ProductionAdmissionError("owner issue instruction binding differs")

    def verify_snapshot(self, snapshot: OwnerIssueSnapshot) -> None:
        if (
            self.repository != snapshot.repository
            or self.author_association != snapshot.author_association
            or self.issue_state != snapshot.issue_state
            or self.authority_issue_number != snapshot.authority_issue_number
            or self.authority_issue_url != snapshot.authority_issue_url
            or self.authority_issue_node_id != snapshot.authority_issue_node_id
            or self.authority_issue_updated_at != snapshot.authority_issue_updated_at
            or self.owner_identity != snapshot.owner_identity
            or self.title_digest != snapshot.title_digest
            or self.body_digest != snapshot.body_digest
        ):
            raise ProductionAdmissionError("owner issue live authority differs")


@dataclass(frozen=True, slots=True)
class OwnerIssueSnapshot:
    authority_issue_number: int
    authority_issue_url: str
    authority_issue_node_id: str
    authority_issue_updated_at: str
    owner_identity: str
    captured_at: str
    exact_main_sha: str
    exact_main_tree: str
    evidence_manifest_digest: str
    readiness_report_digest: str
    operational_manifest_digest: str
    identity_set_digest: str
    shadow_closeout_digest: str
    canary_closeout_digest: str
    production_signing_key_id: str
    title_digest: str
    body_digest: str
    owner_signing_key_id: str
    owner_signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str
    repository: str = "fol2/newsroom"
    author_association: str = "OWNER"
    issue_state: str = "OPEN"
    purpose: str = "PRODUCTION_OPERATIONAL_ADMISSION"

    @classmethod
    def build(
        cls,
        *,
        owner_issue: OwnerIssueRecord,
        captured_at: str,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        production_signing_key_id: str,
        owner_signing_key: AuthenticationKey,
    ) -> OwnerIssueSnapshot:
        if (
            not isinstance(owner_issue, OwnerIssueRecord)
            or owner_issue.authority_issue_number in _NON_INSTRUCTION_ISSUES
        ):
            raise ProductionAdmissionError(
                "production admission requires a dedicated owner instruction issue"
            )
        if (
            owner_signing_key.key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
            or owner_signing_key.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT
        ):
            raise ProductionAdmissionError("owner issue key class differs")
        if (
            not report.ready_for_admission
            or report.evidence_manifest_digest != evidence_manifest.digest
            or report.identity_set_digest != evidence_manifest.identity_set.digest
            or report.operational_manifest_digest
            != evidence_manifest.identity_set.operational_manifest_digest
            or report.freeze != evidence_manifest.identity_set.freeze
        ):
            raise ProductionAdmissionError("owner issue evidence differs")
        shadow = _bound_artifact(evidence_manifest, BoundArtifactRole.SHADOW_CLOSEOUT)
        canary = _bound_artifact(
            evidence_manifest,
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
        )
        owner_issue.verify_instruction_binding(
            report=report,
            evidence_manifest=evidence_manifest,
            production_signing_key_id=production_signing_key_id,
        )
        checked_captured_at = _timestamp(captured_at, "captured_at")
        if owner_issue.authority_issue_updated_at > checked_captured_at:
            raise ProductionAdmissionError(
                "owner issue snapshot predates live authority"
            )
        unsigned = {
            "schema_version": "newsroom.owner-production-admission-issue-snapshot.v1",
            "repository": "fol2/newsroom",
            "authority_issue_number": owner_issue.authority_issue_number,
            "authority_issue_url": owner_issue.authority_issue_url,
            "authority_issue_node_id": owner_issue.authority_issue_node_id,
            "authority_issue_updated_at": owner_issue.authority_issue_updated_at,
            "owner_identity": owner_issue.owner_identity,
            "author_association": "OWNER",
            "issue_state": "OPEN",
            "purpose": "PRODUCTION_OPERATIONAL_ADMISSION",
            "captured_at": checked_captured_at,
            **report.freeze.canonical_value(),
            "evidence_manifest_digest": evidence_manifest.digest,
            "readiness_report_digest": report.digest,
            "operational_manifest_digest": (
                evidence_manifest.identity_set.operational_manifest_digest
            ),
            "identity_set_digest": evidence_manifest.identity_set.digest,
            "shadow_closeout_digest": shadow.artifact_digest,
            "canary_closeout_digest": canary.artifact_digest,
            "production_signing_key_id": _token(
                production_signing_key_id, "production_signing_key_id"
            ),
            "title_digest": owner_issue.title_digest,
            "body_digest": owner_issue.body_digest,
            "owner_signing_key_id": owner_signing_key.key_id,
            "owner_signing_key_class": owner_signing_key.key_class.value,
        }
        seal = _seal(unsigned, owner_signing_key.secret)
        raw = canonical_json_bytes({**unsigned, "seal": seal})
        return cls(
            owner_issue.authority_issue_number,
            str(unsigned["authority_issue_url"]),
            owner_issue.authority_issue_node_id,
            owner_issue.authority_issue_updated_at,
            str(unsigned["owner_identity"]),
            str(unsigned["captured_at"]),
            report.freeze.exact_main_sha,
            report.freeze.exact_main_tree,
            evidence_manifest.digest,
            report.digest,
            evidence_manifest.identity_set.operational_manifest_digest,
            evidence_manifest.identity_set.digest,
            shadow.artifact_digest,
            canary.artifact_digest,
            str(unsigned["production_signing_key_id"]),
            str(unsigned["title_digest"]),
            str(unsigned["body_digest"]),
            owner_signing_key.key_id,
            owner_signing_key.key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> OwnerIssueSnapshot:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "repository",
            "authority_issue_number",
            "authority_issue_url",
            "authority_issue_node_id",
            "authority_issue_updated_at",
            "owner_identity",
            "author_association",
            "issue_state",
            "purpose",
            "captured_at",
            "exact_main_sha",
            "exact_main_tree",
            "evidence_manifest_digest",
            "readiness_report_digest",
            "operational_manifest_digest",
            "identity_set_digest",
            "shadow_closeout_digest",
            "canary_closeout_digest",
            "production_signing_key_id",
            "title_digest",
            "body_digest",
            "owner_signing_key_id",
            "owner_signing_key_class",
            "seal",
        }
        issue_number = value.get("authority_issue_number")
        if (
            set(value) != required
            or value["schema_version"]
            != "newsroom.owner-production-admission-issue-snapshot.v1"
            or value["repository"] != "fol2/newsroom"
            or type(issue_number) is not int
            or issue_number <= 0
            or issue_number in _NON_INSTRUCTION_ISSUES
            or value["authority_issue_url"]
            != f"https://github.com/fol2/newsroom/issues/{issue_number}"
            or value["author_association"] != "OWNER"
            or value["issue_state"] != "OPEN"
            or value["purpose"] != "PRODUCTION_OPERATIONAL_ADMISSION"
            or value["owner_signing_key_class"]
            != KeyClass.HUMAN_ACCOUNTABLE_OWNER.value
        ):
            raise ProductionAdmissionError("owner issue snapshot fields differ")
        seal = value["seal"]
        if not isinstance(seal, str):
            raise ProductionAdmissionError("owner issue snapshot seal differs")
        updated_at = _timestamp(
            value["authority_issue_updated_at"], "authority_issue_updated_at"
        )
        captured_at = _timestamp(value["captured_at"], "captured_at")
        if updated_at > captured_at:
            raise ProductionAdmissionError(
                "owner issue snapshot predates live authority"
            )
        return cls(
            issue_number,
            _token(value["authority_issue_url"], "authority_issue_url"),
            _token(value["authority_issue_node_id"], "authority_issue_node_id"),
            updated_at,
            _token(value["owner_identity"], "owner_identity"),
            captured_at,
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _digest(value["readiness_report_digest"], "readiness_report_digest"),
            _digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            _digest(value["shadow_closeout_digest"], "shadow_closeout_digest"),
            _digest(value["canary_closeout_digest"], "canary_closeout_digest"),
            _token(value["production_signing_key_id"], "production_signing_key_id"),
            _digest(value["title_digest"], "title_digest"),
            _digest(value["body_digest"], "body_digest"),
            _token(value["owner_signing_key_id"], "owner_signing_key_id"),
            KeyClass.HUMAN_ACCOUNTABLE_OWNER,
            seal,
            raw,
            digest_bytes(raw),
        )

    def verify(self, trusted_keys: Mapping[str, AuthenticationKey]) -> None:
        reconstructed = OwnerIssueSnapshot.from_canonical_bytes(self.canonical_bytes)
        if reconstructed != self:
            raise ProductionAdmissionError("owner issue snapshot is forged")
        key = trusted_keys.get(self.owner_signing_key_id)
        if (
            key is None
            or key.key_id != self.owner_signing_key_id
            or key.key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
            or key.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT
        ):
            raise ProductionAdmissionError("owner issue snapshot key is untrusted")
        _verify_seal(_canonical_document(self.canonical_bytes), secret=key.secret)


@dataclass(frozen=True, slots=True)
class OwnerAdmissionInstruction:
    instruction_id: str
    authority_issue_number: int
    authority_issue_url: str
    authority_issue_snapshot: OwnerIssueSnapshot
    owner_identity: str
    issued_at: str
    exact_main_sha: str
    exact_main_tree: str
    evidence_manifest_digest: str
    readiness_report_digest: str
    operational_manifest_digest: str
    identity_set_digest: str
    shadow_closeout_digest: str
    canary_closeout_digest: str
    production_signing_key_id: str
    owner_signing_key_id: str
    owner_signing_key_class: KeyClass
    seal: str
    canonical_bytes: bytes
    digest: str
    admission_scope: str = "production"
    maximum_admissions: int = 1
    increment11r_authorised: bool = False
    production_activation_authorised: bool = False

    @classmethod
    def build(
        cls,
        *,
        authority_issue_snapshot: OwnerIssueSnapshot,
        issued_at: str,
        report: ProductionReadinessReport,
        evidence_manifest: ProductionEvidenceManifest,
        production_signing_key_id: str,
        owner_signing_key: AuthenticationKey,
    ) -> OwnerAdmissionInstruction:
        if (
            owner_signing_key.key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
            or owner_signing_key.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT
        ):
            raise ProductionAdmissionError("owner instruction key class differs")
        authority_issue_snapshot.verify({owner_signing_key.key_id: owner_signing_key})
        if not report.ready_for_admission:
            raise ProductionAdmissionError("owner instruction requires ready evidence")
        if (
            report.evidence_manifest_digest != evidence_manifest.digest
            or report.identity_set_digest != evidence_manifest.identity_set.digest
            or report.operational_manifest_digest
            != evidence_manifest.identity_set.operational_manifest_digest
            or report.freeze != evidence_manifest.identity_set.freeze
        ):
            raise ProductionAdmissionError("owner instruction evidence differs")
        shadow = _bound_artifact(evidence_manifest, BoundArtifactRole.SHADOW_CLOSEOUT)
        canary = _bound_artifact(
            evidence_manifest,
            BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
        )
        if (
            authority_issue_snapshot.exact_main_sha != report.freeze.exact_main_sha
            or authority_issue_snapshot.exact_main_tree != report.freeze.exact_main_tree
            or authority_issue_snapshot.evidence_manifest_digest
            != evidence_manifest.digest
            or authority_issue_snapshot.readiness_report_digest != report.digest
            or authority_issue_snapshot.operational_manifest_digest
            != evidence_manifest.identity_set.operational_manifest_digest
            or authority_issue_snapshot.identity_set_digest
            != evidence_manifest.identity_set.digest
            or authority_issue_snapshot.shadow_closeout_digest != shadow.artifact_digest
            or authority_issue_snapshot.canary_closeout_digest != canary.artifact_digest
            or authority_issue_snapshot.production_signing_key_id
            != production_signing_key_id
            or authority_issue_snapshot.captured_at > _timestamp(issued_at, "issued_at")
        ):
            raise ProductionAdmissionError("owner issue snapshot binding differs")
        base = {
            "schema_version": "newsroom.owner-production-admission-instruction.v1",
            "authority_issue_number": authority_issue_snapshot.authority_issue_number,
            "authority_issue_url": authority_issue_snapshot.authority_issue_url,
            "authority_issue_snapshot": dict(
                _canonical_document(authority_issue_snapshot.canonical_bytes)
            ),
            "owner_identity": authority_issue_snapshot.owner_identity,
            "issued_at": _timestamp(issued_at, "issued_at"),
            **report.freeze.canonical_value(),
            "evidence_manifest_digest": evidence_manifest.digest,
            "readiness_report_digest": report.digest,
            "operational_manifest_digest": (
                evidence_manifest.identity_set.operational_manifest_digest
            ),
            "identity_set_digest": evidence_manifest.identity_set.digest,
            "shadow_closeout_digest": shadow.artifact_digest,
            "canary_closeout_digest": canary.artifact_digest,
            "production_signing_key_id": _token(
                production_signing_key_id, "production_signing_key_id"
            ),
            "production_signing_key_class": (
                KeyClass.PRODUCTION_OPERATIONAL_ADMISSION.value
            ),
            "owner_signing_key_id": owner_signing_key.key_id,
            "owner_signing_key_class": owner_signing_key.key_class.value,
            "admission_scope": "production",
            "maximum_admissions": 1,
            "increment11r_authorised": False,
            "production_activation_authorised": False,
        }
        instruction_id = digest_bytes(canonical_json_bytes(base))
        unsigned = {**base, "instruction_id": instruction_id}
        seal = _seal(unsigned, owner_signing_key.secret)
        value = {**unsigned, "seal": seal}
        raw = canonical_json_bytes(value)
        return cls(
            instruction_id,
            authority_issue_snapshot.authority_issue_number,
            str(base["authority_issue_url"]),
            authority_issue_snapshot,
            str(base["owner_identity"]),
            str(base["issued_at"]),
            report.freeze.exact_main_sha,
            report.freeze.exact_main_tree,
            evidence_manifest.digest,
            report.digest,
            evidence_manifest.identity_set.operational_manifest_digest,
            evidence_manifest.identity_set.digest,
            shadow.artifact_digest,
            canary.artifact_digest,
            str(base["production_signing_key_id"]),
            owner_signing_key.key_id,
            owner_signing_key.key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> OwnerAdmissionInstruction:
        value = _canonical_document(raw)
        required = {
            "schema_version",
            "instruction_id",
            "authority_issue_number",
            "authority_issue_url",
            "authority_issue_snapshot",
            "owner_identity",
            "issued_at",
            "exact_main_sha",
            "exact_main_tree",
            "evidence_manifest_digest",
            "readiness_report_digest",
            "operational_manifest_digest",
            "identity_set_digest",
            "shadow_closeout_digest",
            "canary_closeout_digest",
            "production_signing_key_id",
            "production_signing_key_class",
            "owner_signing_key_id",
            "owner_signing_key_class",
            "admission_scope",
            "maximum_admissions",
            "increment11r_authorised",
            "production_activation_authorised",
            "seal",
        }
        issue_number = value.get("authority_issue_number")
        issue_snapshot_value = value.get("authority_issue_snapshot")
        issued_at_value = value.get("issued_at")
        if (
            set(value) != required
            or value["schema_version"]
            != "newsroom.owner-production-admission-instruction.v1"
            or type(issue_number) is not int
            or issue_number <= 0
            or issue_number in _NON_INSTRUCTION_ISSUES
            or value["authority_issue_url"]
            != f"https://github.com/fol2/newsroom/issues/{issue_number}"
            or not isinstance(issue_snapshot_value, dict)
            or not isinstance(issued_at_value, str)
            or value["production_signing_key_class"]
            != KeyClass.PRODUCTION_OPERATIONAL_ADMISSION.value
            or not isinstance(value["owner_signing_key_class"], str)
            or value["admission_scope"] != "production"
            or value["maximum_admissions"] != 1
            or value["increment11r_authorised"] is not False
            or value["production_activation_authorised"] is not False
        ):
            raise ProductionAdmissionError("owner instruction fields differ")
        issue_snapshot = OwnerIssueSnapshot.from_canonical_bytes(
            canonical_json_bytes(issue_snapshot_value)
        )
        issued_at = _timestamp(issued_at_value, "issued_at")
        if (
            issue_snapshot.authority_issue_number != issue_number
            or issue_snapshot.authority_issue_url != value["authority_issue_url"]
            or issue_snapshot.owner_identity != value["owner_identity"]
            or issue_snapshot.exact_main_sha != value["exact_main_sha"]
            or issue_snapshot.exact_main_tree != value["exact_main_tree"]
            or issue_snapshot.evidence_manifest_digest
            != value["evidence_manifest_digest"]
            or issue_snapshot.readiness_report_digest
            != value["readiness_report_digest"]
            or issue_snapshot.operational_manifest_digest
            != value["operational_manifest_digest"]
            or issue_snapshot.identity_set_digest != value["identity_set_digest"]
            or issue_snapshot.shadow_closeout_digest != value["shadow_closeout_digest"]
            or issue_snapshot.canary_closeout_digest != value["canary_closeout_digest"]
            or issue_snapshot.production_signing_key_id
            != value["production_signing_key_id"]
            or issue_snapshot.captured_at > issued_at
        ):
            raise ProductionAdmissionError("owner issue snapshot binding differs")
        try:
            owner_key_class = KeyClass(value["owner_signing_key_class"])
        except (TypeError, ValueError) as exc:
            raise ProductionAdmissionError(
                "owner instruction key class differs"
            ) from exc
        base = {
            name: item
            for name, item in value.items()
            if name not in {"instruction_id", "seal"}
        }
        expected_instruction_id = digest_bytes(canonical_json_bytes(base))
        if value["instruction_id"] != expected_instruction_id:
            raise ProductionAdmissionError("owner instruction identity differs")
        seal = value["seal"]
        if not isinstance(seal, str):
            raise ProductionAdmissionError("owner instruction seal differs")
        return cls(
            expected_instruction_id,
            issue_number,
            _token(value["authority_issue_url"], "authority_issue_url"),
            issue_snapshot,
            _token(value["owner_identity"], "owner_identity"),
            issued_at,
            _git_sha(value["exact_main_sha"], "exact_main_sha"),
            _git_sha(value["exact_main_tree"], "exact_main_tree"),
            _digest(value["evidence_manifest_digest"], "evidence_manifest_digest"),
            _digest(value["readiness_report_digest"], "readiness_report_digest"),
            _digest(
                value["operational_manifest_digest"],
                "operational_manifest_digest",
            ),
            _digest(value["identity_set_digest"], "identity_set_digest"),
            _digest(value["shadow_closeout_digest"], "shadow_closeout_digest"),
            _digest(value["canary_closeout_digest"], "canary_closeout_digest"),
            _token(value["production_signing_key_id"], "production_signing_key_id"),
            _token(value["owner_signing_key_id"], "owner_signing_key_id"),
            owner_key_class,
            seal,
            raw,
            digest_bytes(raw),
        )

    def verify(self, trusted_keys: Mapping[str, AuthenticationKey]) -> None:
        reconstructed = OwnerAdmissionInstruction.from_canonical_bytes(
            self.canonical_bytes
        )
        if reconstructed != self:
            raise ProductionAdmissionError("owner instruction is forged")
        self.authority_issue_snapshot.verify(trusted_keys)
        key = trusted_keys.get(self.owner_signing_key_id)
        if (
            key is None
            or key.key_id != self.owner_signing_key_id
            or key.key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
            or key.provenance is not KeyProvenance.PRODUCTION_TRUST_ROOT
            or self.owner_signing_key_class is not KeyClass.HUMAN_ACCOUNTABLE_OWNER
        ):
            raise ProductionAdmissionError("owner instruction key is untrusted")
        _verify_seal(_canonical_document(self.canonical_bytes), secret=key.secret)


def _verify_owner_instruction_binding(
    *,
    instruction: OwnerAdmissionInstruction,
    report: ProductionReadinessReport,
    evidence_manifest: ProductionEvidenceManifest,
    trusted_owner_keys: Mapping[str, AuthenticationKey],
    current_owner_issue: OwnerIssueRecord | None = None,
) -> None:
    instruction.verify(trusted_owner_keys)
    if current_owner_issue is not None:
        current_owner_issue.verify_snapshot(instruction.authority_issue_snapshot)
    shadow = _bound_artifact(evidence_manifest, BoundArtifactRole.SHADOW_CLOSEOUT)
    canary = _bound_artifact(
        evidence_manifest,
        BoundArtifactRole.LIVE_EVIDENCE_INTAKE_CANARY_CLOSEOUT,
    )
    if (
        instruction.exact_main_sha != report.freeze.exact_main_sha
        or instruction.exact_main_tree != report.freeze.exact_main_tree
        or instruction.evidence_manifest_digest != evidence_manifest.digest
        or instruction.readiness_report_digest != report.digest
        or instruction.operational_manifest_digest
        != evidence_manifest.identity_set.operational_manifest_digest
        or instruction.identity_set_digest != evidence_manifest.identity_set.digest
        or instruction.shadow_closeout_digest != shadow.artifact_digest
        or instruction.canary_closeout_digest != canary.artifact_digest
    ):
        raise ProductionAdmissionError("owner instruction binding differs")
