"""The saf-puan three- and five-week windows: a plan under stated limits, never a
forecast, published beside the one-week baseline without moving its bytes.

The shared member world (``test_live_transfers``) publishes three gameweeks and no
fixtures, so it cannot carry a window; these tests build a capture whose calendar reaches
gameweek six, the way the horizon planning tests do, and hold the GW1 replay squad in it.
"""

import datetime
import json
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_league_views import _Provider
from tests.unit.test_live_horizon_planning import _inputs as _horizon_inputs
from tests.unit.test_live_recommendation import (
    GW1_REPLAY_CAPTAIN,
    GW1_REPLAY_SQUAD,
    GW1_REPLAY_STARTING_XI,
    GW1_REPLAY_TOTAL_COST_TENTHS,
    SEASON,
)
from tests.unit.test_projection_horizon_builder import _in_season_handoff
from tests.unit.test_public_probability_guards import _FORBIDDEN_TEXT

from squadopt.application.advice import (
    MEMBER_WINDOWS,
    WINDOW_STATED_LIMITS,
    AdviseEntryRequest,
    advise_entry,
    member_horizon_builder,
)
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN
from squadopt.data.snapshots import read_snapshot
from squadopt.live.recommendation import project
from squadopt.planning import CHIP_NAMES

ENTRY = 101
LEAGUE = 352490


@pytest.fixture(name="window_world")
def _window_world(tmp_path: Path) -> dict[str, Any]:
    """A GW2 capture whose calendar reaches GW6, the member holding the replay squad."""

    inputs, _horizon, _held, rules = _horizon_inputs(tmp_path, tuple(range(2, 7)))
    snapshot = read_snapshot(tmp_path, str(inputs.snapshot_id))
    handoff = _in_season_handoff(snapshot)
    picks = EntryPicks(
        entry_id=ENTRY,
        season=SEASON,
        gameweek=1,
        squad=GW1_REPLAY_SQUAD,
        starting_xi=GW1_REPLAY_STARTING_XI,
        captain=GW1_REPLAY_CAPTAIN,
        vice_captain=1004,
        bank_tenths=1_000 - GW1_REPLAY_TOTAL_COST_TENTHS,
        free_transfers=1,
        free_transfers_known=False,
        source_snapshot_id=str(inputs.snapshot_id),
    )
    return {
        "inputs": inputs,
        "projection": project(inputs, in_season=handoff),
        "rules": rules,
        "provider": _Provider({ENTRY: picks}),
        "builder": member_horizon_builder(snapshot, season=SEASON, in_season=handoff),
    }


def _advise(world: dict[str, Any], *, with_builder: bool = True, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "season": SEASON,
        "gameweek": 2,
        "league_id": LEAGUE,
        "entry_id": ENTRY,
    }
    fields.update(overrides)
    return advise_entry(
        AdviseEntryRequest(**fields),
        provider=world["provider"],
        inputs=world["inputs"],
        projection=world["projection"],
        rules=world["rules"],
        horizon_builder=world["builder"] if with_builder else None,
    )


