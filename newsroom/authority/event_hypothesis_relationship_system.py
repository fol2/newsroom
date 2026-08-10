"""Public opener for the checked Hypothesis relationship authority facade."""

from . import _event_hypothesis_relationship_system as _private


def open_event_hypothesis_relationship_authority_system(
    *args: object, **kwargs: object
) -> object:
    """Open and immediately wrap the checked v22 authority."""

    raw = _private.open_relationship_authority(*args, **kwargs)
    try:
        from newsroom.increment6.relationships import (
            EventHypothesisRelationshipAuthority,
            RelationshipContractError,
            _compose_event_hypothesis_relationship_authority,
        )

        facade = _compose_event_hypothesis_relationship_authority(raw)
        if type(facade) is not EventHypothesisRelationshipAuthority:
            raise RelationshipContractError(
                "relationship authority system returned a forged facade"
            )
        return facade
    except BaseException:
        raw.close()
        raise


__all__ = [
    "open_event_hypothesis_relationship_authority_system",
]
