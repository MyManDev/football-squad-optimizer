"""The menu beyond the one-week pure-points plan: windows and rival strategies under the
Top 100 influence, and rival strategies over a window.

Every document states base-model numbers, is priced against the member's own pure-points
plan for the same window at setting 0, and is published at its own address against the
default rival only. The one-week baseline and everything already published keep their
bytes.
"""

import datetime
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_league_views import _Provider
from tests.unit.test_member_windows import ENTRY, LEAGUE, SEASON
from tests.unit.test_member_windows import _window_world as _base_world

import squadopt.application.advice as advice_module
import squadopt.application.advice_variants as variants
import squadopt.application.league_views as views
from squadopt.application.advice import (
    TOP100_LIMIT,
    WINDOW_LINEARIZATION_LEVEL,
    AdviseEntryRequest,
    advise_entry,
    solve_member_control,
    solve_pricing_control,
    solve_window_plan,
    window_horizon,
)
from squadopt.application.advice_variants import (
    RIVAL_WINDOW_LIMIT,
    TOP100_WINDOW_LIMIT,
    advise_rival_window,
    advise_rival_with_top100,
    advise_window_with_top100,
    weighted_horizon,
)
from squadopt.application.entries import EntryError, EntryRegistration, held_squad_from_picks
from squadopt.application.league_views import MemberStanding, build_league_views, variant_path
from squadopt.application.lineup_publication import best_eleven_basis
from squadopt.application.strategies.catalog import (
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
    PUBLISHABLE_FIELDS,
)
from squadopt.application.top100_weight import Top100Counts, base_points
from squadopt.platform.advice_documents import validate_advice_document

window_world = _base_world  # re-register the fixture in this module

RIVAL = 202
WEB_COPY = (
    Path(__file__).resolve().parents[2]
    / "web"
    / "src"
    / "features"
    / "league"
    / "advice"
    / "top100Copy.ts"
)
ENVELOPE = {
    "season",
    "gameweek",
    "entry_id",
    "league_id",
    "mode",
    "window",
    "source_snapshot_id",
    "rival_label",
    "rival_entry_id",
    "data_quality",
    "missing_fields",
}


@pytest.fixture(name="world")
def _world(window_world: dict[str, Any]) -> dict[str, Any]:
    """The window world with a second member: the same fifteen, another eleven."""

    mine = window_world["provider"].picks(ENTRY, SEASON, 1)
    bench = [player for player in mine.squad if player not in mine.starting_xi]
    table = window_world["projection"].table
    position = dict(zip(table["player_id"], table["position"], strict=True))
    swapped = next(
        (out, into)
        for into in bench
        for out in mine.starting_xi
        if position[out] == position[into] and out != mine.captain
    )
    eleven = tuple(swapped[1] if player == swapped[0] else player for player in mine.starting_xi)
    rival = replace(mine, entry_id=RIVAL, starting_xi=eleven, captain=eleven[-1])
    # The five best players the member does not hold: at 50 they move the window's plan.
    ranked = table.sort_values(["expected_points", "player_id"], ascending=[False, True])
    outside = [int(player) for player in ranked["player_id"] if int(player) not in mine.squad]
    counts = Top100Counts(
        counts=dict.fromkeys(outside[:5], 100),
        table_sha256="a" * 64,
        cohort_snapshot_id="fpl-top100-20260827T080000Z-000000000000",
        picks_snapshot_id="fpl-elite-picks-20260827T080100Z-111111111111",
        picks_gameweek=1,
    )
    return {
        **window_world,
        "provider": _Provider({ENTRY: mine, RIVAL: rival}),
        "counts": counts,
        "rival_eleven": set(eleven),
    }


def _request(**overrides: Any) -> AdviseEntryRequest:
    fields: dict[str, Any] = {
        "season": SEASON,
        "gameweek": 2,
        "league_id": LEAGUE,
        "entry_id": ENTRY,
    }
    fields.update(overrides)
    return AdviseEntryRequest(**fields)


