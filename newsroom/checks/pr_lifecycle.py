"""Deterministic pull-request lifecycle contracts and housekeeping plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import re
from typing import Iterable, Mapping


class PrLifecycleError(ValueError):
    """Pull-request lifecycle metadata or inventory is invalid."""


class LifecycleKind(StrEnum):
    CANONICAL = "canonical"
    SUPPORT = "support"
    PREFLIGHT = "preflight"


class CloseWhen(StrEnum):
    MERGED = "merged"
    CHECKPOINTED = "checkpointed"
    CANONICAL_MERGED = "canonical-merged"


class BranchRetention(StrEnum):
    KEEP = "keep"
    DELETE_AFTER_CHECKPOINT = "delete-after-checkpoint"


_METADATA_KEYS = (
    "Lifecycle",
    "Delivery-Atom",
    "Canonical-PR",
    "Checkpoint-Ref",
    "Close-When",
    "Branch-Retention",
)
_METADATA_LINE = re.compile(
    r"^(Lifecycle|Delivery-Atom|Canonical-PR|Checkpoint-Ref|Close-When|Branch-Retention):[ \t]*(.*)$"
)
_ATOM = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PR_REFERENCE = re.compile(r"^#([1-9][0-9]*)$")
_REF_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_MAX_DISPOSABLE_PER_CANONICAL = 2
_STALE_AFTER = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class PrLifecycle:
    kind: LifecycleKind
    delivery_atom: str
    canonical_pr: int | None
    checkpoint_ref: str | None
    close_when: CloseWhen
    branch_retention: BranchRetention

    @property
    def canonical_is_self(self) -> bool:
        return self.canonical_pr is None

    @property
    def is_disposable(self) -> bool:
        return self.kind in {LifecycleKind.SUPPORT, LifecycleKind.PREFLIGHT}


@dataclass(frozen=True, slots=True)
class OpenPullRequest:
    number: int
    body: str
    draft: bool
    head_ref: str
    created_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number <= 0:
            raise PrLifecycleError("pull-request number must be positive")
        if not isinstance(self.body, str):
            raise PrLifecycleError("pull-request body must be text")
        if not isinstance(self.draft, bool):
            raise PrLifecycleError("pull-request draft state must be boolean")
        _validate_ref(self.head_ref, field="head_ref")
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise PrLifecycleError("pull-request creation time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CloseAction:
    pr_number: int
    reason: str
    delete_branch: str | None = None


@dataclass(frozen=True, slots=True)
class HousekeepingPlan:
    close_actions: tuple[CloseAction, ...]
    warnings: tuple[str, ...]


def parse_pr_lifecycle(body: str) -> PrLifecycle:
    """Parse exactly one value for every lifecycle field from a PR body."""

    if not isinstance(body, str):
        raise PrLifecycleError("pull-request body must be text")
    values: dict[str, str] = {}
    duplicates: set[str] = set()
    for raw_line in body.splitlines():
        match = _METADATA_LINE.fullmatch(raw_line)
        if match is None:
            continue
        key, raw_value = match.groups()
        if key in values:
            duplicates.add(key)
        values[key] = raw_value.strip()
    if duplicates:
        raise PrLifecycleError(
            "duplicate lifecycle fields: " + ", ".join(sorted(duplicates))
        )
    missing = [key for key in _METADATA_KEYS if key not in values]
    if missing:
        raise PrLifecycleError(
            "missing lifecycle fields: " + ", ".join(missing)
        )
    empty = [key for key in _METADATA_KEYS if not values[key]]
    if empty:
        raise PrLifecycleError(
            "empty lifecycle fields: " + ", ".join(empty)
        )
    try:
        kind = LifecycleKind(values["Lifecycle"])
        close_when = CloseWhen(values["Close-When"])
        retention = BranchRetention(values["Branch-Retention"])
    except ValueError as exc:
        raise PrLifecycleError("unsupported lifecycle metadata value") from exc

    delivery_atom = values["Delivery-Atom"]
    if _ATOM.fullmatch(delivery_atom) is None:
        raise PrLifecycleError(
            "Delivery-Atom must be a bounded lowercase identifier"
        )

    canonical_text = values["Canonical-PR"]
    if canonical_text == "self":
        canonical_pr = None
    else:
        match = _PR_REFERENCE.fullmatch(canonical_text)
        if match is None:
            raise PrLifecycleError("Canonical-PR must be self or #<number>")
        canonical_pr = int(match.group(1))

    checkpoint_text = values["Checkpoint-Ref"]
    checkpoint_ref = None if checkpoint_text == "NONE" else checkpoint_text
    if checkpoint_ref is not None:
        _validate_ref(checkpoint_ref, field="Checkpoint-Ref")

    lifecycle = PrLifecycle(
        kind=kind,
        delivery_atom=delivery_atom,
        canonical_pr=canonical_pr,
        checkpoint_ref=checkpoint_ref,
        close_when=close_when,
        branch_retention=retention,
    )
    _validate_lifecycle_shape(lifecycle)
    return lifecycle


def validate_pull_request_lifecycle(
    lifecycle: PrLifecycle,
    *,
    pr_number: int,
    draft: bool,
    head_ref: str,
) -> None:
    """Validate metadata against the actual pull-request surface."""

    if not isinstance(lifecycle, PrLifecycle):
        raise PrLifecycleError("lifecycle must be typed")
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number <= 0:
        raise PrLifecycleError("pull-request number must be positive")
    if not isinstance(draft, bool):
        raise PrLifecycleError("pull-request draft state must be boolean")
    _validate_ref(head_ref, field="head_ref")

    if lifecycle.kind is LifecycleKind.CANONICAL:
        if lifecycle.canonical_pr is not None:
            raise PrLifecycleError("canonical PR must declare Canonical-PR: self")
        if lifecycle.close_when is not CloseWhen.MERGED:
            raise PrLifecycleError("canonical PR must close only when merged")
        if lifecycle.branch_retention is not BranchRetention.KEEP:
            raise PrLifecycleError("canonical branch retention must be keep")
        if head_ref.startswith(("support/", "preflight/")):
            raise PrLifecycleError("canonical PR cannot use a disposable branch prefix")
        return

    if lifecycle.canonical_pr is None:
        raise PrLifecycleError("disposable PR must reference a canonical PR")
    if lifecycle.canonical_pr == pr_number:
        raise PrLifecycleError("disposable PR cannot reference itself")
    if not draft:
        raise PrLifecycleError("support and preflight PRs must remain drafts")
    expected_prefix = (
        "support/"
        if lifecycle.kind is LifecycleKind.SUPPORT
        else "preflight/"
    )
    if not head_ref.startswith(expected_prefix):
        raise PrLifecycleError(
            f"{lifecycle.kind.value} PR branch must start with {expected_prefix}"
        )
    if lifecycle.close_when is CloseWhen.MERGED:
        raise PrLifecycleError("disposable PR cannot use Close-When: merged")
    if (
        lifecycle.close_when is CloseWhen.CHECKPOINTED
        and lifecycle.checkpoint_ref is None
    ):
        raise PrLifecycleError(
            "checkpointed disposable PR requires a checkpoint ref"
        )
    if (
        lifecycle.branch_retention is BranchRetention.DELETE_AFTER_CHECKPOINT
        and lifecycle.checkpoint_ref is None
    ):
        raise PrLifecycleError(
            "branch deletion requires a checkpoint ref"
        )


def validate_pull_request_event(event: Mapping[str, object]) -> PrLifecycle:
    """Validate a pull_request or pull_request_target event payload."""

    try:
        raw_pr = event["pull_request"]
        if not isinstance(raw_pr, Mapping):
            raise TypeError
        number = int(raw_pr["number"])
        draft = raw_pr["draft"]
        body = raw_pr.get("body") or ""
        raw_head = raw_pr["head"]
        if not isinstance(raw_head, Mapping):
            raise TypeError
        head_ref = raw_head["ref"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PrLifecycleError("GitHub pull-request event is malformed") from exc
    lifecycle = parse_pr_lifecycle(str(body))
    validate_pull_request_lifecycle(
        lifecycle,
        pr_number=number,
        draft=draft,  # type: ignore[arg-type]
        head_ref=head_ref,  # type: ignore[arg-type]
    )
    return lifecycle


def plan_housekeeping(
    open_pull_requests: Iterable[OpenPullRequest],
    *,
    merged_canonical_prs: frozenset[int] = frozenset(),
    existing_checkpoint_refs: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> HousekeepingPlan:
    """Build a deterministic, fail-closed plan for open PRs.

    Canonical PRs are never auto-closed. Disposable PRs are closeable only when
    their declared checkpoint or canonical-merge condition is independently true.
    """

    if not isinstance(merged_canonical_prs, frozenset) or any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in merged_canonical_prs
    ):
        raise PrLifecycleError("merged canonical PR inventory is malformed")
    if not isinstance(existing_checkpoint_refs, frozenset):
        raise PrLifecycleError("checkpoint ref inventory must be immutable")
    for ref in existing_checkpoint_refs:
        _validate_ref(ref, field="checkpoint ref")
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PrLifecycleError("housekeeping time must be timezone-aware")

    prs = tuple(sorted(open_pull_requests, key=lambda item: item.number))
    if len({item.number for item in prs}) != len(prs):
        raise PrLifecycleError("open pull-request inventory contains duplicates")

    parsed: dict[int, PrLifecycle] = {}
    for pr in prs:
        lifecycle = parse_pr_lifecycle(pr.body)
        validate_pull_request_lifecycle(
            lifecycle,
            pr_number=pr.number,
            draft=pr.draft,
            head_ref=pr.head_ref,
        )
        parsed[pr.number] = lifecycle

    canonical_by_atom: dict[str, OpenPullRequest] = {}
    for pr in prs:
        lifecycle = parsed[pr.number]
        if lifecycle.kind is not LifecycleKind.CANONICAL:
            continue
        previous = canonical_by_atom.get(lifecycle.delivery_atom)
        if previous is not None:
            raise PrLifecycleError(
                "multiple open canonical PRs for delivery atom "
                f"{lifecycle.delivery_atom}: #{previous.number}, #{pr.number}"
            )
        canonical_by_atom[lifecycle.delivery_atom] = pr

    disposable_counts: dict[int, int] = {}
    for pr in prs:
        lifecycle = parsed[pr.number]
        if not lifecycle.is_disposable:
            continue
        assert lifecycle.canonical_pr is not None
        disposable_counts[lifecycle.canonical_pr] = (
            disposable_counts.get(lifecycle.canonical_pr, 0) + 1
        )
        canonical = next(
            (item for item in prs if item.number == lifecycle.canonical_pr),
            None,
        )
        if canonical is not None:
            canonical_lifecycle = parsed[canonical.number]
            if canonical_lifecycle.kind is not LifecycleKind.CANONICAL:
                raise PrLifecycleError(
                    f"#{pr.number} references non-canonical open PR "
                    f"#{canonical.number}"
                )
            if canonical_lifecycle.delivery_atom != lifecycle.delivery_atom:
                raise PrLifecycleError(
                    f"#{pr.number} delivery atom differs from canonical "
                    f"#{canonical.number}"
                )
        elif lifecycle.canonical_pr not in merged_canonical_prs:
            raise PrLifecycleError(
                f"#{pr.number} references neither an open nor merged canonical PR"
            )
    excess = {
        number: count
        for number, count in disposable_counts.items()
        if count > _MAX_DISPOSABLE_PER_CANONICAL
    }
    if excess:
        detail = ", ".join(
            f"#{number} has {count}"
            for number, count in sorted(excess.items())
        )
        raise PrLifecycleError(
            "too many open disposable PRs per canonical PR: " + detail
        )

    actions: list[CloseAction] = []
    warnings: list[str] = []
    for pr in prs:
        lifecycle = parsed[pr.number]
        age = current.astimezone(timezone.utc) - pr.created_at.astimezone(
            timezone.utc
        )
        if age > _STALE_AFTER:
            warnings.append(
                f"#{pr.number} has remained open for {age.days} days"
            )
        if not lifecycle.is_disposable:
            continue
        assert lifecycle.canonical_pr is not None
        close_reason: str | None = None
        if lifecycle.close_when is CloseWhen.CHECKPOINTED:
            if (
                lifecycle.checkpoint_ref is not None
                and lifecycle.checkpoint_ref in existing_checkpoint_refs
            ):
                close_reason = (
                    "declared checkpoint exists: "
                    f"{lifecycle.checkpoint_ref}"
                )
        elif (
            lifecycle.close_when is CloseWhen.CANONICAL_MERGED
            and lifecycle.canonical_pr in merged_canonical_prs
        ):
            close_reason = (
                f"canonical PR #{lifecycle.canonical_pr} is merged"
            )
        if close_reason is None:
            continue

        delete_branch: str | None = None
        if lifecycle.branch_retention is BranchRetention.DELETE_AFTER_CHECKPOINT:
            if (
                lifecycle.checkpoint_ref is None
                or lifecycle.checkpoint_ref not in existing_checkpoint_refs
            ):
                raise PrLifecycleError(
                    f"#{pr.number} branch deletion lacks a verified checkpoint"
                )
            delete_branch = pr.head_ref
        actions.append(
            CloseAction(
                pr_number=pr.number,
                reason=close_reason,
                delete_branch=delete_branch,
            )
        )

    return HousekeepingPlan(
        close_actions=tuple(actions),
        warnings=tuple(sorted(warnings)),
    )


def _validate_lifecycle_shape(lifecycle: PrLifecycle) -> None:
    if lifecycle.kind is LifecycleKind.CANONICAL:
        if lifecycle.canonical_pr is not None:
            raise PrLifecycleError("canonical lifecycle must reference self")
        if lifecycle.close_when is not CloseWhen.MERGED:
            raise PrLifecycleError("canonical lifecycle must close when merged")
        if lifecycle.branch_retention is not BranchRetention.KEEP:
            raise PrLifecycleError("canonical lifecycle must retain its branch")
        return
    if lifecycle.canonical_pr is None:
        raise PrLifecycleError("disposable lifecycle requires canonical PR")
    if lifecycle.close_when is CloseWhen.MERGED:
        raise PrLifecycleError("disposable lifecycle cannot close when merged")
    if (
        lifecycle.close_when is CloseWhen.CHECKPOINTED
        and lifecycle.checkpoint_ref is None
    ):
        raise PrLifecycleError("checkpoint closure requires checkpoint ref")
    if (
        lifecycle.branch_retention is BranchRetention.DELETE_AFTER_CHECKPOINT
        and lifecycle.checkpoint_ref is None
    ):
        raise PrLifecycleError("branch deletion requires checkpoint ref")


def _validate_ref(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _REF_TEXT.fullmatch(value) is None
        or value.endswith(("/", "."))
        or value.startswith(("/", "."))
        or "//" in value
        or ".." in value
        or "@{" in value
        or value.endswith(".lock")
    ):
        raise PrLifecycleError(f"{field} is not a safe bounded Git ref")
    return value


__all__ = [
    "BranchRetention",
    "CloseAction",
    "CloseWhen",
    "HousekeepingPlan",
    "LifecycleKind",
    "OpenPullRequest",
    "PrLifecycle",
    "PrLifecycleError",
    "parse_pr_lifecycle",
    "plan_housekeeping",
    "validate_pull_request_event",
    "validate_pull_request_lifecycle",
]
