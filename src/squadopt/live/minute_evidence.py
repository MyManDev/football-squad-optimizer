"""Draft consumer for PR912 components; no fitting, fetches, or publication.

Only a source-verified, fixture-scoped exclusion of a full match is supported.
The intervention preserves P(appearance) and reallocates full-match mass to the
learned positive sub-90 classes in their original proportions. This is an explicit
model intervention, not a calibrated likelihood inferred from a coach's language.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import TypedDict, cast

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.stats import nbinom

from squadopt.live.football_artifact import ARTIFACT_CONTRACT, forecast_digest
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSIONS,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)
from squadopt.prediction.football_components import role_component_record
from squadopt.prediction.football_minutes_role import (
    RETAINED_HISTORY_ROLE_FEATURE_VERSION,
    ROLE_COMPONENT_COLUMNS,
    RoleMinuteDistribution,
)

# A JSON protocol boundary, not an import dependency on the unmerged producer.
# This reader names only the fields needed to prove and recompute its intervention.
FIXTURE_COMPONENTS_CONTRACT = "football_fixture_components_v1"
AVAILABILITY_SCOPE = "one_state_per_player_week"
IDENTITY_COLUMNS = (
    "GW",
    "fixture",
    "kickoff",
    "club",
    "opponent",
    "home",
    "player_code",
    "position",
)
COMPONENT_COLUMNS = (
    "expected_minutes",
    "appearance_probability",
    "p60",
    "team_goal_rate",
    "opponent_goal_rate",
    "goals",
    "goals_share",
    "assists",
    "assists_share",
    "clean_sheet_probability",
    "defcon_probability",
    "defcon_rate90",
    "defcon_dispersion",
    "residual_if_appearance",
    "raw_expected_points",
    "expected_points",
    *(f"minute_probability_{b}" for b in range(4)),
    *(f"minute_value_{b}" for b in range(4)),
)

INTERVENTION_VERSION = "explicit_full_match_exclusion_v1"
_ASSUMPTIONS = (
    "source_verified_explicit_full_match_exclusion",
    "appearance_probability_preserved",
    "full_match_mass_reallocated_over_learned_positive_sub90_support",
    "club_attack_rates_fixed_and_all_player_shares_renormalized",
    "captured_eligibility_shared_across_gameweek_fixtures_and_applied_once",
    "conditional_fixture_appearances_independent",
    "residual_per_appearance_held_fixed",
    "no_calibrated_soft_statement_probabilities",
)
_ID_FIELDS = (
    "season",
    "gameweek",
    "source_snapshot_id",
    "captured_at_utc",
    "source_fingerprint",
    "training_rows",
    "training_latest_kickoff",
    "archive_hashes",
)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f"{label} must be a positive integer.")
    return int(value)


def _close(actual: ArrayLike, expected: ArrayLike, label: str) -> None:
    if not np.allclose(actual, expected, rtol=1e-10, atol=1e-10):
        raise ValueError(f"Inconsistent component basis: {label}.")


class _AvailabilityMultiplier(TypedDict):
    player_code: int
    multiplier: float


class _CapturedAvailability(TypedDict):
    multipliers: list[_AvailabilityMultiplier]


def _availability_multipliers(companion: Mapping[str, object]) -> dict[int, float]:
    """Read the header already validated by FixtureComponentBasis.from_documents."""
    availability = cast(_CapturedAvailability, companion["captured_availability"])
    return {entry["player_code"]: entry["multiplier"] for entry in availability["multipliers"]}


def _canonical(document: Mapping[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class ExplicitMinuteEvidence:
    """The caller verifies source bytes, quote semantics, timing and deadline first.

    No generic disposition or source-generated probability is accepted. The span is
    provenance only: this pure layer neither fetches nor claims to reverify its bytes.
    Raw quotes never enter the output. Each fixture is explicit, including in a DGW.
    """

    evidence_id: str
    player_id: int
    gameweek: int
    fixture_ids: tuple[int, ...]
    restriction: str
    source_url: str
    source_sha256: str
    span_start: int
    span_end: int

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or self.restriction != "no_full_match":
            raise ValueError("Only identified explicit no_full_match evidence is supported.")
        _integer(self.player_id, "player_id")
        _integer(self.gameweek, "gameweek")
        if (
            not isinstance(self.fixture_ids, tuple)
            or not self.fixture_ids
            or len(set(self.fixture_ids)) != len(self.fixture_ids)
        ):
            raise ValueError("An explicit nonempty unique fixture scope is required.")
        for fixture in self.fixture_ids:
            _integer(fixture, "fixture_id")
        object.__setattr__(self, "player_id", int(self.player_id))
        object.__setattr__(self, "gameweek", int(self.gameweek))
        object.__setattr__(self, "fixture_ids", tuple(int(f) for f in self.fixture_ids))
        if not self.source_url.startswith(("https://", "http://")) or not re.fullmatch(
            r"[0-9a-f]{64}", self.source_sha256
        ):
            raise ValueError("A source URL and SHA256 are required.")
        if (
            isinstance(self.span_start, bool)
            or not isinstance(self.span_start, Integral)
            or isinstance(self.span_end, bool)
            or not isinstance(self.span_end, Integral)
            or not 0 <= self.span_start < self.span_end
        ):
            raise ValueError("A nonempty source byte span is required.")
        object.__setattr__(self, "span_start", int(self.span_start))
        object.__setattr__(self, "span_end", int(self.span_end))


def _joint_minutes(frame: pd.DataFrame) -> RoleMinuteDistribution | None:
    if not frame.attrs.get("joint_role", False):
        return None
    if frame.minute_role_status.nunique() != 1:
        raise ValueError("One fitted model must have one role-support status.")
    if frame.minute_role_status.iloc[0] != "fitted_known_start_labels":
        return None  # Explicit unknown-role fallback uses the retained four-bin law.
    p = np.column_stack(
        [
            frame.zero_probability.to_numpy(float),
            *(
                frame[f"{role}_minute_probability_{b}"].to_numpy(float)
                for role in ("start", "cameo")
                for b in (1, 2, 3)
            ),
        ]
    )
    m = np.column_stack(
        [
            np.zeros(len(frame)),
            *(
                frame[f"{role}_minute_value_{b}"].to_numpy(float)
                for role in ("start", "cameo")
                for b in (1, 2, 3)
            ),
        ]
    )
    return RoleMinuteDistribution(p, m, np.array([0, 1, 2, 3, 1, 2, 3]), True)


def _score_components(frame: pd.DataFrame) -> pd.DataFrame:
    """Recompute the v1 producer's deterministic component identities, without refitting."""
    out = frame.copy(deep=True)
    joint = _joint_minutes(out)
    if joint is None:
        p = out[[f"minute_probability_{b}" for b in range(4)]].to_numpy(float)
        m = out[[f"minute_value_{b}" for b in range(4)]].to_numpy(float)
        bins = np.arange(4)
    else:
        p, m, bins = joint.probabilities, joint.minutes, joint.bins
        marginal, means = joint.collapsed()
        for b in range(4):
            out[f"minute_probability_{b}"] = marginal[:, b]
            out[f"minute_value_{b}"] = means[:, b]
        out["start_probability"] = p[:, 1:4].sum(axis=1)
        out["cameo_probability"] = p[:, 4:7].sum(axis=1)
    out["expected_minutes"] = (p * m).sum(axis=1)
    out["appearance_probability"] = 1 - p[:, 0]
    out["p60"] = p[:, bins >= 2].sum(axis=1)
    if "minute_role_status" in out:
        out["expected_minutes_if_appearance"] = np.divide(
            out.expected_minutes.to_numpy(float),
            out.appearance_probability.to_numpy(float),
            out=np.zeros(len(out)),
            where=out.appearance_probability.to_numpy(float) > 0,
        )
    opponent = out.opponent_goal_rate.to_numpy(float)
    out["clean_sheet_probability"] = sum(
        p[:, b] * np.exp(-opponent * m[:, b] / 90) for b in np.flatnonzero(bins >= 2)
    )
    rate = out.defcon_rate90.to_numpy(float)
    size = out.defcon_dispersion.to_numpy(float)
    threshold = np.where(out.position.eq("DEF"), 10, 12)
    dc = np.zeros(len(out))
    for b in range(1, p.shape[1]):
        mu = np.maximum(rate * m[:, b] / 90, 1e-12)
        dc += p[:, b] * nbinom.sf(threshold - 1, size, size / (size + mu))
    dc[out.position.eq("GK").to_numpy()] = 0
    out["defcon_probability"] = dc
    season = str(out.attrs["season"])
    goal = out.position.map(
        {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
    ).to_numpy(float)
    clean = out.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy(float)
    raw = (
        out.appearance_probability
        + out.p60
        + goal * out.goals
        + 3 * out.assists
        + clean * out.clean_sheet_probability
        + out.appearance_probability * out.residual_if_appearance
    )
    if season >= "2025-26":
        raw = raw + 2 * dc
    out["raw_expected_points"] = raw
    out["expected_points"] = np.maximum(raw, 0)
    return out


def _validate_components(frame: pd.DataFrame, season: str, *, joint_role: bool = False) -> None:
    if not set(COMPONENT_COLUMNS) <= set(frame):
        raise ValueError("The companion is missing a required scoring component.")
    if joint_role:
        for record in frame.to_dict("records"):
            role_component_record({str(key): value for key, value in record.items()})
    frame.attrs["joint_role"] = joint_role
    if frame.duplicated(["fixture", "player_code"]).any():
        raise ValueError("Repeated player-fixture component rows.")
    if not frame.position.isin(("GK", "DEF", "MID", "FWD")).all():
        raise ValueError("Unknown player position in the component basis.")
    for value in frame.loc[:, list(COMPONENT_COLUMNS)].to_numpy(object).flat:
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise ValueError("Every scoring component must be a finite JSON number.")
    probabilities = [
        "appearance_probability",
        "p60",
        "goals_share",
        "assists_share",
        "clean_sheet_probability",
        "defcon_probability",
        *(f"minute_probability_{b}" for b in range(4)),
    ]
    unit = frame[probabilities].to_numpy(float)
    if ((unit < 0) | (unit > 1)).any():
        raise ValueError("A component probability lies outside [0, 1].")
    _close(
        frame[[f"minute_probability_{b}" for b in range(4)]].sum(axis=1),
        1.0,
        "minute probability sum",
    )
    nonnegative = [
        "expected_minutes",
        "team_goal_rate",
        "opponent_goal_rate",
        "goals",
        "assists",
        "defcon_rate90",
    ]
    if (frame[nonnegative].to_numpy(float) < 0).any() or frame.defcon_dispersion.le(0).any():
        raise ValueError("Component rates require nonnegative values and positive dispersion.")
    if not np.array_equal(
        frame.expected_points.to_numpy(float),
        np.maximum(frame.raw_expected_points.to_numpy(float), 0),
    ):
        raise ValueError("Expected points must equal clipped raw points.")
    for _, fixture in frame.groupby("fixture", sort=False):
        sides = {int(cast(int, club)): side for club, side in fixture.groupby("club", sort=False)}
        if len(sides) != 2 or {int(side.home.iloc[0]) for side in sides.values()} != {0, 1}:
            raise ValueError("A fixture requires two opposing home/away component sides.")
        for club, side in sides.items():
            opponent = next(key for key in sides if key != club)
            if not side.opponent.eq(opponent).all() or side.home.nunique() != 1:
                raise ValueError("Inconsistent opposing fixture identities.")
            _close(side.team_goal_rate, float(side.team_goal_rate.iloc[0]), "team intensity")
            _close(
                side.opponent_goal_rate,
                float(sides[opponent].team_goal_rate.iloc[0]),
                "opposing intensity",
            )
    means = frame[[f"minute_value_{b}" for b in range(4)]].to_numpy(float)
    if not (
        np.all(means[:, 0] == 0)
        and np.all((means[:, 1] > 0) & (means[:, 1] < 60))
        and np.all((means[:, 2] >= 60) & (means[:, 2] < 90))
        and np.all((means[:, 3] >= 90) & (means[:, 3] <= 120))
    ):
        raise ValueError("Minute representatives do not match the learned four-class support.")
    frame.attrs["season"] = season
    scored = _score_components(frame)
    for column in (
        "expected_minutes",
        "appearance_probability",
        "p60",
        "clean_sheet_probability",
        "defcon_probability",
        "raw_expected_points",
        "expected_points",
    ):
        _close(frame[column], scored[column], column)
    for _, side in frame.groupby(["GW", "fixture", "club"], sort=False):
        for head in ("goals", "assists"):
            share = side[head + "_share"].to_numpy(float)
            mass = float(side[head].sum())
            _close(share.sum(), float(side.expected_minutes.gt(0).any()), head + " share coverage")
            _close(side[head], mass * share, head + " allocation")
            if (share[side.expected_minutes.eq(0).to_numpy()] != 0).any():
                raise ValueError("A zero-minute row has a positive attacking share.")
        if float(side.goals.sum()) > float(side.team_goal_rate.iloc[0]) + 1e-10:
            raise ValueError("Credited goal mass exceeds the team's forecast.")
        if float(side.assists.sum()) > float(side.goals.sum()) + 1e-10:
            raise ValueError("Credited assist mass exceeds credited goals.")


def _weekly_from_fixture_rows(
    weekly: pd.DataFrame, rows: pd.DataFrame, multipliers: Mapping[int, float]
) -> pd.DataFrame:
    """Shared eligibility a times [1-product(1-q_fixture)], never product(1-a*q)."""
    out = weekly.copy(deep=True)
    lookup = {
        (int(cast(int, w)), int(cast(int, p))): group
        for (w, p), group in rows.groupby(["GW", "player_code"])
    }
    for index, row in out.iterrows():
        group = lookup.get((int(row.gameweek), int(row.player_id)))
        a = multipliers[int(row.player_id)]
        out.at[index, "expected_points"] = (
            0.0 if group is None else a * float(group.expected_points.sum())
        )
        out.at[index, "appearance_probability"] = (
            0.0
            if group is None
            else a * (1 - float((1 - group.appearance_probability.to_numpy(float)).prod()))
        )
    return out


@dataclass(frozen=True, slots=True)
class FixtureComponentBasis:
    """Canonical JSON prevents an upstream DataFrame mutation changing the retained basis."""

    _served_json: str
    _companion_json: str

    @classmethod
    def from_documents(
        cls,
        served: Mapping[str, object],
        companion: Mapping[str, object],
        *,
        fixture_calendar: pd.DataFrame,
        roster_clubs: Mapping[int, int],
    ) -> FixtureComponentBasis:
        for document in (served, companion):
            if document.get("fingerprint") != forecast_digest(dict(document)):
                raise ValueError("Fixture basis fingerprint mismatch.")
        if (
            served.get("contract_version") != ARTIFACT_CONTRACT
            or companion.get("contract_version") != FIXTURE_COMPONENTS_CONTRACT
            or served.get("model_version")
            not in (FOOTBALL_MODEL_VERSION, *JOINT_ROLE_MODEL_VERSIONS)
            or companion.get("model_version") != served.get("model_version")
        ):
            raise ValueError("Only the PR912 v1 fixture component contract is supported.")
        role_metadata = served.get("role_metadata")
        if served["model_version"] == JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION and (
            not isinstance(role_metadata, dict)
            or role_metadata.get("role_feature_version") != RETAINED_HISTORY_ROLE_FEATURE_VERSION
        ):
            raise ValueError(
                "Retained-history components require their explicit role feature identity."
            )
        if companion.get("forecast_fingerprint") != served["fingerprint"]:
            raise ValueError("Companion belongs to a different forecast.")
        if any(companion.get(key) != served.get(key) or key not in served for key in _ID_FIELDS):
            raise ValueError("Companion source, cutoff or training binding differs.")
        if companion.get("training_selection") != served.get("training_selection"):
            raise ValueError("Companion training selection differs from the served forecast.")
        if companion.get("role_metadata") != served.get("role_metadata"):
            raise ValueError("Companion role-minute metadata differs from the served forecast.")
        weekly = pd.DataFrame(cast(list[dict[str, object]], served["rows"]))
        required = {
            "gameweek",
            "player_id",
            "team_id",
            "position",
            "fixture_count",
            "home_fixture_count",
            "expected_points",
            "appearance_probability",
        }
        if (
            not required <= set(weekly)
            or weekly.empty
            or weekly.duplicated(["gameweek", "player_id"]).any()
        ):
            raise ValueError("The served player-week basis is incomplete or duplicated.")
        weeks = sorted(set(weekly.gameweek))
        if weeks != companion.get("gameweeks") or weeks[0] != served["gameweek"]:
            raise ValueError("Companion week coverage differs.")
        roster = weekly.loc[weekly.gameweek.eq(weeks[0])].set_index("player_id")
        players = set(roster.index)
        if set(roster_clubs) != players or any(
            set(g.player_id) != players for _, g in weekly.groupby("gameweek")
        ):
            raise ValueError("The full captured roster must cover every served week.")
        for player, club in roster_clubs.items():
            _integer(player, "roster player")
            _integer(club, "roster club")
        for col in ("team_id", "position"):
            if not (weekly[col].to_numpy() == weekly.player_id.map(roster[col]).to_numpy()).all():
                raise ValueError("Served player identity changes across the window.")
        availability = companion.get("captured_availability")
        if (
            not isinstance(availability, dict)
            or availability.get("application") != "not_applied"
            or availability.get("scope") != AVAILABILITY_SCOPE
        ):
            raise ValueError("Captured availability must be unapplied and shared per player-week.")
        entries = availability.get("multipliers")
        if not isinstance(entries, list):
            raise ValueError("Captured availability entries are missing.")
        multipliers = {}
        for entry in entries:
            player = _integer(entry["player_code"], "availability player")
            value = entry["multiplier"]
            if (
                player in multipliers
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError("Invalid or duplicate captured availability.")
            multipliers[player] = float(value)
        if set(multipliers) != players:
            raise ValueError("Captured availability does not cover the exact roster.")
        rows = pd.DataFrame(cast(list[dict[str, object]], companion["rows"]))
        calendar = fixture_calendar.loc[fixture_calendar.GW.isin(weeks)].copy()
        calendar_cols = ["GW", "fixture", "kickoff", "club", "opponent", "home"]
        if calendar.empty or calendar.duplicated(["fixture", "club"]).any() or rows.empty:
            raise ValueError("A nonempty unique source calendar and fixture basis are required.")
        for col in ("GW", "fixture", "club", "opponent"):
            for value in calendar[col]:
                _integer(value, "calendar " + col)
            for value in rows[col]:
                _integer(value, "component " + col)
        if not calendar.home.isin((0, 1)).all() or not rows.home.isin((0, 1)).all():
            raise ValueError("Invalid calendar home flag.")
        if any(pd.Timestamp(value).tzinfo is None for value in (*calendar.kickoff, *rows.kickoff)):
            raise ValueError("Fixture kickoff timestamps must be timezone aware.")
        for _, match in calendar.groupby("fixture"):
            if len(match) != 2 or match.GW.nunique() != 1 or match.kickoff.nunique() != 1:
                raise ValueError("A source fixture requires two sides with one week and kickoff.")
        calendar["home"] = calendar.home.astype(int)
        rows["home"] = rows.home.astype(int)
        calendar["kickoff"] = pd.to_datetime(calendar.kickoff, utc=True)
        rows["kickoff"] = pd.to_datetime(rows.kickoff, utc=True)
        cutoff = pd.Timestamp(cast(str, served["captured_at_utc"]))
        if (
            cutoff.tzinfo is None
            or calendar.kickoff.isna().any()
            or not calendar.kickoff.gt(cutoff).all()
        ):
            raise ValueError("Fixture calendar does not follow the aware source cutoff.")
        expected = pd.DataFrame(
            {"player_code": list(roster_clubs), "club": list(roster_clubs.values())}
        )
        expected = expected.merge(calendar[calendar_cols], on="club", validate="many_to_many")
        expected["position"] = expected.player_code.map(roster.position)
        keys = ["fixture", "player_code"]
        actual_identity = rows[list(IDENTITY_COLUMNS)].sort_values(keys).reset_index(drop=True)
        expected_identity = (
            expected[list(IDENTITY_COLUMNS)].sort_values(keys).reset_index(drop=True)
        )
        if not actual_identity.equals(expected_identity):
            raise ValueError("Fixture rows do not exactly cover the captured calendar and roster.")
        # Validate the externally supplied JSON before doing any arithmetic with it.
        _validate_components(
            rows,
            str(served["season"]),
            joint_role=served["model_version"] in JOINT_ROLE_MODEL_VERSIONS,
        )
        aggregate = _weekly_from_fixture_rows(weekly, rows, dict.fromkeys(players, 1.0))
        for col in ("expected_points", "appearance_probability"):
            _close(weekly[col], aggregate[col], "served weekly " + col)
        counts = rows.groupby(["GW", "player_code"]).agg(
            fixture_count=("fixture", "size"), home_fixture_count=("home", "sum")
        )
        for row in weekly.itertuples():
            key = (int(cast(int, row.gameweek)), int(cast(int, row.player_id)))
            for col in ("fixture_count", "home_fixture_count"):
                actual = 0 if key not in counts.index else counts.loc[key, col]
                if getattr(row, col) != actual:
                    raise ValueError("Served fixture counts do not match companion coverage.")
        return cls(_canonical(served), _canonical(companion))

    @property
    def served(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self._served_json))

    @property
    def companion(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self._companion_json))

    @property
    def fixture_rows(self) -> pd.DataFrame:
        frame = pd.DataFrame(cast(list[dict[str, object]], self.companion["rows"]))
        frame.attrs["season"] = str(self.served["season"])
        frame.attrs["joint_role"] = self.served["model_version"] in JOINT_ROLE_MODEL_VERSIONS
        return frame

    @property
    def weekly_rows(self) -> pd.DataFrame:
        # Use original weekly floats for a true no-evidence identity, not recomputed sums.
        frame = pd.DataFrame(cast(list[dict[str, object]], self.served["rows"]))
        lookup = _availability_multipliers(self.companion)
        for column in ("expected_points", "appearance_probability"):
            frame[column] = frame[column] * frame.player_id.map(lookup)
        return frame


