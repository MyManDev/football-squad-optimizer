"""A chip the member chose: forced on the one-week plan, scored as the chip week scores.

The planner never decides a chip on the member path. The member names one, the solve is
handed exactly that chip, and the document states what the chip week is expected to score
above the member's own no-chip plan, this gameweek only, beside the sentence saying that
is all it states.
"""

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
from tests.unit.test_league_views import _legal_squad, _member_picks, _Provider, _world_context
from tests.unit.test_top100_weight import PREFERRED, _counts, _words

from squadopt.application.advice import (
    NO_CHIP_LIMIT,
    AdviseEntryRequest,
    advise_entry,
    advise_with_managers_word,
    advise_with_top100,
    net_expected_points,
    solve_member_control,
)
from squadopt.application.advice_chips import (
    CHIP_CHOICE_BASIS,
    CHIP_CHOICE_LIMIT,
    FREE_HIT_LIMIT,
    advise_with_chip,
    chip_week_points,
    member_chip_menu,
)
from squadopt.application.entries import EntryError, EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.application.lineup_publication import (
    best_eleven_points,
    best_lineup_points_with_chip,
)
from squadopt.application.strategies.catalog import (
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
    PUBLISHABLE_FIELDS,
)
from squadopt.live.rules import ChipWindow
from squadopt.platform.advice_documents import validate_advice_document

world = world_module._world  # re-register the fixture in this module

LEAGUE = 352490
ENVELOPE = {
    "season",
    "gameweek",
    "entry_id",
    "league_id",
    "mode",
    "window",
    "source_snapshot_id",
    "rival_label",
    "data_quality",
    "missing_fields",
}


def _request(entry_id: int = 101) -> AdviseEntryRequest:
    return AdviseEntryRequest(season="2026-27", gameweek=2, league_id=LEAGUE, entry_id=entry_id)


def _every_chip_open(rules: Any) -> Any:
    """The world's rules with the Triple Captain's window opened over gameweek 2 as well."""

    return replace(
        rules,
        chips=tuple(
            ChipWindow(w.name, w.number, 1, 19, w.chip_type) if w.name == "3xc" else w
            for w in rules.chips
        ),
    )


def _advise(world: dict[str, Any], chip: str, **picks_overrides: Any) -> Any:
    inputs, projection, rules = _world_context(world)
    rules = _every_chip_open(rules)
    picks = replace(_member_picks(world, 101, _legal_squad(world)), **picks_overrides)
    provider = _Provider({101: picks})
    control = solve_member_control(picks, inputs, projection, rules)
    advice = advise_with_chip(
        _request(),
        chip=chip,
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        control=control,
    )
    return advice, control, (inputs, projection, rules, picks, provider)


def _readded(payload: dict[str, Any]) -> float:
    """The chip week's total as a reader re-adds it from the published rows."""

    total = math.fsum(p["expected_points"] for p in payload["starting_xi"])
    total += payload["captain"]["expected_points"]
    if payload["chip"] == "3xc":
        total += payload["captain"]["expected_points"]
    if payload["chip"] == "bboost":
        total += math.fsum(p["expected_points"] for p in payload["bench"])
    return total


# -- which chips a member may choose ------------------------------------------------------


def test_the_menu_is_the_members_own_history_against_the_published_windows(
    world: dict[str, Any],
) -> None:
    _inputs, _projection, rules = _world_context(world)
    menu = member_chip_menu(rules, 2, {})
    assert menu.known is True
    assert menu.held == ("wildcard", "freehit", "bboost")
    # The world's Triple Captain opens in gameweek 20.
    assert menu.unavailable == (("3xc", "window_not_open"),)
    assert menu.windows["bboost"]["first_half"] == {
        "state": "available",
        "gameweek": None,
        "start_event": 1,
        "stop_event": 19,
    }

    played = member_chip_menu(rules, 2, {"bboost": (1,)})
    assert played.held == ("wildcard", "freehit")
    assert ("bboost", "already_played") in played.unavailable


