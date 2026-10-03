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
            result = forecast(target, joint=True)
            if not (self.train.minutes.gt(0) & self.train.starts.isin([0, 1])).any():
                result[["start_probability", "cameo_probability"]] = np.nan
            return result

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
            protocol = json.loads((path / "protocol.json").read_text())
            assert protocol["role_diagnostics"]["probability_bin_edges"] == [
                i / 10 for i in range(11)
            ]
            assert protocol["role_diagnostics"]["additional_fits"] == 0
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
    assert protocol["contract"] == result["contract"] == "football_joint_role_measurement_v2"
    assert protocol["fit_budget"]["role_baseline_additional_fits"] == 0
    assert result["role_baseline_additional_fits"] == 0
    budgets = json.loads((output / "budgets.json").read_text())
    assert all(b["appearance_q_identical"] for b in budgets)
    assert all(
        b["control_additional_fits"] == b["role_baseline_additional_fits"] == 0 for b in budgets
    )
    roles = json.loads((output / "role-scores.json").read_text())
    assert len(roles) == 8 * 2 * 5
    assert {r["arm"] for r in scores} == set(study.ARMS)
    assert {r["arm"] for r in roles} == set(study.ROLE_ARMS)
    for record in scores:
        if record["arm"] == "frozen_v1":
            assert record["role_nll"] is None
        else:
            paired = next(
                r
                for r in roles
                if (r["fold"], r["position"], r["arm"])
                == (record["fold"], record["position"], record["arm"])
            )
            assert all(paired[k] == record[k] for k in paired if k.startswith("role_"))
    old_comparison = json.loads((output / "comparison.json").read_text())
    assert old_comparison == study.summarize(scores)
    assert all(r["paired_origins"] == 0 for r in old_comparison if r["metric"] == "role_nll")
    role_comparison = json.loads((output / "role-comparison.json").read_text())
    assert all(r["paired_origins"] == 8 for r in role_comparison)
    diagnostics = json.loads((output / "role-diagnostics.json").read_text())
    assert len(diagnostics) == 8 * 2 * 5
    for record in diagnostics:
        same = next(
            r
            for r in diagnostics
            if (r["fold"], r["position"]) == (record["fold"], record["position"])
            and r["arm"] != record["arm"]
        )
        assert same["appearance"] == record["appearance"]
        for name in ("appearance", "conditional_start"):
            assert len(record[name]["bins"]) == 10
            assert sum(cell["count"] for cell in record[name]["bins"]) == record[name]["rows"]
        assert not {"player_id", "player_code", "probabilities", "labels"} & record.keys()
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


def test_pooled_reference_counts_known_appearances_only_and_preserves_inputs():
    train = pd.DataFrame(
        {"minutes": [0, 40, 75, 90, 15, 90], "starts": [0, 1, 0, 1, np.nan, np.nan]}
    )
    control = pd.DataFrame({"appearance_probability": [0.0, 0.25, 0.75, 1.0]})
    joint = control.copy(deep=True)
    before = [frame.copy(deep=True) for frame in (train, control, joint)]
    prediction, metadata = study.pooled_role_baseline(train, control, joint)
    assert metadata["known_start_label_rows"] == 3
    assert metadata["unknown_start_label_rows"] == 2
    assert metadata["training_appearance_rows"] == 5
    assert metadata["starting_label_rows"] == 2
    assert metadata["pooled_start_given_appearance"] == pytest.approx(2 / 3)
    np.testing.assert_allclose(prediction.sum(axis=1), 1)
    np.testing.assert_allclose(prediction.start_probability, [0, 1 / 6, 0.5, 2 / 3])
    np.testing.assert_allclose(prediction.cameo_probability, [0, 1 / 12, 0.25, 1 / 3])
    for actual, saved in zip((train, control, joint), before, strict=True):
        pd.testing.assert_frame_equal(actual, saved)


@pytest.mark.parametrize("label", [0, 1])
def test_pooled_reference_supports_boundary_rates_and_shared_q(label):
    train = pd.DataFrame({"minutes": [40, 90], "starts": [label, label]})
    prediction = pd.DataFrame({"appearance_probability": [0.0, 1.0]})
    baseline, metadata = study.pooled_role_baseline(train, prediction, prediction)
    actual = pd.DataFrame({"minutes": [0, 75], "starts": [0, label]})
    score = study.role_losses(actual, baseline)
    assert metadata["pooled_start_given_appearance"] == label
    assert score["role_scored_rows"] == 2
    assert score["role_nll"] == score["role_brier"] == 0
    # The existing declared logarithmic floor also bounds a wrong certain role.
    actual.loc[1, "starts"] = 1 - label
    wrong = study.role_losses(actual, baseline)
    assert wrong["role_nll"] == pytest.approx(-np.log(study.LOG_FLOOR) / 2)
    assert wrong["role_brier"] == 1.0


