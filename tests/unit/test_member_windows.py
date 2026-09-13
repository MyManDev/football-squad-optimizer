"""The saf-puan three- and five-week windows: a plan under stated limits, never a
forecast, published beside the one-week baseline without moving its bytes.

The shared member world (``test_live_transfers``) publishes three gameweeks and no
fixtures, so it cannot carry a window; these tests build a capture whose calendar reaches
gameweek six, the way the horizon planning tests do, and hold the GW1 replay squad in it.
"""

import dataclasses
import datetime
import json
import re
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

from squadopt.application import advice as advice_module
from squadopt.application.advice import (
    MEMBER_WINDOWS,
    WINDOW_STATED_LIMITS,
    WINDOW_TOP100_LIMIT,
    AdviseEntryRequest,
    advise_entry,
    member_horizon_builder,
    window_stated_limits,
)
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN
from squadopt.data.snapshots import read_snapshot
from squadopt.live.recommendation import project
from squadopt.live.transfers import MEMBER_PLANNING_POLICY
from squadopt.optimization import SolverExecutionError, SolverStatus
from squadopt.planning import CHIP_NAMES

ENTRY = 101
LEAGUE = 352490

#: The site keys its Turkish copy by these exact sentences, so the producer's constant and
#: the web's copy of it are two ends of one contract with a silent failure mode: an unknown
#: sentence falls through in English onto a Turkish page and every test stays green.
WEB_FIXTURE = Path(__file__).resolve().parents[2] / "web" / "src" / "fixtures" / "league.ts"


