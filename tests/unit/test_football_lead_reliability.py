"""The lead reliability runner keeps the protocol's rules; synthetic frames, no archive."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from scripts import measure_football_lead_reliability as runner
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.evaluation.promotion import PromotionPolicy

SEASON = "2024-25"
KICKOFF = pd.Timestamp("2024-08-01 15:00", tz="UTC")


@pytest.fixture(scope="module")
def synthetic(football_fixture):  # noqa: F811
    """The shared synthetic football season, labelled as an evaluated one."""
    _, history, _, _, training = football_fixture
    history = history.assign(
        season=SEASON,
        name=lambda d: d.player_code.astype(str),
        team=lambda d: "Club " + d.club.astype(str),
        value=50,
    )
    training = training.assign(season=SEASON)
    calendar = history.loc[:, ["fixture", "club", "opponent", "home", "GW", "kickoff"]]
    return history, training, calendar.drop_duplicates().reset_index(drop=True)


@pytest.fixture(scope="module")
def measured(synthetic):
    history, training, calendar = synthetic
    return runner.measure_frames(
        history,
        training,
        {SEASON: calendar},
        seasons=(SEASON,),
        measured=(10,),
        lead_one=range(10, 17),
        last=16,
    )


def _row(**values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "season": SEASON,
        "GW": 9,
        "fixture": 1,
        "player_code": 1,
        "club": 1,
        "position": "MID",
        "kickoff": KICKOFF,
        "name": "A",
        "team": "Club 1",
        "value": 50,
    }
    return {**base, **values}


def test_each_measured_origin_forecasts_the_weeks_the_protocol_states() -> None:
    lengths = {o: len(runner.origin_weeks(o)) for o in runner.MEASURED_ORIGINS}
    assert lengths == {11: 14, 15: 14, 19: 14, 23: 14, 27: 12, 31: 8}
    assert tuple(range(11, 39)) == runner.LEAD_ONE_ORIGINS
    assert runner.SELECTED_SEASONS == ("2022-23", "2023-24", "2024-25")
    assert "2025-26" not in runner.SELECTED_SEASONS
    assert runner.NEVER_OPENED == ("2025-26",)


def test_the_decision_instant_is_the_first_kickoff_less_ninety_minutes() -> None:
    history = pd.DataFrame(
        [_row(GW=5, kickoff=KICKOFF), _row(GW=5, fixture=2, kickoff=KICKOFF - pd.Timedelta("2h"))]
    )
    instant = runner.decision_instant(history, SEASON, 5)
    assert instant == KICKOFF - pd.Timedelta("2h") - pd.Timedelta(minutes=90)
    with pytest.raises(runner.LeadReliabilityRefusal, match="GW6"):
        runner.decision_instant(history, SEASON, 6)


def test_the_roster_is_decided_by_settled_rows_of_the_two_weeks_before_the_origin() -> None:
    origin_kickoff = KICKOFF + pd.Timedelta(days=21)
    instant = origin_kickoff - pd.Timedelta(minutes=90)
    history = pd.DataFrame(
        [
            # Moved clubs between the two weeks: the later row decides.
            _row(player_code=1, GW=8, club=1, kickoff=KICKOFF + pd.Timedelta(days=7)),
            _row(player_code=1, GW=9, club=2, kickoff=KICKOFF + pd.Timedelta(days=14)),
            # Only a row in the origin's own week: unknown at the decision, so absent.
            _row(player_code=2, GW=10, kickoff=origin_kickoff),
            # A week-9 fixture played after the decision instant is not settled.
            _row(player_code=3, GW=9, kickoff=instant - pd.Timedelta(hours=2)),
            # Three weeks before the origin is outside the rule.
            _row(player_code=4, GW=7, kickoff=KICKOFF),
            # Another season is never read for this one's roster.
            _row(player_code=5, GW=9, season="2023-24", kickoff=KICKOFF + pd.Timedelta(days=14)),
        ]
    )
    roster = runner.roster_at(history, SEASON, 10, instant)
    assert roster.player_id.tolist() == [1]
    assert roster.club.tolist() == [2]
    assert set(roster.columns) == {
        "player_id",
        "name",
        "team_id",
        "position",
        "price_tenths",
        "club",
    }


def test_a_blank_or_a_double_marks_its_gameweek_irregular() -> None:
    sides = [
        {"GW": 1, "club": 1, "fixture": 1},
        {"GW": 1, "club": 2, "fixture": 1},
        {"GW": 2, "club": 1, "fixture": 2},
        {"GW": 2, "club": 1, "fixture": 3},
        {"GW": 2, "club": 2, "fixture": 2},
        {"GW": 3, "club": 2, "fixture": 4},
    ]
    assert runner.irregular_weeks(pd.DataFrame(sides)) == [2, 3]


def _labelled(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["error"] = frame.expected_points - frame.total_points
    return frame


def test_a_pair_needs_both_forecasts_matched_and_a_regular_target_week() -> None:
    common = {"season": SEASON, "position": "MID"}
    labelled = _labelled(
        [
            # Origin 10 at lead 2 of GW11, and GW11's own lead-1 forecast: one pair.
            {
                **common,
                "fixture": 1,
                "player_code": 1,
                "GW": 11,
                "origin": 10,
                "lead": 2,
                "expected_points": 5.0,
                "total_points": 2.0,
            },
            {
                **common,
                "fixture": 1,
                "player_code": 1,
                "GW": 11,
                "origin": 11,
                "lead": 1,
                "expected_points": 3.0,
                "total_points": 2.0,
            },
            # Unmatched at lead 2: unknown, never zero, so no pair.
            {
                **common,
                "fixture": 2,
                "player_code": 2,
                "GW": 11,
                "origin": 10,
                "lead": 2,
                "expected_points": 4.0,
                "total_points": float("nan"),
            },
            {
                **common,
                "fixture": 2,
                "player_code": 2,
                "GW": 11,
                "origin": 11,
                "lead": 1,
                "expected_points": 4.0,
                "total_points": 1.0,
            },
            # An irregular target week is kept apart.
            {
                **common,
                "fixture": 3,
                "player_code": 3,
                "GW": 12,
                "origin": 10,
                "lead": 3,
                "expected_points": 4.0,
                "total_points": 1.0,
            },
            {
                **common,
                "fixture": 3,
                "player_code": 3,
                "GW": 12,
                "origin": 12,
                "lead": 1,
                "expected_points": 2.0,
                "total_points": 1.0,
            },
        ]
    )
    pairs = runner.paired_differences(labelled, measured=(10,), irregular={SEASON: [12]})
    assert pairs.player_code.tolist() == [1]
    assert pairs.difference.tolist() == [(5.0 - 2.0) ** 2 - (3.0 - 2.0) ** 2]


def test_a_forecast_without_an_outcome_stays_unknown_and_is_counted() -> None:
    forecast = pd.DataFrame(
        {
            "season": [SEASON, SEASON],
            "fixture": [1, 9],
            "player_code": [1, 1],
            "GW": [11, 11],
            "position": ["MID", "MID"],
            "expected_points": [3.0, 3.0],
            "origin": [11, 11],
            "lead": [1, 1],
        }
    )
    history = pd.DataFrame(
        {"season": [SEASON], "fixture": [1], "player_code": [1], "total_points": [2.0]}
    )
    labelled = runner.with_outcomes(forecast, history)
    assert labelled.total_points.isna().tolist() == [False, True]
    (count,) = runner.counts(labelled, labelled.iloc[0:0].assign(difference=0.0))
    assert (count["forecast"], count["matched"], count["unmatched"]) == (2, 1, 1)


def _units(season_weeks: list[tuple[str, int]], differences: list[float], lead: int = 3):
    return pd.DataFrame(
        {
            "season": [season for season, _ in season_weeks],
            "GW": [week for _, week in season_weeks],
            "lead": [lead] * len(season_weeks),
            "difference": differences,
            "error": [1.0] * len(season_weeks),
            "error_1": [0.5] * len(season_weeks),
        }
    )


def test_the_interval_reads_each_seasons_units_in_week_order_under_its_own_lead_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the interval is handed: each season's units in target-week order, under lead_k."""

    seen: list[tuple[list[tuple[str, float]], str]] = []

    def spy(differences, *, policy, candidate_id):
        seen.append((list(differences), candidate_id))
        return (0.0, 0.0)

    monkeypatch.setattr(runner, "season_aware_moving_block_interval", spy)
    pairs = _units(
        [
            ("2024-25", 13),
            ("2023-24", 12),
            ("2024-25", 11),
            ("2023-24", 11),
            ("2024-25", 12),
            ("2023-24", 13),
        ],
        [3.0, 2.0, 1.0, 0.5, 2.5, 4.0],
    )
    runner.lead_figures(pairs)
    assert seen == [
        (
            [
                ("2023-24", 0.5),
                ("2023-24", 2.0),
                ("2023-24", 4.0),
                ("2024-25", 1.0),
                ("2024-25", 2.5),
                ("2024-25", 3.0),
            ],
            "lead_3",
        )
    ]


