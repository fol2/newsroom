from __future__ import annotations

from newsroom.authority.canonical import digest_bytes, digest_canonical
from newsroom.sources import ObservationModel

from .compression import decompress_body
from .models import (
    AdapterRequest,
    Capture,
    FixtureTransportScenario,
    ObservationProposal,
    ParserIssue,
    ParserResult,
    TransportReceipt,
)
from .parsers import parse_capture
from .security import validate_endpoint_evidence
from .types import (
    AdapterContractError,
    BodyEncoding,
    Completeness,
    ObservationProposalOutcome,
    QuarantineRecommendation,
    TransportFailureKind,
)


_STATUS_REASONS = {
    401: (ObservationProposalOutcome.UNAUTHORISED, "HTTP_UNAUTHORISED"),
    403: (ObservationProposalOutcome.UNAUTHORISED, "HTTP_FORBIDDEN"),
    404: (ObservationProposalOutcome.NOT_FOUND, "HTTP_NOT_FOUND"),
    410: (ObservationProposalOutcome.GONE, "HTTP_GONE"),
    429: (ObservationProposalOutcome.RATE_LIMITED, "HTTP_RATE_LIMITED"),
}
_ENCODING_HEADERS = {
    "identity": BodyEncoding.IDENTITY,
    "gzip": BodyEncoding.GZIP,
    "deflate": BodyEncoding.DEFLATE,
}


def _proposal(
    request: AdapterRequest,
    scenario: FixtureTransportScenario,
    *,
    outcome: ObservationProposalOutcome,
    reason_codes: tuple[str, ...],
    quarantine: QuarantineRecommendation,
    incomplete: bool,
    receipt: TransportReceipt | None = None,
    capture: Capture | None = None,
    parser_result: ParserResult | None = None,
    candidate_items=(),
) -> ObservationProposal:
    return ObservationProposal(
        proposal_id=scenario.proposal_id,
        request_id=request.request_id,
        source_definition_id=request.source_definition_id,
        source_definition_version_id=request.source_definition_version_id,
        outcome=outcome,
        reason_codes=tuple(sorted(reason_codes)),
        quarantine=quarantine,
        incomplete=incomplete,
        receipt=receipt,
        capture=capture,
        parser_result=parser_result,
        candidate_items=tuple(candidate_items),
    )


def _timing_failure(
    request: AdapterRequest,
    scenario: FixtureTransportScenario,
) -> TransportFailureKind | None:
    timing = scenario.timing
    limits = request.timeout_limits
    if timing.connect_ms > limits.connect_ms:
        return TransportFailureKind.CONNECT_TIMEOUT
    if timing.read_ms > limits.read_ms:
        return TransportFailureKind.READ_TIMEOUT
    if timing.maximum_idle_ms > limits.idle_ms:
        return TransportFailureKind.IDLE_TIMEOUT
    if timing.total_ms > limits.total_ms:
        return TransportFailureKind.TOTAL_TIMEOUT
    return None


def _parse_content_type(value: str | None) -> tuple[str, str]:
    if value is None:
        return "application/octet-stream", "utf-8"
    parts = [part.strip() for part in value.split(";")]
    media_type = parts[0].lower()
    if not media_type or "/" not in media_type:
        raise AdapterContractError("response content type is malformed")
    charset = "utf-8"
    seen: set[str] = set()
    for parameter in parts[1:]:
        if not parameter:
            continue
        if "=" not in parameter:
            raise AdapterContractError("response content-type parameter is malformed")
        name, raw_value = parameter.split("=", 1)
        name = name.strip().lower()
        raw_value = raw_value.strip().strip('"').lower()
        if name in seen:
            raise AdapterContractError("response content-type parameter is duplicated")
        seen.add(name)
        if name == "charset":
            charset = raw_value
    return media_type, charset


def _encoding_from_headers(scenario: FixtureTransportScenario) -> BodyEncoding:
    header = scenario.header("content-encoding")
    if header is None:
        expected = BodyEncoding.IDENTITY
    else:
        expected = _ENCODING_HEADERS.get(header.strip().lower())
        if expected is None:
            raise AdapterContractError("response content encoding is unsupported")
    if expected is not scenario.content_encoding:
        raise AdapterContractError("fixture body encoding differs from response header")
    return expected


