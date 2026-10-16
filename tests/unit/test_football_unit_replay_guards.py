"""Orthogonal replay boundary cases from the owner review, using synthetic receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType

import pytest
from tests.unit.test_football_unit_replay import (
    ACQUIRED,
    FIT,
    GENERATED,
    D,
    current_projection,
    fitted,
    replay_catalog,
    replay_observation,
)
from tests.unit.test_football_unit_strength import observation

from squadopt.experiments.football_unit_experiment import _result_receipt
from squadopt.features.football_fm_attributes import read_scoped_fm_attributes
from squadopt.features.football_unit_inputs import (
    UNIT_LEGACY_REPLAY_VERSION,
    NumericAttributeSpec,
    PlayerMapping,
    UnitExposureClock,
)
from squadopt.prediction.football_unit_strength import (
    UNIT_LEGACY_REPLAY_FIT_VERSION,
    FootballUnitStrengthModel,
    _fingerprint,
)


def test_replay_fm_handoff_selects_historical_mapping_before_later_expiry():
    c = replay_catalog()
    payload = b"uid,trait\n1001,8\n1002,20\n"
    source = replace(c.sources[0], sha256=hashlib.sha256(payload).hexdigest())
    replay = replace(
        c.replay,
        source_hashes=tuple(
            (name, source.sha256 if name == "fm.csv" else digest)
            for name, digest in c.replay.source_hashes
        ),
    )
    # The first mapping expires well before acquisition, but after this decision.
    mappings = (
        PlayerMapping("fm", "1001", 1, 1, D - timedelta(days=1), D + timedelta(days=30)),
        PlayerMapping("fm", "1002", 2, 1, D - timedelta(days=1), ACQUIRED),
    )
    spec = NumericAttributeSpec("trait", "fm", 1, 20, "rating", "explicit test trait")
    options = dict(
        source=source,
        cutoff=D,
        mappings=mappings,
        attributes=(spec,),
        attribute_columns={"trait": "trait"},
        uid_column="uid",
    )
    with pytest.raises(ValueError, match="unavailable"):
        read_scoped_fm_attributes(payload, **options)
    scoped = read_scoped_fm_attributes(payload, replay=replay, **options)
    base = replace(
        c,
        sources=(source, *c.sources[1:]),
        attributes=(),
        mappings=tuple(x for x in c.mappings if x.source_id != "fm"),
        player_attributes=(),
        replay=replay,
    )
    result = scoped.add_to_catalog(base, attributes=(spec,))
    assert result.value(1, spec) == 8
    assert result.value(2, spec) == 20
    assert scoped.cutoff == result.decision_cutoff == D
    # A receipt made at another historically admissible decision cannot be handed off.
    earlier = read_scoped_fm_attributes(
        payload, replay=replay, **{**options, "cutoff": D - timedelta(minutes=1)}
    )
    with pytest.raises(ValueError, match="equal the catalog decision"):
        earlier.add_to_catalog(base, attributes=(spec,))
    changed = replace(scoped, replay=replace(replay, fm_version_reference="different evidence"))
    with pytest.raises(ValueError, match="exact replay basis"):
        changed.add_to_catalog(base, attributes=(spec,))
    with pytest.raises(ValueError, match="historical decision"):
        read_scoped_fm_attributes(payload, replay=replay, **{**options, "cutoff": ACQUIRED})


def test_feature_cutoff_after_decision_is_not_hidden_by_source_mismatch():
    c = replay_catalog()
    replay = replace(c.replay, feature_cutoff=D + timedelta(minutes=1))
    sources = (
        *c.sources[:2],
        replace(
            c.sources[2], effective_at=replay.feature_cutoff, valid_until=D + timedelta(minutes=1)
        ),
    )
    with pytest.raises(ValueError, match="historical decision"):
        replace(c, replay=replay, sources=sources)


def test_projection_refuses_replay_even_with_named_projection_source_and_matching_scope():
    c = replace(replay_catalog(), projection_source_id="reference")
    p = current_projection()
    with pytest.raises(ValueError, match="current unit projection"):
        replace(
            p,
            season=c.season,
            gameweek=c.gameweek,
            fixture_id=c.fixture_id,
            decision_cutoff=D,
            captured_at=D,
            kickoff=D + timedelta(hours=2),
            catalog=c,
        )


@pytest.mark.parametrize(
    "index,changes,message",
    [
        (0, {"kind": "provider"}, "identities"),
        (1, {"kind": "fm"}, "identities"),
        (2, {"kind": "fm"}, "identities"),
        (1, {"published_at": D - timedelta(days=1)}, "identities"),
        (2, {"published_at": D}, "identities"),
        (1, {"effective_at": D}, "feature cutoff"),
        (1, {"valid_until": D - timedelta(seconds=1)}, "validity"),
        (2, {"valid_until": D - timedelta(seconds=1)}, "validity"),
        (1, {"valid_until": ACQUIRED}, "expire before retrieval"),
        (2, {"valid_until": ACQUIRED}, "expire before retrieval"),
    ],
)
def test_each_named_replay_source_clause_has_an_independent_case(index, changes, message):
    c = replay_catalog()
    sources = list(c.sources)
    sources[index] = replace(sources[index], **changes)
    with pytest.raises(ValueError, match=message):
        replace(c, sources=tuple(sources))


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"fm_version_reference": " "}, "version evidence"),
        ({"native_fit_sha256": None}, "fit SHA256"),
        ({"native_fit_sha256": "g" * 64}, "fit SHA256"),
        ({"native_training_cutoff": None}, "training cutoff"),
        ({"native_training_cutoff": D}, "feature cutoff"),
        ({"native_training_cutoff": D.replace(tzinfo=None)}, "timezone"),
        ({"recorded_at": D - timedelta(days=3) + timedelta(hours=1)}, "settled"),
        ({"recorded_at": D - timedelta(days=3) + timedelta(hours=3)}, "settled"),
    ],
)
def test_replay_evidence_and_revision_settlement_are_independent(changes, message):
    with pytest.raises(ValueError, match=message):
        replace(replay_catalog().replay, **changes)


def test_hash_order_is_canonical_and_replay_identity_is_fingerprinted():
    c = replay_catalog()
    reordered = replace(c.replay, source_hashes=tuple(reversed(c.replay.source_hashes)))
    assert reordered.source_hashes == tuple(sorted(c.replay.source_hashes))
    assert _fingerprint(replace(c, replay=reordered)) == _fingerprint(c)
    changed = replace(c.replay, fm_version_reference="another explicit evidence reference")
    assert _fingerprint(replace(c, replay=changed)) != _fingerprint(c)


def test_catalog_rejects_untyped_replay_with_all_named_sources_present():
    with pytest.raises(ValueError, match="typed immutable receipt"):
        replace(replay_catalog(), projection_source_id="reference", replay=object())


@pytest.mark.parametrize("field", ["decision_cutoff", "kickoff", "outcome_available_at"])
def test_observation_requires_independent_explicit_timezones(field):
    row = replay_observation()
    with pytest.raises(ValueError, match="timezone"):
        replace(row, **{field: getattr(row, field).replace(tzinfo=None)})


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"exposure_clock": object()}, "typed immutable"),
        ({"minutes": 39.5}, "integer"),
        ({"exposure_clock": None}, "declared observed"),
    ],
)
def test_replay_exposure_guards_do_not_depend_on_overlong_duration(changes, message):
    with pytest.raises(ValueError, match=message):
        replace(replay_observation(), **changes)


@pytest.mark.parametrize("changes", [{"interval_id": " "}, {"selection_reference": ""}])
def test_prefix_clock_requires_both_identity_and_selection(changes):
    with pytest.raises(ValueError, match="interval and selection"):
        replace(replay_observation().exposure_clock, **changes)


def test_prefix_clock_cannot_be_attached_to_a_nonreplay_observation():
    row = observation(1, replacement=False)
    clock = UnitExposureClock(row.outcome_source.sha256, "x", "test selection")
    with pytest.raises(ValueError, match="historical replay contract"):
        replace(row, minutes=20, exposure_clock=clock)


@pytest.fixture(scope="module")
def result():
    return fitted().predict(current_projection())


def boundary(result, *, replay=None, exposure=None, metadata=None, sources=None):
    values = dict(result.metadata)
    if replay is not None:
        values["training_replay_receipts"] = (json.dumps(replay),)
    if exposure is not None:
        values["training_exposure_receipts"] = (json.dumps(exposure),)
    if metadata:
        values.update(metadata)
    if sources:
        values["training_source_receipts"] = (tuple(tuple(row) for row in sources),)
    return _result_receipt(replace(result, metadata=MappingProxyType(values)))


@pytest.mark.parametrize(
    "field",
    [
        "training_selection",
        "exposure_semantics",
        "projection_extrapolation",
        "fm_effective_semantics",
    ],
)
def test_boundary_pins_every_replay_statement(result, field):
    assert _result_receipt(result)
    with pytest.raises(ValueError, match="exact"):
        boundary(result, metadata={field: ""})


def test_boundary_source_recheck_does_not_depend_on_fit_time_availability(result):
    sources = [list(row) for row in result.metadata["training_source_receipts"][0]]
    reference = next(row for row in sources if row[0] == "reference")
    reference[5] = (D + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="identities"):
        boundary(result, sources=sources)


def test_boundary_generation_equal_fit_is_independent_of_source_and_outcome_availability(result):
    exposure = json.loads(result.metadata["training_exposure_receipts"][0])
    exposure["outcome_available_at"] = ACQUIRED.isoformat()
    for field in ("published_at", "captured_at", "effective_at"):
        exposure["outcome_source"][field] = ACQUIRED.isoformat()
    assert boundary(result, exposure=exposure)
    with pytest.raises(ValueError, match="generated after fitting"):
        boundary(result, exposure=exposure, metadata={"training_cutoff": GENERATED.isoformat()})


@pytest.mark.parametrize(
    "mutation",
    [
        "fractional",
        "fractional_start",
        "negative",
        "zero",
        "over40",
        "kickoff",
        "settled",
        "at_fit",
        "source_availability",
        "clock_hash",
        "release_false",
    ],
)
def test_boundary_rechecks_each_exposure_clause(result, mutation):
    exposure = json.loads(result.metadata["training_exposure_receipts"][0])
    metadata = {}
    if mutation == "fractional":
        exposure["minutes"] = 39.5
    elif mutation == "fractional_start":
        exposure["start_minute"], exposure["minutes"] = 0.5, 39
    elif mutation == "negative":
        exposure["start_minute"], exposure["minutes"] = -1, 39
    elif mutation == "zero":
        exposure["minutes"] = 0
    elif mutation == "over40":
        exposure["minutes"] = 41
    elif mutation == "kickoff":
        exposure["kickoff"] = D.isoformat()
    elif mutation == "settled":
        when = D + timedelta(hours=4)
        exposure["outcome_available_at"] = when.isoformat()
        for field in ("published_at", "captured_at", "effective_at"):
            exposure["outcome_source"][field] = when.isoformat()
    elif mutation == "at_fit":
        exposure["outcome_available_at"] = FIT.isoformat()
    elif mutation == "source_availability":
        exposure["outcome_source"]["captured_at"] = (FIT - timedelta(minutes=1)).isoformat()
    elif mutation == "clock_hash":
        exposure["clock"]["source_sha256"] = "e" * 64
    else:
        metadata["allow_released_2025_26"] = False
    with pytest.raises(ValueError):
        boundary(result, exposure=exposure, metadata=metadata)


def test_new_fit_requires_native_receipt_but_legacy_result_remains_readable(result):
    row = replay_observation()
    legacy = replace(
        row.catalog.replay,
        version=UNIT_LEGACY_REPLAY_VERSION,
        native_fit_sha256=None,
        native_training_cutoff=None,
    )
    with pytest.raises(ValueError, match="v2 native baseline"):
        FootballUnitStrengthModel(
            (replace(row, catalog=replace(row.catalog, replay=legacy)),),
            cutoff=FIT,
            allow_released_2025_26=True,
        )
    receipt = json.loads(result.metadata["training_replay_receipts"][0])
    receipt["replay"]["version"] = UNIT_LEGACY_REPLAY_VERSION
    receipt["replay"].pop("native_fit_sha256")
    receipt["replay"].pop("native_training_cutoff")
    assert boundary(
        result, replay=receipt, metadata={"fit_contract": UNIT_LEGACY_REPLAY_FIT_VERSION}
    )
    with pytest.raises(ValueError, match="native baseline replay receipt"):
        boundary(result, replay=receipt)


def test_replayed_sources_cannot_be_reused_as_current_after_dropping_replay():
    c = replay_catalog()
    assert c.sources[1].valid_until == c.sources[2].valid_until == D
    with pytest.raises(ValueError, match="stale"):
        replace(
            c,
            replay=None,
            decision_cutoff=FIT,
            projection_source_id="reference",
            sources=tuple(
                replace(source, valid_until=FIT) if source.kind == "fm" else source
                for source in c.sources
            ),
        )


def test_release_used_tracks_rows_even_when_option_is_enabled():
    row = replay_observation()
    row = replace(row, season="2024-25", catalog=replace(row.catalog, season="2024-25"))
    result = FootballUnitStrengthModel((row,), cutoff=FIT, allow_released_2025_26=True).predict(
        current_projection()
    )
    assert result.metadata["allow_released_2025_26"] is False
    assert _result_receipt(result)
    with pytest.raises(ValueError, match="actual training exposure"):
        boundary(result, metadata={"allow_released_2025_26": True})


@pytest.mark.parametrize("mutation", ["duplicate_interval", "fixture_basis"])
def test_boundary_rechecks_distinct_identity_and_fixture_basis(result, mutation):
    values = dict(result.metadata)
    first = json.loads(values["training_exposure_receipts"][0])
    first["minutes"] = 20
    second = json.loads(json.dumps(first))
    second["start_minute"] = 20
    second["clock"]["interval_id"] = "second"
    if mutation == "duplicate_interval":
        second["clock"]["interval_id"] = first["clock"]["interval_id"]
    else:
        second["kickoff"] = (D + timedelta(hours=3)).isoformat()
    values.update(
        training_rows=4,
        training_source_receipts=values["training_source_receipts"] * 2,
        training_replay_receipts=values["training_replay_receipts"] * 2,
        training_exposure_receipts=(json.dumps(first), json.dumps(second)),
    )
    with pytest.raises(ValueError, match=r"source or fitting policy|one historical basis"):
        _result_receipt(replace(result, metadata=MappingProxyType(values)))


def test_boundary_normalizes_malformed_replay_type_to_value_error(result):
    receipt = json.loads(result.metadata["training_replay_receipts"][0])
    receipt["replay"]["source_hashes"] = 42
    with pytest.raises(ValueError, match="Malformed unit replay"):
        boundary(result, replay=receipt)