def test_a_lead_with_fewer_than_six_units_in_total_is_thin_and_gets_no_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Six units are read over the two seasons: 3 + 3 is not thin, though each season alone
    is under six; 5 units are thin, keep their point estimate and never reach the interval."""

    calls: list[str] = []

    def spy(differences, *, policy, candidate_id):
        calls.append(candidate_id)
        return (0.0, 1.0)

    monkeypatch.setattr(runner, "season_aware_moving_block_interval", spy)
    three_and_three = _units(
        [(season, week) for season in ("2023-24", "2024-25") for week in (11, 12, 13)],
        [1.0] * 6,
        lead=2,
    )
    five = _units([("2023-24", week) for week in range(11, 16)], [1.0, 2.0, 3.0, 4.0, 5.0], lead=3)
    figures = {row["lead"]: row for row in runner.lead_figures(pd.concat([three_and_three, five]))}
    assert (figures[2]["units"], figures[2]["thin"], figures[2]["interval"]) == (6, False, [0, 1])
    assert (figures[3]["units"], figures[3]["thin"], figures[3]["interval"]) == (5, True, None)
    assert figures[3]["mean_difference"] == pytest.approx(3.0)
    assert calls == ["lead_2"]


def test_units_are_ordered_by_target_week_and_a_short_lead_is_thin() -> None:
    weeks = [12, 11, 14, 13]
    pairs = pd.DataFrame(
        {
            "season": [SEASON] * 4,
            "GW": weeks,
            "lead": [2] * 4,
            "difference": [1.0, 4.0, -2.0, 3.0],
            "error": [1.0] * 4,
            "error_1": [0.5] * 4,
        }
    )
    (lead_two, *_rest) = runner.lead_figures(pairs)
    assert lead_two["units"] == 4 and lead_two["thin"] is True
    assert lead_two["mean_difference"] == pytest.approx(1.5)
    assert lead_two["interval"] is None
    assert all(row["units"] == 0 and row["interval"] is None for row in _rest)


def test_the_policy_is_the_protocols_and_resamples_every_unit_of_a_four_unit_season() -> None:
    """Blocks of 1: with blocks of 4 a season of four units would reproduce itself."""

    assert (
        PromotionPolicy(
            confidence_level=0.90,
            bootstrap_resamples=5000,
            moving_block_length=1,
            deterministic_seed=0,
        )
        == runner.POLICY
    )
    pairs = _units(
        [("2023-24", week) for week in (11, 15, 19, 23)]
        + [("2024-25", week) for week in (11, 15, 19, 23)],
        [1.0, 2.0, 4.0, 8.0, 1.0, 3.0, 9.0, 27.0],
        lead=13,
    )
    (figure,) = [row for row in runner.lead_figures(pairs) if row["lead"] == 13]
    low, high = figure["interval"]
    assert figure["thin"] is False and low < high


def test_the_squared_errors_are_averaged_as_the_figure_is() -> None:
    """Per unit first, then over units: the figure is the difference of the two means."""

    pairs = pd.DataFrame(
        {
            "season": [SEASON] * 4,
            "GW": [11, 11, 11, 12],
            "lead": [2] * 4,
            "error": [1.0, 3.0, 5.0, 2.0],
            "error_1": [1.0, 1.0, 1.0, 0.0],
        }
    )
    pairs["difference"] = pairs.error**2 - pairs.error_1**2
    (figure, *_rest) = runner.lead_figures(pairs)
    # Unit 11: mean e_k^2 = 35/3, mean e_1^2 = 1; unit 12: 4 and 0.
    assert figure["mean_squared_error"] == pytest.approx((35 / 3 + 4) / 2)
    assert figure["mean_squared_error_lead_1"] == pytest.approx(0.5)
    assert figure["mean_difference"] == pytest.approx(
        figure["mean_squared_error"] - figure["mean_squared_error_lead_1"]
    )


def test_the_check_stops_on_a_missing_column_and_never_opens_the_excluded_season(
    tmp_path: Path,
) -> None:
    for season in runner.SELECTED_SEASONS:
        for name, columns in runner.REQUIRED_COLUMNS.items():
            path = tmp_path / "data" / season / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(",".join(columns) + "\n", encoding="utf-8")
    # A 2025-26 file that cannot be read: opening it would fail the check.
    (tmp_path / "data" / "2025-26" / "gws" / "merged_gw.csv").mkdir(parents=True)
    hashes = runner.check(tmp_path)
    assert sorted({key.split("/")[0] for key in hashes}) == list(runner.SELECTED_SEASONS)

    columns = [c for c in runner.REQUIRED_COLUMNS["gws/merged_gw.csv"] if c != "value"]
    (tmp_path / "data" / "2023-24" / "gws" / "merged_gw.csv").write_text(
        ",".join(columns) + "\n", encoding="utf-8"
    )
    with pytest.raises(
        runner.LeadReliabilityRefusal, match=r"2023-24/gws/merged_gw\.csv lacks value"
    ):
        runner.check(tmp_path)


def test_the_run_reads_the_three_selected_seasons_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def archive(root: Path, *, seasons: object = None) -> pd.DataFrame:
        seen.append(seasons)
        raise runner.LeadReliabilityRefusal("stop after the read")

    monkeypatch.setattr(runner, "check", lambda root: {})
    monkeypatch.setattr(runner, "archive_history", archive)
    with pytest.raises(runner.LeadReliabilityRefusal, match="stop after the read"):
        runner.run(tmp_path / "archive", tmp_path / "out", repository_commit="0" * 40)
    assert seen == [runner.SELECTED_SEASONS]
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("where", ["docs", "data", "archive", "existing"])
def test_the_run_refuses_a_destination_the_protocol_forbids(tmp_path: Path, where: str) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    output = {
        "docs": runner.REPOSITORY_ROOT / "docs" / "lead-reliability-test",
        "data": runner.REPOSITORY_ROOT / "data" / "lead-reliability-test",
        "archive": archive / "out",
        "existing": tmp_path,
    }[where]
    with pytest.raises(runner.LeadReliabilityRefusal, match=r"Refusing|already exists"):
        runner.run(archive, output, repository_commit="0" * 40)
    assert where == "existing" or not output.exists()


def test_a_failed_origin_is_recorded_once_and_never_retried(
    synthetic, monkeypatch: pytest.MonkeyPatch
) -> None:
    history, training, calendar = synthetic
    calls: list[int] = []
    original = runner.forecast_origin

    def counted(*args: object, **kwargs: object):
        calls.append(int(kwargs["origin"]))  # type: ignore[call-overload]
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runner, "forecast_origin", counted)
    record, _ = runner.measure_frames(
        history,
        training,
        {SEASON: calendar},
        seasons=(SEASON,),
        measured=(),
        lead_one=(17,),
        last=16,
    )
    assert calls == [17]
    assert [(f["season"], f["origin"]) for f in record["failed_origins"]] == [(SEASON, 17)]
    assert "GW17" in record["failed_origins"][0]["error"]


def test_the_synthetic_season_is_measured_end_to_end(measured) -> None:
    record, labelled = measured
    assert record["failed_origins"] == []
    assert record["seasons_never_opened"] == ["2025-26"]
    assert record["locked_holdout_accessed"] is False
    assert [o["origin"] for o in record["origins"]] == list(range(10, 17))
    assert record["origins"][0]["gameweeks"] == [10, 16]
    assert {o["roster_players"] for o in record["origins"]} == {32}

    primary = {row["lead"]: row for row in record["primary"]}
    for lead in range(2, 8):
        assert (primary[lead]["pairs"], primary[lead]["units"]) == (32, 1)
        assert primary[lead]["thin"] is True
    assert all(primary[lead]["units"] == 0 for lead in range(8, 15))

    # Recompute lead 3 from the labelled forecasts, outside the runner's pairing.
    later = labelled.loc[labelled.origin.eq(10) & labelled.lead.eq(3)].set_index("player_code")
    first = labelled.loc[labelled.origin.eq(12) & labelled.lead.eq(1)].set_index("player_code")
    difference = (later.error**2 - first.error.reindex(later.index) ** 2).mean()
    assert primary[3]["mean_difference"] == pytest.approx(difference)
    assert all(count["unmatched"] == 0 for count in record["counts"])


def test_the_lead_one_side_of_a_week_does_not_depend_on_how_far_its_origin_looks(
    synthetic, measured
) -> None:
    """Why an origin is forecast once: its own week equals a one-week forecast of it."""
    history, training, calendar = synthetic
    _, labelled = measured
    own = labelled.loc[labelled.origin.eq(10) & labelled.lead.eq(1)].set_index("player_code")
    alone, _, _ = runner.forecast_origin(
        training, history, calendar, season=SEASON, origin=10, weeks=(10,)
    )
    alone = alone.set_index("player_code")
    assert len(own) == 32 and own.GW.eq(10).all()
    # Equal up to the platform's last binary digit: the same sums land in a different order on
    # arm64 and x86-64, and a tolerance of a billionth still catches any dependence on the origin.
    pd.testing.assert_series_equal(
        own.expected_points.sort_index(),
        alone.expected_points.sort_index(),
        check_exact=False,
        rtol=1e-9,
        atol=0.0,
    )


def test_the_descriptive_figures_are_by_lead_over_measured_origins_only() -> None:
    rows = []
    for player in range(12):
        rows.append(
            {
                "season": SEASON,
                "fixture": player,
                "player_code": player,
                "GW": 11,
                "origin": 10,
                "lead": 2,
                "position": "MID",
                "expected_points": float(player),
                "total_points": float(player),
            }
        )
    rows.append(
        {
            "season": SEASON,
            "fixture": 99,
            "player_code": 99,
            "GW": 11,
            "origin": 11,
            "lead": 1,
            "position": "MID",
            "expected_points": 9.0,
            "total_points": 0.0,
        }
    )
    pairs = pd.DataFrame({"season": [SEASON], "GW": [11], "lead": [2]})
    figures = runner.descriptive(_labelled(rows), pairs, measured=(10,), irregular={})
    assert [row["lead"] for row in figures] == list(range(1, 15))
    lead_one, lead_two = figures[0], figures[1]
    # Origin 11 is not measured: its lead-1 forecast is a pair's other side, not a secondary.
    assert (lead_one["forecast"], lead_one["matched"], lead_one["paired"]) == (0, 0, None)
    assert lead_two["lead"] == 2 and lead_two["matched"] == 12
    assert (lead_two["forecast"], lead_two["unmatched"], lead_two["paired"]) == (12, 0, 1)
    assert lead_two["slope_realized_on_forecast"] == pytest.approx(1.0)
    assert lead_two["mean_signed_error"] == pytest.approx(0.0)
    assert lead_two["top_ten_optimism"] == pytest.approx(0.0)
    assert lead_two["spearman_by_position"] == {"MID": pytest.approx(1.0)}


def _forecast(**values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "season": SEASON,
        "fixture": 1,
        "player_code": 1,
        "GW": 11,
        "origin": 10,
        "lead": 2,
        "position": "MID",
        "expected_points": 1.0,
        "total_points": 1.0,
    }
    return {**base, **values}


def test_the_secondaries_are_taken_in_the_lead_s_units_and_skip_blank_and_double_weeks() -> None:
    """Lead k reads only the target weeks with a pair at lead k; lead 1 the measured origins'
    own weeks; a blank or double week enters no lead, however wrong its forecasts are."""

    rows = [
        # Lead 2, GW11: a unit (it has a pair).
        _forecast(player_code=1, fixture=1, GW=11, lead=2, expected_points=2.0, total_points=1.0),
        # Lead 2, GW12: no pair at lead 2, so not a unit.
        _forecast(player_code=2, fixture=2, GW=12, lead=3, expected_points=9.0, total_points=0.0),
        _forecast(
            player_code=3,
            fixture=3,
            GW=11,
            lead=2,
            expected_points=9.0,
            total_points=0.0,
            season="2023-24",
        ),
        # Lead 1 of the measured origin's own week, and an irregular week at lead 1.
        _forecast(player_code=4, fixture=4, GW=10, lead=1, expected_points=3.0, total_points=1.0),
        _forecast(
            player_code=5,
            fixture=5,
            GW=14,
            origin=14,
            lead=1,
            expected_points=30.0,
            total_points=0.0,
        ),
        # An irregular target week at lead 5: never a unit.
        _forecast(player_code=6, fixture=6, GW=14, lead=5, expected_points=30.0, total_points=0.0),
    ]
    pairs = pd.DataFrame({"season": [SEASON], "GW": [11], "lead": [2]})
    figures = runner.descriptive(
        _labelled(rows), pairs, measured=(10, 14), irregular={SEASON: [14]}
    )
    lead = {row["lead"]: row for row in figures}
    assert (lead[2]["forecast"], lead[2]["mean_signed_error"]) == (1, pytest.approx(1.0))
    assert lead[3]["forecast"] == 0 and lead[3]["mean_signed_error"] is None
    assert (lead[1]["forecast"], lead[1]["mean_signed_error"]) == (1, pytest.approx(2.0))
    assert lead[5]["forecast"] == 0


def test_spearman_pools_origins_rather_than_averaging_them() -> None:
    """Two origins at the same lead, each ranked perfectly inside itself but at offset levels:
    the one pooled coefficient is far from 1, where the mean of per-origin ones would be 1."""

    rows = []
    for origin, week, forecast_offset, realized_offset in (
        (10, 11, 0.0, 0.0),
        (11, 12, 10.0, -10.0),
    ):
        for player in range(3):
            code = 100 * origin + player
            rows.append(
                _forecast(
                    player_code=code,
                    fixture=code,
                    origin=origin,
                    GW=week,
                    lead=2,
                    expected_points=float(player) + forecast_offset,
                    total_points=float(player) + realized_offset,
                )
            )
    pairs = pd.DataFrame({"season": [SEASON, SEASON], "GW": [11, 12], "lead": [2, 2]})
    figures = runner.descriptive(_labelled(rows), pairs, measured=(10, 11), irregular={})
    (lead_two,) = [row for row in figures if row["lead"] == 2]
    frame = pd.DataFrame(rows)
    pooled = frame.expected_points.corr(frame.total_points, method="spearman")
    assert lead_two["spearman_by_position"]["MID"] == pytest.approx(pooled)
    assert pooled < 0


def test_top_ten_optimism_pools_player_fixtures_and_breaks_a_tenth_place_tie_by_code() -> None:
    """A group of 12 and a group of 3: the mean is over 13 player-fixtures, not two group means.
    Three forecasts tie at tenth place; the lowest player code is taken, not the first row."""

    rows = []
    for player in range(9):
        rows.append(
            _forecast(
                player_code=100 + player,
                fixture=100 + player,
                GW=11,
                expected_points=20.0 - player,
                total_points=19.0 - player,
            )
        )
    # Tied at 11.0, in this row order; the lowest code (110) is the only one 1 optimistic.
    for code, optimism in ((190, 50.0), (110, 1.0), (111, 50.0)):
        rows.append(
            _forecast(
                player_code=code,
                fixture=code,
                GW=11,
                expected_points=11.0,
                total_points=11.0 - optimism,
            )
        )
    for player in range(3):
        rows.append(
            _forecast(
                player_code=200 + player,
                fixture=200 + player,
                GW=12,
                expected_points=5.0,
                total_points=1.0,
            )
        )
    pairs = pd.DataFrame({"season": [SEASON, SEASON], "GW": [11, 12], "lead": [2, 2]})
    (lead_two,) = [
        row
        for row in runner.descriptive(_labelled(rows), pairs, measured=(10,), irregular={})
        if row["lead"] == 2
    ]
    # Nine leaders and code 110, each 1 optimistic, then the second group's three, each 4.
    assert lead_two["top_ten_optimism"] == pytest.approx((10 * 1.0 + 3 * 4.0) / 13)


def test_blank_and_double_weeks_are_reported_apart_as_units_pairs_and_a_mean_over_pairs() -> None:
    """Two irregular target weeks at lead 5 with 3 and 1 pairs: 2 units, 4 pairs, and the mean
    over the pairs, not over the weeks. They enter no primary pair."""

    rows = []
    for origin, week, players in ((10, 14, 3), (11, 15, 1)):
        for player in range(players):
            code = 1000 * week + player
            rows.append(
                _forecast(
                    player_code=code,
                    fixture=code,
                    origin=origin,
                    GW=week,
                    lead=5,
                    expected_points=3.0,
                    total_points=1.0,
                )
            )
            rows.append(
                _forecast(
                    player_code=code,
                    fixture=code,
                    origin=week,
                    GW=week,
                    lead=1,
                    expected_points=1.0 + player,
                    total_points=1.0,
                )
            )
    irregular = {SEASON: [14, 15]}
    report = runner.kept_apart(_labelled(rows), measured=(10, 11), irregular=irregular)
    # e_5^2 is 4 throughout; e_1^2 is 0, 1 and 4 in week 14 and 0 in week 15.
    assert report == {"5": {"units": 2, "pairs": 4, "mean_difference": pytest.approx(11 / 4)}}
    assert runner.paired_differences(_labelled(rows), measured=(10, 11), irregular=irregular).empty
