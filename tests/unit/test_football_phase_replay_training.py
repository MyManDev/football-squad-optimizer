"""Historical facts and current reconstruction clocks are kept distinct."""

from dataclasses import replace

import pytest
from tests.fixtures.football_phase_fixtures import (
    duty_capture,
    observation_documents,
    raw_bytes,
    read_observation,
    source,
)

from squadopt.features.football_phase_inputs import (
    PhaseReplay,
    observation_digest,
    validate_observation,
)
from squadopt.prediction.football_phase_duties import PhaseDutyModel

RETRIEVED = "2026-10-15T18:00:00Z"
GENERATED = "2026-10-15T19:00:00Z"
CUTOFF = "2026-10-15T20:00:00Z"


def replay_case():
    documents = observation_documents(season="2025-26")
    for document in documents:
        for key in ("decision_at", "kickoff", "outcome_available_at"):
            if key in document:
                document[key] = document[key].replace("2024-", "2025-")
    replay = PhaseReplay(
        "a" * 40,
        "2025-08-01T10:00:00Z",
        RETRIEVED,
        tuple(
            (name, "b" * 64)
            for name in ("players_raw.csv", "teams.csv", "fixtures.csv", "gws/merged_gw.csv")
        ),
        documents[0]["decision_at"],
        "2025-07-25T12:00:00Z",
        GENERATED,
    )
    duties = replace(
        duty_capture(season="2025-26", decision=documents[0]["decision_at"]),
        snapshot_id="git:" + replay.revision,
        source_fingerprint="b" * 64,
        captured_at=RETRIEVED,
    )
    arguments = dict(
        duties=duties,
        replay=replay,
        allowed_seasons=("2025-26",),
        training_cutoff=CUTOFF,
        allow_released_2025_26=True,
        baseline_source=source(raw_bytes(documents[2]), kind="baseline", when=GENERATED),
        outcome_source=source(raw_bytes(documents[0]), kind="phase-events", when=RETRIEVED),
        totals_source=source(raw_bytes(documents[1]), kind="fpl-totals", when=RETRIEVED),
    )
    return documents, arguments


def test_released_replay_fits_without_forging_original_capture():
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    assert observation.duties.captured_at == RETRIEVED
    assert observation.baseline_source.captured_at == GENERATED
    model = PhaseDutyModel().fit(
        (observation,),
        cutoff=CUTOFF,
        allowed_seasons=("2025-26",),
        target_season="2026-27",
        target_gameweek=7,
        allow_released_2025_26=True,
    )
    assert model.metadata.goal_events == 5
    assert model.metadata.assist_events == 2
    assert model.metadata.released_2025_26
    assert model.metadata.contract_version == "football_phase_duty_replay_fit_v1"
    assert model.metadata.training_receipts[0].replay == observation.replay
    assert observation_digest(observation) != observation_digest(replace(observation, replay=None))


def test_release_and_replay_are_separate_explicit_requirements():
    documents, arguments = replay_case()
    with pytest.raises(ValueError, match="protect"):
        read_observation(documents, **(arguments | {"allow_released_2025_26": False}))
    with pytest.raises(ValueError, match="cutoff"):
        read_observation(documents, **(arguments | {"replay": None}))
    observation = read_observation(documents, **arguments)
    with pytest.raises(ValueError, match="protect"):
        PhaseDutyModel().fit(
            (observation,),
            cutoff=CUTOFF,
            allowed_seasons=("2025-26",),
            target_season="2026-27",
            target_gameweek=7,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"recorded_at": "2025-08-02T00:00:00Z"},
        {"feature_cutoff": "2025-08-01T12:00:01Z"},
        {"latest_history_kickoff": "2025-08-01T10:00:00Z"},
        {"generated_at": CUTOFF},
        {"retrieved_at": "2026-10-15T19:00:01Z"},
        {"revision": "c" * 40},
        {"revision": "not-a-commit"},
        {"source_hashes": (("players_raw.csv", "b" * 64),)},
        {"version": "invented"},
    ],
)
def test_replay_refuses_changed_clocks_or_unbound_sources_before_labels(changes):
    documents, arguments = replay_case()
    arguments["replay"] = replace(arguments["replay"], **changes)
    # Malformed event content must remain unopened until the causal basis passes.
    documents[0]["events"] = "never parse this"
    arguments["outcome_source"] = source(
        raw_bytes(documents[0]), kind="phase-events", when=RETRIEVED
    )
    with pytest.raises(ValueError, match=r"[Rr]eplay|revision"):
        read_observation(documents, **arguments)


def test_replay_cannot_admit_target_week_or_skip_full_credit_validation():
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    with pytest.raises(ValueError, match="target"):
        validate_observation(
            observation,
            training_cutoff=CUTOFF,
            allowed_seasons=("2025-26",),
            allow_released_2025_26=True,
            excluded_target=("2025-26", 1),
        )
    broken = replace(observation, events=observation.events[:-1])
    with pytest.raises(ValueError, match="reconcile"):
        validate_observation(
            broken,
            training_cutoff=CUTOFF,
            allowed_seasons=("2025-26",),
            allow_released_2025_26=True,
        )


def test_frozen_observation_digest_is_unchanged():
    import hashlib
    import json
    from dataclasses import asdict

    observation = read_observation()
    old_fields = asdict(observation)
    old_fields.pop("replay")
    old_digest = hashlib.sha256(
        json.dumps(old_fields, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert observation_digest(observation) == old_digest
