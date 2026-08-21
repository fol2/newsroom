"""Increment 9Q Rights Review qualification evidence.

Parameterised Rights Review validator for the ten OD-001 Rights Gates.
This module emits Qualification Evidence for RIGHTS_UK-01,
RIGHTS_UK-02, RIGHTS_UK-03, RIGHTS_UK-05, RIGHTS_UK-10, RIGHTS_HK-01,
RIGHTS_HK-02, RIGHTS_HK-04, RIGHTS_RAD-01 and RIGHTS_RAD-02.

CI fixture digests only. Does not mint First I/O Gate Records. Loading this
module performs no network I/O and no production writes.

Each emitted Rights Gate PASSes only through three sealed, independent AI
Rights Review Records for that gate's exact OD-001 source role and exact
bound endpoint. The validator is wired into proving.assess; a boolean, a
sealer listing, or a Gate Record namesake cannot PASS.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
    validate_sha256_digest,
)
from newsroom.increment9.provider_terms import PROVIDER_CLASSES

SCHEMA_VERSION = "newsroom.increment9.qualification-evidence.v1"
GATE_ID = "RIGHTS_UK-01"
UK_02_GATE_ID = "RIGHTS_UK-02"
UK_03_GATE_ID = "RIGHTS_UK-03"
UK_05_GATE_ID = "RIGHTS_UK-05"
UK_10_GATE_ID = "RIGHTS_UK-10"
HK_01_GATE_ID = "RIGHTS_HK-01"
HK_02_GATE_ID = "RIGHTS_HK-02"
HK_04_GATE_ID = "RIGHTS_HK-04"
RAD_01_GATE_ID = "RIGHTS_RAD-01"
RAD_02_GATE_ID = "RIGHTS_RAD-02"
INVENTORY_NAME = "inventory.json"
HMAC_KEY_NAME = "hmac.key"
FIXTURE_HMAC_KEY = b"newsroom.increment9.rights.fixture-hmac-key"
FIXTURE_NOW = "2026-08-18T12:00:00.000000Z"
FIXTURE_ISSUED_AT = "2026-08-18T00:00:00.000000Z"
FIXTURE_EXPIRES_AT = "2026-08-19T00:00:00.000000Z"
FIXTURE_TERMS_URL = "https://terms.govuk.fixture.invalid/uk-01"
FIXTURE_TERMS_BYTES = b"newsroom.increment9.rights.uk-01.fixture-terms\n"
FIXTURE_ACCESS_METHOD = "HTTPS_GET_PUBLIC_ATOM"
UK_02_ACCESS_METHOD = "HTTPS_GET_PUBLIC_CONTENT_API_JSON"
UK_03_ACCESS_METHOD = UK_02_ACCESS_METHOD
UK_02_TERMS_URL = "https://terms.govuk.fixture.invalid/uk-02"
UK_02_TERMS_BYTES = b"newsroom.increment9.rights.uk-02.fixture-terms\n"
UK_03_TERMS_URL = "https://terms.govuk.fixture.invalid/uk-03"
UK_03_TERMS_BYTES = b"newsroom.increment9.rights.uk-03.fixture-terms\n"
UK_05_ACCESS_METHOD = FIXTURE_ACCESS_METHOD
UK_05_TERMS_URL = "https://terms.govuk.fixture.invalid/uk-05"
UK_05_TERMS_BYTES = b"newsroom.increment9.rights.uk-05.fixture-terms\n"
UK_10_ACCESS_METHOD = "HTTPS_GET_PUBLIC_WARNINGS_RSS"
UK_10_TERMS_URL = "https://terms.metoffice.fixture.invalid/uk-10"
UK_10_TERMS_BYTES = b"newsroom.increment9.rights.uk-10.fixture-terms\n"
HK_01_ACCESS_METHOD = "HTTPS_GET_PUBLIC_TC_RSS_XML"
HK_01_TERMS_URL = "https://terms.newsgovhk.fixture.invalid/hk-01"
HK_01_TERMS_BYTES = b"newsroom.increment9.rights.hk-01.fixture-terms\n"
HK_02_ACCESS_METHOD = "HTTPS_GET_PUBLIC_HKO_WARNSUM_JSON"
HK_02_TERMS_URL = "https://terms.hko.fixture.invalid/hk-02"
HK_02_TERMS_BYTES = b"newsroom.increment9.rights.hk-02.fixture-terms\n"
HK_04_ACCESS_METHOD = HK_01_ACCESS_METHOD
HK_04_TERMS_URL = "https://terms.edb.fixture.invalid/hk-04"
HK_04_TERMS_BYTES = b"newsroom.increment9.rights.hk-04.fixture-terms\n"
RAD_01_ACCESS_METHOD = HK_01_ACCESS_METHOD
RAD_01_TERMS_URL = "https://terms.rthk.fixture.invalid/rad-01"
RAD_01_TERMS_BYTES = b"newsroom.increment9.rights.rad-01.fixture-terms\n"
RAD_02_ACCESS_METHOD = "HTTPS_GET_PUBLIC_BBC_RSS_XML"
RAD_02_TERMS_URL = "https://terms.bbc.fixture.invalid/rad-02"
RAD_02_TERMS_BYTES = b"newsroom.increment9.rights.rad-02.fixture-terms\n"
FIXTURE_DATA_CLASS = "PUBLIC_OFFICIAL_PUBLICATION_METADATA"
FIXTURE_DESTINATIONS = ("TEN_APPROVED_SOURCE_ENDPOINTS",)
# Evaluation-only Graphiti destinations; not live or production authority.
GRAPHITI_EVALUATION_DESTINATIONS = frozenset(
    {
        "EVALUATION_CURSOR_AGENT_CLI",
        "EVALUATION_GROK_BUILD_CLI",
        "EVALUATION_OPENROUTER_EMBEDDINGS",
    }
)
FIXTURE_RETENTION = "RAW_HTTP_MAX_7_DAYS"
FIXTURE_FAMILIES = (
    "ANTHROPIC_AGENT_SDK",
    "OPENAI_CODEX",
    "XAI_GROK_BUILD",
)
UK_01_ENDPOINT = (
    "https://www.gov.uk/search/all.atom?organisations%5B%5D=home-office"
    "&organisations%5B%5D=uk-visas-and-immigration&order=updated-newest"
)
UK_01_SOURCE_ROLE = "Home Office and UKVI authority anchor"
UK_02_ENDPOINT = (
    "https://www.gov.uk/api/content/british-national-overseas-bno-visa"
)
UK_02_SOURCE_ROLE = "BN(O) authority anchor"
UK_03_ENDPOINT = "https://www.gov.uk/api/content/guidance/immigration-rules"
UK_03_SOURCE_ROLE = "Immigration Rules authority anchor"
UK_05_ENDPOINT = (
    "https://www.gov.uk/search/all.atom?organisations%5B%5D=department-for-education"
    "&organisations%5B%5D=ofqual&order=updated-newest"
)
UK_05_SOURCE_ROLE = "DfE and Ofqual education anchor"
UK_10_ENDPOINT = (
    "https://weather.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK"
)
UK_10_NINE_P_ENDPOINT = (
    "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/UK"
)
UK_10_SOURCE_ROLE = "Met Office warning anchor"
HK_01_ENDPOINT = "https://www.news.gov.hk/tc/common/html/topstories.rss.xml"
HK_01_SOURCE_ROLE = "news.gov.hk official editorial radar"
HK_02_ENDPOINT = (
    "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc"
)
HK_02_SOURCE_ROLE = "HKO warning anchor"
HK_04_ENDPOINT = "https://www.edb.gov.hk/tc/whats_new_rss.xml"
HK_04_SOURCE_ROLE = "EDB education anchor"
RAD_01_ENDPOINT = "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
RAD_01_NINE_P_ENDPOINT = (
    "https://rthk9.rthk.hk/rthk/news/rss/c_expressnews_clocal.xml"
)
RAD_01_SOURCE_ROLE = "RTHK lead-only comparator"
RAD_02_ENDPOINT = "https://feeds.bbci.co.uk/news/uk/rss.xml"
RAD_02_SOURCE_ROLE = "BBC UK lead-only comparator"
_EMITTED_ONLY = (
    "this packet emits RIGHTS_UK-01, RIGHTS_UK-02, RIGHTS_UK-03, "
    "RIGHTS_UK-05, RIGHTS_UK-10, RIGHTS_HK-01, RIGHTS_HK-02, "
    "RIGHTS_HK-04, RIGHTS_RAD-01 and RIGHTS_RAD-02 only"
)

# Exact OD-001 endpoints. Tests assert equality with proving.SOURCE_URLS
# except RIGHTS_UK-10, which binds the weather host (#578), not the 9P www
# host, and RIGHTS_RAD-01, which binds the rthk.hk host (#582), not the 9P
# rthk9 host. These are two named host-alias exceptions, not one generic rule.
BINDINGS: dict[str, tuple[str, str, str]] = {
    HK_01_GATE_ID: (
        "HK-01",
        HK_01_SOURCE_ROLE,
        HK_01_ENDPOINT,
    ),
    HK_02_GATE_ID: (
        "HK-02",
        HK_02_SOURCE_ROLE,
        HK_02_ENDPOINT,
    ),
    HK_04_GATE_ID: (
        "HK-04",
        HK_04_SOURCE_ROLE,
        HK_04_ENDPOINT,
    ),
    RAD_01_GATE_ID: (
        "RAD-01",
        RAD_01_SOURCE_ROLE,
        RAD_01_ENDPOINT,
    ),
    RAD_02_GATE_ID: (
        "RAD-02",
        RAD_02_SOURCE_ROLE,
        RAD_02_ENDPOINT,
    ),
    "RIGHTS_UK-01": ("UK-01", UK_01_SOURCE_ROLE, UK_01_ENDPOINT),
    "RIGHTS_UK-02": ("UK-02", UK_02_SOURCE_ROLE, UK_02_ENDPOINT),
    UK_03_GATE_ID: ("UK-03", UK_03_SOURCE_ROLE, UK_03_ENDPOINT),
    UK_05_GATE_ID: ("UK-05", UK_05_SOURCE_ROLE, UK_05_ENDPOINT),
    UK_10_GATE_ID: ("UK-10", UK_10_SOURCE_ROLE, UK_10_ENDPOINT),
}

REFUSAL_CLASSES = (
    "NO_RECORDS",
    "FEWER_THAN_THREE",
    "DUPLICATE_FAMILY",
    "MALFORMED_RECORD",
    "INVALID_SEAL",
    "NON_PASS_VERDICT",
    "BINDING_MISMATCH",
    "TERMS_DIGEST_DRIFT",
    "EXPIRED_OR_FUTURE",
    "ANTI_NAMESAKE",
)
PROBE_COUNTS = {
    "NO_RECORDS": 3,
    "FEWER_THAN_THREE": 2,
    "DUPLICATE_FAMILY": 1,
    "MALFORMED_RECORD": 3,
    "INVALID_SEAL": 1,
    "NON_PASS_VERDICT": 2,
    "BINDING_MISMATCH": 3,
    "TERMS_DIGEST_DRIFT": 1,
    "EXPIRED_OR_FUTURE": 2,
    "ANTI_NAMESAKE": 3,
}
EMITTED_GATES = frozenset(
    {
        GATE_ID,
        UK_02_GATE_ID,
        UK_03_GATE_ID,
        UK_05_GATE_ID,
        UK_10_GATE_ID,
        HK_01_GATE_ID,
        HK_02_GATE_ID,
        HK_04_GATE_ID,
        RAD_01_GATE_ID,
        RAD_02_GATE_ID,
    }
)
PACKAGE_FIXTURES = Path(__file__).parent / "fixtures" / "increment9q11_rights_uk_01"
PACKAGE_FIXTURES_UK_02 = (
    Path(__file__).parent / "fixtures" / "increment9q12_rights_uk_02"
)
PACKAGE_FIXTURES_UK_03 = (
    Path(__file__).parent / "fixtures" / "increment9q13_rights_uk_03"
)
PACKAGE_FIXTURES_UK_05 = (
    Path(__file__).parent / "fixtures" / "increment9q14_rights_uk_05"
)
PACKAGE_FIXTURES_UK_10 = (
    Path(__file__).parent / "fixtures" / "increment9q15_rights_uk_10"
)
PACKAGE_FIXTURES_HK_01 = (
    Path(__file__).parent / "fixtures" / "increment9q16_rights_hk_01"
)
PACKAGE_FIXTURES_HK_02 = (
    Path(__file__).parent / "fixtures" / "increment9q17_rights_hk_02"
)
PACKAGE_FIXTURES_HK_04 = (
    Path(__file__).parent / "fixtures" / "increment9q18_rights_hk_04"
)
PACKAGE_FIXTURES_RAD_01 = (
    Path(__file__).parent / "fixtures" / "increment9q19_rights_rad_01"
)
PACKAGE_FIXTURES_RAD_02 = (
    Path(__file__).parent / "fixtures" / "increment9q20_rights_rad_02"
)
PACKAGE_FIXTURES_BY_GATE = {
    GATE_ID: PACKAGE_FIXTURES,
    UK_02_GATE_ID: PACKAGE_FIXTURES_UK_02,
    UK_03_GATE_ID: PACKAGE_FIXTURES_UK_03,
    UK_05_GATE_ID: PACKAGE_FIXTURES_UK_05,
    UK_10_GATE_ID: PACKAGE_FIXTURES_UK_10,
    HK_01_GATE_ID: PACKAGE_FIXTURES_HK_01,
    HK_02_GATE_ID: PACKAGE_FIXTURES_HK_02,
    HK_04_GATE_ID: PACKAGE_FIXTURES_HK_04,
    RAD_01_GATE_ID: PACKAGE_FIXTURES_RAD_01,
    RAD_02_GATE_ID: PACKAGE_FIXTURES_RAD_02,
}
PROBE_COUNTS_BY_GATE = {
    GATE_ID: PROBE_COUNTS,
    UK_02_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
    UK_03_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
    UK_05_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
    UK_10_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 5},
    HK_01_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
    HK_02_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
    HK_04_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
    RAD_01_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 5},
    RAD_02_GATE_ID: {**PROBE_COUNTS, "BINDING_MISMATCH": 4},
}
_FIXTURE_ACCESS = {
    GATE_ID: FIXTURE_ACCESS_METHOD,
    UK_02_GATE_ID: UK_02_ACCESS_METHOD,
    UK_03_GATE_ID: UK_03_ACCESS_METHOD,
    UK_05_GATE_ID: UK_05_ACCESS_METHOD,
    UK_10_GATE_ID: UK_10_ACCESS_METHOD,
    HK_01_GATE_ID: HK_01_ACCESS_METHOD,
    HK_02_GATE_ID: HK_02_ACCESS_METHOD,
    HK_04_GATE_ID: HK_04_ACCESS_METHOD,
    RAD_01_GATE_ID: RAD_01_ACCESS_METHOD,
    RAD_02_GATE_ID: RAD_02_ACCESS_METHOD,
}
_FIXTURE_TERMS = {
    GATE_ID: (FIXTURE_TERMS_URL, FIXTURE_TERMS_BYTES),
    UK_02_GATE_ID: (UK_02_TERMS_URL, UK_02_TERMS_BYTES),
    UK_03_GATE_ID: (UK_03_TERMS_URL, UK_03_TERMS_BYTES),
    UK_05_GATE_ID: (UK_05_TERMS_URL, UK_05_TERMS_BYTES),
    UK_10_GATE_ID: (UK_10_TERMS_URL, UK_10_TERMS_BYTES),
    HK_01_GATE_ID: (HK_01_TERMS_URL, HK_01_TERMS_BYTES),
    HK_02_GATE_ID: (HK_02_TERMS_URL, HK_02_TERMS_BYTES),
    HK_04_GATE_ID: (HK_04_TERMS_URL, HK_04_TERMS_BYTES),
    RAD_01_GATE_ID: (RAD_01_TERMS_URL, RAD_01_TERMS_BYTES),
    RAD_02_GATE_ID: (RAD_02_TERMS_URL, RAD_02_TERMS_BYTES),
}
_FIXTURE_PACKET = {
    GATE_ID: "9q11",
    UK_02_GATE_ID: "9q12",
    UK_03_GATE_ID: "9q13",
    UK_05_GATE_ID: "9q14",
    UK_10_GATE_ID: "9q15",
    HK_01_GATE_ID: "9q16",
    HK_02_GATE_ID: "9q17",
    HK_04_GATE_ID: "9q18",
    RAD_01_GATE_ID: "9q19",
    RAD_02_GATE_ID: "9q20",
}
_PROVING_INVENTORY_KW = {
    GATE_ID: "rights",
    UK_02_GATE_ID: "rights_uk_02",
    UK_03_GATE_ID: "rights_uk_03",
    UK_05_GATE_ID: "rights_uk_05",
    UK_10_GATE_ID: "rights_uk_10",
    HK_01_GATE_ID: "rights_hk_01",
    HK_02_GATE_ID: "rights_hk_02",
    HK_04_GATE_ID: "rights_hk_04",
    RAD_01_GATE_ID: "rights_rad_01",
    RAD_02_GATE_ID: "rights_rad_02",
}
_CROSS_OTHER = {
    GATE_ID: UK_02_GATE_ID,
    UK_02_GATE_ID: GATE_ID,
    UK_03_GATE_ID: UK_02_GATE_ID,
    UK_05_GATE_ID: GATE_ID,
    UK_10_GATE_ID: GATE_ID,
    HK_01_GATE_ID: UK_10_GATE_ID,
    HK_02_GATE_ID: UK_02_GATE_ID,
    HK_04_GATE_ID: HK_01_GATE_ID,
    RAD_01_GATE_ID: HK_01_GATE_ID,
    RAD_02_GATE_ID: RAD_01_GATE_ID,
}
_MARKERS = {
    "NO_RECORDS": b"no_records",
    "FEWER_THAN_THREE": b"fewer_than_three",
    "DUPLICATE_FAMILY": b"duplicate_family",
    "MALFORMED_RECORD": b"malformed_record",
    "INVALID_SEAL": b"invalid_seal",
    "NON_PASS_VERDICT": b"non_pass_verdict",
    "BINDING_MISMATCH": b"binding_mismatch",
    "TERMS_DIGEST_DRIFT": b"terms_digest_drift",
    "EXPIRED_OR_FUTURE": b"expired_or_future",
    "ANTI_NAMESAKE": b"anti_namesake",
}
_INVENTORY_FIELDS = frozenset({"bound_terms", "now", "reviews"})
_BOUND_FIELDS = frozenset({"terms_digest", "terms_url"})
_RECORD_FIELDS = frozenset(
    {
        "access_method",
        "data_class",
        "destinations",
        "endpoint",
        "expires_at",
        "gate_id",
        "issued_at",
        "retention",
        "reviewer_family",
        "reviewer_id",
        "seal",
        "source_role",
        "terms_digest",
        "terms_url",
        "verdict",
    }
)
_TIMESTAMP = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z\Z"
)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,255}\Z")
_ALLOWED_SURFACES = frozenset({*REFUSAL_CLASSES, INVENTORY_NAME, HMAC_KEY_NAME})

Probe = Callable[[str, Path], bool]


class RightsError(ValueError):
    """Rights Review bind, seal or independence failed closed."""


class QualificationError(ValueError):
    """Qualification inventory, probe or digest check failed closed."""


@dataclass(frozen=True, slots=True)
class RightsVerdict:
    status: str
    reason: str
    gate_id: str | None = None
    endpoint: str | None = None
    source_role: str | None = None
    families: tuple[str, ...] = ()
    reviewer_ids: tuple[str, ...] = ()
    destinations: tuple[str, ...] = ()
    expires_at: str | None = None
    terms_url: str | None = None
    terms_digest: str | None = None


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
    endpoint: str
    source_role: str
    families: tuple[str, ...]
    reviewer_ids: tuple[str, ...]
    refusals_engaged: int
    refusals: tuple[RefusalDigest, ...]
    evidence_digest: str


def _fail(reason: str) -> RightsVerdict:
    return RightsVerdict(status="FAIL", reason=reason)


def _token(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise RightsError("record is malformed")
    encoded = value.encode("utf-8", errors="strict")
    if len(encoded) > 256 or _TOKEN.fullmatch(value) is None:
        raise RightsError("record is malformed")
    return value


def _url(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise RightsError("record is malformed")
    if len(value.encode("utf-8", errors="strict")) > 1024:
        raise RightsError("record is malformed")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str:
        raise RightsError("terms digest differs")
    try:
        return validate_sha256_digest(value, field=field)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise RightsError("terms digest differs") from exc


def _timestamp(value: object, field: str) -> str:
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise RightsError(f"{field} token is malformed")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise RightsError(f"{field} token is malformed") from exc
    return value


def _instant(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _destinations(value: object) -> tuple[str, ...]:
    if type(value) not in (tuple, list) or not value:
        raise RightsError("record is malformed")
    tokens = tuple(_token(item, "destination") for item in value)
    if tokens != tuple(sorted(set(tokens))):
        raise RightsError("record is malformed")
    return tokens


def _seal(unsigned: Mapping[str, object]) -> str:
    mac = hmac.new(
        FIXTURE_HMAC_KEY, canonical_json_bytes(dict(unsigned)), hashlib.sha256
    )
    return f"hmac-sha256:{mac.hexdigest()}"


def _verify_seal(record: Mapping[str, object]) -> None:
    presented = record.get("seal")
    if type(presented) is not str or not presented.startswith("hmac-sha256:"):
        raise RightsError("seal is invalid")
    unsigned = {key: record[key] for key in record if key != "seal"}
    expected = _seal(unsigned)
    if not hmac.compare_digest(expected, presented):
        raise RightsError("seal is invalid")


def _window(issued_at: str, expires_at: str, now: str) -> None:
    if _instant(issued_at) > _instant(now) or _instant(expires_at) <= _instant(now):
        raise RightsError("record is expired or future-dated")


def terms_digest_for(terms_url: str = FIXTURE_TERMS_URL, *, gate: str = GATE_ID) -> str:
    _, payload = _FIXTURE_TERMS[gate]
    return digest_bytes(payload + terms_url.encode("utf-8"))


def bound_terms_identity(*, gate: str = GATE_ID) -> dict[str, str]:
    url, payload = _FIXTURE_TERMS[gate]
    return {
        "terms_digest": digest_bytes(payload + url.encode("utf-8")),
        "terms_url": url,
    }


def fixtures_for(gate: str) -> Path:
    try:
        return PACKAGE_FIXTURES_BY_GATE[gate]
    except KeyError as exc:
        raise QualificationError(_EMITTED_ONLY) from exc


def fixture_review(
    family: str,
    *,
    reviewer_id: str | None = None,
    gate: str = GATE_ID,
    **changes: object,
) -> dict[str, object]:
    identity = bound_terms_identity(gate=gate)
    suffix = family.lower().replace("_", "-")
    unsigned: dict[str, object] = {
        "access_method": _FIXTURE_ACCESS[gate],
        "data_class": FIXTURE_DATA_CLASS,
        "destinations": list(FIXTURE_DESTINATIONS),
        "endpoint": BINDINGS[gate][2],
        "expires_at": FIXTURE_EXPIRES_AT,
        "gate_id": gate,
        "issued_at": FIXTURE_ISSUED_AT,
        "retention": FIXTURE_RETENTION,
        "reviewer_family": family,
        "reviewer_id": reviewer_id or f"reviewer-{suffix}-{_FIXTURE_PACKET[gate]}",
        "source_role": BINDINGS[gate][1],
        "terms_digest": identity["terms_digest"],
        "terms_url": identity["terms_url"],
        "verdict": "PASS",
    }
    for key, value in changes.items():
        if key != "seal":
            unsigned[key] = value
    record = dict(unsigned)
    record["seal"] = changes["seal"] if "seal" in changes else _seal(unsigned)
    return record


def evaluation_rights_destinations() -> tuple[str, ...]:
    """Return source-endpoint plus explicit EVALUATION Graphiti destinations."""

    return tuple(sorted({*FIXTURE_DESTINATIONS, *GRAPHITI_EVALUATION_DESTINATIONS}))


def fixture_inventory(*, gate: str = GATE_ID) -> dict[str, object]:
    return {
        "bound_terms": bound_terms_identity(gate=gate),
        "now": FIXTURE_NOW,
        "reviews": [fixture_review(family, gate=gate) for family in FIXTURE_FAMILIES],
    }


def evaluation_fixture_inventory(*, gate: str = GATE_ID) -> dict[str, object]:
    destinations = list(evaluation_rights_destinations())
    return {
        "bound_terms": bound_terms_identity(gate=gate),
        "now": FIXTURE_NOW,
        "reviews": [
            fixture_review(family, gate=gate, destinations=destinations)
            for family in FIXTURE_FAMILIES
        ],
    }


def bind_inventory(raw: object) -> dict[str, object]:
    """Refuse an envelope that is not a valid fixture inventory."""

    if type(raw) is not dict or set(raw) != _INVENTORY_FIELDS:
        raise RightsError("inventory is required")
    _timestamp(raw["now"], "now")
    bound = raw["bound_terms"]
    if type(bound) is not dict or set(bound) != _BOUND_FIELDS:
        raise RightsError("inventory is required")
    identity = {
        "terms_digest": _digest(bound["terms_digest"], "terms_digest"),
        "terms_url": _url(bound["terms_url"]),
    }
    reviews = raw["reviews"]
    if type(reviews) not in (tuple, list):
        raise RightsError("inventory is required")
    return {
        "bound_terms": identity,
        "now": raw["now"],
        "reviews": [dict(item) if type(item) is dict else item for item in reviews],
    }


def _parse_review(
    value: object,
    *,
    gate_id: str,
    now: str,
    bound_terms: Mapping[str, str],
) -> dict[str, object]:
    if type(value) is not dict or set(value) != _RECORD_FIELDS:
        raise RightsError("record is malformed")
    presented_gate = _token(value["gate_id"], "gate_id")
    source_role = _url(value["source_role"])
    endpoint = _url(value["endpoint"])
    expected = BINDINGS[gate_id]
    if (
        presented_gate != gate_id
        or source_role != expected[1]
        or endpoint != expected[2]
    ):
        raise RightsError("binding mismatch")
    access_method = _token(value["access_method"], "access_method")
    data_class = _token(value["data_class"], "data_class")
    destinations = _destinations(value["destinations"])
    retention = _token(value["retention"], "retention")
    reviewer_family = _token(value["reviewer_family"], "reviewer_family")
    if reviewer_family not in PROVIDER_CLASSES:
        raise RightsError("record is malformed")
    reviewer_id = _token(value["reviewer_id"], "reviewer_id")
    terms_url = _url(value["terms_url"])
    terms_digest = _digest(value["terms_digest"], "terms_digest")
    if (
        terms_digest != bound_terms["terms_digest"]
        or terms_url != bound_terms["terms_url"]
    ):
        raise RightsError("terms digest differs")
    issued_at = _timestamp(value["issued_at"], "issued_at")
    expires_at = _timestamp(value["expires_at"], "expires_at")
    verdict = value["verdict"]
    if type(verdict) is not str:
        raise RightsError("record is malformed")
    _verify_seal(value)
    _window(issued_at, expires_at, now)
    if verdict != "PASS":
        raise RightsError("verdict is not PASS")
    return {
        "access_method": access_method,
        "data_class": data_class,
        "destinations": destinations,
        "endpoint": endpoint,
        "expires_at": expires_at,
        "gate_id": presented_gate,
        "issued_at": issued_at,
        "retention": retention,
        "reviewer_family": reviewer_family,
        "reviewer_id": reviewer_id,
        "source_role": source_role,
        "terms_digest": terms_digest,
        "terms_url": terms_url,
        "verdict": verdict,
    }


def assess_rights(
    gate_id: object,
    *,
    inventory: object = None,
    now: str | None = None,
) -> RightsVerdict:
    """Fail-closed Rights Review verdict. No wall-clock read. No network."""

    if type(inventory) is bool:
        return _fail("boolean cannot satisfy this Rights Gate")
    if inventory is None:
        return _fail("inventory is required")
    if type(gate_id) is not str or gate_id not in BINDINGS:
        return _fail("binding mismatch")
    try:
        bound = bind_inventory(inventory)
        instant = _timestamp(now, "now") if now is not None else bound["now"]
    except RightsError:
        return _fail("inventory is required")
    reviews = bound["reviews"]
    if not reviews:
        return _fail("no records presented")
    parsed: list[dict[str, object]] = []
    for item in reviews:
        try:
            parsed.append(
                _parse_review(
                    item,
                    gate_id=gate_id,
                    now=instant,
                    bound_terms=bound["bound_terms"],
                )
            )
        except RightsError as exc:
            return _fail(str(exc))
    if len(parsed) < 3:
        return _fail("fewer than three reviews")
    if len(parsed) != 3:
        return _fail("record is malformed")
    families = tuple(item["reviewer_family"] for item in parsed)
    if len(set(families)) != 3:
        return _fail("duplicate reviewer family")
    ordered = tuple(sorted(parsed, key=lambda item: str(item["reviewer_family"])))
    destination_sets = {tuple(item["destinations"]) for item in ordered}
    if len(destination_sets) != 1:
        return _fail("record is malformed")
    return RightsVerdict(
        status="PASS",
        reason="authorised",
        gate_id=gate_id,
        endpoint=str(ordered[0]["endpoint"]),
        source_role=str(ordered[0]["source_role"]),
        families=tuple(str(item["reviewer_family"]) for item in ordered),
        reviewer_ids=tuple(str(item["reviewer_id"]) for item in ordered),
        destinations=next(iter(destination_sets)),
        expires_at=min(str(item["expires_at"]) for item in ordered),
        terms_url=str(ordered[0]["terms_url"]),
        terms_digest=str(ordered[0]["terms_digest"]),
    )


def refuse_namesake_satisfaction(
    gates: tuple[str, ...] | list[str], *, gate: str = GATE_ID
) -> None:
    """Refuse required_gate_ids listing as this Rights Gate."""

    if gate in gates:
        raise RightsError(
            "required_gate_ids listing cannot satisfy this Rights Gate"
        )
    raise RightsError(f"{gate} is absent from required_gate_ids")


def refuse_boolean(value: bool) -> None:
    """Refuse a boolean as this Rights Gate."""

    raise RightsError("boolean cannot satisfy this Rights Gate")


def refuse_gate_record_namesake(record: Mapping[str, object]) -> None:
    """Refuse a Gate Record subject_digest or reviewer_families as this gate."""

    raise RightsError(
        "Gate Record subject_digest or reviewer_families cannot satisfy this Rights Gate"
    )


def _reject_forbidden(inventory: Path) -> None:
    if "news_pool" in str(inventory).lower():
        raise QualificationError("inventory must not alias news_pool")


def _refusal_surfaces(inventory: Path) -> tuple[tuple[str, Path], ...]:
    if not inventory.is_dir():
        raise QualificationError("inventory is required")
    missing = [rc for rc in REFUSAL_CLASSES if not (inventory / rc).is_file()]
    if missing:
        raise QualificationError(f"missing refusal class: {missing[0]}")
    extras = sorted(
        path.name for path in inventory.iterdir() if path.name not in _ALLOWED_SURFACES
    )
    if extras:
        raise QualificationError(f"unexpected refusal class: {extras[0]}")
    return tuple((rc, inventory / rc) for rc in REFUSAL_CLASSES)


def _load_inventory(inventory: Path) -> dict[str, object]:
    path = inventory / INVENTORY_NAME
    if not path.is_file():
        raise QualificationError("inventory is required")
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("inventory is required") from exc
    try:
        bind_inventory(raw)
    except RightsError as exc:
        raise QualificationError("inventory is required") from exc
    return raw


def _require_hmac_key(inventory: Path) -> None:
    path = inventory / HMAC_KEY_NAME
    if not path.is_file() or path.read_bytes() != FIXTURE_HMAC_KEY:
        raise QualificationError("inventory is required")


def _digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def _refused(action: Callable[[], object]) -> bool:
    try:
        action()
    except RightsError:
        return True
    return False


def _verdict_fail(
    inventory: object,
    *,
    now: str | None = FIXTURE_NOW,
    gate_id: str = GATE_ID,
) -> bool:
    return assess_rights(gate_id, inventory=inventory, now=now).status != "PASS"


def default_probe(refusal_class: str, path: Path) -> bool:
    """Verify that a rights-review refusal class engages on the real contracts."""

    return probe_for(GATE_ID)(refusal_class, path)


def probe_for(gate: str) -> Probe:
    """Return the refusal-class probe bound to one emitted Rights Gate."""

    def writer(refusal_class: str, path: Path) -> bool:
        if refusal_class not in REFUSAL_CLASSES:
            raise QualificationError(f"unknown refusal class: {refusal_class}")
        if not path.is_file():
            raise QualificationError(f"missing refusal class: {refusal_class}")
        if _MARKERS[refusal_class] not in path.read_bytes():
            return False
        probes = {
            "NO_RECORDS": _should_engage_no_records,
            "FEWER_THAN_THREE": _should_engage_fewer_than_three,
            "DUPLICATE_FAMILY": _should_engage_duplicate_family,
            "MALFORMED_RECORD": _should_engage_malformed_record,
            "INVALID_SEAL": _should_engage_invalid_seal,
            "NON_PASS_VERDICT": _should_engage_non_pass_verdict,
            "BINDING_MISMATCH": _should_engage_binding_mismatch,
            "TERMS_DIGEST_DRIFT": _should_engage_terms_digest_drift,
            "EXPIRED_OR_FUTURE": _should_engage_expired_or_future,
            "ANTI_NAMESAKE": _should_engage_anti_namesake,
        }
        return bool(probes[refusal_class](gate))

    return writer


def _with_reviews(reviews: list[object], *, gate: str = GATE_ID) -> dict[str, object]:
    inventory = fixture_inventory(gate=gate)
    inventory["reviews"] = reviews
    return inventory


def _should_engage_no_records(gate: str) -> bool:
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    empty = _with_reviews([], gate=gate)
    gates = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    proving = next(g for g in gates if g.gate_id == gate)
    return all(
        (
            _verdict_fail(None, gate_id=gate),
            _verdict_fail(empty, gate_id=gate),
            proving.status is GateStatus.FAIL,
        )
    )


def _should_engage_fewer_than_three(gate: str) -> bool:
    one = _with_reviews([fixture_review(FIXTURE_FAMILIES[0], gate=gate)], gate=gate)
    two = _with_reviews(
        [
            fixture_review(FIXTURE_FAMILIES[0], gate=gate),
            fixture_review(FIXTURE_FAMILIES[1], gate=gate),
        ],
        gate=gate,
    )
    return _verdict_fail(one, gate_id=gate) and _verdict_fail(two, gate_id=gate)


def _should_engage_duplicate_family(gate: str) -> bool:
    reviews = [
        fixture_review(FIXTURE_FAMILIES[0], gate=gate),
        fixture_review(FIXTURE_FAMILIES[1], gate=gate),
        fixture_review(
            FIXTURE_FAMILIES[0],
            gate=gate,
            reviewer_id=f"reviewer-duplicate-{_FIXTURE_PACKET[gate]}",
        ),
    ]
    return _verdict_fail(_with_reviews(reviews, gate=gate), gate_id=gate)


def _should_engage_malformed_record(gate: str) -> bool:
    missing = fixture_review(FIXTURE_FAMILIES[0], gate=gate)
    del missing["retention"]
    extra = fixture_review(FIXTURE_FAMILIES[0], gate=gate)
    extra["extra"] = "field"
    vacant = fixture_review(FIXTURE_FAMILIES[0], gate=gate, destinations=[])
    authorised = fixture_inventory(gate=gate)["reviews"]
    return all(
        (
            _verdict_fail(
                _with_reviews([missing, authorised[1], authorised[2]], gate=gate),
                gate_id=gate,
            ),
            _verdict_fail(
                _with_reviews([extra, authorised[1], authorised[2]], gate=gate),
                gate_id=gate,
            ),
            _verdict_fail(
                _with_reviews([vacant, authorised[1], authorised[2]], gate=gate),
                gate_id=gate,
            ),
        )
    )


def _should_engage_invalid_seal(gate: str) -> bool:
    bad = fixture_review(
        FIXTURE_FAMILIES[0], gate=gate, seal="hmac-sha256:" + "0" * 64
    )
    authorised = fixture_inventory(gate=gate)["reviews"]
    return _verdict_fail(
        _with_reviews([bad, authorised[1], authorised[2]], gate=gate), gate_id=gate
    )


def _should_engage_non_pass_verdict(gate: str) -> bool:
    authorised = fixture_inventory(gate=gate)["reviews"]
    failed = fixture_review(FIXTURE_FAMILIES[0], gate=gate, verdict="FAIL")
    waived = fixture_review(FIXTURE_FAMILIES[0], gate=gate, verdict="WAIVE")
    return _verdict_fail(
        _with_reviews([failed, authorised[1], authorised[2]], gate=gate), gate_id=gate
    ) and _verdict_fail(
        _with_reviews([waived, authorised[1], authorised[2]], gate=gate), gate_id=gate
    )


def _should_engage_binding_mismatch(gate: str) -> bool:
    authorised = fixture_inventory(gate=gate)["reviews"]
    other = _CROSS_OTHER[gate]
    other_role = BINDINGS[other][1]
    other_endpoint = BINDINGS[other][2]
    mismatched = fixture_review(FIXTURE_FAMILIES[0], gate=gate, gate_id=other)
    role = fixture_review(FIXTURE_FAMILIES[0], gate=gate, source_role=other_role)
    endpoint = fixture_review(
        FIXTURE_FAMILIES[0], gate=gate, endpoint=other_endpoint
    )
    engaged = all(
        (
            _verdict_fail(
                _with_reviews([mismatched, authorised[1], authorised[2]], gate=gate),
                gate_id=gate,
            ),
            _verdict_fail(
                _with_reviews([role, authorised[1], authorised[2]], gate=gate),
                gate_id=gate,
            ),
            _verdict_fail(
                _with_reviews([endpoint, authorised[1], authorised[2]], gate=gate),
                gate_id=gate,
            ),
        )
    )
    if gate == GATE_ID:
        return engaged
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    sibling = fixture_inventory(gate=other)
    gates = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        now=FIXTURE_NOW,
        **{_PROVING_INVENTORY_KW[gate]: sibling},
    )
    proving = next(g for g in gates if g.gate_id == gate)
    crossed = engaged and _verdict_fail(sibling, gate_id=gate) and (
        proving.status is GateStatus.FAIL
    )
    if gate == UK_10_GATE_ID:
        aliased = _with_reviews(
            [
                fixture_review(family, gate=gate, endpoint=UK_10_NINE_P_ENDPOINT)
                for family in FIXTURE_FAMILIES
            ],
            gate=gate,
        )
        alias_gates = proving_assess(
            run_id="r1",
            kill_switch=False,
            no_emergency_stop=True,
            now=FIXTURE_NOW,
            **{_PROVING_INVENTORY_KW[gate]: aliased},
        )
        alias_proving = next(g for g in alias_gates if g.gate_id == gate)
        return (
            crossed
            and _verdict_fail(aliased, gate_id=gate)
            and alias_proving.status is GateStatus.FAIL
        )
    if gate == RAD_01_GATE_ID:
        aliased = _with_reviews(
            [
                fixture_review(family, gate=gate, endpoint=RAD_01_NINE_P_ENDPOINT)
                for family in FIXTURE_FAMILIES
            ],
            gate=gate,
        )
        alias_gates = proving_assess(
            run_id="r1",
            kill_switch=False,
            no_emergency_stop=True,
            now=FIXTURE_NOW,
            **{_PROVING_INVENTORY_KW[gate]: aliased},
        )
        alias_proving = next(g for g in alias_gates if g.gate_id == gate)
        return (
            crossed
            and _verdict_fail(aliased, gate_id=gate)
            and alias_proving.status is GateStatus.FAIL
        )
    return crossed


def _should_engage_terms_digest_drift(gate: str) -> bool:
    authorised = fixture_inventory(gate=gate)["reviews"]
    drifted = fixture_review(
        FIXTURE_FAMILIES[0], gate=gate, terms_digest="sha256:" + "0" * 64
    )
    return _verdict_fail(
        _with_reviews([drifted, authorised[1], authorised[2]], gate=gate),
        gate_id=gate,
    )


def _should_engage_expired_or_future(gate: str) -> bool:
    authorised = fixture_inventory(gate=gate)["reviews"]
    expired = fixture_review(FIXTURE_FAMILIES[0], gate=gate, expires_at=FIXTURE_NOW)
    future = fixture_review(
        FIXTURE_FAMILIES[0], gate=gate, issued_at="2026-08-18T12:00:00.000001Z"
    )
    return _verdict_fail(
        _with_reviews([expired, authorised[1], authorised[2]], gate=gate),
        gate_id=gate,
    ) and _verdict_fail(
        _with_reviews([future, authorised[1], authorised[2]], gate=gate),
        gate_id=gate,
    )


def _should_engage_anti_namesake(gate: str) -> bool:
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess
    from scripts.increment9_shadow_campaign import required_gate_ids

    namesake_closed = _refused(
        lambda: refuse_namesake_satisfaction(required_gate_ids(), gate=gate)
    )
    boolean_closed = _refused(lambda: refuse_boolean(True)) and _verdict_fail(
        True, gate_id=gate
    )
    record_closed = _refused(
        lambda: refuse_gate_record_namesake(
            {"reviewer_families": list(FIXTURE_FAMILIES), "subject_digest": "sha256:" + "0" * 64}
        )
    )
    gates = proving_assess(run_id="r1", kill_switch=False, no_emergency_stop=True)
    proving = next(g for g in gates if g.gate_id == gate)
    listed = gate in required_gate_ids()
    engaged = (
        namesake_closed
        and boolean_closed
        and record_closed
        and listed
        and proving.status is GateStatus.FAIL
        and proving.reason == "inventory is required"
    )
    if gate == GATE_ID:
        return engaged
    extra: dict[str, object] = {
        "rights": fixture_inventory(gate=GATE_ID),
        "now": FIXTURE_NOW,
    }
    prior = {
        UK_03_GATE_ID: (UK_02_GATE_ID,),
        UK_05_GATE_ID: (UK_02_GATE_ID, UK_03_GATE_ID),
        UK_10_GATE_ID: (UK_02_GATE_ID, UK_03_GATE_ID, UK_05_GATE_ID),
        HK_01_GATE_ID: (
            UK_02_GATE_ID,
            UK_03_GATE_ID,
            UK_05_GATE_ID,
            UK_10_GATE_ID,
        ),
        HK_02_GATE_ID: (
            UK_02_GATE_ID,
            UK_03_GATE_ID,
            UK_05_GATE_ID,
            UK_10_GATE_ID,
            HK_01_GATE_ID,
        ),
        HK_04_GATE_ID: (
            UK_02_GATE_ID,
            UK_03_GATE_ID,
            UK_05_GATE_ID,
            UK_10_GATE_ID,
            HK_01_GATE_ID,
            HK_02_GATE_ID,
        ),
        RAD_01_GATE_ID: (
            UK_02_GATE_ID,
            UK_03_GATE_ID,
            UK_05_GATE_ID,
            UK_10_GATE_ID,
            HK_01_GATE_ID,
            HK_02_GATE_ID,
            HK_04_GATE_ID,
        ),
        RAD_02_GATE_ID: (
            UK_02_GATE_ID,
            UK_03_GATE_ID,
            UK_05_GATE_ID,
            UK_10_GATE_ID,
            HK_01_GATE_ID,
            HK_02_GATE_ID,
            HK_04_GATE_ID,
            RAD_01_GATE_ID,
        ),
    }
    for sibling in prior.get(gate, ()):
        extra[_PROVING_INVENTORY_KW[sibling]] = fixture_inventory(gate=sibling)
    isolated = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        **extra,
    )
    uk01 = next(g for g in isolated if g.gate_id == GATE_ID)
    target = next(g for g in isolated if g.gate_id == gate)
    if uk01.status is not GateStatus.PASS or target.status is not GateStatus.FAIL:
        return False
    return engaged and all(
        next(g for g in isolated if g.gate_id == sibling).status is GateStatus.PASS
        for sibling in prior.get(gate, ())
    )


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


def _demonstrate(inventory: Mapping[str, object], *, gate: str = GATE_ID) -> RightsVerdict:
    first = assess_rights(gate, inventory=inventory, now=FIXTURE_NOW)
    second = assess_rights(gate, inventory=inventory, now=FIXTURE_NOW)
    if first.status != "PASS" or first != second:
        raise QualificationError("inventory is required")
    from newsroom.increment9.proving import GateStatus
    from newsroom.increment9.proving import assess as proving_assess

    gates = proving_assess(
        run_id="r1",
        kill_switch=False,
        no_emergency_stop=True,
        now=FIXTURE_NOW,
        **{_PROVING_INVENTORY_KW[gate]: inventory},
    )
    proving = next(g for g in gates if g.gate_id == gate)
    if proving.status is not GateStatus.PASS:
        raise QualificationError("inventory is required")
    return first


def _evidence_body(
    bound: RightsVerdict,
    records: tuple[RefusalDigest, ...],
    engaged_count: int,
) -> dict[str, object]:
    return {
        "deterministic_pass": True,
        "gate_id": bound.gate_id,
        "pass_derivation": {
            "endpoint": bound.endpoint,
            "gate_id": bound.gate_id,
            "reviewer_count": 3,
            "reviewer_families": list(bound.families),
            "reviewer_ids": list(bound.reviewer_ids),
            "source_role": bound.source_role,
            "unanimous": True,
            "verdicts": ["PASS", "PASS", "PASS"],
        },
        "refusals": _refusal_payload(records),
        "refusals_engaged": engaged_count,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
    }


def assess(
    inventory: Path,
    *,
    probe: Probe | None = None,
    gate: str = GATE_ID,
    rights_inventory: Mapping[str, object] | None = None,
) -> QualificationEvidence:
    """Assess that an emitted Rights Gate's refusal classes engage deterministically."""

    if gate not in EMITTED_GATES:
        raise QualificationError(_EMITTED_ONLY)
    _reject_forbidden(inventory)
    surfaces = _refusal_surfaces(inventory)
    _require_hmac_key(inventory)
    if rights_inventory is not None:
        try:
            bound_inventory = bind_inventory(rights_inventory)
        except RightsError as exc:
            raise QualificationError("inventory is required") from exc
    else:
        bound_inventory = _load_inventory(inventory)
    writer = probe_for(gate) if probe is None else probe
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
        RefusalDigest(rc, before[rc], after[rc], True, PROBE_COUNTS_BY_GATE[gate][rc])
        for rc in REFUSAL_CLASSES
    )
    raw = {
        "bound_terms": bound_inventory["bound_terms"],
        "now": bound_inventory["now"],
        "reviews": bound_inventory["reviews"],
    }
    bound = _demonstrate(raw, gate=gate)
    payload = _evidence_body(bound, records, engaged_count)
    return QualificationEvidence(
        gate_id=gate,
        status="PASS",
        endpoint=str(bound.endpoint),
        source_role=str(bound.source_role),
        families=bound.families,
        reviewer_ids=bound.reviewer_ids,
        refusals_engaged=engaged_count,
        refusals=records,
        evidence_digest=digest_bytes(canonical_json_bytes(payload)),
    )


def evidence_json(evidence: QualificationEvidence) -> bytes:
    """Serialise qualification evidence to canonical JSON."""

    payload = _evidence_body(
        RightsVerdict(
            status=evidence.status,
            reason="authorised",
            gate_id=evidence.gate_id,
            endpoint=evidence.endpoint,
            source_role=evidence.source_role,
            families=evidence.families,
            reviewer_ids=evidence.reviewer_ids,
        ),
        evidence.refusals,
        evidence.refusals_engaged,
    )
    payload["evidence_digest"] = evidence.evidence_digest
    return canonical_json_bytes(payload)
