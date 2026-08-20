"""Can a Gaussian process price the end of the season better than four constants?

Every rolling-horizon planner here strips value at its edge: week six of a five-week plan
is priced at zero, so the planner happily sells the future. The chip holding values patch
the worst of it — four constants, measured at +97..114 a season — but the rest of the
squad state carries no terminal value at all. This module runs the pre-registered first
test (`docs/terminal_value_prereg.md`): from the committed season-chain artifacts, one row
per applied decision week, predict the net points still to come from the state after the
decision, and beat the constants-plus-average baseline the planner already implies —
held out season by season, or record the negative and keep the constants.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor  # type: ignore[import-untyped]
from sklearn.gaussian_process.kernels import (  # type: ignore[import-untyped]
    RBF,
    ConstantKernel,
    WhiteKernel,
)

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError

TERMINAL_VALUE_STUDY_CONTRACT_VERSION: Final = "terminal_value_gp_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

CHIP_NAMES: Final = ("bboost", "3xc", "wildcard", "freehit")
#: Which chips each recorded variant actually offers when its chains enable chips.
#: Measured from the artifacts themselves (the union of chips ever played per directory),
#: not assumed: the freehit exists only in the two variants that model it. Using a
#: directory-level constant keeps the "still in hand" feature free of future information —
#: reading a chain's own chips_played to decide what was available would leak the ending.
CHIPS_OFFERED: Final[Mapping[str, tuple[str, ...]]] = {
    "season_chain": ("bboost", "3xc", "wildcard"),
    "season_chain_blind": ("bboost", "3xc", "wildcard"),
    "season_chain_fh": ("bboost", "3xc", "wildcard", "freehit"),
    "season_chain_hybrid": ("bboost", "3xc", "wildcard"),
    "season_chain_value": ("bboost", "3xc", "wildcard"),
    "chain_tuned": ("bboost", "3xc", "wildcard", "freehit"),
}
#: The season-chain value-mode holding constants, fixed in the pre-registration.
HOLDING_VALUE_POINTS: Final[Mapping[str, float]] = {
    "bboost": 20.0,
    "3xc": 18.0,
    "wildcard": 12.0,
    "freehit": 20.0,
}
FEATURE_COLUMNS: Final = (
    "remaining_weeks",
    "bank_tenths",
    "squad_sell_value_tenths",
    "free_transfers",
    "has_bboost",
    "has_3xc",
    "has_wildcard",
    "has_freehit",
)
TARGET_COLUMN: Final = "remaining_net_points"


@dataclass(frozen=True, slots=True)
class TerminalValueConfig:
    """Where the chains are read from, and the deterministic fitting knobs."""

    chain_directories: tuple[str, ...] = (
        "season_chain",
        "season_chain_blind",
        "season_chain_fh",
        "season_chain_hybrid",
        "season_chain_value",
        "chain_tuned",
    )
    seasons: tuple[str, ...] = ("2021-22", "2022-23", "2023-24", "2024-25")
    deterministic_seed: int = 0
    max_rows_per_fit: int = 4000

    def __post_init__(self) -> None:
        if LOCKED_HOLDOUT_SEASON in self.seasons:
            raise ExperimentConfigurationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read."
            )
        if len(self.seasons) < 2:
            raise ExperimentConfigurationError("Leave-one-season-out needs at least two seasons.")


@dataclass(frozen=True, slots=True)
class SeasonScore:
    season: str
    rows: int
    gp_mean_absolute_error: float
    baseline_mean_absolute_error: float

    @property
    def improvement(self) -> float:
        """Positive when the GP is closer than the baseline."""

        return self.baseline_mean_absolute_error - self.gp_mean_absolute_error


@dataclass(frozen=True, slots=True)
class TerminalValueStudy:
    contract_version: str
    config: TerminalValueConfig
    rows: int
    seasons: tuple[SeasonScore, ...]
    pooled_gp_mae: float
    pooled_baseline_mae: float
    by_phase: Mapping[str, Mapping[str, float]]
    kernel: str
    verdict: Mapping[str, object]
    diagnostics: Mapping[str, object]


# --- rows from the committed chains ---------------------------------------------


def load_state_rows(
    artifact_root: Path | str, config: TerminalValueConfig | None = None
) -> pd.DataFrame:
    """One row per applied decision week of every recorded chain.

    The state is *after* the decision (bank, sell value, transfers, chips left), and the
    target is the realized net still to come — next week through the season's end — read
    from the same chain, so state and target can never mix chains or seasons.
    """

    settings = TerminalValueConfig() if config is None else config
    root = Path(artifact_root)
    records: list[dict[str, object]] = []
    chains_read = 0
    for directory in settings.chain_directories:
        for season in settings.seasons:
            path = root / directory / f"{season}.json"
            if not path.is_file():
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            for index, chain in enumerate(document.get("chains", [])):
                weeks = chain.get("weeks", [])
                if not weeks:
                    continue
                chains_read += 1
                offered = CHIPS_OFFERED.get(directory, ())
                enabled = set(offered) if bool(chain.get("chips_enabled")) else set()
                nets = [float(week["net_points"]) for week in weeks]
                played_before: set[str] = set()
                for position, week in enumerate(weeks):
                    remaining = float(sum(nets[position + 1 :]))
                    chip = week.get("chip")
                    if chip:
                        played_before.add(str(chip))
                    remaining_weeks = len(weeks) - position - 1
                    if remaining_weeks == 0:
                        continue  # the final week has no future to price
                    row: dict[str, object] = {
                        "source": f"{directory}/{season}#chain{index}",
                        "season": season,
                        "gameweek": int(week["gameweek"]),
                        "remaining_weeks": remaining_weeks,
                        "bank_tenths": float(week["bank_after_tenths"]),
                        "squad_sell_value_tenths": float(week["squad_sell_value_tenths"]),
                        "free_transfers": float(week["free_transfers_after"]),
                        TARGET_COLUMN: remaining,
                    }
                    for name in CHIP_NAMES:
                        row[f"has_{name}"] = float(name in enabled and name not in played_before)
                    records.append(row)
    if not records:
        raise ExperimentExecutionError(
            f"No chain artifact under {root} held any weeks for {settings.seasons!r}."
        )
    frame = pd.DataFrame.from_records(records)
    frame.attrs["chains_read"] = chains_read
    return frame.sort_values(["season", "source", "gameweek"], kind="stable").reset_index(drop=True)


# --- the two predictors ----------------------------------------------------------


def baseline_prediction(rows: pd.DataFrame, training: pd.DataFrame) -> np.ndarray:
    """What the planner already implies: average weeks ahead, plus chips in hand."""

    weekly = float((training[TARGET_COLUMN] / training["remaining_weeks"]).mean())
    values = rows["remaining_weeks"].to_numpy(dtype="float64") * weekly
    for name in CHIP_NAMES:
        values = values + rows[f"has_{name}"].to_numpy(dtype="float64") * float(
            HOLDING_VALUE_POINTS[name]
        )
    return values


def fit_and_predict_gp(
    training: pd.DataFrame, held_out: pd.DataFrame, config: TerminalValueConfig
) -> tuple[np.ndarray, str]:
    """Standardised GP with the pre-registered kernel; returns predictions and the kernel."""

    fitted = training
    if len(fitted) > config.max_rows_per_fit:
        fitted = fitted.sample(n=config.max_rows_per_fit, random_state=config.deterministic_seed)
    matrix = fitted.loc[:, list(FEATURE_COLUMNS)].to_numpy(dtype="float64")
    target = fitted[TARGET_COLUMN].to_numpy(dtype="float64")
    centre = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale == 0.0] = 1.0
    kernel = ConstantKernel(1.0) * RBF(length_scale=np.ones(matrix.shape[1])) + WhiteKernel(
        noise_level=1.0
    )
    model = GaussianProcessRegressor(
        kernel=kernel,
        normalize_y=True,
        random_state=config.deterministic_seed,
        n_restarts_optimizer=1,
    )
    model.fit((matrix - centre) / scale, target)
    held_matrix = (
        held_out.loc[:, list(FEATURE_COLUMNS)].to_numpy(dtype="float64") - centre
    ) / scale
    predictions = np.asarray(model.predict(held_matrix), dtype="float64")
    return predictions, str(model.kernel_)


# --- the study -------------------------------------------------------------------


def run_terminal_value_study(
    artifact_root: Path | str, config: TerminalValueConfig | None = None
) -> TerminalValueStudy:
    """Leave one season out at a time; the gate is applied by code."""

    settings = TerminalValueConfig() if config is None else config
    rows = load_state_rows(artifact_root, settings)
    seasons: list[SeasonScore] = []
    gp_errors: list[np.ndarray] = []
    baseline_errors: list[np.ndarray] = []
    phase_records: list[pd.DataFrame] = []
    kernel_description = ""
    for season in settings.seasons:
        held_out = rows.loc[rows["season"] == season]
        training = rows.loc[rows["season"] != season]
        if held_out.empty or training.empty:
            continue
        gp_predictions, kernel_description = fit_and_predict_gp(training, held_out, settings)
        base_predictions = baseline_prediction(held_out, training)
        actual = held_out[TARGET_COLUMN].to_numpy(dtype="float64")
        gp_error = np.abs(actual - gp_predictions)
        base_error = np.abs(actual - base_predictions)
        seasons.append(
            SeasonScore(
                season=season,
                rows=len(held_out),
                gp_mean_absolute_error=float(gp_error.mean()),
                baseline_mean_absolute_error=float(base_error.mean()),
            )
        )
        gp_errors.append(gp_error)
        baseline_errors.append(base_error)
        phase = held_out.loc[:, ["remaining_weeks"]].copy()
        phase["gp_error"] = gp_error
        phase["baseline_error"] = base_error
        phase_records.append(phase)
    if not seasons:
        raise ExperimentExecutionError("No season could be scored.")
    pooled_gp = float(np.concatenate(gp_errors).mean())
    pooled_baseline = float(np.concatenate(baseline_errors).mean())
    phases = pd.concat(phase_records, ignore_index=True)
    bands = {
        "early_25_plus_weeks_left": phases["remaining_weeks"] >= 25,
        "mid_10_to_24_weeks_left": (phases["remaining_weeks"] >= 10)
        & (phases["remaining_weeks"] < 25),
        "late_under_10_weeks_left": phases["remaining_weeks"] < 10,
    }
    by_phase = {
        label: {
            "rows": int(mask.sum()),
            "gp_mae": float(phases.loc[mask, "gp_error"].mean()) if mask.any() else 0.0,
            "baseline_mae": (
                float(phases.loc[mask, "baseline_error"].mean()) if mask.any() else 0.0
            ),
        }
        for label, mask in bands.items()
    }
    better_seasons = sum(1 for score in seasons if score.improvement > 0.0)
    verdict = {
        "pooled_improvement": pooled_baseline - pooled_gp,
        "seasons_better": better_seasons,
        "seasons_total": len(seasons),
        "passes": bool(pooled_gp < pooled_baseline and better_seasons >= min(3, len(seasons))),
    }
    return TerminalValueStudy(
        contract_version=TERMINAL_VALUE_STUDY_CONTRACT_VERSION,
        config=settings,
        rows=len(rows),
        seasons=tuple(seasons),
        pooled_gp_mae=pooled_gp,
        pooled_baseline_mae=pooled_baseline,
        by_phase=by_phase,
        kernel=kernel_description,
        verdict=verdict,
        diagnostics={
            "chains_read": int(rows.attrs.get("chains_read", 0)),
            "chain_directories": list(settings.chain_directories),
            "holding_value_points": dict(HOLDING_VALUE_POINTS),
            "feature_columns": list(FEATURE_COLUMNS),
            "locked_holdout_accessed": False,
            "promotion_available": False,
            "promotion_note": (
                "Nothing consumes the fitted value. A passing gate earns the next step - "
                "a terminal-value term in the planner's objective, measured against the "
                "holding-value control on the season chain - under its own declaration."
            ),
        },
    )


def study_to_markdown(study: TerminalValueStudy) -> str:
    """The artifact a reader can check without running anything."""

    lines = [
        "# A Gaussian process against four constants: pricing the rest of the season",
        "",
        f"- Contract `{study.contract_version}`; {study.rows} state rows from "
        f"{study.diagnostics.get('chains_read')} recorded chains across "
        f"{len(study.config.chain_directories)} chip-mode variants; leave-one-season-out "
        f"over {', '.join(study.config.seasons)}.",
        "- Target: net points from the next week to the season's end. Baseline: remaining "
        "weeks x the training seasons' mean weekly net, plus the holding values of chips "
        "still in hand (bboost 20, 3xc 18, wildcard 12, freehit 20). Gate declared in "
        "`terminal_value_prereg.md` before anything was fitted.",
        f"- Fitted kernel (last fold): `{study.kernel}`.",
        "",
        "| Season | Rows | GP MAE | Baseline MAE | Improvement |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for score in study.seasons:
        lines.append(
            f"| {score.season} | {score.rows} | {score.gp_mean_absolute_error:.2f} "
            f"| {score.baseline_mean_absolute_error:.2f} | {score.improvement:+.2f} |"
        )
    lines += [
        f"| **pooled** | {study.rows} | **{study.pooled_gp_mae:.2f}** "
        f"| **{study.pooled_baseline_mae:.2f}** "
        f"| **{study.pooled_baseline_mae - study.pooled_gp_mae:+.2f}** |",
        "",
        "## By phase of the season (reported, not gated)",
        "",
        "| Band | Rows | GP MAE | Baseline MAE |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, values in study.by_phase.items():
        lines.append(
            f"| {label} | {values['rows']:.0f} | {values['gp_mae']:.2f} "
            f"| {values['baseline_mae']:.2f} |"
        )
    verdict = study.verdict
    lines += [
        "",
        "## Verdict",
        "",
        f"- Pooled improvement: {float(str(verdict['pooled_improvement'])):+.2f} MAE; better "
        f"in {verdict['seasons_better']} of {verdict['seasons_total']} seasons.",
        (
            "**The gate passes**: the state carries more than the four constants, which "
            "earns the next step — a terminal-value term in the planner's objective, "
            "measured on the season chain under its own declaration. Nothing is promoted "
            "by this result."
            if verdict["passes"]
            else "**The gate fails**: the holding-value constants are not improved upon by "
            "this state representation. The constants stand, and the negative is recorded."
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CHIPS_OFFERED",
    "CHIP_NAMES",
    "FEATURE_COLUMNS",
    "HOLDING_VALUE_POINTS",
    "TERMINAL_VALUE_STUDY_CONTRACT_VERSION",
    "SeasonScore",
    "TerminalValueConfig",
    "TerminalValueStudy",
    "baseline_prediction",
    "fit_and_predict_gp",
    "load_state_rows",
    "run_terminal_value_study",
    "study_to_markdown",
]
