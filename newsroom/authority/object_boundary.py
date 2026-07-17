from __future__ import annotations

from dataclasses import replace

from .object_policy import (
    AdmissionPreflight,
    ObjectAdmissionRegistry,
    StaticRightsResolver,
    activate_admission_contract,
    prepare_admission,
)
from .objects import (
    ImmutableBlobIdentity,
    ObjectAdmissionDefinition,
    ObjectAdmissionReceipt,
    ObjectAdmissionRequest,
    ObjectPolicyError,
    RightsDecision,
)
from .types import EventId, UtcTimestamp


def authorize_admission_preflight(
    *,
    registry: ObjectAdmissionRegistry,
    rights_resolver: StaticRightsResolver,
    request: ObjectAdmissionRequest,
    principal_id: str,
    authority_domain: str,
    now: UtcTimestamp,
) -> AdmissionPreflight:
    """Resolve server semantics and fail known denial before staging.

    This public boundary deliberately accepts no bytes, stream, blob digest or
    size. A caller cannot accidentally proceed with a denied preflight result.
    """

    preflight = prepare_admission(
        registry=registry,
        rights_resolver=rights_resolver,
        request=request,
        principal_id=principal_id,
        authority_domain=authority_domain,
        now=now,
    )
    preflight.require_allowed()
    return preflight


def activate_admission_with_event(
    *,
    definition: ObjectAdmissionDefinition,
    blob: ImmutableBlobIdentity,
    rights: RightsDecision,
    activation_event_id: EventId,
    now: UtcTimestamp,
) -> ObjectAdmissionReceipt:
    """Create an ACTIVE admission view only with its ordered event identity."""

    if not isinstance(activation_event_id, EventId):
        raise ObjectPolicyError("activation event identity must be typed")
    receipt = activate_admission_contract(
        definition=definition,
        blob=blob,
        rights=rights,
        now=now,
    )
    return replace(receipt, activation_event_id=activation_event_id)


__all__ = [
    "activate_admission_with_event",
    "authorize_admission_preflight",
]
