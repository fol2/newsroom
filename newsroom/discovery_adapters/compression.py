from __future__ import annotations

import zlib

from .types import AdapterContractError, BodyEncoding, BodyLimits


def _bounded_inflate(data: bytes, *, wbits: int, limit: int) -> bytes:
    try:
        decompressor = zlib.decompressobj(wbits)
        output = decompressor.decompress(data, limit + 1)
        if len(output) > limit or decompressor.unconsumed_tail:
            raise AdapterContractError("decompressed body exceeds its byte bound")
        flushed = decompressor.flush(limit + 1 - len(output))
    except zlib.error as exc:
        raise AdapterContractError("compressed body is malformed") from exc
    output += flushed
    if len(output) > limit:
        raise AdapterContractError("decompressed body exceeds its byte bound")
    if decompressor.unused_data:
        raise AdapterContractError("concatenated compressed streams are prohibited")
    if not decompressor.eof:
        raise AdapterContractError("compressed body is truncated")
    return output


def decompress_body(
    data: bytes,
    *,
    encoding: BodyEncoding,
    limits: BodyLimits,
) -> bytes:
    if not isinstance(data, bytes):
        raise AdapterContractError("compressed body must be immutable bytes")
    if not isinstance(encoding, BodyEncoding):
        raise AdapterContractError("body encoding must be typed")
    if not isinstance(limits, BodyLimits):
        raise AdapterContractError("body limits must be typed")
    if encoding not in limits.allowed_encodings:
        raise AdapterContractError("body encoding is outside the allow-list")
    if len(data) > limits.max_compressed_bytes:
        raise AdapterContractError("compressed body exceeds its byte bound")

    if encoding is BodyEncoding.IDENTITY:
        output = data
    elif encoding is BodyEncoding.GZIP:
        output = _bounded_inflate(
            data,
            wbits=zlib.MAX_WBITS | 16,
            limit=limits.max_decompressed_bytes,
        )
    else:
        output = _bounded_inflate(
            data,
            wbits=zlib.MAX_WBITS,
            limit=limits.max_decompressed_bytes,
        )

    if len(output) > limits.max_decompressed_bytes:
        raise AdapterContractError("decompressed body exceeds its byte bound")
    if output:
        denominator = max(1, len(data))
        if len(output) > denominator * limits.max_decompression_ratio:
            raise AdapterContractError("decompression ratio exceeds its safe bound")
    return output


__all__ = ["decompress_body"]
