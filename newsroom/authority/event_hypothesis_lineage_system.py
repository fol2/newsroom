"""Public opener for the checked v23 Hypothesis lineage authority facade."""

from . import _event_hypothesis_lineage_system as _private


def open_event_hypothesis_lineage_authority_system(
    *args: object, **kwargs: object
) -> object:
    return _private.open_lineage_authority(*args, **kwargs)


__all__ = ["open_event_hypothesis_lineage_authority_system"]
