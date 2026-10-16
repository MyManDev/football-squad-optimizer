"""Original public CSV duties retain separate public and acquisition evidence."""

import hashlib
from dataclasses import replace

import pytest

from squadopt.features.football_phase_inputs import PhaseReplay
from squadopt.features.football_phase_replay import (
    MAX_REPLAY_CSV_BYTES,
    read_replayed_phase_duties,
)

PLAYERS = (
    b"id,code,team,team_code,penalties_order,direct_freekicks_order,"
    b"corners_and_indirect_freekicks_order,ignored\n"
    b"1,1001,1,3,1.0,None,,unused\n"
    b"2,1002,1,3,2,1,3,unused\n"
    b"3,1003,2,7,None,1.0,3,unused\n"
)
TEAMS = b"id,code,name\n1,3,One\n2,7,Two\n"
DECISION = "2025-11-01T10:00:00Z"


def _replay(players=PLAYERS, teams=TEAMS, **overrides):
    return PhaseReplay(
        **(
            {
                "revision": "a" * 40,
                "recorded_at": "2025-11-01T00:00:00Z",
                "retrieved_at": "2026-10-15T10:00:00Z",
                "source_hashes": (
                    ("players_raw.csv", hashlib.sha256(players).hexdigest()),
                    ("teams.csv", hashlib.sha256(teams).hexdigest()),
                ),
                "feature_cutoff": DECISION,
                "latest_history_kickoff": "2025-10-25T15:00:00Z",
                "generated_at": "2026-10-15T11:00:00Z",
            }
            | overrides
        )
    )


def _read(players=PLAYERS, teams=TEAMS, **overrides):
    arguments = {
        "season": "2025-26",
        "decision_at": DECISION,
        "valid_until": DECISION,
        "replay": _replay(players, teams),
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-only",
        "allow_released_2025_26": True,
    }
    return read_replayed_phase_duties(players, teams, **(arguments | overrides))


def test_protected_season_requires_opt_in_before_decoding_duties():
    with pytest.raises(ValueError, match="protected"):
        read_replayed_phase_duties(
            b"\xff",
            b"\xff",
            season="2025-26",
            decision_at=DECISION,
            valid_until=DECISION,
            replay=_replay(),
            model_use_approved=True,
            model_use_evidence_ref="synthetic-only",
        )
    with pytest.raises(ValueError, match="protected"):
        _read(allow_released_2025_26=False)


@pytest.mark.parametrize("selection", [None, 0, 1, "True"])
def test_released_season_selection_requires_a_strict_boolean(selection):
    with pytest.raises(ValueError, match="explicit Boolean"):
        _read(allow_released_2025_26=selection)


def test_other_season_does_not_require_release_opt_in():
    capture = _read(season="2024-25", allow_released_2025_26=False)
    assert capture.season == "2024-25"


def test_public_version_duties_preserve_actual_acquisition_and_nullable_ranks():
    replay = _replay()
    capture = _read(replay=replay)
    assert capture.snapshot_id == "git:" + replay.revision
    assert capture.captured_at == replay.retrieved_at
    assert capture.captured_at > DECISION
    assert capture.source_fingerprint == hashlib.sha256(PLAYERS).hexdigest()
    assert capture.valid_until == DECISION
    assert [(p.player_code, p.club) for p in capture.players] == [(1001, 3), (1002, 3), (1003, 7)]
    assert capture.players[0].penalties_order == 1
    assert capture.players[0].direct_freekicks_order is None
    assert capture.players[0].corners_and_indirect_freekicks_order is None
    assert capture.players[1].direct_freekicks_order == capture.players[2].direct_freekicks_order


@pytest.mark.parametrize("file", ["players", "teams"])
def test_modified_original_bytes_are_refused_before_decoding(file):
    with pytest.raises(ValueError, match="source hashes"):
        _read(
            PLAYERS + b"\xff" if file == "players" else PLAYERS,
            TEAMS + b"\xff" if file == "teams" else TEAMS,
            replay=_replay(),
        )


