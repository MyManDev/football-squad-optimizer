"""The fixed measurement protocol is wired causally without opening any real archive."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scripts import measure_football_role_minutes as study


def observed(season="2024-25", week=11):
    return pd.DataFrame(
        {
            "season": season,
            "GW": week,
            "position": ["GK", "DEF", "MID", "FWD"],
            "player_code": range(1, 5),
            "fixture": week,
            "club": 1,
            "opponent": 2,
            "home": 1.0,
            "kickoff": pd.Timestamp(f"{season[:4]}-08-01T15:00Z") + pd.Timedelta(weeks=week),
            "minutes": [0, 40, 75, 90],
            "m_bin": [0, 1, 2, 3],
            "starts": [0, 1, 0, 1],
            "appeared": [0, 1, 1, 1],
            "long": [0, 0, 1, 1],
            "goals_scored": [0, 0, 0, 1],
            "assists": 0,
            "clean_sheets": 0,
            "dc_event": [0, 1, 0, 1],
            "total_points": [0, 1, 2, 6],
        }
    )


def forecast(actual, *, joint=False):
    result = pd.DataFrame(index=actual.index)
    result["expected_points"] = actual.total_points + (1 if joint else 0)
    result["expected_minutes"] = actual.minutes + (1 if joint else 0)
    result["appearance_probability"] = actual.appeared
    result["p60"] = actual.long
    result["goals"] = actual.goals_scored
    result["assists"] = actual.assists
    result["clean_sheet_probability"] = actual.clean_sheets
    result["defcon_probability"] = actual.dc_event
    for b in range(4):
        result[f"minute_probability_{b}"] = actual.m_bin.eq(b).astype(float)
    if joint:
        result["zero_probability"] = actual.minutes.eq(0).astype(float)
        result["start_probability"] = (actual.minutes.gt(0) & actual.starts.eq(1)).astype(float)
        result["cameo_probability"] = (actual.minutes.gt(0) & actual.starts.eq(0)).astype(float)
    return result


def test_roles_use_actual_recorded_starts_and_control_has_no_invented_role_score():
    actual = observed()
    control = study.losses(actual, forecast(actual))
    full = study.losses(actual, forecast(actual, joint=True))
    assert control["role_nll"] is None and control["role_scored_rows"] == 0
    assert full["role_nll"] == 0 and full["role_brier"] == 0
    assert full["role_scored_rows"] == 4  # Includes short starter and long cameo.
    assert full["dc_rows"] == 0 and full["dc_brier"] is None
    current = observed(study.CURRENT_SEASON)
    assert study.losses(current, forecast(current))["dc_rows"] == 3
    missing = actual.assign(starts=np.nan)
    unknown = forecast(actual, joint=True)
    unknown[["start_probability", "cameo_probability"]] = np.nan
    scored = study.losses(missing, unknown)
    assert scored["role_known_rows"] == 1 and scored["role_unknown_rows"] == 3
    assert scored["role_scored_rows"] == 0 and scored["role_brier"] is None


def test_summary_pairs_equal_origins_retains_negative_positive_missing_and_bias():
    records = []
    for fold, before, after in (("a", 3.0, 2.0), ("b", 1.0, 4.0), ("c", 2.0, 2.0)):
        for arm, score in zip(study.ARMS, (before, after), strict=True):
            records.append(
                {
                    "fold": fold,
                    "position": "ALL",
                    "arm": arm,
                    "points_mae": score,
                    "points_bias": score,
                    "role_nll": None if arm == "frozen_v1" else score,
                }
            )
    records.append({"fold": "unpaired", "position": "ALL", "arm": "joint_role", "points_mae": 99.0})
    summary = {r["metric"]: r for r in study.summarize(records)}
    score = summary["points_mae"]
    assert score["paired_origins"] == 3
    assert score["joint_minus_frozen"] == pytest.approx(2 / 3)
    assert (score["negative_deltas"], score["positive_deltas"], score["ties"]) == (1, 1, 1)
    assert summary["role_nll"]["paired_origins"] == 0
    assert summary["role_nll"]["joint_minus_frozen"] is None
    assert summary["points_bias"]["interpretation"] == "signed_bias_not_ranked"


@pytest.mark.parametrize(
    "selection", [(), ("2025-26",), (*study.SEASONS, "2025-26"), study.SEASONS[::-1]]
)
def test_allowlist_refuses_before_any_io(monkeypatch, tmp_path, selection):
    monkeypatch.setattr(study, "_hashes", lambda *_: pytest.fail("No file may be opened."))
    with pytest.raises(ValueError, match="Explicit training seasons"):
        study.run(tmp_path / "archive", tmp_path / "result", training_seasons=selection)
    assert not (tmp_path / "result").exists()


def fake_world(monkeypatch):
    history = pd.concat(
        [
            observed("2022-23", 1),
            *[observed(s, 1) for s in study.SEASONS[1:]],
            *[observed(s, w) for s, w in study.ORIGINS],
        ],
        ignore_index=True,
    )
    calls = []

    def archive(_root, *, seasons):
        assert seasons == study.SEASONS
        return history.copy()

    def training(frame, *, prior_only_season):
        assert prior_only_season == "2022-23"
        return frame.loc[frame.season.ne(prior_only_season)].copy()

    class Model:
        def __init__(self, train, past, *, cutoff):
            assert not train.empty and not past.empty
            assert (past.kickoff + pd.Timedelta(hours=3) < cutoff).all()
            assert (train.kickoff + pd.Timedelta(hours=3) < cutoff).all()
            self.cutoff = cutoff
            self.train = train
            self.past = past
            self.role_metadata = {"known_start_label_rows": len(train), "minute_prior_rows": 10.0}
            calls.append(self)

        def predict(self, target):
            season, week = str(target.season.iloc[0]), int(target.GW.iloc[0])
            for frame in (self.train, self.past):
                assert (
                    (frame.season < season) | (frame.season.eq(season) & frame.GW.lt(week))
                ).all()
            return forecast(target, joint=True)

    monkeypatch.setattr(study, "archive_history", archive)
    monkeypatch.setattr(study, "causal_training", training)
    monkeypatch.setattr(study, "JointRoleFootballModel", Model)
    monkeypatch.setattr(
        study.FixtureFootballModel, "predict", lambda self, target: forecast(target)
    )
    monkeypatch.setattr(
        study,
        "football_features",
        lambda _past, target, _cutoff: pd.DataFrame(
            {f: 0.0 for f in study.FEATURES}, index=target.index
        ),
    )
    monkeypatch.setattr(study, "_hashes", lambda _root, names: dict.fromkeys(names, "a" * 64))

    # The on-disk preregistration is asserted before the first fit by the wrapper below.
    def output_at(path):
        original = Model.__init__

        def init(self, *args, **kwargs):
            assert (path / "protocol.json").exists()
            assert (path / "input-hashes.json").exists()
            assert (path / "folds.json").exists()
            original(self, *args, **kwargs)

        monkeypatch.setattr(Model, "__init__", init)

    return history, calls, output_at


def test_fixed_eight_origins_one_fit_each_and_no_extra_control_fit(monkeypatch, tmp_path):
    _, calls, output_at = fake_world(monkeypatch)
    output = tmp_path / "measurement"
    output_at(output)
    assert study.run(tmp_path / "archive", output, training_seasons=study.SEASONS)
    assert len(calls) == 8
    protocol = json.loads((output / "protocol.json").read_text())
    assert protocol["promotion_rule"] is None and not protocol["availability_or_news_backfill"]
    result = json.loads((output / "result.json").read_text())
    assert result["completed_origins"] == 8 and result["candidate_fit_attempts"] == 8
    scores = json.loads((output / "scores.json").read_text())
    assert len(scores) == 8 * 2 * 5
    assert all(r["points_mae"] == (r["arm"] == "joint_role") for r in scores)
    with pytest.raises(FileExistsError):
        study.run(tmp_path / "archive", output, training_seasons=study.SEASONS)


def test_all_current_settled_weeks_added_without_new_archive_season_reads(monkeypatch, tmp_path):
    _, calls, output_at = fake_world(monkeypatch)
    snapshot = SimpleNamespace(
        metadata=SimpleNamespace(
            snapshot_id="synthetic",
            fingerprint="b" * 64,
            captured_at_utc="2026-09-01T12:00Z",
            checksums={"event.json": "c" * 64},
        )
    )
    monkeypatch.setattr(study, "read_snapshot", lambda root, identity: snapshot)
    monkeypatch.setattr(study, "infer_season", lambda capture: study.CURRENT_SEASON)
    monkeypatch.setattr(
        study,
        "read_inputs",
        lambda capture, season: SimpleNamespace(deadline=SimpleNamespace(gameweek=3)),
    )
    monkeypatch.setattr(
        study,
        "captured_history",
        lambda capture, season, gameweek: pd.concat(
            [observed(season, 1), observed(season, 2)], ignore_index=True
        ),
    )
    output = tmp_path / "with-current"
    output_at(output)
    assert study.run(
        tmp_path / "archive",
        output,
        training_seasons=study.SEASONS,
        snapshot_root=tmp_path / "snapshots",
        snapshot_id="synthetic",
    )
    assert len(calls) == 10
    current = json.loads((output / "current-evidence.json").read_text())
    assert current["gameweeks"] == [1, 2] and current["status"] == "available"
    result = json.loads((output / "result.json").read_text())
    assert result["required_origins"] == 10 and not result["predictive_superiority_verified"]


def test_missing_fixed_fold_remains_explicit_failure_and_never_replaced(monkeypatch, tmp_path):
    history, calls, output_at = fake_world(monkeypatch)
    monkeypatch.setattr(
        study,
        "archive_history",
        lambda root, seasons: history.loc[~(history.season.eq("2024-25") & history.GW.eq(35))],
    )
    output = tmp_path / "missing"
    output_at(output)
    assert not study.run(tmp_path / "archive", output, training_seasons=study.SEASONS)
    assert len(calls) == 7
    failure = json.loads((output / "failures.json").read_text())
    assert failure == [{"fold": "2024-25-gw35", "error_type": "ValueError"}]
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "incomplete" and result["required_origins"] == 8
