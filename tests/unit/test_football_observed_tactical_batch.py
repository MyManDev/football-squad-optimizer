"""Per-call team-context reuse preserves direct feature rows and exact allocations."""

from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import Any

import numpy as np
import pytest
from tests.unit.test_football_observed_tactical import (
    encoded,
    fit,
    observation,
    projection,
    sha,
)

from squadopt.features import football_observed_tactical_inputs as features
from squadopt.features.football_observed_tactical_inputs import (
    ObservedTacticalPlayer,
    ObservedTacticalProjection,
)
from squadopt.prediction import football_observed_tactical as model_module
from squadopt.prediction.football_observed_tactical import ObservedTacticalModel
from squadopt.prediction.football_observed_tactical_serving import (
    ObservedTacticalServingModel,
    export_observed_tactical_serving_model,
    read_observed_tactical_serving_model,
)


def direct_rows(
    p: ObservedTacticalProjection, players: Sequence[ObservedTacticalPlayer], *, home: bool
) -> dict[str, tuple[dict[str, float | None], ...]]:
    """The previous inference call pattern, one direct feature call per player/head."""
    return {
        head: tuple(
            features.recipient_features(p, player, home=home, head=head) for player in players
        )
        for head in ("goals", "assists")
    }


@pytest.mark.parametrize("home", [True, False])
@pytest.mark.parametrize("missing", [False, True])
def test_batch_matches_direct_rows_including_order_and_missingness(
    home: bool, missing: bool
) -> None:
    p = projection(current=True, missing=missing)
    side = p.home if home else p.away
    players = tuple(reversed(side.players))
    expected = direct_rows(p, players, home=home)
    result = features.recipient_feature_rows(p, players, home=home)
    assert tuple(result) == ("goals", "assists")
    assert result == expected
    for head in result:
        assert [tuple(row.items()) for row in result[head]] == [
            tuple(row.items()) for row in expected[head]
        ]


def test_batch_rows_do_not_share_mutable_dicts_or_leak_to_another_projection() -> None:
    p = projection(current=True)
    players = (p.home.players[0], p.home.players[0], p.home.players[1])
    result = features.recipient_feature_rows(p, players, home=True)
    expected = direct_rows(p, players, home=True)
    all_rows = [row for rows in result.values() for row in rows]
    assert len({id(row) for row in all_rows}) == len(all_rows)
    result["goals"][0]["own_observed_cross_attempts_per_fixture"] = 999.0
    assert result["goals"][1] == expected["goals"][1]
    assert result["assists"] == expected["assists"]
    assert features.recipient_feature_rows(p, players, home=True) == expected
    changed = replace(
        p,
        home=replace(
            p.home,
            observed_fixtures=(replace(p.home.observed_fixtures[0], counts=(9, 2, 3, 4)),),
        ),
    )
    revised = features.recipient_feature_rows(changed, players, home=True)
    assert revised == direct_rows(changed, players, home=True)
    assert revised != expected


def test_foreign_player_and_unknown_direct_head_refuse_before_team_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = projection(current=True)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Team context was built before recipient admission.")

    monkeypatch.setattr(features, "_team_terms", forbidden)
    with pytest.raises(ValueError, match="outside the supplied roster"):
        features.recipient_feature_rows(p, (p.away.players[0],), home=True)
    with pytest.raises(ValueError, match="outside the supplied roster"):
        features.recipient_features(p, p.away.players[0], home=True, head="goals")
    with pytest.raises(ValueError, match="goals or assists"):
        features.recipient_features(p, p.home.players[0], home=True, head="invented")


@pytest.fixture(scope="module")
def fitted() -> ObservedTacticalModel:
    return fit(tuple(observation(i) for i in range(3)))


