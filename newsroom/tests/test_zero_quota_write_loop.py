from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.control_plane.admission import (
    DeterministicWriteAdmission,
    select_write_ready,
)
from newsroom.control_plane.child_environment import unprivileged_child_environment
from newsroom.control_plane.cycle import run_cycle
from newsroom.control_plane.editorial import (
    DiscoverySignalRecord,
    GroupedObservation,
    NewsLeadRecord,
    StoryCandidateRecord,
    form_candidates,
)
from newsroom.control_plane.evidence import (
    ClaimAuthorityClass,
    Evid012QualificationTest,
    EvidenceGateEvidence,
    EvidencePackage,
    GovernedClaimEvidence,
    GovernedClaimStatus,
    QualificationEvidence,
    package_for,
)
from newsroom.control_plane.items import SourceItem, parse_observation
from newsroom.control_plane.store import connect, list_payloads
from newsroom.control_plane.writer import (
    CliChainWriter,
    FixtureWriter,
    WriterCopy,
    WriterDispatchError,
    WriterEvidenceLink,
    validate_writer_copy,
)
from newsroom.effective_revision import retain_observation_revision_first_seen
from newsroom.tests.test_control_plane_private_beta import _proving

_CLOCK = lambda: datetime(2026, 8, 20, tzinfo=UTC)


def test_non_controller_children_do_not_receive_evidence_approval_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWSROOM_EVIDENCE_APPROVAL_KEY", "secret" * 8)
    assert "NEWSROOM_EVIDENCE_APPROVAL_KEY" not in unprivileged_child_environment()


def _admit_package(
    candidate: StoryCandidateRecord,
    package: EvidencePackage,
    *,
    authority_class: ClaimAuthorityClass = ClaimAuthorityClass.RESPONSIBLE_PRIMARY,
    origin_ids: tuple[str, ...] | None = None,
) -> EvidencePackage:
    headline = candidate.headline
    substantive = candidate.items[0].body
    origins = origin_ids or (f"origin:{candidate.items[0].source_id}",)
    claims = (
        GovernedClaimEvidence(
            claim_id=f"claim:{candidate.candidate_id}:headline",
            claim=headline,
            passage_index=0,
            supporting_excerpt=headline,
            source_ids=(candidate.items[0].source_id,),
            source_record_ids=(f"source-record:{candidate.items[0].source_id}",),
            source_authority_decision_ids=(
                f"source-authority:{candidate.items[0].source_id}:headline",
            ),
            rights_decision_ids=(f"rights:{candidate.items[0].source_id}",),
            dependency_evidence_ids=(f"dependency:{candidate.items[0].source_id}",),
            evidential_origin_ids=origins,
            authority_class=authority_class,
            authority_scope="Responsible source for its own published update.",
            status=GovernedClaimStatus.CONFIRMED_FACT,
            attribution=candidate.items[0].source_id,
            rendered_assertion_zh_hant_hk="官方公布咗最新安排",
            claim_role="HEADLINE",
        ),
        GovernedClaimEvidence(
            claim_id=f"claim:{candidate.candidate_id}:substantive",
            claim=substantive,
            passage_index=0,
            supporting_excerpt=substantive,
            source_ids=(candidate.items[0].source_id,),
            source_record_ids=(f"source-record:{candidate.items[0].source_id}",),
            source_authority_decision_ids=(
                f"source-authority:{candidate.items[0].source_id}:substantive",
            ),
            rights_decision_ids=(f"rights:{candidate.items[0].source_id}",),
            dependency_evidence_ids=(f"dependency:{candidate.items[0].source_id}",),
            evidential_origin_ids=origins,
            authority_class=authority_class,
            authority_scope="Responsible source for its own published update.",
            status=GovernedClaimStatus.CONFIRMED_FACT,
            attribution=candidate.items[0].source_id,
            rendered_assertion_zh_hant_hk="相關官方資料確認安排已經更新",
            claim_role="SUBSTANTIVE",
        ),
    )
    claim_ids = tuple(claim.claim_id for claim in claims)
    return replace(
        package,
        substantive_new_information=(substantive,),
        governed_claims=claims,
        qualification_evidence=(
            QualificationEvidence(
                Evid012QualificationTest.OFFICIAL_ACTION_OR_DEADLINE,
                claims[1].claim_id,
                (
                    ("action_class", "OFFICIAL_DEADLINE"),
                    ("reader_action", substantive),
                ),
            ),
        ),
        selection_rationale="Retained governed evidence proves a material official development.",
        geography=("Hong Kong" if "HK" in candidate.items[0].source_id else "UK",),
        categories=("Politics and law",),
        evidence_gate_results=(
            ("CLAIM_TRACEABILITY", "PASS"),
            ("EVIDENCE_SUFFICIENCY", "PASS"),
            ("SOURCE_AUTHORITY", "PASS"),
        ),
        evidence_gate_evidence=tuple(
            EvidenceGateEvidence(gate, "PASS", claim_ids)  # type: ignore[arg-type]
            for gate in (
                "CLAIM_TRACEABILITY",
                "EVIDENCE_SUFFICIENCY",
                "SOURCE_AUTHORITY",
            )
        ),
        freshness_result="PASS",
        integrity_result="PASS",
        resolved_evidence_records=(
            ("fixture-evidence-record", f"digest:{candidate.candidate_id}"),
        ),
    )


