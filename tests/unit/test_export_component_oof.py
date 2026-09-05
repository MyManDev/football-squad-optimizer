"""Tests for the Phase C out-of-fold export.

The fold walk is exercised on a synthetic frame rather than on the archive, because the
suite is offline by design. What the archive run adds is a digest, and that belongs in the
export's own record rather than in a test that would need a data store to pass.
"""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scripts.export_component_oof import (
    _DERIVED_FLOAT_COLUMNS,
    LOCKED_HOLDOUT_SEASON,
    OOF_COLUMNS,
    OOF_CONTRACT_VERSION,
    PUBLIC_POINTS_BOUND,
    ROSTER_COLUMNS,
    ROSTER_CONTRACT_VERSION,
    build_decision_roster,
    build_oof_table,
    main,
)

from squadopt.backtest.splits import DecisionPoint
from squadopt.data.errors import DataError
from squadopt.features.component_targets import build_component_targets
from squadopt.features.evidence import EVIDENCE_COLUMNS
from squadopt.prediction.component_dataset import (
    build_component_frame,
    component_feature_columns,
)
from squadopt.prediction.component_models import ComponentModelConfig
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE

SEASON = "2024-25"
SEASON_ORDER = (SEASON,)
FEATURES = component_feature_columns()
SMALL = ComponentModelConfig(minimum_training_rows=10)


def _panel_for(gameweeks: int, players: int) -> pd.DataFrame:
    """The canonical panel the frame and the roster are both built from."""

    rows = []
    for gameweek in range(1, gameweeks + 1):
        for player in range(1, players + 1):
            plays = (player + gameweek) % 5 != 0
            rows.append((gameweek, player, 90 if plays else 0, 3 + player % 4 if plays else 0))
    raw = pd.DataFrame(rows, columns=["gameweek", "player_id", "minutes", "total_points"])
    return pd.DataFrame(
        {
            "season": pd.Series(SEASON, index=raw.index, dtype="string"),
            "gameweek": raw["gameweek"].astype("int64"),
            "player_id": raw["player_id"].astype("int64"),
            "name": ("P" + raw["player_id"].astype(str)).astype("string"),
            "team_id": pd.Series(1, index=raw.index, dtype="int64"),
            "position": pd.Series("MID", index=raw.index, dtype="string"),
            "price_tenths": (40 + raw["player_id"]).astype("int64"),
            "minutes": raw["minutes"].astype("int64"),
            "total_points": raw["total_points"].astype("int64"),
        }
    )


def _frame(gameweeks: int, players: int) -> pd.DataFrame:
    panel = _panel_for(gameweeks, players)
    raw = panel.loc[:, ["gameweek", "player_id"]]
    features = panel.loc[:, ["season", "gameweek", "player_id", "price_tenths"]].copy(deep=True)
    for offset, column in enumerate(FEATURES, start=1):
        if column == "price_tenths":
            continue
        if column in ("fixture_count", "home_fixture_count"):
            features[column] = pd.Series(1, index=raw.index, dtype="int64")
        else:
            features[column] = (raw["player_id"] % 7 * offset + raw["gameweek"]).astype("float64")
    return build_component_frame(features, build_component_targets(panel))


def _decisions(gameweeks: range) -> tuple[DecisionPoint, ...]:
    return tuple(DecisionPoint(season=SEASON, gameweek=gameweek) for gameweek in gameweeks)


# --- shape ------------------------------------------------------------------


def test_the_table_carries_the_declared_columns_in_order() -> None:
    table, _ = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )

    assert tuple(table.columns) == OOF_COLUMNS
    assert table["contract_version"].unique().tolist() == [OOF_CONTRACT_VERSION]


def test_every_row_is_labelled_with_the_fold_that_produced_it() -> None:
    """`fold_id` is the join key the evaluation side folds on, so it must match the row."""

    table, walk = build_oof_table(
        _frame(6, 20), _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )

    expected = SEASON + "-gw0" + table["target_gameweek"].astype(str)
    assert table["fold_id"].tolist() == expected.tolist()
    assert walk.scored_folds == 5


def test_one_row_per_player_per_decision() -> None:
    table, _ = build_oof_table(
        _frame(6, 20), _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )

    keys = ["season", "target_gameweek", "player_id"]
    assert not bool(table.duplicated(subset=keys).any())
    assert len(table) == 5 * 20


# --- missingness ------------------------------------------------------------


def test_the_decision_timestamp_is_missing_on_every_archive_row() -> None:
    """The archive publishes no deadline and one cannot be recovered from a kickoff time.

    Missing is the honest value. Forging it would forge the single field every leakage
    argument rests on, which is why `data/schema.py` refuses to do it for fixtures too.
    """

    table, _ = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )

    assert bool(table["decision_timestamp_utc"].isna().all())


def test_the_start_component_is_missing_in_the_export() -> None:
    table, _ = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )

    assert bool(table["start_probability"].isna().all())
    assert bool(table["start_target"].isna().all())