def _validate_content_length(scenario: FixtureTransportScenario) -> None:
    value = scenario.header("content-length")
    if value is None:
        return
    if not value.isdigit() or int(value) != len(scenario.body):
        raise AdapterContractError("response Content-Length differs from fixture bytes")


def _receipt(
    request: AdapterRequest,
    scenario: FixtureTransportScenario,
    *,
    final_url: str,
    failure_kind: TransportFailureKind | None,
    decompressed: bytes | None,
) -> TransportReceipt:
    return TransportReceipt(
        attempt_id=scenario.attempt_id,
        request_id=request.request_id,
        scenario_id=scenario.scenario_id,
        final_url=final_url,
        status_code=scenario.status_code,
        headers=scenario.headers,
        content_encoding=scenario.content_encoding,
        compressed_digest=digest_bytes(scenario.body),
        compressed_length=len(scenario.body),
        decompressed_digest=(
            None if decompressed is None else digest_bytes(decompressed)
        ),
        decompressed_length=None if decompressed is None else len(decompressed),
        dns_evidence_digest=scenario.dns_evidence.digest,
        tls_evidence_digest=scenario.tls_evidence.digest,
        redirect_digest=digest_canonical(
            [item.canonical_value() for item in scenario.redirects]
        ),
        timing=scenario.timing,
        observed_at=scenario.observed_at,
        failure_kind=failure_kind,
    )


def _parser_failure_result(
    request: AdapterRequest,
    scenario: FixtureTransportScenario,
    capture: Capture,
    *,
    code: str,
    message: str,
) -> ParserResult:
    return ParserResult(
        parser_result_id=scenario.parser_result_id,
        capture_id=capture.capture_id,
        adapter=request.adapter,
        shape_contract_digest=request.shape_contract.digest,
        completeness=Completeness.PARTIAL,
        items=(),
        issues=(ParserIssue(code, message),),
        representation_digest=digest_canonical(
            {
                "capture_body_digest": capture.body_digest,
                "shape_contract_digest": request.shape_contract.digest,
                "parser_version": request.adapter.parser_version,
                "normalizer_version": request.adapter.normalizer_version,
                "failure_code": code,
            }
        ),
        shape_drift=False,
        produced_at=scenario.observed_at,
    )


def _baseline_is_exact(request: AdapterRequest) -> bool:
    baseline = request.baseline
    return baseline is not None and (
        baseline.source_definition_version_id
        == request.source_definition_version_id
        and baseline.validator_contract == request.validator_contract
    )


def _validate_304_validator(
    request: AdapterRequest,
    scenario: FixtureTransportScenario,
) -> bool:
    if not _baseline_is_exact(request):
        return False
    assert request.baseline is not None
    etag = scenario.header("etag")
    modified = scenario.header("last-modified")
    if etag is not None and request.baseline.validator.etag != etag:
        return False
    if (
        modified is not None
        and request.baseline.validator.last_modified != modified
    ):
        return False
    return True


