"""Project several gameweeks from one captured decision snapshot.

`squadopt.planning.horizon` fixes what the transfer planner will accept and leaves the
builder to this side. This is that builder.

The idea it rests on is narrow and worth stating exactly, because it is what separates a
projection from a forecast of forecasts. **One information state covers the whole
horizon.** Player features come from the decision point and never move; only the calendar
varies per target gameweek. That is why a capture can support a four-week horizon while
`recommendation.project` still refuses a mid-season target: there, the *decision point*
itself would need a season's played history that no captured source carries. Here the
decision point stays put and the question is what the same knowledge implies for each
gameweek ahead.

Two consequences are stated rather than buried.

**Expected points scale linearly with fixture count.** A blank gameweek projects exactly
zero, a double projects twice a single. That is not a new rule invented here — the
expected-minutes stage already scales by fixture count and caps at that many full matches
(`prediction/minutes.py`). Reusing it keeps one treatment of the calendar rather than two.
But the operational control that produces the base projection is calendar-blind, so the
scaling is post-processing applied on top of it, and it is named in the horizon's
post-processing contract instead of hiding inside the number.

**The horizon is not gate evidence.** The frozen evaluation objective is single-gameweek
realized squad points. Nothing measures how far a multi-gameweek projection drifts, and it
will drift: expected minutes for gameweek t+3 are computed from what was known at t, so
injuries, rotation and suspensions in between are unseen. Expect the projection to grow
overconfident as the horizon lengthens, by an amount nobody has measured yet.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.data.fixtures import aggregate_team_gameweek
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    fixture_snapshot,
    player_snapshot,
    team_codes,
    team_names,
)
from squadopt.features.cross_season import CrossSeasonConfig
from squadopt.live.recommendation import (
    InSeasonProjection,
    infer_season,
    project,
    read_inputs,
)
from squadopt.planning.horizon import (
    PROJECTION_HORIZON_COLUMNS,
    ProjectionHorizon,
)
from squadopt.prediction.availability import (
    AVAILABILITY_RULE_CONTRACT_VERSION,
    AvailabilityRuleConfig,
)
from squadopt.prediction.config import BaselineProjectionConfig

# The calendar rule applied on top of the calendar-blind control. Named in the horizon's
# post-processing contract so a consumer can tell that the scaling happened outside the
# model rather than inside it.
FIXTURE_SCALING_RULE_VERSION: Final = "linear_fixture_count_scaling_v1"
HORIZON_POST_PROCESSING_CONTRACT_VERSION: Final = (
    f"{AVAILABILITY_RULE_CONTRACT_VERSION}+{FIXTURE_SCALING_RULE_VERSION}"
)

_BASE_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")

__all__ = [
    "FIXTURE_SCALING_RULE_VERSION",
    "HORIZON_POST_PROCESSING_CONTRACT_VERSION",
    "build_projection_horizon",
    "gameweek_fixture_fingerprints",
    "make_projection_horizon_builder",
]


def _require_consecutive(target_gameweeks: Sequence[int]) -> tuple[int, ...]:
    """Return the requested gameweeks, refusing a gap.

    The contract represents a blank gameweek as a row with no fixtures, so a missing
    gameweek in the request is genuinely ambiguous: it could mean "skip it" or "it is
    blank", and those are different plans.
    """

    if not isinstance(target_gameweeks, tuple | list) or not target_gameweeks:
        raise DataSourceError("target_gameweeks must be a non-empty sequence of gameweeks.")
    values: list[int] = []
    for value in target_gameweeks:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DataSourceError(f"target_gameweeks must be positive integers, got {value!r}.")
        values.append(int(value))
    ordered = tuple(sorted(set(values)))
    if len(ordered) != len(values):
        raise DataSourceError("target_gameweeks must not repeat a gameweek.")
    if ordered != tuple(range(ordered[0], ordered[-1] + 1)):
        raise DataSourceError(
            f"target_gameweeks must be consecutive, got {ordered!r}. A blank gameweek is a "
            "row with zero fixtures, not a gameweek left out of the request."
        )
    return ordered


def _payload(snapshot: CapturedSnapshot, name: str) -> bytes:
    payload = snapshot.payloads.get(name)
    if payload is None:
        raise DataSourceError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no {name!r} payload, so it "
            "cannot support a projection horizon."
        )
    return payload


def _team_code_by_name(bootstrap: bytes) -> Mapping[str, int]:
    """Bridge the panel's display name to the fixture table's persistent code.

    Composed from the payload's own two mappings rather than a stored table, so the
    bridge is the one that capture declared. The per-season integer is deliberately not
    the join key: it is reassigned as clubs are promoted and relegated, so the same
    number denotes different clubs in different seasons.
    """

    names = team_names(bootstrap)
    codes = team_codes(bootstrap)
    missing = sorted(set(names) - set(codes))
    if missing:
        raise DataSourceError(
            f"The capture names teams {missing!r} without a persistent code, so the "
            "fixture table cannot be joined to the projected roster."
        )
    bridge = {str(name): int(codes[identifier]) for identifier, name in names.items()}
    if len(bridge) != len(names):
        duplicates = sorted(
            {name for name in names.values() if list(names.values()).count(name) > 1}
        )
        raise DataSourceError(f"The capture names two teams identically: {duplicates!r}.")
    return bridge


def gameweek_fixture_fingerprints(
    calendar: pd.DataFrame,
    target_gameweeks: Sequence[int],
) -> Mapping[int, str]:
    """Fingerprint each gameweek's fixture context separately.

    One fingerprint per gameweek rather than one for the horizon: two plans built from
    captures that agree on gameweek two and disagree on gameweek four should be
    distinguishable at the gameweek that moved.
    """

    fingerprints: dict[int, str] = {}
    for gameweek in target_gameweeks:
        rows = calendar.loc[calendar["gameweek"] == int(gameweek)]
        payload = (
            rows.loc[:, ["team_id", "fixture_count", "home_fixture_count"]]
            .sort_values("team_id", kind="stable")
            .to_dict(orient="records")
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        fingerprints[int(gameweek)] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return fingerprints


def build_projection_horizon(
    decision_snapshot: CapturedSnapshot,
    target_gameweeks: tuple[int, ...],
    *,
    panel: pd.DataFrame | None = None,
    season: str | None = None,
    projection_config: BaselineProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
    availability_config: AvailabilityRuleConfig | None = None,
    in_season: InSeasonProjection | None = None,
) -> ProjectionHorizon:
    """Project a consecutive horizon from one captured information state.

    Gameweek one uses the completed-history ``panel``. A horizon beginning later in the
    season uses an ``in_season`` handoff for the first target gameweek. The live
    projection seam validates that handoff against the season, capture and gameweek
    before its numbers are reused across the captured future calendar.
    """

    if not isinstance(decision_snapshot, CapturedSnapshot):
        raise DataSourceError("decision_snapshot must be a CapturedSnapshot.")
    if panel is not None and not isinstance(panel, pd.DataFrame):
        raise DataSourceError("panel must be a pandas DataFrame when supplied.")
    gameweeks = _require_consecutive(target_gameweeks)

    bootstrap = _payload(decision_snapshot, BOOTSTRAP_PAYLOAD)
    fixtures_payload = _payload(decision_snapshot, FIXTURES_PAYLOAD)
    resolved_season = season or infer_season(decision_snapshot)
    snapshot_id = decision_snapshot.metadata.snapshot_id

    # The information state. Read once, at the first target, and reused unchanged for
    # every later gameweek — which is the whole claim this module makes.
    inputs = read_inputs(decision_snapshot, season=resolved_season, gameweek=gameweeks[0])
    projection = project(
        inputs,
        panel,
        projection_config=projection_config,
        cross_season=cross_season,
        availability_config=availability_config,
        in_season=in_season,
    )
    projected = projection.table

    calendar = aggregate_team_gameweek(
        fixture_snapshot(
            fixtures_payload,
            bootstrap,
            season=resolved_season,
            snapshot_id=snapshot_id,
            captured_at_utc=decision_snapshot.metadata.captured_at_utc,
        )
    )
    bridge = _team_code_by_name(bootstrap)
    base = projected.loc[:, [*_BASE_COLUMNS, "expected_points"]].copy(deep=True)
    unknown = sorted({str(name) for name in base["team_id"]} - set(bridge))
    if unknown:
        raise DataSourceError(
            f"The projected roster names teams the capture does not: {unknown!r}."
        )
    base["team_code"] = base["team_id"].astype("string").map(bridge).astype("int64")

    frames = [_gameweek_rows(base, calendar, gameweek) for gameweek in gameweeks]
    table = pd.concat(frames, ignore_index=True).loc[:, list(PROJECTION_HORIZON_COLUMNS)]

    return ProjectionHorizon(
        table=table,
        season=resolved_season,
        source_snapshot_id=snapshot_id,
        model_name=_projection_identity(projection.diagnostics, "model_name"),
        model_version=_projection_identity(projection.diagnostics, "model_version"),
        feature_contract_version=_projection_identity(
            projection.diagnostics, "feature_contract_version"
        ),
        post_processing_contract_version=HORIZON_POST_PROCESSING_CONTRACT_VERSION,
    )


def _projection_identity(diagnostics: Mapping[str, object], name: str) -> str:
    """Return one required provenance value from the shared projection seam."""

    value = diagnostics.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DataSourceError(f"Projection diagnostics carry no non-empty {name!r}.")
    return value


def _gameweek_rows(
    base: pd.DataFrame,
    calendar: pd.DataFrame,
    gameweek: int,
) -> pd.DataFrame:
    """Apply one gameweek's calendar to the shared information state.

    A club absent from the calendar for this gameweek is blank, not missing: it gets
    zero fixtures and therefore zero points, and its players stay in the table. Dropping
    them would break the fixed player universe the planner reasons over and would also
    quietly turn "he cannot score this week" into "he does not exist this week".
    """

    counts = calendar.loc[
        calendar["gameweek"] == int(gameweek),
        ["team_id", "fixture_count", "home_fixture_count"],
    ].rename(columns={"team_id": "team_code"})

    rows = base.merge(counts, on="team_code", how="left", validate="many_to_one")
    fixture_count = rows["fixture_count"].fillna(0).astype("int64")
    home_count = rows["home_fixture_count"].fillna(0).astype("int64")

    rows["gameweek"] = int(gameweek)
    rows["fixture_count"] = fixture_count
    rows["home_fixture_count"] = home_count
    rows["expected_points"] = (
        rows["expected_points"]
        .astype("float64")
        .mul(fixture_count.astype("float64"))
        .clip(lower=0.0)
    )
    return rows


def fixture_counts_by_player(
    decision_snapshot: CapturedSnapshot,
    gameweek: int,
    *,
    season: str | None = None,
) -> dict[int, int]:
    """Each captured player's fixture count in ``gameweek``, from the capture's calendar.

    A club absent from the calendar that gameweek is blank and gets zero. Built for the
    live risk layer, whose double-gameweek scale needs the calendar per player.
    """

    if not isinstance(decision_snapshot, CapturedSnapshot):
        raise DataSourceError("decision_snapshot must be a CapturedSnapshot.")
    bootstrap = _payload(decision_snapshot, BOOTSTRAP_PAYLOAD)
    fixtures_payload = _payload(decision_snapshot, FIXTURES_PAYLOAD)
    resolved_season = season or infer_season(decision_snapshot)
    calendar = aggregate_team_gameweek(
        fixture_snapshot(
            fixtures_payload,
            bootstrap,
            season=resolved_season,
            snapshot_id=decision_snapshot.metadata.snapshot_id,
            captured_at_utc=decision_snapshot.metadata.captured_at_utc,
        )
    )
    counts_by_code = {
        int(team): int(count)
        for team, count in zip(
            calendar.loc[calendar["gameweek"] == int(gameweek), "team_id"].tolist(),
            calendar.loc[calendar["gameweek"] == int(gameweek), "fixture_count"].tolist(),
            strict=True,
        )
    }
    bridge = _team_code_by_name(bootstrap)
    players = player_snapshot(bootstrap)
    return {
        int(player): counts_by_code.get(int(bridge[str(team)]), 0)
        for player, team in zip(
            players["player_id"].tolist(), players["team_id"].tolist(), strict=True
        )
    }


def make_projection_horizon_builder(
    panel: pd.DataFrame | None = None,
    *,
    season: str | None = None,
    projection_config: BaselineProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
    availability_config: AvailabilityRuleConfig | None = None,
    in_season: InSeasonProjection | None = None,
) -> Callable[[CapturedSnapshot, tuple[int, ...]], ProjectionHorizon]:
    """Bind projection inputs so the result satisfies ``ProjectionHorizonBuilder``.

    The planner should not know whether the decision point needs completed history or an
    in-season handoff. Binding that producer-side detail here keeps the planning seam
    unchanged.
    """

    def build(
        decision_snapshot: CapturedSnapshot,
        target_gameweeks: tuple[int, ...],
    ) -> ProjectionHorizon:
        return build_projection_horizon(
            decision_snapshot,
            target_gameweeks,
            panel=panel,
            season=season,
            projection_config=projection_config,
            cross_season=cross_season,
            availability_config=availability_config,
            in_season=in_season,
        )

    return build