def test_a_free_hit_played_last_gameweek_bars_this_gameweeks(world: dict[str, Any]) -> None:
    _inputs, _projection, rules = _world_context(world)
    halves = replace(
        rules,
        chips=(
            *rules.chips,
            ChipWindow("freehit", 1, 20, 38, "transfer"),
        ),
    )
    menu = member_chip_menu(halves, 20, {"freehit": (19,)})
    assert "freehit" not in menu.held
    assert ("freehit", "free_hit_played_last_gameweek") in menu.unavailable
    assert "freehit" in member_chip_menu(halves, 21, {"freehit": (19,)}).held


def test_an_uncaptured_history_offers_no_chip_and_guesses_none(world: dict[str, Any]) -> None:
    _inputs, _projection, rules = _world_context(world)
    menu = member_chip_menu(rules, 2, None)
    assert menu.known is False
    assert menu.held == () and menu.unavailable == ()
    assert menu.windows["wildcard"]["first_half"]["state"] == "unknown"


# -- the basis a chip week scores on ------------------------------------------------------

SQUAD = [
    ("GK", 4.0),
    ("GK", 3.0),
    *(("DEF", value) for value in (5.0, 4.0, 3.5, 3.0, 1.0)),
    *(("MID", value) for value in (9.0, 6.0, 5.0, 2.0, 1.5)),
    *(("FWD", value) for value in (7.0, 4.5, 2.5)),
]


def test_a_rebuild_chip_scores_as_any_week_does() -> None:
    for chip in ("wildcard", "freehit"):
        assert best_lineup_points_with_chip(SQUAD, chip) == best_eleven_points(SQUAD)


def test_a_triple_captain_counts_the_captain_once_more() -> None:
    doubled = best_eleven_points(SQUAD)
    assert doubled is not None
    assert best_lineup_points_with_chip(SQUAD, "3xc") == pytest.approx(doubled + 9.0)


def test_a_bench_boost_scores_all_fifteen_with_the_best_of_them_doubled() -> None:
    total = sum(value for _position, value in SQUAD)
    assert best_lineup_points_with_chip(SQUAD, "bboost") == pytest.approx(total + 9.0)


def test_a_fifteen_with_no_legal_eleven_has_no_chip_value_either() -> None:
    forwards = [("FWD", 5.0)] * 15
    for chip in ("wildcard", "3xc", "bboost"):
        assert best_lineup_points_with_chip(forwards, chip) is None


# -- the chip document ----------------------------------------------------------------------


@pytest.mark.parametrize("chip", ["wildcard", "freehit", "bboost", "3xc"])
def test_a_chip_document_is_the_chip_week_as_it_is_expected_to_score(
    world: dict[str, Any], chip: str
) -> None:
    advice, control, (_inputs, projection, _rules, picks, _provider) = _advise(world, chip)
    payload = advice.payload

    assert advice.chip == chip
    assert payload["mode"] == "saf-puan" and payload["window"] == 1
    assert payload["chip"] == chip
    assert payload["expected_own_points"] == pytest.approx(_readded(payload), abs=1e-9)
    assert payload["expected_points_cost"] == 0.0
    assert "expected_points_cost_ceiling" not in payload
    assert payload["control_solver_status"] == control.plan.solver_status.name

    choice = payload["chip_choice"]
    assert set(choice) == {"chip", "gain_vs_no_chip", "basis", "windows_left"}
    assert choice["chip"] == chip and choice["basis"] == CHIP_CHOICE_BASIS
    assert choice["windows_left"]["first_half"]["state"] == "available"
    # The gain is the two weeks' difference, each net of the hits it pays.
    assert choice["gain_vs_no_chip"] == pytest.approx(
        payload["expected_own_points"]
        - payload["transfer_hit_points"]
        - net_expected_points(control.plan),
        abs=1e-9,
    )

    # The rows add up to the gain against holding, and the gain to the lineup total, on
    # the basis the chip week scores on, with the held fifteen playing the same chip.
    lookup = {
        int(p): (str(q), float(v))
        for p, q, v in zip(
            projection.table["player_id"],
            projection.table["position"],
            projection.table["expected_points"],
            strict=True,
        )
    }
    hold = best_lineup_points_with_chip((lookup[p] for p in picks.squad), chip)
    assert hold is not None
    assert payload["expected_gain_vs_hold"] == pytest.approx(
        payload["expected_own_points"] - hold, abs=1e-9
    )
    rows = [move["expected_points_delta"] for move in payload["moves"]]
    assert math.fsum(rows) == pytest.approx(payload["expected_gain_vs_hold"], abs=1e-9)
    assert {move["reason_code"] for move in payload["moves"]} <= {"points_gain"}

    assert CHIP_CHOICE_LIMIT in payload["stated_limits"]
    assert NO_CHIP_LIMIT not in payload["stated_limits"]
    assert (FREE_HIT_LIMIT in payload["stated_limits"]) is (chip == "freehit")

    assert set(payload) - ENVELOPE <= PUBLISHABLE_FIELDS
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


