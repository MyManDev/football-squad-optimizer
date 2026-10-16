"""Historical facts and current reconstruction clocks are kept distinct."""

import csv
import hashlib
import io
from dataclasses import asdict, replace

import pytest
from tests.fixtures.football_phase_fixtures import (
    bootstrap_document,
    duty_capture,
    native_case,
    observation_documents,
    projection_document,
    raw_bytes,
    read_observation,
    read_projection,
    source,
)

from squadopt.features.football_phase_inputs import (
    PhaseDutyCapture,
    PhaseDutyPlayer,
    PhaseReplay,
    observation_digest,
    validate_observation,
    validate_observation_header,
)
from squadopt.features.football_phase_replay import read_replayed_phase_duties
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
        valid_until=documents[0]["decision_at"],
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
    assert model.metadata.contract_version == "football_phase_duty_replay_fit_v2"
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
    assert observation_digest(read_observation()) == (
        "7e8fba7d8245a7b9eaa590cfe98d9aab1e9c7e4841f670b4612aee4821150895"
    )


def _validate_header(observation, **overrides):
    validate_observation_header(
        observation,
        **(
            dict(
                training_cutoff=CUTOFF,
                allowed_seasons=("2025-26",),
                allow_released_2025_26=True,
            )
            | overrides
        ),
    )


@pytest.mark.parametrize("missing", ["fixtures.csv", "gws/merged_gw.csv"])
def test_calendar_and_history_hash_are_individually_required(missing):
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    _validate_header(observation)
    replay = replace(
        observation.replay,
        source_hashes=tuple(
            pair for pair in observation.replay.source_hashes if pair[0] != missing
        ),
    )
    with pytest.raises(ValueError, match="calendar and history"):
        _validate_header(replace(observation, replay=replay))


@pytest.mark.parametrize(
    "replay_changes,duty_changes,baseline_changes",
    [
        # Only recorded <= feature fails; recording still precedes the decision.
        ({"recorded_at": "2025-08-01T11:00:00Z", "feature_cutoff": "2025-08-01T10:00:00Z"}, {}, {}),
        ({"feature_cutoff": "2025-08-01T12:00:01Z"}, {}, {}),
        ({"retrieved_at": "2025-08-01T12:00:00Z"}, {"captured_at": "2025-08-01T12:00:00Z"}, {}),
        ({"retrieved_at": "2026-10-15T19:00:01Z"}, {"captured_at": "2026-10-15T19:00:01Z"}, {}),
        ({"generated_at": CUTOFF}, {}, {"captured_at": CUTOFF, "published_at": CUTOFF}),
        # Four hours separate history and feature cutoff; only history < recording fails.
        (
            {
                "recorded_at": "2025-08-01T08:00:00Z",
                "latest_history_kickoff": "2025-08-01T08:00:00Z",
            },
            {},
            {},
        ),
        # History precedes recording; the gap is exactly three hours, not strictly greater.
        ({"latest_history_kickoff": "2025-08-01T09:00:00Z"}, {}, {}),
    ],
)
def test_each_replay_clock_inequality_is_pinned_alone(
    replay_changes, duty_changes, baseline_changes
):
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    _validate_header(observation)
    broken = replace(
        observation,
        replay=replace(observation.replay, **replay_changes),
        duties=replace(observation.duties, **duty_changes),
        baseline_source=replace(observation.baseline_source, **baseline_changes),
    )
    with pytest.raises(ValueError, match="Replay clocks"):
        _validate_header(broken)


@pytest.mark.parametrize(
    "field,changes",
    [
        ("duties", {"snapshot_id": "git:" + "c" * 40}),
        ("duties", {"source_fingerprint": "c" * 64}),
        ("duties", {"captured_at": "2026-10-15T18:00:01Z"}),
        ("baseline_source", {"captured_at": "2026-10-15T19:00:01Z"}),
        ("baseline_source", {"published_at": "2026-10-15T19:00:01Z"}),
    ],
)
def test_each_replay_receipt_binding_is_pinned_alone(field, changes):
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    _validate_header(observation)
    broken = replace(observation, **{field: replace(getattr(observation, field), **changes)})
    with pytest.raises(ValueError, match="does not bind"):
        _validate_header(broken)


@pytest.mark.parametrize("selection", [None, 0, 1, "True"])
def test_header_and_reader_release_selection_require_boolean_before_labels(selection):
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    with pytest.raises(ValueError, match="explicit Boolean"):
        _validate_header(observation, allow_released_2025_26=selection)
    documents[0]["events"] = "must not be decoded"
    with pytest.raises(ValueError, match="explicit Boolean"):
        read_observation(documents, **(arguments | {"allow_released_2025_26": selection}))


def _csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _read_capture(replay, *, season, decision):
    bootstrap = bootstrap_document()
    players, teams = _csv_bytes(bootstrap["elements"]), _csv_bytes(bootstrap["teams"])
    hashes = dict(replay.source_hashes)
    hashes.update(
        {
            "players_raw.csv": hashlib.sha256(players).hexdigest(),
            "teams.csv": hashlib.sha256(teams).hexdigest(),
        }
    )
    replay = replace(replay, source_hashes=tuple(hashes.items()))
    capture = read_replayed_phase_duties(
        players,
        teams,
        season=season,
        decision_at=decision,
        valid_until=decision,
        replay=replay,
        model_use_approved=True,
        model_use_evidence_ref="synthetic-only",
        allow_released_2025_26=True,
    )
    return capture, replay


