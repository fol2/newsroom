from __future__ import annotations

from typing import Any, Mapping

from newsroom.retrieval.models import FindRelatedEventCandidatesRequest
from newsroom.retrieval.fixture_v2 import IntegratedFixtureV2RetrievalContract
from newsroom.retrieval.policy import HybridRetrievalPolicy

from ._security import _AuthorizationRequest
from .canonical import digest_canonical


RETRIEVAL_REQUIRED_SCOPE = "authority.retrieval.read"
RETRIEVAL_SECURITY_SCOPE = "authority.retrieval"
RETRIEVAL_RETENTION_SCOPE = "authority.audit"
RETRIEVAL_AGGREGATE_TYPE = "retrieval_context_v2"
RETRIEVAL_EVENT_TYPE = "retrieval.context.read"
RETRIEVAL_EVENT_SCHEMA_VERSION = 2
RETRIEVAL_PAYLOAD_MODE = "NO_PAYLOAD"
RETRIEVAL_PAYLOAD_SCHEMA_VERSION = "retrieval_context_v2"
RETRIEVAL_PAYLOAD_SCHEMA_CONTRACT_VERSION = (
    "bounded-hybrid-retrieval-authorization-v1"
)
RETRIEVAL_PAYLOAD_CANONICALIZER_VERSION = "retrieval-read-none-v1"
RETRIEVAL_TRUST_SCOPE = "ADMITTED"


def retrieval_authorization_schema_digest(
    policy: HybridRetrievalPolicy,
) -> str:
    return digest_canonical(
        {
            "contract": RETRIEVAL_PAYLOAD_SCHEMA_CONTRACT_VERSION,
            "payload_mode": RETRIEVAL_PAYLOAD_MODE,
            "tool": policy.tool_name,
            "tool_version": policy.tool_version,
        }
    )


def retrieval_stable_semantic_digest(
    *,
    request: FindRelatedEventCandidatesRequest,
    policy: HybridRetrievalPolicy,
    retrieval_contract: IntegratedFixtureV2RetrievalContract,
) -> str:
    return digest_canonical(
        {
            "policy_digest": policy.contract_digest,
            "retrieval_contract_digest": retrieval_contract.contract_digest,
            "request": request.canonical_value(),
        }
    )


def retrieval_authorization_unsigned(
    *,
    authentication_context_id: str,
    principal_id: str,
    authority_domain: str,
    request: FindRelatedEventCandidatesRequest,
    policy: HybridRetrievalPolicy,
    retrieval_contract: IntegratedFixtureV2RetrievalContract,
) -> dict[str, Any]:
    return {
        "authentication_context_id": authentication_context_id,
        "principal_id": principal_id,
        "authority_domain": authority_domain,
        "operation_type": f"read:{policy.purpose}:{policy.tool_name}",
        "required_scope": RETRIEVAL_REQUIRED_SCOPE,
        "stable_semantic_request_digest": retrieval_stable_semantic_digest(
            request=request,
            policy=policy,
            retrieval_contract=retrieval_contract,
        ),
        "command_definition_digest": policy.contract_digest,
        "aggregate_type": RETRIEVAL_AGGREGATE_TYPE,
        "aggregate_id": str(request.context_id),
        "event_type": RETRIEVAL_EVENT_TYPE,
        "event_schema_version": RETRIEVAL_EVENT_SCHEMA_VERSION,
        "payload_mode": RETRIEVAL_PAYLOAD_MODE,
        "payload_schema_version": RETRIEVAL_PAYLOAD_SCHEMA_VERSION,
        "payload_schema_contract_version": (
            RETRIEVAL_PAYLOAD_SCHEMA_CONTRACT_VERSION
        ),
        "payload_schema_contract_digest": retrieval_authorization_schema_digest(
            policy
        ),
        "payload_canonicalizer_version": (
            RETRIEVAL_PAYLOAD_CANONICALIZER_VERSION
        ),
        "trust_scope": RETRIEVAL_TRUST_SCOPE,
        "security_scope": RETRIEVAL_SECURITY_SCOPE,
        "retention_scope": RETRIEVAL_RETENTION_SCOPE,
        "object_class": None,
        "allowed_use": None,
    }


def retrieval_authorization_request(
    *,
    authentication: Any,
    request: FindRelatedEventCandidatesRequest,
    policy: HybridRetrievalPolicy,
    retrieval_contract: IntegratedFixtureV2RetrievalContract,
) -> _AuthorizationRequest:
    unsigned = retrieval_authorization_unsigned(
        authentication_context_id=str(
            authentication.authentication_context_id
        ),
        principal_id=authentication.principal_id,
        authority_domain=authentication.authority_domain,
        request=request,
        policy=policy,
        retrieval_contract=retrieval_contract,
    )
    typed = dict(unsigned)
    typed.pop("authentication_context_id")
    return _AuthorizationRequest(
        authentication_context_id=authentication.authentication_context_id,
        **typed,
        request_digest=digest_canonical(unsigned),
    )


def require_exact_retrieval_authorization_value(
    *,
    value: Mapping[str, object],
    authentication_context_id: str,
    principal_id: str,
    authority_domain: str,
    request: FindRelatedEventCandidatesRequest,
    policy: HybridRetrievalPolicy,
    retrieval_contract: IntegratedFixtureV2RetrievalContract,
) -> None:
    expected = retrieval_authorization_unsigned(
        authentication_context_id=authentication_context_id,
        principal_id=principal_id,
        authority_domain=authority_domain,
        request=request,
        policy=policy,
        retrieval_contract=retrieval_contract,
    )
    expected_digest = digest_canonical(expected)
    if dict(value) != {**expected, "request_digest": expected_digest}:
        raise ValueError("retrieval authorization request differs from authority")


__all__ = [
    "RETRIEVAL_AGGREGATE_TYPE",
    "RETRIEVAL_EVENT_SCHEMA_VERSION",
    "RETRIEVAL_EVENT_TYPE",
    "RETRIEVAL_PAYLOAD_CANONICALIZER_VERSION",
    "RETRIEVAL_PAYLOAD_MODE",
    "RETRIEVAL_PAYLOAD_SCHEMA_CONTRACT_VERSION",
    "RETRIEVAL_PAYLOAD_SCHEMA_VERSION",
    "RETRIEVAL_REQUIRED_SCOPE",
    "RETRIEVAL_RETENTION_SCOPE",
    "RETRIEVAL_SECURITY_SCOPE",
    "RETRIEVAL_TRUST_SCOPE",
    "require_exact_retrieval_authorization_value",
    "retrieval_authorization_request",
    "retrieval_authorization_schema_digest",
    "retrieval_authorization_unsigned",
    "retrieval_stable_semantic_digest",
]
