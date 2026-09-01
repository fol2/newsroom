from __future__ import annotations

import json
import sqlite3

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.persistence import AuthorityPersistenceError
from newsroom.extraction.models import ProducedExtraction, ProposalDraft
from newsroom.extraction.types import (
    ExtractionOutputId,
    ExtractionRunId,
    ExtractionRunVersionId,
)
from newsroom.graphiti_adapter.models import (
    ApprovedReplayBundle,
    GraphitiAdapterConfigurationRecord,
    GraphitiAttemptRecord,
    GraphitiInputManifest,
    GraphitiReplaySourceRecord,
)
from newsroom.graphiti_adapter.types import (
    GraphitiAdapterConfigurationId,
    GraphitiAttemptId,
    GraphitiReplaySourceId,
)


class _GraphitiAdapterReadMixin:
    def graphiti_configuration(
        self, configuration_id: GraphitiAdapterConfigurationId
    ) -> GraphitiAdapterConfigurationRecord:
        if not isinstance(configuration_id, GraphitiAdapterConfigurationId):
            raise TypeError("adapter configuration identity must be typed")
        with self._lock:
            row = self._graphiti_configuration_row(
                self._connection, configuration_id
            )
            result = self._graphiti_configuration_from_row(
                self._connection, row, replayed=False
            )
            self._require_graphiti_configuration_current(
                self._connection, result
            )
            return result

    def graphiti_attempt(self, attempt_id: GraphitiAttemptId) -> GraphitiAttemptRecord:
        if not isinstance(attempt_id, GraphitiAttemptId):
            raise TypeError("adapter attempt identity must be typed")
        with self._lock:
            row = self._graphiti_attempt_row(self._connection, attempt_id)
            result = self._graphiti_attempt_from_row(
                self._connection, row, replayed=False
            )
            self._require_graphiti_attempt_current(self._connection, result)
            workspace_row = self._connection.execute(
                "SELECT * FROM graphiti_workspaces WHERE workspace_id=?",
                (str(result.workspace_id),),
            ).fetchone()
            if workspace_row is None:
                raise AuthorityPersistenceError(
                    "Graphiti attempt workspace is missing"
                )
            self._require_graphiti_workspace_absent(
                self._graphiti_workspace_from_row(workspace_row)
            )
            return result

    def graphiti_attempt_history(
        self, run_id: ExtractionRunId, *, limit: int
    ) -> tuple[GraphitiAttemptRecord, ...]:
        if not isinstance(run_id, ExtractionRunId):
            raise TypeError("adapter attempt run identity must be typed")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("adapter attempt history limit must be positive")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM graphiti_adapter_attempts WHERE run_id=? "
                "ORDER BY attempt_number DESC LIMIT ?",
                (str(run_id), limit),
            ).fetchall()
            results = tuple(
                self._graphiti_attempt_from_row(
                    self._connection, row, replayed=False
                )
                for row in rows
            )
            for result in results:
                self._require_graphiti_attempt_current(self._connection, result)
            return results

    def graphiti_manifest_for_attempt(
        self, attempt_id: GraphitiAttemptId
    ) -> GraphitiInputManifest:
        if not isinstance(attempt_id, GraphitiAttemptId):
            raise TypeError("adapter attempt identity must be typed")
        with self._lock:
            attempt_row = self._graphiti_attempt_row(self._connection, attempt_id)
            attempt = self._graphiti_attempt_from_row(
                self._connection, attempt_row, replayed=False
            )
            self._require_graphiti_attempt_current(self._connection, attempt)
            manifest_row = self._connection.execute(
                "SELECT * FROM graphiti_input_manifests WHERE manifest_id=?",
                (str(attempt.manifest_id),),
            ).fetchone()
            if manifest_row is None:
                raise AuthorityPersistenceError(
                    "Graphiti attempt manifest is missing"
                )
            manifest = self._graphiti_manifest_from_row(
                self._connection, manifest_row
            )
            if (
                manifest.run_id != attempt.run_id
                or manifest.requested_run_version_id != attempt.run_version_id
                or manifest.configuration_id != attempt.configuration_id
                or manifest.configuration_digest != attempt.configuration_digest
            ):
                raise AuthorityPersistenceError(
                    "Graphiti attempt manifest binding differs"
                )
            return manifest

    def graphiti_replay_source(
        self, replay_source_id: GraphitiReplaySourceId
    ) -> GraphitiReplaySourceRecord:
        if not isinstance(replay_source_id, GraphitiReplaySourceId):
            raise TypeError("adapter replay source identity must be typed")
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM graphiti_replay_sources WHERE replay_source_id=?",
                (str(replay_source_id),),
            ).fetchone()
            if row is None:
                raise KeyError(str(replay_source_id))
            result = self._graphiti_replay_source_from_row(
                self._connection, row, replayed=False
            )
            attempt = self._graphiti_attempt_from_row(
                self._connection,
                self._graphiti_attempt_row(
                    self._connection, result.source.source_attempt_id
                ),
                replayed=False,
            )
            self._require_graphiti_attempt_current(self._connection, attempt)
            return result

    def approved_graphiti_replay_bundle(
        self, replay_source_id: GraphitiReplaySourceId
    ) -> ApprovedReplayBundle:
        if not isinstance(replay_source_id, GraphitiReplaySourceId):
            raise TypeError("adapter replay source identity must be typed")
        with self._lock:
            return self._approved_replay_bundle(replay_source_id)

    def _approved_replay_bundle(
        self, replay_source_id: GraphitiReplaySourceId
    ) -> ApprovedReplayBundle:
        """Private raw-output seam used only by an authorised replay command."""

        with self._lock:
            return self._approved_replay_bundle_locked(replay_source_id)

    def _approved_replay_bundle_locked(
        self, replay_source_id: GraphitiReplaySourceId
    ) -> ApprovedReplayBundle:
        row = self._connection.execute(
            "SELECT * FROM graphiti_replay_sources WHERE replay_source_id=?",
            (str(replay_source_id),),
        ).fetchone()
        if row is None:
            raise KeyError(str(replay_source_id))
        retained = self._graphiti_replay_source_from_row(
            self._connection, row, replayed=False
        )
        source = retained.source
        attempt = self._graphiti_attempt_from_row(
            self._connection,
            self._graphiti_attempt_row(self._connection, source.source_attempt_id),
            replayed=False,
        )
        self._require_graphiti_attempt_current(self._connection, attempt)

        version_row = self._connection.execute(
            "SELECT * FROM extraction_run_versions WHERE run_version_id=?",
            (str(source.source_run_version_id),),
        ).fetchone()
        if version_row is None:
            raise AuthorityPersistenceError(
                "approved replay extraction run version is missing"
            )
        version = self._run_version_from_row(
            self._connection, version_row, replayed=False
        )
        self._revalidate_result_current(self._connection, version)
        if version.output is None or version.output.output_id != source.source_output_id:
            raise AuthorityPersistenceError(
                "approved replay output differs from extraction authority"
            )
        output_row = self._connection.execute(
            "SELECT canonical_bytes,canonical_digest FROM extraction_outputs "
            "WHERE output_id=?",
            (str(source.source_output_id),),
        ).fetchone()
        if output_row is None:
            raise AuthorityPersistenceError("approved replay output is missing")
        raw_bytes = bytes(output_row["canonical_bytes"])
        if (
            digest_bytes(raw_bytes) != str(output_row["canonical_digest"])
            or str(output_row["canonical_digest"])
            != source.output_canonical_digest
        ):
            raise AuthorityPersistenceError(
                "approved replay output digest differs"
            )
        try:
            raw_value = json.loads(raw_bytes.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AuthorityPersistenceError(
                "approved replay output is not valid JSON"
            ) from exc
        if not isinstance(raw_value, dict) or canonical_json_bytes(raw_value) != raw_bytes:
            raise AuthorityPersistenceError(
                "approved replay output is not a canonical object"
            )

        proposals = ()
        if version.proposal_set is not None:
            if (
                source.source_proposal_set_id
                != version.proposal_set.proposal_set_id
                or source.proposal_set_canonical_digest
                != version.proposal_set.canonical_digest
            ):
                raise AuthorityPersistenceError(
                    "approved replay proposal set differs from retained authority"
                )
            proposals = tuple(
                ProposalDraft(
                    local_id=item.local_id,
                    kind=item.kind,
                    subject_placeholder=item.subject_placeholder,
                    object_placeholder=item.object_placeholder,
                    predicate_hint=item.predicate_hint,
                    confidence_basis_points=item.confidence_basis_points,
                    uncertainty_codes=item.uncertainty_codes,
                    rationale_codes=item.rationale_codes,
                    evidence=item.evidence,
                )
                for item in version.proposal_set.proposals
            )
        elif source.source_proposal_set_id is not None:
            raise AuthorityPersistenceError(
                "approved replay source requires a missing proposal set"
            )

        produced = ProducedExtraction(
            outcome=version.outcome,
            failure_code=version.failure_code,
            validation=version.output.validation,
            raw_output_value=raw_value,
            proposals=proposals,
            usage=version.usage,
        )
        return ApprovedReplayBundle(source=source, produced=produced)


__all__ = ["_GraphitiAdapterReadMixin"]
