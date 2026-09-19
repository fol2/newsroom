"""Bound operational changes without relaxing independent rendering or provenance."""

from dataclasses import replace

import pytest

from newsroom.control_plane.admission import DeterministicWriteAdmission
from newsroom.control_plane.evidence import QualificationEvidence
from newsroom.tests.test_zero_quota_write_loop import (
    _bind_fixture_entities, _candidate_package,
)


REPLACEMENT = (
    "These changes replace end-point assessment (EPA) with a new approach, "
    "called apprenticeship assessment, which allows assessment to take place "
    "throughout the apprenticeship rather than only at the end."
)


def _replacement_package(text=REPLACEMENT):
    candidate, package = _candidate_package()
    claim = _bind_fixture_entities(replace(
        package.governed_claims[1], claim=text, supporting_excerpt=text,
        rendered_assertion_zh_hant_hk=(
            "改動以新學徒評核方式取代終期評核，讓評核在整個學徒期進行，"
            "而非只在期末進行。"
        ),
    ))
    qualification = QualificationEvidence(
        "LAW_RIGHT_STATUS_POLICY", claim.claim_id,
        package.qualification_evidence[1].qualification_record_id,
        (("change_kind", "PUBLIC_POLICY"), ("event_polarity", "AFFIRMED"),
         ("change_relation", "NEW_OR_CHANGED_STATE"),
         ("material_relation_span", text), ("new_state", text)),
    )
    package = replace(
        package, passages=(package.passages[0] + "\n" + text,),
        governed_claims=(package.governed_claims[0], claim),
        substantive_new_information=(package.governed_claims[0].claim, text),
        qualification_evidence=(package.qualification_evidence[0], qualification),
        resolved_evidence_records=(*package.resolved_evidence_records, *(
            (record_id, "fixture-entity-digest")
            for _, _, record_id in claim.named_entity_evidence
        )),
    )
    return candidate, package


def test_exact_operational_replacement_sentence_passes_qualification():
    candidate, package = _replacement_package()
    decision = DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-09-20T00:00:00Z",
    )
    assert decision.decision == "WRITE_READY", decision.stable_reason_codes


@pytest.mark.parametrize("source_prefix", [
    "Officials deny that ", "Subject to approval, ", "Officials propose that ",
    "Officials deny that\n",
])
def test_operational_replacement_cannot_excise_source_context(source_prefix):
    candidate, package = _replacement_package()
    # Model-selected claim, excerpt and witness remain unchanged and byte-bound.
    # The authoritative source sentence, rather than that selection, governs.
    package = replace(package, passages=(
        package.passages[0].replace(REPLACEMENT, source_prefix + REPLACEMENT),
    ))
    decision = DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-09-20T00:00:00Z",
    )
    assert decision.decision == "HOLD"
    assert decision.stable_reason_codes == ("QUALIFICATION_EVIDENCE_NOT_EXACT",)


@pytest.mark.parametrize("new_state", ["a new approach", "apprenticeship assessment"])
def test_operational_replacement_accepts_exact_parsed_new_regime(new_state):
    candidate, package = _replacement_package()
    qualification = package.qualification_evidence[1]
    evidence = dict(qualification.test_evidence)
    evidence["new_state"] = new_state
    package = replace(package, qualification_evidence=(
        package.qualification_evidence[0],
        replace(qualification, test_evidence=tuple(evidence.items())),
    ))
    decision = DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-09-20T00:00:00Z",
    )
    assert decision.decision == "WRITE_READY", decision.stable_reason_codes


@pytest.mark.parametrize("text", [
    REPLACEMENT.replace("assessment", "inspection"),
    REPLACEMENT.replace("These changes replace", "This policy replaces"),
    REPLACEMENT.replace("a new approach, called apprenticeship assessment", "a new assessment process"),
])
def test_operational_replacement_is_not_a_retained_sentence_lookup(text):
    candidate, package = _replacement_package(text)
    assert DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-09-20T00:00:00Z",
    ).decision == "WRITE_READY"


