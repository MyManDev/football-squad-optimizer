"""Runtime platform contracts above the transport-neutral application layer.

This package may consume ``squadopt.application`` and every lower engine layer. Nothing
below it imports platform code. Concrete HTTP, database, queue and deployment adapters
arrive later and remain on this side of the boundary.
"""

from squadopt.platform.context import (
    RUN_CONTEXT_CONTRACT_VERSION,
    RunContext,
    RunContextError,
)
from squadopt.platform.manifest import (
    RUN_MANIFEST_CONTRACT_VERSION,
    RUN_MANIFEST_SCHEMA_PATH,
    RunManifestError,
    parse_run_manifest,
    read_run_manifest,
    run_manifest_document,
    run_manifest_schema,
    serialize_run_manifest,
    write_run_manifest,
    write_run_manifest_schema,
)

__all__ = [
    "RUN_CONTEXT_CONTRACT_VERSION",
    "RUN_MANIFEST_CONTRACT_VERSION",
    "RUN_MANIFEST_SCHEMA_PATH",
    "RunContext",
    "RunContextError",
    "RunManifestError",
    "parse_run_manifest",
    "read_run_manifest",
    "run_manifest_document",
    "run_manifest_schema",
    "serialize_run_manifest",
    "write_run_manifest",
    "write_run_manifest_schema",
]
