from __future__ import annotations

import sqlite3
from collections.abc import Callable

from newsroom.authority._capability import _AuthorizedCommandGrant
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.authority.types import UtcTimestamp
from newsroom.extraction.models import ExtractionRunVersion
from newsroom.extraction.types import ExtractionRunId
from newsroom.graphiti_adapter.models import (
    GraphitiAdapterConfiguration,
    GraphitiAdapterConfigurationRecord,
    GraphitiAdapterExecution,
    GraphitiAttemptRecord,
    GraphitiAttemptRequest,
    GraphitiReplayApprovalRequest,
    GraphitiReplaySource,
    GraphitiReplaySourceRecord,
)
from newsroom.graphiti_adapter.policy import (
    GRAPHITI_ATTEMPT_EXECUTE_COMMAND,
    GRAPHITI_CONFIGURATION_REGISTER_COMMAND,
    GRAPHITI_REPLAY_APPROVE_COMMAND,
)
from newsroom.graphiti_adapter.types import (
    GraphitiAdapterAmbiguousEffect,
    GraphitiAdapterIdentifierReuse,
    GraphitiAdapterOutcome,
    GraphitiAdapterRightsDenied,
    GraphitiAdapterSemanticCollision,
    GraphitiAdapterStateError,
    GraphitiAdapterVersionConflict,
    GraphitiReplayEligibility,
    GraphitiRuntimeMode,
    GraphitiWorkspaceState,
)

from ._graphiti_adapter_store_common import graphiti_event_digest