def _common(world: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": world["provider"],
        "inputs": world["inputs"],
        "projection": world["projection"],
        "rules": world["rules"],
    }


def _window_control(world: dict[str, Any], window: int) -> dict[str, Any]:
    return advise_entry(_request(window=window), **_common(world), horizon_builder=world["builder"])


def _publishable(payload: dict[str, Any]) -> None:
    assert set(payload) - ENVELOPE <= PUBLISHABLE_FIELDS
    assert not any(str(key).startswith("_") for key in payload)

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert not FORBIDDEN_FIELD_PATTERN.search(str(key)), f"{path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            assert not FORBIDDEN_TEXT_PATTERN.search(node), f"{path}: {node}"

    walk(payload, "payload")
    validate_advice_document(
        json.dumps(
            {
                "contract_version": "provisional_league_ui_v1",
                "generated_at_utc": "2026-08-27T09:00:00Z",
                "source_kind": "live",
                "payload": payload,
            }
        ).encode()
    )


def _priced_against(payload: dict[str, Any], control: dict[str, Any]) -> None:
    total = sum(
        row["expected_points"] - row["transfer_hit_points"] for row in payload["plan_weeks"]
    )
    against = sum(
        row["expected_points"] - row["transfer_hit_points"] for row in control["plan_weeks"]
    )
    assert payload["expected_points_cost"] == pytest.approx(max(against, total) - total)
    assert payload["expected_points_cost"] >= 0
    assert payload["control_solver_status"] == control["solver_status"]
    # The ceiling is the price under the control's proof and absent without it.
    if control["solver_status"] == "OPTIMAL":
        assert payload["expected_points_cost_ceiling"] == payload["expected_points_cost"]
    else:
        assert "expected_points_cost_ceiling" not in payload


def test_a_weighted_horizon_scales_every_week_and_keeps_its_provenance(
    world: dict[str, Any],
) -> None:
    base = world["builder"]((2, 3, 4))
    same = weighted_horizon(base, world["counts"].counts, 0)
    assert same.horizon_fingerprint == base.horizon_fingerprint
    weighted = weighted_horizon(base, world["counts"].counts, 50)
    assert weighted.horizon_fingerprint != base.horizon_fingerprint
    assert weighted.source_snapshot_id == base.source_snapshot_id
    favoured = set(world["counts"].counts)
    for (_, before), (_, after) in zip(
        base.table.iterrows(), weighted.table.iterrows(), strict=True
    ):
        factor = 1.5 if int(before["player_id"]) in favoured else 1.0
        assert after["expected_points"] == pytest.approx(before["expected_points"] * factor)
        assert after["gameweek"] == before["gameweek"]


def test_a_window_under_a_setting_states_base_numbers_and_prices_against_the_window_at_0(
    world: dict[str, Any],
) -> None:
    control = _window_control(world, 3)
    advice = advise_window_with_top100(
        _request(window=3),
        weight=50,
        counts=world["counts"],
        **_common(world),
        horizon_builder=world["builder"],
        control_payload=control,
    )
    payload = advice.payload
    assert (payload["mode"], payload["window"]) == ("saf-puan", 3)
    assert payload["top100"]["weight"] == 50
    assert payload["optimality_gap"] is None
    assert payload["stated_limits"][-2:] == [TOP100_LIMIT.format(weight=50), TOP100_WINDOW_LIMIT]
    assert payload["stated_limits"][:-2] == control["stated_limits"]
    points = base_points(world["projection"])
    for player in [*payload["starting_xi"], *payload["bench"], payload["captain"]]:
        assert player["expected_points"] == points[player["player_id"]]
    first = payload["plan_weeks"][0]
    assert first["expected_points"] == pytest.approx(payload["expected_own_points"])
    _priced_against(payload, control)
    # Favouring the best players outside the squad at 50 moves the plan, and it says so.
    assert payload["top100"]["changed"] is True
    assert {move["reason_code"] for move in payload["moves"]} <= {
        "window_value",
        "top100_preference",
    }
    _publishable(payload)


