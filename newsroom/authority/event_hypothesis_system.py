"""Public opener for the checked Event Hypothesis authority facade."""

from __future__ import annotations

from . import _event_hypothesis_system as _private


def open_event_hypothesis_authority_system(*args: object, **kwargs: object) -> object:
    """Open and immediately wrap the checked v21 authority."""

    raw = _private.EventHypothesisAuthority.open(*args, **kwargs)
    try:
        from newsroom.increment6.hypotheses import (
            EventHypothesisAuthority,
            HypothesisContractError,
            _compose_event_hypothesis_authority,
        )

        facade = _compose_event_hypothesis_authority(raw)
        if type(facade) is not EventHypothesisAuthority:
            raise HypothesisContractError(
                "Hypothesis authority system returned a forged facade"
            )
        return facade
    except BaseException:
        raw.close()
        raise


__all__ = [
    "open_event_hypothesis_authority_system",
]
