"""Read a ``rotation_evidence_v2`` pair, or refuse it.

The owner's lane reads this instead of raw captures, so everything the table asserts about
itself is checked here before a single row is returned: the digest, the manifest's required
fields, the column order, the completeness identity, the never-missing flags, every closed
vocabulary, and that no capture postdates the deadline it was built for.

The digest is recomputed **before the CSV is parsed**. A table that has been edited must not
get as far as pandas: a parse failure would report a malformed column when the real fact is
that the bytes are not the bytes that were published.

One check is deliberately weaker than Phase B's, and named rather than hidden.
``source_snapshot_ids`` varies by row here, because a row records only the captures it was
actually read from -- a player nobody wrote about was read from the decision capture alone.
Phase B's provenance is constant per table, so its reader can compare the manifest against
one row's value; this one compares the manifest against the **union** over rows.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError, DataValidationError
from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    PUBLISHED_PRECISIONS,
    ROTATION_DISPOSITIONS,
)
from squadopt.features.rotation_evidence import (
    _ROTATION_EVIDENCE_DTYPES,
    CONTRACT_VERSION,
    FEED_NEWS_STATES,
    FORBIDDEN_COLUMNS,
    ROTATION_EVIDENCE_COLUMNS,
)

#: The export's own contract, separate from the table's. The table is what the rows mean; this
#: is how the pair on disk is shaped, and either can move without the other.
ARTIFACT_CONTRACT_VERSION: Final = "rotation_evidence_export_v1"

#: Every manifest field the reader requires. A missing one refuses the pair: the manifest is
#: what makes the table checkable, and a manifest with a hole in it checks less than it claims.
REQUIRED_MANIFEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "contract_version",
        "artifact_contract_version",
        "season",
        "target_gameweek",
        "deadline_timestamp_utc",
        "generated_at_utc",
        "repository_commit",
        "table_file",
        "table_sha256",
        "row_count",
        "roster_size",
        "roster_snapshot_id",
        "source_snapshot_ids",
        "clubs_declared",
        "clubs_covered",
        "documents_read",
        "document_sha256s",
        "model_identifier",
        "model_version",
        "prompt_sha256",
        "response_sha256s",
        "claims_coded",
        "claims_ambiguous",
        "players_not_addressed",
    }
)

#: Columns the manifest also states, and which must agree with every row.
_COLUMN_TO_MANIFEST: Final[Mapping[str, str]] = {
    "contract_version": "contract_version",
    "season": "season",
    "target_gameweek": "target_gameweek",
    "deadline_timestamp_utc": "deadline_timestamp_utc",
}

#: Flags that are never missing, because each separates "did not happen" from "not observed".
_NEVER_MISSING_FLAGS: Final[tuple[str, ...]] = (
    "timing_verified",
    "club_source_covered",
    "rotation_claim_observed",
    "model_evidence_observed",
    "fixture_context_midweek",
)

#: Columns that carry a value only where a claim was observed, and nothing where none was.
_CLAIM_ONLY_COLUMNS: Final[tuple[str, ...]] = (
    "rotation_disposition",
    "rotation_claim_published_precision",
    "rotation_claim_speaker",
)


def _read_manifest(path: Path) -> Mapping[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise DataSourceError(f"Cannot read the manifest at {path}: {error}") from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DataSourceError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise DataValidationError(f"{path} must hold a JSON object.")
    missing = sorted(REQUIRED_MANIFEST_FIELDS - document.keys())
    if missing:
        raise DataValidationError(f"{path} is missing required manifest field(s) {missing!r}.")
    return document


def _single_value(table: pd.DataFrame, column: str) -> object:
    """The one value a column carries across every row; anything else is not one week."""

    if bool(table[column].isna().any()):
        raise DataValidationError(f"{column} is missing on some rows; the table is not one week.")
    values = table[column].drop_duplicates().tolist()
    if len(values) != 1:
        raise DataValidationError(
            f"{column} must carry exactly one value across the table, got {len(values)}."
        )
    return values[0]


def _string_list(manifest: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = manifest.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise DataValidationError(f"Manifest {key!r} must be a list of non-empty strings.")
    return tuple(str(item) for item in value)


def _whole_number(manifest: Mapping[str, object], key: str) -> int:
    value = manifest.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataValidationError(
            f"Manifest {key!r} must be a non-negative integer, got {value!r}."
        )
    return value


def _row_sources(table: pd.DataFrame) -> tuple[str, ...]:
    identifiers: set[str] = set()
    for value in table["source_snapshot_ids"].tolist():
        identifiers.update(part for part in str(value).split(";") if part)
    return tuple(sorted(identifiers))


def _validate_manifest_and_table(
    manifest: Mapping[str, object], table: pd.DataFrame, table_path: Path
) -> None:
    if manifest.get("contract_version") != CONTRACT_VERSION:
        raise DataValidationError(
            f"{table_path.name} declares contract {manifest.get('contract_version')!r}, not "
            f"{CONTRACT_VERSION!r}."
        )
    if manifest.get("artifact_contract_version") != ARTIFACT_CONTRACT_VERSION:
        raise DataValidationError(
            f"{table_path.name} declares export contract "
            f"{manifest.get('artifact_contract_version')!r}, not "
            f"{ARTIFACT_CONTRACT_VERSION!r}."
        )
    if manifest.get("table_file") != table_path.name:
        raise DataValidationError(
            f"The manifest names table {manifest.get('table_file')!r} but was read beside "
            f"{table_path.name!r}."
        )
    if tuple(table.columns) != ROTATION_EVIDENCE_COLUMNS:
        raise DataValidationError(
            f"{table_path.name} columns do not match {CONTRACT_VERSION} in its declared order."
        )
    forbidden = sorted(set(table.columns) & FORBIDDEN_COLUMNS)
    if forbidden:
        raise DataValidationError(f"{table_path.name} carries forbidden column(s) {forbidden!r}.")
    if table.empty:
        raise DataValidationError(f"{table_path.name} carries no rows.")

    row_count = _whole_number(manifest, "row_count")
    if len(table) != row_count:
        raise DataValidationError(
            f"{table_path.name} holds {len(table)} rows and its manifest declares {row_count}."
        )
    # The completeness identity, and the honest replacement for an arithmetic one. There is
    # no total a model's coverage sums to, so what is checked instead is that every roster
    # player got a row: a table with a player missing would look complete otherwise.
    roster_size = _whole_number(manifest, "roster_size")
    if row_count != roster_size:
        raise DataValidationError(
            f"{table_path.name} declares {row_count} rows for a roster of {roster_size}; "
            "the contract is one row per roster player, always."
        )
    if not bool(table["player_id"].is_unique):
        raise DataValidationError(f"{table_path.name} repeats a player_id.")
    if not bool(table["player_id"].is_monotonic_increasing):
        raise DataValidationError(f"{table_path.name} rows must be sorted by player_id.")

    for column, field in _COLUMN_TO_MANIFEST.items():
        observed = _single_value(table, column)
        declared = manifest.get(field)
        if str(observed) != str(declared):
            raise DataValidationError(
                f"{table_path.name} column {column!r} carries {observed!r} while the manifest "
                f"declares {field!r} as {declared!r}."
            )

    for column in _NEVER_MISSING_FLAGS:
        if bool(table[column].isna().any()):
            raise DataValidationError(
                f"{table_path.name} column {column!r} is missing on some rows. It separates "
                "'did not happen' from 'not observed', so a missing value would collapse the "
                "very distinction it exists to keep."
            )
    if not bool(table["timing_verified"].astype("boolean").all()):
        raise DataValidationError(
            f"{table_path.name} carries rows whose sources are not all earlier than the "
            "deadline they were built for."
        )

    captured = pd.to_datetime(table["captured_at_utc"], utc=True, errors="raise")
    deadlines = pd.to_datetime(table["deadline_timestamp_utc"], utc=True, errors="raise")
    if not bool((captured < deadlines).all()):
        raise DataValidationError(
            "Every rotation capture must be strictly earlier than its decision deadline."
        )

    observed_claims = table["rotation_claim_observed"].astype("boolean")
    for column in _CLAIM_ONLY_COLUMNS:
        present = table[column].notna()
        if not bool((present == observed_claims).all()):
            raise DataValidationError(
                f"{table_path.name} column {column!r} disagrees with "
                "rotation_claim_observed. It carries a value exactly where a claim was "
                "observed and nothing where none was."
            )

    for column, allowed in (
        ("rotation_disposition", ROTATION_DISPOSITIONS),
        ("rotation_claim_published_precision", PUBLISHED_PRECISIONS),
        ("rotation_claim_speaker", CLAIM_SPEAKERS),
        ("feed_news_state", FEED_NEWS_STATES),
    ):
        unknown = sorted({str(value) for value in table[column].dropna().tolist()} - set(allowed))
        if unknown:
            raise DataValidationError(
                f"{table_path.name} column {column!r} carries {unknown!r}, outside its closed "
                f"vocabulary {list(allowed)!r}."
            )

    declared_sources = _string_list(manifest, "source_snapshot_ids")
    if tuple(sorted(declared_sources)) != _row_sources(table):
        raise DataValidationError(
            f"{table_path.name} rows were read from {_row_sources(table)!r} while its manifest "
            f"declares {declared_sources!r}. Provenance is per row here, so the manifest "
            "carries the union of what the rows actually used."
        )
    roster_snapshot = manifest.get("roster_snapshot_id")
    if not isinstance(roster_snapshot, str) or roster_snapshot not in declared_sources:
        raise DataValidationError(
            f"Manifest roster_snapshot_id {roster_snapshot!r} is not among the declared "
            "source snapshots; the roster has to have come from one of them."
        )
    covered = set(_string_list(manifest, "clubs_covered"))
    declared_clubs = set(_string_list(manifest, "clubs_declared"))
    if not covered <= declared_clubs:
        raise DataValidationError(
            f"Manifest clubs_covered {sorted(covered - declared_clubs)!r} were never declared; "
            "coverage cannot exceed what the week set out to read."
        )
    for key in ("documents_read", "claims_coded", "claims_ambiguous", "players_not_addressed"):
        _whole_number(manifest, key)
    _string_list(manifest, "document_sha256s")


def read_rotation_evidence_artifact(table_path: Path, manifest_path: Path) -> pd.DataFrame:
    """Return a contract-checked rotation evidence table with its dtypes restored.

    A checksum, schema, timing, vocabulary or manifest disagreement rejects the pair.
    Ordinary missing evidence stays ``pd.NA``: this reader refuses a table that is wrong, not
    one that honestly records having observed nothing.
    """

    manifest = _read_manifest(manifest_path)
    try:
        table_bytes = table_path.read_bytes()
    except OSError as error:
        raise DataSourceError(f"Cannot read the table at {table_path}: {error}") from error
    digest = hashlib.sha256(table_bytes).hexdigest()
    if digest != manifest.get("table_sha256"):
        raise DataValidationError(
            f"{table_path.name} hashes to {digest} and its manifest declares "
            f"{manifest.get('table_sha256')!r}. The bytes are not the bytes that were "
            "published, so they are refused before they are parsed."
        )
    try:
        table = pd.read_csv(table_path, dtype=dict(_ROTATION_EVIDENCE_DTYPES))
    except (ValueError, pd.errors.ParserError) as error:
        raise DataValidationError(f"{table_path.name} could not be read: {error}") from error

    _validate_manifest_and_table(manifest, table, table_path)

    # Every list here becomes a **tuple**. Phase B's consumer compares one of its own against
    # ``()`` to decide whether an artifact is fit for operational use, and a list would never
    # equal an empty tuple however empty it was; the same discipline is kept so a downstream
    # identity comparison cannot silently fail.
    table.attrs.update(
        {
            "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
            "generated_at_utc": manifest["generated_at_utc"],
            "repository_commit": manifest["repository_commit"],
            "table_sha256": manifest["table_sha256"],
            "roster_size": manifest["roster_size"],
            "roster_snapshot_id": manifest["roster_snapshot_id"],
            "source_snapshot_ids": _string_list(manifest, "source_snapshot_ids"),
            "clubs_declared": _string_list(manifest, "clubs_declared"),
            "clubs_covered": _string_list(manifest, "clubs_covered"),
            "documents_read": manifest["documents_read"],
            "document_sha256s": _string_list(manifest, "document_sha256s"),
            "model_identifier": manifest["model_identifier"],
            "model_version": manifest["model_version"],
            "prompt_sha256": manifest["prompt_sha256"],
            "response_sha256s": _string_list(manifest, "response_sha256s"),
            "claims_coded": manifest["claims_coded"],
            "claims_ambiguous": manifest["claims_ambiguous"],
            "players_not_addressed": manifest["players_not_addressed"],
        }
    )
    return table


__all__ = [
    "ARTIFACT_CONTRACT_VERSION",
    "REQUIRED_MANIFEST_FIELDS",
    "read_rotation_evidence_artifact",
]