@dataclass(frozen=True, slots=True)
class MinuteInterventionResult:
    fixture_rows: pd.DataFrame
    weekly_rows: pd.DataFrame
    evidence_audit: tuple[dict[str, object], ...]
    source_forecast_fingerprint: str
    source_components_fingerprint: str
    fingerprint: str
    assumptions: tuple[str, ...] = _ASSUMPTIONS
    contract_version: str = INTERVENTION_VERSION


def apply_explicit_minute_evidence(
    basis: FixtureComponentBasis, evidence: Sequence[ExplicitMinuteEvidence]
) -> MinuteInterventionResult:
    """Reallocate learned minutes, recompute affected club shares, aggregate once.

    Changes are first-week only. Fixture IDs are required even for a single gameweek;
    applying one fixture's statement to a second fixture is never an implicit default.
    """
    original = basis.fixture_rows
    weekly = basis.weekly_rows
    adjusted = original.copy(deep=True)
    affected_sides: set[tuple[int, int, int]] = set()
    used: set[tuple[int, int]] = set()
    ids: set[str] = set()
    audit: list[dict[str, object]] = []
    for item in evidence:
        if not isinstance(item, ExplicitMinuteEvidence) or item.evidence_id in ids:
            raise ValueError("Duplicate or unsupported minute evidence.")
        ids.add(item.evidence_id)
        if item.gameweek != basis.served["gameweek"]:
            raise ValueError("Minute evidence must address the current decision week.")
        effective = weekly.loc[
            weekly.gameweek.eq(item.gameweek) & weekly.player_id.eq(item.player_id),
            "appearance_probability",
        ]
        if len(effective) != 1 or float(effective.iloc[0]) <= 0:
            raise ValueError("No positive effective appearance basis for this intervention.")
        for fixture in item.fixture_ids:
            key = (item.player_id, fixture)
            if key in used:
                raise ValueError(
                    "Overlapping minute restrictions require upstream conflict resolution."
                )
            used.add(key)
            selected = adjusted.index[
                adjusted.player_code.eq(item.player_id)
                & adjusted.fixture.eq(fixture)
                & adjusted.GW.eq(item.gameweek)
            ]
            if len(selected) != 1:
                raise ValueError("Evidence names an unknown player-fixture scope.")
            index = selected[0]
            p = adjusted.loc[index, [f"minute_probability_{b}" for b in range(4)]].to_numpy(float)
            shorter = p[1] + p[2]
            if 1 - p[0] <= 0 or (p[3] > 0 and shorter <= 0):
                raise ValueError("No learned positive sub-90 support for this intervention.")
            joint = _joint_minutes(adjusted.loc[[index]])
            if joint is not None:
                # A statement excluding a full match changes exposure, not the
                # starting role. Never invent a starter-to-cameo transition to
                # obtain shorter support when that role has none in the fit.
                for role in ("start", "cameo"):
                    columns = [f"{role}_minute_probability_{b}" for b in (1, 2, 3)]
                    values = adjusted.loc[index, columns].to_numpy(float)
                    support = float(values[:2].sum())
                    if values[2] > 0 and support <= 0:
                        raise ValueError(
                            "No learned positive sub-90 support within the starting role."
                        )
                    if values[2] > 0:
                        adjusted.loc[index, columns[:2]] = values[:2] * (1 + values[2] / support)
                        adjusted.at[index, columns[2]] = 0.0
            elif p[3] > 0:
                adjusted.loc[index, ["minute_probability_1", "minute_probability_2"]] = p[1:3] * (
                    1 + p[3] / shorter
                )
                adjusted.at[index, "minute_probability_3"] = 0.0
            row = adjusted.loc[index]
            affected_sides.add((int(row.GW), int(row.fixture), int(row.club)))
            audit.append(
                {
                    "evidence_id": item.evidence_id,
                    "player_id": item.player_id,
                    "gameweek": item.gameweek,
                    "fixture_id": fixture,
                    "restriction": item.restriction,
                    "source_url": item.source_url,
                    "source_sha256": item.source_sha256,
                    "source_span": [item.span_start, item.span_end],
                    "source_verification": "caller_verified",
                    "expected_minutes_before": float(
                        cast(float, original.at[index, "expected_minutes"])
                    ),
                }
            )
    changed_players: set[int] = set()
    for week, fixture, club in sorted(affected_sides):
        mask = adjusted.GW.eq(week) & adjusted.fixture.eq(fixture) & adjusted.club.eq(club)
        before = original.loc[mask]
        side = _score_components(adjusted.loc[mask])
        old_minutes = before.expected_minutes.to_numpy(float)
        new_minutes = side.expected_minutes.to_numpy(float)
        for head in ("goals", "assists"):
            weights = np.divide(
                before[head + "_share"].to_numpy(float) * new_minutes,
                old_minutes,
                out=np.zeros(len(side)),
                where=old_minutes > 0,
            )
            if weights.sum() <= 0:
                raise ValueError(
                    "Minute intervention leaves no supported team attacking allocation."
                )
            share = weights / weights.sum()
            side[head + "_share"] = share
            side[head] = float(before[head].sum()) * share
        side = _score_components(side)
        updated_columns = [*COMPONENT_COLUMNS]
        if "minute_role_status" in side:
            updated_columns.extend(
                name for name in ROLE_COMPONENT_COLUMNS if name not in updated_columns
            )
        adjusted.loc[mask, updated_columns] = side[updated_columns].to_numpy()
        changed_players.update(int(p) for p in side.player_code)
    if evidence:
        multipliers = _availability_multipliers(basis.companion)
        computed = _weekly_from_fixture_rows(weekly, adjusted, multipliers)
        mask = weekly.gameweek.eq(cast(int, basis.served["gameweek"])) & weekly.player_id.isin(
            changed_players
        )
        _close(
            computed.appearance_probability,
            weekly.appearance_probability,
            "preserved weekly appearance",
        )
        weekly.loc[mask, "expected_points"] = computed.loc[mask, "expected_points"].to_numpy()
        for record in audit:
            row = adjusted.loc[
                adjusted.player_code.eq(cast(int, record["player_id"]))
                & adjusted.fixture.eq(cast(int, record["fixture_id"]))
            ].iloc[0]
            record["expected_minutes_after"] = float(row.expected_minutes)
            record["appearance_probability"] = float(row.appearance_probability)
    identity = {
        "contract_version": INTERVENTION_VERSION,
        "forecast_fingerprint": basis.served["fingerprint"],
        "components_fingerprint": basis.companion["fingerprint"],
        "evidence": audit,
        "weekly_rows": weekly.to_dict("records"),
    }
    return MinuteInterventionResult(
        adjusted,
        weekly,
        tuple(audit),
        str(basis.served["fingerprint"]),
        str(basis.companion["fingerprint"]),
        forecast_digest(identity),
    )
