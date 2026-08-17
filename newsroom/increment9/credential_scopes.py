"""Least-privilege CredentialRef resolver for Increment 9Q-5.

Injected fixture store only. No Keychain, daemon or network. Resolution
returns class, scope and digest — never secret bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.deployment import (
    EXPECTED_CREDENTIAL_CLASSES,
    PROHIBITED_CREDENTIAL_CLASSES,
)
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN

DETERMINISTIC_BOUNDARY = "DETERMINISTIC_BOUNDARY"
CREDENTIAL_SCOPE = "INCREMENT9_SHADOW"
FIXTURE_PRINCIPAL_DIGEST = "sha256:" + "e" * 64
FIXTURE_PRODUCTION_NAMES = ("PRODUCTION_NEO4J", "PRODUCTION_SQLITE")
NAMESAKE_CAMPAIGN_CLASSES = (
    "NEO4J_SHADOW_WRITER",
    "OPENAI_CODEX_LOGIN",
    "OPENAI_EMBEDDINGS_API",
)
MODEL_FAMILY_LOGIN = {
    "ANTHROPIC_AGENT_SDK": "ANTHROPIC_AGENT_SDK",
    "GOOGLE_GEMINI_API": "GOOGLE_GEMINI_API",
    "OPENAI_CODEX_LOGIN": "OPENAI_CODEX_LOGIN",
    "XAI_GROK_BUILD_LOGIN": "XAI_GROK_BUILD_LOGIN",
}
BOUNDARY_ONLY_CLASSES = frozenset(
    {
        "NEO4J_SHADOW_WRITER",
        "OPENAI_EMBEDDINGS_API",
        "SOURCE_OWNER_PROVISIONED",
    }
)
ADMITTED_HANDLES = frozenset({DETERMINISTIC_BOUNDARY, *MODEL_FAMILY_LOGIN})
_SECRET_KEYS = frozenset(
    {"api_key", "credential_value", "password", "secret", "secret_bytes"}
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_REF_FIELDS = frozenset({"credential_class", "digest", "scope"})


class CredentialScopeError(ValueError):
    """Credential resolution or inventory bind failed closed."""


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """Metadata-only credential handle: class, scope and digest. Never secret bytes."""

    credential_class: str
    scope: str
    digest: str

    def __post_init__(self) -> None:
        _token(self.credential_class, "credential_class")
        _token(self.scope, "scope")
        try:
            object.__setattr__(
                self, "digest", validate_sha256_digest(self.digest, field="digest")
            )
        except (CanonicalizationError, TypeError, ValueError) as exc:
            raise CredentialScopeError("credential digest differs") from exc

    def primitive(self) -> dict[str, str]:
        return {
            "credential_class": self.credential_class,
            "digest": self.digest,
            "scope": self.scope,
        }


def _token(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise CredentialScopeError(f"{field} token is malformed")
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > 256 or _TOKEN.fullmatch(value) is None:
        raise CredentialScopeError(f"{field} token is malformed")
    return value


def _od012_classes() -> set[str]:
    decisions = {
        item.decision_id: item.selection
        for item in INCREMENT_9_SHADOW_PLAN.owner_decisions
    }
    classes = decisions["OD-012"]["credential_classes_and_secret_locations"]["classes"]
    return set(classes)


def inventory_digest() -> str:
    """Canonical digest of the OD-012 seven-permitted-plus-one-prohibited split."""

    return digest_bytes(
        canonical_json_bytes(
            {
                "permitted_credential_classes": list(EXPECTED_CREDENTIAL_CLASSES),
                "prohibited_credential_classes": list(PROHIBITED_CREDENTIAL_CLASSES),
            }
        )
    )


def bind_inventory(
    permitted: tuple[str, ...], prohibited: tuple[str, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Refuse inventory drift against the OD-012 split and the deployment contract."""

    if type(permitted) is not tuple or type(prohibited) is not tuple:
        raise CredentialScopeError("credential class inventory type differs")
    if permitted != tuple(sorted(set(permitted))) or not permitted:
        raise CredentialScopeError("permitted credential classes are not unique and sorted")
    if prohibited != tuple(sorted(set(prohibited))) or not prohibited:
        raise CredentialScopeError("prohibited credential classes are not unique and sorted")
    if set(permitted) & set(prohibited):
        raise CredentialScopeError("credential class boundaries overlap")
    expected = _od012_classes()
    if set(permitted) | set(prohibited) != expected:
        raise CredentialScopeError("credential classes differ from OD-012")
    if permitted != EXPECTED_CREDENTIAL_CLASSES:
        raise CredentialScopeError("permitted credential classes differ from OD-012")
    if prohibited != PROHIBITED_CREDENTIAL_CLASSES:
        raise CredentialScopeError("prohibited credential classes differ from OD-012")
    return permitted, prohibited


def bind_campaign_credential_classes(classes: tuple[str, ...]) -> tuple[str, ...]:
    """Campaign BASELINE_CREDENTIAL_SCOPES inventory: OD-012 permitted classes only.

    The historical three-class namesake list cannot PASS.
    """

    if type(classes) is not tuple or classes != EXPECTED_CREDENTIAL_CLASSES:
        raise CredentialScopeError("campaign credential classes differ from OD-012")
    bind_inventory(EXPECTED_CREDENTIAL_CLASSES, PROHIBITED_CREDENTIAL_CLASSES)
    return classes


