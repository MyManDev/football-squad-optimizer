"""Multiweek rival plans use the existing engine and an equal-window control."""

import dataclasses
import json
from typing import Any

import pytest
from tests.unit.test_member_windows import ENTRY, SEASON, _advise, _window_world

from squadopt.application.advice import build_window_control
from squadopt.application.entries import EntryError
from squadopt.data.errors import DataSourceError
from squadopt.platform.advice_documents import AdviceDocumentError, validate_advice_document

window_world = _window_world


def _rival(world: dict[str, Any], *, distant: bool = False) -> None:
    picks = world["provider"].picks(ENTRY, SEASON, 1)
    changes: dict[str, Any] = {"entry_id": 202}
    if distant:
        others = sorted(set(world["projection"].table["player_id"]) - set(picks.squad))
        squad = tuple([*others, *picks.squad][:15])
        changes.update(squad=squad, starting_xi=squad[:11], captain=squad[0])
    world["provider"]._picks[202] = dataclasses.replace(picks, **changes)


def _document(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "contract_version": "provisional_league_ui_v1",
            "source_kind": "example",
            "generated_at_utc": "2026-09-15T00:00:00Z",
            "payload": payload,
        }
    ).encode()


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("mode", ["ortak-koru", "fark-yarat"])
def test_rival_window_keeps_policy_and_compares_the_same_window(
    window_world: dict[str, Any],
    window: int,
    mode: str,
) -> None:
    _rival(window_world, distant=mode == "fark-yarat")
    control = _advise(window_world, window=window)
    payload = _advise(window_world, strategy=mode, window=window, rival_entry_id=202)
    comparison = payload["window_comparison"]
    squad = {p["player_id"] for p in [*payload["starting_xi"], *payload["bench"]]}
    rival = window_world["provider"].picks(202, SEASON, 1)
    assert comparison["overlap_actual"] == len(squad & set(rival.starting_xi))
    assert (
        comparison["overlap_actual"] >= 9
        if mode == "ortak-koru"
        else comparison["overlap_actual"] <= 5
    )
    for plan in (payload, control):
        assert all(len(w["transfers_in"]) <= 1 and w["chip"] is None for w in plan["plan_weeks"])
    control_total = sum(
        w["expected_points"] - w["transfer_hit_points"] for w in control["plan_weeks"]
    )
    total = sum(w["expected_points"] - w["transfer_hit_points"] for w in payload["plan_weeks"])
    assert comparison["control_total_net_points"] == pytest.approx(control_total)
    assert comparison["total_net_points"] == pytest.approx(total)
    assert comparison["net_points_difference"] == pytest.approx(total - control_total)
    assert "expected_points_cost" not in payload
    validate_advice_document(_document(payload))
    assert _advise(window_world, strategy=mode, window=window, rival_entry_id=202) == payload


def test_impossible_band_is_reported_without_relaxing_it(window_world: dict[str, Any]) -> None:
    _rival(window_world)
    with pytest.raises(DataSourceError, match="INFEASIBLE"):
        _advise(window_world, strategy="fark-yarat", window=3, rival_entry_id=202)


@pytest.mark.parametrize("change", ["window", "total", "rival", "band", "missing"])
def test_corrupt_comparison_is_refused(window_world: dict[str, Any], change: str) -> None:
    _rival(window_world)
    payload = _advise(window_world, strategy="ortak-koru", window=3, rival_entry_id=202)
    if change == "window":
        payload["window"] = 5
    elif change == "missing":
        del payload["window_comparison"]
    else:
        field = {"total": "total_net_points", "rival": "rival_entry_id", "band": "overlap_actual"}[
            change
        ]
        payload["window_comparison"][field] = 0
    with pytest.raises(AdviceDocumentError):
        validate_advice_document(_document(payload))


def test_precomputed_control_cannot_cross_windows(window_world: dict[str, Any]) -> None:
    from squadopt.application.advice import AdviseEntryRequest, advise_entry

    _rival(window_world)
    world = window_world
    control = build_window_control(
        world["provider"].picks(ENTRY, SEASON, 1),
        world["inputs"],
        world["projection"],
        world["rules"],
        league_id=352490,
        window=3,
        horizon_builder=world["builder"],
    )
    with pytest.raises(EntryError, match="different inputs or window"):
        advise_entry(
            AdviseEntryRequest(
                SEASON, 2, 352490, ENTRY, strategy="ortak-koru", window=5, rival_entry_id=202
            ),
            provider=world["provider"],
            inputs=world["inputs"],
            projection=world["projection"],
            rules=world["rules"],
            horizon_builder=world["builder"],
            window_control=control,
        )
