"""Joint-role components reach the existing cited, fixture-bound minute intervention."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scipy.stats import nbinom
from tests.unit.test_minute_evidence import basis_from, claim, documents

from squadopt.live.football_artifact import forecast_digest
from squadopt.live.minute_evidence import apply_explicit_minute_evidence
from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSION
from squadopt.prediction.football_minutes_role import ROLE_MINUTE_VERSION


def joint_documents(*, unknown=False, no_start_shorter=False, dgw=False):
    served, companion, calendar, clubs = documents(eligibility=0.5, dgw=dgw)
    frame = pd.DataFrame(companion["rows"])
    frame["zero_probability"] = frame.minute_probability_0
    frame["unknown_role_probability"] = frame.appearance_probability if unknown else 0.0
    frame["minute_role_status"] = (
        "unavailable_no_known_start_labels" if unknown else "fitted_known_start_labels"
    )
    frame["minute_role_version"] = ROLE_MINUTE_VERSION
    frame["known_start_label_rows"] = 0 if unknown else 96
    frame["unknown_start_label_rows"] = 96 if unknown else 0
    frame["minute_prior_rows"] = 10.0
    for role in ("start", "cameo"):
        for b in (1, 2, 3):
            split = (0.7, 0.6, 0.9)[b - 1]
            if no_start_shorter and b < 3:
                split = 0.0
            fraction = split if role == "start" else 1 - split
            frame[f"{role}_minute_probability_{b}"] = (
                None if unknown else frame[f"minute_probability_{b}"] * fraction
            )
            frame[f"{role}_minute_value_{b}"] = (
                None
                if unknown
                else ((40.0, 80.0, 90.0) if role == "start" else (10.0, 65.0, 90.0))[b - 1]
            )
        frame[role + "_probability"] = (
            None if unknown else sum(frame[f"{role}_minute_probability_{b}"] for b in (1, 2, 3))
        )
    if not unknown:
        expected = np.zeros(len(frame))
        cs = np.zeros(len(frame))
        dc = np.zeros(len(frame))
        threshold = np.where(frame.position.eq("DEF"), 10, 12)
        for b in (1, 2, 3):
            weighted = np.zeros(len(frame))
            for role in ("start", "cameo"):
                p = frame[f"{role}_minute_probability_{b}"].to_numpy(float)
                minutes = frame[f"{role}_minute_value_{b}"].to_numpy(float)
                weighted += p * minutes
                expected += p * minutes
                if b >= 2:
                    cs += p * np.exp(-1.5 * minutes / 90)
                mu = np.maximum(8.0 * minutes / 90, 1e-12)
                dc += p * nbinom.sf(threshold - 1, 4.0, 4.0 / (4.0 + mu))
            frame[f"minute_value_{b}"] = weighted / frame[f"minute_probability_{b}"].to_numpy(float)
            if b == 3:
                frame[f"minute_value_{b}"] = frame[f"minute_value_{b}"].clip(lower=90.0)
        dc[frame.position.eq("GK").to_numpy()] = 0
        frame["expected_minutes"] = expected
        frame["clean_sheet_probability"] = cs
        frame["defcon_probability"] = dc
        goal = frame.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
        clean = frame.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0})
        frame["raw_expected_points"] = (
            frame.appearance_probability
            + frame.p60
            + goal * frame.goals
            + 3 * frame.assists
            + clean * cs
            + 2 * dc
            + frame.appearance_probability * frame.residual_if_appearance
        )
        frame["expected_points"] = frame.raw_expected_points.clip(lower=0)
    frame["expected_minutes_if_appearance"] = frame.expected_minutes / frame.appearance_probability
    scores = frame.groupby(["GW", "player_code"]).expected_points.sum()
    for row in served["rows"]:
        row["expected_points"] = float(scores.loc[row["gameweek"], row["player_id"]])
    for document in (served, companion):
        document["model_version"] = JOINT_ROLE_MODEL_VERSION
        document["role_metadata"] = {
            "version": ROLE_MINUTE_VERSION,
            "known_start_label_rows": 0 if unknown else 96,
        }
    served["fingerprint"] = forecast_digest(served)
    companion["rows"] = frame.to_dict("records")
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    return served, companion, calendar, clubs


def test_reader_accepts_correct_joint_jensen_score_and_no_evidence_is_exact_noop():
    parts = joint_documents()
    original = deepcopy(parts[:2])
    basis = basis_from(parts)
    row = basis.fixture_rows.iloc[0]
    collapsed = sum(
        row[f"minute_probability_{b}"] * np.exp(-1.5 * row[f"minute_value_{b}"] / 90)
        for b in (2, 3)
    )
    assert abs(row.clean_sheet_probability - collapsed) > 1e-6
    unchanged = apply_explicit_minute_evidence(basis, [])
    assert_frame_equal(unchanged.weekly_rows, basis.weekly_rows)
    assert_frame_equal(unchanged.fixture_rows, basis.fixture_rows)
    assert parts[:2] == original


def test_cited_shorter_match_preserves_roles_q_and_future_then_recomputes_all_heads():
    basis = basis_from(joint_documents(dgw=True))
    before = basis.fixture_rows
    result = apply_explicit_minute_evidence(basis, [claim()])
    old = before.loc[before.player_code.eq(3) & before.fixture.eq(62)].iloc[0]
    row = result.fixture_rows.loc[
        result.fixture_rows.player_code.eq(3) & result.fixture_rows.fixture.eq(62)
    ].iloc[0]
    assert row.start_probability == pytest.approx(old.start_probability)
    assert row.cameo_probability == pytest.approx(old.cameo_probability)
    assert row.appearance_probability == old.appearance_probability
    assert row.start_minute_probability_3 == row.cameo_minute_probability_3 == 0
    assert row.expected_minutes < old.expected_minutes
    assert row.p60 < old.p60
    assert row.defcon_probability < old.defcon_probability
    assert row.expected_minutes_if_appearance == pytest.approx(
        row.expected_minutes / row.appearance_probability
    )
    # The other fixture in the double gameweek and all later weeks are untouched.
    unaffected = before.fixture.ne(62)
    assert_frame_equal(result.fixture_rows.loc[unaffected], before.loc[unaffected])
    np.testing.assert_allclose(
        result.weekly_rows.appearance_probability, basis.weekly_rows.appearance_probability
    )
    for head in ("goals", "assists"):
        np.testing.assert_allclose(
            result.fixture_rows.groupby(["fixture", "club"])[head].sum(),
            before.groupby(["fixture", "club"])[head].sum(),
        )
    repeated = apply_explicit_minute_evidence(basis, [claim()])
    assert result.fingerprint == repeated.fingerprint


def test_absent_role_support_cannot_be_replaced_by_an_invented_role_switch():
    basis = basis_from(joint_documents(no_start_shorter=True))
    with pytest.raises(ValueError, match="within the starting role"):
        apply_explicit_minute_evidence(basis, [claim()])


def test_unknown_role_fallback_remains_readable_and_intervenable_without_invented_starts():
    basis = basis_from(joint_documents(unknown=True))
    result = apply_explicit_minute_evidence(basis, [claim()])
    assert result.fixture_rows.start_probability.isna().all()
    assert result.fixture_rows.cameo_probability.isna().all()
    np.testing.assert_allclose(
        result.fixture_rows.unknown_role_probability, result.fixture_rows.appearance_probability
    )
    row = result.fixture_rows.query("player_code == 3 and fixture == 62").iloc[0]
    assert row.minute_probability_3 == 0


@pytest.mark.parametrize("damage", ["role_mass", "role_mean", "nullable", "nonlinear", "metadata"])
def test_redigested_inconsistent_joint_companion_is_refused(damage):
    served, companion, calendar, clubs = joint_documents()
    if damage == "role_mass":
        companion["rows"][0]["start_probability"] += 0.1
    elif damage == "role_mean":
        companion["rows"][0]["start_minute_value_1"] = 70
    elif damage == "nullable":
        companion["rows"][0]["start_probability"] = None
    elif damage == "nonlinear":
        row = companion["rows"][0]
        row["clean_sheet_probability"] = sum(
            row[f"minute_probability_{b}"] * np.exp(-1.5 * row[f"minute_value_{b}"] / 90)
            for b in (2, 3)
        )
    else:
        companion["role_metadata"] = {"known_start_label_rows": 1}
    companion["fingerprint"] = forecast_digest(companion)
    with pytest.raises(ValueError):
        basis_from((served, companion, calendar, clubs))