@pytest.mark.parametrize("text", [
    REPLACEMENT.replace("These changes", "These proposed changes"),
    REPLACEMENT.replace("changes replace", "changes may replace"),
    REPLACEMENT.replace("changes replace", "changes do not replace"),
    REPLACEMENT.replace("a new approach", "a proposed new approach"),
    REPLACEMENT.replace("apprenticeship assessment,", "assessment subject to approval,"),
    REPLACEMENT.replace("which allows", "which does not allow"),
    REPLACEMENT.replace("the apprenticeship rather", "the unchanged apprenticeship rather"),
    REPLACEMENT.replace("the apprenticeship rather", "the unknown apprenticeship rather"),
    REPLACEMENT.replace("apprenticeship assessment,", "apprenticeship inspection,"),
    REPLACEMENT.replace("allows assessment", "allows inspection"),
    REPLACEMENT.replace("apprenticeship assessment,", "assessing proposals for assessment,"),
    REPLACEMENT.replace(", which allows", " without changing the operation, which allows"),
    REPLACEMENT.split(", which allows")[0] + ".",
    REPLACEMENT.replace("throughout the apprenticeship rather than only at the end", "only at the end"),
])
def test_proposed_negated_unknown_renamed_or_unrelated_replacement_holds(text):
    candidate, package = _replacement_package(text)
    decision = DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-09-20T00:00:00Z",
    )
    assert decision.decision == "HOLD"
    assert "QUALIFICATION_EVIDENCE_NOT_EXACT" in decision.stable_reason_codes


@pytest.mark.parametrize("mutation", [
    "fragment", "excised_context", "missing_source", "wrong_claim",
    "wrong_kind", "wrong_test", "unknown_kind", "old_state", "rendering",
])
def test_operational_replacement_preserves_other_boundaries(mutation):
    candidate, package = _replacement_package(
        "Officials deny that " + REPLACEMENT if mutation == "excised_context" else REPLACEMENT,
    )
    claim, qualification = package.governed_claims[1], package.qualification_evidence[1]
    evidence = dict(qualification.test_evidence)
    if mutation == "unknown_kind":
        evidence["change_kind"] = "UNKNOWN"
        with pytest.raises(ValueError, match="qualification"):
            replace(qualification, test_evidence=tuple(evidence.items()))
        return
    if mutation == "fragment":
        evidence["material_relation_span"] = REPLACEMENT.split(", which allows")[0]
    elif mutation == "excised_context":
        evidence["material_relation_span"] = REPLACEMENT
    elif mutation == "old_state":
        evidence["new_state"] = "end-point assessment (EPA)"
    elif mutation == "wrong_kind":
        evidence["change_kind"] = "STATUS"
    elif mutation == "wrong_test":
        evidence = {
            "domain": "EDUCATION", "event_polarity": "AFFIRMED",
            "effect_relation": "MATERIAL_PRACTICAL_EFFECT",
            "material_relation_span": REPLACEMENT, "practical_effect": REPLACEMENT,
        }
        qualification = QualificationEvidence(
            "HOUSEHOLD_PRACTICAL_EFFECT", claim.claim_id,
            qualification.qualification_record_id, tuple(evidence.items()),
        )
    elif mutation == "wrong_claim":
        qualification = replace(qualification, governed_claim_id="missing-claim")
    elif mutation == "missing_source":
        package = replace(package, passages=(package.governed_claims[0].claim,))
    elif mutation == "rendering":
        claim = replace(claim, rendered_assertion_zh_hant_hk=(
            claim.rendered_assertion_zh_hant_hk + " apprenticeship assessment"
        ))
    package = replace(
        package, governed_claims=(package.governed_claims[0], claim),
        qualification_evidence=(package.qualification_evidence[0], replace(
            qualification, test_evidence=tuple(evidence.items()),
        )),
    )
    decision = DeterministicWriteAdmission().decide(
        candidate, package, decided_at="2026-09-20T00:00:00Z",
    )
    assert decision.decision == "HOLD"
    assert ("INVALID_GOVERNED_CLAIM_EVIDENCE" if mutation in {"missing_source", "rendering"}
            else "QUALIFICATION_EVIDENCE_NOT_EXACT") in decision.stable_reason_codes