@pytest.mark.parametrize("file", ["players", "teams"])
def test_oversized_csv_is_refused_before_hashing_or_decoding(file):
    oversized = b"x" * (MAX_REPLAY_CSV_BYTES + 1)
    with pytest.raises(ValueError, match="20 MiB"):
        _read(
            oversized if file == "players" else PLAYERS,
            oversized if file == "teams" else TEAMS,
            replay=_replay(),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"recorded_at": "2025-11-01T10:00:01Z"},
        {"retrieved_at": DECISION},
        {"generated_at": "2026-10-15T09:59:59Z"},
        {"feature_cutoff": "2025-11-01T10:00:01Z"},
        {"feature_cutoff": "2025-10-31T23:59:59Z"},
        {"recorded_at": "2025-11-01T00:00:00"},
        {"revision": "a" * 39},
        {"version": "unknown"},
        {"source_hashes": (("players_raw.csv", "a" * 64),)},
        {"source_hashes": (("players_raw.csv", "a" * 64), ("players_raw.csv", "b" * 64))},
        {"source_hashes": (("players_raw.csv", "A" * 64), ("teams.csv", "b" * 64))},
    ],
)
def test_invalid_public_revision_and_clock_evidence_is_refused(changes):
    with pytest.raises(ValueError):
        _read(replay=replace(_replay(), **changes))


@pytest.mark.parametrize("rank", [b"0", b"-1", b"1.2", b"NaN", b"null", b"True", b"1e0"])
def test_invalid_rank_encodings_are_not_coerced_or_treated_as_missing(rank):
    with pytest.raises(ValueError, match="positive integral"):
        _read(PLAYERS.replace(b"1.0,None", rank + b",None", 1))


@pytest.mark.parametrize(
    "players,teams",
    [
        (PLAYERS.replace(b"2,1002", b"1,1002"), TEAMS),
        (PLAYERS.replace(b"2,1002", b"2,1001"), TEAMS),
        (PLAYERS.replace(b"3,1003,2,7", b"3,1003,9,7"), TEAMS),
        (PLAYERS.replace(b"3,1003,2,7", b"3,1003,2,3"), TEAMS),
        (PLAYERS.replace(b"3,1003,2,7", b"3,1003,2,None"), TEAMS),
        (PLAYERS, TEAMS.replace(b"2,7", b"1,7")),
        (PLAYERS, TEAMS.replace(b"2,7", b"2,3")),
        (PLAYERS, TEAMS.replace(b"2,7", b"2,0")),
    ],
)
def test_ambiguous_identities_and_club_mapping_disagreement_are_refused(players, teams):
    with pytest.raises(ValueError):
        _read(players, teams)


@pytest.mark.parametrize(
    "players",
    [
        PLAYERS.replace(b"penalties_order", b"absent"),
        PLAYERS.replace(b"ignored", b"code"),
        PLAYERS.replace(b",unused", b",unused,extra", 1),
        PLAYERS.replace(b",unused", b"", 1),
        PLAYERS + b"\xff",
        PLAYERS + b"\x00",
        PLAYERS.split(b"\n", 1)[0] + b"\n",
        b"",
    ],
)
def test_malformed_or_incomplete_csv_is_refused(players):
    with pytest.raises(ValueError):
        _read(players)


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_use_approved": False},
        {"model_use_approved": 1},
        {"model_use_evidence_ref": ""},
        {"valid_until": "2025-11-01T09:59:59Z"},
        {"season": "2025-27"},
    ],
)
def test_model_use_and_scope_are_explicit(overrides):
    with pytest.raises(ValueError):
        _read(**overrides)


@pytest.mark.parametrize("expiry", ["2026-10-15T10:00:00Z", "2027-07-01T00:00:00Z"])
def test_replayed_duty_expiry_must_precede_actual_retrieval(expiry):
    with pytest.raises(ValueError, match="clocks disagree"):
        _read(valid_until=expiry)


def test_bom_and_optional_team_code_are_supported_without_guessing_clubs():
    players = b"\xef\xbb\xbf" + PLAYERS.replace(b",team_code", b"")
    for code, team, club in ((1001, 1, 3), (1002, 1, 3), (1003, 2, 7)):
        players = players.replace(f",{code},{team},{club},".encode(), f",{code},{team},".encode())
    capture = _read(players)
    assert [player.club for player in capture.players] == [3, 3, 7]