class _GraphitiAdapterCommitMixin:
    def commit_graphiti_configuration(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        configuration: GraphitiAdapterConfiguration,
    ) -> GraphitiAdapterConfigurationRecord:
        if not isinstance(configuration, GraphitiAdapterConfiguration):
            raise TypeError("adapter configuration commit requires a typed value")
        self._require_graphiti_grant(
            grant,
            command_type=GRAPHITI_CONFIGURATION_REGISTER_COMMAND,
            aggregate_id=str(configuration.configuration_id),
            canonical_bytes=configuration.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            if grant.replay_of_command_id is not None:
                committed = self._commit_grant_in_transaction(
                    conn, grant, recorded_at=now.to_text()
                )
                row = self._graphiti_configuration_row(
                    conn, configuration.configuration_id
                )
                result = self._graphiti_configuration_from_row(
                    conn, row, replayed=True
                )
                self._require_graphiti_configuration_current(conn, result)
                return result

            self._graphiti_ensure_identifier_absent(
                conn,
                table="graphiti_adapter_configurations",
                column="configuration_id",
                identifier=str(configuration.configuration_id),
                identity="Graphiti adapter configuration identity",
            )
            self._graphiti_ensure_semantic_absent(
                conn,
                table="graphiti_adapter_configurations",
                column="semantic_digest",
                digest=configuration.semantic_digest,
                identity="Graphiti adapter configuration semantics",
            )
            contract = self._contract_from_row(
                conn,
                self._contract_row(conn, str(configuration.extractor_contract_id)),
                replayed=False,
            )
            if contract.request.digest != configuration.extractor_contract_digest:
                raise AuthorityPersistenceError(
                    "Graphiti configuration extractor contract differs"
                )
            policy = self._graphiti_workspace_policy_from_row(
                self._graphiti_workspace_policy_row(
                    conn, configuration.workspace_policy.policy_id
                )
            )
            if policy != configuration.workspace_policy:
                raise AuthorityPersistenceError(
                    "Graphiti configuration workspace policy differs"
                )
            if configuration.runtime_mode is GraphitiRuntimeMode.REAL_GRAPHITI:
                configuration.require_execution_authorized()

            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=now.to_text()
            )
            if committed.replayed:
                raise AuthorityPersistenceError(
                    "new Graphiti configuration command unexpectedly replayed"
                )

            components = {
                "framework": configuration.framework,
                "model": configuration.model,
                "embedding": configuration.embedding,
                "prompt": configuration.prompt,
                "output_schema": configuration.output_schema,
                "code": configuration.code,
                "normalisation": configuration.normalisation,
                "temporal_policy": configuration.temporal_policy,
                "adapter_policy": configuration.adapter_policy,
            }
            component_values: list[str] = []
            for name in (
                "framework",
                "model",
                "embedding",
                "prompt",
                "output_schema",
                "code",
                "normalisation",
                "temporal_policy",
                "adapter_policy",
            ):
                item = components[name]
                component_values.extend(
                    [item.component_id, item.component_version, item.contract_digest]
                )
            conn.execute(
                "INSERT INTO graphiti_adapter_configurations("
                "configuration_id,runtime_mode,execution_profile,"
                "framework_id,framework_version,framework_digest,"
                "model_id,model_version,model_digest,"
                "embedding_id,embedding_version,embedding_digest,"
                "prompt_id,prompt_version,prompt_digest,"
                "output_schema_id,output_schema_version,output_schema_digest,"
                "code_id,code_version,code_digest,"
                "normalisation_id,normalisation_version,normalisation_digest,"
                "temporal_policy_id,temporal_policy_version,temporal_policy_digest,"
                "adapter_policy_id,adapter_policy_version,adapter_policy_digest,"
                "extractor_contract_id,extractor_contract_digest,"
                "workspace_policy_id,workspace_policy_digest,fixture_case,"
                "real_runtime_authority_digest,semantic_digest,authority_event_id,"
                "canonical_bytes,canonical_digest,recorded_at) "
                + "VALUES(" + ",".join("?" for _ in range(41)) + ")",
                (
                    str(configuration.configuration_id),
                    configuration.runtime_mode.value,
                    configuration.execution_profile.value,
                    *component_values,
                    str(configuration.extractor_contract_id),
                    configuration.extractor_contract_digest,
                    str(configuration.workspace_policy.policy_id),
                    configuration.workspace_policy.canonical_digest,
                    (
                        None
                        if configuration.fixture_case is None
                        else configuration.fixture_case.value
                    ),
                    (
                        None
                        if configuration.real_runtime_authority is None
                        else configuration.real_runtime_authority.authority_decision_digest
                    ),
                    configuration.semantic_digest,
                    committed.event_id,
                    configuration.canonical_bytes,
                    configuration.canonical_digest,
                    now.to_text(),
                ),
            )
            row = self._graphiti_configuration_row(
                conn, configuration.configuration_id
            )
            return self._graphiti_configuration_from_row(
                conn, row, replayed=False
            )

    def preflight_graphiti_attempt(
        self,
        *,
        attempt: GraphitiAttemptRequest,
        principal_id: str,
    ) -> None:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise TypeError("adapter attempt preflight requires a typed request")
        with self._lock:
            conn = self._connection
            configuration = self._graphiti_configuration_from_row(
                conn,
                self._graphiti_configuration_row(
                    conn, attempt.configuration.configuration_id
                ),
                replayed=False,
            )
            if configuration.configuration != attempt.configuration:
                raise AuthorityPersistenceError(
                    "adapter attempt configuration differs from retained authority"
                )
            self._require_graphiti_configuration_current(conn, configuration)
            now = self._clock()
            try:
                self._require_current_input(
                    conn,
                    request=attempt.extraction_request,
                    now=now,
                    principal_id=principal_id,
                    require_text=True,
                )
            except PermissionError as exc:
                raise GraphitiAdapterRightsDenied(str(exc)) from exc
            head = self._graphiti_attempt_head_row(
                conn, attempt.extraction_request.run_id
            )
            if attempt.attempt_number == 1:
                if head is not None:
                    raise GraphitiAdapterVersionConflict(
                        "initial adapter attempt already has a current head"
                    )
            elif (
                head is None
                or int(head["current_attempt_number"])
                != attempt.attempt_number - 1
                or str(head["current_attempt_id"])
                != str(attempt.expected_previous_attempt_id)
                or bool(head["terminal"])
            ):
                raise GraphitiAdapterVersionConflict(
                    "adapter attempt does not extend the current non-terminal head"
                )
            if attempt.replay_source is not None:
                replay_row = conn.execute(
                    "SELECT * FROM graphiti_replay_sources WHERE replay_source_id=?",
                    (str(attempt.replay_source.replay_source_id),),
                ).fetchone()
                if replay_row is None:
                    raise GraphitiAdapterStateError(
                        "approved replay source is not retained"
                    )
                retained = self._graphiti_replay_source_from_row(
                    conn, replay_row, replayed=False
                )
                if retained.source != attempt.replay_source:
                    raise AuthorityPersistenceError(
                        "adapter replay source differs from retained authority"
                    )

    @staticmethod
    def _workspace_lifecycle_value(
        *,
        workspace_id: str,
        ordinal: int,
        state: GraphitiWorkspaceState,
        reason: str | None,
        recorded_at: str,
    ) -> dict[str, object]:
        return {
            "workspace_id": workspace_id,
            "lifecycle_ordinal": ordinal,
            "state": state.value,
            "reason": reason,
            "recorded_at": recorded_at,
        }

    def _persist_graphiti_attempt_after_extraction(
        self,
        conn: sqlite3.Connection,
        *,
        adapter_grant: _AuthorizedCommandGrant,
        attempt: GraphitiAttemptRequest,
        execution: GraphitiAdapterExecution,
        result: ExtractionRunVersion,
        recorded_at: UtcTimestamp,
    ) -> GraphitiAttemptRecord:
        adapter_grant.authentication.require_current(recorded_at)
        if adapter_grant.authentication.principal_id != result.request.input_binding.passages[0].principal_id:
            raise AuthorityPersistenceError(
                "adapter executor differs from governed hydration principal"
            )
        configuration = self._graphiti_configuration_from_row(
            conn,
            self._graphiti_configuration_row(
                conn, attempt.configuration.configuration_id
            ),
            replayed=False,
        )
        if configuration.configuration != attempt.configuration:
            raise AuthorityPersistenceError(
                "adapter attempt configuration differs from retained authority"
            )
        self._require_graphiti_configuration_current(conn, configuration)
        if execution.attempt != attempt:
            raise AuthorityPersistenceError(
                "adapter execution differs from authorised attempt"
            )
        receipt = execution.produced.attempt_receipt_value
        if attempt.extraction_contract.producer_kind == "GRAPHITI_EVALUATION":
            receipt = execution.produced.raw_output_value or receipt
            if not isinstance(receipt, dict):
                raise AuthorityPersistenceError(
                    "Graphiti execution lacks exact terminal raw receipt"
                )
            unsigned_receipt = dict(receipt)
            receipt_digest = unsigned_receipt.pop("raw_output_digest", None)
            if receipt_digest != digest_bytes(canonical_json_bytes(unsigned_receipt)):
                raise AuthorityPersistenceError("Graphiti terminal receipt digest differs")
            expected_receipt_binding = {
                "workspace_group": attempt.configuration.workspace_policy.namespace_prefix,
                "generation_id": attempt.generation_id,
                "episode_uuid": attempt.episode_uuid,
                "attempt_number": attempt.attempt_number,
                "predecessor_episode_uuid": attempt.predecessor_episode_uuid,
                "temporal_basis": attempt.temporal_basis,
                "reference_time": (
                    None
                    if attempt.reference_time is None
                    else attempt.reference_time.to_text()
                ),
                "passages": [
                    item.canonical_value() for item in attempt.manifest.passages
                ],
            }
            if any(
                receipt.get(key) != value
                for key, value in expected_receipt_binding.items()
            ):
                raise AuthorityPersistenceError(
                    "Graphiti terminal receipt differs from attempt authority"
                )
            receipt_proposals = receipt.get("proposals")
            if not isinstance(receipt_proposals, list) or (
                execution.produced.raw_output_value is not None
                and receipt_proposals
                != [
                    item.canonical_value()
                    for item in execution.produced.proposals
                ]
            ):
                raise AuthorityPersistenceError(
                    "Graphiti terminal receipt proposal evidence differs"
                )
        if execution.cleanup_receipt.recorded_at != execution.ended_at:
            raise AuthorityPersistenceError(
                "adapter cleanup chronology differs from execution"
            )
        self._require_graphiti_workspace_absent(execution.workspace)
        self._graphiti_ensure_identifier_absent(
            conn,
            table="graphiti_adapter_attempts",
            column="attempt_id",
            identifier=str(attempt.attempt_id),
            identity="Graphiti adapter attempt identity",
        )
        for table, column, identifier, identity in (
            (
                "graphiti_workspaces",
                "workspace_id",
                str(attempt.workspace_id),
                "Graphiti workspace identity",
            ),
            (
                "graphiti_input_manifests",
                "manifest_id",
                str(attempt.manifest.manifest_id),
                "Graphiti input manifest identity",
            ),
            (
                "graphiti_cleanup_receipts",
                "receipt_id",
                str(attempt.cleanup_receipt_id),
                "Graphiti cleanup receipt identity",
            ),
        ):
            self._graphiti_ensure_identifier_absent(
                conn,
                table=table,
                column=column,
                identifier=identifier,
                identity=identity,
            )
        head = self._graphiti_attempt_head_row(conn, result.request.run_id)
        if attempt.attempt_number == 1:
            if head is not None:
                raise GraphitiAdapterVersionConflict(
                    "initial adapter attempt already has a current head"
                )
        elif (
            head is None
            or int(head["current_attempt_number"]) != attempt.attempt_number - 1
            or str(head["current_attempt_id"])
            != str(attempt.expected_previous_attempt_id)
            or bool(head["terminal"])
        ):
            raise GraphitiAdapterVersionConflict(
                "adapter attempt does not extend the current non-terminal head"
            )

        committed = self._commit_grant_in_transaction(
            conn, adapter_grant, recorded_at=recorded_at.to_text()
        )
        if committed.replayed:
            raise AuthorityPersistenceError(
                "new adapter execution resolved to an unexpected replay"
            )

        workspace = execution.workspace
        workspace_bytes = canonical_json_bytes(workspace.canonical_value())
        conn.execute(
            "INSERT INTO graphiti_workspaces("
            "workspace_id,configuration_id,policy_id,policy_digest,namespace,"
            "canonical_bytes,canonical_digest,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                str(workspace.workspace_id),
                str(workspace.configuration_id),
                str(workspace.policy_id),
                workspace.policy_digest,
                workspace.namespace,
                workspace_bytes,
                workspace.canonical_digest,
                workspace.created_at.to_text(),
            ),
        )
        lifecycle = (
            (1, GraphitiWorkspaceState.CREATED, None, workspace.created_at),
            (2, GraphitiWorkspaceState.ACTIVE, None, execution.started_at),
            (
                3,
                execution.cleanup_receipt.final_state,
                execution.cleanup_receipt.reason.value,
                execution.cleanup_receipt.recorded_at,
            ),
        )
        for ordinal, state, reason, timestamp in lifecycle:
            value = self._workspace_lifecycle_value(
                workspace_id=str(workspace.workspace_id),
                ordinal=ordinal,
                state=state,
                reason=reason,
                recorded_at=timestamp.to_text(),
            )
            data = canonical_json_bytes(value)
            conn.execute(
                "INSERT INTO graphiti_workspace_lifecycle_events("
                "workspace_id,lifecycle_ordinal,state,reason,canonical_bytes,"
                "canonical_digest,recorded_at) VALUES(?,?,?,?,?,?,?)",
                (
                    str(workspace.workspace_id),
                    ordinal,
                    state.value,
                    reason,
                    data,
                    digest_bytes(data),
                    timestamp.to_text(),
                ),
            )

        manifest = attempt.manifest
        manifest_bytes = manifest.canonical_bytes
        conn.execute(
            "INSERT INTO graphiti_input_manifests("
            "manifest_id,configuration_id,configuration_digest,"
            "extractor_contract_id,extractor_contract_digest,run_id,"
            "requested_run_version_id,requested_version_number,definition_id,"
            "definition_version_id,item_id,revision_id,representation_id,"
            "input_binding_digest,passage_count,canonical_bytes,canonical_digest,"
            "retained_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(manifest.manifest_id),
                str(manifest.configuration_id),
                manifest.configuration_digest,
                str(manifest.extractor_contract_id),
                manifest.extractor_contract_digest,
                str(manifest.run_id),
                str(manifest.requested_run_version_id),
                manifest.requested_version_number,
                str(manifest.definition_id),
                str(manifest.definition_version_id),
                str(manifest.item_id),
                str(manifest.revision_id),
                str(manifest.representation_id),
                manifest.input_binding_digest,
                len(manifest.passages),
                manifest_bytes,
                manifest.canonical_digest,
                recorded_at.to_text(),
            ),
        )
        for ordinal, passage in enumerate(manifest.passages, start=1):
            data = canonical_json_bytes(passage.canonical_value())
            conn.execute(
                "INSERT INTO graphiti_input_manifest_passages("
                "manifest_id,passage_ordinal,run_id,passage_id,admission_id,"
                "access_decision_id,hydration_policy_contract_digest,principal_id,"
                "authority_domain,purpose,object_class,allowed_use,security_scope,"
                "retention_scope,byte_offset,byte_length,blob_digest,text_digest,"
                "language,canonical_bytes,canonical_digest) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(manifest.manifest_id),
                    ordinal,
                    str(manifest.run_id),
                    str(passage.passage_id),
                    str(passage.admission_id),
                    str(passage.access_decision_id),
                    passage.hydration_policy_contract_digest,
                    passage.principal_id,
                    passage.authority_domain,
                    passage.purpose,
                    passage.object_class,
                    passage.allowed_use,
                    passage.security_scope,
                    passage.retention_scope,
                    passage.byte_offset,
                    passage.byte_length,
                    passage.blob_digest,
                    passage.text_digest,
                    passage.language,
                    data,
                    digest_bytes(data),
                ),
            )

        cleanup = execution.cleanup_receipt
        cleanup_bytes = canonical_json_bytes(cleanup.canonical_value())
        conn.execute(
            "INSERT INTO graphiti_cleanup_receipts("
            "receipt_id,workspace_id,final_state,reason,private_node_count,"
            "private_relation_count,file_count,byte_count,workspace_absent,"
            "canonical_bytes,canonical_digest,recorded_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(cleanup.receipt_id),
                str(cleanup.workspace_id),
                cleanup.final_state.value,
                cleanup.reason.value,
                cleanup.private_node_count,
                cleanup.private_relation_count,
                cleanup.file_count,
                cleanup.byte_count,
                int(cleanup.workspace_absent),
                cleanup_bytes,
                cleanup.canonical_digest,
                cleanup.recorded_at.to_text(),
            ),
        )

        output_id = None if result.output is None else result.output.output_id
        proposal_set_id = (
            None if result.proposal_set is None else result.proposal_set.proposal_set_id
        )
        attempt_value = {
            "attempt_id": str(attempt.attempt_id),
            "run_id": str(result.request.run_id),
            "run_version_id": str(result.request.run_version_id),
            "attempt_number": attempt.attempt_number,
            "previous_attempt_id": (
                None
                if attempt.expected_previous_attempt_id is None
                else str(attempt.expected_previous_attempt_id)
            ),
            "configuration_id": str(attempt.configuration.configuration_id),
            "configuration_digest": attempt.configuration.canonical_digest,
            "workspace_id": str(attempt.workspace_id),
            "manifest_id": str(attempt.manifest.manifest_id),
            "outcome": execution.outcome.value,
            "failure_code": execution.failure_code,
            "started_at": execution.started_at.to_text(),
            "ended_at": execution.ended_at.to_text(),
            "usage": result.usage.canonical_value(),
            "output_id": None if output_id is None else str(output_id),
            "proposal_set_id": (
                None if proposal_set_id is None else str(proposal_set_id)
            ),
            "cleanup_receipt_id": str(cleanup.receipt_id),
            "cleanup_receipt_digest": cleanup.canonical_digest,
        }
        attempt_bytes = canonical_json_bytes(attempt_value)
        conn.execute(
            "INSERT INTO graphiti_adapter_attempts("
            "attempt_id,run_id,run_version_id,attempt_number,previous_attempt_id,"
            "configuration_id,configuration_digest,workspace_id,manifest_id,"
            "outcome,failure_code,started_at,ended_at,elapsed_ms,input_bytes,"
            "output_bytes,proposal_count,evidence_range_count,request_tokens,"
            "response_tokens,cost_microunits,extraction_output_id,proposal_set_id,"
            "cleanup_receipt_id,authority_event_id,canonical_bytes,canonical_digest,"
            "recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(attempt.attempt_id),
                str(result.request.run_id),
                str(result.request.run_version_id),
                attempt.attempt_number,
                (
                    None
                    if attempt.expected_previous_attempt_id is None
                    else str(attempt.expected_previous_attempt_id)
                ),
                str(attempt.configuration.configuration_id),
                attempt.configuration.canonical_digest,
                str(attempt.workspace_id),
                str(attempt.manifest.manifest_id),
                execution.outcome.value,
                execution.failure_code,
                execution.started_at.to_text(),
                execution.ended_at.to_text(),
                result.usage.elapsed_ms,
                result.usage.input_bytes,
                result.usage.output_bytes,
                result.usage.proposal_count,
                result.usage.evidence_range_count,
                result.usage.request_tokens,
                result.usage.response_tokens,
                result.usage.cost_microunits,
                None if output_id is None else str(output_id),
                None if proposal_set_id is None else str(proposal_set_id),
                str(cleanup.receipt_id),
                committed.event_id,
                attempt_bytes,
                digest_bytes(attempt_bytes),
                recorded_at.to_text(),
            ),
        )
        if receipt is not None and execution.produced.raw_output_value is None:
            receipt_bytes = canonical_json_bytes(receipt)
            conn.execute(
                "INSERT INTO graphiti_attempt_receipts("
                "attempt_id,run_version_id,canonical_bytes,canonical_digest,retained_at) "
                "VALUES(?,?,?,?,?)",
                (
                    str(attempt.attempt_id),
                    str(result.request.run_version_id),
                    receipt_bytes,
                    digest_bytes(receipt_bytes),
                    recorded_at.to_text(),
                ),
            )
        if attempt.replay_source is not None:
            retained_source_row = conn.execute(
                "SELECT * FROM graphiti_replay_sources WHERE replay_source_id=?",
                (str(attempt.replay_source.replay_source_id),),
            ).fetchone()
            if retained_source_row is None:
                raise AuthorityPersistenceError(
                    "approved replay attempt lacks retained source authority"
                )
            retained_source = self._graphiti_replay_source_from_row(
                conn, retained_source_row, replayed=False
            )
            if retained_source.source != attempt.replay_source:
                raise AuthorityPersistenceError(
                    "approved replay attempt source differs"
                )
            replay_value = {
                "attempt_id": str(attempt.attempt_id),
                "replay_source_id": str(attempt.replay_source.replay_source_id),
            }
            replay_bytes = canonical_json_bytes(replay_value)
            conn.execute(
                "INSERT INTO graphiti_adapter_attempt_replays("
                "attempt_id,replay_source_id,canonical_bytes,canonical_digest) "
                "VALUES(?,?,?,?)",
                (
                    str(attempt.attempt_id),
                    str(attempt.replay_source.replay_source_id),
                    replay_bytes,
                    digest_bytes(replay_bytes),
                ),
            )

        if attempt.attempt_number == 1:
            conn.execute(
                "INSERT INTO graphiti_adapter_attempt_heads("
                "run_id,current_attempt_number,current_attempt_id,terminal,updated_at) "
                "VALUES(?,?,?,?,?)",
                (
                    str(result.request.run_id),
                    attempt.attempt_number,
                    str(attempt.attempt_id),
                    int(execution.outcome.terminal),
                    recorded_at.to_text(),
                ),
            )
        else:
            conn.execute(
                "UPDATE graphiti_adapter_attempt_heads SET "
                "current_attempt_number=?,current_attempt_id=?,terminal=?,updated_at=? "
                "WHERE run_id=?",
                (
                    attempt.attempt_number,
                    str(attempt.attempt_id),
                    int(execution.outcome.terminal),
                    recorded_at.to_text(),
                    str(result.request.run_id),
                ),
            )
        row = self._graphiti_attempt_row(conn, attempt.attempt_id)
        retained = self._graphiti_attempt_from_row(conn, row, replayed=False)
        self._require_graphiti_attempt_current(conn, retained)
        return retained

    def commit_graphiti_attempt(
        self,
        adapter_grant: _AuthorizedCommandGrant,
        extraction_grant: _AuthorizedCommandGrant | None,
        *,
        attempt: GraphitiAttemptRequest,
        execution: GraphitiAdapterExecution | None,
    ) -> GraphitiAttemptRecord:
        if not isinstance(attempt, GraphitiAttemptRequest):
            raise TypeError("adapter attempt commit requires a typed request")
        self._require_graphiti_grant(
            adapter_grant,
            command_type=GRAPHITI_ATTEMPT_EXECUTE_COMMAND,
            aggregate_id=str(attempt.attempt_id),
            canonical_bytes=attempt.canonical_bytes,
        )
        if adapter_grant.replay_of_command_id is not None:
            if extraction_grant is not None or execution is not None:
                raise AuthorityPersistenceError(
                    "exact adapter replay must not rerun extraction or workspace"
                )
            with self._lock, self._transaction() as conn:
                now = self._clock()
                adapter_grant.authentication.require_current(now)
                committed = self._commit_grant_in_transaction(
                    conn, adapter_grant, recorded_at=now.to_text()
                )
                row = conn.execute(
                    "SELECT * FROM graphiti_adapter_attempts WHERE authority_event_id=?",
                    (committed.event_id,),
                ).fetchone()
                if row is None:
                    raise AuthorityPersistenceError(
                        "replayed adapter command lacks retained attempt"
                    )
                result = self._graphiti_attempt_from_row(
                    conn, row, replayed=True
                )
                self._require_graphiti_attempt_current(conn, result)
                return result
        if extraction_grant is None:
            raise TypeError("new adapter execution requires an extraction grant")
        if extraction_grant.replay_of_command_id is not None:
            raise GraphitiAdapterAmbiguousEffect(
                "Extraction Run already exists without adapter attempt authority; "
                "explicit reconciliation is required"
            )
        if not isinstance(execution, GraphitiAdapterExecution):
            raise TypeError("new adapter execution requires a typed result")
        holder: dict[str, GraphitiAttemptRecord] = {}

        def after_persist(
            conn: sqlite3.Connection,
            result: ExtractionRunVersion,
            recorded_at: UtcTimestamp,
        ) -> None:
            holder["result"] = self._persist_graphiti_attempt_after_extraction(
                conn,
                adapter_grant=adapter_grant,
                attempt=attempt,
                execution=execution,
                result=result,
                recorded_at=recorded_at,
            )

        self.commit_extraction_run(
            extraction_grant,
            request=attempt.extraction_request,
            production=execution.produced,
            started_at=execution.started_at,
            ended_at=execution.ended_at,
            _after_persist=after_persist,
        )
        try:
            return holder["result"]
        except KeyError as exc:
            raise AuthorityPersistenceError(
                "adapter attempt callback did not retain authority"
            ) from exc

    def commit_graphiti_replay_approval(
        self,
        grant: _AuthorizedCommandGrant,
        *,
        request: GraphitiReplayApprovalRequest,
    ) -> GraphitiReplaySourceRecord:
        if not isinstance(request, GraphitiReplayApprovalRequest):
            raise TypeError("replay approval commit requires a typed request")
        self._require_graphiti_grant(
            grant,
            command_type=GRAPHITI_REPLAY_APPROVE_COMMAND,
            aggregate_id=str(request.replay_source_id),
            canonical_bytes=request.canonical_bytes,
        )
        with self._lock, self._transaction() as conn:
            now = self._clock()
            grant.authentication.require_current(now)
            committed = self._commit_grant_in_transaction(
                conn, grant, recorded_at=now.to_text()
            )
            if committed.replayed:
                row = conn.execute(
                    "SELECT * FROM graphiti_replay_sources WHERE approval_event_id=?",
                    (committed.event_id,),
                ).fetchone()
                if row is None:
                    raise AuthorityPersistenceError(
                        "replayed approval lacks retained replay source"
                    )
                result = self._graphiti_replay_source_from_row(
                    conn, row, replayed=True
                )
                source_attempt = self._graphiti_attempt_from_row(
                    conn,
                    self._graphiti_attempt_row(
                        conn, result.source.source_attempt_id
                    ),
                    replayed=False,
                )
                self._require_graphiti_attempt_current(conn, source_attempt)
                return result

            self._graphiti_ensure_identifier_absent(
                conn,
                table="graphiti_replay_sources",
                column="replay_source_id",
                identifier=str(request.replay_source_id),
                identity="Graphiti replay source identity",
            )
            attempt = self._graphiti_attempt_from_row(
                conn,
                self._graphiti_attempt_row(conn, request.source_attempt_id),
                replayed=False,
            )
            self._require_graphiti_attempt_current(conn, attempt)
            if (
                attempt.run_version_id != request.source_run_version_id
                or attempt.output_id != request.source_output_id
                or attempt.proposal_set_id != request.source_proposal_set_id
            ):
                raise AuthorityPersistenceError(
                    "replay approval source identities differ from retained attempt"
                )
            eligibility = {
                GraphitiAdapterOutcome.COMPLETE: GraphitiReplayEligibility.COMPLETE,
                GraphitiAdapterOutcome.PARTIAL: GraphitiReplayEligibility.PARTIAL,
                GraphitiAdapterOutcome.MALFORMED_OUTPUT: (
                    GraphitiReplayEligibility.MALFORMED_OUTPUT
                ),
            }.get(attempt.outcome)
            if eligibility is None or eligibility is not request.eligibility:
                raise GraphitiAdapterStateError(
                    "adapter attempt outcome is not eligible for approved replay"
                )
            version_row = conn.execute(
                "SELECT * FROM extraction_run_versions WHERE run_version_id=?",
                (str(request.source_run_version_id),),
            ).fetchone()
            if version_row is None:
                raise AuthorityPersistenceError(
                    "replay approval run version is missing"
                )
            version = self._run_version_from_row(conn, version_row, replayed=False)
            self._revalidate_result_current(conn, version)
            if version.output is None:
                raise AuthorityPersistenceError(
                    "replay approval requires retained structured output"
                )
            output_digest = version.output.canonical_digest
            proposal_digest = (
                None
                if version.proposal_set is None
                else version.proposal_set.canonical_digest
            )
            proposals = (
                ()
                if version.proposal_set is None
                else tuple(
                    {
                        "local_id": item.local_id,
                        "kind": item.kind.value,
                        "subject_placeholder": item.subject_placeholder,
                        "object_placeholder": item.object_placeholder,
                        "predicate_hint": (
                            None
                            if item.predicate_hint is None
                            else item.predicate_hint.value
                        ),
                        "confidence_basis_points": item.confidence_basis_points,
                        "uncertainty_codes": list(item.uncertainty_codes),
                        "rationale_codes": list(item.rationale_codes),
                        "evidence": [
                            evidence.canonical_value()
                            for evidence in item.evidence
                        ],
                    }
                    for item in version.proposal_set.proposals
                )
            )
            replay_payload_digest = digest_canonical(
                {
                    "outcome": version.outcome.value,
                    "failure_code": version.failure_code.value,
                    "validation": version.output.validation.value,
                    "raw_output_digest": output_digest,
                    "proposals": list(proposals),
                    "usage": version.usage.canonical_value(),
                }
            )
            if (
                output_digest != request.expected_output_canonical_digest
                or proposal_digest
                != request.expected_proposal_set_canonical_digest
                or replay_payload_digest != request.expected_replay_payload_digest
            ):
                raise AuthorityPersistenceError(
                    "replay approval expected digests differ from retained authority"
                )
            event = self._graphiti_record_context(
                conn, event_id=committed.event_id
            )
            source = GraphitiReplaySource(
                replay_source_id=request.replay_source_id,
                source_attempt_id=request.source_attempt_id,
                source_run_version_id=request.source_run_version_id,
                source_output_id=request.source_output_id,
                source_proposal_set_id=request.source_proposal_set_id,
                eligibility=request.eligibility,
                output_canonical_digest=output_digest,
                proposal_set_canonical_digest=proposal_digest,
                replay_payload_digest=replay_payload_digest,
                approval_event_digest=graphiti_event_digest(event),
            )
            data = canonical_json_bytes(source.canonical_value())
            conn.execute(
                "INSERT INTO graphiti_replay_sources("
                "replay_source_id,source_attempt_id,source_run_version_id,"
                "source_output_id,source_proposal_set_id,eligibility,"
                "output_canonical_digest,proposal_set_canonical_digest,"
                "replay_payload_digest,approval_event_id,approval_event_digest,"
                "canonical_bytes,canonical_digest,approved_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(source.replay_source_id),
                    str(source.source_attempt_id),
                    str(source.source_run_version_id),
                    str(source.source_output_id),
                    (
                        None
                        if source.source_proposal_set_id is None
                        else str(source.source_proposal_set_id)
                    ),
                    source.eligibility.value,
                    source.output_canonical_digest,
                    source.proposal_set_canonical_digest,
                    source.replay_payload_digest,
                    committed.event_id,
                    source.approval_event_digest,
                    data,
                    source.canonical_digest,
                    now.to_text(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM graphiti_replay_sources WHERE replay_source_id=?",
                (str(source.replay_source_id),),
            ).fetchone()
            assert row is not None
            return self._graphiti_replay_source_from_row(
                conn, row, replayed=False
            )


__all__ = ["_GraphitiAdapterCommitMixin"]
