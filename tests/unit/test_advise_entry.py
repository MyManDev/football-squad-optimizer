"""advise_entry: a wire-shaped request, injected collaborators, the same bytes."""

import dataclasses
import json
from pathlib import Path
from typing import Any, get_type_hints

import pytest
import tests.unit.test_league_views as league_views_tests
import tests.unit.test_live_transfers as world_module
from tests.unit.test_league_views import (
    _legal_squad,
    _member_picks,
    _Provider,
    _world_context,
)

from squadopt.application import advice as advice_service
from squadopt.application.advice import AdviseEntryRequest, advise_entry
from squadopt.application.entries import EntryError, EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.optimization import SolverStatus

world = league_views_tests.world  # re-register the fixture in this module


def _request(**overrides: object) -> AdviseEntryRequest:
    fields: dict[str, object] = {
        "season": "2026-27",
        "gameweek": 2,
        "league_id": 352490,
        "entry_id": 101,
    }
    fields.update(overrides)
    return AdviseEntryRequest(**fields)  # type: ignore[arg-type]


def test_the_request_carries_no_path_anywhere() -> None:
    """DecideRequest carries filesystem paths because it is an operator command; a
    request that will travel over a network boundary must not."""

    hints = get_type_hints(AdviseEntryRequest)
    for name, annotation in hints.items():
        assert "Path" not in str(annotation), (name, annotation)
    assert not any(
        isinstance(field.default, Path) for field in dataclasses.fields(AdviseEntryRequest)
    )


def test_the_request_is_validated() -> None:
    with pytest.raises(EntryError, match="season"):
        _request(season=" ")
    with pytest.raises(EntryError, match="gameweek"):
        _request(gameweek=0)
    with pytest.raises(EntryError, match="entry_id"):
        _request(entry_id=-1)
    with pytest.raises(EntryError, match="rival_entry_id"):
        _request(rival_entry_id=0)


def test_advise_entry_produces_the_builders_bytes(world: dict[str, Any], tmp_path: Path) -> None:
    """The pure call and the batch builder agree byte for byte on the same member.

    The builder is the caller of ``advise_entry`` now, so this is close to a tautology —
    which is the point: the service path and the static path cannot drift, because they
    are one function.
    """

    import datetime

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    provider = _Provider({101: _member_picks(world, 101, squad)})
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    build_league_views(
        provider,
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "site",
        now=when,
    )
    published = json.loads(
        (tmp_path / "site" / "advice" / "101" / "saf-puan" / "1.json").read_text(encoding="utf-8")
    )["payload"]

    direct = advise_entry(
        _request(),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )

    assert direct == published


