from __future__ import annotations

from newsroom.authority import INCREMENT_1A_TRACEABILITY


def test_increment_1a_traceability_names_canonical_authority() -> None:
    flattened = {item for values in INCREMENT_1A_TRACEABILITY.values() for item in values}
    assert {"ADR-0001", "ADR-0002", "ADR-0004", "GRPROD-020"} <= flattened
    assert all(module.startswith("newsroom.authority.") for module in INCREMENT_1A_TRACEABILITY)
