"""How much precision a residual export must drop to survive crossing machines.

Two owners regenerated the candidate residual export at the same commit, from the same
dataset snapshot, and recorded different `table_sha256`. The content agreed to every
reported decimal; the bytes did not. The cause is `fit_learned_rate`, which solves a small
ridge system through LAPACK, and LAPACK is not bit-identical across machines. The control
export has no linear solve and reproduces exactly.

That leaves a question the acceptance record posed and did not answer: is rounding the
written values enough, and to how many decimals?

This measures it rather than assuming. For a range of relative perturbations — the size a
last-bit difference in a fitted coefficient could reach — it counts how many rows would
round to a different value. A precision survives if that count is zero at the perturbation
sizes double-precision arithmetic can actually produce.

The measurement is deliberately run against an existing export rather than against two
regenerated ones. Regenerating on one machine cannot show the effect at all: the same
machine is bit-identical with itself. Perturbing a real table shows what *would* happen,
at any magnitude, without needing the second machine present.

Rounding the values is necessary and it is not sufficient. Identical values still reach
disk as different bytes if the line terminator differs, because `DataFrame.to_csv` defaults
to `os.linesep` — so the same table writes `\r\n` on Windows and `\n` on Linux, and
`table_sha256` digests the raw file bytes. The two owners who compared hashes were both on
Windows, which is why the value half of the problem was the only half visible. Writing
through `write_export_table` fixes the terminator; the measurement above fixes the values.
Both halves are needed before a hash means "the same table" rather than "the same table on
the same operating system".
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from squadopt.backtest.splits import BacktestConfigurationError

EXPORT_PRECISION_CONTRACT_VERSION: Final = "export_precision_v1"

# The line terminator every export is written with, on every platform. Explicit because
# pandas defaults to os.linesep and a digest over the file bytes would otherwise identify
# the operating system as much as the table.
EXPORT_LINE_TERMINATOR: Final = "\n"

# Double precision carries about 2.2e-16 of relative resolution, so a last-bit difference
# in a coefficient reaches the output somewhere near 1e-16. The larger sizes are headroom:
# they say how far the answer would have to degrade before a precision stopped working.
DEFAULT_PERTURBATIONS: Final = (1e-16, 1e-15, 1e-14, 1e-12)

# Candidates for the written precision. Nine decimals is five orders below anything any
# report quotes, so it discards nothing a reader could notice.
DEFAULT_DECIMALS: Final = (12, 9, 6)


def write_export_table(table: pd.DataFrame, path: Path) -> None:
    """Write one export table in the bytes every machine agrees on.

    Every measurement table whose `table_sha256` is recorded goes through here, so the
    digest identifies the table and not the operating system that wrote it. The parent
    directory is created if it is missing, which lets a caller name an output path without
    preparing it first.

    Rounding the values is the caller's job and is measured by this module; the terminator
    is this function's job. A hash means "the same table" only when both are settled.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, lineterminator=EXPORT_LINE_TERMINATOR)


@dataclass(frozen=True, slots=True)
class PrecisionRow:
    """How many rows move, at one perturbation and one written precision."""

    relative_perturbation: float
    decimals: int | None
    changed_rows: int

    @property
    def survives(self) -> bool:
        """No row moves, so two machines write the same bytes."""

        return self.changed_rows == 0


@dataclass(frozen=True, slots=True)
class ExportPrecisionResult:
    """The measurement, and the population it was measured on."""

    contract_version: str
    column: str
    observations: int
    non_zero_observations: int
    rows: tuple[PrecisionRow, ...]

    def recommended_decimals(self, *, perturbation: float) -> int | None:
        """The coarsest precision that survives a perturbation of the given size.

        Coarsest rather than finest: every precision below the survivor also survives,
        and quoting the finest would imply the margin is thinner than it is.
        """

        surviving = [
            row.decimals
            for row in self.rows
            if row.decimals is not None
            and row.survives
            and row.relative_perturbation >= perturbation
        ]
        return max(surviving) if surviving else None


def _changed_rows(values: np.ndarray, relative: float, decimals: int | None) -> int:
    """Count values whose written form differs when perturbed either way.

    The perturbation is applied in both directions because a difference between two
    machines has no sign: what matters is whether the interval the true value could
    occupy straddles a boundary in the written representation.
    """

    magnitude = np.abs(values) * relative
    low = values - magnitude
    high = values + magnitude
    if decimals is None:
        return int((low != high).sum())
    return int((np.round(low, decimals) != np.round(high, decimals)).sum())


