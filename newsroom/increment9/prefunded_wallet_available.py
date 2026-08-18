"""Increment 9Q-7 PREFUNDED_WALLET_AVAILABLE qualification evidence.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Qualification proves cap bind, non-replenishing prefund and
reservation-before-spend availability on the real contracts, fail-closed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment9.comparator import (
    BudgetCaps,
    ComparatorContractError,
    ResourceReservation,
)
from newsroom.increment9.controller import ControllerError
from newsroom.increment9.epoch import EvaluationEpoch, EpochAuthorityError
from newsroom.increment9.plan import INCREMENT_9_SHADOW_PLAN_DIGEST
from newsroom.increment9.prefunded_wallet import (
    CAPACITY_GBP_MINOR_UNITS,
    SPEND_METERED,
    SPEND_SUBSCRIPTION,
    PrefundedWalletError,
    bind_campaign_prefunded_wallet,
    bind_wallet,
    bound_wallet,
    budget_caps_digest,
    fixture_wallet,
    ledger_budget_reservation,
    refuse_namesake_satisfaction,
)

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "PREFUNDED_WALLET_AVAILABLE"
WALLET_NAME = "wallet.json"

REFUSAL_CLASSES = (
    "CAPACITY_MISMATCH",
    "CURRENCY_OR_UNITS_MISMATCH",
    "REPLENISHMENT_ATTEMPT",
    "TRANSFER_ATTEMPT",
    "OVERDRAFT_RESERVATION",
    "DEBIT_WITHOUT_RESERVATION",
    "DEBIT_EXCEEDING_RESERVATION",
    "SUBSCRIPTION_CLASS_DEBIT",
    "BUDGET_RULES_DIGEST_DRIFT",
    "MALFORMED_REQUEST",
    "ANTI_NAMESAKE",
)
PACKAGE_FIXTURES = (
    Path(__file__).parent / "fixtures" / "increment9q7_prefunded_wallet_available"
)
_MARKERS = {
    "CAPACITY_MISMATCH": b"capacity_mismatch",
    "CURRENCY_OR_UNITS_MISMATCH": b"currency_or_units_mismatch",
    "REPLENISHMENT_ATTEMPT": b"replenishment_attempt",
    "TRANSFER_ATTEMPT": b"transfer_attempt",
    "OVERDRAFT_RESERVATION": b"overdraft_reservation",
    "DEBIT_WITHOUT_RESERVATION": b"debit_without_reservation",
    "DEBIT_EXCEEDING_RESERVATION": b"debit_exceeding_reservation",
    "SUBSCRIPTION_CLASS_DEBIT": b"subscription_class_debit",
    "BUDGET_RULES_DIGEST_DRIFT": b"budget_rules_digest_drift",
    "MALFORMED_REQUEST": b"malformed_request",
    "ANTI_NAMESAKE": b"anti_namesake",
}
_DIGEST = "sha256:" + "0" * 64
_OPENED = "2026-08-16T00:00:00.000000Z"
_CLOSES = "2026-09-13T00:00:00.000000Z"

Probe = Callable[[str, Path], bool]


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


@dataclass(frozen=True, slots=True)
class RefusalDigest:
    refusal_class: str
    before_digest: str
    after_digest: str
    engaged: bool
    count: int


@dataclass(frozen=True, slots=True)
class QualificationEvidence:
    gate_id: str
    status: str
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
    budget_caps_digest: str
    reservation_digest: str
    evidence_digest: str


def _reject_forbidden(inventory: Path) -> None:
    lowered = str(inventory).lower()
    if "news_pool" in lowered:
        raise QualificationError("inventory must not alias news_pool")


def _refusal_surfaces(inventory: Path) -> tuple[tuple[str, Path], ...]:
    if not inventory.is_dir():
        raise QualificationError("inventory is required")
    missing = [rc for rc in REFUSAL_CLASSES if not (inventory / rc).is_file()]
    if missing:
        raise QualificationError(f"missing refusal class: {missing[0]}")
    extras = sorted(
        path.name
        for path in inventory.iterdir()
        if path.name not in REFUSAL_CLASSES and path.name != WALLET_NAME
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _load_wallet(inventory: Path) -> dict[str, object]:
    path = inventory / WALLET_NAME
    if not path.is_file():
        raise QualificationError("wallet is required")
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("wallet is required") from exc
    if type(raw) is not dict or not raw:
        raise QualificationError("wallet is required")
    try:
        bind_wallet(raw)
    except PrefundedWalletError as exc:
        raise QualificationError("wallet is required") from exc
    return raw


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except (
        PrefundedWalletError,
        ComparatorContractError,
        ControllerError,
        EpochAuthorityError,
    ):
        return True
    return False


def _reserve(
    wallet=None,
    *,
    reservation_id: str = "reservation-1",
    amount: int = 1,
    spend_class: str = SPEND_METERED,
    digest: str | None = None,
):
    active = wallet if wallet is not None else bound_wallet()
    return active.reserve(
        reservation_id=reservation_id,
        amount_gbp_minor_units=amount,
        spend_class=spend_class,
        budget_rules_digest=digest if digest is not None else budget_caps_digest(),
    )


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that a prefunded-wallet refusal class engages on the real contracts.

    Returns True if the refusal engaged (fail-closed). Returns False if it
    did not engage (unexpected success).
    """
    if refusal_class not in REFUSAL_CLASSES:
        raise QualificationError(f"unknown refusal class: {refusal_class}")
    if not path.is_file():
        raise QualificationError(f"missing refusal class: {refusal_class}")
    if _MARKERS[refusal_class] not in path.read_bytes():
        return False
    probes = {
        "CAPACITY_MISMATCH": _should_engage_capacity_mismatch,
        "CURRENCY_OR_UNITS_MISMATCH": _should_engage_currency_or_units_mismatch,
        "REPLENISHMENT_ATTEMPT": _should_engage_replenishment_attempt,
        "TRANSFER_ATTEMPT": _should_engage_transfer_attempt,
        "OVERDRAFT_RESERVATION": _should_engage_overdraft_reservation,
        "DEBIT_WITHOUT_RESERVATION": _should_engage_debit_without_reservation,
        "DEBIT_EXCEEDING_RESERVATION": _should_engage_debit_exceeding_reservation,
        "SUBSCRIPTION_CLASS_DEBIT": _should_engage_subscription_class_debit,
        "BUDGET_RULES_DIGEST_DRIFT": _should_engage_budget_rules_digest_drift,
        "MALFORMED_REQUEST": _should_engage_malformed_request,
        "ANTI_NAMESAKE": _should_engage_anti_namesake,
    }
    return bool(probes[refusal_class]())


