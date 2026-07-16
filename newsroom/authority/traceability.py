"""Increment 1A requirement-to-module traceability.

The map is intentionally narrow: it identifies the Accepted records implemented
by this review boundary without claiming later graph, source, evidence or
publication conformance.
"""

INCREMENT_1A_TRACEABILITY: dict[str, tuple[str, ...]] = {
    "ADR-0001": ("store", "objects", "service"),
    "ADR-0002": ("migrations", "store", "objects"),
    "ADR-0004": ("types", "models", "store"),
    "DREC-001": ("types",),
    "DREC-002": ("types", "models"),
    "DREC-003": ("types", "canonical"),
    "DREC-004": ("store",),
    "DREC-005": ("types",),
    "DREC-006": ("store",),
    "DREC-007": ("store",),
    "DREC-016": ("objects", "store"),
    "DREC-070": ("models", "store"),
    "DREC-073": ("types", "models"),
    "DREC-074": ("types",),
    "DREC-076": ("models", "store"),
    "DREC-077": ("store",),
    "GRAG-001": ("types", "models", "store"),
    "GRAG-002": ("store",),
    "GRAG-003": ("objects", "store"),
    "GRAG-004": ("store",),
    "GRAG-005": ("store",),
    "GRAG-010": ("types",),
    "GRAG-011": ("types",),
    "GRAG-012": ("types", "models"),
    "GRAG-030": ("types",),
    "GRPROD-005": ("types", "models", "store"),
    "GRPROD-020": ("traceability",),
}