def _candidate_package(
    *, substantive: tuple[str, ...] = ("The deadline changed to 30 September.",)
) -> tuple[StoryCandidateRecord, EvidencePackage]:
    item = SourceItem(
        source_id="HK-01",
        item_key="item-1",
        headline="申請期限改至9月30日",
        body="The deadline changed to 30 September.",
        canonical_url="https://example.test/item-1",
    )
    signal = DiscoverySignalRecord("signal-1", "HK-01", "item-1", "sha256:body")
    lead = NewsLeadRecord("lead-1", "signal-1", item.headline)
    candidate = StoryCandidateRecord(
        "candidate-1", "hypothesis-1", item.headline, (item,), (signal,), (lead,)
    )
    package = EvidencePackage(
        candidate_id=candidate.candidate_id,
        hypothesis_id=candidate.hypothesis_id,
        signal_ids=(signal.signal_id,),
        lead_ids=(lead.lead_id,),
        source_ids=(item.source_id,),
        observation_digests=(signal.observation_digest,),
        passages=(f"HK-01: {item.headline}\n{item.body}",),
    )
    package = _admit_package(candidate, package)
    if not substantive:
        package = replace(package, substantive_new_information=())
    return candidate, package


def _qualified_builder(
    ready_sources: frozenset[str],
):
    def build(candidate: StoryCandidateRecord) -> EvidencePackage:
        package = package_for(candidate)
        if not ({item.source_id for item in candidate.items} & ready_sources):
            return package
        return _admit_package(candidate, package)

    return build


class RecordingFixtureWriter(FixtureWriter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        self.calls.append(candidate.candidate_id)
        return super().write(candidate, package)


class CountingWriter:
    writer_id = "counting-writer"

    def __init__(self) -> None:
        self.calls = 0

    def write(
        self, candidate: StoryCandidateRecord, package: EvidencePackage
    ) -> WriterCopy:
        self.calls += 1
        raise AssertionError("an unqualified candidate reached the writer")


def test_zero_qualifying_candidates_succeed_without_writer_or_filler(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    writer = CountingWriter()

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=writer,
        max_writes=5,
        clock=_CLOCK,
    )

    assert writer.calls == 0
    assert report.candidates_considered == 3
    assert report.write_ready == 0
    assert report.selected_write_ready == 0
    assert report.candidate_attempts == 0
    assert report.provider_dispatches == 0
    assert report.accepted_payload_count == 0
    assert report.minted == 0
    assert list_payloads(str(unpublished)) == ()

    connection = sqlite3.connect(unpublished)
    decisions = connection.execute(
        "SELECT decision, COUNT(*) FROM unpublished_write_admission_decisions "
        "GROUP BY decision ORDER BY decision"
    ).fetchall()
    close_kind = connection.execute(
        "SELECT COUNT(*) FROM ledger WHERE kind='PRIVATE_CYCLE_CLOSE'"
    ).fetchone()[0]
    connection.close()
    assert decisions == [("HOLD", 3)]
    assert close_kind == 1


def test_non_empty_passage_without_substantive_fact_is_rejected() -> None:
    candidate, package = _candidate_package(substantive=())

    decision = DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-08-20T00:00:00.000000Z"
    )

    assert decision.decision == "REJECT"
    assert decision.stable_reason_codes == ("NO_SUBSTANTIVE_NEW_INFORMATION",)


def test_evid_012_is_a_closed_versioned_domain() -> None:
    with pytest.raises(ValueError, match="not in EVID-012"):
        QualificationEvidence(
            cast(Evid012QualificationTest, "TOTALLY_NOT_EVID_012"),
            "claim-1",
            (("invalid", "invalid"),),
        )


def test_ordinary_short_delay_cannot_satisfy_material_disruption_evidence() -> None:
    with pytest.raises(ValueError, match="does not satisfy EVID-012"):
        QualificationEvidence(
            Evid012QualificationTest.ESSENTIAL_SERVICE_DISRUPTION,
            "claim-short-delay",
            (
                ("service_kind", "TRANSPORT"),
                ("material_effect_class", "MINOR_DELAY"),
                ("affected_group", "Two passengers for two minutes"),
            ),
        )


def test_material_duration_classifier_must_be_exact_in_retained_fact() -> None:
    candidate, package = _candidate_package()
    headline, substantive = package.governed_claims
    short_delay = "Train delayed by 2 minutes."
    changed_substantive = replace(
        substantive,
        claim=short_delay,
        supporting_excerpt=short_delay,
        rendered_assertion_zh_hant_hk="列車只係短暫延誤咗兩分鐘",
    )
    unsupported = replace(
        package,
        passages=(f"HK-01: {headline.claim}\n{short_delay}",),
        substantive_new_information=(short_delay,),
        governed_claims=(headline, changed_substantive),
        qualification_evidence=(
            QualificationEvidence(
                Evid012QualificationTest.ESSENTIAL_SERVICE_DISRUPTION,
                changed_substantive.claim_id,
                (
                    ("service_kind", "TRANSPORT"),
                    ("duration_minutes", "60"),
                    ("affected_group", short_delay),
                ),
            ),
        ),
    )

    decision = DeterministicWriteAdmission().decide(
        candidate, unsupported, decided_at="2026-08-20T00:00:00.000000Z"
    )
    assert decision.decision == "HOLD"
    assert decision.stable_reason_codes == ("QUALIFICATION_EVIDENCE_NOT_EXACT",)


def test_self_reported_pass_gates_without_governed_claims_fail_closed() -> None:
    candidate, package = _candidate_package()
    ungoverned = replace(
        package,
        governed_claims=(),
        evidence_gate_evidence=(),
    )

    decision = DeterministicWriteAdmission().decide(
        candidate, ungoverned, decided_at="2026-08-20T00:00:00.000000Z"
    )

    assert decision.decision == "HOLD"
    assert "MISSING_GOVERNED_CLAIMS" in decision.stable_reason_codes
    assert "CLAIM_TRACEABILITY_PROVENANCE_NOT_PASS" in decision.stable_reason_codes


