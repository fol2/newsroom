from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Mapping

from lxml import etree

from newsroom.authority.canonical import digest_canonical
from newsroom.authority.types import UtcTimestamp
from newsroom.sources import SourceDefinitionId, SourceDefinitionVersionId

from .models import (
    Capture,
    ParsedField,
    ParsedItem,
    ParserIssue,
    ParserResult,
)
from .types import (
    AdapterContractError,
    AdapterKind,
    AdapterRequestId,
    AdapterVersionRef,
    Completeness,
    ParserLimits,
    ParserResultId,
    ShapeField,
    SourceShapeContract,
)


_MISSING = object()
_PROHIBITED_XML_MARKERS = (b"<!doctype", b"<!entity")
_PATH_LEAF = "\x00leaf"
_XML_DECLARATION_ENCODING = re.compile(
    r"^<\?xml[^>]*\bencoding\s*=\s*([\'\"])([^\'\"]+)\1",
    re.IGNORECASE,
)


class _DuplicateJsonKey(AdapterContractError):
    pass


@dataclass(frozen=True, slots=True)
class _ParsedBatch:
    items: tuple[ParsedItem, ...]
    issues: tuple[ParserIssue, ...]
    completeness: Completeness
    shape_drift: bool


def _reject_constant(value: str) -> None:
    raise AdapterContractError(
        f"JSON non-finite number is prohibited: {value}"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_utf8(data: bytes, *, identity: str) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise AdapterContractError(
            f"{identity} is not valid UTF-8"
        ) from exc


def _validate_json_resources(value: Any, limits: ParserLimits) -> None:
    entries = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limits.max_depth:
            raise AdapterContractError(
                "JSON nesting exceeds its depth bound"
            )
        if isinstance(current, Mapping):
            entries += len(current)
            for key, child in current.items():
                if len(key.encode("utf-8")) > limits.max_scalar_bytes:
                    raise AdapterContractError(
                        "JSON key exceeds its scalar bound"
                    )
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            entries += len(current)
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            if len(current.encode("utf-8")) > limits.max_scalar_bytes:
                raise AdapterContractError(
                    "JSON string exceeds its scalar bound"
                )
        elif isinstance(current, float):
            if not math.isfinite(current):
                raise AdapterContractError("JSON number must be finite")
            if len(repr(current).encode("utf-8")) > limits.max_scalar_bytes:
                raise AdapterContractError(
                    "JSON number exceeds its scalar bound"
                )
        elif isinstance(current, int) and not isinstance(current, bool):
            if len(str(current).encode("utf-8")) > limits.max_scalar_bytes:
                raise AdapterContractError(
                    "JSON number exceeds its scalar bound"
                )
        elif current is not None and not isinstance(current, bool):
            raise AdapterContractError(
                "JSON contains an unsupported scalar"
            )
        if entries > limits.max_collection_entries:
            raise AdapterContractError(
                "JSON collection size exceeds its bound"
            )


def safe_json_loads(data: bytes, *, limits: ParserLimits) -> Any:
    text = _decode_utf8(data, identity="JSON body")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _DuplicateJsonKey:
        raise
    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise AdapterContractError("JSON body is malformed") from exc
    _validate_json_resources(value, limits)
    return value


def _extract_path(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _scalar_text(value: Any, *, field: ShapeField) -> str | object:
    if value is _MISSING or value is None:
        return _MISSING
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float) and math.isfinite(value):
        text = repr(value)
    else:
        raise AdapterContractError(
            f"shape field {field.name} is not scalar"
        )
    if len(text.encode("utf-8")) > field.maximum_bytes:
        raise AdapterContractError(
            f"shape field {field.name} exceeds its byte bound"
        )
    return text


def _allowed_path_tree(contract: SourceShapeContract) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for field in contract.fields:
        current = root
        for part in field.path:
            current = current.setdefault(part, {})
        current[_PATH_LEAF] = True
    return root


def _unexpected_paths(
    value: Mapping[str, Any],
    *,
    contract: SourceShapeContract,
) -> tuple[str, ...]:
    if contract.allow_additional_fields:
        return ()
    unexpected: list[str] = []
    stack: list[tuple[Mapping[str, Any], dict[str, Any], tuple[str, ...]]] = [
        (value, _allowed_path_tree(contract), ())
    ]
    while stack:
        current, allowed, prefix = stack.pop()
        for key, child in current.items():
            node = allowed.get(key)
            path = (*prefix, key)
            if not isinstance(node, dict):
                unexpected.append(".".join(path))
                continue
            descendants = {
                name: child_node
                for name, child_node in node.items()
                if name != _PATH_LEAF
            }
            if isinstance(child, Mapping) and descendants:
                stack.append((child, descendants, path))
            elif isinstance(child, Mapping) and _PATH_LEAF not in node:
                unexpected.extend(
                    ".".join((*path, nested))
                    for nested in sorted(child)
                )
    return tuple(sorted(set(unexpected)))


def _item_from_mapping(
    value: Mapping[str, Any],
    *,
    source_definition_id: SourceDefinitionId,
    contract: SourceShapeContract,
    index: int,
) -> tuple[ParsedItem | None, tuple[ParserIssue, ...], bool]:
    fields: list[ParsedField] = []
    issues: list[ParserIssue] = []
    by_name: dict[str, str] = {}
    item_invalid = False

    unexpected = _unexpected_paths(value, contract=contract)
    if unexpected:
        issues.append(
            ParserIssue(
                "UNEXPECTED_FIELDS",
                "unexpected fields: " + ",".join(unexpected),
                item_index=index,
            )
        )
        return None, tuple(issues), True

    for field in contract.fields:
        try:
            selected = _scalar_text(
                _extract_path(value, field.path),
                field=field,
            )
        except AdapterContractError as exc:
            issues.append(
                ParserIssue(
                    "FIELD_INVALID",
                    str(exc),
                    item_index=index,
                )
            )
            item_invalid = True
            continue
        if selected is _MISSING:
            if field.required:
                issues.append(
                    ParserIssue(
                        "REQUIRED_FIELD_MISSING",
                        f"required field {field.name} is absent",
                        item_index=index,
                    )
                )
                item_invalid = True
            continue
        assert isinstance(selected, str)
        by_name[field.name] = selected
        fields.append(ParsedField(field.name, selected))

    missing_identity = [
        name
        for name in contract.identity_fields
        if name not in by_name
    ]
    if missing_identity:
        issues.append(
            ParserIssue(
                "IDENTITY_FIELD_MISSING",
                "missing identity fields: " + ",".join(missing_identity),
                item_index=index,
            )
        )
        item_invalid = True

    if item_invalid or not fields:
        return None, tuple(issues), False
    if contract.singleton_identity is not None:
        identity: object = {
            "singleton_identity": contract.singleton_identity,
        }
    else:
        identity = [
            (name, by_name[name])
            for name in contract.identity_fields
        ]
    key = digest_canonical(
        {
            "source_definition_id": str(source_definition_id),
            "identity": identity,
        }
    )
    return (
        ParsedItem(
            item_key=key,
            fields=tuple(sorted(fields, key=lambda item: item.name)),
        ),
        tuple(issues),
        False,
    )


def _finalize_batch(
    *,
    values: list[Mapping[str, Any]],
    source_definition_id: SourceDefinitionId,
    contract: SourceShapeContract,
    limits: ParserLimits,
    structural_drift: bool,
    structural_issues: list[ParserIssue],
) -> _ParsedBatch:
    if contract.singleton_identity is not None and len(values) > 1:
        return _ParsedBatch(
            items=(),
            issues=(
                ParserIssue(
                    "SINGLETON_MULTIPLE_ITEMS",
                    "singleton source shape produced multiple items",
                ),
            ),
            completeness=Completeness.PARTIAL,
            shape_drift=True,
        )

    truncated = len(values) > limits.max_items
    selected = values[: limits.max_items]
    if truncated:
        structural_issues.append(
            ParserIssue(
                "ITEM_LIMIT_TRUNCATED",
                "item count exceeded the parser bound",
            )
        )

    by_key: dict[str, ParsedItem] = {}
    issues = list(structural_issues)
    drift = structural_drift
    invalid = sum(
        1 for issue in structural_issues if issue.item_index is not None
    )
    for index, value in enumerate(selected):
        item, item_issues, item_drift = _item_from_mapping(
            value,
            source_definition_id=source_definition_id,
            contract=contract,
            index=index,
        )
        issues.extend(item_issues)
        drift = drift or item_drift
        if item is None:
            invalid += 1
            continue
        existing = by_key.get(item.item_key)
        if existing is not None:
            code = (
                "DUPLICATE_ITEM"
                if existing == item
                else "IDENTITY_COLLISION"
            )
            issues.append(
                ParserIssue(
                    code,
                    "multiple parsed items occupy one source-scoped identity",
                    item_index=index,
                )
            )
            if existing != item:
                drift = True
            invalid += 1
            continue
        by_key[item.item_key] = item

    if invalid and not by_key:
        drift = True

    if truncated:
        completeness = Completeness.TRUNCATED
    elif invalid:
        completeness = Completeness.PARTIAL
    else:
        completeness = Completeness.COMPLETE
    return _ParsedBatch(
        items=tuple(sorted(by_key.values(), key=lambda item: item.item_key)),
        issues=tuple(
            sorted(
                issues,
                key=lambda item: (
                    item.code,
                    -1 if item.item_index is None else item.item_index,
                    item.message,
                ),
            )
        ),
        completeness=completeness,
        shape_drift=drift,
    )


def _json_batch(
    data: bytes,
    *,
    source_definition_id: SourceDefinitionId,
    contract: SourceShapeContract,
    limits: ParserLimits,
) -> _ParsedBatch:
    value = safe_json_loads(data, limits=limits)
    container = (
        _extract_path(value, contract.items_path)
        if contract.items_path
        else value
    )
    if isinstance(container, Mapping):
        values = [container]
        issues: list[ParserIssue] = []
        drift = False
    elif isinstance(container, list):
        values = []
        issues = []
        drift = False
        for index, item in enumerate(container):
            if isinstance(item, Mapping):
                values.append(item)
            else:
                issues.append(
                    ParserIssue(
                        "ITEM_NOT_OBJECT",
                        "JSON item is not an object",
                        item_index=index,
                    )
                )
        # A non-object list entry is an honest partial item failure, not a
        # whole-source shape drift when other object boundaries are intact.
    else:
        return _finalize_batch(
            values=[],
            source_definition_id=source_definition_id,
            contract=contract,
            limits=limits,
            structural_drift=True,
            structural_issues=[
                ParserIssue(
                    "ITEM_CONTAINER_MISSING",
                    "JSON items path does not resolve to an object or list",
                )
            ],
        )
    return _finalize_batch(
        values=values,
        source_definition_id=source_definition_id,
        contract=contract,
        limits=limits,
        structural_drift=drift,
        structural_issues=issues,
    )


def _xml_local_name(element: etree._Element) -> str:
    if not isinstance(element.tag, str):
        return ""
    return etree.QName(element).localname.lower()


def _direct_children(
    element: etree._Element,
    names: set[str],
) -> list[etree._Element]:
    return [
        child
        for child in element
        if _xml_local_name(child) in names
    ]


def _first_text(
    element: etree._Element,
    names: tuple[str, ...],
) -> str | None:
    for name in names:
        children = _direct_children(element, {name})
        for child in children:
            text = " ".join(
                part.strip()
                for part in child.itertext()
                if part.strip()
            )
            if text:
                return text
    return None


def _first_descendant_text(
    element: etree._Element,
    names: tuple[str, ...],
) -> str | None:
    selected = set(names)
    for child in element.iter():
        if _xml_local_name(child) not in selected:
            continue
        text = " ".join(
            part.strip()
            for part in child.itertext()
            if part.strip()
        )
        if text:
            return text
    return None


def _feed_mapping(element: etree._Element) -> dict[str, str]:
    value: dict[str, str] = {}
    for key, names in {
        "title": ("title",),
        "id": ("id", "guid"),
        "guid": ("guid",),
        "published": ("published", "pubdate", "date"),
        "updated": ("updated", "modified"),
        "summary": ("summary", "description"),
        "content": ("content", "encoded"),
        "author": ("author", "creator"),
    }.items():
        selected = _first_text(element, names)
        if selected is not None:
            value[key] = selected

    link: str | None = None
    for child in _direct_children(element, {"link"}):
        href = child.attrib.get("href")
        relation = child.attrib.get("rel", "alternate")
        if href and relation in {"alternate", "self"}:
            link = href.strip()
            if relation == "alternate":
                break
        elif child.text and child.text.strip():
            link = child.text.strip()
            break
    if link:
        value["link"] = link
    return value


def _validate_xml_resources(
    root: etree._Element,
    limits: ParserLimits,
) -> None:
    entries = 0
    stack: list[tuple[etree._Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        if depth > limits.max_depth:
            raise AdapterContractError(
                "XML nesting exceeds its depth bound"
            )
        entries += 1 + len(element.attrib)
        if entries > limits.max_collection_entries:
            raise AdapterContractError(
                "XML collection size exceeds its bound"
            )
        if len(element.attrib) > limits.max_xml_attributes:
            raise AdapterContractError(
                "XML attribute count exceeds its bound"
            )
        for value in element.attrib.values():
            if len(value.encode("utf-8")) > limits.max_scalar_bytes:
                raise AdapterContractError(
                    "XML attribute exceeds its scalar bound"
                )
        if (
            element.text
            and len(element.text.encode("utf-8"))
            > limits.max_scalar_bytes
        ):
            raise AdapterContractError(
                "XML text exceeds its scalar bound"
            )
        if (
            element.tail
            and len(element.tail.encode("utf-8"))
            > limits.max_scalar_bytes
        ):
            raise AdapterContractError(
                "XML tail text exceeds its scalar bound"
            )
        stack.extend((child, depth + 1) for child in element)


def _rss_atom_batch(
    data: bytes,
    *,
    source_definition_id: SourceDefinitionId,
    contract: SourceShapeContract,
    limits: ParserLimits,
) -> _ParsedBatch:
    text = _decode_utf8(data, identity="RSS/Atom XML")
    declaration = text.lstrip("\ufeff \t\r\n")[:512]
    encoding = _XML_DECLARATION_ENCODING.match(declaration)
    if encoding is not None and encoding.group(2).lower() not in {"utf-8", "utf8"}:
        raise AdapterContractError(
            "RSS/Atom XML declaration differs from UTF-8 transport contract"
        )
    lowered = data.lower()
    if any(marker in lowered for marker in _PROHIBITED_XML_MARKERS):
        raise AdapterContractError(
            "XML DTD or entity declarations are prohibited"
        )
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
        huge_tree=False,
        remove_comments=False,
    )
    try:
        root = etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise AdapterContractError(
            "RSS/Atom XML is malformed"
        ) from exc
    _validate_xml_resources(root, limits)
    root_name = _xml_local_name(root)
    if root_name == "feed":
        entries = [
            child
            for child in root
            if _xml_local_name(child) == "entry"
        ]
    elif root_name in {"rss", "rdf"}:
        entries = [
            item
            for item in root.iter()
            if _xml_local_name(item) == "item"
        ]
    else:
        return _finalize_batch(
            values=[],
            source_definition_id=source_definition_id,
            contract=contract,
            limits=limits,
            structural_drift=True,
            structural_issues=[
                ParserIssue(
                    "FEED_ROOT_DRIFT",
                    f"unexpected feed root {root_name}",
                )
            ],
        )
    return _finalize_batch(
        values=[_feed_mapping(entry) for entry in entries],
        source_definition_id=source_definition_id,
        contract=contract,
        limits=limits,
        structural_drift=False,
        structural_issues=[],
    )


def _maintained_document_batch(
    capture: Capture,
    *,
    source_definition_id: SourceDefinitionId,
    contract: SourceShapeContract,
    limits: ParserLimits,
) -> _ParsedBatch:
    if capture.content_type == "text/plain":
        text = _decode_utf8(
            capture.body,
            identity="maintained document",
        )
        value = {"body": text.strip()}
    elif capture.content_type == "text/html":
        _decode_utf8(capture.body, identity="maintained HTML")
        lowered = capture.body.lower()
        if b"<!entity" in lowered:
            raise AdapterContractError(
                "HTML entity declarations are prohibited"
            )
        parser = etree.HTMLParser(
            encoding="utf-8",
            no_network=True,
            recover=False,
            huge_tree=False,
        )
        try:
            root = etree.fromstring(capture.body, parser=parser)
        except (etree.XMLSyntaxError, ValueError) as exc:
            raise AdapterContractError(
                "maintained HTML is malformed"
            ) from exc
        if root is None:
            raise AdapterContractError(
                "maintained HTML has no document root"
            )
        _validate_xml_resources(root, limits)
        title = _first_descendant_text(root, ("title",))
        etree.strip_elements(
            root,
            "script",
            "style",
            with_tail=False,
        )
        text = " ".join(
            part.strip()
            for part in root.itertext()
            if part.strip()
        )
        value = {"body": text}
        if title:
            value["title"] = title
    else:
        raise AdapterContractError(
            "maintained-document content type is unsupported"
        )
    return _finalize_batch(
        values=[value],
        source_definition_id=source_definition_id,
        contract=contract,
        limits=limits,
        structural_drift=False,
        structural_issues=[],
    )


def _failure_batch(code: str, message: str) -> _ParsedBatch:
    return _ParsedBatch(
        items=(),
        issues=(ParserIssue(code, message),),
        completeness=Completeness.PARTIAL,
        shape_drift=False,
    )


def _representation_digest(batch: _ParsedBatch) -> str:
    # Representation equality is parsed/normalized output equality. Source
    # bytes and producer-slot versions are retained separately so a parser
    # upgrade cannot fabricate a publisher revision.
    return digest_canonical(
        {
            "completeness": batch.completeness.value,
            "items": [item.canonical_value() for item in batch.items],
            "issues": [item.canonical_value() for item in batch.issues],
            "shape_drift": batch.shape_drift,
        }
    )


def parse_capture(
    capture: Capture,
    *,
    parser_result_id: ParserResultId,
    request_id: AdapterRequestId,
    source_definition_id: SourceDefinitionId,
    source_definition_version_id: SourceDefinitionVersionId,
    kind: AdapterKind,
    adapter: AdapterVersionRef,
    shape_contract: SourceShapeContract,
    limits: ParserLimits,
    produced_at: UtcTimestamp,
) -> ParserResult:
    if shape_contract.kind is not kind:
        raise AdapterContractError(
            "parser kind differs from shape contract"
        )
    if (
        capture.request_id != request_id
        or capture.source_definition_id != source_definition_id
        or capture.source_definition_version_id
        != source_definition_version_id
    ):
        raise AdapterContractError(
            "parser invocation lineage differs from capture"
        )
    try:
        if kind is AdapterKind.JSON_DOCUMENT:
            batch = _json_batch(
                capture.body,
                source_definition_id=source_definition_id,
                contract=shape_contract,
                limits=limits,
            )
        elif kind is AdapterKind.RSS_ATOM:
            batch = _rss_atom_batch(
                capture.body,
                source_definition_id=source_definition_id,
                contract=shape_contract,
                limits=limits,
            )
        else:
            batch = _maintained_document_batch(
                capture,
                source_definition_id=source_definition_id,
                contract=shape_contract,
                limits=limits,
            )
    except _DuplicateJsonKey as exc:
        batch = _failure_batch("JSON_DUPLICATE_KEY", str(exc))
    except AdapterContractError as exc:
        batch = _failure_batch("PARSER_REJECTED", str(exc))

    producer_slot_digest = digest_canonical(
        {
            "adapter": adapter.canonical_value(),
            "shape_contract_digest": shape_contract.digest,
        }
    )
    return ParserResult(
        parser_result_id=parser_result_id,
        capture_id=capture.capture_id,
        capture_digest=capture.digest,
        request_id=request_id,
        source_definition_id=source_definition_id,
        source_definition_version_id=source_definition_version_id,
        adapter=adapter,
        shape_contract_digest=shape_contract.digest,
        source_body_digest=capture.body_digest,
        producer_slot_digest=producer_slot_digest,
        completeness=batch.completeness,
        items=batch.items,
        issues=batch.issues,
        representation_digest=_representation_digest(batch),
        shape_drift=batch.shape_drift,
        produced_at=produced_at,
    )


__all__ = ["parse_capture", "safe_json_loads"]
