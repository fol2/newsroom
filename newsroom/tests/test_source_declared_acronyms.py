"""Source declarations replace per-acronym rendering allow-lists."""

from types import SimpleNamespace

import pytest

from newsroom.control_plane import evidence
from newsroom.control_plane.admission import _valid_zh_hant_hk_rendering


@pytest.mark.parametrize(("declaration", "acronym"), (
    ("general consent order (GCO)", "GCO"),
    ("General Consent Orders (GCOs)", "GCOs"),
    ("Department for Education (DfE)", "DfE"),
    ("Education and Skills Funding Agency (ESFA)", "ESFA"),
    ("national non-domestic rates (NNDR)", "NNDR"),
    ("Condition Improvement Fund (CIF)", "CIF"),
))
def test_exact_source_declaration_types_only_its_matching_acronym(declaration, acronym):
    claim = f"The {acronym} now applies."
    context = f"The {declaration} was introduced. {claim}"
    names = evidence.bounded_named_entities(claim, source_context=context)
    assert names == frozenset({(acronym, "OFFICIAL_TERM")})
    assert evidence._has_bounded_named_entity_shape(acronym, "OFFICIAL_TERM", source_context=claim)
    rendered = f"現時適用{acronym}。"
    assert evidence.rendered_named_entities(rendered, names) == names
    assert _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim=claim, supporting_excerpt=claim, named_entities=(acronym,),
        rendered_assertion_zh_hant_hk=rendered,
    ))


@pytest.mark.parametrize(("context", "claim"), (
    ("GCO applies.", "The GCO now applies."),
    ("general consent order (GCA)", "The GCA now applies."),
    ("general consent order (GCO)", "The GCA now applies."),
    ("general consent order (gco)", "The gco now applies."),
    ("general consent order (GCO)", "The GCOX now applies."),
    ("general consent order (GCO)", "The GCO_2 now applies."),
    ("general consent order (GCO)", "The XGCO now applies."),
    ("general consent order (GCO)", "The GCO2 now applies."),
    ("General Consent Orders (GCOs)", "The GCO now applies."),
    ("General Consent Order (GCO)", "The GCOs now applies."),
    ("general consent order (GCO)", "The GCO-related now applies."),
    ("general consent order (GCO)", "The GCO/other now applies."),
    ("general consent order (GCO)", "The GCO.other now applies."),
    ("ordinary copied prose (DELETED)", "DELETED now applies."),
))
def test_absent_mismatched_or_extended_source_acronym_is_not_a_name(context, claim):
    assert evidence.bounded_named_entities(claim, source_context=context) == frozenset()


def test_declaration_does_not_whitelist_other_latin_prose_or_add_unclaimed_entity():
    context = "general consent order (GCO) applies."
    assert evidence.bounded_named_entities("The form changed.", source_context=context) == frozenset()
    assert not _valid_zh_hant_hk_rendering(SimpleNamespace(
        claim="The GCO now applies.", supporting_excerpt=context, named_entities=("GCO",),
        rendered_assertion_zh_hant_hk="GCO now applies。",
    ))
