"""One accounted, fixed-route embedding of an exact native extraction passage.

The caller supplies the existing qualified invocation policy and signed-stop /
source-rights fence. No provider call is made while opening a runtime. No retry,
workspace Graphiti vector or fabricated provider receipt is used here.
"""

from __future__ import annotations

import json
import math
import sqlite3
import ssl
import struct
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from newsroom.authority import AuthenticationProof, GovernedObjects, ObjectAdmissionRequest
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical
from newsroom.graphiti_adapter.evaluation_packet import OPENROUTER_BASE_URL, OPENROUTER_EMBEDDING_SLUG
from newsroom.graphiti_adapter.embedding_meter import _usd_microunits
from newsroom.increment5.native_retrieval import (
    NATIVE_VECTOR_DIMENSIONS, NativeEmbeddingReceipt, NativeEmbeddingReference,
    NativeRetrievalHold, _vector,
)

from .govuk_evidence import _NoRedirect, _unique_object
from .model_usage import (
    InvocationAllocation, InvocationEfficiencyPolicy, InvocationTerminal,
    MODEL_USAGE_SCHEMA_VERSION, ModelUsageAdmissionError,
    ModelUsageIntegrityError, ModelUsageService, UsageComponents, UsageStatus,
    WorkEnvelope, WorkloadClass, _allocation_from_record, _envelope_from_record,
)
from .veto import VetoError

VERSION = "hermes-native-passage-embedding-v1"
ROUTE = "NATIVE_RETRIEVAL_EMBEDDING"
URL = OPENROUTER_BASE_URL + "/embeddings"
TIMEOUT = 30
MAX_RESPONSE_BYTES = 1_048_576
SCHEMA_DIGEST = digest_canonical({
    "model": OPENROUTER_EMBEDDING_SLUG, "dimensions": NATIVE_VECTOR_DIMENSIONS,
    "response": "one-finite-float-vector-with-provider-id-and-usage",
})
MODEL_DIGEST = digest_canonical({
    "provider": "openrouter", "model": OPENROUTER_EMBEDDING_SLUG,
    "dimensions": NATIVE_VECTOR_DIMENSIONS, "encoding_format": "float",
    "stored_encoding": "big-endian-float32",
})


def implementation_digest() -> str:
    return digest_bytes(Path(__file__).read_bytes())


