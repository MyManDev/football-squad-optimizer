"""The Top 100 influence: a member's weight on last week's Top 100 elevens, priced on base points.

The weight moves the points a plan is chosen on and nothing else: every number a weighted
document publishes is the base projection's, the price is the base-model difference
against the member's own weight-zero plan, and the counts pass the same gate the handoff
applies before any of it is solved.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import tests.unit.test_live_transfers as world_module
from tests.unit.test_league_views import _legal_squad, _member_picks, _Provider, _world_context

import squadopt.application.top100_weight as top100_module
from squadopt.application.advice import (
    TOP100_LIMIT,
    AdviseEntryRequest,
    advise_with_managers_word,
    advise_with_top100,
    net_expected_points,
    solve_member_control,
)
from squadopt.application.entries import EntryError, EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.application.manager_words import ManagerWord, ManagerWords
from squadopt.application.strategies.catalog import (
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
    PUBLISHABLE_FIELDS,
)
from squadopt.application.top100_weight import (
    PUBLISHED_PLAN_CARRIES_TOP100,
    TOP100_INPUTS_REFUSED,
    TOP100_WEIGHTS,
    Top100Counts,
    Top100InputsRefused,
    base_net,
    base_points,
    decision_changed,
    load_top100_counts,
    rebased_week,
    validate_top100_weight,
    weighted_projection,
)
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


#: Two players the member's pure-points plan leaves out: a forward the member holds and
#: sells, and a midfielder nobody holds. At weight 50 the member keeps the forward and
#: buys the midfielder, which the base model scores lower.
PREFERRED = [1017, 1020]


def _favoured(projection: Any, squad: list[int]) -> list[int]:
    """Eleven players the member does not hold, highest projected first, then any others."""

    table = projection.table.sort_values(["expected_points", "player_id"], ascending=[False, True])
    outside = [int(p) for p in table["player_id"] if int(p) not in squad]
    inside = [int(p) for p in table["player_id"] if int(p) in squad]
    return (outside + inside)[:11]


def _counts(favoured: list[int], **overrides: object) -> Top100Counts:
    fields: dict[str, Any] = {
        "counts": {player: 100 for player in favoured},
        "table_sha256": "a" * 64,
        "cohort_snapshot_id": "fpl-top100-20260827T080000Z-000000000000",
        "picks_snapshot_id": "fpl-elite-picks-20260827T080100Z-111111111111",
        "picks_gameweek": 1,
    }
    fields.update(overrides)
    return Top100Counts(**fields)


def _artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inputs: Any,
    projection: Any,
    favoured: list[int],
    **row_overrides: object,
) -> Path:
    """A verified-looking evidence pair: the favoured eleven at full support."""

    rows = []
    for player in sorted(int(p) for p in projection.table["player_id"]):
        count = 100 if player in favoured else 0
        rows.append(
            {
                "season": inputs.season,
                "target_gameweek": int(inputs.deadline.gameweek),
                "captured_at_utc": inputs.captured_at_utc,
                "deadline_timestamp_utc": inputs.deadline.deadline_utc,
                "player_id": player,
                "elite_cohort_size": 100,
                "elite_members_observed": 100,
                "elite_start_count_lag1": count,
                "elite_start_share_lag1": count / 100,
                "elite_evidence_observed": True,
                **row_overrides,
            }
        )
    evidence = pd.DataFrame(rows)
    evidence.attrs.update(
        {
            "elite_members_missing_picks": 0,
            "unmapped_picked_elements": (),
            "table_sha256": "c" * 64,
            "generated_at_utc": inputs.captured_at_utc,
            "cohort_snapshot_id": "fpl-top100-20260827T080000Z-000000000000",
        }
    )
    monkeypatch.setattr(top100_module, "read_player_evidence_artifact", lambda *_: evidence)
    table = tmp_path / "player_evidence_v1_2026-27_gw02_top100_111111111111.csv"
    table.write_text("unused\n", encoding="utf-8")
    (tmp_path / "player_evidence_v1_2026-27_gw02_top100_111111111111.manifest.json").write_text(
        json.dumps(
            {
                "source_snapshot_ids": [
                    "fpl-elite-picks-20260827T080100Z-111111111111",
                    "fpl-top100-20260827T080000Z-000000000000",
                ]
            }
        ),
        encoding="utf-8",
    )
    return table


def _words(player: int) -> ManagerWords:
    return ManagerWords(
        season="2026-27",
        gameweek=2,
        source_kind="synthetic_fixture",
        source_label="club_news_v1.fixture.json",
        evidence_table="rotation_evidence_v2_2026-27_gw02.csv",
        clubs_covered=("Club 1",),
        words=(
            ManagerWord(
                player_id=player,
                disposition="stated_expected_absent",
                speaker="the manager",
                published_at_utc="2026-08-21T10:00:00Z",
                published_precision="instant",
                club="Club 1",
                source_url="https://club.example/club-1/news",
                fetched_at_utc="2026-08-22T11:00:00Z",
                words="He will not travel.",
            ),
        ),
    )


# -- the weight -------------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False, 20.0, "20", 15, 60, -5, None])
def test_only_the_offered_weights_are_accepted(value: object) -> None:
    with pytest.raises(EntryError):
        validate_top100_weight(value)


def test_every_offered_weight_is_accepted() -> None:
    assert TOP100_WEIGHTS == (0, 5, 10, 20, 30, 40, 50)
    for weight in TOP100_WEIGHTS:
        assert validate_top100_weight(weight) == weight


def test_the_weight_scales_points_by_its_count_and_nothing_else(world: dict[str, Any]) -> None:
    _inputs, projection, _rules = _world_context(world)
    before = projection.table.copy(deep=True)
    players = [int(p) for p in projection.table["player_id"]]
    counts = {players[0]: 100, players[1]: 40}

    unchanged = weighted_projection(projection, counts, 0)
    pd.testing.assert_frame_equal(unchanged.table, projection.table)

    weighted = weighted_projection(projection, counts, 50)
    pd.testing.assert_frame_equal(projection.table, before)
    by_id = dict(zip(weighted.table["player_id"], weighted.table["expected_points"], strict=True))
    base = dict(zip(before["player_id"], before["expected_points"], strict=True))
    assert by_id[players[0]] == pytest.approx(base[players[0]] * 1.5, abs=1e-12)
    assert by_id[players[1]] == pytest.approx(base[players[1]] * 1.2, abs=1e-12)
    for player in players[2:]:
        assert by_id[player] == base[player]
    other = [c for c in before.columns if c != "expected_points"]
    pd.testing.assert_frame_equal(weighted.table[other], before[other])
    assert weighted.diagnostics["top100_weight"] == 50
    assert "top100_base_point_ratios" not in weighted.diagnostics


def test_a_player_projected_at_zero_stays_at_zero(world: dict[str, Any]) -> None:
    _inputs, projection, _rules = _world_context(world)
    player = int(projection.table["player_id"].iloc[0])
    table = projection.table.copy(deep=True)
    table.loc[table["player_id"] == player, "expected_points"] = 0.0
    zeroed = replace(projection, table=table)
    weighted = weighted_projection(zeroed, {player: 100}, 50)
    row = weighted.table.loc[weighted.table["player_id"] == player, "expected_points"]
    assert float(row.iloc[0]) == 0.0


# -- the base-model arithmetic ----------------------------------------------------------


def test_base_scoring_of_a_plan_is_the_planners_own_net(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    control = solve_member_control(picks, inputs, projection, rules)
    points = base_points(projection)
    week = control.plan.weeks[0]
    assert base_net(week, points) == pytest.approx(net_expected_points(control.plan), abs=1e-9)

    weighted = weighted_projection(projection, dict.fromkeys(points, 100), 50)
    preferred = solve_member_control(picks, inputs, weighted, rules)
    rebased = rebased_week(preferred.plan.weeks[0], points)
    for frame in (rebased.selected_squad, rebased.starting_xi, rebased.bench):
        for player, value in zip(frame["player_id"], frame["expected_points"], strict=True):
            assert value == points[int(player)]
    assert rebased.captain["expected_points"] == points[int(rebased.captain["player_id"])]
    assert rebased.projected_score == pytest.approx(
        base_net(preferred.plan.weeks[0], points) + preferred.plan.weeks[0].transfer_hit_points
    )
    assert not decision_changed(week, control.decision, week, control.decision)


# -- the gate ---------------------------------------------------------------------------


def test_the_counts_pass_the_handoffs_own_gate(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, projection, _rules = _world_context(world)
    favoured = _favoured(projection, _legal_squad(world))
    table = _artifact(tmp_path, monkeypatch, inputs, projection, favoured)
    counts = load_top100_counts(table, inputs=inputs, projection=projection)
    assert counts.counts == dict.fromkeys(favoured, 100)
    assert counts.picks_snapshot_id == "fpl-elite-picks-20260827T080100Z-111111111111"
    assert counts.cohort_snapshot_id == "fpl-top100-20260827T080000Z-000000000000"
    assert counts.picks_gameweek == 1
    assert counts.table_sha256 == "c" * 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"captured_at_utc": "2026-08-27T09:00:01Z"},
        {"target_gameweek": 3},
        {"deadline_timestamp_utc": "2026-08-28T18:30:00Z"},
        {"elite_members_observed": 99},
        {"elite_evidence_observed": False},
    ],
)
def test_counts_the_gate_refuses_turn_the_menu_off(
    world: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    inputs, projection, _rules = _world_context(world)
    table = _artifact(
        tmp_path, monkeypatch, inputs, projection, _favoured(projection, []), **overrides
    )
    with pytest.raises(Top100InputsRefused) as refusal:
        load_top100_counts(table, inputs=inputs, projection=projection)
    assert refusal.value.reason == TOP100_INPUTS_REFUSED


def test_counts_that_do_not_add_up_to_eleven_starters_each_are_refused(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, projection, _rules = _world_context(world)
    table = _artifact(tmp_path, monkeypatch, inputs, projection, _favoured(projection, [])[:10])
    with pytest.raises(Top100InputsRefused):
        load_top100_counts(table, inputs=inputs, projection=projection)


def test_evidence_generated_after_the_capture_is_refused(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, projection, _rules = _world_context(world)
    table = _artifact(tmp_path, monkeypatch, inputs, projection, _favoured(projection, []))
    evidence = top100_module.read_player_evidence_artifact(table, table)
    evidence.attrs["generated_at_utc"] = "2026-08-27T09:00:01Z"
    with pytest.raises(Top100InputsRefused):
        load_top100_counts(table, inputs=inputs, projection=projection)


def test_missing_picks_are_refused(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, projection, _rules = _world_context(world)
    table = _artifact(tmp_path, monkeypatch, inputs, projection, _favoured(projection, []))
    evidence = top100_module.read_player_evidence_artifact(table, table)
    evidence.attrs["elite_members_missing_picks"] = 1
    with pytest.raises(Top100InputsRefused):
        load_top100_counts(table, inputs=inputs, projection=projection)


def test_a_projection_that_already_carries_the_uplift_is_refused(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, projection, _rules = _world_context(world)
    table = _artifact(tmp_path, monkeypatch, inputs, projection, _favoured(projection, []))
    uplifted = replace(
        projection,
        diagnostics={**projection.diagnostics, "projection_evidence_fingerprint": "f" * 64},
    )
    with pytest.raises(Top100InputsRefused) as refusal:
        load_top100_counts(table, inputs=inputs, projection=uplifted)
    assert refusal.value.reason == PUBLISHED_PLAN_CARRIES_TOP100


def test_a_manifest_naming_no_picks_capture_is_refused(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs, projection, _rules = _world_context(world)
    table = _artifact(tmp_path, monkeypatch, inputs, projection, _favoured(projection, []))
    top100_module.top100_manifest_path(table).write_text(
        json.dumps({"source_snapshot_ids": ["fpl-top100-20260827T080000Z-000000000000"]}),
        encoding="utf-8",
    )
    with pytest.raises(Top100InputsRefused):
        load_top100_counts(table, inputs=inputs, projection=projection)


# -- the weighted document ----------------------------------------------------------------


def _advise(world: dict[str, Any], weight: int, *, words: ManagerWords | None = None) -> Any:
    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    picks = _member_picks(world, 101, squad)
    provider = _Provider({101: picks})
    control = solve_member_control(picks, inputs, projection, rules)
    advice = advise_with_top100(
        _request(),
        weight=weight,
        counts=_counts(PREFERRED),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        control=control,
        words=words,
    )
    return advice, control, (inputs, projection, rules, picks, provider)


def test_a_weighted_document_publishes_the_weighted_decision_at_base_points(
    world: dict[str, Any],
) -> None:
    advice, control, (inputs, projection, rules, picks, _provider) = _advise(world, 50)
    payload = advice.payload
    points = base_points(projection)
    weighted = weighted_projection(projection, _counts(PREFERRED).counts, 50)
    preferred = solve_member_control(picks, inputs, weighted, rules)
    week = preferred.plan.weeks[0]

    assert payload["mode"] == "saf-puan" and payload["window"] == 1
    assert payload["captain"]["player_id"] == int(week.captain["player_id"])
    assert {p["player_id"] for p in payload["starting_xi"]} == {
        int(p) for p in week.starting_xi["player_id"]
    }
    assert sorted(m["player_in"]["player_id"] for m in payload["moves"]) == sorted(
        preferred.decision.transfers_in_ids
    )
    for player in [*payload["starting_xi"], *payload["bench"], payload["captain"]]:
        assert player["expected_points"] == points[player["player_id"]]
    assert payload["expected_own_points"] == pytest.approx(
        base_net(week, points) + week.transfer_hit_points
    )

    control_value = base_net(control.plan.weeks[0], points)
    selected = base_net(week, points)
    assert payload["expected_points_cost"] == pytest.approx(max(control_value, selected) - selected)
    assert payload["expected_points_cost"] >= 0
    assert payload["expected_points_cost_ceiling"] >= payload["expected_points_cost"]
    if control.plan.solver_status.name == "OPTIMAL":
        assert payload["expected_points_cost_ceiling"] == payload["expected_points_cost"]
    assert payload["optimality_gap"] is None
    assert payload["control_solver_status"] == control.plan.solver_status.name
    assert payload["top100"] == {
        "weight": 50,
        "changed": decision_changed(
            control.plan.weeks[0], control.decision, week, preferred.decision
        ),
        "price_basis": "base_model_pure_points_v1",
        "cohort_snapshot_id": "fpl-top100-20260827T080000Z-000000000000",
        "picks_snapshot_id": "fpl-elite-picks-20260827T080100Z-111111111111",
        "table_sha256": "a" * 64,
        "picks_gameweek": 1,
    }
    assert payload["stated_limits"][-1] == TOP100_LIMIT.format(weight=50)
    assert set(payload) - ENVELOPE <= PUBLISHABLE_FIELDS
    assert not any(str(key).startswith("_") for key in payload)
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


def test_the_favoured_players_move_the_plan_and_the_moves_say_why(world: dict[str, Any]) -> None:
    advice, control, _context = _advise(world, 50)
    payload = advice.payload
    assert payload["top100"]["changed"] is True
    reasons = {move["reason_code"] for move in payload["moves"]}
    assert "top100_preference" in reasons
    assert "manager_word" not in reasons
    control_ins = set(control.decision.transfers_in_ids)
    for move in payload["moves"]:
        if move["reason_code"] == "top100_preference":
            assert move["player_in"]["player_id"] not in control_ins or (
                move["player_out"]["player_id"] not in control.decision.transfers_out_ids
            )


def test_weight_zero_and_other_strategies_are_refused(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    provider = _Provider({101: picks})
    counts = _counts(PREFERRED)
    for request, weight in (
        (_request(), 0),
        (replace(_request(), window=3), 20),
        (replace(_request(), strategy="ortak-koru", rival_entry_id=202), 20),
    ):
        with pytest.raises(EntryError):
            advise_with_top100(
                request,
                weight=weight,
                counts=counts,
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
            )


def test_with_the_word_the_price_is_the_pairs_and_the_word_still_binds(
    world: dict[str, Any],
) -> None:
    _inputs, projection, _rules = _world_context(world)
    squad = _legal_squad(world)
    favoured = _favoured(projection, squad)
    words = _words(squad[0])
    advice, _control, _context = _advise(world, 50, words=words)
    payload = advice.word_payload
    assert payload is not None and advice.word_unavailable == ""
    assert payload["evidence"]["kind"] == "managers_word"
    assert squad[0] not in {p["player_id"] for p in payload["starting_xi"]}
    assert payload["captain"]["player_id"] != squad[0]
    assert payload["vice_captain"]["player_id"] != squad[0]
    assert payload["top100"]["weight"] == 50
    assert payload["expected_points_cost_ceiling"] >= payload["expected_points_cost"]
    # The plain weighted document is untouched by the word.
    assert "evidence" not in advice.payload
    assert favoured  # the counts favoured someone


def test_at_weight_zero_the_pair_price_is_the_words_own(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The combined price is the word's price when the weight is zero; pinned here by
    letting the weighted path run at zero, which the public call refuses."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    picks = _member_picks(world, 101, squad)
    provider = _Provider({101: picks})
    words = _words(squad[0])
    word = advise_with_managers_word(
        _request(),
        words=words,
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    import squadopt.application.advice as advice_module

    monkeypatch.setattr(advice_module, "validate_top100_weight", lambda value: 1)
    monkeypatch.setattr(advice_module, "weighted_projection", lambda base, counts, weight: base)
    zero = advise_with_top100(
        _request(),
        weight=0,
        counts=_counts(PREFERRED),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        words=words,
    ).word_payload
    assert zero is not None
    for key in (
        "expected_points_cost",
        "expected_points_cost_ceiling",
        "captain",
        "vice_captain",
        "starting_xi",
        "moves",
        "evidence",
        "expected_own_points",
        "expected_gain_vs_hold",
    ):
        assert zero[key] == word[key], key


def test_member_documents_carry_no_forbidden_text(world: dict[str, Any]) -> None:
    squad = _legal_squad(world)
    advice, _control, _context = _advise(world, 20, words=_words(squad[0]))

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

    walk(advice.payload, "plain")
    walk(advice.word_payload, "word")


# -- publication ------------------------------------------------------------------------


def _publish(
    world: dict[str, Any],
    out: Path,
    *,
    counts: Top100Counts | None,
    words: ManagerWords | None = None,
    reason: str | None = None,
    squads: dict[int, list[int]] | None = None,
) -> Any:
    inputs, projection, rules = _world_context(world)
    squads = squads or {101: _legal_squad(world)}
    provider = _Provider(
        {entry: _member_picks(world, entry, squad) for entry, squad in squads.items()}
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
        manager_words=words,
        top100_counts=counts,
        top100_unavailable_reason=reason,
    )


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def test_the_menu_is_published_beside_the_baseline_and_named_in_the_index(
    world: dict[str, Any], tmp_path: Path
) -> None:
    squad = _legal_squad(world)
    counts = _counts(PREFERRED)
    words = _words(squad[0])
    _publish(world, tmp_path / "plain", counts=None, words=words)
    report = _publish(world, tmp_path / "menu", counts=counts, words=words)

    directory = tmp_path / "menu" / "advice" / "101" / "saf-puan" / "1"
    names = sorted(path.name for path in directory.iterdir())
    assert names == sorted(
        [
            "hoca-sozu.json",
            *(f"top100-{w}.json" for w in TOP100_WEIGHTS if w),
            *(f"top100-{w}-hoca-sozu.json" for w in TOP100_WEIGHTS if w),
        ]
    )
    assert not any(name.startswith("top100-0") for name in names)
    for relative in ("advice/101/saf-puan/1.json", "advice/101/saf-puan/1/hoca-sozu.json"):
        plain = _read(tmp_path / "plain" / relative)
        menu = _read(tmp_path / "menu" / relative)
        assert plain == menu, relative

    index = _read(tmp_path / "menu" / "advice" / "101" / "index.json")
    assert index["top100"]["available"] is True
    assert index["top100"]["published_weight"] == 0
    assert index["top100"]["weights"] == list(TOP100_WEIGHTS)
    assert index["top100"]["paths"] == {
        str(w): f"advice/101/saf-puan/1/top100-{w}.json" for w in TOP100_WEIGHTS if w
    }
    assert index["top100"]["word_paths"] == {
        str(w): f"advice/101/saf-puan/1/top100-{w}-hoca-sozu.json" for w in TOP100_WEIGHTS if w
    }
    assert index["top100"]["unavailable"] == []
    assert index["top100"]["source"] == counts.source_record()
    for key in index["top100"]:
        assert not FORBIDDEN_FIELD_PATTERN.search(key)
    for weight in (5, 50):
        document = _read(directory / f"top100-{weight}.json")
        assert document["top100"]["weight"] == weight
    assert report.members[0].rendered


def test_without_counts_the_index_says_why_and_old_files_go(
    world: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "tree"
    _publish(world, out, counts=_counts(PREFERRED))
    assert (out / "advice/101/saf-puan/1/top100-20.json").is_file()

    report = _publish(world, out, counts=None, reason=TOP100_INPUTS_REFUSED)
    index = _read(out / "advice/101/index.json")
    assert index["top100"] == {"available": False, "reason": TOP100_INPUTS_REFUSED}
    assert not (out / "advice/101/saf-puan/1").exists()
    assert "advice/101/saf-puan/1/top100-20.json" in report.removed

    _publish(world, out, counts=None)
    assert _read(out / "advice/101/index.json")["top100"] == {
        "available": False,
        "reason": "no_top100_this_run",
    }


def test_a_weighted_document_is_invariant_to_every_other_member(
    world: dict[str, Any], tmp_path: Path
) -> None:
    squad = _legal_squad(world)
    counts = _counts(PREFERRED)
    other = [*squad[:-1], 1023]
    _publish(world, tmp_path / "alone", counts=counts)
    _publish(world, tmp_path / "pair", counts=counts, squads={101: squad, 102: other})
    for weight in (5, 20, 50):
        relative = f"advice/101/saf-puan/1/top100-{weight}.json"
        assert _read(tmp_path / "alone" / relative) == _read(tmp_path / "pair" / relative)


def test_a_weight_that_fails_is_recorded_not_fatal(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import squadopt.application.league_views as views

    real = views.advise_with_top100

    def flaky(*args: Any, **kwargs: Any) -> Any:
        if kwargs["weight"] == 30:
            raise EntryError("no plan at this setting")
        return real(*args, **kwargs)

    monkeypatch.setattr(views, "advise_with_top100", flaky)
    report = _publish(world, tmp_path, counts=_counts(PREFERRED))
    index = _read(tmp_path / "advice/101/index.json")
    assert "30" not in index["top100"]["paths"]
    assert index["top100"]["unavailable"] == [
        {"weight": 30, "word": False, "reason": "not_solved_for_member"}
    ]
    assert "Top 100 influence 30 not solved: no plan at this setting" in report.members[0].reason