def test_uncomputed_combinations_are_refused_not_faked(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    provider = _Provider({101: _member_picks(world, 101, _legal_squad(world))})

    def call(request: AdviseEntryRequest) -> dict[str, object]:
        return advise_entry(
            request, provider=provider, inputs=inputs, projection=projection, rules=rules
        )

    with pytest.raises(EntryError, match="needs a rival"):
        call(_request(strategy="fark-yarat"))
    with pytest.raises(EntryError, match="not computed"):
        call(_request(window=2))
    # A saf-puan window is computed, but only from the capture's horizon builder.
    with pytest.raises(EntryError, match="horizon builder"):
        call(_request(window=3))
    with pytest.raises(EntryError, match="window 1 only"):
        call(_request(strategy="fark-yarat", rival_entry_id=202, window=5))
    with pytest.raises(EntryError, match="not in the catalogue"):
        call(_request(strategy="kaptan-taklidi"))
    with pytest.raises(EntryError, match="not wired"):
        call(_request(strategy="kaptan-ayris", rival_entry_id=202))
    with pytest.raises(EntryError, match="rival-free"):
        call(_request(rival_entry_id=202))
    with pytest.raises(EntryError, match="own rival"):
        call(_request(strategy="fark-yarat", rival_entry_id=101))
    with pytest.raises(EntryError, match="not the capture's"):
        call(_request(gameweek=7))
    with pytest.raises(EntryError, match="not the capture's"):
        call(_request(season="2025-26"))


def test_the_payload_carries_the_whole_decision(world: dict[str, Any]) -> None:
    """Transfers alone are not a gameweek: captain, vice-captain, eleven, bench order and
    chip travel with the moves, all in expected points, completed by the scorer's rule."""

    from squadopt.planning import CHIP_NAMES

    inputs, projection, rules = _world_context(world)
    provider = _Provider({101: _member_picks(world, 101, _legal_squad(world))})
    payload = advise_entry(
        _request(), provider=provider, inputs=inputs, projection=projection, rules=rules
    )
    eleven = payload["starting_xi"]
    bench = payload["bench"]
    captain = payload["captain"]
    vice = payload["vice_captain"]
    assert isinstance(eleven, list) and len(eleven) == 11
    assert isinstance(bench, list) and len(bench) == 4
    assert isinstance(captain, dict) and isinstance(vice, dict)
    eleven_ids = [player["player_id"] for player in eleven]
    bench_ids = [player["player_id"] for player in bench]
    assert len(set(eleven_ids) | set(bench_ids)) == 15
    assert captain["player_id"] in eleven_ids
    assert vice["player_id"] in eleven_ids and vice["player_id"] != captain["player_id"]
    # The vice-captain is the eleven's next-highest expected points; the bench is the
    # goalkeeper first, then outfield by descending expected points — the scorer's rule.
    others = [p for p in eleven if p["player_id"] != captain["player_id"]]
    assert vice["expected_points"] == max(p["expected_points"] for p in others)
    assert bench[0]["position"] == "GK"
    outfield = [p["expected_points"] for p in bench[1:]]
    assert outfield == sorted(outfield, reverse=True)
    positions = [p["position"] for p in eleven]
    assert positions == sorted(positions, key=("GK", "DEF", "MID", "FWD").index)
    assert payload["chip"] is None or payload["chip"] in CHIP_NAMES
    assert payload["expected_own_points"] == pytest.approx(
        sum(p["expected_points"] for p in eleven) + captain["expected_points"]
    )


def test_a_rival_strategy_carries_the_decision_and_agrees_with_its_own_captain_label(
    world: dict[str, Any],
) -> None:
    inputs, projection, rules = _world_context(world)
    rival = _rival_squad(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, rival),
        }
    )
    payload = advise_entry(
        _request(strategy="fark-yarat", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    captain = payload["captain"]
    assert isinstance(captain, dict) and len(payload["starting_xi"]) == 11
    rival_captain = provider.picks(202, "2026-27", 1).captain
    assert payload["captain_agreement"] == (captain["player_id"] == rival_captain)
    assert isinstance(payload["expected_own_points"], float)


def test_a_decision_without_its_week_publishes_no_lineup(world: dict[str, Any]) -> None:
    """A menu entry handed over without its plan week gets null lineup fields, never an
    invented eleven."""

    from squadopt.application.advice import build_advice_payload
    from squadopt.application.entries import held_squad_from_picks

    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    _plan, decision, _config = advice_service.plan_transfers(inputs, projection, held, rules)
    payload = build_advice_payload(
        picks, inputs, projection, rules, league_id=352490, mode="garantici", decision=decision
    )
    for name in ("expected_own_points", "captain", "vice_captain", "starting_xi", "bench", "chip"):
        assert payload[name] is None


def _rival_squad(world: dict[str, Any]) -> list[int]:
    # Only the first eleven (the public XI) matters to the band. It is arranged to
    # share exactly six players with the member's fifteen, so the differential band
    # (overlap <= 5) is one same-position swap away — reachable within the world's
    # budget and club caps, and the constraint still has to bind for the test to mean
    # anything.
    codes = [1004, 1005, 1006, 1012, 1013, 1014]  # shared with the member
    codes += [1003, 1009, 1017, 1018, 1019]  # outsiders completing the eleven
    codes += [1010, 1011, 1023, 1024]  # bench, outside the band
    return codes


def test_a_rival_strategy_computes_against_the_named_rival(world: dict[str, Any]) -> None:
    """fark-yarat with a rival: banded plan, price tag, and only publishable fields."""

    inputs, projection, rules = _world_context(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, _rival_squad(world)),
        }
    )
    payload = advise_entry(
        _request(strategy="fark-yarat", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    assert payload["mode"] == "fark-yarat"
    assert payload["rival_entry_id"] == 202
    assert payload["rival_label"] == "entry-202"
    # The band held: at most five of the rival's eleven in the decided fifteen.
    overlap = payload["overlap_count"]
    assert isinstance(overlap, int) and 0 <= overlap <= 5
    # The price tag is the control's expected points minus the banded plan's — a
    # constraint can only cost, never pay.
    cost = payload["expected_points_cost"]
    assert isinstance(cost, float) and cost >= 0.0
    # The gap is a mean in expected points; its spread is not computed, and no
    # probability-shaped field exists anywhere in the payload.
    assert isinstance(payload["expected_gap_vs_rival"], float)
    assert isinstance(payload["captain_agreement"], bool)
    assert payload["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert not any("probab" in key or key.startswith("p_") for key in payload)


def test_a_rival_missing_from_the_projection_is_refused_not_scored_as_zero(
    world: dict[str, Any],
) -> None:
    inputs, projection, rules = _world_context(world)
    rival = _rival_squad(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, rival),
        }
    )
    incomplete = dataclasses.replace(
        projection,
        table=projection.table.loc[projection.table["player_id"] != rival[0]].reset_index(
            drop=True
        ),
    )

    with pytest.raises(EntryError, match="cannot treat missing players as zero"):
        advise_entry(
            _request(strategy="fark-yarat", rival_entry_id=202),
            provider=provider,
            inputs=inputs,
            projection=incomplete,
            rules=rules,
        )


def test_an_unproven_control_is_published_with_its_own_account(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A control the solver found but could not prove still anchors the price tag —
    the tag then carries the control's status and bound gap beside it, instead of the
    member vanishing from the rival strategies."""

    inputs, projection, rules = _world_context(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, _rival_squad(world)),
        }
    )
    original = advice_service.plan_transfers

    def feasible_control(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
        plan, decision, config = original(*args, **kwargs)
        return (
            dataclasses.replace(
                plan,
                solver_status=SolverStatus.FEASIBLE,
                diagnostics={**dict(plan.diagnostics), "absolute_optimality_gap": 0.75},
            ),
            decision,
            config,
        )

    monkeypatch.setattr(advice_service, "plan_transfers", feasible_control)

    payload = advise_entry(
        _request(strategy="fark-yarat", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    assert payload["control_solver_status"] == "FEASIBLE"
    assert payload["control_optimality_gap"] == 0.75
    assert isinstance(payload["expected_points_cost"], float)


def test_a_precomputed_control_gives_the_same_bytes(world: dict[str, Any]) -> None:
    """The batch solves each member's control once and renders the whole rival menu
    from it; the answer must be byte-identical to the per-request solve."""

    from squadopt.application.advice import solve_member_control

    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    provider = _Provider({101: picks, 202: _member_picks(world, 202, _rival_squad(world))})
    control = solve_member_control(picks, inputs, projection, rules)
    for request in (_request(), _request(strategy="fark-yarat", rival_entry_id=202)):
        direct = advise_entry(
            request, provider=provider, inputs=inputs, projection=projection, rules=rules
        )
        reused = advise_entry(
            request,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            control=control,
        )
        assert json.dumps(reused, sort_keys=True) == json.dumps(direct, sort_keys=True)
    # Another member's control is refused, not silently used.
    other = dataclasses.replace(control, picks=dataclasses.replace(picks, entry_id=202))
    with pytest.raises(EntryError, match="solved for entry 202"):
        advise_entry(
            _request(),
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            control=other,
        )


def test_the_price_tag_and_the_gap_are_net_of_hits(world: dict[str, Any]) -> None:
    """A band that forces paid transfers costs those hits: the tag is the control's
    points minus its hits against the banded plan's points minus its hits, and the gap
    against the rival subtracts the plan's own hits."""

    from squadopt.application.advice import net_expected_points, solve_member_control
    from squadopt.application.entries import held_squad_from_picks
    from squadopt.live import plan_transfers_with_overlap
    from squadopt.planning import FirstWeekOverlap

    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    rival = _member_picks(world, 202, _rival_squad(world))
    provider = _Provider({101: picks, 202: rival})
    payload = advise_entry(
        _request(strategy="fark-yarat", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    control = solve_member_control(picks, inputs, projection, rules)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    band = FirstWeekOverlap(player_ids=frozenset(rival.starting_xi), minimum=None, maximum=5)
    plan, _decision, _config = plan_transfers_with_overlap(inputs, projection, held, rules, band)
    assert payload["expected_points_cost"] == pytest.approx(
        net_expected_points(control.plan) - net_expected_points(plan)
    )
    expected = {
        int(str(row["player_id"])): float(str(row["expected_points"]))
        for _, row in projection.table.iterrows()
    }
    rival_expected = sum(expected[p] for p in rival.starting_xi) + expected[rival.captain]
    own = payload["expected_own_points"]
    assert isinstance(own, float)
    assert payload["expected_gap_vs_rival"] == pytest.approx(
        own - float(plan.total_transfer_hit_points or 0.0) - rival_expected
    )


def test_a_member_is_shown_the_games_charge_never_the_planning_margin(
    world: dict[str, Any],
) -> None:
    """The one number a member reads about a hit is the four points the game takes.

    ``MEMBER_PLANNING_POLICY`` prices a paid transfer at 8 inside the solve — a caution
    margin on a projection that overstates transfer gains — and at the game's 4 in every
    number that leaves it. This member's plan pays one hit, so the two would differ if
    the margin leaked: through the plan, the decision the ledger records, the advice
    payload's ``transfer_hit_points``, and ``net_expected_points``, which decides
    between two solved plans and must therefore compare at what is actually docked.

    The charge is stated once, on the week. This member's plan makes two transfers and
    pays for one of them, so a per-move copy of the week's charge would show a reader
    two rows of 4 for a week the game docks 4 once.
    """

    from squadopt.application.advice import net_expected_points, solve_member_control
    from squadopt.live.transfers import MEMBER_PLANNING_POLICY

    margin = MEMBER_PLANNING_POLICY["transfer_hit_cost_points"]
    charge = MEMBER_PLANNING_POLICY["hit_points_charged"]
    assert isinstance(margin, float) and isinstance(charge, float) and margin > charge

    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    control = solve_member_control(picks, inputs, projection, rules)
    week = control.plan.weeks[0]

    assert control.transfer_config.transfer_hit_cost_points == margin
    assert control.transfer_config.hit_points_charged == charge
    assert week.paid_transfer_count == 1, "the pin is vacuous unless a hit is paid"
    assert week.transfer_hit_points == charge
    assert control.plan.total_transfer_hit_points == charge
    assert control.decision.transfer_hit_points == charge
    assert control.decision.transfer_hit_cost_points == charge
    assert net_expected_points(control.plan) == pytest.approx(
        float(control.plan.total_projected_score or 0.0) - charge
    )

    payload = advise_entry(
        _request(),
        provider=_Provider({101: picks}),
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    moves = payload["moves"]
    assert isinstance(moves, list) and len(moves) == 2
    assert payload["transfer_hit_points"] == charge
    assert not any("expected_points_cost" in move for move in moves)


def _club_legal_squad(world: dict[str, Any]) -> list[int]:
    """A fifteen the game would accept as held: 2/5/5/3, at most three per club, nobody
    unavailable — so one free transfer is a real budget rather than an impossibility."""

    inputs, projection, _ = _world_context(world)
    unavailable = set(projection.unavailable_players)
    quotas = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    per_club: dict[str, int] = {}
    chosen: list[int] = []
    rows = inputs.players.sort_values("player_id")
    for position, quota in quotas.items():
        taken = 0
        for _, row in rows.loc[rows["position"] == position].iterrows():
            player = int(str(row["player_id"]))
            club = str(row["team_id"])
            if player in unavailable or per_club.get(club, 0) >= 3:
                continue
            chosen.append(player)
            per_club[club] = per_club.get(club, 0) + 1
            taken += 1
            if taken == quota:
                break
        assert taken == quota, (position, taken)
    return chosen


def test_a_rival_strategy_spends_the_free_transfers_before_it_spends_hits(
    world: dict[str, Any],
) -> None:
    """Every extra transfer costs four points; a one-week band is not worth buying. The
    strategy solves the band within the free transfers (the band relaxed to what they
    reach) and again at its target with hits, keeps the higher net expected points, and
    publishes the other as the alternative with its price."""

    inputs, projection, rules = _world_context(world)
    squad = _club_legal_squad(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, squad),
            202: _member_picks(world, 202, _rival_squad(world)),
        }
    )
    payload = advise_entry(
        _request(strategy="ortak-koru", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    assert payload["transfer_cap"] == 1  # the public endpoints show no banked transfer
    assert payload["overlap_target"] == 9
    applied = payload["overlap_applied"]
    assert isinstance(applied, int) and 1 <= applied <= 9
    assert payload["plan_kind"] in {"within_free_transfers", "with_hits"}
    hits = float(str(payload["transfer_hit_points"]))
    if payload["plan_kind"] == "within_free_transfers":
        assert len(payload["moves"]) <= 1 and hits == 0.0
        alternative = payload["alternative_plan"]
        if alternative is not None:
            assert alternative["kind"] == "with_hits"
            assert alternative["overlap_applied"] == 9
            assert alternative["transfer_hit_points"] >= 0.0
    else:
        assert applied == 9
        alternative = payload["alternative_plan"]
        assert alternative is None or alternative["kind"] == "within_free_transfers"


def test_a_squad_that_needs_transfers_to_be_legal_falls_back_to_the_hit_plan(
    world: dict[str, Any],
) -> None:
    """This world's shared 'legal' fifteen holds four from one club: the planner needs two
    transfers before any band applies, so nothing is reachable within one free transfer
    and the with-hits plan is the only candidate — stated as such, not refused."""

    inputs, projection, rules = _world_context(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, _rival_squad(world)),
        }
    )
    payload = advise_entry(
        _request(strategy="fark-yarat", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    assert payload["plan_kind"] == "with_hits"
    assert payload["overlap_applied"] == payload["overlap_target"] == 5
    assert payload["alternative_plan"] is None


def test_the_rival_changes_labels_not_the_baseline(world: dict[str, Any]) -> None:
    """The saf-puan answer is byte-identical whether or not a rival entry exists in the
    capture: the rival is a parameter of rival strategies, never an input to the
    baseline — the invariance rule, exercised at the seam the backend will call."""

    inputs, projection, rules = _world_context(world)
    alone = _Provider({101: _member_picks(world, 101, _legal_squad(world))})
    accompanied = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, _rival_squad(world)),
        }
    )
    baseline_alone = advise_entry(
        _request(), provider=alone, inputs=inputs, projection=projection, rules=rules
    )
    baseline_accompanied = advise_entry(
        _request(), provider=accompanied, inputs=inputs, projection=projection, rules=rules
    )
    assert baseline_alone == baseline_accompanied


@pytest.mark.parametrize(
    ("strategy", "entry_id"),
    [("saf-puan", 101), ("fark-yarat", 101), ("fark-yarat", 202)],
)
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"entry_id": 303}, "Picks entry_id"),
        ({"season": "2024-25"}, "Picks season"),
        ({"gameweek": 2}, "Picks gameweek"),
        ({"source_snapshot_id": "another-capture"}, "another capture"),
    ],
)
def test_mismatched_member_or_rival_picks_are_refused_before_solving(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
    entry_id: int,
    changes: dict[str, object],
    message: str,
) -> None:
    inputs, projection, rules = _world_context(world)
    picks = {
        101: _member_picks(world, 101, _legal_squad(world)),
        202: _member_picks(world, 202, _rival_squad(world)),
    }
    picks[entry_id] = dataclasses.replace(picks[entry_id], **changes)

    def unexpected_solve(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Mismatched picks must be rejected before either planner is called.")

    monkeypatch.setattr(advice_service, "plan_transfers", unexpected_solve)
    monkeypatch.setattr(advice_service, "plan_transfers_with_overlap", unexpected_solve)
    request = _request(strategy=strategy, rival_entry_id=202 if strategy != "saf-puan" else None)

    with pytest.raises(EntryError, match=message):
        advise_entry(
            request,
            provider=_Provider(picks),
            inputs=inputs,
            projection=projection,
            rules=rules,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"season": "2024-25"}, "rules belong to another season"),
        ({"source_snapshot_id": "another-capture"}, "rules belong to another capture"),
    ],
)
def test_mismatched_rules_are_refused_before_solving(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
    message: str,
) -> None:
    inputs, projection, rules = _world_context(world)
    provider = _Provider({101: _member_picks(world, 101, _legal_squad(world))})

    def unexpected_solve(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Mismatched rules must be rejected before the planner is called.")

    monkeypatch.setattr(advice_service, "plan_transfers", unexpected_solve)

    with pytest.raises(EntryError, match=message):
        advise_entry(
            _request(),
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=dataclasses.replace(rules, **changes),
        )


def test_picks_without_capture_metadata_keep_their_existing_payload(
    world: dict[str, Any],
) -> None:
    inputs, projection, rules = _world_context(world)
    picks = dataclasses.replace(
        _member_picks(world, 101, _legal_squad(world)), source_snapshot_id=None
    )

    payload = advise_entry(
        _request(),
        provider=_Provider({101: picks}),
        inputs=inputs,
        projection=projection,
        rules=rules,
    )

    assert payload["entry_id"] == 101
    assert payload["source_snapshot_id"] is None


# --- what the published rows may say ------------------------------------------------


#: A world built so the caution margin and the game's charge disagree about the second
#: transfer. Everyone is worth 2.0; 1024 is worth 12.0 and 1023 is worth 8.0, so the free
#: transfer buys 1024 outright and the next transfer's gross gain is 6.0 — above the
#: game's charge of 4 and below MEMBER_PLANNING_POLICY's caution margin of 8, so the
#: control declines it. ``ortak-koru``'s floor of nine needs both 1023 and 1024, which is
#: two transfers on one free transfer: the band buys what the margin refused.
_MARGIN_SPLIT_MEMBER = [
    *[1001, 1002],  # GK
    *[1004, 1006, 1007, 1008, 1009],  # DEF
    *[1013, 1014, 1015, 1016, 1017],  # MID
    *[1020, 1021, 1022],  # FWD
]
_MARGIN_SPLIT_RIVAL = [
    *[1023, 1024, 1001, 1002, 1004, 1006, 1007, 1008, 1009, 1003, 1005],  # the public eleven
    *[1010, 1011, 1012, 1018],  # the bench, outside the band
]


def _margin_split_context(world: dict[str, Any]) -> tuple[Any, Any, Any]:
    """``_world_context`` with the projection above, rewritten into the same handoff."""

    from squadopt.data.snapshots import read_snapshot
    from squadopt.live import read_inputs, read_season_rules
    from squadopt.live.recommendation import project, read_projection_handoff

    points = {code: 2.0 for code in range(1001, 1025)}
    points[1024] = 12.0
    points[1023] = 8.0
    handoff_path = world_module._handoff(world, points=points)
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=league_views_tests.SEASON, gameweek=2)
    projection = project(inputs, in_season=read_projection_handoff(handoff_path))
    rules = read_season_rules(snapshot, season=league_views_tests.SEASON)
    return inputs, projection, rules