def _should_engage_capacity_mismatch() -> bool:
    drifted = fixture_wallet(capacity_gbp_minor_units=24_999)
    return _refused(lambda: BudgetCaps(gross_monetary_gbp_minor_units=24_999)) and _refused(
        lambda: bind_wallet(drifted)
    )


def _should_engage_currency_or_units_mismatch() -> bool:
    usd = fixture_wallet(currency="USD")
    fractional = fixture_wallet(capacity_gbp_minor_units=25000.5)  # type: ignore[arg-type]
    wallet = bound_wallet()
    return all(
        (
            _refused(lambda: bind_wallet(usd)),
            _refused(lambda: bind_wallet(fractional)),
            _refused(lambda: _reserve(wallet, amount=1.5)),  # type: ignore[arg-type]
        )
    )


def _should_engage_replenishment_attempt() -> bool:
    return _refused(lambda: bound_wallet().replenish(1))


def _should_engage_transfer_attempt() -> bool:
    transferable = fixture_wallet(budget_transfer_allowed=True)
    return all(
        (
            _refused(lambda: BudgetCaps(budget_transfer_allowed=True)),
            _refused(lambda: bind_wallet(transferable)),
            _refused(lambda: bound_wallet().transfer(1, "other-wallet")),
        )
    )


def _should_engage_overdraft_reservation() -> bool:
    caps = BudgetCaps()
    over = ResourceReservation(
        gross_monetary_gbp_minor_units=caps.gross_monetary_gbp_minor_units + 1
    )
    over_cap = over.gross_monetary_gbp_minor_units > caps.gross_monetary_gbp_minor_units
    return over_cap and _refused(
        lambda: _reserve(amount=CAPACITY_GBP_MINOR_UNITS + 1)
    )


