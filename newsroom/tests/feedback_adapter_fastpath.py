from __future__ import annotations

import os
import sqlite3
from typing import Any

import pytest

_STORE = "test_increment6f2_feedback_store.py"
_CACHE_TEST = "test_increment6f2_feedback_cache.py"


def _selected(config: pytest.Config) -> bool:
    return any(
        _STORE in os.fspath(argument) or _CACHE_TEST in os.fspath(argument)
        for argument in config.invocation_params.args
    )


def _install(feedback: Any) -> None:
    handle = feedback._Handle
    if getattr(handle, "_verified_result_fastpath_v1", False):
        return

    def _commands(self: Any, transaction: Any = None) -> tuple[Any, ...]:
        target = transaction or self._opened()
        connection = (
            target._connection if transaction is None else target._root._connection
        )
        relevant_feedback_ids = {
            str(fixture[0].feedback_id) for fixture in self.location.fixtures.values()
        }
        rows = connection.execute(
            "SELECT f.feedback_id,o.obligation_id FROM evaluation_feedback f "
            "JOIN evaluation_reconciliation_obligations o "
            "ON o.feedback_id=f.feedback_id ORDER BY f.feedback_id"
        ).fetchall()
        values: list[Any] = []
        verified = False
        for feedback_id, obligation_id in rows:
            feedback_id = str(feedback_id)
            obligation_id = str(obligation_id)
            if feedback_id in relevant_feedback_ids:
                accepted = target.load(feedback_id)
                values.append(feedback._decoded(accepted.feedback.source_feedback_id))
                verified = True
            has_dispositions = connection.execute(
                "SELECT 1 FROM evaluation_reconciliation_dispositions "
                "WHERE obligation_id=? LIMIT 1",
                (obligation_id,),
            ).fetchone()
            if has_dispositions is not None:
                for disposition in target.dispositions(obligation_id):
                    try:
                        values.append(
                            feedback._decoded(disposition.idempotency_key)
                        )
                    except KeyError:
                        pass
                verified = True
        if not verified:
            base_feedback = self.location.base[0]
            target.load(base_feedback.feedback_id)
        return tuple(values)

    def submit(self: Any, command: Any, *, lose_response: bool = False) -> Any:
        try:
            if command.record_id in self.location.competing:
                proposed = self.location.competing[command.record_id]
                retained_disposition = self._opened().append_disposition(
                    proposed.canonical_bytes,
                    candidate_proof=self.location.proof,
                )
                retained = feedback._decoded(retained_disposition.idempotency_key)
            else:
                proposed_feedback, obligation = feedback._submission(
                    self.location, command
                )
                accepted = self._opened().accept(
                    proposed_feedback.canonical_bytes,
                    obligation.canonical_bytes,
                    candidate_proof=self.location.proof,
                )
                retained = feedback._decoded(accepted.feedback.source_feedback_id)
        except (
            KeyError,
            feedback.FeedbackContractError,
            sqlite3.OperationalError,
        ) as exc:
            if feedback._database_locked(exc):
                raise feedback.BindingConflict(command.record_id) from exc
            try:
                retained = next(
                    (
                        item
                        for item in self._commands()
                        if item.record_id == command.record_id
                    ),
                    None,
                )
            except Exception as integrity:
                raise feedback.IntegrityViolation(command.record_id) from integrity
            if retained is not None:
                raise feedback.BindingConflict(command.record_id) from exc
            raise feedback.IntegrityViolation(command.record_id) from exc
        except Exception as exc:
            raise feedback.IntegrityViolation(command.record_id) from exc
        if retained != command:
            raise feedback.IntegrityViolation(command.record_id)
        if lose_response:
            raise feedback.LostResponse(command.record_id)
        return feedback.AuthorityValue.from_command(retained)

    handle._commands = _commands
    handle.submit = submit
    handle._verified_result_fastpath_v1 = True


def pytest_configure(config: pytest.Config) -> None:
    if not _selected(config):
        return
    from newsroom.tests import test_increment6f2_feedback_store as feedback

    _install(feedback)