def _margin_split_payload(world: dict[str, Any]) -> dict[str, object]:
    inputs, projection, rules = _margin_split_context(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _MARGIN_SPLIT_MEMBER),
            202: _member_picks(world, 202, _MARGIN_SPLIT_RIVAL),
        }
    )
    return advise_entry(
        _request(strategy="ortak-koru", rival_entry_id=202),
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
    )


def test_a_strategy_is_never_published_as_giving_up_negative_points(
    world: dict[str, Any],
) -> None:
    """The price tag is a price, never a discount.

    The control and the banded candidates are all solved under the caution margin, and
    the tag compares them at the game's charge — two different objectives, so the band's
    forced paid transfer could out-net the control and the tag went negative, telling
    this member the strategy hands them two expected points. The anchor is now solved at
    the charge, so the comparison is between maximisers of the same objective, and the
    alternative carries the same guarantee.
    """

    payload = _margin_split_payload(world)

    assert payload["plan_kind"] == "with_hits"  # vacuous unless the band buys a hit
    assert payload["overlap_applied"] == 9
    cost = payload["expected_points_cost"]
    assert isinstance(cost, float) and cost >= 0.0
    alternative = payload["alternative_plan"]
    assert isinstance(alternative, dict)
    assert float(str(alternative["expected_points_cost"])) >= 0.0