def _web_stated_limits() -> list[str]:
    """The sentences the site holds, read out of its fixture rather than restated here."""

    text = WEB_FIXTURE.read_text(encoding="utf-8")
    block = re.search(
        r"export const WINDOW_STATED_LIMITS: readonly string\[\] = \[(.*?)^\];",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert block is not None, f"{WEB_FIXTURE} no longer declares WINDOW_STATED_LIMITS"
    return [json.loads(literal) for literal in re.findall(r'"(?:[^"\\]|\\.)*"', block.group(1))]


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
        # The member bought this squad at the capture's own prices, so nothing is in
        # profit and the sell-on fee withholds nothing: the selling value is what the
        # fifteen cost. The fee is pinned in test_member_spending_power.py.
        squad_sell_value_tenths=GW1_REPLAY_TOTAL_COST_TENTHS,
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
    # This fixture's handoff carries no elite evidence, so the Top-100 sentence is not
    # among the limits: a mechanism that was not applied is not claimed.
    assert payload["stated_limits"] == window_stated_limits(window_world["projection"])
    assert WINDOW_TOP100_LIMIT in WINDOW_STATED_LIMITS
    assert WINDOW_TOP100_LIMIT not in payload["stated_limits"]
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
        # A published hit is the game's charge times the paid transfers, never the
        # caution margin the window was planned under.
        paid = (
            0
            if week["chip"] in {"wildcard", "freehit"}
            else max(0, len(week["transfers_in"]) - week["free_transfers_before"])
        )
        assert week["transfer_hit_points"] == paid * float(
            str(MEMBER_PLANNING_POLICY["hit_points_charged"])
        )
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
    # The week's charge is on the payload once, not copied onto each move row.
    assert payload["transfer_hit_points"] == first["transfer_hit_points"]
    for move in payload["moves"]:
        assert "expected_points_cost" not in move
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
    with pytest.raises(EntryError, match=r"supports windows \(1,\) only"):
        _advise(window_world, strategy="fark-yarat", rival_entry_id=202, window=3)
    with pytest.raises(EntryError, match=r"supports windows \(1, 3, 5\) only"):
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


def test_two_builds_of_one_capture_publish_the_same_window_bytes(
    window_world: dict[str, Any], tmp_path: Path
) -> None:
    """The published requirement: the same capture, handoff and registry, built twice,
    are the same files with the same bytes.

    A window is published as the best plan the search found rather than a proven one,
    which is honest only while "the best found" is the same on both builds. Otherwise a
    member is shown whichever answer their build happened to reach, and the immutable
    advice record describes an answer rather than the answer.
    """

    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    registrations = (EntryRegistration(ENTRY, "member-a", "2026-08-23T00:00:00Z"),)
    published = []
    for name in ("first", "second"):
        report = build_league_views(
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
            horizon_builder=window_world["builder"],
        )
        published.append(sorted(report.files))

    assert published[0] == published[1]
    assert f"advice/{ENTRY}/saf-puan/5.json" in published[0]
    for relative in published[0]:
        assert (tmp_path / "first" / relative).read_bytes() == (
            tmp_path / "second" / relative
        ).read_bytes(), relative


def test_a_window_the_clock_cut_short_is_refused_rather_than_published(
    window_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A search the wall-clock safety cap stopped is not published.

    The deterministic budget stops a truncated search at a point that is a function of
    the inputs; the wall clock stops it at a point that is a function of the machine. On
    the GW4 capture the fifteen members' five-week windows spend their whole hundred
    deterministic units in 191.7s to 295.8s of wall clock across the site builder's own
    fifteen-worker pool, so the ceiling that used to sit at 300.0s bound under any load
    beyond that measurement and two builds published two different plans. The ceiling is
    now far above that work, and a plan it did cut short is refused here: the planner
    already refuses a clock-cut search that reached no plan at all, and this closes the
    other half, where the clock cut a search that had one.
    """

    solved = advice_module.plan_transfer_horizon

    def clock_stopped(*args: Any, **kwargs: Any) -> Any:
        plan, config = solved(*args, **kwargs)
        cut = dataclasses.replace(
            plan,
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={
                **dict(plan.diagnostics),
                "deterministic_time_used": 21.5,
                "solver_deterministic_time_limit": 60.0,
                "deterministic_time_budget_exhausted": False,
            },
        )
        return cut, config

    monkeypatch.setattr(advice_module, "plan_transfer_horizon", clock_stopped)

    with pytest.raises(SolverExecutionError, match="wall-clock safety cap"):
        _advise(window_world, window=3)


def test_the_top100_sentence_is_published_only_when_the_projection_carries_it(
    window_world: dict[str, Any],
) -> None:
    """A window states the uplift as a fact, so it may only say so when it is one.

    The uplift is optional: ``build_projection_handoff`` applies it only when given the
    evidence table, ``run_week --skip-top100`` and ``--projection component-only`` leave
    it out, and both un-uplifted model versions are promoted, so a window is published
    from a projection that carries none. The projection says which it is — an elite
    handoff carries the evidence fingerprint it was built from, and the un-uplifted
    versions are forbidden from carrying one — so the sentence is derived from the
    projection rather than assumed.
    """

    projection = window_world["projection"]
    assert projection.diagnostics.get("projection_evidence_fingerprint") is None
    assert WINDOW_TOP100_LIMIT not in window_stated_limits(projection)

    uplifted = dataclasses.replace(
        projection,
        diagnostics={**dict(projection.diagnostics), "projection_evidence_fingerprint": "ab" * 32},
    )
    assert window_stated_limits(uplifted) == list(WINDOW_STATED_LIMITS)
    # Nothing else moves: the same sentences, in the same order, either way.
    assert window_stated_limits(projection) == [
        sentence for sentence in WINDOW_STATED_LIMITS if sentence != WINDOW_TOP100_LIMIT
    ]


def test_the_site_holds_the_producers_window_limit_sentences_verbatim() -> None:
    """The sentences the page is keyed by are the sentences the payload carries.

    ``WINDOW_STATED_LIMITS`` is published into every window document; the site translates
    each one by exact string lookup and falls through to the producer's English when it
    does not know it. Nothing compared the two constants, so rewording one here shipped an
    English sentence onto the Turkish page with pytest and vitest both green. This asserts
    the equality rather than the wording, so it survives any rewrite of the sentences and
    fails only when the two sides disagree.
    """

    assert _web_stated_limits() == list(WINDOW_STATED_LIMITS)