def test_a_rebuild_chip_pays_no_hits_and_is_not_below_the_control(world: dict[str, Any]) -> None:
    for chip in ("wildcard", "freehit"):
        advice, _control, _context = _advise(world, chip)
        assert advice.payload["transfer_hit_points"] == 0.0
        assert advice.payload["chip_choice"]["gain_vs_no_chip"] >= -1e-9
        assert not any("below the no-chip control" in note for note in advice.notes)


def test_the_bench_and_the_third_captain_count_are_what_the_planner_counted(
    world: dict[str, Any],
) -> None:
    for chip in ("bboost", "3xc"):
        advice, _control, (inputs, projection, rules, picks, _provider) = _advise(world, chip)
        from squadopt.application.advice_chips import CHIP_OPTIMIZATION
        from squadopt.application.entries import held_squad_from_picks
        from squadopt.live import plan_transfers

        prices = {
            int(row["player_id"]): int(row["price_tenths"]) for _, row in inputs.players.iterrows()
        }
        plan, _decision, _config = plan_transfers(
            inputs,
            projection,
            held_squad_from_picks(picks, current_prices=prices),
            rules,
            optimization=CHIP_OPTIMIZATION,
            chip=chip,
        )
        assert advice.payload["expected_own_points"] == pytest.approx(
            chip_week_points(plan.weeks[0]), abs=1e-9
        )