def test_simplified_rendering_fails_versioned_zh_hant_hk_gate() -> None:
    candidate, package = _candidate_package()
    headline, substantive = package.governed_claims
    simplified = replace(
        headline,
        rendered_assertion_zh_hant_hk="官方说新安排",
    )
    decision = DeterministicWriteAdmission().decide(
        candidate,
        replace(package, governed_claims=(simplified, substantive)),
        decided_at="2026-08-20T00:00:00.000000Z",
    )
    assert decision.decision == "HOLD"
    assert "INVALID_GOVERNED_CLAIM_EVIDENCE" in decision.stable_reason_codes


def test_qualification_detail_must_be_exact_in_bound_governed_claim() -> None:
    candidate, package = _candidate_package()
    unsupported = replace(
        package,
        qualification_evidence=(
            QualificationEvidence(
                Evid012QualificationTest.OFFICIAL_ACTION_OR_DEADLINE,
                package.governed_claims[1].claim_id,
                (
                    ("action_class", "OFFICIAL_DEADLINE"),
                    ("reader_action", "An unsupported reader action."),
                ),
            ),
        ),
    )

    decision = DeterministicWriteAdmission().decide(
        candidate, unsupported, decided_at="2026-08-20T00:00:00.000000Z"
    )
    assert decision.decision == "HOLD"
    assert decision.stable_reason_codes == ("QUALIFICATION_EVIDENCE_NOT_EXACT",)


def test_admission_identity_binds_exact_evidence_package_digest() -> None:
    candidate, package = _candidate_package()
    changed = replace(package, passages=(package.passages[0] + " Corrected version.",))
    policy = DeterministicWriteAdmission()

    first = policy.decide(candidate, package, decided_at="2026-08-20T00:00:00.000000Z")
    replay = policy.decide(candidate, package, decided_at="2026-08-21T00:00:00.000000Z")
    drifted = policy.decide(
        candidate, changed, decided_at="2026-08-20T00:00:00.000000Z"
    )

    assert first.decision == "WRITE_READY"
    assert replay.decision_id == first.decision_id
    assert drifted.decision_id != first.decision_id
    assert drifted.evidence_package_digest != first.evidence_package_digest


def test_two_write_ready_candidates_never_trigger_three_replacements(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    unpublished = tmp_path / "unpublished_store.sqlite3"
    writer = RecordingFixtureWriter()

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=writer,
        evidence_package_builder=_qualified_builder(frozenset({"HK-01", "UK-01"})),
        max_writes=5,
        clock=_CLOCK,
    )

    assert report.write_ready == 2
    assert report.admission_hold == 1
    assert report.selected_write_ready == 2
    assert report.candidate_attempts == 2
    assert report.provider_dispatches == 2
    assert report.minted == 2
    assert len(writer.calls) == 2


def test_five_ready_candidates_with_valid_primary_results_insert_five(
    tmp_path: Path,
) -> None:
    proving = _proving(tmp_path)
    expanded = b"""<feed>
      <entry><id>uk-1</id><title>Rule one changed</title><link href="https://example.test/uk-1"/><summary>Rule one took effect.</summary></entry>
      <entry><id>uk-2</id><title>Rule two changed</title><link href="https://example.test/uk-2"/><summary>Rule two took effect.</summary></entry>
      <entry><id>uk-3</id><title>Rule three changed</title><link href="https://example.test/uk-3"/><summary>Rule three took effect.</summary></entry>
    </feed>"""
    connection = sqlite3.connect(proving)
    connection.execute(
        "UPDATE proving_observations SET body=?, body_digest=?, item_count=3 "
        "WHERE source_id='UK-01'",
        (expanded, digest_bytes(expanded)),
    )
    connection.commit()
    connection.close()
    unpublished = tmp_path / "unpublished_store.sqlite3"
    writer = RecordingFixtureWriter()

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(unpublished),
        writer=writer,
        evidence_package_builder=_qualified_builder(
            frozenset({"HK-01", "UK-01", "UK-02"})
        ),
        max_writes=5,
        clock=_CLOCK,
    )

    assert report.selected_write_ready == 5
    assert report.candidate_attempts == 5
    assert report.provider_dispatches == 5
    assert report.minted == 5
    assert len(writer.calls) == 5
    assert len(list_payloads(str(unpublished))) == 5


def _valid_cli_json(prompt: str) -> str:
    raw_claims = next(
        line.removeprefix("approved_governed_claims：")
        for line in prompt.splitlines()
        if line.startswith("approved_governed_claims：")
    )
    claims = json.loads(raw_claims)
    headline = claims[0]["rendered_assertion"]
    body_claims = "；".join(item["rendered_assertion"] for item in claims[1:])
    return json.dumps(
        {
            "title": f"【未出版】{headline}",
            "body": f"本報根據已核實證據報道：{body_claims}",
            "evidence_links": [
                {
                    "governed_claim_id": item["governed_claim_id"],
                    "rendered_assertion": item["rendered_assertion"],
                }
                for item in claims
            ],
        },
        ensure_ascii=False,
    )


def test_malformed_primary_then_one_valid_fallback_consumes_two_leaf_calls(
    tmp_path: Path,
) -> None:
    calls = {"primary": 0, "fallback": 0}

    def primary(_prompt: str) -> str:
        calls["primary"] += 1
        return "not-json"

    def fallback(prompt: str) -> str:
        calls["fallback"] += 1
        return _valid_cli_json(prompt)

    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=CliChainWriter(primary=primary, fallback=fallback),
        evidence_package_builder=_qualified_builder(frozenset({"HK-01"})),
        clock=_CLOCK,
    )

    assert calls == {"primary": 1, "fallback": 1}
    assert report.provider_dispatches == 2
    assert report.primary_dispatches == 1
    assert report.fallback_dispatches == 1
    assert report.minted == 1


