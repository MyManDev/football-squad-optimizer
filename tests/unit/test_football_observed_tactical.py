"""Invented observed-source fixtures, independent moments and causal refusals."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import squadopt.prediction.football_observed_tactical as model_module
from squadopt.features.football_observed_tactical_inputs import (
    INPUT_VERSION,
    REQUIRED_HISTORY,
    ObservedEventFixture,
    ObservedRole,
    ObservedTacticalObservation,
    ObservedTacticalPlayer,
    ObservedTacticalProfile,
    ObservedTacticalProjection,
    ObservedTacticalReplay,
    ObservedTacticalSide,
    ObservedTacticalSource,
    digest,
    forecast_role,
    recipient_features,
    style_values,
    team_features,
    validate_header,
    validate_projection,
)
from squadopt.features.football_observed_tactical_readers import (
    ObservedFMRow,
    read_observed_event_fixture,
    read_observed_fm_profiles,
    read_observed_observation,
    read_observed_panna_roles,
    read_observed_projection,
    read_observed_role_rows,
)
from squadopt.features.football_tactical_inputs import TRAITS, TacticalCredit
from squadopt.prediction.football_observed_tactical import (
    FEATURE_VERSION,
    MODEL_VERSION,
    ObservedTacticalModel,
    fit_transform,
)

CUTOFF = "2026-10-01T00:00:00Z"


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clock(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def source(label: str, at: str, payload: bytes = b"invented") -> ObservedTacticalSource:
    return ObservedTacticalSource(
        label,
        "invented-provider",
        "invented-v1",
        sha(payload),
        at,
        at,
        True,
        "invented-owner-permission",
    )


def projection(
    index: int = 0, *, current: bool = False, missing: bool = False
) -> ObservedTacticalProjection:
    kickoff = datetime(2026 if current else 2024, 10, 10, 12, tzinfo=UTC) + timedelta(
        days=7 * index
    )
    decision = kickoff - timedelta(days=1)
    available = clock(decision - timedelta(hours=1))
    observed = kickoff - timedelta(days=8)
    src = source("past-facts", available)
    sides = []
    for club in (1, 2):
        players = []
        for i, position in enumerate(
            ("GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD", "MID")
        ):
            code = club * 100 + i + 1
            role = "G" if i == 0 else "D" if i <= 4 else "M" if i <= 8 else "F"
            history = (
                ()
                if missing
                else (
                    ObservedRole(
                        "2026-27" if current else "2024-25",
                        1 + index,
                        10 + index,
                        clock(observed),
                        clock(observed + timedelta(hours=3)),
                        code,
                        club,
                        role,
                        "person-" + str(code),
                        i + 2,
                        "invented-exact-person-bridge",
                        src,
                    ),
                )
            )
            attributes = (
                (None,) * len(TRAITS)
                if missing or i == 11
                else tuple(5 + (i + j + index + club) % 15 for j in range(len(TRAITS)))
            )
            profile = ObservedTacticalProfile(
                code,
                club,
                position,
                attributes,
                None if missing or i == 11 else "fm-" + str(code),
                None if missing or i == 11 else "invented-exact-name-dob",
                None if missing or i == 11 else src,
                None if missing else "f" * 64,
                not missing,
                history,
                () if missing or i == 11 else tuple((name, name) for name in TRAITS),
            )
            players.append(
                ObservedTacticalPlayer(
                    profile,
                    90.0 if i < 11 else 0.0,
                    1 / 11 if i < 11 else 0.0,
                    1 / 11 if i < 11 else 0.0,
                )
            )
        events = (
            ()
            if missing
            else (
                ObservedEventFixture(
                    "2026-27" if current else "2024-25",
                    1 + index,
                    10 + index,
                    club,
                    3 - club,
                    clock(observed),
                    clock(observed + timedelta(hours=3)),
                    "match-" + str(index),
                    "team-" + str(club),
                    "a" * 64,
                    "b" * 64,
                    (club + index, 0, 1, 0),
                    20,
                    tuple(range(1, 21)),
                    src,
                    True,
                ),
            )
        )
        sides.append(
            ObservedTacticalSide(
                club,
                tuple(players),
                1.2 + club / 10,
                0.9,
                0.7,
                events,
            )
        )
    roster = tuple(
        sorted(
            (x.profile.player_code, s.club, x.profile.fpl_position)
            for s in sides
            for x in s.players
        )
    )
    return ObservedTacticalProjection(
        "2026-27" if current else "2024-25",
        5 + index,
        100 + index,
        clock(kickoff),
        clock(decision),
        clock(decision),
        available,
        sides[0],
        sides[1],
        roster,
        source("native", available),
        source("roster", available),
    )


def observation(index: int = 0, *, missing: bool = False) -> ObservedTacticalObservation:
    p = projection(index, missing=missing)
    settled = clock(datetime.fromisoformat(p.kickoff.replace("Z", "+00:00")) + timedelta(hours=3))
    credits = tuple(
        TacticalCredit(code, club, int(code in (102, 110, 210)), int(code in (103, 209)))
        for code, club, _ in p.roster
    )
    return ObservedTacticalObservation(
        p,
        settled,
        source("physical", settled),
        source("credits", settled),
        (2, 1),
        credits,
        "invented-final-fpl-rules",
        True,
    )


def fit(rows: tuple[ObservedTacticalObservation, ...], **kwargs: Any) -> ObservedTacticalModel:
    return ObservedTacticalModel().fit(
        rows,
        cutoff=CUTOFF,
        target_season="2026-27",
        target_gameweek=5,
        allowed_seasons=kwargs.pop("allowed_seasons", ("2024-25",)),
        **kwargs,
    )


def replayed() -> ObservedTacticalObservation:
    o = observation(missing=True)
    p = o.projection

    def changed(value: str) -> str:
        return value.replace("2024-", "2025-")

    actual = "2026-09-01T00:00:00Z"
    generated = "2026-09-02T00:00:00Z"
    recorded = changed(p.generated_at)
    roster_source = replace(p.roster_source, published_at=recorded, retrieved_at=actual)
    hashes = tuple(
        (
            name,
            roster_source.sha256
            if name == "players_raw.csv"
            else p.native_source.sha256
            if name == "native_baseline.json"
            else "b" * 64,
        )
        for name in (*REQUIRED_HISTORY, "native_baseline.json")
    )
    replay = ObservedTacticalReplay(
        "a" * 40,
        recorded,
        actual,
        generated,
        changed(p.feature_cutoff),
        "2025-09-20T00:00:00Z",
        hashes,
    )
    p = replace(
        p,
        season="2025-26",
        kickoff=changed(p.kickoff),
        decision_at=changed(p.decision_at),
        feature_cutoff=changed(p.feature_cutoff),
        generated_at=generated,
        native_source=replace(p.native_source, published_at=actual, retrieved_at=actual),
        roster_source=roster_source,
        replay=replay,
    )
    return replace(
        o,
        projection=p,
        outcome_available_at=generated,
        goal_source=source("physical", generated),
        credit_source=source("credits", generated),
    )


def test_missing_fixture_population_is_not_a_zero_count() -> None:
    p = projection(missing=True)
    validate_projection(p)
    assert style_values(p.home)["observed_cross_attempts_per_fixture"] is None
    assert style_values(p.home)["observed_fixture_count"] == 0
    q = projection()
    assert style_values(q.home)["observed_throughball_attempts_per_fixture"] == 0
    assert style_values(q.home)["observed_fixture_count"] == 1
    assert q.home.observed_fixtures[0].pressure_events is None
    assert q.home.observed_fixtures[0].high_pass_attempts is None


def test_known_trait_denominator_and_support_are_independently_reconstructed() -> None:
    p = projection()
    players = tuple(
        replace(x, profile=replace(x.profile, attributes=(None,) * len(TRAITS))) if i >= 2 else x
        for i, x in enumerate(p.home.players)
    )
    p = replace(p, home=replace(p.home, players=players))
    values = team_features(p, home=True)
    expected = sum(x.profile.attributes[0] / 20 for x in players[:2]) / 2  # type: ignore[operator]
    assert values["own_goal_weighted_heading"] == pytest.approx(expected)
    assert values["own_goal_weighted_heading_observed_weight_fraction"] == pytest.approx(2 / 11)
    assert values["own_goal_weighted_heading_known_player_count"] == 2


def test_lagged_role_uses_same_club_and_complete_inventory_without_position_inference() -> None:
    p = projection()
    player = p.home.players[1]
    profile = replace(
        player.profile, role_history=(replace(player.profile.role_history[0], provider_role="F"),)
    )
    assert profile.fpl_position == "DEF"
    assert forecast_role(profile, p) == "F"
    assert (
        forecast_role(
            replace(profile, role_inventory_sha256=None, role_inventory_complete=False), p
        )
        is None
    )
    assert (
        forecast_role(replace(profile, role_history=(replace(profile.role_history[0], club=2),)), p)
        is None
    )
    values = recipient_features(p, p.home.players[-1], home=True, head="goals")
    assert values["player_heading"] is None


def test_train_only_weighted_transform_preserves_masks_and_disabled_channels() -> None:
    rows = [
        {"x": 0.0, "unsupported": None},
        {"x": 4.0, "unsupported": None},
        {"x": None, "unsupported": None},
    ]
    transform = fit_transform(rows, [1.0, 3.0, 4.0], weighting="invented-prior")
    assert transform.means == (3.0, 0.0)
    assert transform.scales == pytest.approx((math.sqrt(3), 1))
    assert transform.observed_weights == (4.0, 0.0)
    assert transform.mask_means == (0.5, 0.0)
    assert transform.active == (True, False)
    transformed = transform.apply(rows)
    assert transformed[:, 0] == pytest.approx([-math.sqrt(3), 1 / math.sqrt(3), 0])
    assert transformed[:, 1] == pytest.approx([1, 1, -1])
    assert np.array_equal(
        transform.apply([{"x": 8.0, "unsupported": 99.0}])[:, 2:], np.zeros((1, 2))
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "2"])
def test_transform_refuses_unobserved_imputation_disguises(bad: Any) -> None:
    with pytest.raises(ValueError):
        fit_transform([{"x": bad}], [1.0], weighting="invented")


def test_interaction_unknown_if_an_operand_is_unknown() -> None:
    p = projection(missing=True)
    features = team_features(p, home=True)
    assert all(value is None for name, value in features.items() if "*" in name)
    assert not any("pressure" in name or "high_pass" in name for name in features)


@pytest.mark.parametrize(
    "mutation",
    [
        "target_gw",
        "old_29_days",
        "unfinished",
        "role_target",
        "future_fm",
        "unknown_pressure",
        "roster",
        "minutes",
        "clock",
        "same_club",
    ],
)
def test_projection_refuses_leakage_identity_and_scope_mutations(mutation: str) -> None:
    p = projection()
    f = p.home.observed_fixtures[0]
    if mutation == "target_gw":
        p = replace(p, home=replace(p.home, observed_fixtures=(replace(f, gameweek=p.gameweek),)))
    elif mutation == "old_29_days":
        p = replace(
            p, home=replace(p.home, observed_fixtures=(replace(f, kickoff="2024-09-01T00:00:00Z"),))
        )
    elif mutation == "unfinished":
        p = replace(
            p, home=replace(p.home, observed_fixtures=(replace(f, finished_at=p.feature_cutoff),))
        )
    elif mutation == "role_target":
        x = p.home.players[0]
        changed = replace(
            x,
            profile=replace(
                x.profile, role_history=(replace(x.profile.role_history[0], gameweek=p.gameweek),)
            ),
        )
        p = replace(p, home=replace(p.home, players=(changed, *p.home.players[1:])))
    elif mutation == "future_fm":
        x = p.home.players[0]
        changed = replace(x, profile=replace(x.profile, trait_source=source("future", p.kickoff)))
        p = replace(p, home=replace(p.home, players=(changed, *p.home.players[1:])))
    elif mutation == "unknown_pressure":
        p = replace(p, home=replace(p.home, observed_fixtures=(replace(f, pressure_events=0),)))  # type: ignore[arg-type]
    elif mutation == "roster":
        p = replace(p, roster=p.roster[:-1])
    elif mutation == "minutes":
        p = replace(
            p,
            home=replace(
                p.home, players=(replace(p.home.players[0], minutes=91), *p.home.players[1:])
            ),
        )
    elif mutation == "clock":
        p = replace(p, generated_at=p.kickoff)
    else:
        p = replace(p, away=p.home)
    with pytest.raises(ValueError):
        validate_projection(p)


def test_released_replay_requires_strict_opt_in_and_preserves_actual_clock() -> None:
    o = replayed()
    with pytest.raises(ValueError, match="opt-in"):
        fit((o,), allowed_seasons=("2025-26",))
    for flag in (1, "true", None):
        with pytest.raises(ValueError, match="Boolean"):
            validate_projection(o.projection, allow_released_2025_26=flag)  # type: ignore[arg-type]
    model = fit((o,), allowed_seasons=("2025-26",), allow_released_2025_26=True)
    assert model.metadata.allow_released_2025_26 is True
    assert model.metadata.training_receipts[0].generated_at == "2026-09-02T00:00:00Z"
    with pytest.raises(ValueError, match="prospective"):
        model.predict(o.projection)


def test_all_headers_before_any_outcome_access(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = observation(), observation(1)
    second = replace(second, projection=replace(second.projection, season="2027-28"))
    seen = []
    monkeypatch.setattr(model_module, "validate_outcome", lambda row: seen.append(row))
    with pytest.raises(ValueError, match="before outcome"):
        fit((first, second))
    assert seen == []


def test_actual_fit_control_and_independent_marginal_context_predictions() -> None:
    model = fit(tuple(observation(i) for i in range(3)))
    p = projection(current=True)
    result, control = model.predict(p), model.predict(p, control=True)
    assert result.model_version == MODEL_VERSION and result.feature_version == FEATURE_VERSION
    assert result.projection_sha256 == digest(p)
    assert result.model_sha256 == sha(model.metadata_json.encode())
    x = model.metadata.team_transform.apply(
        [team_features(p, home=True), team_features(p, home=False)]
    )
    for i, (side, learned, base) in enumerate(
        zip((p.home, p.away), (result.home, result.away), (control.home, control.away), strict=True)
    ):
        rate = side.base_goal_rate * math.exp(float(x[i] @ np.asarray(model.metadata.beta)))
        assert learned.team_goal_rate == pytest.approx(rate, rel=1e-13)
        assert base.team_goal_rate == side.base_goal_rate
        assert math.fsum(r.goals for r in learned.players) == pytest.approx(
            rate * side.scored_fraction
        )
        assert math.fsum(r.assists for r in learned.players) == pytest.approx(
            rate * side.scored_fraction * side.assist_fraction
        )
        by_code = {r.player_code: r for r in base.players}
        for native in side.players:
            row = by_code[native.profile.player_code]
            assert (
                row.goals == side.base_goal_rate * side.scored_fraction * native.native_goal_share
            )
            assert (
                row.assists
                == side.base_goal_rate
                * side.scored_fraction
                * side.assist_fraction
                * native.native_assist_share
            )
        assert all(
            row.goals + row.assists <= learned.team_goal_rate + 1e-12 for row in learned.players
        )


def test_current_empty_styles_and_roles_remain_unknown_not_carried_forward() -> None:
    model = fit((observation(missing=True),))
    p = projection(current=True, missing=True)
    result = model.predict(p)
    assert result.home.team_goal_rate == p.home.base_goal_rate
    assert result.away.team_goal_rate == p.away.base_goal_rate
    assert all(
        not active
        for name, active in zip(
            model.metadata.team_transform.features,
            model.metadata.team_transform.active,
            strict=True,
        )
        if "per_fixture" in name
    )


def test_recipient_only_exact_softmax_native_control_and_compact_source_receipt() -> None:
    model = fit(tuple(observation(i) for i in range(3)))
    p = projection(current=True)
    result = model.predict_recipients(p)
    control = model.predict_recipients(p, control=True)
    standalone = model.predict(p)
    assert result.model_sha256 == model.model_sha256
    assert result.projection_sha256 == digest(p)
    assert result.policy == model_module.RECIPIENT_POLICY
    assert result.model_cutoff == CUTOFF
    assert p.home.players[0].profile.role_inventory_sha256 in result.source_hashes
    assert "metadata" not in asdict(result)
    for i, (side, learned, native, full) in enumerate(
        zip(
            (p.home, p.away),
            (result.home, result.away),
            (control.home, control.away),
            (standalone.home, standalone.away),
            strict=True,
        )
    ):
        players = sorted(side.players, key=lambda x: x.profile.player_code)
        for head, transform, gamma in (
            ("goals", model.metadata.goal_transform, model.metadata.goal_gamma),
            ("assists", model.metadata.assist_transform, model.metadata.assist_gamma),
        ):
            shares = [
                getattr(x, "native_goal_share" if head == "goals" else "native_assist_share")
                for x in players
            ]
            features = transform.apply(
                [recipient_features(p, x, home=i == 0, head=head) for x in players]
            )
            weights = [
                s * math.exp(float(x @ np.asarray(gamma)))
                for s, x in zip(shares, features, strict=True)
            ]
            expected = [w / math.fsum(weights) for w in weights]
            name = "goal_share" if head == "goals" else "assist_share"
            assert [getattr(x, name) for x in learned.players] == pytest.approx(expected, rel=1e-13)
            assert [getattr(x, name) for x in native.players] == shares
            assert getattr(learned.players[-1], name) == 0.0
            fraction = side.scored_fraction * (side.assist_fraction if head == "assists" else 1)
            assert [getattr(x, head) for x in full.players] == [
                full.team_goal_rate * fraction * getattr(x, name) for x in learned.players
            ]
        assert "team_goal_rate" not in asdict(learned)


def test_recipient_only_never_evaluates_count_head_and_is_invariant_to_count_coefficients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = fit((observation(), observation(1)))
    p = projection(current=True)
    before = model.predict_recipients(p)
    fitted = model._fitted
    assert fitted is not None
    beta = model_module._immutable(np.full(len(fitted.beta), 1e200))
    metadata = replace(fitted.metadata, beta=tuple(beta))
    metadata_json = model_module._canonical(metadata)
    model._fitted = replace(
        fitted,
        beta=beta,
        metadata=metadata,
        metadata_json=metadata_json,
        sha256=sha(metadata_json.encode()),
    )

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Recipient-only inference evaluated the count head.")

    monkeypatch.setattr(model_module, "_rates", forbidden)
    monkeypatch.setattr(model_module, "team_features", forbidden)
    monkeypatch.setattr(model, "predict", forbidden)
    after = model.predict_recipients(p)
    assert after.home == before.home and after.away == before.away
    assert after.model_sha256 != before.model_sha256
    assert after.projection_sha256 == before.projection_sha256


@pytest.mark.parametrize("invalid", ["nan", "negative", "mass", "zero_support", "physical"])
def test_recipient_only_refuses_invalid_probabilities_without_clipping(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    model = fit((observation(),))
    p = projection(current=True)

    def corrupted(shares: Any, features: Any, gamma: Any) -> Any:
        probabilities = shares.copy()
        if invalid == "nan":
            probabilities[0, 0] = np.nan
        elif invalid == "negative":
            probabilities[0, 0] = -0.1
        elif invalid == "mass":
            probabilities *= 0.9
        elif invalid == "zero_support":
            probabilities[0, -1] = probabilities[0, 0]
            probabilities[0, 0] = 0
        else:
            probabilities[:] = 0
            probabilities[0, 0] = 1
        return probabilities, np.zeros_like(probabilities)

    monkeypatch.setattr(model_module, "_recipient_probabilities", corrupted)
    with pytest.raises(ValueError, match=r"support or mass|physical goal share"):
        model.predict_recipients(p)


def test_recipient_only_requires_positive_head_support_and_prospective_window() -> None:
    o = observation()
    no_assists = replace(o, credits=tuple(replace(c, assists=0) for c in o.credits))
    model = fit((no_assists,))
    p = projection(current=True)
    with pytest.raises(ValueError, match="credited-event support"):
        model.predict_recipients(p)
    assert model.predict_recipients(p, control=True).control
    with pytest.raises(ValueError, match="Boolean"):
        model.predict_recipients(p, control=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="target window"):
        model.predict_recipients(replace(p, gameweek=4))
    with pytest.raises(ValueError, match="prospective"):
        model.predict_recipients(replayed().projection)


def test_failed_refit_is_atomic_and_internal_metadata_mutation_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = fit((observation(),))
    before = model.metadata_json
    monkeypatch.setattr(
        model_module,
        "minimize",
        lambda *a, **k: type("Bad", (), {"success": False, "x": np.zeros(2)})(),
    )
    with pytest.raises(ValueError, match="optimizer"):
        model.fit(
            (observation(),),
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweek=5,
            allowed_seasons=("2024-25",),
        )
    assert model.metadata_json == before
    with pytest.raises(FrozenInstanceError):
        model.metadata.scope = "different"  # type: ignore[misc]
    stored = model._fitted
    assert stored is not None
    with pytest.raises(ValueError):
        stored.beta.setflags(write=True)
    model._fitted = replace(stored, metadata=replace(stored.metadata, context_policy="different"))
    with pytest.raises(ValueError, match="metadata"):
        _ = model.metadata_json


def test_strict_projection_and_observation_raw_roundtrip() -> None:
    p = projection()
    raw = encoded({"version": INPUT_VERSION, "projection": asdict(p)})
    assert read_observed_projection(raw, expected_sha256=sha(raw)) == p
    with pytest.raises(ValueError, match="hash"):
        read_observed_projection(raw + b" ", expected_sha256=sha(raw))
    bad = raw.replace(b'"version":', b'"extra":1,"version":', 1)
    with pytest.raises(ValueError):
        read_observed_projection(bad, expected_sha256=sha(bad))
    o = observation()
    raw = encoded({"version": INPUT_VERSION, "observation": asdict(o)})
    options = dict(
        cutoff=CUTOFF, target_season="2026-27", target_gameweek=5, allowed_seasons=("2024-25",)
    )
    assert read_observed_observation(raw, expected_sha256=sha(raw), **options) == o
    data = json.loads(raw)
    data["observation"]["projection"]["season"] = "2027-28"
    data["observation"]["physical_goals"] = "not labels"
    bad = encoded(data)
    with pytest.raises(ValueError, match="before outcome"):
        read_observed_observation(bad, expected_sha256=sha(bad), **options)


def event_rows() -> list[dict[str, object]]:
    return [
        {
            "match_id": "m",
            "event_id": float(i + 1),
            "type_id": float(t),
            "team_id": "home",
            "season": "2024-2025",
            "qualifier_json": json.dumps(q),
        }
        for i, (t, q) in enumerate(
            (
                (1, {"2": "", "4": ""}),
                (2, {"2": ""}),
                (13, {"15": "", "23": ""}),
                (16, {"28": "", "15": "", "23": ""}),
                (14, {}),
            )
        )
    ]


def parse_events(rows: list[dict[str, object]]) -> ObservedEventFixture:
    raw = encoded(rows)
    return read_observed_event_fixture(
        raw,
        source=source("events", "2024-10-01T00:00:00Z", raw),
        season="2024-25",
        gameweek=1,
        fixture=1,
        club=1,
        opponent=2,
        kickoff="2024-09-29T12:00:00Z",
        finished_at="2024-09-29T15:00:00Z",
        provider_match_id="m",
        provider_club_id="home",
        provider_opponent_id="away",
        bridge_sha256="a" * 64,
        complete_row_count=len(rows),
        complete_inventory_sha256="b" * 64,
    )


def test_provider_event_mapping_counts_attempts_and_excludes_own_goal_shots() -> None:
    result = parse_events(event_rows())
    assert result.counts == (2, 1, 1, 1)
    assert result.event_rows == 5
    assert result.pressure_events is None and result.high_pass_attempts is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("qualifier_json", None),
        ("qualifier_json", '{"2":1,"2":2}'),
        ("event_id", 1.5),
        ("event_id", True),
        ("team_id", "unmapped"),
        ("match_id", "target"),
        ("season", "2025-2026"),
    ],
)
def test_provider_reader_refuses_unknown_or_malformed_evidence(field: str, value: Any) -> None:
    rows = event_rows()
    rows[0][field] = value
    with pytest.raises(ValueError):
        parse_events(rows)


def test_fm_reader_binds_exact_row_name_dob_and_preserves_unknown_traits() -> None:
    p = projection(missing=True)
    raw = b"Name,DOB,Heading\nExact Person,2000-01-01,17\n"
    source_ = source("FM", "2024-09-01T00:00:00Z", raw)
    mapping = ObservedFMRow(
        p.home.players[0].profile.player_code,
        2,
        "Exact Person",
        "2000-01-01",
        "invented-exact-bridge",
    )
    options = dict(
        source=source_,
        profiles=tuple(x.profile for x in p.home.players),
        mappings=(mapping,),
        name_column="Name",
        date_of_birth_column="DOB",
        trait_columns=(("heading", "Heading"),),
    )
    profiles = read_observed_fm_profiles(raw, **options)
    assert profiles[0].attributes == (17, *(None for _ in TRAITS[1:]))
    assert all(value is None for value in profiles[1].attributes)
    with pytest.raises(ValueError, match="name/DOB"):
        read_observed_fm_profiles(
            raw, **dict(options, mappings=(replace(mapping, expected_date_of_birth="2001-01-01"),))
        )


def test_provider_role_reader_never_uses_fpl_scoring_position() -> None:
    raw = (
        b"match_id,team_side,player_id,position,lineup_status\n"
        b"m,home,111,F,confirmed\nm,away,222,G,confirmed\n"
    )
    roles = read_observed_role_rows(
        raw,
        source=source("roles", "2024-09-01T00:00:00Z", raw),
        provider_match_id="m",
        season="2024-25",
        gameweek=1,
        fixture=1,
        kickoff="2024-08-30T12:00:00Z",
        finished_at="2024-08-30T15:00:00Z",
        club_by_team_side=(("home", 1), ("away", 2)),
        people=(("111", 101), ("222", 201)),
        mapping_ref="invented-per-fixture-bridge",
    )
    assert roles[0].provider_role == "F" and roles[0].original_row == 2
    assert roles[1].provider_role == "G"


def test_native_marginal_context_keeps_all_roster_support_without_a_joint_xi_claim() -> None:
    p = projection(missing=True)
    players = tuple(
        replace(x, minutes=90.0, native_goal_share=1 / 12, native_assist_share=1 / 12)
        for x in p.home.players
    )
    p = replace(p, home=replace(p.home, players=players))
    validate_projection(p)
    assert math.fsum(x.minutes for x in p.home.players) == 1080
    assert p.context_policy == "native_full_roster_marginal_context_v1"
    assert not hasattr(p, "starting_xi")
    model = fit((observation(missing=True),))
    current = projection(current=True, missing=True)
    current = replace(current, home=replace(current.home, players=players))
    result = model.predict(current, control=True)
    assert result.home.players[-1].goals > 0
    assert all(not hasattr(x, "clean_sheet_probability") for x in result.home.players)


@pytest.mark.parametrize("spaced", [False, True])
def test_panna_roles_use_declared_named_mapping_and_keep_substitute_unknown(spaced: bool) -> None:
    rows = [
        {
            "match_id": "m",
            "player_id": "p" + str(i),
            "team_id": "a",
            "position": name,
            "season": "2024-2025",
            "is_starter": name != "Substitute",
        }
        for i, name in enumerate(
            (
                "Goalkeeper",
                "Wing Back" if spaced else "WingBack",
                "Defensive Midfielder" if spaced else "DefensiveMidfielder",
                "Attacking Midfielder" if spaced else "AttackingMidfielder",
                "Striker",
                "Substitute",
            )
        )
    ]
    raw = encoded(rows)
    result = read_observed_panna_roles(
        raw,
        source=source("panna", "2024-09-01T00:00:00Z", raw),
        provider_match_id="m",
        season="2024-25",
        gameweek=1,
        fixture=1,
        kickoff="2024-08-30T12:00:00Z",
        finished_at="2024-08-30T15:00:00Z",
        clubs=(("a", 1), ("b", 2)),
        people=tuple(("p" + str(i), i + 101) for i in range(5)),
        mapping_ref="invented-exact-bridge",
    )
    assert tuple(r.provider_role for r in result) == ("G", "D", "M", "M", "F")
    assert len(result) == 5


def test_source_captured_before_finished_fact_is_rejected() -> None:
    p = projection()
    event = p.home.observed_fixtures[0]
    event = replace(
        event, source=replace(event.source, published_at=event.kickoff, retrieved_at=event.kickoff)
    )
    with pytest.raises(ValueError, match="finished fact"):
        validate_projection(replace(p, home=replace(p.home, observed_fixtures=(event,))))


def test_provider_fixture_cannot_be_double_counted_under_a_second_fpl_id() -> None:
    p = projection()
    event = p.home.observed_fixtures[0]
    with pytest.raises(ValueError, match="duplicated"):
        validate_projection(
            replace(p, home=replace(p.home, observed_fixtures=(event, replace(event, fixture=999))))
        )


def test_source_generation_cannot_precede_its_latest_acquisition() -> None:
    p = projection()
    with pytest.raises(ValueError, match="source clocks"):
        validate_projection(replace(p, generated_at="2024-10-01T00:00:00Z"))


def test_positive_credit_without_native_recipient_support_refuses() -> None:
    o = observation()
    zero = replace(o.projection.home.players[1], native_goal_share=0.0)
    more = replace(o.projection.home.players[0], native_goal_share=2 / 11)
    p = replace(
        o.projection,
        home=replace(o.projection.home, players=(more, zero, *o.projection.home.players[2:])),
    )
    with pytest.raises(ValueError, match="recipient support"):
        fit((replace(o, projection=p),))


def test_no_credited_events_disable_enabled_head_without_erasing_control() -> None:
    o = observation(missing=True)
    o = replace(o, credits=tuple(replace(c, assists=0) for c in o.credits))
    model = fit((o,))
    p = projection(current=True, missing=True)
    with pytest.raises(ValueError, match="credited-event support"):
        model.predict(p)
    assert math.fsum(c.assists for c in model.predict(p, control=True).home.players) > 0


def test_player_physical_credit_guard_refuses_without_clipping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = fit((observation(missing=True),))

    def concentrated(shares: Any, features: Any, gamma: Any) -> tuple[Any, Any]:
        probabilities = np.zeros_like(shares)
        probabilities[:, 0] = 1.0
        return probabilities, np.zeros_like(shares)

    monkeypatch.setattr(model_module, "_recipient_probabilities", concentrated)
    with pytest.raises(ValueError, match="G\\+A exceeds"):
        model.predict(projection(current=True, missing=True))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("success", 1),
        ("status", 1),
        ("status", 2),
        ("status", True),
        ("nit", -1),
        ("nit", 11),
        ("nfev", 0),
        ("x", np.array([math.nan])),
        ("x", np.zeros(2)),
        ("x", np.array([True])),
        ("x", np.array(["1.0"])),
        ("x", np.array([1.0 + 2.0j])),
        ("x", np.array([1.0], dtype=object)),
    ],
)
def test_optimizer_success_flag_does_not_override_invalid_receipt(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    fields = {"success": True, "status": 0, "nit": 1, "nfev": 2, "x": np.zeros(1)}
    fields[field] = value
    monkeypatch.setattr(model_module, "minimize", lambda *a, **k: SimpleNamespace(**fields))
    with pytest.raises(ValueError, match="optimizer"):
        model_module._optimize(lambda x: (float(x @ x), 2 * x), 1, 10, "test")


def test_lagged_role_excludes_stale_and_other_club_observations() -> None:
    p = projection()
    profile = p.home.players[1].profile
    original = profile.role_history[0]
    cutoff = datetime.fromisoformat(p.feature_cutoff)
    stale = replace(
        original,
        kickoff=clock(cutoff - timedelta(days=28, seconds=1)),
        finished_at=clock(cutoff - timedelta(days=27, hours=21)),
    )
    assert forecast_role(replace(profile, role_history=(stale,)), p) is None
    boundary = replace(stale, kickoff=clock(cutoff - timedelta(days=28)))
    assert forecast_role(replace(profile, role_history=(boundary,)), p) == original.provider_role
    prior = replace(original, provider_role="F")
    other_club = replace(
        original,
        fixture=original.fixture + 1,
        club=p.away.club,
        kickoff=clock(datetime.fromisoformat(original.kickoff) + timedelta(days=1)),
        finished_at=clock(datetime.fromisoformat(original.finished_at) + timedelta(days=1)),
        provider_role="M",
    )
    profile = replace(profile, role_history=(prior, other_club))
    assert forecast_role(profile, p) == "F"
    assert forecast_role(replace(profile, club=p.away.club), p) == "M"
    assert forecast_role(replace(profile, role_inventory_complete=False), p) is None


def test_lagged_role_refuses_contradictory_latest_timestamp() -> None:
    p = projection()
    player = p.home.players[1]
    first = player.profile.role_history[0]
    other = replace(first, fixture=first.fixture + 1, provider_role="F")
    profile = replace(player.profile, role_history=(first, other))
    with pytest.raises(ValueError, match="contradict"):
        forecast_role(profile, p)
    p = replace(
        p,
        home=replace(
            p.home,
            players=(p.home.players[0], replace(player, profile=profile), *p.home.players[2:]),
        ),
    )
    with pytest.raises(ValueError, match="contradict"):
        validate_projection(p)


@pytest.mark.parametrize("complete", [None, 1, "complete"])
def test_role_inventory_completeness_requires_boolean(complete: Any) -> None:
    p = projection()
    player = p.home.players[0]
    changed = replace(player, profile=replace(player.profile, role_inventory_complete=complete))
    with pytest.raises(ValueError, match="Boolean"):
        validate_projection(
            replace(p, home=replace(p.home, players=(changed, *p.home.players[1:])))
        )


def test_complete_role_inventory_requires_hash_and_old_schema_is_refused() -> None:
    p = projection()
    player = p.home.players[0]
    changed = replace(player, profile=replace(player.profile, role_inventory_sha256=None))
    with pytest.raises(ValueError, match="inventory needs"):
        validate_projection(
            replace(p, home=replace(p.home, players=(changed, *p.home.players[1:])))
        )
    raw = encoded({"version": "football_observed_tactical_inputs_v1", "projection": asdict(p)})
    with pytest.raises(ValueError, match="version"):
        read_observed_projection(raw, expected_sha256=sha(raw))


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("version", "unknown", "provenance"),
        ("revision", "main", "provenance"),
        ("feature_cutoff", "2025-10-09T11:59:59Z", "replay clocks"),
        ("generated_at", "2026-09-02T00:00:01Z", "replay clocks"),
        ("latest_native_history_kickoff", "2025-10-09T11:00:00Z", "replay clocks"),
        ("recorded_at", "2025-10-09T12:00:01Z", "replay clocks"),
        ("retrieved_at", "2025-10-09T12:00:00Z", "replay clocks"),
        ("retrieved_at", "2026-09-02T00:00:01Z", "replay clocks"),
    ],
)
def test_replay_provenance_clock_clauses_are_independently_pinned(field, value, match) -> None:
    p = replayed().projection
    validate_projection(p, allow_released_2025_26=True)
    with pytest.raises(ValueError, match=match):
        validate_projection(
            replace(p, replay=replace(p.replay, **{field: value})), allow_released_2025_26=True
        )


def test_replay_inventory_and_individual_source_bindings_refuse_independently() -> None:
    p = replayed().projection
    r = p.replay
    assert r is not None
    hashes = r.source_hashes
    for changed, match in (
        (replace(r, source_hashes=(*hashes, hashes[0])), "unique"),
        (
            replace(r, source_hashes=tuple(x for x in hashes if x[0] != "teams.csv")),
            "requires original history",
        ),
        (
            replace(
                r,
                source_hashes=tuple(
                    (n, "c" * 64 if n == "native_baseline.json" else h) for n, h in hashes
                ),
            ),
            "hash binding",
        ),
        (
            replace(
                r,
                source_hashes=tuple(
                    (n, "c" * 64 if n == "players_raw.csv" else h) for n, h in hashes
                ),
            ),
            "hash binding",
        ),
    ):
        with pytest.raises(ValueError, match=match):
            validate_projection(replace(p, replay=changed), allow_released_2025_26=True)
    with pytest.raises(ValueError, match="original revision clock"):
        validate_projection(
            replace(p, roster_source=replace(p.roster_source, published_at="2025-10-09T10:59:59Z")),
            allow_released_2025_26=True,
        )


def test_replay_target_week_and_generation_cutoff_refuse_before_any_outcome_labels() -> None:
    o = replace(replayed(), physical_goals=object())
    with pytest.raises(ValueError, match="Whole target"):
        validate_header(
            o,
            cutoff=CUTOFF,
            target_season="2025-26",
            target_gameweek=5,
            allowed_seasons=("2025-26",),
            allow_released_2025_26=True,
        )
    p = o.projection
    p = replace(p, generated_at=CUTOFF, replay=replace(p.replay, generated_at=CUTOFF))
    validate_projection(p, allow_released_2025_26=True)
    with pytest.raises(ValueError, match="generated inputs follow"):
        validate_header(
            replace(o, projection=p),
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweek=5,
            allowed_seasons=("2025-26",),
            allow_released_2025_26=True,
        )


def test_current_source_publication_cannot_follow_its_retrieval() -> None:
    p = projection(current=True)
    with pytest.raises(ValueError, match="source clocks"):
        validate_projection(
            replace(p, native_source=replace(p.native_source, published_at=p.decision_at))
        )


def test_fm_publication_cutoff_is_independent_of_source_acquisition_order() -> None:
    p = projection(current=True)
    p = replace(p, feature_cutoff=p.generated_at, generated_at="2026-10-09T11:30:00Z")
    validate_projection(p)
    first = p.home.players[0]
    assert first.profile.trait_source is not None
    later = replace(
        first.profile.trait_source,
        published_at="2026-10-09T11:15:00Z",
        retrieved_at="2026-10-09T11:15:00Z",
    )
    changed = replace(first, profile=replace(first.profile, trait_source=later))
    with pytest.raises(ValueError, match="FM attributes were published"):
        validate_projection(
            replace(p, home=replace(p.home, players=(changed, *p.home.players[1:])))
        )


@pytest.mark.parametrize("clause", ["kickoff", "cutoff", "retrieval"])
def test_each_role_finish_clause_refuses_independently(clause: str) -> None:
    p = projection(current=True)
    first = p.home.players[0]
    role = first.profile.role_history[0]
    if clause == "kickoff":
        role = replace(role, finished_at=role.kickoff)
    elif clause == "cutoff":
        role = replace(role, finished_at=p.feature_cutoff)
    else:
        role = replace(
            role, source=replace(role.source, published_at=role.kickoff, retrieved_at=role.kickoff)
        )
    changed = replace(first, profile=replace(first.profile, role_history=(role,)))
    with pytest.raises(ValueError, match=r"role.*finished|role.*unavailable"):
        validate_projection(
            replace(p, home=replace(p.home, players=(changed, *p.home.players[1:])))
        )
