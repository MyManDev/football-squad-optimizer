"""Bounded canonical DTO bytes for the composite's code-selected source types.

The caller supplies the concrete dataclass type. Payloads cannot name a Python
class, import a module, call a factory, or introduce fields outside that type.
Model parameters use their own narrower family readers instead of this codec.
"""

from __future__ import annotations

import hashlib
import json
import math
import types
from contextlib import suppress
from dataclasses import fields, is_dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal, TypeVar, Union, cast, get_args, get_origin, get_type_hints

T = TypeVar("T")
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_VECTOR_ITEMS = 20000
MAX_DEPTH = 24


@lru_cache(maxsize=128)
def _declared_fields(expected: type[Any]) -> tuple[tuple[str, Any], ...]:
    """Cache only code-selected DTO schemas, never a payload-selected type."""
    names = tuple(field.name for field in fields(expected))
    hints = get_type_hints(expected)
    if set(hints) != set(names):
        raise ValueError("Composite source type lacks exact field annotations.")
    return tuple((name, hints[name]) for name in names)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Composite source JSON repeats an object field.")
        result[name] = value
    return result


def _decode(value: Any, expected: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ValueError("Composite source exceeds the nesting bound.")
    origin, args = get_origin(expected), get_args(expected)
    if origin in (Union, types.UnionType):
        candidates = []
        for option in args:
            with suppress(ValueError):
                candidates.append(_decode(value, option, depth + 1))
        if len(candidates) != 1:
            raise ValueError("Composite source has no unique declared variant.")
        return candidates[0]
    if origin is Literal:
        if any(type(value) is type(option) and value == option for option in args):
            return value
        raise ValueError("Composite source uses an unsupported literal.")
    if origin is tuple:
        if type(value) is not list or len(value) > MAX_VECTOR_ITEMS:
            raise ValueError("Composite source requires a bounded array.")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(item, args[0], depth + 1) for item in value)
        if len(value) != len(args):
            raise ValueError("Composite source tuple has a different length.")
        return tuple(
            _decode(item, item_type, depth + 1) for item, item_type in zip(value, args, strict=True)
        )
    if isinstance(expected, type) and is_dataclass(expected):
        declared = _declared_fields(expected)
        if type(value) is not dict or set(value) != {name for name, _ in declared}:
            raise ValueError("Composite source fields differ from the declared DTO.")
        try:
            return expected(
                **{name: _decode(value[name], hint, depth + 1) for name, hint in declared}
            )
        except (TypeError, OverflowError, AttributeError) as error:
            raise ValueError("Composite source DTO failed construction.") from error
    if expected is datetime:
        if type(value) is not str:
            raise ValueError("Composite source timestamp must be text.")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Composite source timestamp is malformed.") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Composite source timestamp requires an explicit offset.")
        return timestamp
    if expected is float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Composite source number must be finite and not Boolean.")
        return float(value)
    if expected in (str, int, bool, type(None)) and type(value) is expected:
        return value
    raise ValueError("Composite source does not match its code-selected type.")


def _encode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        raise ValueError("Composite source exceeds the nesting bound.")
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encode(getattr(value, field.name), depth + 1) for field in fields(value)
        }
    if type(value) is tuple:
        if len(value) > MAX_VECTOR_ITEMS:
            raise ValueError("Composite source exceeds the array bound.")
        return [_encode(item, depth + 1) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Composite source timestamp requires an explicit offset.")
        return value.isoformat()
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Composite source contains a non-DTO or nonfinite value.")


def composite_source_bytes(value: object) -> bytes:
    """Serialize an immutable typed source, validating its full annotation graph."""
    if not is_dataclass(value) or isinstance(value, type):
        raise ValueError("Composite source root must be a dataclass instance.")
    document = _encode(_decode(_encode(value), type(value)))
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("Composite source exceeds its byte bound.")
    return payload


def read_composite_source(payload: bytes, *, expected_sha256: str, source_type: type[T]) -> T:
    """Restore the caller-selected DTO; an integrity hash does not authenticate a source."""
    if (
        type(payload) is not bytes
        or not 0 < len(payload) <= MAX_SOURCE_BYTES
        or type(expected_sha256) is not str
        or hashlib.sha256(payload).hexdigest() != expected_sha256
        or not isinstance(source_type, type)
        or not is_dataclass(source_type)
    ):
        raise ValueError("Composite source bytes, digest or declared type are invalid.")
    try:
        document = json.loads(payload, object_pairs_hook=_object)
        canonical = json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if canonical != payload:
            raise ValueError("Composite source bytes must use canonical JSON.")
        restored = _decode(document, source_type)
        if composite_source_bytes(restored) != payload:
            raise ValueError("Composite source is not in its canonical typed representation.")
        return cast(T, restored)
    except (UnicodeError, RecursionError, OverflowError, TypeError) as error:
        raise ValueError("Malformed composite source JSON.") from error
