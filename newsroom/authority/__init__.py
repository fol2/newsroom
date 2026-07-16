"""Public command-boundary contract for Newsroom authority Increment 1A1.

Mutation-capable persistence, authentication contexts, authorization decisions,
commit capabilities and blob storage are deliberately internal and are not
exported from this package.
"""

from .auth import (
    AuthenticationError,
    AuthenticationProof,
    AuthorizationDenied,
    StaticAuthenticator,
    StaticAuthorizer,
    StaticPrincipal,
)
from .canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    digest_canonical,
    validate_sha256_digest,
)
from .models import (
    CommandDefinition,
    CommandValidationError,
    InlinePayload,
    NO_PAYLOAD,
    NoPayload,
    ObjectAdmissionDescriptor,
    ObjectAdmissionPayload,
    SemanticCommand,
)
from .policy import CommandRegistry, UnknownCommandDefinition
from .service import AuthorizationReceipt, CommandService, ObjectAdmissionLookup
from .traceability import INCREMENT_1A_TRACEABILITY
from .types import (
    AggregateId,
    AggregateVersion,
    AuditId,
    AuthenticationContextId,
    AuthorizationDecisionId,
    CausationKind,
    CausationRef,
    CommandId,
    CorrelationId,
    EventId,
    ObjectAdmissionId,
    PayloadMode,
    RightsDecisionId,
    TemporalValue,
    TimePrecision,
    TrustScope,
    UtcTimestamp,
)

__all__ = [
    "AggregateId",
    "AggregateVersion",
    "AuditId",
    "AuthenticationContextId",
    "AuthenticationError",
    "AuthenticationProof",
    "AuthorizationDecisionId",
    "AuthorizationDenied",
    "AuthorizationReceipt",
    "CanonicalizationError",
    "CausationKind",
    "CausationRef",
    "CommandDefinition",
    "CommandId",
    "CommandRegistry",
    "CommandService",
    "CommandValidationError",
    "CorrelationId",
    "EventId",
    "INCREMENT_1A_TRACEABILITY",
    "InlinePayload",
    "NO_PAYLOAD",
    "NoPayload",
    "ObjectAdmissionDescriptor",
    "ObjectAdmissionId",
    "ObjectAdmissionLookup",
    "ObjectAdmissionPayload",
    "PayloadMode",
    "RightsDecisionId",
    "SemanticCommand",
    "StaticAuthenticator",
    "StaticAuthorizer",
    "StaticPrincipal",
    "TemporalValue",
    "TimePrecision",
    "TrustScope",
    "UnknownCommandDefinition",
    "UtcTimestamp",
    "canonical_json_bytes",
    "digest_bytes",
    "digest_canonical",
    "validate_sha256_digest",
]
