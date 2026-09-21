"""The appearance chance crossing the handoff, and what it must not disturb on the way.

The handoff is the one document between the producer and the live decision, and this is
the first optional thing it has ever carried. What these hold: the chance survives a
round trip, a handoff that states none is byte-identical to the one written before this
key existed, a file written before it still verifies, and the identity separates two
projections that agree on every point and disagree on who is likely to be there.
"""

import json
from pathlib import Path

import pytest

from squadopt.data.errors import DataSourceError
from squadopt.live import CONTROL_MODEL_NAME, read_projection_handoff, write_projection_handoff
from squadopt.live.recommendation import InSeasonProjection

SEASON = "2026-27"
SNAPSHOT = "fpl-live-20260919T230412Z-58378075a133"
POINTS = {101: 5.5, 102: 3.25, 103: 0.75}


def _projection(**overrides: object) -> InSeasonProjection:
    arguments: dict[str, object] = {
        "season": SEASON,
        "gameweek": 6,
        "source_snapshot_id": SNAPSHOT,
        "model_name": CONTROL_MODEL_NAME,
        "model_version": "synthetic-in-season-v0",
        "feature_contract_version": "synthetic-in-season-features-v0",
        "expected_points": dict(POINTS),
    }
    arguments.update(overrides)
    return InSeasonProjection(**arguments)  # type: ignore[arg-type]


def _round_trip(tmp_path: Path, projection: InSeasonProjection) -> InSeasonProjection:
    return read_projection_handoff(write_projection_handoff(tmp_path / "handoff.json", projection))


# --- the round trip ---------------------------------------------------------


def test_a_stated_chance_survives_the_handoff(tmp_path: Path) -> None:
    chances = {101: 0.94, 102: 0.31}
    read = _round_trip(tmp_path, _projection(appearance_probability=chances))

    assert read.appearance_probability == chances
    assert read.fingerprint == _projection(appearance_probability=chances).fingerprint


def test_a_player_the_producer_did_not_model_is_absent_rather_than_zero(tmp_path: Path) -> None:
    """The direct-control route leaves its component inputs missing by contract.

    A zero there would say the player certainly will not appear, which is a claim about
    the player rather than about the model, and it is the claim that would bench them.
    """

    read = _round_trip(tmp_path, _projection(appearance_probability={101: 0.94}))

    assert read.appearance_probability is not None
    assert 103 in read.expected_points
    assert 103 not in read.appearance_probability


def test_a_producer_that_states_none_reads_as_none_rather_than_empty(tmp_path: Path) -> None:
    """``None`` and ``{}`` are different: no opinion, against an opinion about nobody."""

    read = _round_trip(tmp_path, _projection())

    assert read.appearance_probability is None


# --- what it must not disturb -----------------------------------------------


def test_a_handoff_without_one_is_written_exactly_as_it_is_written_today(
    tmp_path: Path,
) -> None:
    """The key is added only when there is something to say, so nothing else moves."""

    written = write_projection_handoff(tmp_path / "handoff.json", _projection())
    document = json.loads(written.read_text(encoding="utf-8"))

    assert "appearance_probability" not in document


def test_a_file_written_before_this_key_existed_still_verifies(tmp_path: Path) -> None:
    """The fingerprint is checked on read, so a silent change here would void the archive."""

    path = write_projection_handoff(tmp_path / "handoff.json", _projection())
    document = json.loads(path.read_text(encoding="utf-8"))
    assert "appearance_probability" not in document

    read = read_projection_handoff(path)

    assert read.appearance_probability is None
    assert read.fingerprint == document["fingerprint"]


def test_two_projections_agreeing_on_every_point_are_told_apart_by_the_chances() -> None:
    """They order a bench differently, so the identity has to separate them."""

    confident = _projection(appearance_probability={101: 0.95, 102: 0.90})
    doubtful = _projection(appearance_probability={101: 0.95, 102: 0.10})

    assert confident.expected_points == doubtful.expected_points
    assert confident.fingerprint != doubtful.fingerprint
    assert _projection().fingerprint not in {confident.fingerprint, doubtful.fingerprint}


# --- what is refused --------------------------------------------------------


@pytest.mark.parametrize("chance", [-0.01, 1.01, float("nan"), float("inf")])
def test_a_chance_outside_the_unit_interval_is_refused_rather_than_clipped(
    chance: float,
) -> None:
    """The bench rule divides by this number.

    Above one it quietly reorders a bench, below zero it flips the order, and neither is
    something a clip repairs into a fact about a footballer.
    """

    with pytest.raises(DataSourceError, match="lies in \\[0, 1\\]"):
        _projection(appearance_probability={101: chance})


def test_a_chance_for_a_player_the_handoff_gives_no_points_for_is_refused() -> None:
    """One projection, two readings of it; a player in one and not the other is a bug."""

    with pytest.raises(DataSourceError, match="gives no expected points"):
        _projection(appearance_probability={999: 0.5})


def test_a_malformed_appearance_block_is_a_broken_document_not_an_absence(
    tmp_path: Path,
) -> None:
    path = write_projection_handoff(tmp_path / "handoff.json", _projection())
    document = json.loads(path.read_text(encoding="utf-8"))
    document["appearance_probability"] = [0.5]
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DataSourceError, match="must map player codes to chances"):
        read_projection_handoff(path)
