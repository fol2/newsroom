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
        ("ETA", "OFFICIAL_TERM"),
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
    assert evidence.bounded_named_entities("UKVI and ATASX and ETAX and XETA") == frozenset()


def test_university_of_name_is_complete_and_drops_the_determiner():
    source = "The University of Salford published the guidance."

    assert evidence.bounded_named_entities(source) == frozenset(
        {("University of Salford", "ORGANISATION")}
    )
    assert evidence.bounded_named_entities(
        "University of Salford."
    ) == frozenset({("University of Salford", "ORGANISATION")})
    assert evidence._has_bounded_named_entity_shape(
        "University of Salford", "ORGANISATION", source_context=source,
    )
    assert _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim=source,
        supporting_excerpt=source,
        named_entities=("University of Salford",),
        rendered_assertion_zh_hant_hk="University of Salford公布指引。",
    ))


@pytest.mark.parametrize(
    "text",
    (
        "The University published the guidance.",
        "University of Salford-X published the guidance.",
        "University of Salford_X published the guidance.",
        "University of Salford2 published the guidance.",
        "University of Salford.ac.uk published the guidance.",
        "University of Salford Manchester published the guidance.",
        "University of Salford/School published the guidance.",
        "XUniversity of Salford published the guidance.",
        "-University of Salford published the guidance.",
        "_University of Salford published the guidance.",
        ".University of Salford published the guidance.",
    ),
)
def test_university_of_name_rejects_truncations_and_extensions(text):
    assert evidence.bounded_named_entities(text) == frozenset()


def test_retained_consumer_corrections_do_not_hide_other_unsupported_literals():
    assert not _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim="The University of Salford and DfE published the guidance.",
        supporting_excerpt=(
            "The University of Salford and DfE published the guidance."
        ),
        named_entities=("University of Salford",),
        rendered_assertion_zh_hant_hk="University of Salford及DfE公布指引。",
    ))
    assert not _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim="Kent Police dispersed a crowd without notice.",
        supporting_excerpt="Kent Police dispersed a crowd without notice.",
        named_entities=("Kent Police",),
        rendered_assertion_zh_hant_hk="Kent Police在no-notice情況下驅散人群。",
    ))


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


def test_source_context_types_official_route_framework_and_level_codes():
    source = (
        "English language requirement for settlement on the UK Ancestry route "
        "UKA 15.1. The applicant must show English language ability on the Common "
        "European Framework of Reference for Languages in speaking and listening "
        "to at least level B1 or level B2."
    )

    assert evidence.bounded_named_entities(
        source,
        source_context=source,
    ) == frozenset({
        ("UK Ancestry", "OFFICIAL_TERM"),
        ("Common European Framework of Reference for Languages", "OFFICIAL_TERM"),
        ("B1", "OFFICIAL_TERM"),
        ("B2", "OFFICIAL_TERM"),
    })


@pytest.mark.parametrize(
    ("claim", "source_context", "official_term"),
    (
        (
            "The qualification must meet ST8.1/2/3 of the Rules.",
            "Immigration Rules Appendix Graduate. "
            "The qualification must meet ST8.1/2/3 of the Rules.",
            "ST8.1/2/3",
        ),
        (
            "Permission was previously granted under Part 14: stateless persons.",
            "Immigration Rules part 14: stateless persons. "
            "Permission was previously granted under Part 14: stateless persons.",
            "Part 14: stateless persons",
        ),
    ),
)
def test_source_context_types_bounded_immigration_rule_references(
    claim, source_context, official_term,
):
    assert evidence.bounded_named_entities(
        claim,
        source_context=source_context,
    ) == frozenset({(official_term, "OFFICIAL_TERM")})


@pytest.mark.parametrize(
    ("claim", "source_context"),
    (
        (
            "The qualification must meet ST8.1/2/3X of the Rules.",
            "Immigration Rules Appendix Graduate. ST8.1/2/3 applies.",
        ),
        (
            "The qualification must meet ST8.1/2/3 of the Rules.",
            "A training handbook says ST8.1/2/3 applies.",
        ),
        (
            "Permission was granted under Part 14: stateless persons.",
            "A handbook cites Part 14: stateless persons.",
        ),
        (
            "Permission was granted under Part 14: stateless personsX.",
            "Immigration Rules part 14: stateless persons.",
        ),
    ),
)
def test_immigration_rule_references_require_exact_declared_source_context(
    claim, source_context,
):
    assert evidence.bounded_named_entities(
        claim,
        source_context=source_context,
    ) == frozenset()


@pytest.mark.parametrize("suffix", ("/4.", ".4.", "_extra.", "X.", ".foo", "-extra"))
def test_immigration_citation_source_prefix_is_not_an_exact_token(suffix):
    assert evidence.bounded_named_entities(
        "The code is ST8.1/2/3",
        source_context="Immigration Rules Appendix Graduate. The code is ST8.1/2/3" + suffix,
    ) == frozenset()


def test_immigration_citation_allows_sentence_ending_punctuation():
    claim = "The code is ST8.1/2/3."
    assert evidence.bounded_named_entities(
        claim, source_context="Immigration Rules Appendix Graduate. " + claim,
    ) == frozenset({("ST8.1/2/3", "OFFICIAL_TERM")})


@pytest.mark.parametrize("suffix", (" and related persons.", "-related.", "/related.", "_related.", ".related.", "X."))
def test_immigration_part_source_prefix_is_not_an_exact_title(suffix):
    assert evidence.bounded_named_entities(
        "Permission under Part 14: stateless persons",
        source_context="Immigration Rules Part 14: stateless persons" + suffix,
    ) == frozenset()


