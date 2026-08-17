"""Increment 9Q-5 BASELINE_CREDENTIAL_SCOPES qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Qualification proves inventory bind, principal bind, isolation and
least-privilege resolution on the real contracts, fail-closed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.credential_scopes import (
    BOUNDARY_ONLY_CLASSES,
    CREDENTIAL_SCOPE,
    DETERMINISTIC_BOUNDARY,
    FIXTURE_PRINCIPAL_DIGEST,
    FIXTURE_PRODUCTION_NAMES,
    MODEL_FAMILY_LOGIN,
    NAMESAKE_CAMPAIGN_CLASSES,
    CredentialScopeError,
    bind_campaign_credential_classes,
    bind_inventory,
    bound_resolver,
    credential_ref_from_primitive,
    inventory_digest,
    resolve,
)
from newsroom.increment9.deployment import (
    EXPECTED_CREDENTIAL_CLASSES,
    EXPECTED_PROBES,
    PROHIBITED_CREDENTIAL_CLASSES,
)
from newsroom.increment9.shadow_contracts import ShadowAccessBoundary, ShadowContractError

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "BASELINE_CREDENTIAL_SCOPES"

REFUSAL_CLASSES = (
    "UNKNOWN_CREDENTIAL_CLASS",
    "PUBLICATION_TARGET_ADAPTER_REFUSED",
    "CROSS_FAMILY_LOGIN_REFUSED",
    "MODEL_FAMILY_AUTHORITY_CLASS_REFUSED",
    "PRODUCTION_STORE_NAME_REFUSED",
    "PRINCIPAL_DIGEST_MISMATCH",
    "INVENTORY_DRIFT",
    "SECRET_BYTES_IN_RESOLUTION",
    "MALFORMED_REQUEST",
    "ANTI_NAMESAKE",
)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q5_baseline_credential_scopes"
_A2_PROBES = ("CREDENTIAL_VALUES_ABSENT", "PRODUCTION_CREDENTIAL_DENIED")
_MARKERS = {
    "UNKNOWN_CREDENTIAL_CLASS": b"unknown_credential_class",
    "PUBLICATION_TARGET_ADAPTER_REFUSED": b"publication_target_adapter_refused",
    "CROSS_FAMILY_LOGIN_REFUSED": b"cross_family_login_refused",
    "MODEL_FAMILY_AUTHORITY_CLASS_REFUSED": b"model_family_authority_class_refused",
    "PRODUCTION_STORE_NAME_REFUSED": b"production_store_name_refused",
    "PRINCIPAL_DIGEST_MISMATCH": b"principal_digest_mismatch",
    "INVENTORY_DRIFT": b"inventory_drift",
    "SECRET_BYTES_IN_RESOLUTION": b"secret_bytes_in_resolution",
    "MALFORMED_REQUEST": b"malformed_request",
    "ANTI_NAMESAKE": b"anti_namesake",
}

Probe = Callable[[str, Path], bool]


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


@dataclass(frozen=True, slots=True)
class RefusalDigest:
    refusal_class: str
    before_digest: str
    after_digest: str
    engaged: bool
    count: int


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    gate_id: str
    status: str
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
    principal_digest: str
    inventory_digest: str
    evidence_digest: str


def _reject_forbidden(inventory: Path) -> None:
    lowered = str(inventory).lower()
    if "news_pool" in lowered:
        raise QualificationError("inventory must not alias news_pool")


def _refusal_surfaces(inventory: Path) -> tuple[tuple[str, Path], ...]:
    if not inventory.is_dir():
        raise QualificationError("inventory is required")
    missing = [rc for rc in REFUSAL_CLASSES if not (inventory / rc).is_file()]
    if missing:
        raise QualificationError(f"missing refusal class: {missing[0]}")
    extras = sorted(
        path.name for path in inventory.iterdir() if path.name not in REFUSAL_CLASSES
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except (CredentialScopeError, ShadowContractError):
        return True
    return False


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that a credential-scope refusal class engages on the real contracts.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")
    if _MARKERS[refusal_class] not in path.read_bytes():
        return False
    probes = {
        "UNKNOWN_CREDENTIAL_CLASS": _should_engage_unknown_credential_class,
        "PUBLICATION_TARGET_ADAPTER_REFUSED": _should_engage_publication_target,
        "CROSS_FAMILY_LOGIN_REFUSED": _should_engage_cross_family_login,
        "MODEL_FAMILY_AUTHORITY_CLASS_REFUSED": _should_engage_model_family_authority,
        "PRODUCTION_STORE_NAME_REFUSED": _should_engage_production_store_name,
        "PRINCIPAL_DIGEST_MISMATCH": _should_engage_principal_digest_mismatch,
        "INVENTORY_DRIFT": _should_engage_inventory_drift,
        "SECRET_BYTES_IN_RESOLUTION": _should_engage_secret_bytes,
        "MALFORMED_REQUEST": _should_engage_malformed_request,
        "ANTI_NAMESAKE": _should_engage_anti_namesake,
    }
    return bool(probes[refusal_class]())


def _should_engage_unknown_credential_class() -> bool:
    return _refused(
        lambda: resolve(
            FIXTURE_PRINCIPAL_DIGEST,
            DETERMINISTIC_BOUNDARY,
            "NOT_A_CREDENTIAL_CLASS",
        )
    )


def _should_engage_publication_target() -> bool:
    handles = (DETERMINISTIC_BOUNDARY, *MODEL_FAMILY_LOGIN)
    return all(
        _refused(
            lambda h=handle: resolve(
                FIXTURE_PRINCIPAL_DIGEST, h, "PUBLICATION_TARGET_ADAPTER"
            )
        )
        for handle in handles
    )


def _should_engage_cross_family_login() -> bool:
    pairs = [
        (handle, other)
        for handle, own in MODEL_FAMILY_LOGIN.items()
        for other in MODEL_FAMILY_LOGIN.values()
        if other != own
    ]
    return all(
        _refused(
            lambda h=handle, c=other: resolve(FIXTURE_PRINCIPAL_DIGEST, h, c)
        )
        for handle, other in pairs
    )


def _should_engage_model_family_authority() -> bool:
    return all(
        _refused(
            lambda h=handle, c=cls: resolve(FIXTURE_PRINCIPAL_DIGEST, h, c)
        )
        for handle in MODEL_FAMILY_LOGIN
        for cls in BOUNDARY_ONLY_CLASSES
    )


def _should_engage_production_store_name() -> bool:
    handles = (DETERMINISTIC_BOUNDARY, *MODEL_FAMILY_LOGIN)
    return all(
        _refused(
            lambda h=handle, c=name: resolve(FIXTURE_PRINCIPAL_DIGEST, h, c)
        )
        for handle in handles
        for name in FIXTURE_PRODUCTION_NAMES
    )


def _should_engage_principal_digest_mismatch() -> bool:
    other = "sha256:" + "0" * 64
    return other != FIXTURE_PRINCIPAL_DIGEST and _refused(
        lambda: resolve(other, DETERMINISTIC_BOUNDARY, "OPENAI_CODEX_LOGIN")
    )


def _should_engage_inventory_drift() -> bool:
    missing = EXPECTED_CREDENTIAL_CLASSES[:-1]
    extra = tuple(sorted((*EXPECTED_CREDENTIAL_CLASSES, "EXTRA_CREDENTIAL_CLASS")))
    unsorted = (
        EXPECTED_CREDENTIAL_CLASSES[1],
        EXPECTED_CREDENTIAL_CLASSES[0],
        *EXPECTED_CREDENTIAL_CLASSES[2:],
    )
    duplicate = (EXPECTED_CREDENTIAL_CLASSES[0], *EXPECTED_CREDENTIAL_CLASSES)
    overlap_prohibited = ("NEO4J_SHADOW_WRITER",)
    drifted = (
        (missing, PROHIBITED_CREDENTIAL_CLASSES),
        (extra, PROHIBITED_CREDENTIAL_CLASSES),
        (unsorted, PROHIBITED_CREDENTIAL_CLASSES),
        (duplicate, PROHIBITED_CREDENTIAL_CLASSES),
        (EXPECTED_CREDENTIAL_CLASSES, overlap_prohibited),
        (("ANTHROPIC_AGENT_SDK",), ("ANTHROPIC_AGENT_SDK",)),
    )
    bind_closed = all(
        _refused(lambda p=permitted, q=prohibited: bind_inventory(p, q))
        for permitted, prohibited in drifted
    )
    boundary_overlap = _refused(
        lambda: ShadowAccessBoundary(
            purpose_identity="increment9-evaluation-only",
            principal_identity_digest=FIXTURE_PRINCIPAL_DIGEST,
            permitted_credential_classes=("ANTHROPIC_AGENT_SDK",),
            prohibited_credential_classes=("ANTHROPIC_AGENT_SDK",),
            egress_policy_digest=FIXTURE_PRINCIPAL_DIGEST,
            artefact_policy_digest=FIXTURE_PRINCIPAL_DIGEST,
        )
    )
    boundary_unsorted = _refused(
        lambda: ShadowAccessBoundary(
            purpose_identity="increment9-evaluation-only",
            principal_identity_digest=FIXTURE_PRINCIPAL_DIGEST,
            permitted_credential_classes=(
                "OPENAI_CODEX_LOGIN",
                "ANTHROPIC_AGENT_SDK",
            ),
            prohibited_credential_classes=PROHIBITED_CREDENTIAL_CLASSES,
            egress_policy_digest=FIXTURE_PRINCIPAL_DIGEST,
            artefact_policy_digest=FIXTURE_PRINCIPAL_DIGEST,
        )
    )
    deployment_closed = (
        extra != EXPECTED_CREDENTIAL_CLASSES
        and overlap_prohibited != PROHIBITED_CREDENTIAL_CLASSES
    )
    return bind_closed and boundary_overlap and boundary_unsorted and deployment_closed


def _should_engage_secret_bytes() -> bool:
    digest = digest_bytes(
        canonical_json_bytes(
            {"credential_class": "OPENAI_CODEX_LOGIN", "scope": CREDENTIAL_SCOPE}
        )
    )
    secret_record = {
        "credential_class": "OPENAI_CODEX_LOGIN",
        "digest": digest,
        "scope": CREDENTIAL_SCOPE,
        "secret": "sk-fixture-not-a-real-secret",
    }
    load_closed = _refused(lambda: credential_ref_from_primitive(secret_record))
    ref = resolve(
        FIXTURE_PRINCIPAL_DIGEST, DETERMINISTIC_BOUNDARY, "OPENAI_CODEX_LOGIN"
    )
    primitive = ref.primitive()
    evidence = json.loads(canonical_json_bytes(primitive).decode("utf-8"))
    clean = set(primitive) == {"credential_class", "digest", "scope"} and not (
        {"secret", "secret_bytes"} & set(evidence)
    )
    return load_closed and clean


def _should_engage_malformed_request() -> bool:
    over_long = "H" * 257
    return all(
        (
            _refused(
                lambda: resolve(
                    FIXTURE_PRINCIPAL_DIGEST, "", "OPENAI_CODEX_LOGIN"
                )
            ),
            _refused(
                lambda: resolve(
                    FIXTURE_PRINCIPAL_DIGEST, over_long, "OPENAI_CODEX_LOGIN"
                )
            ),
            _refused(
                lambda: resolve(
                    FIXTURE_PRINCIPAL_DIGEST,
                    "not a token",
                    "OPENAI_CODEX_LOGIN",
                )
            ),
            _refused(
                lambda: resolve(
                    FIXTURE_PRINCIPAL_DIGEST,
                    "WEIRD_HANDLE",
                    "OPENAI_CODEX_LOGIN",
                )
            ),
        )
    )


def _should_engage_anti_namesake() -> bool:
    namesake_closed = _refused(
        lambda: bind_campaign_credential_classes(NAMESAKE_CAMPAIGN_CLASSES)
    )
    a2_as_classes = _refused(lambda: bind_campaign_credential_classes(_A2_PROBES))
    a2_not_this_gate = all(name not in REFUSAL_CLASSES for name in _A2_PROBES)
    a2_remain_readiness = all(name in EXPECTED_PROBES for name in _A2_PROBES)
    authorised = not _refused(
        lambda: bind_campaign_credential_classes(EXPECTED_CREDENTIAL_CLASSES)
    )
    return (
        namesake_closed
        and a2_as_classes
        and a2_not_this_gate
        and a2_remain_readiness
        and authorised
    )


def _refusal_payload(
    records: tuple[RefusalDigest, ...],
) -> list[dict[str, str | bool | int]]:
    return [
        {
            "after_digest": item.after_digest,
            "before_digest": item.before_digest,
            "count": item.count,
            "engaged": item.engaged,
            "refusal_class": item.refusal_class,
        }
        for item in records
    ]


def assess(inventory: Path, *, probe: Probe | None = None) -> QualificationEvidence:
    """Assess that all ten credential-scope refusal classes engage deterministically.

    Fails closed if:
    - Inventory missing or inaccessible
    - Any refusal class surface missing or unexpected
    - Any digest changes without claimed engagement
    - Probe mutates any surface (fail-closed invariant)
    - Any refusal fails to engage
    """
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    writer = default_probe if probe is None else probe
    bound_resolver()
    bind_inventory(EXPECTED_CREDENTIAL_CLASSES, PROHIBITED_CREDENTIAL_CLASSES)
    before = {rc: _digest_file(path) for rc, path in surfaces}
    engaged_count = 0
    for rc, path in surfaces:
        if writer(rc, path):
            engaged_count += 1
    after = {rc: _digest_file(path) for rc, path in surfaces}
    if any(before[rc] != after[rc] for rc in REFUSAL_CLASSES):
        raise QualificationError("refusal surface digest mutated")
    if engaged_count != len(REFUSAL_CLASSES):
        raise QualificationError(
            f"not all refusals engaged: {engaged_count}/{len(REFUSAL_CLASSES)}"
        )
    records = tuple(
        RefusalDigest(rc, before[rc], after[rc], True, 1) for rc in REFUSAL_CLASSES
    )
    principal = FIXTURE_PRINCIPAL_DIGEST
    inventory_id = inventory_digest()
    payload = {
        "gate_id": GATE_ID,
        "inventory_digest": inventory_id,
        "principal_digest": principal,
        "refusals": _refusal_payload(records),
        "refusals_engaged": engaged_count,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
    }
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        refusals_engaged=engaged_count,
        refusals=records,
        principal_digest=principal,
        inventory_digest=inventory_id,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""
    payload = {
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "inventory_digest": evidence.inventory_digest,
        "principal_digest": evidence.principal_digest,
        "refusals": _refusal_payload(evidence.refusals),
        "refusals_engaged": evidence.refusals_engaged,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
    }
    return canonical_json_bytes(payload)