def test_the_default_document_still_says_no_chip_was_offered(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    baseline = advise_entry(
        _request(),
        provider=_Provider({101: picks}),
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    assert baseline["chip"] is None
    assert baseline["stated_limits"] == [NO_CHIP_LIMIT]
    assert "chip_choice" not in baseline


def test_a_chip_the_member_cannot_play_is_refused_before_any_solve(
    world: dict[str, Any],
) -> None:
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    cases: list[tuple[Any, AdviseEntryRequest, str]] = [
        (picks, _request(), "3xc"),  # the window opens in gameweek 20
        (replace(picks, chips_used={"bboost": (1,)}), _request(), "bboost"),
        (replace(picks, chips_used=None), _request(), "wildcard"),
        (picks, _request(), "limitless"),
        (picks, replace(_request(), window=3), "wildcard"),
        (picks, replace(_request(), strategy="ortak-koru", rival_entry_id=202), "wildcard"),
    ]
    for member, request, chip in cases:
        with pytest.raises(EntryError):
            advise_with_chip(
                request,
                chip=chip,
                provider=_Provider({101: member}),
                inputs=inputs,
                projection=projection,
                rules=rules,
            )


def test_chip_documents_carry_no_forbidden_text(world: dict[str, Any]) -> None:
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

    for chip in ("freehit", "bboost"):
        advice, _control, _context = _advise(world, chip)
        walk(advice.payload, chip)


# -- publication ------------------------------------------------------------------------


def _publish(
    world: dict[str, Any],
    out: Path,
    *,
    picks_overrides: dict[str, Any] | None = None,
    squads: dict[int, list[int]] | None = None,
    **options: Any,
) -> Any:
    inputs, projection, rules = _world_context(world)
    squads = squads or {101: _legal_squad(world)}
    provider = _Provider(
        {
            entry: replace(_member_picks(world, entry, squad), **(picks_overrides or {}))
            for entry, squad in squads.items()
        }
    )
    registrations = tuple(
        EntryRegistration(entry, f"member-{entry}", "2026-08-23T00:00:00Z") for entry in squads
    )
    return build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=LEAGUE,
        league_name="Test League",
        out_dir=out,
        **options,
    )


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def test_every_held_chip_is_published_beside_the_baseline_and_named_in_the_index(
    world: dict[str, Any], tmp_path: Path
) -> None:
    report = _publish(world, tmp_path)
    directory = tmp_path / "advice/101/saf-puan/1"
    assert sorted(path.name for path in directory.iterdir()) == [
        "chip-bboost.json",
        "chip-freehit.json",
        "chip-wildcard.json",
    ]
    index = _read(tmp_path / "advice/101/index.json")
    assert index["chips"] == {
        "available": True,
        "paths": {
            chip: f"advice/101/saf-puan/1/chip-{chip}.json"
            for chip in ("wildcard", "freehit", "bboost")
        },
        "unavailable": [{"chip": "3xc", "reason": "window_not_open"}],
        "held": ["wildcard", "freehit", "bboost"],
    }
    for chip in ("wildcard", "freehit", "bboost"):
        document = _read(directory / f"chip-{chip}.json")
        assert document["chip"] == chip and document["chip_choice"]["chip"] == chip
    assert {f"advice/101/saf-puan/1/chip-{chip}.json" for chip in index["chips"]["paths"]} <= set(
        report.files
    )
    assert report.members[0].rendered


def test_every_other_document_keeps_the_bytes_its_own_function_returns(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The chips are solved on every run, so there is no publish without them to compare
    with; each existing document is compared with what its own function returns."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    picks = _member_picks(world, 101, squad)
    provider = _Provider({101: picks})
    words = _words(squad[0])
    counts = _counts(PREFERRED)
    _publish(world, tmp_path, manager_words=words, top100_counts=counts)
    common = {"provider": provider, "inputs": inputs, "projection": projection, "rules": rules}

    assert _read(tmp_path / "advice/101/saf-puan/1.json") == advise_entry(_request(), **common)
    assert _read(tmp_path / "advice/101/saf-puan/1/hoca-sozu.json") == json.loads(
        json.dumps(advise_with_managers_word(_request(), words=words, **common))
    )
    for weight in (5, 50):
        weighted = advise_with_top100(
            _request(), weight=weight, counts=counts, words=words, **common
        )
        directory = tmp_path / "advice/101/saf-puan/1"
        assert _read(directory / f"top100-{weight}.json") == json.loads(
            json.dumps(weighted.payload)
        )
        assert _read(directory / f"top100-{weight}-hoca-sozu.json") == json.loads(
            json.dumps(weighted.word_payload)
        )


def test_published_chip_documents_are_in_the_advice_record(
    world: dict[str, Any], tmp_path: Path
) -> None:
    _publish(world, tmp_path / "tree", advice_record_root=tmp_path / "record")
    records = list((tmp_path / "record").rglob("advice.json"))
    assert records
    recorded = {
        item["published_path"]
        for path in records
        for item in json.loads(path.read_text(encoding="utf-8"))["advice"]
        if "/chip-" in item["published_path"]
    }
    published = {
        path.relative_to(tmp_path / "tree").as_posix()
        for path in (tmp_path / "tree").rglob("chip-*.json")
    }
    assert published
    assert recorded == published


def test_a_chip_played_since_the_last_publish_takes_its_file_with_it(
    world: dict[str, Any], tmp_path: Path
) -> None:
    _publish(world, tmp_path)
    assert (tmp_path / "advice/101/saf-puan/1/chip-bboost.json").is_file()

    report = _publish(world, tmp_path, picks_overrides={"chips_used": {"bboost": (1,)}})
    index = _read(tmp_path / "advice/101/index.json")
    assert "bboost" not in index["chips"]["paths"]
    assert {"chip": "bboost", "reason": "already_played"} in index["chips"]["unavailable"]
    assert not (tmp_path / "advice/101/saf-puan/1/chip-bboost.json").exists()
    assert "advice/101/saf-puan/1/chip-bboost.json" in report.removed


def test_a_member_with_every_open_chip_played_is_told_none_is_left(
    world: dict[str, Any], tmp_path: Path
) -> None:
    spent = {"wildcard": (1,), "freehit": (1,), "bboost": (1,)}
    _publish(world, tmp_path / "spent", picks_overrides={"chips_used": spent})
    index = _read(tmp_path / "spent/advice/101/index.json")
    assert index["chips"]["available"] is False
    assert index["chips"]["reason"] == "no_chip_left"
    assert index["chips"]["held"] == []
    assert not (tmp_path / "spent/advice/101/saf-puan/1").exists()


def test_a_chip_that_fails_is_recorded_not_fatal(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import squadopt.application.league_views as views

    real = views.advise_with_chip

    def flaky(*args: Any, **kwargs: Any) -> Any:
        if kwargs["chip"] == "wildcard":
            raise EntryError("no plan under this chip")
        return real(*args, **kwargs)

    monkeypatch.setattr(views, "advise_with_chip", flaky)
    report = _publish(world, tmp_path)
    index = _read(tmp_path / "advice/101/index.json")
    assert "wildcard" not in index["chips"]["paths"]
    assert {"chip": "wildcard", "reason": "not_solved_for_member"} in index["chips"]["unavailable"]
    assert index["chips"]["held"] == ["wildcard", "freehit", "bboost"]
    assert "chip wildcard not solved: no plan under this chip" in report.members[0].reason
    assert (tmp_path / "advice/101/saf-puan/1.json").is_file()


def test_a_chip_document_is_invariant_to_every_other_member(
    world: dict[str, Any], tmp_path: Path
) -> None:
    squad = _legal_squad(world)
    other = [*squad[:-1], 1023]
    _publish(world, tmp_path / "alone")
    _publish(world, tmp_path / "pair", squads={101: squad, 102: other})
    for chip in ("wildcard", "bboost"):
        relative = f"advice/101/saf-puan/1/chip-{chip}.json"
        assert _read(tmp_path / "alone" / relative) == _read(tmp_path / "pair" / relative)


def test_without_an_index_to_name_them_no_chip_is_solved_or_written(
    world: dict[str, Any], tmp_path: Path
) -> None:
    _publish(world, tmp_path, rival_menu=False)
    assert not (tmp_path / "advice/101/index.json").exists()
    assert not list((tmp_path / "advice").rglob("chip-*.json"))


# -- the sentences the site keys its copy by ----------------------------------------------


def test_the_site_holds_the_producers_chip_sentences_word_for_word() -> None:
    """The page translates a stated limit by looking the producer's sentence up; a sentence
    that drifted would fall through as "unknown" on the card and every other test stays
    green."""

    web = Path(__file__).resolve().parents[2] / "web" / "src"
    fixture = (web / "fixtures" / "league.ts").read_text(encoding="utf-8")
    copy = (web / "features" / "league" / "advice" / "chipCopy.ts").read_text(encoding="utf-8")
    for sentence in (CHIP_CHOICE_LIMIT, FREE_HIT_LIMIT):
        assert json.dumps(sentence) in fixture
        assert json.dumps(sentence) in copy


def test_a_history_the_windows_cannot_place_offers_no_chip_and_keeps_the_member(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import squadopt.application.league_views as views

    def unplaceable(*_args: Any, **_kwargs: Any) -> Any:
        raise EntryError("Chip 'bboost' was played in [25], outside every window.")

    monkeypatch.setattr(views, "member_chip_menu", unplaceable)
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    render = views.render_member(
        views.MemberRenderTask(
            entry_id=101,
            label="member-101",
            season="2026-27",
            gameweek=2,
            league_id=LEAGUE,
            rival_ids=(),
            default_rival_id=None,
            rival_strategies=(),
        ),
        provider=_Provider({101: picks}),
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    assert render.baseline is not None
    assert render.chips_known is False
    assert render.chip_payloads == () and render.chips_held == ()
    assert any("outside every window" in note for note in render.chip_notes)
