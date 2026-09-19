"""Month-granularity localisation preserves retained factual precision."""

from dataclasses import replace

import pytest

from newsroom.control_plane.evidence import (
    ClaimAuthorityClass, GovernedClaimEvidence, GovernedClaimStatus,
)


def _claim(source: str, target: str) -> GovernedClaimEvidence:
    text = f"The programme changed in {source}."
    return GovernedClaimEvidence(
        claim_id="claim", claim=text, passage_index=0, supporting_excerpt=text,
        source_ids=("source",), source_record_ids=("record",),
        source_authority_decision_ids=("authority",), rights_decision_ids=("rights",),
        dependency_evidence_ids=("dependency",), evidential_origin_ids=("origin",),
        authority_class=ClaimAuthorityClass.RESPONSIBLE_PRIMARY,
        authority_scope="Programme changes", status=GovernedClaimStatus.CONFIRMED_FACT,
        attribution="The originating authority", claim_role="SUBSTANTIVE",
        rendered_assertion_zh_hant_hk=f"計劃於{target}修訂。",
        semantic_relation_evidence_id="semantic",
        localised_factual_expressions=((source, target),),
    )


@pytest.mark.parametrize(("source", "target"), (
    # Exact retained pairs from ledger results 25853 and 25848.
    ("February 2025", "2025年2月"),
    ("January", "一月"),
    ("October", "十月"),
    ("December 2026", "二零二六年十二月"),
    ("March", "3月"),
))
def test_month_localisation_preserves_source_precision(source, target):
    claim = _claim(source, target)
    assert claim.localised_factual_expressions == ((source, target),)
    for changes in (
        {"claim": "The programme changed.", "supporting_excerpt": "The programme changed."},
        {"rendered_assertion_zh_hant_hk": "計劃已修訂。"},
    ):
        with pytest.raises(ValueError, match="equivalent exact claim facts"):
            replace(claim, **changes)


@pytest.mark.parametrize(("source", "target"), (
    ("January", "二月"),
    ("January", "2025年一月"),
    ("January 2025", "一月"),
    ("January 2025", "2026年一月"),
    ("January", "一月一日"),
    ("1 January", "一月"),
    ("January", "1個月"),
    ("1 month", "一月"),
    ("January 2025", "2025年0月"),
    ("January 2025", "2025年13月"),
    ("January 0000", "零年一月"),
    ("Januaryish", "一月"),
    ("Jan", "一月"),
))
def test_month_localisation_rejects_changed_precision_units_or_value(source, target):
    with pytest.raises(ValueError, match="equivalent exact claim facts"):
        _claim(source, target)
