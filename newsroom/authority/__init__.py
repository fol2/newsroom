"""Public authority contracts for Increment 1A1/A2a/A2b.

Mutation-capable SQLite/blob persistence, authentication contexts, authorization
records, rights records and commit capabilities remain internal. Application code
receives only authenticated command, metadata and governed-object facades.
"""

from .auth import AuthenticationError, AuthenticationProof, AuthorizationDenied, StaticAuthenticator, StaticAuthorizer, StaticPrincipal
from .canonical import CanonicalizationError, canonical_json_bytes, digest_bytes, digest_canonical, validate_sha256_digest
from .models import CommandDefinition, CommandValidationError, CommittedCommandIdentity, InlinePayload, NO_PAYLOAD, NoPayload, ObjectAdmissionDescriptor, ObjectAdmissionPayload, SemanticCommand
from .object_system import AuthorityObjectSystem, open_authority_object_system
from .objects import (
    AuthorityObjects,
    HydratedObject,
    ObjectAdmissionDefinition,
    ObjectAdmissionDenied,
    ObjectAdmissionReceipt,
    ObjectAdmissionRegistry,
    ObjectAdmissionRequest,
    ObjectDeletionReceipt,
    ObjectHydrationDenied,
    ObjectIntegrityError,
    ObjectLifecycleError,
    ObjectLimitError,
    ObjectLimits,
    ObjectPolicyError,
    StaticRightsResolver,
    StaticRightsRule,
)
from .persistence import AuthenticationContextRecord, AuthorityCommands, AuthorityEvents, AuthorityPersistenceError, AuthoritySchemaError, AuthorityWriterBusy, AuthorizationDecisionRecord, CommandResultRecord, CommittedCommand, EventProvenanceRecord, ExpectedVersionConflict, IdempotencyConflict, LedgerEventRecord, UnknownCausation, UnsupportedPayloadMode
from .policy import CommandRegistry, PayloadSchemaContract, PayloadSchemaRegistry, PayloadSchemaValidationError, UnknownCommandDefinition, UnknownPayloadSchema
from .service import AuthorizationReceipt, CommandService, CommittedCommandLookup, IdempotencyIdentityConflict, ObjectAdmissionLookup
from .system import AuthorityEventSystem, open_authority_event_system
from .traceability import INCREMENT_1A_TRACEABILITY
from .types import AggregateId, AggregateVersion, AuditId, AuthenticationContextId, AuthorizationDecisionId, CausationKind, CausationRef, CommandId, CorrelationId, EventId, ObjectAdmissionId, PayloadId, PayloadMode, RightsDecisionId, TemporalValue, TimePrecision, TrustScope, UtcTimestamp

__all__ = [
    "AggregateId", "AggregateVersion", "AuditId", "AuthenticationContextId",
    "AuthenticationContextRecord", "AuthenticationError", "AuthenticationProof",
    "AuthorityCommands", "AuthorityEventSystem", "AuthorityEvents", "AuthorityObjectSystem",
    "AuthorityObjects", "AuthorityPersistenceError", "AuthoritySchemaError", "AuthorityWriterBusy",
    "AuthorizationDecisionId", "AuthorizationDecisionRecord", "AuthorizationDenied",
    "AuthorizationReceipt", "CanonicalizationError", "CausationKind", "CausationRef",
    "CommandDefinition", "CommandId", "CommandRegistry", "CommandResultRecord", "CommandService",
    "CommandValidationError", "CommittedCommand", "CommittedCommandIdentity", "CommittedCommandLookup",
    "CorrelationId", "EventId", "EventProvenanceRecord", "ExpectedVersionConflict",
    "HydratedObject", "INCREMENT_1A_TRACEABILITY", "IdempotencyConflict",
    "IdempotencyIdentityConflict", "InlinePayload", "LedgerEventRecord", "NO_PAYLOAD", "NoPayload",
    "ObjectAdmissionDefinition", "ObjectAdmissionDenied", "ObjectAdmissionDescriptor",
    "ObjectAdmissionId", "ObjectAdmissionLookup", "ObjectAdmissionPayload", "ObjectAdmissionReceipt",
    "ObjectAdmissionRegistry", "ObjectAdmissionRequest", "ObjectDeletionReceipt", "ObjectHydrationDenied",
    "ObjectIntegrityError", "ObjectLifecycleError", "ObjectLimitError", "ObjectLimits", "ObjectPolicyError",
    "PayloadId", "PayloadMode", "PayloadSchemaContract", "PayloadSchemaRegistry",
    "PayloadSchemaValidationError", "RightsDecisionId", "SemanticCommand", "StaticAuthenticator",
    "StaticAuthorizer", "StaticPrincipal", "StaticRightsResolver", "StaticRightsRule", "TemporalValue",
    "TimePrecision", "TrustScope", "UnknownCausation", "UnknownCommandDefinition", "UnknownPayloadSchema",
    "UnsupportedPayloadMode", "UtcTimestamp", "canonical_json_bytes", "digest_bytes", "digest_canonical",
    "open_authority_event_system", "open_authority_object_system", "validate_sha256_digest",
]