def test_second_candidate_cannot_consume_second_cycle_fallback(tmp_path: Path) -> None:
    calls = {"primary": 0, "fallback": 0}

    def primary(_prompt: str) -> str:
        calls["primary"] += 1
        return "malformed"

    def fallback(prompt: str) -> str:
        calls["fallback"] += 1
        return _valid_cli_json(prompt)

    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=CliChainWriter(primary=primary, fallback=fallback),
        evidence_package_builder=_qualified_builder(frozenset({"HK-01", "UK-01"})),
        clock=_CLOCK,
    )

    assert calls == {"primary": 2, "fallback": 1}
    assert report.candidate_attempts == 2
    assert report.provider_dispatches == 3
    assert report.fallback_dispatches == 1
    assert report.minted == 1
    assert report.no_useful_output_circuit_open is True


def test_exhausted_candidate_routes_open_no_useful_output_circuit(
    tmp_path: Path,
) -> None:
    calls = 0

    def unusable(_prompt: str) -> str:
        nonlocal calls
        calls += 1
        return "malformed"

    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=CliChainWriter(primary=unusable, fallback=unusable),
        evidence_package_builder=_qualified_builder(
            frozenset({"HK-01", "UK-01", "UK-02"})
        ),
        clock=_CLOCK,
    )

    assert report.selected_write_ready == 3
    assert report.candidate_attempts == 1
    assert report.provider_dispatches == 2
    assert calls == 2
    assert report.no_useful_output_circuit_open is True
    assert report.minted == 0


def test_systemic_authentication_failure_opens_route_circuit_immediately(
    tmp_path: Path,
) -> None:
    class AuthFailureWriter(FixtureWriter):
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(self, *args: object, **kwargs: object) -> WriterCopy:
            self.calls += 1
            raise WriterDispatchError(
                "provider authentication failed",
                failure_class="SYSTEMIC",
                reason_code="PROVIDER_AUTHENTICATION_FAILURE",
            )

    writer = AuthFailureWriter()
    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=writer,
        evidence_package_builder=_qualified_builder(
            frozenset({"HK-01", "UK-01", "UK-02"})
        ),
        clock=_CLOCK,
    )

    assert writer.calls == 1
    assert report.provider_dispatches == 1
    assert report.writer_circuit_open is True
    assert report.writer_circuit_open_reason == "PROVIDER_AUTHENTICATION_FAILURE"
    assert report.minted == 0


@pytest.mark.parametrize(
    "message",
    (
        "401 Unauthorized",
        "login required",
        "invalid API key",
        "permission denied",
        "invalid model configuration",
        "HTTP 429 Too Many Requests",
        "402 Payment Required",
    ),
)
def test_actual_cli_classifier_marks_provider_control_failures_systemic(
    message: str,
) -> None:
    candidate, package = _candidate_package()

    def primary(_prompt: str) -> str:
        raise RuntimeError(message)

    writer = CliChainWriter(
        primary=primary,
        fallback=lambda _prompt: pytest.fail(
            "systemic failure must not reach fallback"
        ),
    )
    with pytest.raises(WriterDispatchError) as caught:
        writer.dispatch(candidate, package, route="PRIMARY")
    assert caught.value.failure_class == "SYSTEMIC"
    assert caught.value.reason_code == "SYSTEMIC_PROVIDER_FAILURE"


def test_json_character_offset_429_remains_fallback_eligible() -> None:
    candidate, package = _candidate_package()

    def primary(_prompt: str) -> str:
        raise RuntimeError("JSON parse error at column 430 (char 429)")

    writer = CliChainWriter(primary=primary, fallback=lambda _prompt: "unused")
    with pytest.raises(WriterDispatchError) as caught:
        writer.dispatch(candidate, package, route="PRIMARY")
    assert caught.value.failure_class == "FALLBACK_ELIGIBLE"


def test_filler_output_is_rejected_and_never_inserted(tmp_path: Path) -> None:
    class FillerWriter(FixtureWriter):
        def dispatch(
            self,
            candidate: StoryCandidateRecord,
            package: EvidencePackage,
            *,
            route: str,
        ) -> WriterCopy:
            rendered = package.governed_claims[0].rendered_assertion_zh_hant_hk
            return WriterCopy(
                title=f"【未出版】{rendered}",
                body=f"值得注意的是，{rendered}",
                writer_id=f"filler-{route}",
                evidence_package_digest=package.digest,
                evidence_links=(
                    WriterEvidenceLink(
                        f"claim:{candidate.candidate_id}:headline",
                        rendered,
                    ),
                ),
            )

    unpublished = tmp_path / "unpublished_store.sqlite3"
    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(unpublished),
        writer=FillerWriter(),
        evidence_package_builder=_qualified_builder(frozenset({"HK-01"})),
        clock=_CLOCK,
    )

    assert report.provider_dispatches == 2
    assert report.draft_reject == 1
    assert report.minted == 0
    assert list_payloads(str(unpublished)) == ()


def test_syntactically_valid_unmapped_claim_is_rejected(tmp_path: Path) -> None:
    class UnsupportedWriter(FixtureWriter):
        def dispatch(
            self,
            candidate: StoryCandidateRecord,
            package: EvidencePackage,
            *,
            route: str,
        ) -> WriterCopy:
            rendered = package.governed_claims[0].rendered_assertion_zh_hant_hk
            return WriterCopy(
                title=f"【未出版】{rendered}",
                body=f"本報根據已核實證據報道：{rendered}。市民明天必須撤離。",
                writer_id=f"unsupported-{route}",
                evidence_package_digest=package.digest,
                evidence_links=(
                    WriterEvidenceLink(
                        f"claim:{candidate.candidate_id}:headline",
                        rendered,
                    ),
                ),
            )

    unpublished = tmp_path / "unpublished_store.sqlite3"
    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(unpublished),
        writer=UnsupportedWriter(),
        evidence_package_builder=_qualified_builder(frozenset({"HK-01"})),
        clock=_CLOCK,
    )

    assert report.draft_reject == 1
    assert ("REQUIRED_GOVERNED_CLAIM_MISSING", 1) in report.draft_reason_counts
    assert list_payloads(str(unpublished)) == ()