def test_a_window_setting_refuses_what_it_is_not(world: dict[str, Any]) -> None:
    control = _window_control(world, 3)
    for request, weight in ((_request(window=1), 20), (_request(window=3), 0)):
        with pytest.raises(EntryError):
            advise_window_with_top100(
                request,
                weight=weight,
                counts=world["counts"],
                **_common(world),
                horizon_builder=world["builder"],
                control_payload=control,
            )


def test_a_rival_strategy_over_a_window_holds_the_band_in_the_first_week(
    world: dict[str, Any],
) -> None:
    control = _window_control(world, 3)
    for strategy in ("ortak-koru", "fark-yarat"):
        payload = advise_rival_window(
            _request(strategy=strategy, window=3, rival_entry_id=RIVAL),
            weight=0,
            counts=None,
            **_common(world),
            horizon_builder=world["builder"],
            control_payload=control,
        ).payload
        assert (payload["mode"], payload["window"], payload["rival_entry_id"]) == (
            strategy,
            3,
            RIVAL,
        )
        # The band counts the rival's eleven inside the member's fifteen.
        fifteen = {p["player_id"] for p in [*payload["starting_xi"], *payload["bench"]]}
        overlap = len(fifteen & world["rival_eleven"])
        assert overlap == payload["overlap_count"]
        if strategy == "ortak-koru":
            assert overlap >= payload["overlap_applied"]
        else:
            assert overlap <= payload["overlap_applied"]
        assert payload["transfer_cap"] == 1
        assert payload["plan_kind"] == "within_free_transfers"
        assert payload["alternative_plan"] is None
        assert len(payload["plan_weeks"]) == 3
        assert all(len(row["transfers_in"]) <= 1 for row in payload["plan_weeks"])
        assert payload["stated_limits"][-1] == RIVAL_WINDOW_LIMIT
        assert "top100" not in payload
        assert {move["reason_code"] for move in payload["moves"]} <= {"mode_tradeoff"}
        _priced_against(payload, control)
        _publishable(payload)


def test_a_rival_window_under_a_setting_is_the_same_document_on_base_numbers(
    world: dict[str, Any],
) -> None:
    control = _window_control(world, 3)
    arguments = {**_common(world), "horizon_builder": world["builder"], "control_payload": control}
    request = _request(strategy="ortak-koru", window=3, rival_entry_id=RIVAL)
    at_zero = advise_rival_window(request, weight=0, counts=None, **arguments).payload
    payload = advise_rival_window(
        request, weight=50, counts=world["counts"], **arguments, reference_payload=at_zero
    ).payload
    assert payload["top100"]["weight"] == 50
    assert payload["optimality_gap"] is None
    assert payload["stated_limits"][-3:] == [
        RIVAL_WINDOW_LIMIT,
        TOP100_LIMIT.format(weight=50),
        TOP100_WINDOW_LIMIT,
    ]
    points = base_points(world["projection"])
    for player in payload["starting_xi"]:
        assert player["expected_points"] == points[player["player_id"]]
    _priced_against(payload, control)
    _publishable(payload)
    with pytest.raises(EntryError):
        advise_rival_window(request, weight=20, counts=None, **arguments)


