"""Independent byte, clock, identity and final-credit checks using invented sources."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest
from tests.football_phase_fixtures import (
    DECISION,
    SEASON,
    bootstrap_document,
    captured_snapshot,
    duty_capture,
    native_case,
    observation_documents,
    projection_document,
    raw_bytes,
    read_observation,
    read_projection,
    source,
)

from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.features.football_phase_inputs import (
    read_phase_duties,
    read_phase_observation,
    read_phase_projection,
    validate_projection,
)


def _read_snapshot(snapshot, **overrides):
    arguments = {
        "season": SEASON,
        "decision_at": DECISION,
        "valid_until": "2026-10-01T00:00:00Z",
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-only",
    }
    return read_phase_duties(snapshot, **(arguments | overrides))


def test_persistent_ids_and_nullable_tied_ranks_are_preserved():
    document = bootstrap_document()
    document["elements"][0]["penalties_order"] = None
    document["elements"][1]["penalties_order"] = 7
    document["elements"][2]["penalties_order"] = 7
    snapshot = captured_snapshot(document)
    capture = _read_snapshot(snapshot)
    players = {player.player_code: player for player in capture.players}
    assert players[1].penalties_order is None
    assert players[2].penalties_order == players[3].penalties_order == 7
    assert players[1].club == 1  # The public team id is101, not the persistent code.
    assert set(players) == set(range(1, 67))
    assert capture.source_fingerprint == snapshot.metadata.fingerprint
    assert capture.snapshot_id == snapshot.metadata.snapshot_id
    assert capture.model_use_evidence_ref == "synthetic-only"
    with pytest.raises(FrozenInstanceError):
        capture.players[0].club = 999
    with pytest.raises(TypeError):
        snapshot.payloads[BOOTSTRAP_PAYLOAD] = b"different"


@pytest.mark.parametrize(
    "damage",
    [
        lambda document: document["elements"][0].pop("penalties_order"),
        lambda document: document["elements"][0].update(penalties_order=0),
        lambda document: document["elements"][0].update(penalties_order=True),
        lambda document: document["elements"][0].update(penalties_order=1.5),
        lambda document: document["elements"][0].update(code=True),
        lambda document: document["elements"][0].update(team=999),
        lambda document: document["elements"].append(deepcopy(document["elements"][0])),
        lambda document: document["teams"][1].update(code=document["teams"][0]["code"]),
        lambda document: document["teams"][1].update(id=document["teams"][0]["id"]),
    ],
)
def test_captured_rank_and_club_ambiguities_are_refused(damage):
    document = bootstrap_document()
    damage(document)
    with pytest.raises(ValueError):
        _read_snapshot(captured_snapshot(document))


@pytest.mark.parametrize(
    "field", ["snapshot_id", "fingerprint", "checksums", "source", "schema_version"]
)
def test_capture_metadata_is_reverified_at_the_parser_boundary(field):
    snapshot = captured_snapshot()
    replacement = (
        {"checksums": {BOOTSTRAP_PAYLOAD: "0" * 64}} if field == "checksums" else {field: "wrong"}
    )
    damaged = replace(snapshot, metadata=replace(snapshot.metadata, **replacement))
    with pytest.raises(ValueError):
        _read_snapshot(damaged)


def test_original_payload_bytes_are_rechecked_before_reading_priorities():
    snapshot = captured_snapshot()
    changed = dict(snapshot.payloads)
    changed[BOOTSTRAP_PAYLOAD] = changed[BOOTSTRAP_PAYLOAD] + b" "
    with pytest.raises(ValueError, match="checksum"):
        _read_snapshot(replace(snapshot, payloads=changed))


@pytest.mark.parametrize(
    "overrides",
    [
        {"decision_at": "2026-09-22T11:59:59Z"},
        {"valid_until": "2026-09-22T11:59:59Z"},
        {"decision_at": "2026-09-22T12:00:00"},
        {"model_use_approved": False},
        {"model_use_approved": 1},
        {"model_use_evidence_ref": ""},
    ],
)
def test_duty_capture_clock_and_admitted_use_are_required(overrides):
    with pytest.raises(ValueError):
        _read_snapshot(captured_snapshot(), **overrides)


def test_raw_phase_credits_reconcile_with_separately_hashed_fpl_totals():
    documents = observation_documents()
    observation = read_observation(documents)
    assert len(observation.players) == 11
    assert sum(total.goals for total in observation.totals) == 5
    assert sum(total.assists for total in observation.totals) == 2
    assert [event.phase for event in observation.events].count("penalty") == 2
    assert observation.baseline_source.raw_sha256 != observation.outcome_source.raw_sha256
    assert observation.outcome_source.raw_sha256 != observation.totals_source.raw_sha256
    assert all(event.scorer != event.assist for event in observation.events)


@pytest.mark.parametrize(
    "damage",
    [
        lambda documents: documents[0].update(complete_coverage=False),
        lambda documents: documents[0].update(rules_version="another-rules-version"),
        lambda documents: documents[0].update(phase_definition_version="unknown"),
        lambda documents: documents[0].update(gameweek=2),
        lambda documents: documents[0]["events"][0].update(credit_status="provisional"),
        lambda documents: documents[0]["events"][0].update(phase="unlabelled"),
        lambda documents: documents[0]["events"][0].update(assist=18),
        lambda documents: documents[0]["events"][0].update(scorer=999),
        lambda documents: documents[0]["events"].append(deepcopy(documents[0]["events"][0])),
        lambda documents: documents[1].update(final=False),
        lambda documents: documents[1]["players"][0].update(goals=1),
        lambda documents: documents[1]["players"].pop(),
        lambda documents: documents[1]["players"][2].update(minutes=0.0),
        lambda documents: documents[2]["players"][0].update(position="ST"),
        lambda documents: documents[2]["players"][0].update(goal_weight90=True),
        lambda documents: documents[2]["players"].append(deepcopy(documents[2]["players"][0])),
    ],
)
def test_invalid_or_unsettled_raw_observations_do_not_become_training_rows(damage):
    documents = deepcopy(observation_documents())
    damage(documents)
    with pytest.raises(ValueError):
        read_observation(documents)


@pytest.mark.parametrize(
    "document_index,source_argument",
    [(0, "outcome_source"), (1, "totals_source"), (2, "baseline_source")],
)
def test_every_observation_payload_has_its_own_exact_sha256(document_index, source_argument):
    documents = observation_documents()
    payload = raw_bytes(documents[document_index])
    kind = ("phase-events", "fpl-totals", "baseline")[document_index]
    when = documents[document_index].get(
        "outcome_available_at", documents[document_index]["decision_at"]
    )
    bad_source = replace(source(payload, kind=kind, when=when), raw_sha256="0" * 64)
    with pytest.raises(ValueError, match=r"SHA|sha|checksum|bytes"):
        read_observation(documents, **{source_argument: bad_source})


@pytest.mark.parametrize(
    "season,gameweek,match", [("2025-26", 1, "protect"), (SEASON, 6, "target")]
)
def test_protected_or_target_metadata_refuses_before_decoding_outcomes(season, gameweek, match):
    payload = b"this must never be decoded"
    with pytest.raises(ValueError, match=match):
        read_phase_observation(
            payload,
            payload,
            payload,
            duties=duty_capture(),
            outcome_source=source(payload, kind="phase-events", when=DECISION),
            totals_source=source(payload, kind="fpl-totals", when=DECISION),
            baseline_source=source(payload, kind="baseline", when=DECISION),
            season=season,
            gameweek=gameweek,
            training_cutoff=DECISION,
            allowed_seasons=("2024-25", SEASON),
            excluded_target=(SEASON, 6),
        )


def test_causal_baseline_after_the_actual_decision_is_refused_even_before_kickoff():
    documents = observation_documents()
    baseline = raw_bytes(documents[2])
    late = source(baseline, kind="baseline", when="2024-08-01T13:00:00Z")
    with pytest.raises(ValueError, match=r"cutoff|unavailable"):
        read_observation(documents, baseline_source=late)


@pytest.mark.parametrize(
    "payload", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff", b"[]"]
)
def test_private_projection_json_refuses_duplicate_keys_and_nonfinite_values(payload):
    with pytest.raises(ValueError):
        read_phase_projection(
            payload,
            duties=duty_capture(),
            source=source(payload, kind="projection", when=DECISION),
            model_cutoff=DECISION,
        )


@pytest.mark.parametrize(
    "damage",
    [
        lambda doc: doc["states"][0].update(weight=0.9),
        lambda doc: doc["states"].append(deepcopy(doc["states"][0])),
        lambda doc: doc["states"][0].update(goal_mass=4.0),
        lambda doc: doc["states"][0].update(physical_goal_mass=-1.0),
        lambda doc: doc["states"][0]["players"].pop(),
        lambda doc: doc["states"][0]["players"][0].update(minutes=121),
        lambda doc: doc["states"][0]["players"][0].update(minutes=True),
        lambda doc: doc["states"][0]["players"][0].update(assist_weight90=-1),
        lambda doc: doc.update(home=1),
        lambda doc: doc.update(opponent=6),
    ],
)
def test_raw_projection_requires_complete_scoped_bounded_state_support(damage):
    components, _, _ = native_case()
    document = projection_document(components)
    damage(document)
    with pytest.raises(ValueError):
        read_projection(document)


def test_future_duty_capture_cannot_fill_an_earlier_decision():
    components, _, _ = native_case()
    projection = read_projection(projection_document(components))
    late = replace(projection.duties, captured_at="2026-09-22T13:00:00Z")
    with pytest.raises(ValueError, match=r"future|stale"):
        validate_projection(replace(projection, duties=late), model_cutoff=DECISION)


def test_projected_state_receipts_and_members_are_immutable():
    components, _, _ = native_case()
    projection = read_projection(projection_document(components))
    with pytest.raises(FrozenInstanceError):
        projection.states[0].weight = 0.0
    with pytest.raises(FrozenInstanceError):
        projection.states[0].players[0].minutes = 0.0


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": ""},
        {"provider": ""},
        {"version": ""},
        {"raw_sha256": "0" * 63},
        {"raw_sha256": "F" * 64},
        {"raw_sha256": "0" * 64},
        {"source_kind": "phase-events"},
        {"published_at": "2026-09-22T13:00:00Z"},
        {"captured_at": "2026-09-22T13:00:00Z"},
        {"captured_at": "2026-09-22T12:00:00"},
        {"model_use_approved": False},
        {"model_use_approved": 1},
        {"model_use_evidence_ref": ""},
    ],
)
def test_projection_receipt_requires_semantics_bytes_time_and_admitted_use(changes):
    components, _, _ = native_case()
    document = projection_document(components)
    receipt = source(raw_bytes(document), kind="projection", when=DECISION)
    with pytest.raises(ValueError):
        read_projection(document, source=replace(receipt, **changes))


@pytest.mark.parametrize("receipt", [None, "receipt", {"published_at": DECISION}])
def test_projection_without_a_typed_source_receipt_is_refused_as_a_receipt(receipt):
    components, _, _ = native_case()
    with pytest.raises(ValueError, match="source receipt is required"):
        read_projection(projection_document(components), source=receipt)


def test_future_window_source_is_allowed_only_before_its_recorded_decision():
    components, _, _ = native_case()
    document = projection_document(components)
    document["gameweek"] = 7
    document["decision_at"] = "2026-09-29T12:00:00Z"
    document["kickoff"] = "2026-09-30T15:00:00Z"
    projection = read_projection(document)
    assert projection.source.captured_at == "2026-09-29T12:00:00Z"
    assert projection.gameweek == 7
    assert projection.decision_at == "2026-09-29T12:00:00Z"


def test_own_goal_is_a_physical_event_without_a_credited_attacking_scorer():
    documents = deepcopy(observation_documents())
    documents[0]["events"][-1].update(scorer=None, own_goal=True)
    next(player for player in documents[1]["players"] if player["player_code"] == 54)["goals"] = 0
    observation = read_observation(documents)
    assert len(observation.events) == 5
    assert sum(total.goals for total in observation.totals) == 4
    assert observation.events[-1].own_goal is True
    assert observation.events[-1].scorer is None


@pytest.mark.parametrize(
    "source_argument,document_index", [("outcome_source", 0), ("totals_source", 1)]
)
@pytest.mark.parametrize("timestamp", ["published_at", "captured_at"])
def test_settled_sources_at_training_cutoff_refuse_before_any_source_decoding(
    monkeypatch, source_argument, document_index, timestamp
):
    def decoded(*_args, **_kwargs):
        raise AssertionError("A cutoff-equality source must not be decoded.")

    documents = observation_documents()
    document = documents[document_index]
    kind = "phase-events" if document_index == 0 else "fpl-totals"
    receipt = source(raw_bytes(document), kind=kind, when=document["outcome_available_at"])
    monkeypatch.setattr("squadopt.features.football_phase_inputs._source_json", decoded)
    with pytest.raises(ValueError, match=r"cutoff|strict|predate"):
        read_observation(documents, **{source_argument: replace(receipt, **{timestamp: DECISION})})