def test_a_fold_with_too_little_history_is_recorded_and_takes_the_fallback() -> None:
    """The refusal is visible in two places: the row's route and the walk summary.

    The threshold is raised for this test rather than contrived in the data, because the
    early folds of a real season are thin for a different reason -- a first gameweek has
    no rolling history at all, so its rows carry no features -- and a synthetic frame with
    every feature present cannot reproduce that. What is asserted here is the behaviour
    when the guard fires, whatever made it fire.
    """

    demanding = ComponentModelConfig(minimum_training_rows=100)

    table, walk = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=demanding
    )

    first = table.loc[table["target_gameweek"] == 2]
    assert f"{SEASON}-gw02" in walk.refused_folds
    assert first["composition_route"].unique().tolist() == [DIRECT_CONTROL_ROUTE]
    assert bool(first["control_expected_points"].isna().all())

    later = table.loc[table["target_gameweek"] == 8]
    assert f"{SEASON}-gw08" not in walk.refused_folds
    assert later["composition_route"].unique().tolist() == [COMPONENT_MODEL_ROUTE]


# --- determinism ------------------------------------------------------------


def test_the_same_frame_twice_gives_the_same_table() -> None:
    frame = _frame(8, 20)
    decisions = _decisions(range(2, 9))

    first, first_walk = build_oof_table(frame, decisions, season_order=SEASON_ORDER, config=SMALL)
    second, second_walk = build_oof_table(frame, decisions, season_order=SEASON_ORDER, config=SMALL)

    assert_frame_equal(first, second)
    assert first_walk == second_walk


def test_the_walk_does_not_modify_the_frame_it_reads() -> None:
    frame = _frame(6, 20)
    before = frame.copy(deep=True)

    build_oof_table(frame, _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL)

    assert_frame_equal(frame, before)


def test_a_decision_with_no_population_produces_nothing_rather_than_an_empty_table() -> None:
    frame = _frame(4, 10)

    with pytest.raises(DataError, match="No decision produced"):
        build_oof_table(frame, _decisions(range(90, 92)), season_order=SEASON_ORDER, config=SMALL)


# --- the holdout guard ------------------------------------------------------


def test_the_locked_holdout_is_refused_before_anything_is_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal precedes the archive check, so the season cannot be read even by accident."""

    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--seasons",
            f"2024-25,{LOCKED_HOLDOUT_SEASON}",
            "--archive-root",
            "does-not-exist",
        ],
    )

    assert main() == 1
    assert LOCKED_HOLDOUT_SEASON in capsys.readouterr().out


def test_a_dirty_working_tree_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A recorded commit only reproduces an artifact if that commit was the tree.

    The archive root is deliberately absent, which is what proves the refusal precedes the
    archive check. A precondition that only fires when a data store happens to be present
    is one this suite cannot test -- and the first version of this test passed locally and
    failed in CI for exactly that reason.
    """

    monkeypatch.setattr("sys.argv", ["export_component_oof", "--archive-root", "does-not-exist"])
    monkeypatch.setattr("scripts.export_component_oof._git_revision", lambda: ("abc1234", True))

    assert main() == 1
    assert "uncommitted changes" in capsys.readouterr().out


def test_an_empty_season_list_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["export_component_oof", "--seasons", " , "])

    assert main() == 1
    assert "at least one season" in capsys.readouterr().out.lower()


# --- the control arm stays a control ----------------------------------------


def test_no_phase_b_evidence_column_reaches_the_export() -> None:
    """This is the control arm: it must reproduce with no optional evidence at all.

    Compared against the evidence-*specific* columns rather than the whole evidence
    schema, because the two contracts legitimately share their key and version names --
    `season`, `player_id`, `target_gameweek`, `contract_version`. Sharing a key is what
    makes the two tables joinable later; carrying an evidence value is what would make
    this one a candidate.
    """

    evidence_only = {
        column
        for column in EVIDENCE_COLUMNS
        if column.startswith(("elite_", "overall_", "transfers_", "net_transfers", "availability_"))
        or column in ("chance_of_playing_next_round", "official_news_present")
    }

    assert evidence_only
    assert set(OOF_COLUMNS) & evidence_only == set()


# --- per-fold provenance ----------------------------------------------------


def test_a_fold_is_never_in_its_own_training_set() -> None:
    """The record the chronology check reads, asserted rather than trusted."""

    _, walk = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )

    assert walk.folds
    for record in walk.folds:
        assert record.fold_id not in record.training_fold_ids


def test_the_training_cutoff_is_the_last_fold_before_the_decision() -> None:
    """The ordinal analogue of training_cutoff_utc, which the archive cannot supply."""

    _, walk = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )
    by_id = {record.fold_id: record for record in walk.folds}

    assert by_id[f"{SEASON}-gw05"].training_cutoff_fold_id == f"{SEASON}-gw04"
    assert by_id[f"{SEASON}-gw05"].training_fold_ids == tuple(
        f"{SEASON}-gw0{gameweek}" for gameweek in range(1, 5)
    )