def test_unrelated_claim_in_same_sentence_fails_governed_entailment() -> None:
    _candidate, package = _candidate_package()
    headline, substantive = package.governed_claims
    copy = WriterCopy(
        title=f"【未出版】{headline.rendered_assertion_zh_hant_hk}",
        body=(
            "本報根據已核實證據報道："
            f"{substantive.rendered_assertion_zh_hant_hk}；李家超親自拍板"
        ),
        writer_id="adversarial-writer",
        evidence_package_digest=package.digest,
        evidence_links=tuple(
            WriterEvidenceLink(item.claim_id, item.rendered_assertion_zh_hant_hk)
            for item in package.governed_claims
        ),
    )

    failed = {
        item.reason_code
        for item in validate_writer_copy(copy, package)
        if item.result == "FAIL"
    }
    assert "UNSUPPORTED_CLAIM_RESIDUE" in failed


def test_claim_link_cannot_rebind_another_governed_claim_identity() -> None:
    _candidate, package = _candidate_package()
    headline, substantive = package.governed_claims
    copy = WriterCopy(
        title=f"【未出版】{headline.rendered_assertion_zh_hant_hk}",
        body=(f"本報根據已核實證據報道：{substantive.rendered_assertion_zh_hant_hk}"),
        writer_id="adversarial-writer",
        evidence_package_digest=package.digest,
        evidence_links=(
            WriterEvidenceLink(
                substantive.claim_id,
                headline.rendered_assertion_zh_hant_hk,
            ),
            WriterEvidenceLink(
                substantive.claim_id,
                substantive.rendered_assertion_zh_hant_hk,
            ),
        ),
    )

    failed = {
        item.reason_code
        for item in validate_writer_copy(copy, package)
        if item.result == "FAIL"
    }
    assert "UNSUPPORTED_MATERIAL_CLAIM" in failed


def test_headline_only_draft_cannot_omit_substantive_claim() -> None:
    _candidate, package = _candidate_package()
    headline = package.governed_claims[0]
    copy = WriterCopy(
        title=f"【未出版】{headline.rendered_assertion_zh_hant_hk}",
        body=f"本報根據已核實證據報道：{headline.rendered_assertion_zh_hant_hk}",
        writer_id="headline-only-writer",
        evidence_package_digest=package.digest,
        evidence_links=(
            WriterEvidenceLink(
                headline.claim_id,
                headline.rendered_assertion_zh_hant_hk,
            ),
        ),
    )

    failed = {
        item.reason_code
        for item in validate_writer_copy(copy, package)
        if item.result == "FAIL"
    }
    assert "REQUIRED_GOVERNED_CLAIM_MISSING" in failed


def test_verbatim_source_expression_fails_originality_boundary() -> None:
    _candidate, package = _candidate_package()
    headline, substantive = package.governed_claims
    copy = WriterCopy(
        title=f"【未出版】{headline.rendered_assertion_zh_hant_hk}",
        body=(
            "本報根據已核實證據報道："
            f"{substantive.rendered_assertion_zh_hant_hk}\n{package.passages[0]}"
        ),
        writer_id="copying-writer",
        evidence_package_digest=package.digest,
        evidence_links=tuple(
            WriterEvidenceLink(item.claim_id, item.rendered_assertion_zh_hant_hk)
            for item in package.governed_claims
        ),
    )

    failed = {
        item.reason_code
        for item in validate_writer_copy(copy, package)
        if item.result == "FAIL"
    }
    assert "VERBATIM_SOURCE_EXPRESSION" in failed
    assert "NOT_COMPLETED_ZH_HANT_HK_REPORT" in failed


def test_punctuation_cannot_split_copied_source_sequence() -> None:
    _candidate, package = _candidate_package()
    headline, substantive = package.governed_claims
    source = package.passages[0]
    punctuated_copy = "，".join(
        source[index : index + 11] for index in range(0, len(source), 11)
    )
    copy = WriterCopy(
        title=f"【未出版】{headline.rendered_assertion_zh_hant_hk}",
        body=(
            "本報根據已核實證據報道："
            f"{substantive.rendered_assertion_zh_hant_hk}\n{punctuated_copy}"
        ),
        writer_id="punctuation-copying-writer",
        evidence_package_digest=package.digest,
        evidence_links=tuple(
            WriterEvidenceLink(item.claim_id, item.rendered_assertion_zh_hant_hk)
            for item in package.governed_claims
        ),
    )
    failed = {
        item.reason_code
        for item in validate_writer_copy(copy, package)
        if item.result == "FAIL"
    }
    assert "VERBATIM_SOURCE_EXPRESSION" in failed


