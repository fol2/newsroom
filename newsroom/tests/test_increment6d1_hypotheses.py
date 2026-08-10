from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from newsroom.authority.canonical import canonical_json_bytes
from newsroom.increment6.hypotheses import (
    EVENT_HYPOTHESIS,
    EVENT_HYPOTHESIS_VERSION,
    EventHypothesis,
    EventHypothesisAuthority,
    EventHypothesisVersion,
    HypothesisContractError,
    HypothesisSourceBinding,
)
from newsroom.increment6.proposals import HypothesisRelationship

D = "sha256:" + "1" * 64


def _version() -> EventHypothesisVersion:
    proposal_id = str(uuid.UUID(int=1))
    hypothesis = EventHypothesis.allocate(proposal_id, "local-1")
    source = HypothesisSourceBinding(
        D, D, D, D, str(uuid.UUID(int=2)), D, str(uuid.UUID(int=3)), D
    )
    return EventHypothesisVersion(
        str(uuid.uuid5(uuid.UUID(hypothesis.hypothesis_id), "version:1")),
        hypothesis.hypothesis_id,
        1,
        None,
        None,
        "Unverified summary",
        HypothesisRelationship.NO_ADEQUATE_PRIOR_MATCH,
        None,
        None,
        None,
        proposal_id,
        D,
        D,
        "local-1",
        str(uuid.UUID(int=5)),
        str(uuid.UUID(int=6)),
        D,
        str(uuid.UUID(int=7)),
        D,
        (source,),
        D,
        str(uuid.UUID(int=8)),
        "2042-01-01T00:00:00.000000Z",
    )


def test_exact_contract_round_trip_and_non_effects() -> None:
    value = _version()
    assert EventHypothesisVersion.from_canonical_bytes(value.canonical_bytes) == value
    assert EVENT_HYPOTHESIS.endswith("event-hypothesis.v1")
    assert EVENT_HYPOTHESIS_VERSION.endswith("event-hypothesis-version.v1")
    assert value.creates_candidate is value.creates_relationship is False
    assert value.authorises_publication is value.authorises_external_effect is False


def test_version_identity_and_create_append_topology_fail_closed() -> None:
    value = _version()
    wrong_hypothesis_id = str(uuid.UUID(int=999))
    wrong_version_id = str(uuid.uuid5(uuid.UUID(wrong_hypothesis_id), "version:1"))
    with pytest.raises(HypothesisContractError, match="stable identity"):
        replace(
            value,
            hypothesis_id=wrong_hypothesis_id,
            version_id=wrong_version_id,
        )
    with pytest.raises(HypothesisContractError, match="create relationship"):
        replace(
            value,
            proposed_relationship=HypothesisRelationship.SAME_STATE,
            proposed_target_hypothesis_id=value.hypothesis_id,
            target_version_id=value.version_id,
            target_version_digest=value.canonical_digest,
        )
    with pytest.raises(HypothesisContractError, match="append relationship"):
        replace(
            value,
            ordinal=2,
            version_id=str(uuid.uuid5(uuid.UUID(value.hypothesis_id), "version:2")),
            previous_version_id=value.version_id,
            previous_version_digest=value.canonical_digest,
        )

    forged = value.canonical_value
    forged["hypothesis_id"] = wrong_hypothesis_id
    forged["version_id"] = wrong_version_id
    raw = canonical_json_bytes(
        {"schema_version": EVENT_HYPOTHESIS_VERSION, "version": forged}
    )
    with pytest.raises(HypothesisContractError, match="stable identity"):
        EventHypothesisVersion.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"hypothesis_id":true,"schema_version":"newsroom.increment6.event-hypothesis.v1"}',
        b'{"hypothesis_id":1.0,"schema_version":"newsroom.increment6.event-hypothesis.v1"}',
        b'{"schema_version":"x","schema_version":"x"}',
    ],
)
def test_contract_errors_are_total(raw: bytes) -> None:
    with pytest.raises(HypothesisContractError):
        EventHypothesis.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"true",
        b"1",
        b"1.0",
        b'{"x":9223372036854775808}',
        b'{"hypothesis_id":"\\ud800","schema_version":"newsroom.increment6.event-hypothesis.v1"}',
        b'{"hypothesis_id":"00000000-0000-0000-0000-000000000001","schema_version":"newsroom.increment6.event-hypothesis.v1","unknown":1}',
        b'{ "hypothesis_id":"00000000-0000-0000-0000-000000000001","schema_version":"newsroom.increment6.event-hypothesis.v1"}',
    ],
)
def test_parser_rejects_noncanonical_or_unsupported_json_as_contract_error(
    raw: bytes,
) -> None:
    with pytest.raises(HypothesisContractError):
        EventHypothesis.from_canonical_bytes(raw)