@pytest.mark.parametrize("suffix", (" today.", " Today.", " 2.", "\ttoday."))
def test_immigration_part_word_limit_does_not_truncate_source_title(suffix):
    term = "Part 14: stateless persons and related people"
    assert evidence.bounded_named_entities(
        term, source_context="Immigration Rules " + term + suffix,
    ) == frozenset()


@pytest.mark.parametrize("suffix", (".", ",", ";", ":", ")", "\nThe rules apply."))
def test_immigration_part_title_allows_real_end_delimiters(suffix):
    term = "Part 14: stateless persons"
    assert evidence.bounded_named_entities(
        term, source_context="Immigration Rules " + term + suffix,
    ) == frozenset({(term, "OFFICIAL_TERM")})


def test_declared_immigration_part_title_can_prefix_ordinary_claim_prose():
    term = "Part 14: stateless persons"
    claim = (
        "A Stateless person or their partner or dependent child previously granted "
        f"permission under {term} applying on or after 11 November 2025 will be "
        "considered under this route."
    )

    assert evidence.bounded_named_entities(
        claim,
        source_context=f"Immigration Rules part 14: stateless persons. {claim}",
    ) == frozenset({(term, "OFFICIAL_TERM")})


def test_official_immigration_rules_page_types_bounded_inline_part_reference():
    term = "Part 14: stateless persons"
    claim = (
        "A Stateless person previously granted permission under "
        f"{term} applying on or after 11 November 2025 will be considered."
    )
    source = f"Immigration Rules Appendix Statelessness\n\n{claim}"

    assert evidence.bounded_named_entities(
        claim, source_context=source,
    ) == frozenset({(term, "OFFICIAL_TERM")})


@pytest.mark.parametrize(
    ("claim", "source"),
    (
        (
            "Permission under Part 14: stateless persons applying on or after today.",
            "Immigration Rules Appendix Statelessness\n\nPermission under Part 13: "
            "stateless persons applying on or after today.",
        ),
        (
            "Permission under Part 14: stateless persons applying on or after today.",
            "A handbook says permission under Part 14: stateless persons applying "
            "on or after today.",
        ),
        (
            "Permission under Part 14: ordinary copied prose applying on or after "
            "today.",
            "Immigration Rules Appendix Statelessness\n\nPermission under Part 14: "
            "ordinary copied prose applying on or after today.",
        ),
    ),
)
def test_inline_part_reference_rejects_mutation_unrelated_source_and_prose(
    claim, source,
):
    assert evidence.bounded_named_entities(claim, source_context=source) == frozenset()


@pytest.mark.parametrize("suffix", ("X", "/related", "_related", ".related"))
def test_inline_part_reference_rejects_attached_suffix_mutation(suffix):
    term = "Part 14: stateless persons"
    source = (
        "Immigration Rules Appendix Statelessness\n\nPermission under "
        f"{term} applying on or after today."
    )
    claim = f"Permission under {term}{suffix} applying on or after today."

    assert evidence.bounded_named_entities(claim, source_context=source) == frozenset()


@pytest.mark.parametrize(
    ("claim_term", "declaration"),
    (
        ("Part 14: stateless personsX", "Immigration Rules part 14: stateless persons."),
        ("Part 14: stateless persons", "A handbook cites Part 14: stateless persons."),
        (
            "Part 14: stateless persons",
            "Immigration Rules part 14: stateless persons and related people.",
        ),
    ),
)
def test_ordinary_claim_prefix_requires_the_exact_declared_part_title(
    claim_term, declaration,
):
    claim = f"Permission under {claim_term} applying from today."
    assert evidence.bounded_named_entities(
        claim, source_context=f"{declaration} {claim}",
    ) == frozenset()


def test_immigration_part_short_reference_does_not_bind_longer_declaration():
    term = "Part 14: stateless persons"
    assert evidence.bounded_named_entities(
        term,
        source_context="Immigration Rules " + term + " and related persons. " + term + ".",
    ) == frozenset()


@pytest.mark.parametrize(
    "source",
    (
        "UK Ancestry applicants may apply.",
        "UK Ancestry routes apply.",
        "Common european Framework of Reference for Languages applies.",
        "The requirement is level B3.",
        "ANOTHER DELETED HEADING",
    ),
)
def test_contextual_official_terms_require_the_exact_bounded_shape(source):
    assert evidence.bounded_named_entities(source, source_context=source) in {
        frozenset(),
        frozenset({("UK", "PLACE")}),
    }


def test_official_route_context_near_match_does_not_bind():
    claim = "The UK Ancestry route applies."
    context = "UK Ancestry routes apply."
    assert evidence.bounded_named_entities(
        claim,
        source_context=context,
    ) == frozenset({("UK", "PLACE")})


def test_ordinary_english_and_all_caps_prose_are_not_official_terms():
    assert evidence.bounded_named_entities(
        "immigration bail; Turkish; 36 months; 5 years; places; "
        "invitation to apply; DELETED"
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


def test_source_only_official_term_is_not_added_to_rendering():
    names = evidence.bounded_named_entities("Hong Kong - 1,000 places")
    assert names == frozenset({("Hong Kong", "PLACE")})
    assert not _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim="Hong Kong - 1,000 places",
        supporting_excerpt="Hong Kong - 1,000 places",
        named_entities=("Hong Kong",),
        rendered_assertion_zh_hant_hk=(
            "Youth Mobility Scheme二零二六年配額包括Hong Kong - 1,000 places"
        ),
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