def test_default_package_builder_can_admit_explicit_governed_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proving = _proving(tmp_path)
    body = json.dumps(
        {
            "title": "Official deadline changed",
            "description": "The deadline is now 30 September.",
            "url": "https://example.test/governed-deadline",
        }
    ).encode()
    item = parse_observation(
        source_id="UK-02",
        url="https://www.gov.uk/api/content/governed-deadline",
        body=body,
    )[0]
    governed_candidate = form_candidates(
        (
            GroupedObservation(
                "UK-02",
                digest_bytes(body),
                item,
                "2026-08-20T00:00:00.000000Z",
            ),
        )
    )[0]
    base_package = package_for(governed_candidate)
    claim_ids = ("governed-headline", "governed-development")
    evidence = {
        "schema_version": "newsroom.governed-input.v1",
        "candidate_id": governed_candidate.candidate_id,
        "hypothesis_id": governed_candidate.hypothesis_id,
        "base_package_digest": base_package.digest,
        "governed_claims": [
            {
                "claim_id": "governed-headline",
                "claim": "Official deadline changed",
                "passage_index": 0,
                "supporting_excerpt": "Official deadline changed",
                "source_ids": ["UK-02"],
                "source_record_ids": ["source-record:UK-02"],
                "source_authority_decision_ids": ["source-authority:UK-02:headline"],
                "rights_decision_ids": ["rights:UK-02"],
                "dependency_evidence_ids": ["dependency:UK-02"],
                "evidential_origin_ids": ["official-release-1"],
                "authority_class": "RESPONSIBLE_PRIMARY",
                "authority_scope": "Responsible body for its own deadline.",
                "status": "CONFIRMED_FACT",
                "attribution": "UK-02",
                "rendered_assertion_zh_hant_hk": "英國官方公布咗最新限期安排",
                "claim_role": "HEADLINE",
            },
            {
                "claim_id": "governed-development",
                "claim": "The deadline is now 30 September.",
                "passage_index": 0,
                "supporting_excerpt": "The deadline is now 30 September.",
                "source_ids": ["UK-02"],
                "source_record_ids": ["source-record:UK-02"],
                "source_authority_decision_ids": ["source-authority:UK-02:substantive"],
                "rights_decision_ids": ["rights:UK-02"],
                "dependency_evidence_ids": ["dependency:UK-02"],
                "evidential_origin_ids": ["official-release-1"],
                "authority_class": "RESPONSIBLE_PRIMARY",
                "authority_scope": "Responsible body for its own deadline.",
                "status": "CONFIRMED_FACT",
                "attribution": "UK-02",
                "rendered_assertion_zh_hant_hk": "新限期定喺九月三十日",
                "claim_role": "SUBSTANTIVE",
            },
        ],
        "substantive_new_information": ["The deadline is now 30 September."],
        "qualification_evidence": [
            {
                "test": "OFFICIAL_ACTION_OR_DEADLINE",
                "governed_claim_id": "governed-development",
                "test_evidence": [
                    ["action_class", "OFFICIAL_DEADLINE"],
                    ["reader_action", "The deadline is now 30 September."],
                ],
            }
        ],
        "selection_rationale": "Readers need the retained official deadline.",
        "geography": ["UK"],
        "categories": ["Politics and law"],
        "evidence_gate_results": [
            ["CLAIM_TRACEABILITY", "PASS"],
            ["EVIDENCE_SUFFICIENCY", "PASS"],
            ["SOURCE_AUTHORITY", "PASS"],
        ],
        "evidence_gate_evidence": [
            {
                "gate": gate,
                "result": "PASS",
                "governed_claim_ids": list(claim_ids),
                "policy_version": "newsroom.evidence-gates.v1",
            }
            for gate in (
                "CLAIM_TRACEABILITY",
                "EVIDENCE_SUFFICIENCY",
                "SOURCE_AUTHORITY",
            )
        ],
        "freshness_result": "PASS",
        "integrity_result": "PASS",
    }
    connection = sqlite3.connect(proving)
    connection.execute(
        "UPDATE proving_observations SET body=?, body_digest=?, item_count=1 "
        "WHERE source_id='UK-02'",
        (body, digest_bytes(body)),
    )
    retain_observation_revision_first_seen(
        connection,
        source_id="UK-02",
        url="https://www.gov.uk/api/content/governed-deadline",
        body=body,
        observed_at="2026-08-20T00:00:00.000000Z",
    )
    raw_evidence = canonical_json_bytes(evidence).decode()
    package_json_digest = digest_bytes(raw_evidence.encode())
    records = (
        {
            "record_id": "source-record:UK-02",
            "record_type": "SOURCE_RECORD",
            "candidate_id": governed_candidate.candidate_id,
            "base_package_digest": base_package.digest,
            "status": "CURRENT",
            "source_id": "UK-02",
            "canonical_url": "https://example.test/governed-deadline",
            "publisher": "Fixture authority",
            "responsible_body": "Fixture authority",
            "source_type": "PRIMARY_OFFICIAL",
            "authority_class": "RESPONSIBLE_PRIMARY",
            "publication_time": "2026-08-20T00:00:00Z",
            "retrieval_time": "2026-08-20T00:00:00Z",
            "geography": "UK",
            "language": "en",
            "extraction_status": "COMPLETE",
            "rights_decision_id": "rights:UK-02",
            "originating_report_id": "official-release-1",
            "dependency_evidence_ids": ["dependency:UK-02"],
        },
        {
            "record_id": "source-authority:UK-02:headline",
            "record_type": "SOURCE_AUTHORITY_DECISION",
            "candidate_id": governed_candidate.candidate_id,
            "base_package_digest": base_package.digest,
            "status": "CURRENT",
            "source_id": "UK-02",
            "decision": "ADMITTED",
            "authority_class": "RESPONSIBLE_PRIMARY",
            "authority_scope": "Responsible body for its own deadline.",
            "governed_claim_id": "governed-headline",
            "claim_digest": digest_bytes("Official deadline changed".encode()),
        },
        {
            "record_id": "source-authority:UK-02:substantive",
            "record_type": "SOURCE_AUTHORITY_DECISION",
            "candidate_id": governed_candidate.candidate_id,
            "base_package_digest": base_package.digest,
            "status": "CURRENT",
            "source_id": "UK-02",
            "decision": "ADMITTED",
            "authority_class": "RESPONSIBLE_PRIMARY",
            "authority_scope": "Responsible body for its own deadline.",
            "governed_claim_id": "governed-development",
            "claim_digest": digest_bytes("The deadline is now 30 September.".encode()),
        },
        {
            "record_id": "rights:UK-02",
            "record_type": "RIGHTS_DECISION",
            "candidate_id": governed_candidate.candidate_id,
            "base_package_digest": base_package.digest,
            "status": "CURRENT",
            "source_id": "UK-02",
            "decision": "PERMITTED",
            "permitted_use": "PUBLICATION_EVIDENCE",
        },
        {
            "record_id": "dependency:UK-02",
            "record_type": "DEPENDENCY_EVIDENCE",
            "candidate_id": governed_candidate.candidate_id,
            "base_package_digest": base_package.digest,
            "status": "CURRENT",
            "source_id": "UK-02",
            "dependency_status": "RESOLVED",
            "evidential_origin_id": "official-release-1",
            "originating_report_id": "official-release-1",
        },
    )
    retained_records = []
    connection.execute(
        "CREATE TABLE proving_write_evidence_records("
        "record_id TEXT PRIMARY KEY, record_type TEXT NOT NULL, "
        "record_json TEXT NOT NULL, record_digest TEXT NOT NULL)"
    )
    for record in records:
        record_raw = canonical_json_bytes(record).decode()
        record_digest = digest_bytes(record_raw.encode())
        retained_records.append((record["record_id"], record_digest))
        connection.execute(
            "INSERT INTO proving_write_evidence_records VALUES(?,?,?,?)",
            (record["record_id"], record["record_type"], record_raw, record_digest),
        )
    evidence_record_set_digest = digest_bytes(
        canonical_json_bytes(
            {"records": [list(item) for item in sorted(retained_records)]}
        )
    )
    approval = {
        "base_package_digest": base_package.digest,
        "candidate_id": governed_candidate.candidate_id,
        "controller_principal": "HERMES_EVIDENCE_CONTROLLER",
        "decision": "APPROVED",
        "evidence_record_set_digest": evidence_record_set_digest,
        "hypothesis_id": governed_candidate.hypothesis_id,
        "package_json_digest": package_json_digest,
        "policy_version": "newsroom.evidence-approval.v1",
    }
    approval_raw = canonical_json_bytes(approval).decode()
    approval_key = b"fixture-evidence-controller-key-32-bytes"
    monkeypatch.setenv("NEWSROOM_EVIDENCE_APPROVAL_KEY", approval_key.decode())
    signature = hmac.new(
        approval_key,
        approval_raw.encode(),
        hashlib.sha256,
    ).hexdigest()
    connection.execute(
        "CREATE TABLE proving_write_evidence_packages("
        "candidate_id TEXT PRIMARY KEY, package_json TEXT NOT NULL, "
        "package_json_digest TEXT NOT NULL, approval_status TEXT NOT NULL, "
        "approval_record_json TEXT NOT NULL, approval_signature TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO proving_write_evidence_packages VALUES(?,?,?,?,?,?)",
        (
            governed_candidate.candidate_id,
            raw_evidence,
            package_json_digest,
            "APPROVED",
            approval_raw,
            signature,
        ),
    )
    connection.commit()
    connection.close()

    report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=FixtureWriter(),
        max_writes=5,
        clock=_CLOCK,
    )

    assert report.write_ready == 1
    assert report.provider_dispatches == 1
    assert report.minted == 1

    connection = sqlite3.connect(proving)
    connection.execute(
        "DELETE FROM proving_write_evidence_records WHERE record_id='dependency:UK-02'"
    )
    connection.commit()
    connection.close()
    dangling_report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "dangling-unpublished.sqlite3"),
        writer=CountingWriter(),
        max_writes=5,
        clock=_CLOCK,
    )
    assert dangling_report.write_ready == 0
    assert dangling_report.provider_dispatches == 0
    dependency_record = records[-1]
    dependency_raw = canonical_json_bytes(dependency_record).decode()
    connection = sqlite3.connect(proving)
    connection.execute(
        "INSERT INTO proving_write_evidence_records VALUES(?,?,?,?)",
        (
            dependency_record["record_id"],
            dependency_record["record_type"],
            dependency_raw,
            digest_bytes(dependency_raw.encode()),
        ),
    )
    connection.commit()
    connection.close()

    drifted_body = json.dumps(
        {
            "title": "Official deadline changed",
            "description": "The deadline changed again after approval.",
            "url": "https://example.test/governed-deadline",
        }
    ).encode()
    connection = sqlite3.connect(proving)
    connection.execute(
        "UPDATE proving_observations SET body=?, body_digest=? WHERE source_id='UK-02'",
        (drifted_body, digest_bytes(drifted_body)),
    )
    retain_observation_revision_first_seen(
        connection,
        source_id="UK-02",
        url="https://www.gov.uk/api/content/governed-deadline",
        body=drifted_body,
        observed_at="2026-08-20T00:01:00.000000Z",
    )
    connection.commit()
    connection.close()

    drifted_report = run_cycle(
        proving_store=str(proving),
        unpublished_store=str(tmp_path / "drifted-unpublished.sqlite3"),
        writer=CountingWriter(),
        max_writes=5,
        clock=_CLOCK,
    )
    assert drifted_report.write_ready == 0
    assert drifted_report.provider_dispatches == 0


