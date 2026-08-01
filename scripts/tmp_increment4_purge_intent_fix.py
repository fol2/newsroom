from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact patch anchor, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''from newsroom.authority.persistence import AuthorityPersistenceError
''',
    '''from newsroom.authority.persistence import (
    AuthorityPersistenceError,
    ExpectedVersionConflict,
)
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''                    {
                        "generation_id": str(request.generation_id),
                        "snapshot_digest": snapshot_digest,
                    },
''',
    '''                    {
                        "generation_id": str(request.generation_id),
                        "snapshot_digest": snapshot_digest,
                        "purge_retired_generation": (
                            request.purge_retired_generation
                        ),
                    },
''',
)

replace_once(
    "newsroom/authority/_increment4_neo4j_boundary.py",
    '''        self._create_generation(
            request=request,
            snapshot_digest=request.snapshot.canonical_digest,
            proof=proof,
        )
        promotion = self._promotion_for_generation(request.generation_id)
''',
    '''        try:
            self._create_generation(
                request=request,
                snapshot_digest=request.snapshot.canonical_digest,
                proof=proof,
            )
        except ExpectedVersionConflict:
            raise ProjectionStateError(
                "Increment 4 ACTIVE retry differs from immutable build intent"
            ) from None
        promotion = self._promotion_for_generation(request.generation_id)
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''from __future__ import annotations

from pathlib import Path
''',
    '''from __future__ import annotations

from dataclasses import replace
from pathlib import Path
''',
)

replace_once(
    "newsroom/tests/test_increment4e_neo4j_controller.py",
    '''        apply_before_retry = adapter.apply_count
        cleanup_before_retry = adapter.cleanup_count
        reconcile_before_retry = adapter.reconcile_count
        system.commands.execute(
''',
    '''        apply_before_retry = adapter.apply_count
        cleanup_before_retry = adapter.cleanup_count
        reconcile_before_retry = adapter.reconcile_count

        # Cleanup intent is part of the immutable creation-command identity.
        # A retry cannot attach to this ACTIVE generation while changing the
        # original request from purge=True to purge=False.
        with pytest.raises(
            ProjectionStateError,
            match="immutable build intent",
        ):
            system.increment4.build_and_promote(
                replace(
                    replacement_request,
                    purge_retired_generation=False,
                ),
                proof=extraction_proof(),
            )
        assert adapter.apply_count == apply_before_retry
        assert adapter.cleanup_count == cleanup_before_retry
        assert adapter.reconcile_count == reconcile_before_retry
        assert any(key[0] == str(GENERATION_1) for key in adapter.deliveries)
        assert {
            key: value
            for key, value in adapter.deliveries.items()
            if key[0] == str(GENERATION_2)
        } == serving_before_retry

        system.commands.execute(
''',
)