@pytest.fixture(scope="module")
def compact(fitted: ObservedTacticalModel) -> ObservedTacticalServingModel:
    raw = export_observed_tactical_serving_model(fitted)
    return read_observed_tactical_serving_model(raw, expected_sha256=sha(raw))


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("missing", [False, True])
def test_full_and_compact_outputs_equal_previous_direct_call_pattern_exactly(
    fitted: ObservedTacticalModel,
    compact: ObservedTacticalServingModel,
    monkeypatch: pytest.MonkeyPatch,
    control: bool,
    missing: bool,
) -> None:
    p = projection(current=True, missing=missing)
    before = fitted.metadata_json
    artifact = export_observed_tactical_serving_model(fitted)

    def allocations() -> tuple[Any, ...]:
        return (
            fitted.predict(p, control=control),
            fitted.predict_recipients(p, control=control),
            compact.predict_recipients(p, control=control),
        )

    with monkeypatch.context() as legacy:
        legacy.setattr(model_module, "recipient_feature_rows", direct_rows)
        expected = allocations()
    actual = allocations()
    assert actual == expected
    assert [encoded(asdict(row)) for row in actual] == [encoded(asdict(row)) for row in expected]
    assert fitted.metadata_json == before
    assert export_observed_tactical_serving_model(fitted) == artifact
    for result in actual[1:]:
        for side in (result.home, result.away):
            assert side.players[-1].goal_share == side.players[-1].assist_share == 0.0


@pytest.mark.parametrize("mode", ["full", "recipients", "compact"])
@pytest.mark.parametrize("control", [False, True])
def test_one_recipient_context_per_side_and_no_control_feature_work(
    fitted: ObservedTacticalModel,
    compact: ObservedTacticalServingModel,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    control: bool,
) -> None:
    p = projection(current=True)
    original = features._team_terms
    calls = []

    def counted(value: ObservedTacticalProjection, home: bool) -> dict[str, float | None]:
        calls.append(home)
        return original(value, home)

    monkeypatch.setattr(features, "_team_terms", counted)
    if mode == "full":
        fitted.predict(p, control=control)
    elif mode == "recipients":
        fitted.predict_recipients(p, control=control)
    else:
        compact.predict_recipients(p, control=control)
    # Full prediction independently retains its two paired-rate feature contexts.
    assert calls == (
        [] if control else [True, False, True, False] if mode == "full" else [True, False]
    )


@pytest.mark.parametrize("mode", ["full", "recipients", "compact"])
@pytest.mark.parametrize("bad", ["window", "future_source", "roster"])
def test_source_and_window_guards_precede_all_feature_work(
    fitted: ObservedTacticalModel,
    compact: ObservedTacticalServingModel,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    bad: str,
) -> None:
    p = projection(current=True)
    if bad == "window":
        p = replace(p, gameweek=4)
    elif bad == "future_source":
        p = replace(p, native_source=replace(p.native_source, retrieved_at=p.kickoff))
    else:
        p = replace(p, roster=p.roster[:-1])

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Feature reuse bypassed prediction admission.")

    monkeypatch.setattr(features, "_team_terms", forbidden)
    with pytest.raises(ValueError):
        if mode == "full":
            fitted.predict(p)
        elif mode == "recipients":
            fitted.predict_recipients(p)
        else:
            compact.predict_recipients(p)


def test_unsupported_goal_head_refuses_before_recipient_batch(
    fitted: ObservedTacticalModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = projection(current=True)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Features evaluated before credited-event admission.")

    monkeypatch.setattr(model_module, "recipient_feature_rows", forbidden)
    with pytest.raises(ValueError, match="credited-event support"):
        model_module._recipient_sides(
            p,
            goal_transform=fitted.metadata.goal_transform,
            assist_transform=fitted.metadata.assist_transform,
            goal_events=0,
            assist_events=fitted.metadata.assist_events,
            gammas={
                "goals": np.asarray(fitted.metadata.goal_gamma),
                "assists": np.asarray(fitted.metadata.assist_gamma),
            },
            control=False,
        )