def test_both_utc_timestamps_are_absent_and_that_is_recorded_not_forged() -> None:
    """`data/schema.py` refuses to recover a deadline from a kickoff time; so does this."""

    _, walk = build_oof_table(
        _frame(6, 20), _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )

    for record in walk.folds:
        assert record.decision_timestamp_utc is None
        assert record.training_cutoff_utc is None


def test_the_training_key_digest_covers_the_rows_not_only_the_fold_labels() -> None:
    """Two frames agreeing on folds but differing in rows must not share a digest."""

    decisions = _decisions(range(2, 7))
    _, first = build_oof_table(_frame(6, 20), decisions, season_order=SEASON_ORDER, config=SMALL)
    _, fewer = build_oof_table(_frame(6, 19), decisions, season_order=SEASON_ORDER, config=SMALL)

    same_fold = f"{SEASON}-gw05"
    first_digest = next(r.training_key_digest for r in first.folds if r.fold_id == same_fold)
    fewer_digest = next(r.training_key_digest for r in fewer.folds if r.fold_id == same_fold)
    assert first_digest != fewer_digest


def test_each_record_carries_the_three_contract_versions() -> None:
    _, walk = build_oof_table(
        _frame(6, 20), _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )

    for record in walk.folds:
        assert record.model_version
        assert record.feature_contract_version
        assert record.target_contract_version


# --- the public points bound -------------------------------------------------


def test_the_public_bound_holds_on_the_exported_values() -> None:
    """max(0, p * raw), recomputable from the file rather than only from memory.

    Every column is written at nine decimals, so the derived columns are composed from the
    *rounded* independent ones. Deriving them from unrounded inputs left a discrepancy near
    1e-9 on the real table, which a reader recomputing the identity would have found.
    """

    table, _ = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )
    modelled = table.loc[table["composition_route"] == "component_model"]

    expected = (
        (
            modelled["appearance_probability"].astype("float64")
            * modelled["raw_expected_points_if_appearance"].astype("float64")
        )
        .clip(lower=0.0)
        .round(9)
    )
    assert modelled["control_expected_points"].astype("float64").tolist() == expected.tolist()
    assert bool((modelled["control_expected_points"].astype("float64") >= 0.0).all())
    assert _DERIVED_FLOAT_COLUMNS == (
        "expected_points_if_appearance",
        "control_expected_points",
    )
    assert "max(0, appearance_probability" in PUBLIC_POINTS_BOUND


def test_the_conditional_start_column_is_present_and_missing() -> None:
    table, _ = build_oof_table(
        _frame(6, 20), _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )

    assert "q_start_given_appearance" in table.columns
    assert bool(table["q_start_given_appearance"].isna().all())


# --- the decision roster ----------------------------------------------------


def test_the_roster_covers_exactly_the_scored_population() -> None:
    """Same key, same rows: a decision-level comparison cannot score a different set."""

    frame = _frame(6, 20)
    table, _ = build_oof_table(
        frame, _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )
    roster = build_decision_roster(_panel_for(6, 20), table)

    keys = ["season", "target_gameweek", "player_id"]
    assert tuple(roster.columns) == ROSTER_COLUMNS
    assert len(roster) == len(table)
    assert roster.loc[:, keys].equals(table.loc[:, keys])
    assert roster["contract_version"].unique().tolist() == [ROSTER_CONTRACT_VERSION]


def test_the_roster_carries_no_ownership_column() -> None:
    """selected_by_percent's snapshot timing is unproven, so it fails the condition."""

    assert "selected_by_percent" not in ROSTER_COLUMNS
    assert not any(column.endswith("selected_by_percent") for column in ROSTER_COLUMNS)


def test_a_scored_row_with_no_roster_record_is_refused() -> None:
    """Scoring a player the roster cannot describe would compare two populations."""

    frame = _frame(6, 20)
    table, _ = build_oof_table(
        frame, _decisions(range(2, 7)), season_order=SEASON_ORDER, config=SMALL
    )
    thinned = _panel_for(6, 20)
    thinned = thinned.loc[thinned["player_id"] != 7]

    with pytest.raises(DataError, match="no roster record"):
        build_decision_roster(thinned, table)


# --- what the manifest has to let a consumer do without the file -------------


def test_the_declared_dtypes_are_the_ones_the_written_frame_carries() -> None:
    """A CSV has no dtypes, so the manifest is where the declared ones live.

    Read back with a plain `read_csv`, the nullable columns become float64 and one Int64
    column becomes float64 the moment a value is missing. An evaluator aligning its schema
    needs what was declared, and the manifest reports it from the frame that was written
    rather than from a second list that could drift.
    """

    table, _ = build_oof_table(
        _frame(8, 20), _decisions(range(2, 9)), season_order=SEASON_ORDER, config=SMALL
    )
    declared = {str(column): str(dtype) for column, dtype in table.dtypes.items()}

    assert set(declared) == set(OOF_COLUMNS)
    assert declared["appearance_probability"] == "Float64"
    assert declared["q_start_given_appearance"] == "Float64"
    assert declared["start_target"] == "Int64"
    assert declared["composition_route"] == "string"