def test_a_one_week_rival_strategy_under_a_setting_that_favours_nobody_is_the_strategy_itself(
    world: dict[str, Any],
) -> None:
    """With no counts the weighted points are the base points, so the document must be the
    published strategy document: same decision, same price, same rival reading."""

    common = _common(world)
    mine = world["provider"].picks(ENTRY, SEASON, 1)
    control = solve_member_control(mine, world["inputs"], world["projection"], world["rules"])
    prices = {
        int(row["player_id"]): int(row["price_tenths"])
        for _, row in world["inputs"].players.iterrows()
    }
    pricing = solve_pricing_control(
        world["inputs"],
        world["projection"],
        held_squad_from_picks(mine, current_prices=prices),
        world["rules"],
        control,
    )
    request = _request(strategy="ortak-koru", rival_entry_id=RIVAL)
    reference = advise_entry(request, **common, control=control)
    nobody = replace(world["counts"], counts={})
    payload = advise_rival_with_top100(
        request,
        weight=30,
        counts=nobody,
        **common,
        control=control,
        pricing=pricing,
        reference_payload=reference,
    ).payload
    assert payload["top100"] == {
        "weight": 30,
        "changed": False,
        "price_basis": "base_model_pure_points_v1",
        **nobody.source_record(),
    }
    assert payload["stated_limits"] == [
        *reference["stated_limits"],
        TOP100_LIMIT.format(weight=30),
    ]
    for key in set(reference) - {"stated_limits", "optimality_gap"}:
        assert (
            payload[key] == pytest.approx(reference[key])
            if isinstance(reference[key], float)
            else payload[key] == reference[key]
        ), key
    assert payload["optimality_gap"] is None
    _publishable(payload)

    favoured = advise_rival_with_top100(
        request,
        weight=50,
        counts=world["counts"],
        **common,
        control=control,
        pricing=pricing,
        reference_payload=reference,
    ).payload
    assert favoured["expected_points_cost"] >= 0
    assert favoured["control_solver_status"] == pricing.solver_status.name == "OPTIMAL"
    assert favoured["expected_points_cost_ceiling"] == favoured["expected_points_cost"]
    points = base_points(world["projection"])
    for player in favoured["starting_xi"]:
        assert player["expected_points"] == points[player["player_id"]]
    _publishable(favoured)