def test_a_multi_transfer_week_states_its_hit_charge_once(world: dict[str, Any]) -> None:
    """A week's hit charge belongs to the week, not to one move.

    This plan makes two transfers and pays for one of them. Copying the week's charge
    onto every move row would show a reader two rows of 4 for a week the game docks 4,
    and nothing measures what share of a week's charge belongs to a single swap — so no
    move row carries one and the payload states the charge once.
    """

    payload = _margin_split_payload(world)
    moves = payload["moves"]

    assert isinstance(moves, list) and len(moves) == 2
    assert payload["transfer_hit_points"] == 4.0
    for move in moves:
        assert "expected_points_cost" not in move


def test_every_published_move_names_a_swap_the_game_would_accept(
    world: dict[str, Any],
) -> None:
    """Rows are paired by pitch position, not by the order of two id-sorted lists.

    The planner hands over its transfers sorted by player id, and an FPL element code
    says nothing about position, so pairing by index publishes rows the game's own
    transfer screen would refuse. The synthetic world numbers its players in position
    blocks and so cannot cross them; these are real codes and positions from the
    published pool (``web/public/data/2026-27/gw01/pool.json``), whose id order does
    cross. The row set and the summed delta are unchanged by the pairing.
    """

    import pandas as pd

    pool = {
        int(str(row["player_id"])): row
        for _, row in pd.DataFrame(
            {
                "player_id": [141746, 200834, 201895, 607464],
                "name": ["A", "B", "C", "D"],
                "team_id": ["T", "T", "T", "T"],
                "position": ["MID", "DEF", "DEF", "MID"],
                "expected_points": [6.0, 3.0, 5.0, 9.0],
            }
        ).iterrows()
    }
    moves = advice_service._moves(
        [141746, 200834],
        [201895, 607464],
        by_id=pool,
        pool_by_id=pool,
        gameweek=2,
        reason_code="mode_tradeoff",
    )

    assert len(moves) == 2
    for move in moves:
        assert move["player_out"]["position"] == move["player_in"]["position"]
    assert sum(float(str(move["expected_points_delta"])) for move in moves) == pytest.approx(5.0)
    # The real payload agrees: nothing else re-orders the rows.
    inputs, projection, rules = _world_context(world)
    payload = advise_entry(
        _request(),
        provider=_Provider({101: _member_picks(world, 101, _legal_squad(world))}),
        inputs=inputs,
        projection=projection,
        rules=rules,
    )
    for move in payload["moves"]:
        assert move["player_out"]["position"] == move["player_in"]["position"]


def test_the_one_week_plan_is_not_captioned_as_a_longer_window(world: dict[str, Any]) -> None:
    """``window_value`` is a claim about a longer window; this payload has none.

    The caption was keyed on the mode, so the default one-week saf-puan advice — the page
    every member lands on — labelled each move with a sentence about a longer window
    recovering the transfer cost. The one-week plan has its own reason now, and only the
    multi-week window keeps ``window_value`` (``test_member_windows``).
    """

    inputs, projection, rules = _world_context(world)
    payload = advise_entry(
        _request(),
        provider=_Provider({101: _member_picks(world, 101, _legal_squad(world))}),
        inputs=inputs,
        projection=projection,
        rules=rules,
    )

    assert payload["window"] == 1 and payload["mode"] == "saf-puan"
    moves = payload["moves"]
    assert isinstance(moves, list) and moves
    assert {move["reason_code"] for move in moves} == {"points_gain"}