def test_insert_race_does_not_refund_reserved_attempts(
    tmp_path: Path, monkeypatch
) -> None:
    unpublished = tmp_path / "unpublished_store.sqlite3"
    monkeypatch.setattr(
        "newsroom.control_plane.cycle.insert_payload", lambda *_args: False
    )

    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(unpublished),
        writer=FixtureWriter(),
        evidence_package_builder=_qualified_builder(frozenset({"HK-01"})),
        clock=_CLOCK,
    )

    assert report.candidate_attempts == 1
    assert report.provider_dispatches == 1
    assert report.duplicate == 1
    assert report.draft_hold == 1
    assert report.minted == 0
    connection = sqlite3.connect(unpublished)
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_write_candidate_attempts"
        ).fetchone()[0]
        == 1
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM unpublished_writer_provider_attempts"
        ).fetchone()[0]
        == 1
    )
    assert connection.execute(
        "SELECT outcome, reason_codes_json FROM unpublished_draft_outcomes"
    ).fetchone() == ("HOLD", '["DUPLICATE_INSERT_RACE"]')
    connection.close()


def test_final_ledger_counters_equal_retained_attempts_outcomes_and_inserts(
    tmp_path: Path,
) -> None:
    unpublished = tmp_path / "unpublished_store.sqlite3"
    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(unpublished),
        writer=RecordingFixtureWriter(),
        evidence_package_builder=_qualified_builder(frozenset({"HK-01", "UK-01"})),
        clock=_CLOCK,
    )

    connection = sqlite3.connect(unpublished)
    close = json.loads(
        connection.execute(
            "SELECT payload_json FROM ledger WHERE kind='PRIVATE_CYCLE_CLOSE'"
        ).fetchone()[0]
    )
    retained = {
        "candidate_attempts": connection.execute(
            "SELECT COUNT(*) FROM unpublished_write_candidate_attempts"
        ).fetchone()[0],
        "provider_dispatches": connection.execute(
            "SELECT COUNT(*) FROM unpublished_writer_provider_attempts"
        ).fetchone()[0],
        "accepted": connection.execute(
            "SELECT COUNT(*) FROM unpublished_draft_outcomes WHERE outcome='ACCEPTED'"
        ).fetchone()[0],
        "payloads": connection.execute(
            "SELECT COUNT(*) FROM unpublished_surface_payloads"
        ).fetchone()[0],
    }
    connection.close()

    assert (
        close["candidate_attempts"]
        == retained["candidate_attempts"]
        == report.candidate_attempts
    )
    assert (
        close["provider_dispatches"]
        == retained["provider_dispatches"]
        == report.provider_dispatches
    )
    assert (
        close["draft_outcomes"]["ACCEPTED"]
        == retained["accepted"]
        == report.draft_accepted
    )
    assert close["accepted_payload_count"] == retained["payloads"] == report.minted