def test_reader_output_composes_into_replayed_observation():
    documents, arguments = replay_case()
    arguments["duties"], arguments["replay"] = _read_capture(
        arguments["replay"], season="2025-26", decision=documents[0]["decision_at"]
    )
    observation = read_observation(documents, **arguments)
    assert observation.duties == arguments["duties"]
    assert observation.replay.retrieved_at == RETRIEVED
    assert observation.replay.source_hashes == tuple(sorted(arguments["replay"].source_hashes))


@pytest.mark.parametrize("legacy_validity", [False, True])
def test_replayed_capture_cannot_become_later_projection_or_original_observation(legacy_validity):
    _documents, arguments = replay_case()
    replay = replace(
        arguments["replay"],
        recorded_at="2026-08-01T10:00:00Z",
        retrieved_at="2026-08-20T10:00:00Z",
        generated_at="2026-08-20T11:00:00Z",
        feature_cutoff="2026-08-01T12:00:00Z",
        latest_history_kickoff="2026-07-25T12:00:00Z",
    )
    capture, _ = _read_capture(replay, season="2026-27", decision=replay.feature_cutoff)
    if legacy_validity:
        capture = replace(capture, valid_until="2027-07-01T00:00:00Z")
    with pytest.raises(ValueError, match="requires explicit replay provenance"):
        read_projection(projection_document(native_case()[0]), duties=capture)
    original = read_observation()
    later = replace(
        original,
        season="2026-27",
        duties=capture,
        decision_at="2026-09-01T12:00:00Z",
        kickoff="2026-09-02T12:00:00Z",
        outcome_available_at="2026-09-02T15:00:00Z",
        baseline_source=replace(
            original.baseline_source,
            published_at="2026-09-01T12:00:00Z",
            captured_at="2026-09-01T12:00:00Z",
        ),
        outcome_source=replace(
            original.outcome_source, published_at=RETRIEVED, captured_at=RETRIEVED
        ),
        totals_source=replace(
            original.totals_source, published_at=RETRIEVED, captured_at=RETRIEVED
        ),
    )
    with pytest.raises(ValueError, match="requires explicit replay provenance"):
        _validate_header(later, allowed_seasons=("2026-27",))


@pytest.mark.parametrize("expiry", [RETRIEVED, "2027-07-01T00:00:00Z"])
@pytest.mark.parametrize("serialized", [False, True])
def test_direct_or_restored_replay_duties_cannot_bypass_validity_gate(expiry, serialized):
    documents, arguments = replay_case()
    original = read_observation(documents, **arguments)
    duties = replace(arguments["duties"], valid_until=expiry)
    if serialized:
        fields = asdict(duties)
        fields["players"] = tuple(PhaseDutyPlayer(**row) for row in fields["players"])
        duties = PhaseDutyCapture(**fields)
    with pytest.raises(ValueError, match="Replay duty validity"):
        read_observation(documents, **(arguments | {"duties": duties}))
    with pytest.raises(ValueError, match="Replay duty validity"):
        _validate_header(replace(original, duties=duties))


def test_original_observation_reader_refuses_known_replay_identity():
    original = read_observation()
    duties = replace(original.duties, snapshot_id="git:" + "a" * 40)
    with pytest.raises(ValueError, match="requires explicit replay provenance"):
        read_observation(duties=duties)


@pytest.mark.parametrize(
    "field",
    [
        "source_hashes",
        "recorded_at",
        "retrieved_at",
        "feature_cutoff",
        "latest_history_kickoff",
        "generated_at",
    ],
)
def test_replay_digest_normalizes_source_order_and_equivalent_utc_clocks(field):
    documents, arguments = replay_case()
    observation = read_observation(documents, **arguments)
    value = getattr(observation.replay, field)
    alternate = replace(
        observation.replay,
        **{
            field: tuple(reversed(value))
            if field == "source_hashes"
            else value.replace("Z", "+00:00")
        },
    )
    assert alternate != observation.replay
    assert observation_digest(observation) == observation_digest(
        replace(observation, replay=alternate)
    )
    assert (
        _fit_rows((observation,)).metadata
        == _fit_rows((replace(observation, replay=alternate),)).metadata
    )


def _fit_rows(rows, **overrides):
    return PhaseDutyModel().fit(
        rows,
        **(
            dict(
                cutoff=CUTOFF,
                allowed_seasons=("2024-25", "2025-26"),
                target_season="2026-27",
                target_gameweek=7,
                allow_released_2025_26=True,
            )
            | overrides
        ),
    )


def test_same_rules_original_and_replay_rows_fit_together_in_deterministic_order():
    documents, arguments = replay_case()
    replayed, original = read_observation(documents, **arguments), read_observation()
    model = _fit_rows((replayed, original))
    assert model.metadata == _fit_rows((original, replayed)).metadata
    assert tuple(row.replay is not None for row in model.metadata.training_receipts) == (
        False,
        True,
    )
    assert model.metadata.goal_events == 10
    assert model.metadata.released_2025_26 is True


def test_mixed_rules_fit_refuses_before_inspecting_event_labels():
    documents, arguments = replay_case()
    replayed = read_observation(documents, **arguments)
    original = replace(read_observation(), rules_version="other-rules", events=None)
    with pytest.raises(ValueError, match="one coherent FPL rules version"):
        _fit_rows((original, replayed))


def test_release_option_without_released_or_replay_rows_is_ordinary_fit():
    model = _fit_rows((read_observation(),))
    assert model.metadata.contract_version == "football_phase_duty_fit_v2"
    assert model.metadata.released_2025_26 is False


def test_released_original_capture_does_not_require_replay():
    documents, _arguments = replay_case()
    original = read_observation(
        documents,
        allowed_seasons=("2025-26",),
        training_cutoff=CUTOFF,
        allow_released_2025_26=True,
    )
    assert original.replay is None
    assert _fit_rows((original,)).metadata.released_2025_26 is True