def _publish(world: dict[str, Any], out: Path, *, counts: Top100Counts | None) -> Any:
    return build_league_views(
        world["provider"],
        (
            EntryRegistration(ENTRY, "member-a", "2026-08-23T00:00:00Z"),
            EntryRegistration(RIVAL, "member-b", "2026-08-23T00:00:00Z"),
        ),
        world["inputs"],
        world["projection"],
        world["rules"],
        league_id=LEAGUE,
        league_name="Test League",
        out_dir=out,
        now=datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC),
        standings={
            ENTRY: MemberStanding(ENTRY, "A", "a", rank=2, last_rank=2),
            RIVAL: MemberStanding(RIVAL, "B", "b", rank=1, last_rank=1),
        },
        horizon_builder=world["builder"],
        top100_counts=counts,
    )


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def test_the_batch_publishes_the_wider_menu_against_the_default_rival_and_names_it(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(views, "TOP100_WEIGHTS", (0, 50))
    plain = _publish(world, tmp_path / "plain", counts=None)
    menu = _publish(world, tmp_path / "menu", counts=world["counts"])

    # Everything the plain publish wrote keeps its bytes, the index excepted.
    for name in plain.files:
        if name.endswith("index.json"):
            continue
        assert (tmp_path / "plain" / name).read_bytes() == (
            tmp_path / "menu" / name
        ).read_bytes(), name

    index = _read(tmp_path / "menu" / f"advice/{ENTRY}/index.json")
    assert index["default_rival_entry_id"] == RIVAL
    assert index["windows"] == {
        "saf-puan": [1, 3, 5],
        "ortak-koru": [1, 3, 5],
        "fark-yarat": [1, 3, 5],
    }
    windows = {
        (row["strategy"], row["window"], row["path"])
        for row in index["computed"]
        if "window" in row
    }
    assert windows == {
        (strategy, window, f"advice/{ENTRY}/{strategy}/{window}/vs-{RIVAL}.json")
        for strategy in ("ortak-koru", "fark-yarat")
        for window in (3, 5)
    }
    documents = {
        (row["strategy"], row["window"], row["rival_entry_id"], row["weight"]): row["path"]
        for row in index["top100"]["documents"]
    }
    expected = {
        **{("saf-puan", window, None, 50): None for window in (3, 5)},
        **{
            (strategy, window, RIVAL, 50): None
            for strategy in ("ortak-koru", "fark-yarat")
            for window in (1, 3, 5)
        },
    }
    assert set(documents) == set(expected)
    for (strategy, window, rival, weight), path in documents.items():
        assert path == variant_path(ENTRY, strategy, window, rival, weight)
        document = _read(tmp_path / "menu" / path)
        assert (document["mode"], document["window"]) == (strategy, window)
        assert document["top100"]["weight"] == weight
        assert document.get("rival_entry_id") == rival
    assert index["top100"]["paths"] == {"50": f"advice/{ENTRY}/saf-puan/1/top100-50.json"}
    # Without counts the strategies' windows are still there, at 0.
    plain_index = _read(tmp_path / "plain" / f"advice/{ENTRY}/index.json")
    assert plain_index["windows"]["ortak-koru"] == [1, 3, 5]
    assert plain_index["top100"] == {"available": False, "reason": "no_top100_this_run"}
    assert menu.members[0].rendered

    # A later publish without the menu removes what it no longer writes, and says so.
    again = _publish(world, tmp_path / "menu", counts=None)
    assert not list((tmp_path / "menu" / "advice").rglob("top100-*.json"))
    assert f"advice/{ENTRY}/ortak-koru/3/vs-{RIVAL}/top100-50.json" in again.removed
    assert (tmp_path / "menu" / f"advice/{ENTRY}/ortak-koru/3/vs-{RIVAL}.json").is_file()


def test_a_variant_that_fails_is_recorded_at_its_address(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(views, "TOP100_WEIGHTS", (0, 50))
    real = views.advise_rival_window

    def flaky(request: AdviseEntryRequest, **kwargs: Any) -> Any:
        if request.strategy == "fark-yarat" and request.window == 5:
            raise EntryError("no plan in this window")
        return real(request, **kwargs)

    monkeypatch.setattr(views, "advise_rival_window", flaky)
    report = _publish(world, tmp_path, counts=world["counts"])
    index = _read(tmp_path / f"advice/{ENTRY}/index.json")
    assert index["windows"]["fark-yarat"] == [1, 3]
    assert {
        "strategy": "fark-yarat",
        "rival_entry_id": RIVAL,
        "window": 5,
        # The index is public and carries one stable code; the planner's text is the note's.
        "reason": "not_solved_for_member",
    } in index["unavailable"]
    assert not (tmp_path / f"advice/{ENTRY}/fark-yarat/5").exists()
    note = next(member.reason for member in report.members if member.entry_id == ENTRY)
    assert (
        "fark-yarat 5 weeks vs 202, Top 100 influence 0 not solved: no plan in this window" in note
    )
    assert "Top 100 influence 50 not solved: The strategy's window at 0 did not solve." in note


def test_the_site_holds_the_new_limit_sentences_verbatim() -> None:
    text = WEB_COPY.read_text(encoding="utf-8")
    for sentence in (TOP100_WINDOW_LIMIT, RIVAL_WINDOW_LIMIT):
        assert text.count(json.dumps(sentence)) == 3, sentence


# -- the review's fixes -------------------------------------------------------------------


def test_the_eleven_is_read_the_way_the_solver_breaks_a_tie() -> None:
    """Two midfielders level on the points the plan is chosen on, once rounded the way the
    solver rounds them: the lower id starts, whatever order the fifteen is handed in."""

    def squad(order: list[int]) -> list[tuple[str, float, float, bool, bool, int]]:
        rows: dict[int, tuple[str, float, float]] = {
            1: ("GK", 4.0, 4.0),
            2: ("GK", 1.0, 1.0),
            **{10 + i: ("DEF", 3.0, 3.0) for i in range(5)},
            **{20 + i: ("MID", 5.0, 5.0) for i in range(3)},
            # 23 and 24 tie at 4.0 once rounded to thousandths; their base points differ.
            23: ("MID", 4.0004, 3.2),
            24: ("MID", 4.0, 4.0),
            **{30 + i: ("FWD", 2.0, 2.0) for i in range(3)},
        }
        return [(*rows[i], True, True, i) for i in order]

    ids = [1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32]
    forwards = best_eleven_basis(squad(ids))
    backwards = best_eleven_basis(squad(list(reversed(ids))))
    assert forwards is not None
    assert forwards == backwards


def test_rows_that_do_not_land_on_the_published_total_are_not_published() -> None:
    lookup: dict[int, tuple[str, float]] = {1: ("MID", 5.0), 2: ("MID", 4.0)}
    lookup.update({100 + i: ("DEF", 3.0) for i in range(5)})
    lookup.update({200 + i: ("MID", 3.0) for i in range(4)})
    lookup.update({300 + i: ("FWD", 3.0) for i in range(3)})
    lookup.update({400: ("GK", 3.0), 401: ("GK", 1.0)})
    held = [400, 401, *range(100, 105), *range(200, 204), 2, *range(300, 303)]
    choice = {player: points for player, (_position, points) in lookup.items()}
    after = [1 if player == 2 else player for player in held]
    walked = advice_module._attributed_gains([(2, 1)], held=held, lookup=lookup, choice=choice)
    assert walked == [pytest.approx(2.0)]
    total = best_eleven_basis((lookup[p][0], choice[p], lookup[p][1], True, True, p) for p in after)
    assert total is not None
    agrees = advice_module._attributed_gains(
        [(2, 1)], held=held, lookup=lookup, choice=choice, expected_total=total
    )
    assert agrees == walked
    assert (
        advice_module._attributed_gains(
            [(2, 1)], held=held, lookup=lookup, choice=choice, expected_total=total - 0.8
        )
        is None
    )


def test_a_member_window_is_solved_at_the_window_linearization_level(
    world: dict[str, Any],
) -> None:
    mine = world["provider"].picks(ENTRY, SEASON, 1)
    horizon = window_horizon(world["inputs"], 3, world["builder"])
    plan = solve_window_plan(mine, world["inputs"], world["rules"], horizon, window=3)
    assert plan.diagnostics["linearization_level"] == WINDOW_LINEARIZATION_LEVEL == 2


def test_a_window_priced_against_an_unproven_control_publishes_no_ceiling(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A window's price has a ceiling only under the pure-points window's proof.

    That window's gap is on its objective over every week at once (a tenth of each week's
    bench, each paid transfer at the caution margin), which bounds no price in base
    points. So a proven control prices with the ceiling equal to the price, and an
    unproven one with none: on a Top 100 window, on a rival window, and on a rival window
    restated from a pure-points document that carried a ceiling of its own.
    """

    control = _window_control(world, 3)
    unproven = {**control, "solver_status": "FEASIBLE", "optimality_gap": 2.0}
    total = sum(r["expected_points"] - r["transfer_hit_points"] for r in control["plan_weeks"])
    proven: dict[str, Any] = {}
    variants._price(
        proven, control_payload={**control, "solver_status": "OPTIMAL"}, selected_total=total - 1.5
    )
    assert proven["expected_points_cost"] == pytest.approx(1.5)
    assert proven["expected_points_cost_ceiling"] == proven["expected_points_cost"]
    carried: dict[str, Any] = {"expected_points_cost_ceiling": 0.0}
    variants._price(carried, control_payload=unproven, selected_total=total)
    assert carried["expected_points_cost"] == 0.0
    assert "expected_points_cost_ceiling" not in carried

    weighted = advise_window_with_top100(
        _request(window=3),
        weight=50,
        counts=world["counts"],
        **_common(world),
        horizon_builder=world["builder"],
        control_payload=unproven,
    ).payload
    request = _request(strategy="ortak-koru", window=3, rival_entry_id=RIVAL)
    arguments = {**_common(world), "horizon_builder": world["builder"], "control_payload": unproven}
    rival = advise_rival_window(request, weight=0, counts=None, **arguments).payload

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the window must not be solved again")

    monkeypatch.setattr(variants, "solve_window_plan", refuse)
    restated = advise_rival_window(
        request,
        weight=0,
        counts=None,
        **arguments,
        applied_level=int(str(rival["overlap_applied"])),
        pure_payload={**control, "expected_points_cost": 0.0, "expected_points_cost_ceiling": 0.0},
    ).payload
    for payload in (weighted, rival, restated):
        assert payload["control_solver_status"] == "FEASIBLE"
        assert payload["control_optimality_gap"] == 2.0
        assert float(str(payload["expected_points_cost"])) >= 0
        assert "expected_points_cost_ceiling" not in payload
        _publishable(payload)


def test_a_window_that_already_holds_the_band_is_the_strategys_window(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _window_control(world, 3)
    arguments = {**_common(world), "horizon_builder": world["builder"], "control_payload": control}
    request = _request(strategy="ortak-koru", window=3, rival_entry_id=RIVAL)
    solved = advise_rival_window(request, weight=0, counts=None, **arguments).payload

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the window must not be solved again")

    monkeypatch.setattr(variants, "solve_window_plan", refuse)
    reused = advise_rival_window(
        request,
        weight=0,
        counts=None,
        **arguments,
        applied_level=solved["overlap_applied"],
        pure_payload=control,
    ).payload
    assert reused["mode"] == "ortak-koru"
    assert control["mode"] == "saf-puan"  # the pure document is untouched
    assert reused["plan_weeks"] == control["plan_weeks"]
    assert reused["starting_xi"] == control["starting_xi"]
    assert reused["expected_points_cost"] == 0.0
    assert reused["stated_limits"] == [*control["stated_limits"], RIVAL_WINDOW_LIMIT]
    assert {m["reason_code"] for m in reused["moves"]} <= {"mode_tradeoff"}
    for key in ("overlap_applied", "overlap_target", "transfer_cap", "plan_kind"):
        assert reused[key] == solved[key], key
    assert reused["overlap_count"] >= reused["overlap_applied"]
    _publishable(reused)
    # A window that does not hold the level asked for is solved, not reused.
    with pytest.raises(AssertionError, match="must not be solved again"):
        advise_rival_window(
            request, weight=0, counts=None, **arguments, applied_level=12, pure_payload=control
        )


def test_the_batch_finds_each_band_level_and_the_pricing_control_once(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(views, "TOP100_WEIGHTS", (0, 50))
    calls = {"level": 0, "pricing": 0}
    level, pricing = views.band_level_with_one_transfer, views.solve_pricing_control

    def counted_level(*args: Any, **kwargs: Any) -> Any:
        calls["level"] += 1
        return level(*args, **kwargs)

    def counted_pricing(*args: Any, **kwargs: Any) -> Any:
        calls["pricing"] += 1
        return pricing(*args, **kwargs)

    def solved_again(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the pricing control was solved again inside a document")

    monkeypatch.setattr(views, "band_level_with_one_transfer", counted_level)
    monkeypatch.setattr(views, "solve_pricing_control", counted_pricing)
    monkeypatch.setattr(advice_module, "solve_pricing_control", solved_again)
    report = _publish(world, tmp_path, counts=world["counts"])
    assert all(member.rendered for member in report.members)
    # Two members, two strategies each; one pricing control each.
    assert calls == {"level": 4, "pricing": 2}


def test_a_later_week_that_differs_only_in_its_total_is_a_changed_plan() -> None:
    week = {"transfers_in": [], "transfers_out": [], "expected_points": 50.0}
    same = {"plan_weeks": [week, week], "moves": [], "starting_xi": [], "captain": None}
    other = {**same, "plan_weeks": [week, {**week, "expected_points": 53.7}]}
    assert variants._signature(same) == variants._signature(dict(same))
    assert variants._signature(same) != variants._signature(other)


def test_a_row_the_base_model_scores_below_zero_is_the_settings() -> None:
    payload: dict[str, Any] = {
        "moves": [
            {"expected_points_delta": -0.1, "reason_code": "points_gain"},
            {"expected_points_delta": 0.4, "reason_code": "points_gain"},
            {"expected_points_delta": -0.3, "reason_code": "manager_word"},
            {"expected_points_delta": None, "reason_code": "window_value"},
        ]
    }
    advice_module._setting_rows(payload)
    assert [m["reason_code"] for m in payload["moves"]] == [
        "top100_preference",
        "points_gain",
        "manager_word",
        "window_value",
    ]
