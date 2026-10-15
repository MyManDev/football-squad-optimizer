"""Prediction reuse agrees exactly with the uncached phase calculation at 34275ebd."""

import hashlib
import itertools
import json
from dataclasses import asdict, replace

import numpy as np
import pytest
from tests.unit.test_football_phase_duties import (
    _fit,
    _observation,
    _players,
    _projection,
    _rank_training,
)

from squadopt.features.football_phase_inputs import PHASES, PhaseState, projection_digest
from squadopt.prediction import football_phase_duties as phase_module
from squadopt.prediction.football_phase_duties import (
    PhaseAllocatedPlayer,
    PhaseStateAllocation,
    _features,
)
from squadopt.prediction.football_phase_serving import (
    export_phase_serving_model,
    read_phase_serving_model,
)


def _bytes(value):
    return _document_bytes(asdict(value))


def _document_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _restore(model):
    payload = export_phase_serving_model(model)
    return read_phase_serving_model(payload, expected_sha256=hashlib.sha256(payload).hexdigest())


@pytest.fixture(scope="module")
def models():
    # Synthetic nonzero effects for every rank field and all five phase compositions.
    observations = tuple(
        replace(row, fixture=10 * phase_index + row.fixture)
        for phase_index, phase in enumerate(PHASES)
        for row in _rank_training(phase)
    )
    full = _fit(observations)
    assert any(value != 0 for head in full.metadata.recipient_heads for value in head.coefficients)
    return full, _restore(full)


def _reference(projection, model):
    """Pre-reuse arithmetic, rebuilding the original feature matrix at every head/phase."""
    codes = tuple(sorted(p.player_code for p in projection.states[0].players))
    totals = {head: np.zeros(len(codes), float) for head in ("goals", "assists")}
    zero_shares = {head: np.zeros(len(codes), float) for head in totals}
    masses = {head: 0.0 for head in totals}
    physical = 0.0
    states = []

    def records(goals, assists, goal_shares, assist_shares):
        return tuple(
            PhaseAllocatedPlayer(code, float(g), float(a), float(gs), float(aps))
            for code, g, a, gs, aps in zip(
                codes, goals, assists, goal_shares, assist_shares, strict=True
            )
        )

    for state in projection.states:
        players = tuple(sorted(state.players, key=lambda p: p.player_code))
        allocated, shares = {}, {}
        for head, mass in (("goals", state.goal_mass), ("assists", state.assist_mass)):
            recipient = np.zeros(len(codes), float)
            exposure = phase_module._exposure(players, head)
            for phase, phase_share in zip(PHASES, model._phase_shares[head], strict=True):
                if phase_share == 0:
                    continue
                features, _ = _features(players, projection.duties, head=head, phase=phase)
                probabilities = phase_module._probabilities(
                    features, exposure, model._coefficients[head, phase]
                )
                recipient += phase_share * probabilities
            allocated[head] = mass * recipient
            shares[head] = recipient
            totals[head] += state.weight * allocated[head]
            zero_shares[head] += state.weight * recipient
            masses[head] += state.weight * mass
        physical += state.weight * state.physical_goal_mass
        states.append(
            PhaseStateAllocation(
                state.state_id,
                state.weight,
                records(
                    allocated["goals"], allocated["assists"], shares["goals"], shares["assists"]
                ),
                state.goal_mass,
                state.assist_mass,
                state.physical_goal_mass,
            )
        )
    gs = totals["goals"] / masses["goals"] if masses["goals"] else zero_shares["goals"]
    aps = totals["assists"] / masses["assists"] if masses["assists"] else zero_shares["assists"]
    return phase_module._PhaseMoments(
        records(totals["goals"], totals["assists"], gs, aps),
        tuple(states),
        tuple(float(v) for v in model._phase_shares["goals"]),
        tuple(float(v) for v in model._phase_shares["assists"]),
        masses["goals"],
        masses["assists"],
        physical,
        projection_digest(projection),
    )


def _case(ranks, zero_mass):
    masks = [mask for mask in itertools.product((False, True), repeat=3) if any(mask)]
    # Equal active masks still have different minute exposures and input order.
    masks += [masks[0], masks[-1]]
    states = []
    for index, mask in enumerate(masks):
        players = tuple(
            replace(p, position=position, assist_weight90=weight)
            for p, position, weight in zip(
                _players(
                    tuple((20 + index * 7 + i) if active else 0 for i, active in enumerate(mask))
                ),
                ("GK", "DEF", "FWD"),
                (0.2, 0.7, 1.3),
                strict=True,
            )
        )
        states.append(
            PhaseState(
                str(index),
                1 / len(masks),
                players[::-1] if index % 2 else players,
                0 if zero_mass else 0.3,
                0 if zero_mass else 0.2,
                1.0,
            )
        )
    p = _projection(states=tuple(states), ranks=ranks)
    duties = replace(
        p.duties,
        players=tuple(
            replace(
                player,
                direct_freekicks_order=ranks[(i + 1) % 3],
                corners_and_indirect_freekicks_order=ranks[(i + 2) % 3],
            )
            for i, player in enumerate(p.duties.players)
        ),
    )
    return replace(p, duties=duties)


