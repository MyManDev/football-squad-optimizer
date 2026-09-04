"""Deterministic ``run_manifest_v1`` JSON serialization.

The manifest is the portable representation of :class:`~squadopt.platform.RunContext`.
It is intentionally only an immutable execution identity; lifecycle status, outputs and
failure details belong to the run repository introduced above this contract.
"""

import contextlib
import json
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from squadopt.platform.context import RunContext

RUN_MANIFEST_CONTRACT_VERSION: Final = "run_manifest_v1"
RUN_MANIFEST_SCHEMA_PATH: Final = Path("docs") / "contracts" / "run_manifest_v1.schema.json"


class RunManifestError(ValueError):
    """A run manifest is malformed, unsupported or conflicts with an existing record."""


def run_manifest_document(context: RunContext) -> dict[str, object]:
    """Return the complete JSON-native manifest document."""

    if not isinstance(context, RunContext):
        raise RunManifestError("context must be a RunContext.")
    return {
        "contract_version": RUN_MANIFEST_CONTRACT_VERSION,
        "context": context.to_dict(),
    }


def serialize_run_manifest(context: RunContext) -> bytes:
    """Return canonical UTF-8 bytes with stable key order and one final newline."""

    text = json.dumps(
        run_manifest_document(context),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    return (text + "\n").encode("utf-8")


def parse_run_manifest(data: bytes | str) -> RunContext:
    """Parse and verify one serialized manifest."""

    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as error:
        raise RunManifestError("Run manifest is not valid UTF-8.") from error
    if not isinstance(text, str):
        raise RunManifestError("Run manifest must be bytes or text.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise RunManifestError(f"Run manifest is not valid JSON: {error}.") from error
    if not isinstance(parsed, Mapping):
        raise RunManifestError("Run manifest must be a JSON object.")
    if set(parsed) != {"contract_version", "context"}:
        raise RunManifestError(
            "Run manifest fields must be exactly 'contract_version' and 'context'."
        )
    if parsed["contract_version"] != RUN_MANIFEST_CONTRACT_VERSION:
        raise RunManifestError(
            f"Run manifest contract must be {RUN_MANIFEST_CONTRACT_VERSION!r}, "
            f"got {parsed['contract_version']!r}."
        )
    context = parsed["context"]
    if not isinstance(context, Mapping):
        raise RunManifestError("Run manifest 'context' must be a JSON object.")
    try:
        return RunContext.from_dict(context)
    except ValueError as error:
        raise RunManifestError(f"Run manifest context is invalid: {error}") from error


def write_run_manifest(path: Path | str, context: RunContext) -> Path:
    """Atomically publish one immutable manifest, allowing an identical retry.

    A sibling temporary file is hard-linked into place, so a concurrent writer cannot
    replace an existing run identity. Repeating the exact same write is idempotent;
    attempting to reuse the path for another context is refused.
    """

    target = Path(path)
    payload = serialize_run_manifest(context)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        temporary.write_bytes(payload)
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != payload:
                raise RunManifestError(
                    f"Run manifest {target} already exists with different content."
                ) from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return target


def read_run_manifest(path: Path | str) -> RunContext:
    """Read and verify a manifest from disk."""

    return parse_run_manifest(Path(path).read_bytes())


def run_manifest_schema() -> dict[str, object]:
    """Return the JSON Schema for the portable manifest contract."""

    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    name_pattern = "^[a-z][a-z0-9._-]{0,63}$"
    context = {
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": "run_context_v1"},
            "run_id": {
                "type": "string",
                "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
            },
            "created_at_utc": {
                "type": "string",
                "format": "date-time",
                "pattern": "Z$",
            },
            "repository_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "configuration_fingerprint": digest,
            "input_fingerprints": {
                "type": "object",
                "minProperties": 1,
                "propertyNames": {"pattern": name_pattern},
                "additionalProperties": digest,
            },
            "component_versions": {
                "type": "object",
                "propertyNames": {"pattern": name_pattern},
                "additionalProperties": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": r"^\S(?:.*\S)?$",
                },
            },
            "deterministic_seed": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2**63 - 1,
            },
            "reproducibility_fingerprint": digest,
        },
        "required": [
            "component_versions",
            "configuration_fingerprint",
            "contract_version",
            "created_at_utc",
            "deterministic_seed",
            "input_fingerprints",
            "repository_commit",
            "reproducibility_fingerprint",
            "run_id",
        ],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://squadopt.dev/contracts/{RUN_MANIFEST_CONTRACT_VERSION}.schema.json",
        "title": "SquadOpt run manifest",
        "description": "Immutable identity and reproducibility inputs for one platform run.",
        "type": "object",
        "properties": {
            "contract_version": {
                "type": "string",
                "const": RUN_MANIFEST_CONTRACT_VERSION,
            },
            "context": context,
        },
        "required": ["context", "contract_version"],
        "additionalProperties": False,
    }


def write_run_manifest_schema(path: Path | str | None = None) -> Path:
    """Write the deterministic schema document to ``path`` or its committed location."""

    target = Path(path) if path is not None else RUN_MANIFEST_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(run_manifest_schema(), indent=2, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return target