def _should_engage_debit_without_reservation() -> bool:
    wallet = bound_wallet()
    return _refused(
        lambda: wallet.debit(
            reservation_id="absent-reservation",
            amount_gbp_minor_units=1,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    )


def _should_engage_debit_exceeding_reservation() -> bool:
    wallet = bound_wallet()
    _reserve(wallet, amount=10)
    return _refused(
        lambda: wallet.debit(
            reservation_id="reservation-1",
            amount_gbp_minor_units=11,
            spend_class=SPEND_METERED,
            budget_rules_digest=budget_caps_digest(),
        )
    )


def _should_engage_subscription_class_debit() -> bool:
    wallet = bound_wallet()
    before = wallet.available
    refused = _refused(
        lambda: wallet.debit(
            reservation_id="reservation-1",
            amount_gbp_minor_units=1,
            spend_class=SPEND_SUBSCRIPTION,
            budget_rules_digest=budget_caps_digest(),
        )
    )
    ledgered = any(item.kind == "SUBSCRIPTION" for item in wallet.ledger)
    return refused and ledgered and wallet.available == before == CAPACITY_GBP_MINOR_UNITS


def _fixture_epoch(digest: str) -> EvaluationEpoch:
    return EvaluationEpoch(
        epoch_id="epoch-9q7-fixture",
        plan_digest=INCREMENT_9_SHADOW_PLAN_DIGEST,
        shadow_scope_digest=_DIGEST.replace("0", "6"),
        source_portfolio_digest=_DIGEST.replace("0", "2"),
        prospective_universe_digest=_DIGEST.replace("0", "1"),
        slice_rules_digest=_DIGEST.replace("0", "7"),
        thresholds_digest=_DIGEST.replace("0", "8"),
        comparator_rules_digest=_DIGEST.replace("0", "a"),
        reviewer_rules_digest=_DIGEST.replace("0", "9"),
        budget_rules_digest=digest,
        rights_rules_digest=_DIGEST.replace("0", "3"),
        opened_at=_OPENED,
        cutoff_at=_OPENED,
        closes_at=_CLOSES,
    )


def _should_engage_budget_rules_digest_drift() -> bool:
    expected = budget_caps_digest()
    drifted = "sha256:" + "0" * 64
    epoch = _fixture_epoch(expected)
    epoch_bound = epoch.budget_rules_digest == expected == BudgetCaps().canonical_digest
    return (
        drifted != expected
        and epoch_bound
        and _refused(lambda: _reserve(digest=drifted))
    )


def _should_engage_malformed_request() -> bool:
    wallet = bound_wallet()
    over_long = "H" * 257
    return all(
        (
            _refused(lambda: _reserve(wallet, amount=-1, reservation_id="neg")),
            _refused(lambda: _reserve(wallet, amount=0, reservation_id="zero")),
            _refused(
                lambda: _reserve(
                    wallet, spend_class="NOT_A_SPEND_CLASS", reservation_id="cls"
                )
            ),
            _refused(lambda: _reserve(wallet, reservation_id=over_long)),
        )
    )


def _should_engage_anti_namesake() -> bool:
    from scripts.increment9_shadow_campaign import RUNTIME_GATES

    namesake_closed = _refused(lambda: refuse_namesake_satisfaction(RUNTIME_GATES))
    listed = "PREFUNDED_WALLET_AVAILABLE" in RUNTIME_GATES
    authorised = not _refused(lambda: bind_campaign_prefunded_wallet())
    return namesake_closed and listed and authorised


def _refusal_payload(
    records: tuple[RefusalDigest, ...],
) -> list[dict[str, str | bool | int]]:
    return [
        {
            "after_digest": item.after_digest,
            "before_digest": item.before_digest,
            "count": item.count,
            "engaged": item.engaged,
            "refusal_class": item.refusal_class,
        }
        for item in records
    ]


def _demonstrate(wallet_fixture: Mapping[str, object]) -> tuple[str, str]:
    wallet = bind_wallet(wallet_fixture)
    if wallet.capacity != CAPACITY_GBP_MINOR_UNITS:
        raise QualificationError("wallet is required")
    digest = budget_caps_digest()
    if wallet.budget_caps_digest != digest:
        raise QualificationError("wallet is required")
    reservation = _reserve(wallet, reservation_id="evidence-reservation", amount=1)
    try:
        ledger_budget_reservation(reservation.digest)
    except (PrefundedWalletError, ControllerError) as exc:
        raise QualificationError("wallet is required") from exc
    wallet.debit(
        reservation_id="evidence-reservation",
        amount_gbp_minor_units=1,
        spend_class=SPEND_METERED,
        budget_rules_digest=digest,
    )
    return digest, reservation.digest


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    wallet: Mapping[str, object] | None = None,
) -> QualificationEvidence:
    """Assess that all eleven prefunded-wallet refusal classes engage deterministically.

    Fails closed if:
    - Inventory missing or inaccessible
    - Fixture wallet missing or invalid
    - Any refusal class surface missing or unexpected
    - Any digest changes without claimed engagement
    - Probe mutates any surface (fail-closed invariant)
    - Any refusal fails to engage
    """
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    if wallet is None:
        bound = _load_wallet(inventory)
    else:
        try:
            bind_wallet(wallet)
        except PrefundedWalletError as exc:
            raise QualificationError("wallet is required") from exc
        bound = dict(wallet)
    writer = default_probe if probe is None else probe
    bind_wallet(bound)
    before = {rc: _digest_file(path) for rc, path in surfaces}
    engaged_count = 0
    for rc, path in surfaces:
        if writer(rc, path):
            engaged_count += 1
    after = {rc: _digest_file(path) for rc, path in surfaces}
    if any(before[rc] != after[rc] for rc in REFUSAL_CLASSES):
        raise QualificationError("refusal surface digest mutated")
    if engaged_count != len(REFUSAL_CLASSES):
        raise QualificationError(
            f"not all refusals engaged: {engaged_count}/{len(REFUSAL_CLASSES)}"
        )
    records = tuple(
        RefusalDigest(rc, before[rc], after[rc], True, 1) for rc in REFUSAL_CLASSES
    )
    digest, reservation_digest = _demonstrate(bound)
    payload = {
        "budget_caps_digest": digest,
        "capacity_gbp_minor_units": CAPACITY_GBP_MINOR_UNITS,
        "gate_id": GATE_ID,
        "reservation_digest": reservation_digest,
        "refusals": _refusal_payload(records),
        "refusals_engaged": engaged_count,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
    }
    return QualificationEvidence(
        gate_id=GATE_ID,
        status="PASS",
        refusals_engaged=engaged_count,
        refusals=records,
        budget_caps_digest=digest,
        reservation_digest=reservation_digest,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""
    payload = {
        "budget_caps_digest": evidence.budget_caps_digest,
        "capacity_gbp_minor_units": CAPACITY_GBP_MINOR_UNITS,
        "evidence_digest": evidence.evidence_digest,
        "gate_id": evidence.gate_id,
        "reservation_digest": evidence.reservation_digest,
        "refusals": _refusal_payload(evidence.refusals),
        "refusals_engaged": evidence.refusals_engaged,
        "schema_version": SCHEMA_VERSION,
        "status": evidence.status,
    }
    return canonical_json_bytes(payload)