@pytest.mark.parametrize("ranks", [(1, 2, 3), (1, 1, 3), (3, None, 1), (None, None, None)])
@pytest.mark.parametrize("zero_mass", [False, True])
def test_all_moments_equal_uncached_calculation_with_rank_and_active_roster_changes(
    models, ranks, zero_mass, monkeypatch
):
    full, compact = models
    projection = _case(ranks, zero_mass)
    before = _bytes(full.metadata)
    expected = asdict(_reference(projection, compact))
    builds = []

    def counted(players, duties, *, head, phase):
        field = phase_module._rank_field(head, phase)
        builds.append((field, tuple(p.minutes > 0 for p in players) if field is not None else ()))
        return _features(players, duties, head=head, phase=phase)

    monkeypatch.setattr(phase_module, "_features", counted)
    for model in (full, compact):
        builds.clear()
        actual = asdict(model.predict(projection))
        actual.pop("metadata" if model is full else "serving_receipt")
        assert actual.pop("model_version") == phase_module.MODEL_VERSION
        assert actual.pop("feature_version") == phase_module.FEATURE_VERSION
        assert _document_bytes(actual) == _document_bytes(expected)
        # Seven active masks, three rank fields, one shared positional matrix.
        assert len(builds) == len(set(builds)) == 22
    assert _bytes(full.metadata) == before
    # Equal active masks must retain their distinct minutes rather than reuse probabilities.
    assert expected["states"][6]["players"] != expected["states"][8]["players"]


def test_feature_reuse_is_local_to_each_projection_and_validates_before_reuse(models):
    full, compact = models
    first, changed = _case((1, 1, 3), False), _case((3, None, 1), False)
    for model in (full, compact):
        original = _bytes(model.predict(first))
        assert model.predict(changed).players != model.predict(first).players
        assert _bytes(model.predict(first)) == original
        bad_state = replace(
            first.states[-1],
            players=tuple(replace(p, position="MID") for p in first.states[-1].players),
        )
        with pytest.raises(ValueError, match="rosters or causal baseline weights"):
            model.predict(replace(first, states=(*first.states[:-1], bad_state)))
        with pytest.raises(ValueError, match="stale or future"):
            model.predict(
                replace(first, duties=replace(first.duties, valid_until="2026-10-08T00:00:00Z"))
            )


def test_unfitted_phase_fields_stay_lazy(monkeypatch):
    full = _fit()
    compact = _restore(full)
    projection = _projection(ranks=(2**63 - 1, None, 1))
    expected = asdict(_reference(projection, compact))

    def positional_only(players, duties, *, head, phase):
        assert phase_module._rank_field(head, phase) is None
        return _features(players, duties, head=head, phase=phase)

    monkeypatch.setattr(phase_module, "_features", positional_only)
    for model in (full, compact):
        actual = asdict(model.predict(projection))
        for name in ("metadata", "serving_receipt", "model_version", "feature_version"):
            actual.pop(name, None)
        assert _document_bytes(actual) == _document_bytes(expected)
        with pytest.raises(ValueError, match="duty rank must be a positive integer identity"):
            model.predict(_projection(ranks=(2**63, None, 1)))


def test_active_duty_player_with_zero_exposure_still_changes_rank_context(models):
    states = tuple(
        PhaseState(str(i), 0.5, _players(minutes, weights=(0, 1, 1)), 0.3, 0.2, 1)
        for i, minutes in enumerate(((0, 60, 90), (30, 60, 90)))
    )
    projection = _projection(states=states, ranks=(1, 1, 3))
    expected = asdict(_reference(projection, models[1]))
    for model in models:
        actual = asdict(model.predict(projection))
        for name in ("metadata", "serving_receipt", "model_version", "feature_version"):
            actual.pop(name, None)
        assert _document_bytes(actual) == _document_bytes(expected)


def test_unavailable_head_and_empty_exposure_keep_their_refusals(models, monkeypatch):
    empty = _fit((_observation(events=()),))
    zero = _projection(states=(PhaseState("zero", 1.0, _players(), 0, 0, 0),))

    def forbidden(*args, **kwargs):
        raise AssertionError("An unsupported phase must not build a feature matrix.")

    with monkeypatch.context() as scoped:
        scoped.setattr(phase_module, "_features", forbidden)
        for model in (empty, _restore(empty)):
            assert model.predict(zero).total_goals == 0
            with pytest.raises(ValueError, match="without historical credited events"):
                model.predict(_projection())
    absent = replace(zero, states=(replace(zero.states[0], players=_players((0, 0, 0))),))
    for model in models:
        actual = model.predict(absent)
        assert all(p.goals_share == p.assists_share == 0 for p in actual.players)
        with pytest.raises(ValueError, match="positive on-field exposure"):
            model.predict(
                replace(
                    absent, states=(replace(absent.states[0], goal_mass=1, physical_goal_mass=1),)
                )
            )
        impossible = _projection(states=(PhaseState("one", 1.0, _players((90, 0, 0)), 1, 1, 1),))
        with pytest.raises(ValueError, match="Player goal plus assist mass"):
            model.predict(impossible)
