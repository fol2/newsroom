from __future__ import annotations

from pathlib import Path
from typing import Any

from ._capability import _CapabilityIssuer
from ._event_store import _EventAuthorityStore
from ._object_capability import _ObjectCapabilityIssuer
from ._object_cas import _GovernedCAS
from ._object_store_admission import _ObjectAdmissionStoreMixin
from ._object_store_base import _ObjectStoreBase
from ._object_store_hydration import _ObjectHydrationStoreMixin
from ._object_store_lifecycle import _ObjectLifecycleStoreMixin
from .object_policy import (
    HydrationPolicyRegistry,
    ObjectAdmissionRegistry,
    RightsPolicyRegistry,
)
from .policy import CommandRegistry, PayloadSchemaRegistry
from .types import UtcTimestamp


class _GovernedObjectAuthorityStore(
    _ObjectAdmissionStoreMixin,
    _ObjectLifecycleStoreMixin,
    _ObjectHydrationStoreMixin,
    _ObjectStoreBase,
    _EventAuthorityStore,
):
    """Private A2b SQLite/CAS authority writer.

    Public application code never receives this object. All mutations require
    independently verified A1 or A2b capabilities.
    """

    def __init__(
        self,
        path: Path,
        *,
        issuer: _CapabilityIssuer,
        object_issuer: _ObjectCapabilityIssuer,
        command_registry: CommandRegistry,
        payload_schemas: PayloadSchemaRegistry,
        admission_registry: ObjectAdmissionRegistry,
        rights_policies: RightsPolicyRegistry,
        hydration_policies: HydrationPolicyRegistry,
        cas: _GovernedCAS,
        command_service_version: str,
        busy_timeout_ms: int = 5_000,
        clock: Any = UtcTimestamp.now,
    ) -> None:
        # Object registries and CAS must exist before the base SQLite lifecycle
        # runs migration/integrity hooks through this class's MRO.
        self._object_issuer = object_issuer
        self._admission_registry = admission_registry
        self._rights_policies = rights_policies
        self._hydration_policies = hydration_policies
        self._cas = cas
        super().__init__(
            path,
            issuer=issuer,
            command_registry=command_registry,
            payload_schemas=payload_schemas,
            command_service_version=command_service_version,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        try:
            self._configure_object_store(
                object_issuer=object_issuer,
                admission_registry=admission_registry,
                rights_policies=rights_policies,
                hydration_policies=hydration_policies,
                cas=cas,
            )
        except Exception:
            self.close()
            raise


__all__ = ["_GovernedObjectAuthorityStore"]
