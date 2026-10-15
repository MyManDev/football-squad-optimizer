"""Synthetic receipts exercise replay policy without opening historical data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import numpy as np
import pytest
from tests.unit.test_football_unit_experiment import document
from tests.unit.test_football_unit_strength import (
    catalog,
    observation,
    observations,
    projection,
    unit,
)

from squadopt.experiments.football_unit_experiment import _result_receipt
from squadopt.features.football_unit_catalog import read_unit_observations, read_unit_projection
from squadopt.features.football_unit_inputs import (
    UNIT_PREFIX_CLOCK_VERSION,
    SourceRecord,
    UnitExposureClock,
    UnitHistoricalReplay,
    UnitObservation,
)
from squadopt.prediction.football_unit_strength import (
    UNIT_REPLAY_FIT_VERSION,
    FootballUnitStrengthModel,
    _canonical,
    _fingerprint,
    _observation_fingerprint,
    _projection_fingerprint,
)

D = datetime(2025, 10, 4, 10, tzinfo=UTC)
ACQUIRED = datetime(2026, 10, 15, 18, tzinfo=UTC)
GENERATED = ACQUIRED + timedelta(hours=1)
FIT = GENERATED + timedelta(hours=1)


def replay_catalog():
    original = catalog(cutoff=D, season="2025-26")
    replay = UnitHistoricalReplay(
        "a" * 40,
        D - timedelta(days=2),
        ACQUIRED,
        tuple(
            (name, digest * 64)
            for name, digest in (
                ("players_raw.csv", "1"),
                ("teams.csv", "2"),
                ("fixtures.csv", "3"),
                ("gws/merged_gw.csv", "4"),
                ("fm.csv", "5"),
                ("native_baseline.json", "6"),
            )
        ),
        D - timedelta(hours=1),
        D - timedelta(days=3),
        GENERATED,
        "fm",
        "https://example.test/published-fm-version",
    )

    def source(identity, kind, digest, published, captured, effective, version="test-v1"):
        return SourceRecord(
            identity,
            "test-receipts-only",
            version,
            kind,
            digest * 64,
            published,
            captured,
            effective,
            FIT + timedelta(days=5),
            "test-only-explicit-receipt",
            True,
        )

    sources = (
        source(
            "fm",
            "fm",
            "5",
            D - timedelta(days=1),
            ACQUIRED - timedelta(hours=1),
            D - timedelta(days=1),
        ),
        source(
            "reference",
            "provider",
            "4",
            replay.recorded_at,
            ACQUIRED,
            replay.recorded_at,
            "git:" + replay.revision,
        ),
        source("baseline", "provider", "6", GENERATED, GENERATED, replay.feature_cutoff),
    )
    return replace(
        original,
        sources=sources,
        attributes=tuple(replace(x, source_id="fm") for x in original.attributes),
        mappings=tuple(replace(x, source_id="reference") for x in original.mappings)
        + tuple(replace(x, source_id="fm") for x in original.mappings if x.player_id != 12),
        player_attributes=tuple(
            replace(x, source_id="fm")
            for x in original.player_attributes
            if x.source_player_id != "12"
        ),
        baseline_source_id="baseline",
        reference_source_id="reference",
        projection_source_id=None,
        replay=replay,
    )


def replay_observation():
    c = replay_catalog()
    outcome = SourceRecord(
        "observed-prefix",
        "test-receipts-only",
        "prefix-v1",
        "provider",
        "7" * 64,
        GENERATED,
        GENERATED,
        GENERATED,
        FIT + timedelta(days=5),
        "test-only-explicit-receipt",
        True,
    )
    return UnitObservation(
        "2025-26",
        1,
        1,
        D,
        D + timedelta(hours=2),
        GENERATED,
        outcome,
        c,
        True,
        unit(1, replacement=True),
        unit(2),
        unit(1),
        unit(2),
        0,
        40,
        2,
        1,
        1.4,
        0.8,
        UnitExposureClock(outcome.sha256, "fixture1:0:40", "test-only-selection-evidence"),
    )


def current_projection():
    target = projection()
    decision = FIT + timedelta(hours=1)
    c = replace(
        replay_catalog(),
        season="2026-27",
        gameweek=1,
        fixture_id=800,
        decision_cutoff=decision,
        projection_source_id="reference",
        replay=None,
    )
    return replace(
        target,
        season=c.season,
        gameweek=c.gameweek,
        fixture_id=c.fixture_id,
        decision_cutoff=decision,
        kickoff=decision + timedelta(hours=2),
        captured_at=decision,
        catalog=c,
    )


def fitted():
    return FootballUnitStrengthModel(
        (replay_observation(),), cutoff=FIT, allow_released_2025_26=True
    )


def test_replay_keeps_distinct_actual_source_clocks_and_missing_fm():
    c = replay_catalog()
    assert c.sources[0].captured_at < c.sources[1].captured_at < c.sources[2].captured_at
    assert c.replay.fm_game_vintage == "unknown"
    assert c.value(12, c.attributes[0]) is None
    c.validate_unit(unit(1, replacement=True))
    with pytest.raises(ValueError, match="unavailable"):
        c.sources[0].available_at(D)
    with pytest.raises(ValueError, match="unavailable"):
        replace(c, replay=None, projection_source_id="reference")


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "other"},
        {"fm_game_vintage": "2022-06-27"},
        {"revision": "a" * 39},
        {"recorded_at": D + timedelta(days=1)},
        {"latest_history_kickoff": D - timedelta(hours=3)},
        {"latest_history_kickoff": D - timedelta(days=2)},
        {"retrieved_at": D - timedelta(hours=1)},
        {"generated_at": ACQUIRED - timedelta(seconds=1)},
        {"source_hashes": ()},
        {"generated_at": datetime(2026, 10, 15)},
    ],
)
def test_replay_rejects_invalid_clocks_versions_and_source_inventory(changes):
    with pytest.raises(ValueError):
        replace(replay_catalog().replay, **changes)


@pytest.mark.parametrize(
    ("index", "changes"),
    [
        (0, {"sha256": "8" * 64}),
        (0, {"published_at": D + timedelta(hours=1)}),
        (0, {"effective_at": D}),
        (0, {"captured_at": D}),
        (0, {"captured_at": FIT}),
        (0, {"valid_until": D - timedelta(seconds=1)}),
        (1, {"version": "git:" + "b" * 40}),
        (1, {"sha256": "8" * 64}),
        (1, {"captured_at": ACQUIRED + timedelta(seconds=1)}),
        (2, {"sha256": "8" * 64}),
        (2, {"captured_at": FIT}),
        (2, {"effective_at": D}),
    ],
)
def test_replay_binds_named_sources_without_a_generic_bypass(index, changes):
    c = replay_catalog()
    sources = list(c.sources)
    with pytest.raises(ValueError):
        sources[index] = replace(sources[index], **changes)
        replace(c, sources=tuple(sources))


def test_extra_source_stays_strict_and_projection_refuses_replay():
    c = replay_catalog()
    with pytest.raises(ValueError, match="unavailable"):
        replace(c, sources=(*c.sources, replace(c.sources[0], source_id="extra")))
    with pytest.raises(ValueError, match="current unit projection"):
        replace(current_projection(), catalog=c)
    with pytest.raises(ValueError, match="source receipts"):
        replace(catalog(), projection_source_id=None)
    with pytest.raises(ValueError, match="historical decision"):
        replace(c, replay=replace(c.replay, retrieved_at=D))


@pytest.mark.parametrize(
    "changes",
    [
        {"exposure_clock": None},
        {"minutes": 40.1},
        {"minutes": 41},
        {"start_minute": 0.5, "minutes": 39},
        {"start_minute": -1},
        {"exposure_clock": UnitExposureClock("8" * 64, "x", "test-only")},
    ],
)
def test_reported_prefix_clock_is_required_bounded_and_source_bound(changes):
    with pytest.raises(ValueError):
        replace(replay_observation(), **changes)


@pytest.mark.parametrize("release", [1, 0, "true", None])
def test_release_opt_in_requires_real_boolean(release):
    with pytest.raises(ValueError, match="boolean"):
        FootballUnitStrengthModel(
            (replay_observation(),), cutoff=FIT, allow_released_2025_26=release
        )


def test_default_locked_and_generation_fit_order_stays_strict():
    with pytest.raises(ValueError, match="Locked 2025-26"):
        FootballUnitStrengthModel((replay_observation(),), cutoff=FIT)
    with pytest.raises(ValueError, match="before the fitting cutoff"):
        FootballUnitStrengthModel(
            (replay_observation(),), cutoff=GENERATED, allow_released_2025_26=True
        )


def test_fit_exposes_distinct_immutable_contract_and_real_partial_offsets():
    model = fitted()
    result = model.predict(current_projection())
    assert model.training_rows == 2
    assert result.metadata["fit_contract"] == UNIT_REPLAY_FIT_VERSION
    assert result.metadata["training_exposure_clock"] == UNIT_PREFIX_CLOCK_VERSION
    assert result.metadata["allow_released_2025_26"] is True
    assert result.metadata["fm_game_vintage"] == "unknown"
    assert "whole-match" in result.metadata["projection_extrapolation"]
    assert _result_receipt(result)
    assert np.isfinite(model._head.coef_).all()
    neutral = replace(
        current_projection(), states=(replace(current_projection().states[0], own=unit(1)),)
    )
    assert model.predict(neutral).own_goal_rate == 1.4
    with pytest.raises(TypeError):
        result.metadata["fit_contract"] = "legacy"


def test_nonoverlapping_intervals_fit_but_duplicate_source_intervals_refuse():
    first = replace(replay_observation(), minutes=20)
    second = replace(
        first,
        start_minute=20,
        exposure_clock=replace(first.exposure_clock, interval_id="fixture1:20:40"),
    )
    model = FootballUnitStrengthModel((first, second), cutoff=FIT, allow_released_2025_26=True)
    assert model.training_rows == 4
    with pytest.raises(ValueError, match="identities must not be reused"):
        FootballUnitStrengthModel(
            (first, replace(second, exposure_clock=first.exposure_clock)),
            cutoff=FIT,
            allow_released_2025_26=True,
        )
    with pytest.raises(ValueError, match="overlapping"):
        FootballUnitStrengthModel(
            (first, replace(second, start_minute=19)), cutoff=FIT, allow_released_2025_26=True
        )
    with pytest.raises(ValueError, match="separate fit contracts"):
        FootballUnitStrengthModel(
            (first, observation(1, replacement=False)), cutoff=FIT, allow_released_2025_26=True
        )


@pytest.mark.parametrize("mutation", ["contract", "clock", "count", "hash", "late", "release"])
def test_result_boundary_revalidates_replay_receipts(mutation):
    result = fitted().predict(current_projection())
    metadata = dict(result.metadata)
    if mutation == "contract":
        metadata.pop("fit_contract")
    elif mutation == "clock":
        metadata["training_exposure_clock"] = "physical_seconds"
    elif mutation == "count":
        metadata["training_rows"] = 4
    elif mutation == "release":
        metadata["allow_released_2025_26"] = False
    elif mutation == "hash":
        parsed = json.loads(metadata["training_exposure_receipts"][0])
        parsed["clock"]["source_sha256"] = "8" * 64
        metadata["training_exposure_receipts"] = (json.dumps(parsed),)
    else:
        parsed = json.loads(metadata["training_replay_receipts"][0])
        parsed["replay"]["generated_at"] = FIT.isoformat()
        metadata["training_replay_receipts"] = (json.dumps(parsed),)
    with pytest.raises(ValueError):
        _result_receipt(replace(result, metadata=MappingProxyType(metadata)))


def test_legacy_fingerprints_and_none_json_roundtrips_stay_identical():
    c, o, p = catalog(), observations()[0], projection()
    old_catalog = asdict(c)
    old_catalog.pop("replay")
    for key in ("sources", "attributes", "mappings", "player_attributes"):
        old_catalog[key] = sorted(old_catalog[key], key=_canonical)
    assert _fingerprint(c) == hashlib.sha256(_canonical(old_catalog).encode()).hexdigest()
    old_observation = asdict(o)
    old_observation.pop("exposure_clock")
    old_observation["catalog"] = _fingerprint(o.catalog)
    assert (
        _observation_fingerprint(o)
        == hashlib.sha256(_canonical(old_observation).encode()).hexdigest()
    )
    old_projection = asdict(p)
    old_projection["catalog"].pop("replay")
    assert (
        _projection_fingerprint(p)
        == hashlib.sha256(_canonical(old_projection).encode()).hexdigest()
    )
    assert read_unit_observations(document("observations", [asdict(o)])) == (o,)
    assert read_unit_projection(document("projection", asdict(p))) == p


@pytest.mark.parametrize("field", ["replay", "exposure_clock"])
def test_legacy_json_boundary_refuses_nonnull_replay_fields(field):
    value = asdict(observations()[0])
    if field == "replay":
        value["catalog"][field] = {}
    else:
        value[field] = {}
    with pytest.raises(ValueError, match="versioned fields"):
        read_unit_observations(document("observations", [value]))


def test_legacy_metadata_bytes_and_release_only_policy_are_distinct():
    rows = observations()
    cutoff = rows[0].decision_cutoff + timedelta(days=43)
    legacy = FootballUnitStrengthModel(rows, cutoff=cutoff).predict(projection())
    assert hashlib.sha256(_canonical(dict(legacy.metadata)).encode()).hexdigest() == (
        "e92bbc4d4ccf2311018468115fc5de56b3ec563a1964eefc77b5a910f39620e1"
    )
    explicit = FootballUnitStrengthModel(rows, cutoff=cutoff, allow_released_2025_26=True).predict(
        projection()
    )
    assert explicit.metadata["fit_contract"] == "football_unit_explicit_release_fit_v1"
    assert "training_exposure_clock" not in explicit.metadata
    assert _result_receipt(explicit)
    for result in (legacy, explicit):
        changed = dict(result.metadata)
        changed["training_exposure_receipts"] = ()
        with pytest.raises(ValueError):
            _result_receipt(replace(result, metadata=MappingProxyType(changed)))


@pytest.mark.parametrize("mutation", ["overlap", "week_cutoff", "target", "future"])
def test_result_boundary_rechecks_exposure_population(mutation):
    first = replace(replay_observation(), minutes=20)
    second = replace(
        first,
        start_minute=20,
        exposure_clock=replace(first.exposure_clock, interval_id="fixture1:20:40"),
    )
    result = FootballUnitStrengthModel(
        (first, second), cutoff=FIT, allow_released_2025_26=True
    ).predict(current_projection())
    metadata = dict(result.metadata)
    exposures = [json.loads(value) for value in metadata["training_exposure_receipts"]]
    replays = [json.loads(value) for value in metadata["training_replay_receipts"]]
    if mutation == "overlap":
        exposures[1]["start_minute"] = 19
    elif mutation == "week_cutoff":
        exposures[1]["fixture_id"] = 2
        replays[1]["decision_cutoff"] = (D + timedelta(seconds=1)).isoformat()
    elif mutation == "target":
        exposures[1]["season"] = result.season
        exposures[1]["gameweek"] = result.gameweek
    else:
        exposures[1]["season"] = "2027-28"
    metadata["training_exposure_receipts"] = tuple(json.dumps(value) for value in exposures)
    metadata["training_replay_receipts"] = tuple(json.dumps(value) for value in replays)
    with pytest.raises(ValueError):
        _result_receipt(replace(result, metadata=MappingProxyType(metadata)))