@pytest.mark.parametrize("labels", [[np.nan, np.nan], None])
def test_no_known_appearance_labels_remain_unscored(labels):
    train = pd.DataFrame({"minutes": [40, 90]})
    if labels is not None:
        train["starts"] = labels
    actual = observed()
    prediction = forecast(actual)
    baseline, metadata = study.pooled_role_baseline(train, prediction, prediction)
    assert metadata["status"] == "unavailable_no_known_start_labels"
    assert metadata["pooled_start_given_appearance"] is None
    assert baseline.start_probability.isna().all()
    score = study.role_losses(actual, baseline)
    assert score["role_known_rows"] == 4 and score["role_scored_rows"] == 0
    assert score["role_nll"] is None and score["role_brier"] is None


@pytest.mark.parametrize("kind", ["changed_q", "nan", "negative", "above_one", "reordered"])
def test_pooled_reference_refuses_mismatched_or_invalid_q(kind):
    actual = observed()
    control, joint = forecast(actual), forecast(actual, joint=True)
    joint["appearance_probability"] = joint.appearance_probability.astype(float)
    if kind == "reordered":
        joint = joint.iloc[::-1]
    else:
        joint.loc[0, "appearance_probability"] = {
            "changed_q": np.nextafter(0.0, 1.0),
            "nan": np.nan,
            "negative": -0.01,
            "above_one": 1.01,
        }[kind]
    with pytest.raises(ValueError, match="Restricted role"):
        study.pooled_role_baseline(actual, control, joint)


def test_pooled_reference_receives_exact_causal_train_not_priors_or_targets(monkeypatch, tmp_path):
    history, calls, output_at = fake_world(monkeypatch)
    modified = history.copy(deep=True)
    positive = modified.minutes.gt(0)
    # Opposite sentinels distinguish prior-only history and target/future outcomes.
    modified.loc[positive & modified.season.eq("2022-23"), "starts"] = 1
    late = modified.season.gt("2023-24") | (modified.season.eq("2023-24") & modified.GW.ge(11))
    modified.loc[positive & late, "starts"] = 0
    monkeypatch.setattr(study, "archive_history", lambda root, seasons: modified.copy())
    output = tmp_path / "causal-role"
    output_at(output)
    assert study.run(tmp_path / "archive", output, training_seasons=study.SEASONS)
    assert len(calls) == 8
    budgets = json.loads((output / "budgets.json").read_text())
    first = budgets[0]["role_baseline"]
    assert budgets[0]["fold"] == "2023-24-gw11"
    assert first["known_start_label_rows"] == 3 and first["starting_label_rows"] == 2
    assert first["pooled_start_given_appearance"] == pytest.approx(2 / 3)


def test_role_summary_pairs_equal_origins_with_losses_missing_support_and_counts():
    records = []
    for fold, rows, before, after in (
        ("a", 1, 3.0, 2.0),
        ("b", 1000, 1.0, 4.0),
        ("c", 10, 2.0, 2.0),
        ("unsupported", 50, None, 0.5),
    ):
        for arm, score in zip(study.ROLE_ARMS, (before, after), strict=True):
            records.append(
                {
                    "fold": fold,
                    "position": "ALL",
                    "arm": arm,
                    "rows": rows,
                    "role_known_rows": rows,
                    "role_unknown_rows": 0,
                    "role_scored_rows": rows if score is not None else 0,
                    "role_nll": score,
                    "role_brier": score,
                }
            )
    records.append({**records[0], "fold": "missing-arm", "arm": "joint_role", "role_nll": 99.0})
    summary = [r for r in study.summarize_roles(records) if r["position"] == "ALL"]
    for row in summary:
        assert row["paired_origins"] == 3 and row["unpaired_origins"] == 2
        assert row["paired_scored_rows"] == 1011
        assert row["joint_minus_pooled"] == pytest.approx(2 / 3)
        assert (row["negative_deltas"], row["positive_deltas"], row["ties"]) == (1, 1, 1)
    unequal = [dict(r) for r in records]
    unequal[1]["role_scored_rows"] = 2
    with pytest.raises(ValueError, match="same nonempty population"):
        study.summarize_roles(unequal)
    with pytest.raises(ValueError, match="unique declared arms"):
        study.summarize_roles([*records, records[0]])