def _walk(node: object, path: str, offenders: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if FORBIDDEN_FIELD_PATTERN.search(str(key)):
                offenders.append(f"{path}.{key}")
            _walk(value, f"{path}.{key}", offenders)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", offenders)
    elif isinstance(node, str) and (_FORBIDDEN_TEXT.search(node) or "%" in node):
        offenders.append(f"{path} (text: {node[:60]!r})")


@pytest.mark.parametrize("window", [3, 5])
def test_a_window_publishes_the_first_week_and_the_whole_plan(
    window_world: dict[str, Any], window: int
) -> None:
    """The one-week shape for the first week — moves, armband, eleven, bench, chip — plus
    one row per gameweek and the sentences naming what the window assumes."""

    payload = _advise(window_world, window=window)

    assert payload["mode"] == "saf-puan" and payload["window"] == window
    assert payload["gameweek"] == 2
    assert payload["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert payload["expected_points_cost"] == 0.0 and payload["rival_label"] is None
    assert payload["stated_limits"] == list(WINDOW_STATED_LIMITS)
    # The first week's decision is complete, as the one-week payload's is.
    eleven, bench, captain = payload["starting_xi"], payload["bench"], payload["captain"]
    assert isinstance(eleven, list) and len(eleven) == 11
    assert isinstance(bench, list) and len(bench) == 4 and bench[0]["position"] == "GK"
    assert isinstance(captain, dict) and captain["player_id"] in {p["player_id"] for p in eleven}
    assert payload["chip"] is None or payload["chip"] in CHIP_NAMES
    # One row per gameweek of the window, consecutive from the deadline.
    weeks = payload["plan_weeks"]
    assert isinstance(weeks, list) and [w["gameweek"] for w in weeks] == list(range(2, 2 + window))
    for week in weeks:
        assert isinstance(week["expected_points"], float)
        assert isinstance(week["transfer_hit_points"], float)
        assert isinstance(week["free_transfers_before"], int)
        assert isinstance(week["free_transfers_after"], int)
        assert week["chip"] is None or week["chip"] in CHIP_NAMES
        # The per-week cap the window plans under: at most one transfer, a wildcard
        # week excepted.
        assert len(week["transfers_in"]) == len(week["transfers_out"])
        assert week["chip"] == "wildcard" or len(week["transfers_in"]) <= 1
    played = [week["chip"] for week in weeks if week["chip"] is not None]
    assert len(played) == len(set(played)), "a chip is played at most once in the window"
    # ``moves`` is the first week's transfers, in the one-week shape the page renders.
    first = weeks[0]
    assert [move["player_in"]["player_id"] for move in payload["moves"]] == [
        player["player_id"] for player in first["transfers_in"]
    ]
    assert [move["player_out"]["player_id"] for move in payload["moves"]] == [
        player["player_id"] for player in first["transfers_out"]
    ]
    assert first["chip"] == payload["chip"]
    for move in payload["moves"]:
        assert move["expected_points_cost"] == first["transfer_hit_points"]
        assert move["reason_code"] == "window_value"
    offenders: list[str] = []
    _walk(payload, "payload", offenders)
    assert offenders == []


def test_the_first_week_of_a_window_reads_the_one_week_numbers(
    window_world: dict[str, Any],
) -> None:
    """The horizon's opening week is the same projection the one-week advice reads, so
    the eleven's expected points are the projection's, and the first row's expected
    points are that eleven with the captain doubled."""

    projection = window_world["projection"]
    expected = {
        int(str(row["player_id"])): float(str(row["expected_points"]))
        for _, row in projection.table.iterrows()
    }
    payload = _advise(window_world, window=3)
    for player in [*payload["starting_xi"], *payload["bench"]]:
        assert player["expected_points"] == pytest.approx(expected[player["player_id"]])
    assert payload["expected_own_points"] == pytest.approx(
        sum(p["expected_points"] for p in payload["starting_xi"])
        + payload["captain"]["expected_points"]
    )
    assert payload["plan_weeks"][0]["expected_points"] == pytest.approx(
        payload["expected_own_points"]
    )


def test_windows_are_saf_puan_only_and_need_the_horizon_builder(
    window_world: dict[str, Any],
) -> None:
    """A rival strategy stays at one week; a window nobody computes is refused; a
    window without the capture's horizon builder is refused, never answered from the
    one-week plan."""

    assert MEMBER_WINDOWS == (1, 3, 5)
    with pytest.raises(EntryError, match="window 1 only"):
        _advise(window_world, strategy="fark-yarat", rival_entry_id=202, window=3)
    with pytest.raises(EntryError, match="not computed"):
        _advise(window_world, window=2)
    with pytest.raises(EntryError, match="horizon builder"):
        _advise(window_world, window=3, with_builder=False)


def test_the_batch_publishes_the_windows_without_moving_the_baseline_bytes(
    window_world: dict[str, Any], tmp_path: Path
) -> None:
    """With a horizon builder the tree gains ``saf-puan/3.json`` and ``5.json`` and an
    index listing them; the one-week file is byte-identical with and without it."""

    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    registrations = (EntryRegistration(ENTRY, "member-a", "2026-08-23T00:00:00Z"),)
    reports = {}
    for name, builder in (("plain", None), ("windows", window_world["builder"])):
        reports[name] = build_league_views(
            window_world["provider"],
            registrations,
            window_world["inputs"],
            window_world["projection"],
            window_world["rules"],
            league_id=LEAGUE,
            league_name="Test League",
            out_dir=tmp_path / name,
            now=when,
            rival_menu=False,
            horizon_builder=builder,
        )
    baseline = f"advice/{ENTRY}/saf-puan/1.json"
    assert (tmp_path / "plain" / baseline).read_bytes() == (
        tmp_path / "windows" / baseline
    ).read_bytes()
    assert set(reports["plain"].files) == {"members.json", f"entries/{ENTRY}.json", baseline}
    assert set(reports["windows"].files) == {
        "members.json",
        f"entries/{ENTRY}.json",
        baseline,
        f"advice/{ENTRY}/saf-puan/3.json",
        f"advice/{ENTRY}/saf-puan/5.json",
        f"advice/{ENTRY}/index.json",
    }
    for window in (3, 5):
        document = json.loads(
            (
                tmp_path / "windows" / "advice" / str(ENTRY) / "saf-puan" / f"{window}.json"
            ).read_text(encoding="utf-8")
        )
        assert document["contract_version"] == "provisional_league_ui_v1"
        assert document["payload"]["window"] == window
        assert len(document["payload"]["plan_weeks"]) == window
    index = json.loads(
        (tmp_path / "windows" / "advice" / str(ENTRY) / "index.json").read_text(encoding="utf-8")
    )["payload"]
    assert index["window"] == 1
    assert index["windows"] == {"saf-puan": [1, 3, 5]}
    assert index["strategies"] == ["saf-puan"]
    assert index["unavailable"] == []
