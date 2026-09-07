"""advise_entry: a wire-shaped request, injected collaborators, the same bytes."""

import dataclasses
import json
from pathlib import Path
from typing import Any, get_type_hints

import pytest
import tests.unit.test_league_views as league_views_tests
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
        call(_request(window=3))
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


def test_an_unproven_control_does_not_publish_an_expected_points_cost(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
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
        return dataclasses.replace(plan, solver_status=SolverStatus.FEASIBLE), decision, config

    monkeypatch.setattr(advice_service, "plan_transfers", feasible_control)

    with pytest.raises(EntryError, match="control plan must be OPTIMAL"):
        advise_entry(
            _request(strategy="fark-yarat", rival_entry_id=202),
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
        )


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