def test_q_mismatch_marks_folds_failed_without_partial_arm_results(monkeypatch, tmp_path):
    _, calls, output_at = fake_world(monkeypatch)
    original = study.JointRoleFootballModel.predict

    def changed(self, target):
        result = original(self, target)
        result.loc[result.index[0], "appearance_probability"] = 0.1
        return result

    monkeypatch.setattr(study.JointRoleFootballModel, "predict", changed)
    output = tmp_path / "mismatch"
    output_at(output)
    assert not study.run(tmp_path / "archive", output, training_seasons=study.SEASONS)
    assert len(calls) == 8
    result = json.loads((output / "result.json").read_text())
    assert result["completed_origins"] == 0 and result["candidate_fit_attempts"] == 8
    assert json.loads((output / "scores.json").read_text()) == []
    assert json.loads((output / "role-scores.json").read_text()) == []
    assert json.loads((output / "role-diagnostics.json").read_text()) == []
    assert len(json.loads((output / "failures.json").read_text())) == 8


def test_missing_training_support_is_null_not_a_failed_fold(monkeypatch, tmp_path):
    history, calls, output_at = fake_world(monkeypatch)
    monkeypatch.setattr(
        study, "archive_history", lambda root, seasons: history.assign(starts=np.nan)
    )
    output = tmp_path / "unsupported"
    output_at(output)
    assert study.run(tmp_path / "archive", output, training_seasons=study.SEASONS)
    assert len(calls) == 8
    budgets = json.loads((output / "budgets.json").read_text())
    assert all(b["role_baseline"]["pooled_start_given_appearance"] is None for b in budgets)
    roles = json.loads((output / "role-scores.json").read_text())
    assert all(r["role_scored_rows"] == 0 and r["role_nll"] is None for r in roles)
    summary = json.loads((output / "role-comparison.json").read_text())
    assert all(r["paired_origins"] == 0 and r["joint_minus_pooled"] is None for r in summary)


def test_role_diagnostics_unfloored_decomposition_and_population_are_explicit():
    actual = pd.DataFrame({"minutes": [0, 40, 75, 90, 30], "starts": [0, 1, 0, 1, np.nan]})
    q = pd.Series([0.2, 0.8, 0.6, 0.5, 0.7])
    r = pd.Series([0.5, 0.7, 0.4, 0.6, 0.2])
    prediction = pd.DataFrame(
        {"zero_probability": 1 - q, "start_probability": q * r, "cameo_probability": q * (1 - r)}
    )
    before = prediction.copy(deep=True)
    diagnostic = study.role_diagnostics(actual, prediction, q)
    appearance, conditional = diagnostic["appearance"], diagnostic["conditional_start"]
    assert (diagnostic["role_known_rows"], diagnostic["role_unknown_rows"]) == (4, 1)
    assert appearance["rows"] == 4 and conditional["rows"] == 3
    assert diagnostic["conditional_q_zero_rows"] == 0
    assert diagnostic["conditional_unsupported_rows"] == 0
    assert appearance["floor_active_rows"] == conditional["floor_active_rows"] == 0
    assert diagnostic["joint_floor_active_rows"] == 0
    assert appearance["brier"] == pytest.approx((0.2**2 + 0.2**2 + 0.4**2 + 0.5**2) / 4)
    assert conditional["brier"] == pytest.approx((0.3**2 + 0.4**2 + 0.4**2) / 3)
    joint = study.role_losses(actual, prediction)
    # Conditional loss has three rows, while joint and appearance have four.
    assert joint["role_nll"] == pytest.approx(appearance["nll"] + 3 / 4 * conditional["nll"])
    pd.testing.assert_frame_equal(prediction, before)


def test_q_zero_is_undefined_for_conditional_role_but_counted_in_appearance_loss():
    actual = pd.DataFrame({"minutes": [75, 0, 40, 75, 90], "starts": [1, 0, 1, 0, np.nan]})
    q = pd.Series([0.0, 0.9, 1e-8, 0.4, 0.7])
    r = pd.Series([0.6, 0.5, 1e-8, 1.0, 0.2])
    prediction = pd.DataFrame(
        {"zero_probability": 1 - q, "start_probability": q * r, "cameo_probability": q * (1 - r)}
    )
    diagnostic = study.role_diagnostics(actual, prediction, q)
    assert diagnostic["positive_known_rows"] == 3
    assert diagnostic["conditional_q_zero_rows"] == 1
    assert diagnostic["appearance"]["rows"] == 4
    assert diagnostic["appearance"]["floor_active_rows"] == 1
    assert diagnostic["conditional_start"]["rows"] == 2
    assert diagnostic["conditional_start"]["floor_active_rows"] == 1
    assert diagnostic["joint_floor_active_rows"] == 3