def test_hold_and_reject_candidates_never_reach_injected_writer(
    tmp_path: Path,
) -> None:
    def builder(candidate: StoryCandidateRecord) -> EvidencePackage:
        qualified = _qualified_builder(frozenset({candidate.items[0].source_id}))(
            candidate
        )
        if candidate.items[0].source_id == "UK-01":
            return package_for(candidate)
        if candidate.items[0].source_id == "UK-02":
            return replace(
                qualified,
                substantive_new_information=(),
            )
        return qualified

    writer = RecordingFixtureWriter()
    report = run_cycle(
        proving_store=str(_proving(tmp_path)),
        unpublished_store=str(tmp_path / "unpublished_store.sqlite3"),
        writer=writer,
        evidence_package_builder=builder,
        clock=_CLOCK,
    )

    assert report.write_ready == 1
    assert report.admission_hold == 1
    assert report.admission_reject == 1
    assert len(writer.calls) == 1


def test_selection_uses_retained_quality_before_candidate_id() -> None:
    candidate, _package = _candidate_package()
    low_candidate = replace(candidate, candidate_id="a-candidate")
    low = _admit_package(
        low_candidate,
        package_for(low_candidate),
        authority_class=ClaimAuthorityClass.INDEPENDENT_RELIABLE,
        origin_ids=("wire-origin", "independent-origin"),
    )
    wire_candidate = replace(candidate, candidate_id="z-wire-copies")
    wire = replace(
        low,
        candidate_id=wire_candidate.candidate_id,
        source_ids=("HK-01", "WIRE-COPY-1", "WIRE-COPY-2"),
    )
    policy = DeterministicWriteAdmission()
    low_decision = policy.decide(low_candidate, low, decided_at="2026-08-20T00:00:00Z")
    wire_decision = policy.decide(
        wire_candidate, wire, decided_at="2026-08-20T00:00:00Z"
    )

    selected = select_write_ready(
        (
            (low_candidate, low, low_decision),
            (wire_candidate, wire, wire_decision),
        ),
        limit=2,
        selected_at="2026-08-20T00:00:00Z",
    )

    assert [item[0].candidate_id for item in selected] == [
        "a-candidate",
        "z-wire-copies",
    ]
    assert selected[0][3].ordering_evidence[2] == "independent_evidential_origins=2"

    primary_candidate = replace(candidate, candidate_id="z-primary")
    primary = _admit_package(primary_candidate, package_for(primary_candidate))
    primary_decision = policy.decide(
        primary_candidate, primary, decided_at="2026-08-20T00:00:00Z"
    )
    selected = select_write_ready(
        (
            (low_candidate, low, low_decision),
            (primary_candidate, primary, primary_decision),
        ),
        limit=2,
        selected_at="2026-08-20T00:00:00Z",
    )
    assert selected[0][0].candidate_id == "z-primary"
    assert selected[0][3].ordering_evidence[1] == "claim_authority_score=4"


def test_connect_upgrades_legacy_ledger_for_retained_counter_payloads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-unpublished.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE ledger(seq INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, "
        "payload_digest TEXT NOT NULL, prev_digest TEXT NOT NULL, digest TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    upgraded = connect(str(path))
    columns = {row[1] for row in upgraded.execute("PRAGMA table_info(ledger)")}
    upgraded.close()

    assert "payload_json" in columns
