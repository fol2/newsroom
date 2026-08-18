"""Prefunded Wallet for Increment 9Q-7: fixture ledger, no live provider balances.

Injected capacity, reservations and debits only. Refuses overdraft, replenishment
and transfer. AVAILABLE means sufficiency-before-spend, not mere wallet existence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.comparator import BudgetCaps, ComparatorContractError
from newsroom.increment9.controller import (
    ControllerError,
    ControllerLedgerEntry,
    ControllerStage,
    LedgerKind,
)

CAPACITY_GBP_MINOR_UNITS = 25_000
CURRENCY = "GBP_MINOR_UNITS"
SPEND_METERED = "INCREMENTAL_PAID_API"
SPEND_SUBSCRIPTION = "SUBSCRIPTION"
ADMITTED_SPEND_CLASSES = frozenset({SPEND_METERED, SPEND_SUBSCRIPTION})
FIXTURE_TIMESTAMP = "2026-08-18T00:00:00.000000Z"
FIXTURE_WALLET: dict[str, object] = {
    "budget_transfer_allowed": False,
    "capacity_gbp_minor_units": CAPACITY_GBP_MINOR_UNITS,
    "currency": CURRENCY,
}
_WALLET_FIELDS = frozenset(FIXTURE_WALLET)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")


class PrefundedWalletError(ValueError):
    """Wallet bind, reservation or debit failed closed."""


def budget_caps_digest() -> str:
    """Canonical digest of the frozen OD-011 BudgetCaps contract."""

    return BudgetCaps().canonical_digest


def _token(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise PrefundedWalletError(f"{field} token is malformed")
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > 256 or _TOKEN.fullmatch(value) is None:
        raise PrefundedWalletError(f"{field} token is malformed")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise PrefundedWalletError(f"{field} digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise PrefundedWalletError(f"{field} digest differs") from exc


def _amount(value: object, field: str) -> int:
    if type(value) is float:
        raise PrefundedWalletError("currency or units differ")
    if type(value) is not int:
        raise PrefundedWalletError(f"{field} token is malformed")
    if value <= 0:
        raise PrefundedWalletError(f"{field} token is malformed")
    return value


def _spend_class(value: object) -> str:
    token = _token(value, "spend_class")
    if token not in ADMITTED_SPEND_CLASSES:
        raise PrefundedWalletError("spend_class token is malformed")
    return token


def fixture_wallet(**changes: object) -> dict[str, object]:
    values = dict(FIXTURE_WALLET)
    values.update(changes)
    return values


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    reservation_id: str
    amount_gbp_minor_units: int
    spend_class: str
    budget_rules_digest: str

    def primitive(self) -> dict[str, object]:
        return {
            "amount_gbp_minor_units": self.amount_gbp_minor_units,
            "budget_rules_digest": self.budget_rules_digest,
            "reservation_id": self.reservation_id,
            "spend_class": self.spend_class,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))


@dataclass(frozen=True, slots=True)
class WalletDebit:
    reservation_digest: str
    amount_gbp_minor_units: int
    spend_class: str

    def primitive(self) -> dict[str, object]:
        return {
            "amount_gbp_minor_units": self.amount_gbp_minor_units,
            "reservation_digest": self.reservation_digest,
            "spend_class": self.spend_class,
        }

    @property
    def digest(self) -> str:
        return digest_bytes(canonical_json_bytes(self.primitive()))


@dataclass(frozen=True, slots=True)
class WalletUsage:
    kind: str
    digest: str
    amount_gbp_minor_units: int


@dataclass
class PrefundedWallet:
    """Injected fixture ledger. Opening balance equals OD-011 capacity."""

    capacity: int
    budget_caps_digest: str
    _reserved: dict[str, BudgetReservation] = field(default_factory=dict)
    _consumed: dict[str, int] = field(default_factory=dict)
    _ledger: list[WalletUsage] = field(default_factory=list)

    @property
    def available(self) -> int:
        return self.capacity - sum(item.amount_gbp_minor_units for item in self._reserved.values())

    @property
    def ledger(self) -> tuple[WalletUsage, ...]:
        return tuple(self._ledger)

    def _bind_digest(self, presented: object) -> str:
        digest = _digest(presented, "budget_rules_digest")
        if digest != self.budget_caps_digest:
            raise PrefundedWalletError("budget rules digest differs")
        return digest

    def reserve(
        self,
        *,
        reservation_id: object,
        amount_gbp_minor_units: object,
        spend_class: object,
        budget_rules_digest: object,
    ) -> BudgetReservation:
        token = _token(reservation_id, "reservation_id")
        if token in self._reserved:
            raise PrefundedWalletError("reservation_id token is malformed")
        amount = _amount(amount_gbp_minor_units, "amount_gbp_minor_units")
        cls = _spend_class(spend_class)
        digest = self._bind_digest(budget_rules_digest)
        if amount > self.available:
            raise PrefundedWalletError("reservation exceeds remaining balance")
        reservation = BudgetReservation(token, amount, cls, digest)
        self._reserved[token] = reservation
        self._consumed[token] = 0
        self._ledger.append(
            WalletUsage("RESERVATION", reservation.digest, amount)
        )
        return reservation

    def debit(
        self,
        *,
        reservation_id: object,
        amount_gbp_minor_units: object,
        spend_class: object,
        budget_rules_digest: object,
    ) -> WalletDebit:
        digest = self._bind_digest(budget_rules_digest)
        amount = _amount(amount_gbp_minor_units, "amount_gbp_minor_units")
        cls = _spend_class(spend_class)
        if cls == SPEND_SUBSCRIPTION:
            self._ledger.append(
                WalletUsage("SUBSCRIPTION", digest, amount)
            )
            raise PrefundedWalletError("subscription-class debit is refused")
        token = _token(reservation_id, "reservation_id")
        reservation = self._reserved.get(token)
        if reservation is None:
            raise PrefundedWalletError(
                "debit is not bound to a ledgered Budget Reservation"
            )
        remaining = reservation.amount_gbp_minor_units - self._consumed[token]
        if amount > remaining:
            raise PrefundedWalletError("debit exceeds its reservation")
        record = WalletDebit(reservation.digest, amount, cls)
        self._consumed[token] += amount
        self._ledger.append(WalletUsage("DEBIT", record.digest, amount))
        return record

    def replenish(self, amount_gbp_minor_units: object) -> None:
        raise PrefundedWalletError("replenishment is refused")

    def transfer(self, amount_gbp_minor_units: object, destination: object) -> None:
        raise PrefundedWalletError("budget transfer is refused")


def bind_wallet(fixture: Mapping[str, object]) -> PrefundedWallet:
    """Refuse a fixture that is not the OD-011 prefunded, non-transferable cap."""

    if not isinstance(fixture, Mapping) or not fixture:
        raise PrefundedWalletError("wallet is required")
    if set(fixture) != _WALLET_FIELDS:
        raise PrefundedWalletError("wallet is required")
    caps = BudgetCaps()
    currency = fixture["currency"]
    if type(currency) is not str or currency != CURRENCY:
        raise PrefundedWalletError("currency or units differ")
    capacity = fixture["capacity_gbp_minor_units"]
    if type(capacity) is float:
        raise PrefundedWalletError("currency or units differ")
    if type(capacity) is not int:
        raise PrefundedWalletError("wallet is required")
    if capacity != caps.gross_monetary_gbp_minor_units:
        raise PrefundedWalletError("wallet capacity differs from OD-011")
    if fixture["budget_transfer_allowed"] is not False:
        raise PrefundedWalletError("budget transfer is refused")
    if caps.budget_transfer_allowed is not False:
        raise PrefundedWalletError("budget transfer is refused")
    return PrefundedWallet(
        capacity=capacity, budget_caps_digest=caps.canonical_digest
    )


def bound_wallet(fixture: Mapping[str, object] | None = None) -> PrefundedWallet:
    return bind_wallet(fixture if fixture is not None else FIXTURE_WALLET)


def ledger_budget_reservation(reservation_digest: str) -> ControllerLedgerEntry:
    """Controller BUDGET_RESERVATION chain entry for a wallet reservation digest."""

    return ControllerLedgerEntry(
        ordinal=1,
        stage=ControllerStage.SOURCE,
        kind=LedgerKind.BUDGET_RESERVATION,
        payload_digest=reservation_digest,
        previous_entry_digest=None,
        persisted_at=FIXTURE_TIMESTAMP,
    )


def refuse_namesake_satisfaction(gates: tuple[str, ...] | list[str]) -> None:
    """Refuse RUNTIME_GATES list membership as this First I/O Gate."""

    if "PREFUNDED_WALLET_AVAILABLE" in gates:
        raise PrefundedWalletError(
            "RUNTIME_GATES membership cannot satisfy this First I/O Gate"
        )
    raise PrefundedWalletError(
        "PREFUNDED_WALLET_AVAILABLE is absent from RUNTIME_GATES"
    )


def bind_campaign_prefunded_wallet() -> str:
    """Campaign PREFUNDED_WALLET_AVAILABLE bind: the wallet, not a bare gate name.

    RUNTIME_GATES list membership cannot PASS.
    """

    try:
        caps = BudgetCaps()
    except ComparatorContractError as exc:
        raise PrefundedWalletError("wallet capacity differs from OD-011") from exc
    wallet = bound_wallet()
    if wallet.capacity != caps.gross_monetary_gbp_minor_units:
        raise PrefundedWalletError("wallet capacity differs from OD-011")
    if wallet.budget_caps_digest != caps.canonical_digest:
        raise PrefundedWalletError("budget rules digest differs")
    reservation = wallet.reserve(
        reservation_id="campaign-bind",
        amount_gbp_minor_units=1,
        spend_class=SPEND_METERED,
        budget_rules_digest=caps.canonical_digest,
    )
    try:
        entry = ledger_budget_reservation(reservation.digest)
    except ControllerError as exc:
        raise PrefundedWalletError(
            "debit is not bound to a ledgered Budget Reservation"
        ) from exc
    if entry.kind is not LedgerKind.BUDGET_RESERVATION:
        raise PrefundedWalletError(
            "debit is not bound to a ledgered Budget Reservation"
        )
    wallet.debit(
        reservation_id="campaign-bind",
        amount_gbp_minor_units=1,
        spend_class=SPEND_METERED,
        budget_rules_digest=caps.canonical_digest,
    )
    return caps.canonical_digest