def test_separately_floored_losses_are_not_claimed_to_decompose_joint_nll():
    actual = pd.DataFrame({"minutes": [40], "starts": [1]})
    q = pd.Series([1e-8])
    prediction = pd.DataFrame(
        {
            "zero_probability": 1 - q,
            "start_probability": q * 1e-8,
            "cameo_probability": q * (1 - 1e-8),
        }
    )
    diagnostic = study.role_diagnostics(actual, prediction, q)
    appearance, conditional = diagnostic["appearance"], diagnostic["conditional_start"]
    joint = study.role_losses(actual, prediction)
    assert appearance["floor_active_rows"] == conditional["floor_active_rows"] == 0
    assert diagnostic["joint_floor_active_rows"] == 1
    assert joint["role_nll"] == pytest.approx(-np.log(study.LOG_FLOOR))
    assert appearance["nll"] + conditional["nll"] == pytest.approx(-2 * np.log(1e-8))
    assert appearance["nll"] + conditional["nll"] > joint["role_nll"]


def test_probability_bins_keep_empty_cells_and_place_boundaries_once():
    probabilities = np.array([i / 10 for i in range(11)])
    diagnostic = study._binary_calibration(probabilities, np.zeros(11))
    assert [cell["count"] for cell in diagnostic["bins"]] == [1] * 9 + [2]
    assert diagnostic["bins"][1]["mean_pred"] == 0.1
    assert diagnostic["bins"][-1]["mean_pred"] == pytest.approx(0.95)
    assert [cell["upper_inclusive"] for cell in diagnostic["bins"]] == [False] * 9 + [True]
    sparse = study._binary_calibration(np.array([0.05, 0.1, 1.0]), np.array([0, 1, 1]))
    assert len(sparse["bins"]) == 10
    empty = sparse["bins"][2]
    assert empty["count"] == 0 and empty["mean_pred"] is None and empty["event_rate"] is None
    no_rows = study._binary_calibration(np.array([]), np.array([]))
    assert no_rows["nll"] is None and no_rows["brier"] is None
    assert all(cell["count"] == 0 and cell["mean_pred"] is None for cell in no_rows["bins"])


def test_log_floor_counts_only_strictly_lower_observed_probabilities():
    diagnostic = study._binary_calibration(
        np.array([0, study.LOG_FLOOR / 2, study.LOG_FLOOR, study.LOG_FLOOR * 2, 1]),
        np.ones(5),
    )
    assert diagnostic["floor_active_rows"] == 2
    assert diagnostic["zero_observed_probability_rows"] == 1
    assert diagnostic["nll"] == pytest.approx(
        -(3 * np.log(study.LOG_FLOOR) + np.log(2 * study.LOG_FLOOR)) / 5
    )


@pytest.mark.parametrize("missing", ["all", "one"])
def test_unavailable_roles_keep_appearance_diagnostics_without_invented_conditional_values(missing):
    actual = observed()
    q = pd.Series([0.0, 0.5, 0.0, 1.0])
    prediction = pd.DataFrame(
        {"zero_probability": 1 - q, "start_probability": np.nan, "cameo_probability": np.nan}
    )
    if missing == "one":
        prediction["start_probability"] = q * 0.5
        prediction["cameo_probability"] = q * 0.5
        prediction.loc[0, "start_probability"] = np.nan
    diagnostic = study.role_diagnostics(actual, prediction, q)
    assert not diagnostic["role_forecast_available"]
    assert diagnostic["appearance"]["rows"] == 4
    assert diagnostic["conditional_start"]["rows"] == 0
    assert diagnostic["conditional_start"]["nll"] is None
    assert diagnostic["conditional_q_zero_rows"] == 1
    assert diagnostic["conditional_unsupported_rows"] == 2
    assert diagnostic["joint_scored_rows"] == 0
    assert diagnostic["joint_floor_active_rows"] is None


def test_tiny_positive_q_is_not_reconstructed_from_rounded_zero_probability():
    actual = pd.DataFrame({"minutes": [40], "starts": [1]})
    q = pd.Series([1e-20])
    prediction = pd.DataFrame(
        {"zero_probability": 1 - q, "start_probability": q * 0.25, "cameo_probability": q * 0.75}
    )
    assert prediction.zero_probability.iloc[0] == 1.0
    diagnostic = study.role_diagnostics(actual, prediction, q)
    assert diagnostic["conditional_q_zero_rows"] == 0
    assert diagnostic["conditional_start"]["rows"] == 1
    assert diagnostic["conditional_start"]["nll"] == pytest.approx(-np.log(0.25))
    assert diagnostic["appearance"]["floor_active_rows"] == 1