def run_fixture_adapter(
    request: AdapterRequest,
    scenario: FixtureTransportScenario,
) -> ObservationProposal:
    """Evaluate one repository fixture without performing external I/O."""

    if not isinstance(request, AdapterRequest):
        raise TypeError("adapter runner requires a typed request")
    if not isinstance(scenario, FixtureTransportScenario):
        raise TypeError("adapter runner requires a typed fixture scenario")
    if scenario.request_id != request.request_id:
        raise AdapterContractError("fixture request identity differs from the request")

    try:
        final_url = validate_endpoint_evidence(
            initial_url=request.endpoint,
            policy=request.endpoint_policy,
            dns=scenario.dns_evidence,
            tls=scenario.tls_evidence,
            redirects=scenario.redirects,
        )
    except AdapterContractError:
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.BLOCKED,
            reason_codes=("PREFLIGHT_ENDPOINT_BLOCKED",),
            quarantine=QuarantineRecommendation.QUARANTINE,
            incomplete=True,
        )

    failure_kind = scenario.failure_kind or _timing_failure(request, scenario)
    if failure_kind is not None:
        receipt = _receipt(
            request,
            scenario,
            final_url=final_url,
            failure_kind=failure_kind,
            decompressed=None,
        )
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.TRANSPORT_FAILED,
            reason_codes=(f"TRANSPORT_{failure_kind.value}",),
            quarantine=QuarantineRecommendation.REVIEW,
            incomplete=True,
            receipt=receipt,
        )

    assert scenario.status_code is not None
    status = scenario.status_code
    if status == 304:
        receipt = _receipt(
            request,
            scenario,
            final_url=final_url,
            failure_kind=None,
            decompressed=b"",
        )
        if not _validate_304_validator(request, scenario):
            return _proposal(
                request,
                scenario,
                outcome=ObservationProposalOutcome.TRANSPORT_FAILED,
                reason_codes=("CONDITIONAL_RESPONSE_WITHOUT_EXACT_BASELINE",),
                quarantine=QuarantineRecommendation.REVIEW,
                incomplete=True,
                receipt=receipt,
            )
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.SUCCESS_UNCHANGED,
            reason_codes=("HTTP_304_EXACT_BASELINE",),
            quarantine=QuarantineRecommendation.NONE,
            incomplete=False,
            receipt=receipt,
        )

    mapped = _STATUS_REASONS.get(status)
    if mapped is not None:
        outcome, reason = mapped
        receipt = _receipt(
            request,
            scenario,
            final_url=final_url,
            failure_kind=None,
            decompressed=b"",
        )
        return _proposal(
            request,
            scenario,
            outcome=outcome,
            reason_codes=(reason,),
            quarantine=(
                QuarantineRecommendation.REVIEW
                if outcome
                in {
                    ObservationProposalOutcome.UNAUTHORISED,
                    ObservationProposalOutcome.GONE,
                }
                else QuarantineRecommendation.NONE
            ),
            incomplete=True,
            receipt=receipt,
        )

    if 300 <= status <= 399:
        receipt = _receipt(
            request,
            scenario,
            final_url=final_url,
            failure_kind=None,
            decompressed=b"",
        )
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.REDIRECTED,
            reason_codes=("REDIRECT_TERMINAL",),
            quarantine=QuarantineRecommendation.REVIEW,
            incomplete=True,
            receipt=receipt,
        )

    if not 200 <= status <= 299:
        receipt = _receipt(
            request,
            scenario,
            final_url=final_url,
            failure_kind=TransportFailureKind.CONNECTION,
            decompressed=None,
        )
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.TRANSPORT_FAILED,
            reason_codes=("HTTP_FAILURE_STATUS",),
            quarantine=QuarantineRecommendation.REVIEW,
            incomplete=True,
            receipt=receipt,
        )

    try:
        _validate_content_length(scenario)
        encoding = _encoding_from_headers(scenario)
        body = decompress_body(
            scenario.body,
            encoding=encoding,
            limits=request.body_limits,
        )
    except AdapterContractError:
        receipt = _receipt(
            request,
            scenario,
            final_url=final_url,
            failure_kind=None,
            decompressed=None,
        )
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.TRANSPORT_FAILED,
            reason_codes=("BODY_CONTRACT_REJECTED",),
            quarantine=QuarantineRecommendation.QUARANTINE,
            incomplete=True,
            receipt=receipt,
        )

    receipt = _receipt(
        request,
        scenario,
        final_url=final_url,
        failure_kind=None,
        decompressed=body,
    )

    try:
        content_type, charset = _parse_content_type(
            scenario.header("content-type")
        )
    except AdapterContractError:
        content_type, charset = "application/octet-stream", "utf-8"

    capture = Capture(
        capture_id=scenario.capture_id,
        request_id=request.request_id,
        receipt_digest=receipt.digest,
        content_type=content_type,
        charset=charset,
        body=body,
        captured_at=scenario.observed_at,
    )

    if not body:
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.SUCCESS_EMPTY,
            reason_codes=("SUCCESSFUL_EMPTY_RESPONSE",),
            quarantine=QuarantineRecommendation.NONE,
            incomplete=False,
            receipt=receipt,
            capture=capture,
        )

    if (
        content_type not in request.body_limits.allowed_content_types
        or charset not in request.body_limits.allowed_charsets
    ):
        parser_result = _parser_failure_result(
            request,
            scenario,
            capture,
            code="CONTENT_CONTRACT_REJECTED",
            message="response content type or charset is outside the allow-list",
        )
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.MALFORMED,
            reason_codes=("CONTENT_CONTRACT_REJECTED",),
            quarantine=QuarantineRecommendation.QUARANTINE,
            incomplete=True,
            receipt=receipt,
            capture=capture,
            parser_result=parser_result,
        )

    parser_result = parse_capture(
        capture,
        parser_result_id=scenario.parser_result_id,
        kind=request.kind,
        adapter=request.adapter,
        shape_contract=request.shape_contract,
        limits=request.parser_limits,
        produced_at=scenario.observed_at,
    )

    if parser_result.shape_drift:
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.SHAPE_DRIFT,
            reason_codes=("SOURCE_SHAPE_DRIFT",),
            quarantine=QuarantineRecommendation.QUARANTINE,
            incomplete=True,
            receipt=receipt,
            capture=capture,
            parser_result=parser_result,
        )

    if not parser_result.items and parser_result.issues:
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.MALFORMED,
            reason_codes=("PARSER_REJECTED_INPUT",),
            quarantine=QuarantineRecommendation.QUARANTINE,
            incomplete=True,
            receipt=receipt,
            capture=capture,
            parser_result=parser_result,
        )

    if not parser_result.items:
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.SUCCESS_EMPTY,
            reason_codes=("SUCCESSFUL_EMPTY_COLLECTION",),
            quarantine=QuarantineRecommendation.NONE,
            incomplete=False,
            receipt=receipt,
            capture=capture,
            parser_result=parser_result,
        )

    if (
        _baseline_is_exact(request)
        and request.baseline is not None
        and parser_result.representation_digest
        == request.baseline.representation_digest
    ):
        return _proposal(
            request,
            scenario,
            outcome=ObservationProposalOutcome.SUCCESS_UNCHANGED,
            reason_codes=("REPRESENTATION_MATCHES_EXACT_BASELINE",),
            quarantine=QuarantineRecommendation.NONE,
            incomplete=False,
            receipt=receipt,
            capture=capture,
            parser_result=parser_result,
        )

    if parser_result.completeness is Completeness.TRUNCATED:
        outcome = ObservationProposalOutcome.SUCCESS_TRUNCATED
        reasons = ("ITEM_LIMIT_TRUNCATED", "NO_CLEARANCE_OR_WITHDRAWAL_AUTHORITY")
        incomplete = True
        quarantine = QuarantineRecommendation.REVIEW
    elif parser_result.completeness is Completeness.PARTIAL:
        outcome = ObservationProposalOutcome.SUCCESS_PARTIAL
        reasons = ("INDEPENDENTLY_VALID_PARTIAL_OUTPUT",)
        if request.observation_model in {
            ObservationModel.COMPLETE_CURRENT_STATE,
            ObservationModel.ROLLING_LIST,
        }:
            reasons += ("NO_CLEARANCE_OR_WITHDRAWAL_AUTHORITY",)
        incomplete = True
        quarantine = QuarantineRecommendation.REVIEW
    else:
        outcome = ObservationProposalOutcome.SUCCESS_CHANGED
        reasons = ("OBSERVABLE_CHANGE_CANDIDATES",)
        incomplete = False
        quarantine = QuarantineRecommendation.NONE

    return _proposal(
        request,
        scenario,
        outcome=outcome,
        reason_codes=tuple(sorted(reasons)),
        quarantine=quarantine,
        incomplete=incomplete,
        receipt=receipt,
        capture=capture,
        parser_result=parser_result,
        candidate_items=parser_result.items,
    )


__all__ = ["run_fixture_adapter"]