class NativePassageEmbedder:
    def __init__(
        self, *, api_key: str, objects: GovernedObjects, usage: ModelUsageService,
        policy: InvocationEfficiencyPolicy,
        dispatch_fence: Callable[[], AbstractContextManager],
        implementation_worktree_clean: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        if not api_key or not callable(dispatch_fence):
            raise ValueError("native embedding credential and dispatch fence are required")
        if (
            policy.workload_class is not WorkloadClass.NATIVE_RETRIEVAL_EMBEDDING
            or (policy.provider, policy.route, policy.model, policy.reasoning)
            != ("openrouter", ROUTE, OPENROUTER_EMBEDDING_SLUG, "none")
            or policy.output_schema_digest != SCHEMA_DIGEST
            or policy.prompt_contract_version != VERSION
            or implementation_worktree_clean is not True
            or not policy.qualified
        ):
            raise NativeRetrievalHold("NATIVE_EMBEDDING_POLICY_HOLD")
        usage.register_policy(policy)
        self._key, self._objects, self._usage = api_key, objects, usage
        self._policy, self._fence, self._clock = policy, dispatch_fence, clock

    def retryable_settled_attempt(
        self, *, text: str, passage_id: str, cycle_id: str,
    ) -> bool:
        """Allow retry only after one exact, settled and fully-accounted attempt."""
        request = _request(text)
        envelope = WorkEnvelope.create(
            cycle_id=cycle_id, workload_class=self._policy.workload_class,
            admitted_at=self._clock(), admission_decision_id=None,
            candidate_id=None, hypothesis_digest=None,
            evidence_package_digest=digest_bytes(text.encode()),
            ingest_id=passage_id, graphiti_attempt_id=None,
        )
        allocation = _retained_allocation(
            self._usage, envelope=envelope, prompt_digest=digest_bytes(request),
            policy=self._policy,
        )
        if allocation is None:
            return False
        terminal = self._usage.terminal(allocation.invocation_id)
        if terminal is None or terminal.policy_breach is not None:
            return False
        pre_dispatch_zero = (
            terminal is not None
            and terminal.pre_dispatch_zero_proved
            and terminal.dispatch_at is None
            and terminal.usage_status is UsageStatus.REPORTED
            and terminal.components.total_tokens == 0
        )
        settled_validation_failure = (
            terminal.outcome == "NATIVE_EMBEDDING_FAILED"
            and terminal.failure_class == "ValueError"
            and terminal.usage_status is UsageStatus.REPORTED
            and terminal.components.provenance == "PROVIDER_REPORTED"
            and terminal.components.total_tokens is not None
            and terminal.dispatch_at is not None
            and terminal.provider_telemetry_digest is not None
            and not terminal.pre_dispatch_zero_proved
        )
        settled_timeout = (
            terminal.outcome == "NATIVE_EMBEDDING_FAILED"
            and terminal.failure_class == "TimeoutError"
            and terminal.usage_status is UsageStatus.UNREPORTED
            and terminal.dispatch_at is not None
            and terminal.provider_telemetry_digest is None
            and not terminal.pre_dispatch_zero_proved
        )
        if settled_timeout:
            self._settle_timeout(
                allocation=allocation,
                terminal=terminal,
                passage_id=passage_id,
                cycle_id=cycle_id,
            )
            return self._usage.route_state(ROUTE)["state"] == "CLOSED"
        return pre_dispatch_zero or (
            settled_validation_failure
            and _retained_provider_telemetry(
                self._usage, allocation.invocation_id,
                terminal.provider_telemetry_digest,
            )
        )

    def retain(
        self, *, text: str, passage_id: str, cycle_id: str, proof: AuthenticationProof,
    ) -> NativeEmbeddingReference:
        if type(text) is not str or not text.strip() or not passage_id:
            raise NativeRetrievalHold("NATIVE_EMBEDDING_INPUT_HOLD")
        request = _request(text)
        policy, now = self._policy, self._clock()
        if len(request) > policy.max_prompt_bytes:
            raise NativeRetrievalHold("NATIVE_EMBEDDING_INPUT_BOUND")
        envelope = WorkEnvelope.create(
            cycle_id=cycle_id, workload_class=policy.workload_class, admitted_at=now,
            admission_decision_id=None, candidate_id=None, hypothesis_digest=None,
            evidence_package_digest=digest_bytes(text.encode()), ingest_id=passage_id,
            graphiti_attempt_id=None,
        )
        self._usage.open_envelope(envelope)
        manifest = self._manifest(request, text)
        self._usage.retain_context_manifest(manifest)
        allocation = InvocationAllocation.create(
            envelope_id=envelope.envelope_id, cycle_id=cycle_id, leaf_ordinal=1,
            workload_class=policy.workload_class, invocation_policy_digest=policy.canonical_digest,
            provider=policy.provider, route=policy.route, model=policy.model, reasoning="none",
            prompt_contract_version=VERSION, prompt_bytes=len(request),
            prompt_digest=digest_bytes(request), request_digest=manifest["request_digest"],
            output_schema_digest=SCHEMA_DIGEST, max_output_tokens=1,
            context_manifest_digest=manifest["context_manifest_digest"],
            context_identity=VERSION, config_identity=VERSION,
            one_turn=True, exact_input=True, skills_enabled=False, tools_enabled=False,
            mcp_enabled=False, prior_message_count=0, allocated_at=now,
            recovery_deadline_at=now + timedelta(seconds=TIMEOUT + 5), parent_invocation_id=None,
        )
        try:
            self._usage.allocate(allocation, owner_emergency_stop=False)
        except ModelUsageAdmissionError as exc:
            raise NativeRetrievalHold("NATIVE_EMBEDDING_ALLOCATION_HOLD") from exc
        dispatch_at = None
        telemetry = None
        vector = None
        error = None
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirect(),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            )
            http = urllib.request.Request(URL, data=request, method="POST", headers={
                "Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                "Accept": "application/json", "Accept-Encoding": "identity",
            })
            with self._fence():
                dispatch_at = self._clock()
                self._usage.observe_transport(
                    invocation_id=allocation.invocation_id, observed_at=dispatch_at,
                    state="DISPATCH_STARTED", evidence_digest=manifest["request_digest"],
                )
                with opener.open(http, timeout=TIMEOUT) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                    if response.status != 200 or response.geturl() != URL or len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("native embedding response envelope differs")
            result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
            telemetry = _telemetry(result)
            vector = _response_vector(result)
        except Exception as exc:
            # Preserve post-dispatch accounting even if vector validation fails.
            error = exc
        completed = self._clock()
        known = telemetry is not None and telemetry["total_tokens"] is not None
        zero = dispatch_at is None
        components = (
            UsageComponents(input_tokens=telemetry["prompt_tokens"], output_tokens=0,
                            total_tokens=telemetry["total_tokens"], provenance="PROVIDER_REPORTED")
            if known else UsageComponents(total_tokens=0, provenance="CLI_DERIVED")
            if zero else UsageComponents(provenance="UNAVAILABLE")
        )
        terminal = self._usage.complete(InvocationTerminal.create(
            invocation_id=allocation.invocation_id,
            outcome="NATIVE_EMBEDDING_COMPLETE" if error is None else "NATIVE_EMBEDDING_FAILED",
            failure_class=None if error is None else type(error).__name__,
            usage_status=UsageStatus.REPORTED if known or zero else UsageStatus.UNREPORTED,
            components=components, dispatch_at=dispatch_at, completed_at=completed,
            observed_at=completed, pre_dispatch_zero_proved=zero,
            provider_telemetry_digest=None if telemetry is None else digest_canonical(telemetry),
            od_011_reference="OD-011:NATIVE_RETRIEVAL_EMBEDDING",
            subscription_cli_chat_not_cash_debited=False,
        ), provider_telemetry=telemetry)
        if (
            terminal.outcome == "NATIVE_EMBEDDING_FAILED"
            and terminal.failure_class == "TimeoutError"
            and terminal.usage_status is UsageStatus.UNREPORTED
        ):
            self._settle_timeout(
                allocation=allocation,
                terminal=terminal,
                passage_id=passage_id,
                cycle_id=cycle_id,
            )
        if isinstance(error, VetoError):
            raise error
        if (error is not None or vector is None or telemetry is None
                or terminal.usage_status is not UsageStatus.REPORTED or terminal.policy_breach):
            raise NativeRetrievalHold("NATIVE_EMBEDDING_RESULT_HOLD") from error
        receipt = NativeEmbeddingReceipt(
            digest_bytes(text.encode()), digest_bytes(vector), NATIVE_VECTOR_DIMENSIONS,
            "openrouter", OPENROUTER_EMBEDDING_SLUG, MODEL_DIGEST,
            telemetry["provider_request_id"], terminal.terminal_digest,
            completed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        vector_admission = self._objects.admit(ObjectAdmissionRequest(
            "retrieval.native-vector", f"native-vector:{receipt.vector_digest}",
        ), vector, proof=proof).admission
        receipt_admission = self._objects.admit(ObjectAdmissionRequest(
            "retrieval.native-embedding-receipt", f"native-embedding:{digest_bytes(receipt.canonical_bytes)}",
        ), receipt.canonical_bytes, proof=proof).admission
        return NativeEmbeddingReference(vector_admission.admission_id, receipt_admission.admission_id)

    def _settle_timeout(
        self,
        *,
        allocation: InvocationAllocation,
        terminal: InvocationTerminal,
        passage_id: str,
        cycle_id: str,
    ) -> dict[str, object]:
        return self._usage.disposition_native_embedding_timeout(
            invocation_id=allocation.invocation_id,
            expected_terminal_digest=terminal.terminal_digest,
            expected_allocation_digest=allocation.canonical_digest,
            expected_request_digest=allocation.request_digest,
            expected_passage_id=passage_id,
            expected_cycle_id=cycle_id,
            observed_at=self._clock(),
        )

    def _manifest(self, request: bytes, text: str) -> dict:
        policy = self._policy
        value = dict(
            schema_version=policy.context_manifest_schema_version,
            provider=policy.provider, route=policy.route, model=policy.model, reasoning="none",
            command_semantic_version=VERSION, command_flags=list(policy.command_flags),
            disabled_capabilities=list(policy.disabled_capabilities),
            implementation_revision=implementation_digest(), implementation_worktree_clean=True,
            prompt_contract_version=VERSION, prompt_bytes=len(request), prompt_digest=digest_bytes(request),
            schema_digest=SCHEMA_DIGEST, output_schema_digest=SCHEMA_DIGEST,
            system_digest=digest_bytes(b""), evidence_package_digest=digest_bytes(text.encode()),
            evidence_package_bytes=len(text.encode()), context_identity=VERSION, config_identity=VERSION,
            one_turn=True, exact_input=True, skills_enabled=False, tools_enabled=False,
            mcp_enabled=False, prior_message_count=0, skill_count=0, tool_count=0,
            mcp_server_count=0, mcp_tool_count=0,
        )
        value["request_digest"] = digest_canonical({key: value[key] for key in (
            "provider", "route", "model", "reasoning", "command_semantic_version", "command_flags",
            "implementation_revision", "system_digest", "prompt_digest", "output_schema_digest",
        )})
        return {**value, "context_manifest_digest": digest_canonical(value)}


def _telemetry(value: object) -> dict:
    if type(value) is not dict or type(value.get("usage")) is not dict:
        raise ValueError("embedding response usage is absent")
    usage = value["usage"]
    prompt, total = usage.get("prompt_tokens"), usage.get("total_tokens")
    if any(type(item) is not int or item < 0 for item in (prompt, total)):
        prompt = total = None
    return {"provider": "openrouter",
            "model": value.get("model") if type(value.get("model")) is str else None,
            "provider_request_id": value.get("id") if type(value.get("id")) is str else None,
            "prompt_tokens": prompt, "total_tokens": total,
            "cost_usd_microunits": _usd_microunits(usage.get("cost")),
            # Preserve exact numeric telemetry as JSON text, not unsupported
            # floating-point values in authority canonical JSON.
            "usage_json": json.dumps(usage, sort_keys=True, separators=(",", ":"), allow_nan=False)}


def _response_vector(value: dict) -> bytes:
    if (value.get("model") not in {OPENROUTER_EMBEDDING_SLUG, "text-embedding-3-large"}
            or value.get("object") != "list"
            or type(value.get("id")) is not str or not value["id"]):
        raise ValueError("embedding provider identity differs")
    rows = value.get("data")
    if type(rows) is not list or len(rows) != 1 or rows[0].get("index") != 0:
        raise ValueError("embedding response count differs")
    values = rows[0].get("embedding")
    if (type(values) is not list or len(values) != NATIVE_VECTOR_DIMENSIONS
            or any(type(item) not in (int, float) or not math.isfinite(item) for item in values)):
        raise ValueError("embedding dimensions or values differ")
    result = struct.pack(f">{NATIVE_VECTOR_DIMENSIONS}f", *values)
    _vector(result)
    return result


def _request(text: str) -> bytes:
    return canonical_json_bytes({
        "input": text, "model": OPENROUTER_EMBEDDING_SLUG,
        "dimensions": NATIVE_VECTOR_DIMENSIONS, "encoding_format": "float",
    })


def _retained_allocation(
    usage: ModelUsageService, *, envelope: WorkEnvelope, prompt_digest: str,
    policy: InvocationEfficiencyPolicy,
) -> InvocationAllocation | None:
    """Read one exact prior allocation without binding recovery to new code."""
    connection = sqlite3.connect(Path(usage.path).resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT a.*,a.record_json AS allocation_json,w.envelope_id AS "
            "retained_envelope_id,w.cycle_id AS envelope_cycle_id,w.workload_class AS "
            "envelope_workload_class,w.canonical_digest AS envelope_canonical_digest,"
            "w.record_json AS envelope_json,w.admitted_at AS envelope_admitted_at FROM "
            "model_invocation_allocations a JOIN "
            "model_work_envelopes w ON w.envelope_id=a.envelope_id WHERE "
            "a.envelope_id=?", (envelope.envelope_id,),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return None
    if len(rows) != 1:
        raise ModelUsageIntegrityError("native embedding allocation is ambiguous")
    row = rows[0]
    try:
        envelope_record = json.loads(row["envelope_json"])
        retained_envelope = _envelope_from_record(envelope_record)
        allocation_record = json.loads(row["allocation_json"])
        retained_allocation = _allocation_from_record(allocation_record)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError,
            ModelUsageIntegrityError) as exc:
        raise ModelUsageIntegrityError("native embedding allocation differs") from exc
    column_bindings = (
        ("invocation_id", "invocation_id"), ("envelope_id", "envelope_id"),
        ("cycle_id", "cycle_id"), ("leaf_ordinal", "leaf_ordinal"),
        ("workload_class", "workload_class"), ("policy_digest", "invocation_policy_digest"),
        ("provider", "provider"), ("route", "route"), ("model", "model"),
        ("request_digest", "request_digest"),
        ("parent_invocation_id", "parent_invocation_id"),
        ("allocated_at", "allocated_at"), ("canonical_digest", "canonical_digest"),
    )
    if (
        retained_envelope.as_record() != envelope_record
        or retained_envelope.envelope_id != envelope.envelope_id
        or row["retained_envelope_id"] != retained_envelope.envelope_id
        or row["envelope_cycle_id"] != retained_envelope.cycle_id
        or row["envelope_workload_class"] != retained_envelope.workload_class.value
        or row["envelope_canonical_digest"] != retained_envelope.canonical_digest
        or row["envelope_admitted_at"] != retained_envelope.as_record()["admitted_at"]
        or retained_allocation.as_record() != allocation_record
        or any(row[column] != allocation_record[key] for column, key in column_bindings)
        or retained_allocation.cycle_id != envelope.cycle_id
        or retained_allocation.workload_class is not policy.workload_class
        or retained_allocation.prompt_digest != prompt_digest
        or retained_allocation.provider != policy.provider
        or retained_allocation.route != policy.route
        or retained_allocation.model != policy.model
        or retained_allocation.leaf_ordinal != 1
        or retained_allocation.parent_invocation_id is not None
    ):
        raise ModelUsageIntegrityError("native embedding allocation differs")
    return retained_allocation


def _retained_provider_telemetry(
    usage: ModelUsageService, invocation_id: str, expected_digest: str | None,
) -> bool:
    connection = sqlite3.connect(Path(usage.path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT telemetry_record_digest,provider_telemetry_digest,record_json "
            "FROM model_provider_telemetry WHERE invocation_id=?", (invocation_id,),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1 or expected_digest is None:
        return False
    try:
        record = json.loads(rows[0][2])
        telemetry = record["provider_telemetry"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        type(record) is dict
        and record.get("schema_version") == MODEL_USAGE_SCHEMA_VERSION
        and record.get("invocation_id") == invocation_id
        and record.get("provider_telemetry_digest") == expected_digest
        and rows[0][1] == expected_digest
        and digest_canonical(telemetry) == expected_digest
        and digest_canonical(record) == rows[0][0]
    )