def test_exact_types_uninitialised_values_and_corrupted_nested_sources_are_total() -> (
    None
):
    class Raw(bytes):
        def __len__(self):
            raise RuntimeError("should not dispatch")

    class Sources(tuple):
        def __iter__(self):
            raise RuntimeError("should not dispatch")

    with pytest.raises(HypothesisContractError):
        EventHypothesis.from_canonical_bytes(Raw(b"{}"))
    with pytest.raises(HypothesisContractError):
        replace(_version(), source_bindings=Sources(_version().source_bindings))
    for value in (
        object.__new__(EventHypothesis),
        object.__new__(EventHypothesisVersion),
        object.__new__(HypothesisSourceBinding),
    ):
        with pytest.raises(HypothesisContractError):
            _ = (
                value.canonical_bytes
                if not isinstance(value, HypothesisSourceBinding)
                else value.canonical_value()
            )
    version = _version()
    corrupt = version.source_bindings[0]
    object.__setattr__(corrupt, "disposition_id", object())
    with pytest.raises(HypothesisContractError):
        _ = version.canonical_bytes


def test_public_facade_requires_exact_private_authority() -> None:
    with pytest.raises(HypothesisContractError):
        EventHypothesisAuthority(object())


def test_structural_depth_node_caps_and_constructed_self_cycles_are_total() -> None:
    deep = b'{"a":' * 25 + b"null" + b"}" * 25
    wide = (
        b'{"hypothesis_id":"00000000-0000-0000-0000-000000000001","schema_version":"newsroom.increment6.event-hypothesis.v1","x":['
        + b"null," * 32768
        + b"null]}"
    )
    for raw in (deep, wide):
        with pytest.raises(HypothesisContractError):
            EventHypothesis.from_canonical_bytes(raw)
    version = _version()
    cyclic = list(version.source_bindings)
    cyclic.append(cyclic)  # type: ignore[arg-type]
    object.__setattr__(version, "source_bindings", cyclic)
    with pytest.raises(HypothesisContractError):
        _ = version.canonical_bytes


def test_explosive_builtin_subclasses_are_rejected_without_dispatch() -> None:
    class ExplosiveStr(str):
        def encode(self, *_: object, **__: object) -> bytes:
            raise AssertionError("subclass dispatch")

    class ExplosiveInt(int):
        def __index__(self) -> int:
            raise AssertionError("subclass dispatch")

    class ExplosiveDict(dict):
        def __iter__(self):
            raise AssertionError("subclass dispatch")

    class ExplosiveList(list):
        def __iter__(self):
            raise AssertionError("subclass dispatch")

    with pytest.raises(HypothesisContractError):
        EventHypothesis(ExplosiveStr(str(uuid.UUID(int=1))))
    with pytest.raises(HypothesisContractError):
        replace(_version(), ordinal=ExplosiveInt(1))
    with pytest.raises(HypothesisContractError):
        HypothesisSourceBinding.from_value(ExplosiveDict())
    with pytest.raises(HypothesisContractError):
        replace(_version(), source_bindings=ExplosiveList())


def test_uninitialised_facade_normalises_ordinary_failures_and_preserves_base_exceptions() -> (
    None
):
    facade = object.__new__(EventHypothesisAuthority)
    operations = (
        lambda: facade.retain(b"", (), proof=object()),
        lambda: facade.current(str(uuid.UUID(int=1)), proof=object()),
        lambda: facade.load_version(str(uuid.UUID(int=1))),
        lambda: facade.load_hypothesis(str(uuid.UUID(int=1))),
        lambda: facade.versions(str(uuid.UUID(int=1))),
        facade.close,
    )
    for operation in operations:
        with pytest.raises(HypothesisContractError):
            operation()

    from newsroom.increment6 import hypotheses as module

    for exc in (
        RuntimeError("runtime"),
        KeyError("key"),
        IndexError("index"),
        AttributeError("attribute"),
    ):
        with pytest.raises(HypothesisContractError):
            module._normalise(lambda exc=exc: (_ for _ in ()).throw(exc), "normalised")
    for exc_type in (KeyboardInterrupt, SystemExit):
        with pytest.raises(exc_type):
            module._normalise(
                lambda exc_type=exc_type: (_ for _ in ()).throw(exc_type()), "propagate"
            )
