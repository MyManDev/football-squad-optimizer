"""Public contracts for pre-run validation of residual-export handoff artifacts.

A preflight run inspects an artifact before any measurement consumes it. It never
repairs, reinterprets, or silently drops data: every deviation from the declared
contract becomes a named finding, and a single failed finding blocks the handoff.
"""

import re
from dataclasses import dataclass
from typing import Final

from squadopt.data.errors import DataError

PREFLIGHT_CONTRACT_VERSION: Final = "artifact_preflight_v1"
RESIDUAL_EXPORT_CONTRACT_VERSION: Final = "oos_residual_export_v1"

RESIDUAL_EXPORT_COLUMNS: Final = (
    "fold_id",
    "season",
    "gameweek",
    "player_id",
    "team_id",
    "position",
    "predicted_points",
    "realized_points",
    "residual",
)

MANIFEST_REQUIRED_FIELDS: Final = (
    "contract_version",
    "candidate_label",
    "model_name",
    "model_version",
    "feature_contract_version",
    "training_contract_version",
    "evaluation_objective",
    "development_seasons",
    "opening_gameweeks_included",
    "fold_count",
    "row_count",
    "repository_commit",
    "dataset_snapshot_id",
    "table_sha256",
    "created_at_utc",
)

MANIFEST_IDENTITY_FIELDS: Final = (
    "candidate_label",
    "model_name",
    "model_version",
    "feature_contract_version",
    "training_contract_version",
    "evaluation_objective",
    "dataset_snapshot_id",
)

ALLOWED_POSITIONS: Final = frozenset({"GK", "DEF", "MID", "FWD"})

COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")

# Residual identity is checked as an equation, not an equality of floats: exports round
# through CSV, so an exact match would reject byte-identical re-reads of a valid file.
RESIDUAL_IDENTITY_TOLERANCE: Final = 1e-6
REALIZED_POINTS_TOLERANCE: Final = 1e-9


class PreflightError(DataError):
    """Raised when preflight inputs cannot be examined at all.

    Distinct from a failed finding: a finding records that an artifact violates its
    contract, while this error records that no examination could take place (missing
    file, non-mapping manifest, non-DataFrame table).
    """


@dataclass(frozen=True, slots=True)
class PreflightFinding:
    """One named check outcome with a human-readable explanation."""

    check: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        for name in ("check", "detail"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise PreflightError(f"{name} must be non-empty text.")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.passed, bool):
            raise PreflightError("passed must be a boolean.")


@dataclass(frozen=True, slots=True)
class PreflightExpectations:
    """Externally known facts an artifact must additionally satisfy.

    These express what the receiving side already knows (for example the agreed
    development population of 147 folds and 101447 rows) so that a manifest cannot
    quietly redefine the population it claims to cover. Every field is optional;
    ``None`` means no external expectation is asserted.
    """

    fold_count: int | None = None
    row_count: int | None = None
    development_seasons: tuple[str, ...] | None = None
    evaluation_objective: str | None = None
    repository_commit: str | None = None
    dataset_snapshot_id: str | None = None
    opening_gameweeks_included: bool | None = None

    def __post_init__(self) -> None:
        for name in ("fold_count", "row_count"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PreflightError(f"{name} must be a positive integer or None.")
        for name in ("evaluation_objective", "repository_commit", "dataset_snapshot_id"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise PreflightError(f"{name} must be non-empty text or None.")
            object.__setattr__(self, name, value.strip())
        seasons = self.development_seasons
        if seasons is not None:
            if not isinstance(seasons, tuple) or not seasons:
                raise PreflightError("development_seasons must be a non-empty tuple or None.")
            normalized = tuple(
                season.strip() if isinstance(season, str) else "" for season in seasons
            )
            if any(not season for season in normalized):
                raise PreflightError("development_seasons entries must be non-empty text.")
            if len(set(normalized)) != len(normalized):
                raise PreflightError("development_seasons entries must be unique.")
            object.__setattr__(self, "development_seasons", tuple(sorted(normalized)))
        flag = self.opening_gameweeks_included
        if flag is not None and not isinstance(flag, bool):
            raise PreflightError("opening_gameweeks_included must be a boolean or None.")


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Every finding for one artifact or artifact pair, failures included.

    The report never hides a passed check: an accepted handoff must show what was
    actually verified, and a rejected one must name every violated rule at once
    instead of failing one rule per round-trip.
    """

    artifact_label: str
    findings: tuple[PreflightFinding, ...]
    contract_version: str = PREFLIGHT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_label, str) or not self.artifact_label.strip():
            raise PreflightError("artifact_label must be non-empty text.")
        object.__setattr__(self, "artifact_label", self.artifact_label.strip())
        if self.contract_version != PREFLIGHT_CONTRACT_VERSION:
            raise PreflightError("contract_version does not match the implemented preflight.")
        if not isinstance(self.findings, tuple) or not self.findings:
            raise PreflightError("findings must be a non-empty tuple.")
        if any(not isinstance(finding, PreflightFinding) for finding in self.findings):
            raise PreflightError("findings must contain PreflightFinding values.")

    @property
    def passed(self) -> bool:
        """Return whether the artifact may enter a measurement run."""

        return all(finding.passed for finding in self.findings)

    @property
    def failures(self) -> tuple[PreflightFinding, ...]:
        """Return only the findings that block the handoff."""

        return tuple(finding for finding in self.findings if not finding.passed)
