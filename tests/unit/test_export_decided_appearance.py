"""The double-reduction input is the week's own appearance probabilities, or nothing.

What these hold: the handoff read is the one the ledger decided from, not any handoff kept
for the capture; a handoff that states its probabilities is read as it stands; one that does
not is rebuilt and kept only when the rebuild reproduces its component fingerprint and every
expected point; a player the component route did not model gets no row rather than a zero.
"""

import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
import pytest
from scripts.export_decided_appearance import (
    REBUILT,
    STATED,
    DecidedAppearanceError,
    SettledWeek,
    collect,
    decided_handoff,
    fitted_appearance,
    settled_weeks,
)

from squadopt.live.recommendation import InSeasonProjection, write_projection_handoff

SEASON = "2026-27"
CAPTURE = "fpl-live-20260918T122516Z-cd5c04029774"
COMPONENTS = "c" * 64


def _handoff(
    points: Mapping[int, float],
    *,
    appearance: Mapping[int, float] | None = None,
    component_fingerprint: str | None = COMPONENTS,
    model_version: str = "test-model-v1",
) -> InSeasonProjection:
    diagnostics = (
        {} if component_fingerprint is None else {"component_fingerprint": component_fingerprint}
    )
    return InSeasonProjection(
        season=SEASON,
        gameweek=5,
        source_snapshot_id=CAPTURE,
        model_name="test",
        model_version=model_version,
        feature_contract_version="test-features",
        expected_points=dict(points),
        appearance_probability=None if appearance is None else dict(appearance),
        diagnostics=diagnostics,
    )


def _components(
    rows: Mapping[int, tuple[float, float | None]], fingerprint: str = COMPONENTS
) -> tuple[pd.DataFrame, dict[str, object]]:
    table = pd.DataFrame(
        {
            "player_id": pd.Series(list(rows), dtype="int64"),
            "expected_points": [points for points, _ in rows.values()],
            "appearance_probability": pd.array(
                [chance for _, chance in rows.values()], dtype="Float64"
            ),
        }
    )
    return table, {"component_fingerprint": fingerprint}


def _never(_: InSeasonProjection) -> tuple[pd.DataFrame, dict[str, object]]:
    raise AssertionError("a handoff that states its probabilities must not be rebuilt")


def _data_root(tmp_path: Path, decided: InSeasonProjection, *others: InSeasonProjection) -> Path:
    root = tmp_path / "data"
    kept = root / "handoffs" / "by-capture" / CAPTURE
    for index, handoff in enumerate((*others, decided)):
        write_projection_handoff(kept / f"{index:02d}.json", handoff)
    ledger = root / "ledger" / SEASON / "gw05"
    ledger.mkdir(parents=True)
    (ledger / "decision.json").write_text(
        json.dumps({"metadata": {"projection_handoff_fingerprint": decided.fingerprint}}),
        encoding="utf-8",
    )
    return root


WEEK = SettledWeek(season=SEASON, gameweek=5, decision_capture=CAPTURE)


# --- which handoff ------------------------------------------------------------


def test_the_handoff_read_is_the_one_the_ledger_decided_from(tmp_path: Path) -> None:
    decided = _handoff({1: 2.0, 2: 1.0})
    replay = _handoff({1: 2.5, 2: 1.0})
    root = _data_root(tmp_path, decided, replay)

    assert decided_handoff(root, WEEK).fingerprint == decided.fingerprint


def test_a_ledger_naming_no_kept_handoff_is_refused(tmp_path: Path) -> None:
    root = _data_root(tmp_path, _handoff({1: 2.0}))
    (root / "ledger" / SEASON / "gw05" / "decision.json").write_text(
        json.dumps({"metadata": {"projection_handoff_fingerprint": "f" * 64}}), encoding="utf-8"
    )

    with pytest.raises(DecidedAppearanceError, match="none of the 1 handoff"):
        decided_handoff(root, WEEK)


def test_two_tables_for_one_week_must_name_one_decision_capture(tmp_path: Path) -> None:
    for tail, capture in (("aaa", CAPTURE), ("bbb", "fpl-live-20260918T100000Z-000000000000")):
        (tmp_path / f"settled_outcomes_v1_{SEASON}_gw05_{tail}.manifest.json").write_text(
            json.dumps({"season": SEASON, "gameweek": 5, "pre_deadline_snapshot_id": capture}),
            encoding="utf-8",
        )

    with pytest.raises(DecidedAppearanceError, match="different decision captures"):
        settled_weeks(tmp_path)


# --- which numbers ------------------------------------------------------------


def test_a_handoff_that_states_its_probabilities_is_read_as_it_stands() -> None:
    handoff = _handoff({1: 2.0, 2: 1.0}, appearance={1: 0.9})

    chances, source = fitted_appearance(handoff, _never)

    assert (chances, source) == ({1: 0.9}, STATED)


def test_a_verified_rebuild_gives_a_row_only_where_the_component_route_modelled() -> None:
    handoff = _handoff({1: 2.0, 2: 1.0})

    chances, source = fitted_appearance(
        handoff, lambda _: _components({1: (2.0, 0.8), 2: (1.0, None)})
    )

    assert source == REBUILT
    assert chances == {1: 0.8}


def test_a_rebuild_with_another_component_fingerprint_is_refused() -> None:
    handoff = _handoff({1: 2.0})

    with pytest.raises(DecidedAppearanceError, match="no longer reproduces"):
        fitted_appearance(handoff, lambda _: _components({1: (2.0, 0.8)}, fingerprint="d" * 64))


def test_a_rebuild_whose_points_moved_is_refused() -> None:
    handoff = _handoff({1: 2.0})

    with pytest.raises(DecidedAppearanceError, match="differ from the handoff"):
        fitted_appearance(handoff, lambda _: _components({1: (2.1, 0.8)}))


def test_a_handoff_with_nothing_to_verify_against_is_refused() -> None:
    handoff = _handoff({1: 2.0}, component_fingerprint=None)

    with pytest.raises(DecidedAppearanceError, match="no component fingerprint"):
        fitted_appearance(handoff, _never)


def test_the_rows_name_their_week_and_the_manifest_names_the_handoff(tmp_path: Path) -> None:
    decided = _handoff({1: 2.0, 2: 1.0}, appearance={2: 0.4, 1: 0.7})
    root = _data_root(tmp_path, decided)

    table, described = collect(root, [WEEK], _never)

    assert list(table.columns) == [
        "season",
        "gameweek",
        "player_id",
        "fitted_appearance_probability",
    ]
    assert table["player_id"].tolist() == [1, 2]
    assert set(table["gameweek"]) == {5}
    assert described[0]["handoff_fingerprint"] == decided.fingerprint
    assert described[0]["source"] == STATED
    assert described[0]["rows"] == 2