def credential_ref_from_primitive(value: object) -> CredentialRef:
    """Load a CredentialRef, refusing secret bytes or extra fields."""

    if type(value) is not dict:
        raise CredentialScopeError("credential ref is not an object")
    if _SECRET_KEYS & set(value):
        raise CredentialScopeError("secret bytes are prohibited in a credential ref")
    if set(value) != _REF_FIELDS:
        raise CredentialScopeError("credential ref fields differ")
    ref = CredentialRef(
        credential_class=_token(value["credential_class"], "credential_class"),
        scope=_token(value["scope"], "scope"),
        digest=value["digest"],  # type: ignore[arg-type]
    )
    if set(ref.primitive()) != _REF_FIELDS:
        raise CredentialScopeError("secret bytes are prohibited in a credential ref")
    return ref


def fixture_credential_refs() -> tuple[CredentialRef, ...]:
    """Synthetic metadata-only store for the seven permitted classes."""

    return tuple(
        CredentialRef(
            credential_class=cls,
            scope=CREDENTIAL_SCOPE,
            digest=digest_bytes(
                canonical_json_bytes(
                    {"credential_class": cls, "scope": CREDENTIAL_SCOPE}
                )
            ),
        )
        for cls in EXPECTED_CREDENTIAL_CLASSES
    )


@dataclass(frozen=True, slots=True)
class CredentialResolver:
    """Injected-store resolver bound to one principal digest."""

    bound_principal_digest: str
    store: tuple[CredentialRef, ...]

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "bound_principal_digest",
                validate_sha256_digest(
                    self.bound_principal_digest, field="principal_identity_digest"
                ),
            )
        except (CanonicalizationError, TypeError, ValueError) as exc:
            raise CredentialScopeError("principal digest differs") from exc
        bind_inventory(EXPECTED_CREDENTIAL_CLASSES, PROHIBITED_CREDENTIAL_CLASSES)
        if type(self.store) is not tuple or not self.store:
            raise CredentialScopeError("credential store differs")
        by_class = {}
        for item in self.store:
            if type(item) is not CredentialRef:
                raise CredentialScopeError("store entry is not a CredentialRef")
            if set(item.primitive()) != _REF_FIELDS:
                raise CredentialScopeError("secret bytes are prohibited in a credential ref")
            if item.credential_class in by_class:
                raise CredentialScopeError("store contains a duplicate class")
            by_class[item.credential_class] = item
        if tuple(sorted(by_class)) != EXPECTED_CREDENTIAL_CLASSES:
            raise CredentialScopeError("store inventory differs from OD-012")
        object.__setattr__(self, "store", tuple(by_class[cls] for cls in EXPECTED_CREDENTIAL_CLASSES))

    def _lookup(self) -> Mapping[str, CredentialRef]:
        return {item.credential_class: item for item in self.store}

    def resolve(
        self, principal: str, handle: str, credential_class: str
    ) -> CredentialRef:
        """Return a metadata CredentialRef or refuse fail-closed."""

        _token(principal, "principal")
        try:
            principal = validate_sha256_digest(principal, field="principal")
        except (CanonicalizationError, TypeError, ValueError) as exc:
            raise CredentialScopeError("principal token is malformed") from exc
        _token(handle, "handle")
        _token(credential_class, "credential_class")
        if handle not in ADMITTED_HANDLES:
            raise CredentialScopeError("handle token is malformed")
        if principal != self.bound_principal_digest:
            raise CredentialScopeError("principal digest differs")
        if credential_class in FIXTURE_PRODUCTION_NAMES:
            raise CredentialScopeError("production store name is refused")
        if credential_class == "PUBLICATION_TARGET_ADAPTER":
            raise CredentialScopeError("publication credential is refused")
        if credential_class not in EXPECTED_CREDENTIAL_CLASSES:
            raise CredentialScopeError("unknown credential class")
        if handle != DETERMINISTIC_BOUNDARY:
            if credential_class in BOUNDARY_ONLY_CLASSES:
                raise CredentialScopeError(
                    "model-family handle cannot resolve a boundary-only class"
                )
            if credential_class != MODEL_FAMILY_LOGIN[handle]:
                raise CredentialScopeError(
                    "model-family handle may resolve only its own login class"
                )
        ref = self._lookup()[credential_class]
        if set(ref.primitive()) != _REF_FIELDS:
            raise CredentialScopeError("secret bytes are prohibited in a credential ref")
        return ref


def bound_resolver(
    *,
    principal_digest: str = FIXTURE_PRINCIPAL_DIGEST,
    store: tuple[CredentialRef, ...] | None = None,
) -> CredentialResolver:
    return CredentialResolver(
        bound_principal_digest=principal_digest,
        store=store if store is not None else fixture_credential_refs(),
    )


def resolve(
    principal: str,
    handle: str,
    credential_class: str,
    *,
    resolver: CredentialResolver | None = None,
) -> CredentialRef:
    """Resolve against the injected fixture store. Never returns secret bytes."""

    active = resolver if resolver is not None else bound_resolver()
    return active.resolve(principal, handle, credential_class)
