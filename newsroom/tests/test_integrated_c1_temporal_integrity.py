from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from newsroom.integrated import IntegratedStateError

from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import candidate_request, manifest, proof
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def test_candidate_admission_rejects_context_from_future_serving_time(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    future_time = type(FIXED_NOW)(
        FIXED_NOW.value + timedelta(minutes=1)
    )
    future = replace(
        graph.context,
        metadata=replace(
            graph.context.metadata,
            serving_time=future_time,
        ),
        recorded_at=future_time,
    )
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            IntegratedStateError,
            match="stale against active projection authority",
        ):
            system.candidates.admit(
                candidate_request(
                    future,
                    key="integrated-future-serving-context",
                ),
                context=future,
                manifest=manifest(),
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()