def measure_export_precision(
    table: pd.DataFrame,
    *,
    column: str = "predicted_points",
    perturbations: Sequence[float] = DEFAULT_PERTURBATIONS,
    decimals: Sequence[int] = DEFAULT_DECIMALS,
) -> ExportPrecisionResult:
    """Count how many rows move at each perturbation and written precision."""

    if not isinstance(table, pd.DataFrame):
        raise BacktestConfigurationError("table must be a pandas DataFrame.")
    if column not in table.columns:
        raise BacktestConfigurationError(f"table has no column {column!r}.")
    if not perturbations or not decimals:
        raise BacktestConfigurationError("perturbations and decimals must be non-empty.")
    for value in perturbations:
        if not math.isfinite(value) or value <= 0.0:
            raise BacktestConfigurationError("perturbations must be finite and positive.")
    for value in decimals:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BacktestConfigurationError("decimals must be non-negative integers.")

    values = pd.to_numeric(table[column], errors="coerce").to_numpy(dtype="float64")
    if not bool(np.isfinite(values).all()):
        raise BacktestConfigurationError(f"{column!r} must be finite everywhere.")

    rows: list[PrecisionRow] = []
    for relative in perturbations:
        # `None` is the unrounded case: what the export writes today.
        for written in (None, *sorted(decimals, reverse=True)):
            rows.append(
                PrecisionRow(
                    relative_perturbation=float(relative),
                    decimals=written,
                    changed_rows=_changed_rows(values, float(relative), written),
                )
            )

    return ExportPrecisionResult(
        contract_version=EXPORT_PRECISION_CONTRACT_VERSION,
        column=column,
        observations=len(values),
        non_zero_observations=int((values != 0.0).sum()),
        rows=tuple(rows),
    )


def precision_to_dict(result: ExportPrecisionResult) -> dict[str, object]:
    """Render the measurement as a serialisable document."""

    return {
        "artifact_type": "export_precision",
        "contract_version": result.contract_version,
        "column": result.column,
        "observations": result.observations,
        "non_zero_observations": result.non_zero_observations,
        "recommended_decimals_at_1e-15": result.recommended_decimals(perturbation=1e-15),
        "rows": [
            {
                "relative_perturbation": row.relative_perturbation,
                "decimals": row.decimals,
                "changed_rows": row.changed_rows,
                "survives": row.survives,
            }
            for row in result.rows
        ],
        "gate_evidence": False,
    }


def precision_to_markdown(result: ExportPrecisionResult) -> str:
    """Render the measurement as a report."""

    written = sorted(
        {row.decimals for row in result.rows if row.decimals is not None}, reverse=True
    )
    header = " | ".join(f"{value} dp" for value in written)
    lines = [
        "# Export Precision",
        "",
        f"- Contract: `{result.contract_version}`",
        f"- Column: `{result.column}`",
        f"- Population: {result.observations:,} rows, {result.non_zero_observations:,} non-zero",
        "",
        "Rows whose written value changes when the underlying number is perturbed by the "
        "given relative amount. Zero means two machines write the same bytes.",
        "",
        f"| Relative perturbation | unrounded | {header} |",
        "| ---: | ---: | " + " | ".join("---:" for _ in written) + " |",
    ]
    for perturbation in sorted({row.relative_perturbation for row in result.rows}):
        cells: list[str] = []
        for decimals in (None, *written):
            match = next(
                row
                for row in result.rows
                if row.relative_perturbation == perturbation and row.decimals == decimals
            )
            cells.append(f"{match.changed_rows:,}")
        lines.append(f"| {perturbation:.0e} | " + " | ".join(cells) + " |")

    recommended = result.recommended_decimals(perturbation=1e-15)
    lines += [
        "",
        "## Reading",
        "",
        "Double precision carries about 2.2e-16 of relative resolution, so a last-bit "
        "difference in a fitted coefficient reaches the output near 1e-16. The larger "
        "perturbations are headroom, not predictions: they say how far the arithmetic "
        "would have to degrade before a written precision stopped working.",
        "",
        (
            f"**{recommended} decimal places survives a 1e-15 perturbation with no row moving.**"
            if recommended is not None
            else "**No tested precision survives a 1e-15 perturbation.**"
        ),
        "",
        "Unrounded, every non-zero row moves. That is not bad luck — it is what a "
        "sixteen-significant-digit serialisation of a LAPACK result does when it crosses "
        "machines, and it is why two owners recorded different table hashes for the same "
        "export at the same commit.",
    ]
    return "\n".join(lines) + "\n"
