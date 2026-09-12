"""Provider-free reproductions of retained native assessment contract failures."""

from types import SimpleNamespace

import pytest

from newsroom.control_plane import evidence
from newsroom.control_plane.admission import _valid_zh_hant_hk_rendering
from newsroom.control_plane.native_evidence import (
    NativeEvidenceController,
    NativeEvidenceHold,
)


@pytest.mark.parametrize(
    ("name", "kind"),
    (
        ("UK", "PLACE"),
        ("Hong Kong", "PLACE"),
        ("British National (Overseas)", "OFFICIAL_TERM"),
        ("ATAS", "OFFICIAL_TERM"),
        ("eVisa", "OFFICIAL_TERM"),
    ),
)
def test_source_bound_operational_names_can_be_preserved_in_hk_copy(name, kind):
    source = f"Applicants must use {name}."
    names = evidence.bounded_named_entities(source)
    assert names == frozenset({(name, kind)})
    rendered = f"申請人須使用{name}。"
    assert evidence.rendered_named_entities(rendered, names) == names
    assert _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim=source, supporting_excerpt=source,
        named_entities=(name,), rendered_assertion_zh_hant_hk=rendered,
    ))


def test_short_registry_names_do_not_match_other_latin_words():
    assert evidence.bounded_named_entities("UKVI and ATASX") == frozenset()


@pytest.mark.parametrize(
    "source",
    (
        "General Grounds for Refusal",
        "Part Suitability",
        "Appendix Victim of Domestic Abuse",
        "AR(EU)1.1",
        "Appendix O",
    ),
)
def test_source_bound_official_english_references_can_be_preserved(source):
    names = evidence.bounded_named_entities(source)
    assert names == frozenset({(source, "OFFICIAL_TERM")})
    assert evidence.rendered_named_entities(f"適用{source}。", names) == names
    assert evidence.rendered_named_entities(f"適用{source}X。", names) != names
    invented = "General Grounds for Refusal" if source == "Appendix O" else "Appendix O"
    assert evidence.rendered_named_entities(f"適用{invented}。", names) != names


def test_bounded_official_abbreviation_does_not_admit_arbitrary_all_caps_words():
    source = "Immigration Rules Appendix ECAA: Extension of Stay. ECAA workers."
    assert evidence.bounded_named_entities(source) == frozenset(
        {("ECAA", "OFFICIAL_TERM")}
    )
    assert evidence.bounded_named_entities("ECAA workers may apply.") == frozenset(
        {("ECAA", "OFFICIAL_TERM")}
    )
    assert evidence.bounded_named_entities("ECAA route applies.") == frozenset(
        {("ECAA", "OFFICIAL_TERM")}
    )
    assert evidence.bounded_named_entities("ECAAX workers may apply.") == frozenset()
    assert evidence.bounded_named_entities("DELETED workers may apply.") == frozenset()


def test_ordinary_english_and_all_caps_prose_are_not_official_terms():
    assert evidence.bounded_named_entities(
        "immigration bail; Turkish; 36 months; DELETED"
    ) == frozenset()


def test_preserved_source_person_does_not_need_an_english_reporting_verb():
    names = evidence.bounded_named_entities("John Smith said services would resume.")
    assert names == frozenset({("John Smith", "PERSON")})
    assert evidence.rendered_named_entities("John Smith表示服務將恢復。", names) == names
    assert evidence.rendered_named_entities("John Smith表示英國服務將恢復。", names) != names
    assert evidence.rendered_named_entities("John Smithson表示服務將恢復。", names) != names


def test_preserved_names_do_not_exempt_unrecognised_english_prose():
    assert not _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim="Applicants in the UK must apply.",
        supporting_excerpt="Applicants in the UK must apply.",
        named_entities=("UK",),
        rendered_assertion_zh_hant_hk="UK申請人must apply。",
    ))


@pytest.mark.parametrize(
    "ordinary",
    (
        "獲immigration bail的人。",
        "Au pair職位DELETED Working holidaymakers DELETED。",
    ),
)
def test_source_layout_and_ordinary_english_are_not_rendered_entities(ordinary):
    assert evidence.bounded_named_entities(ordinary) == frozenset()
    assert not _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim=ordinary, supporting_excerpt=ordinary,
        named_entities=(), rendered_assertion_zh_hant_hk=ordinary,
    ))


def test_no_claims_is_not_a_source_authority_failure():
    package = SimpleNamespace(
        candidate_id="candidate", governed_claims=(),
        substantive_new_information=(), qualification_evidence=(),
    )
    with pytest.raises(NativeEvidenceHold, match="NO_QUALIFYING_NEW_INFORMATION"):
        NativeEvidenceController._records(
            SimpleNamespace(digest="base"), package,
            (SimpleNamespace(unit=SimpleNamespace(source_id="UK-03")),),
            (SimpleNamespace(),), SimpleNamespace(source_authority=()),
        )


@pytest.mark.parametrize("field", ("governed_claims", "substantive_new_information", "qualification_evidence"))
def test_missing_authority_with_claim_or_qualification_evidence_stays_held(field):
    package = SimpleNamespace(
        candidate_id="candidate", governed_claims=(),
        substantive_new_information=(), qualification_evidence=(),
    )
    setattr(package, field, ("present",))
    with pytest.raises(NativeEvidenceHold, match="SOURCE_AUTHORITY_HOLD"):
        NativeEvidenceController._records(
            SimpleNamespace(digest="base"), package,
            (SimpleNamespace(unit=SimpleNamespace(source_id="UK-03")),),
            (SimpleNamespace(),), SimpleNamespace(source_authority=()),
        )
