from __future__ import annotations

import sqlite3

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.sources.definition_models import (
    SourceDefinitionRequest,
    SourceDefinitionVersionRequest,
)
from newsroom.sources.policy import (
    SOURCE_DEFINITION_REGISTER_COMMAND,
    SOURCE_DEFINITION_VERSION_RECORD_COMMAND,
)
from newsroom.sources.record_models import (
    SourceDefinition,
    SourceDefinitionVersion,
)
from newsroom.sources.types import SourceVersionConflict


class _SourceRegistryDefinitionCommitMixin:
    def commit_source_definition(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: SourceDefinitionRequest,
    ) -> SourceDefinition:
        if not isinstance(request, SourceDefinitionRequest):
            raise TypeError(
                "source definition commit requires a typed request"
            )
        self._require_source_grant(
            grant,
            command_type=SOURCE_DEFINITION_REGISTER_COMMAND,
            aggregate_id=str(request.definition_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._source_definition_for_event(
                    conn, committed.event_id, replayed=True
                )
            self._ensure_identifier_absent(
                conn,
                table="source_definitions",
                column="definition_id",
                identifier=str(request.definition_id),
                identity="source definition identity",
            )
            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._source_definition_for_event(
                    conn, committed.event_id, replayed=True
                )
            conn.execute(
                "INSERT INTO source_definitions("
                "definition_id,name,editorial_purpose,authority_event_id,"
                "authority_aggregate_version,canonical_bytes,canonical_digest,"
                "recorded_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(request.definition_id),
                    request.name,
                    request.editorial_purpose,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            return self._source_definition_for_event(
                conn, committed.event_id, replayed=False
            )

    def commit_source_definition_version(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: SourceDefinitionVersionRequest,
    ) -> SourceDefinitionVersion:
        if not isinstance(request, SourceDefinitionVersionRequest):
            raise TypeError("source version commit requires a typed request")
        self._require_source_grant(
            grant,
            command_type=SOURCE_DEFINITION_VERSION_RECORD_COMMAND,
            aggregate_id=str(request.version_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=self._clock().to_text()
                )
                return self._source_version_for_event(
                    conn, committed.event_id, replayed=True
                )
            self._definition_row(conn, request.definition_id)
            self._ensure_identifier_absent(
                conn,
                table="source_definition_versions",
                column="version_id",
                identifier=str(request.version_id),
                identity="source definition version identity",
            )
            self._ensure_semantic_absent(
                conn,
                table="source_definition_versions",
                predicate="definition_id=? AND semantic_digest=?",
                parameters=(
                    str(request.definition_id),
                    request.semantic_digest,
                ),
                identity="source definition version semantics",
            )
            current = self._current_version_row(
                conn, request.definition_id
            )
            if current is None:
                if (
                    request.version_number != 1
                    or request.expected_previous_version_id is not None
                ):
                    raise SourceVersionConflict(
                        "initial source definition version must be version one"
                    )
            elif (
                request.version_number
                != int(current["current_version_number"]) + 1
                or request.expected_previous_version_id is None
                or str(request.expected_previous_version_id)
                != str(current["current_version_id"])
            ):
                raise SourceVersionConflict(
                    "source definition version does not extend the exact head"
                )
            for dependency in request.dependencies:
                upstream = dependency.upstream_source_definition_id
                if upstream is None:
                    continue
                if upstream == request.definition_id:
                    raise SourceVersionConflict(
                        "source definition cannot depend directly on itself"
                    )
                self._definition_row(conn, upstream)

            recorded_at = self._clock().to_text()
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=recorded_at
            )
            if committed.replayed:
                return self._source_version_for_event(
                    conn, committed.event_id, replayed=True
                )
            baseline = request.baseline_policy
            conn.execute(
                "INSERT INTO source_definition_versions("
                "version_id,definition_id,version_number,previous_version_id,"
                "locator,locator_digest,adapter_policy_id,adapter_policy_version,"
                "extraction_scope_bytes,rights_decision_id,rights_policy_version,"
                "allowed_use,source_retention_scope,observation_model,"
                "baseline_policy_id,baseline_policy_version,baseline_kind,"
                "baseline_freshness_seconds,baseline_reset_requires_decision,"
                "baseline_notes,item_identity_policy_id,item_identity_policy_version,"
                "revision_policy_id,revision_policy_version,"
                "canonicalization_policy_id,canonicalization_policy_version,"
                "lifecycle_stage,change_reason,execution_authority,semantic_digest,"
                "authority_event_id,authority_aggregate_version,canonical_bytes,"
                "canonical_digest,recorded_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(request.version_id),
                    str(request.definition_id),
                    request.version_number,
                    (
                        None
                        if request.expected_previous_version_id is None
                        else str(request.expected_previous_version_id)
                    ),
                    request.locator,
                    request.locator_digest,
                    request.adapter_contract.policy_id,
                    request.adapter_contract.policy_version,
                    self._json_blob(list(request.extraction_scope)),
                    request.rights.rights_decision_id,
                    request.rights.rights_policy_version,
                    request.rights.allowed_use,
                    request.rights.retention_scope,
                    request.observation_model.value,
                    baseline.reference.policy_id,
                    baseline.reference.policy_version,
                    baseline.kind.value,
                    baseline.freshness_window_seconds,
                    int(baseline.reset_requires_decision),
                    baseline.notes,
                    request.item_identity_policy.policy_id,
                    request.item_identity_policy.policy_version,
                    request.revision_policy.policy_id,
                    request.revision_policy.policy_version,
                    request.canonicalization_policy.policy_id,
                    request.canonicalization_policy.policy_version,
                    request.lifecycle_stage.value,
                    request.change_reason,
                    request.execution_authority,
                    request.semantic_digest,
                    committed.event_id,
                    committed.aggregate_version,
                    request.canonical_bytes,
                    request.digest,
                    recorded_at,
                ),
            )
            self._insert_source_version_children(conn, request=request)
            if current is None:
                conn.execute(
                    "INSERT INTO source_definition_version_heads("
                    "definition_id,current_version_number,current_version_id,"
                    "updated_at) VALUES(?,?,?,?)",
                    (
                        str(request.definition_id),
                        request.version_number,
                        str(request.version_id),
                        recorded_at,
                    ),
                )
            else:
                cursor = conn.execute(
                    "UPDATE source_definition_version_heads "
                    "SET current_version_number=?,current_version_id=?,"
                    "updated_at=? WHERE definition_id=? AND current_version_id=?",
                    (
                        request.version_number,
                        str(request.version_id),
                        recorded_at,
                        str(request.definition_id),
                        str(request.expected_previous_version_id),
                    ),
                )
                if cursor.rowcount != 1:
                    raise AuthorityPersistenceError(
                        "source version head changed during commit"
                    )
            return self._source_version_for_event(
                conn, committed.event_id, replayed=False
            )

    def _insert_source_version_children(
        self,
        conn: sqlite3.Connection,
        *,
        request: SourceDefinitionVersionRequest,
    ) -> None:
        version_id = str(request.version_id)
        for role in request.roles:
            canonical = self._json_blob(role.canonical_value())
            conn.execute(
                "INSERT INTO source_version_roles("
                "version_id,role,purpose,limitations_bytes,canonical_bytes,"
                "canonical_digest) VALUES(?,?,?,?,?,?)",
                (
                    version_id,
                    role.role.value,
                    role.purpose,
                    self._json_blob(list(role.limitations)),
                    canonical,
                    self._digest_value(role.canonical_value()),
                ),
            )
        for function in request.portfolio_functions:
            conn.execute(
                "INSERT INTO source_version_portfolio_functions("
                "version_id,portfolio_function) VALUES(?,?)",
                (version_id, function.value),
            )
        for gap in request.explicit_gaps:
            canonical = self._json_blob(gap.canonical_value())
            conn.execute(
                "INSERT INTO source_version_gaps("
                "version_id,gap_id,gap_class,description,launch_blocking,"
                "canonical_bytes,canonical_digest) VALUES(?,?,?,?,?,?,?)",
                (
                    version_id,
                    gap.gap_id,
                    gap.gap_class,
                    gap.description,
                    int(gap.launch_blocking),
                    canonical,
                    self._digest_value(gap.canonical_value()),
                ),
            )
        for mapping in request.coverage_mappings:
            canonical = self._json_blob(mapping.canonical_value())
            conn.execute(
                "INSERT INTO source_version_coverage_mappings("
                "version_id,obligation_id,responsibility,contribution,"
                "geographies_bytes,languages_bytes,limitations_bytes,"
                "explicit_gap_id,canonical_bytes,canonical_digest) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    mapping.obligation_id,
                    mapping.responsibility.value,
                    mapping.contribution.value,
                    self._json_blob(list(mapping.geographies)),
                    self._json_blob(list(mapping.languages)),
                    self._json_blob(list(mapping.limitations)),
                    mapping.explicit_gap_id,
                    canonical,
                    self._digest_value(mapping.canonical_value()),
                ),
            )
        for dependency in request.dependencies:
            canonical = self._json_blob(dependency.canonical_value())
            conn.execute(
                "INSERT INTO source_version_dependencies("
                "version_id,dependency_id,dependency_kind,description,"
                "upstream_definition_id,canonical_bytes,canonical_digest) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    version_id,
                    dependency.dependency_id,
                    dependency.kind.value,
                    dependency.description,
                    (
                        None
                        if dependency.upstream_source_definition_id is None
                        else str(dependency.upstream_source_definition_id)
                    ),
                    canonical,
                    self._digest_value(dependency.canonical_value()),
                ),
            )


__all__ = ["_SourceRegistryDefinitionCommitMixin"]
