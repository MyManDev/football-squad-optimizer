"""Draft-only consumer tests. Run only in the parent's authorized serial test slot."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.stats import nbinom

from squadopt.live.football_artifact import ARTIFACT_CONTRACT, forecast_digest
from squadopt.live.minute_evidence import (
    FIXTURE_COMPONENTS_CONTRACT,
    ExplicitMinuteEvidence,
    FixtureComponentBasis,
    apply_explicit_minute_evidence,
)
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.scenarios.expected_lineup import expected_lineup_score, improve_expected_lineup

XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)


def documents(
    *, dgw=False, eligibility=1.0, zero_player=None, full_only_player=None, negative=False
):
    """Complete source roster: six clubs of eleven, with a legal 15 spanning six clubs."""
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    position = {
        p: positions[p - 1] if p <= 15 else ("GK" if p % 11 == 0 else "MID") for p in range(1, 67)
    }
    clubs = {p: (p - 1) % 6 + 1 for p in position}
    calendar = []
    for week in (6, 7):
        for match, (home, away) in enumerate(((1, 2), (3, 4), (5, 6)), 1):
            for club, opponent, at_home in ((home, away, 1), (away, home, 0)):
                calendar.append(
                    {
                        "GW": week,
                        "fixture": week * 10 + match,
                        "club": club,
                        "opponent": opponent,
                        "home": at_home,
                        "kickoff": f"2026-09-{23 if week == 6 else 30}T15:00:00+00:00",
                    }
                )
    if dgw:
        calendar.extend(
            [
                {**row, "fixture": 69, "kickoff": "2026-09-25T15:00:00+00:00"}
                for row in calendar
                if row["GW"] == 6 and row["club"] in (3, 4)
            ]
        )
    rows = []
    for side in calendar:
        for player, club in clubs.items():
            if club != side["club"]:
                continue
            probabilities = [0.1, 0.04, 0.01, 0.85]
            if player == zero_player:
                probabilities = [1.0, 0.0, 0.0, 0.0]
            if player == full_only_player:
                probabilities = [0.0, 0.0, 0.0, 1.0]
            means = [0.0, 30.0, 75.0, 90.0]
            minutes = float(np.dot(probabilities, means))
            q, p60 = 1 - probabilities[0], sum(probabilities[2:])
            residual = {3: 0.3, 4: 1.0, 5: 1.0, 6: 0.0, 7: -2.0, 12: -2.0, 13: 20.0, 8: 15.0}.get(
                player, 0.0
            )
            if negative and player == 66:
                residual = -20.0
            threshold = 10 if position[player] == "DEF" else 12
            dc = sum(
                probabilities[b]
                * nbinom.sf(threshold - 1, 4.0, 4.0 / (4.0 + max(8.0 * means[b] / 90, 1e-12)))
                for b in (1, 2, 3)
            )
            if position[player] == "GK":
                dc = 0.0
            rows.append(
                {
                    **side,
                    "player_code": player,
                    "position": position[player],
                    "expected_minutes": minutes,
                    "appearance_probability": q,
                    "p60": p60,
                    "team_goal_rate": 1.5,
                    "opponent_goal_rate": 1.5,
                    "clean_sheet_probability": sum(
                        probabilities[b] * np.exp(-1.5 * means[b] / 90) for b in (2, 3)
                    ),
                    "defcon_probability": dc,
                    "defcon_rate90": 8.0,
                    "defcon_dispersion": 4.0,
                    "residual_if_appearance": residual,
                    **{f"minute_probability_{b}": float(probabilities[b]) for b in range(4)},
                    **{f"minute_value_{b}": means[b] for b in range(4)},
                }
            )
    frame = pd.DataFrame(rows)
    for _, side in frame.groupby(["fixture", "club"]):
        weights = side.expected_minutes
        share = weights / weights.sum()
        frame.loc[side.index, "goals_share"] = share
        frame.loc[side.index, "assists_share"] = share
        frame.loc[side.index, "goals"] = 1.2 * share
        frame.loc[side.index, "assists"] = 0.9 * share
    goal = frame.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
    clean = frame.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0})
    frame["raw_expected_points"] = (
        frame.appearance_probability
        + frame.p60
        + goal * frame.goals
        + 3 * frame.assists
        + clean * frame.clean_sheet_probability
        + 2 * frame.defcon_probability
        + frame.appearance_probability * frame.residual_if_appearance
    )
    frame["expected_points"] = frame.raw_expected_points.clip(lower=0)
    weekly = []
    for (week, player), group in frame.groupby(["GW", "player_code"]):
        weekly.append(
            {
                "gameweek": int(week),
                "player_id": int(player),
                "team_id": clubs[player],
                "position": position[player],
                "name": f"Player {player}",
                "price_tenths": 50,
                "fixture_count": len(group),
                "home_fixture_count": int(group.home.sum()),
                "expected_points": float(group.expected_points.sum()),
                "appearance_probability": 1 - float((1 - group.appearance_probability).prod()),
            }
        )
    binding = {
        "model_version": FOOTBALL_MODEL_VERSION,
        "season": "2026-27",
        "gameweek": 6,
        "source_snapshot_id": "test-capture",
        "captured_at_utc": "2026-09-22T12:00:00+00:00",
        "source_fingerprint": "a" * 64,
        "training_rows": 1000,
        "training_latest_kickoff": "2026-09-20T15:00:00+00:00",
        "archive_hashes": {"test": "b" * 64},
    }
    served = {**binding, "contract_version": ARTIFACT_CONTRACT, "rows": weekly}
    served["fingerprint"] = forecast_digest(served)
    companion = {
        **binding,
        "contract_version": FIXTURE_COMPONENTS_CONTRACT,
        "gameweeks": [6, 7],
        "forecast_fingerprint": served["fingerprint"],
        "captured_availability": {
            "application": "not_applied",
            "scope": "one_state_per_player_week",
            "rule_contract_version": "test",
            "unknown_is_available": True,
            "multiplier_floor": 0.0,
            "multipliers": [{"player_code": p, "multiplier": eligibility} for p in clubs],
        },
        "rows": frame.to_dict("records"),
    }
    companion["fingerprint"] = forecast_digest(companion)
    return served, companion, pd.DataFrame(calendar), clubs


def basis_from(parts):
    served, companion, calendar, clubs = parts
    return FixtureComponentBasis.from_documents(
        served, companion, fixture_calendar=calendar, roster_clubs=clubs
    )


def claim(*, player=3, fixtures=(62,)):
    return ExplicitMinuteEvidence(
        "claim-1",
        player,
        6,
        fixtures,
        "no_full_match",
        "https://club.example/news",
        "c" * 64,
        0,
        30,
    )


def test_no_evidence_is_exact_noop_and_input_is_not_mutated():
    parts = documents(eligibility=0.5)
    saved = deepcopy(parts[:2])
    basis = basis_from(parts)
    result = apply_explicit_minute_evidence(basis, ())
    pd.testing.assert_frame_equal(result.fixture_rows, basis.fixture_rows, check_exact=True)
    pd.testing.assert_frame_equal(result.weekly_rows, basis.weekly_rows, check_exact=True)
    assert parts[:2] == saved
    assert result.evidence_audit == ()


def test_explicit_limit_preserves_q_and_recomputes_teammates():
    basis = basis_from(documents())
    result = apply_explicit_minute_evidence(basis, (claim(),))
    old = basis.fixture_rows.set_index(["fixture", "player_code"])
    new = result.fixture_rows.set_index(["fixture", "player_code"])
    assert new.loc[(62, 3), "expected_minutes"] < old.loc[(62, 3), "expected_minutes"]
    assert new.loc[(62, 3), "p60"] < old.loc[(62, 3), "p60"]
    pd.testing.assert_series_equal(
        result.weekly_rows.appearance_probability,
        basis.weekly_rows.appearance_probability,
        check_exact=True,
    )
    assert new.loc[(62, 3), "expected_points"] < old.loc[(62, 3), "expected_points"]
    assert new.loc[(62, 9), "goals"] > old.loc[(62, 9), "goals"]
    assert new.loc[(62, 9), "expected_points"] > old.loc[(62, 9), "expected_points"]
    for head in ("goals", "assists"):
        after = result.fixture_rows.query("fixture == 62 and club == 3")[head].sum()
        before = basis.fixture_rows.query("fixture == 62 and club == 3")[head].sum()
        assert after == pytest.approx(before, abs=1e-12)
    other_week = result.weekly_rows.gameweek.eq(7)
    pd.testing.assert_frame_equal(
        result.weekly_rows.loc[other_week], basis.weekly_rows.loc[other_week], check_exact=True
    )
    others = ~result.weekly_rows.team_id.eq(3)
    pd.testing.assert_frame_equal(
        result.weekly_rows.loc[others], basis.weekly_rows.loc[others], check_exact=True
    )
    assert "quote" not in str(result.evidence_audit)


def test_real_legal_squad_changes_starting_defender_from_minute_evidence():
    basis = basis_from(documents())
    result = apply_explicit_minute_evidence(basis, (claim(),))
    before = basis.weekly_rows.query("gameweek == 6 and player_id <= 15")
    after = result.weekly_rows.query("gameweek == 6 and player_id <= 15")
    assert before.groupby("team_id").size().max() <= 3
    original = expected_lineup_score(before, XI, BENCH, 13, 8)
    swap_xi = tuple(6 if p == 3 else p for p in XI)
    swap_bench = tuple(3 if p == 6 else p for p in BENCH)
    assert (
        original.expected_net_points
        > expected_lineup_score(before, swap_xi, swap_bench, 13, 8).expected_net_points
    )
    limited = expected_lineup_score(after, XI, BENCH, 13, 8)
    swapped = expected_lineup_score(after, swap_xi, swap_bench, 13, 8)
    assert swapped.expected_net_points > limited.expected_net_points
    improved = improve_expected_lineup(after, XI, BENCH, 13, 8, max_evaluations=128)
    assert 3 not in improved.best.starting_xi
    assert 6 in improved.best.starting_xi
    assert improved.best.expected_net_points > limited.expected_net_points


def test_dgw_scope_is_explicit_and_eligibility_is_shared_once():
    basis = basis_from(documents(dgw=True, eligibility=0.5))
    result = apply_explicit_minute_evidence(basis, (claim(fixtures=(62,)),))
    later = result.fixture_rows.fixture.eq(69)
    pd.testing.assert_frame_equal(
        result.fixture_rows.loc[later], basis.fixture_rows.loc[later], check_exact=True
    )
    player = result.weekly_rows.query("gameweek == 6 and player_id == 3").iloc[0]
    assert player.appearance_probability == pytest.approx(0.5 * (1 - 0.1**2))
    assert player.appearance_probability != pytest.approx(1 - (1 - 0.5 * 0.9) ** 2)
    assert player.expected_points == pytest.approx(
        0.5 * result.fixture_rows.query("GW == 6 and player_code == 3").expected_points.sum()
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"restriction": "stated_minutes_limited"},
        {"restriction": "rotation_risk"},
        {"fixture_ids": ()},
        {"fixture_ids": (62, 62)},
        {"fixture_ids": (True,)},
        {"source_sha256": "missing"},
        {"span_end": 0},
    ],
)
def test_vague_or_malformed_evidence_is_refused(changes):
    with pytest.raises(ValueError):
        replace(claim(), **changes)


@pytest.mark.parametrize("changes", [{"fixture_ids": (999,)}, {"gameweek": 7}, {"player_id": 999}])
def test_ambiguous_or_out_of_scope_fixture_is_refused(changes):
    with pytest.raises(ValueError):
        apply_explicit_minute_evidence(basis_from(documents()), (replace(claim(), **changes),))


def test_duplicate_or_overlapping_evidence_is_refused():
    basis = basis_from(documents())
    with pytest.raises(ValueError, match="Duplicate"):
        apply_explicit_minute_evidence(basis, (claim(), claim()))
    with pytest.raises(ValueError, match="Overlapping"):
        apply_explicit_minute_evidence(basis, (claim(), replace(claim(), evidence_id="other")))


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"zero_player": 3}, "effective appearance"),
        ({"full_only_player": 3}, "sub-90"),
    ],
)
def test_no_learned_shorter_support_is_refused(options, reason):
    with pytest.raises(ValueError, match=reason):
        apply_explicit_minute_evidence(basis_from(documents(**options)), (claim(),))


def test_zero_captured_eligibility_refuses_redundant_claim_without_redistribution():
    parts = documents()
    companion = parts[1]
    for entry in companion["captured_availability"]["multipliers"]:
        if entry["player_code"] == 3:
            entry["multiplier"] = 0.0
    companion["fingerprint"] = forecast_digest(companion)
    basis = basis_from(parts)
    fixtures_before = basis.fixture_rows
    weekly_before = basis.weekly_rows
    assert fixtures_before.query("GW == 6 and player_code == 3").appearance_probability.gt(0).all()
    assert (
        weekly_before.query("gameweek == 6 and player_id == 3").appearance_probability.eq(0).all()
    )
    assert weekly_before.query("gameweek == 6 and player_id == 9").expected_points.gt(0).all()
    with pytest.raises(ValueError, match="effective appearance"):
        apply_explicit_minute_evidence(basis, (claim(),))
    pd.testing.assert_frame_equal(basis.fixture_rows, fixtures_before, check_exact=True)
    pd.testing.assert_frame_equal(basis.weekly_rows, weekly_before, check_exact=True)


def test_valid_claim_keeps_unavailable_teammate_zero_without_changing_raw_share_rule():
    reference_basis = basis_from(documents())
    reference = apply_explicit_minute_evidence(reference_basis, (claim(),))
    parts = documents()
    companion = parts[1]
    for entry in companion["captured_availability"]["multipliers"]:
        if entry["player_code"] == 9:
            entry["multiplier"] = 0.0
    companion["fingerprint"] = forecast_digest(companion)
    basis = basis_from(parts)
    result = apply_explicit_minute_evidence(basis, (claim(),))
    # Eligibility is applied once after the unchanged raw team-allocation rule.
    pd.testing.assert_frame_equal(result.fixture_rows, reference.fixture_rows, check_exact=True)
    unavailable = result.weekly_rows.player_id.eq(9)
    assert result.weekly_rows.loc[unavailable, "expected_points"].eq(0).all()
    assert result.weekly_rows.loc[unavailable, "appearance_probability"].eq(0).all()
    pd.testing.assert_frame_equal(
        result.weekly_rows.loc[~unavailable],
        reference.weekly_rows.loc[~unavailable],
        check_exact=True,
    )
    for head in ("goals", "assists"):
        before = basis.fixture_rows.query("fixture == 62 and club == 3")[head].sum()
        after = result.fixture_rows.query("fixture == 62 and club == 3")[head].sum()
        assert after == pytest.approx(before, abs=1e-12)


@pytest.mark.parametrize(
    "kind",
    [
        "missing_row",
        "negative_probability",
        "wrong_forecast",
        "wrong_source",
        "wrong_fixture",
        "bad_minute_identity",
    ],
)
def test_incomplete_or_inconsistent_companion_is_refused_even_if_redigested(kind):
    parts = documents()
    _, companion, _, _ = parts
    if kind == "missing_row":
        companion["rows"].pop()
    elif kind == "negative_probability":
        companion["rows"][0]["minute_probability_1"] = -0.1
    elif kind == "wrong_forecast":
        companion["forecast_fingerprint"] = "d" * 64
    elif kind == "wrong_source":
        companion["source_snapshot_id"] = "other-capture"
    elif kind == "wrong_fixture":
        companion["rows"][0]["fixture"] = 999
    else:
        companion["rows"][0]["expected_minutes"] += 1
    companion["fingerprint"] = forecast_digest(companion)
    with pytest.raises(ValueError):
        basis_from(parts)


def test_unmodified_digest_refuses_tamper_and_signed_residual_is_supported():
    parts = documents(negative=True)
    basis = basis_from(parts)
    assert basis.fixture_rows.query("player_code == 66").raw_expected_points.lt(0).all()
    assert basis.fixture_rows.query("player_code == 66").expected_points.eq(0).all()
    parts[1]["rows"][0]["goals"] += 1
    with pytest.raises(ValueError, match="fingerprint"):
        basis_from(parts)
