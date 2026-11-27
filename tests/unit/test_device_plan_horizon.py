"""Captured-calendar device inputs and reference answers, using synthetic live data only."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import pytest
from ortools.sat.python import cp_model
from scripts.check_league_tree import main as check_tree
from tests.unit.test_device_plan_fixture import _same
from tests.unit.test_league_views import DISCRETIONARY_SQUAD, _Provider
from tests.unit.test_live_transfers import _bootstrap, _elements
from tests.unit.test_projection_horizon_builder import _calendar

from squadopt.application.advice import member_horizon_builder, window_payload
from squadopt.application.device_plan import (
    DEVICE_PLAN_HORIZON_CONTRACT_VERSION,
    device_plan_capture_table,
    device_plan_entry,
    device_plan_horizon,
    device_plan_table,
)
from squadopt.application.entries import EntryPicks, EntryRegistration
from squadopt.application.horizon_plans import HorizonPlanRequest, plan_horizon
from squadopt.application.league_views import build_league_views
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import HeldSquad, read_inputs, read_season_rules
from squadopt.live.recommendation import InSeasonProjection, project, write_projection_handoff
from squadopt.live.transfers import member_planning_policy, member_window_policy
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.optimization.coefficients import objective_coefficients
from squadopt.planning import optimizer as server_model

FIXTURE = Path(__file__).resolve().parents[2] / "web/src/fixtures/device-plan/horizons.json"
SEASON = "2026-27"


def horizon_world(root: Path) -> dict[str, Any]:
    """No archive, no historical panel: every row belongs to the synthetic live season."""

    events = [
        {
            "id": week,
            "deadline_time": f"2026-09-{week + 1:02d}T17:30:00Z",
            "finished": week == 1,
            "data_checked": week == 1,
        }
        for week in range(1, 7)
    ]
    calendar = json.loads(_calendar(gameweeks=tuple(range(1, 7))))
    calendar = [row for row in calendar if not (row["event"] == 4 and row["team_h"] == 3)]
    calendar.append({**calendar[0], "id": 90, "event": 3, "team_h": 1, "team_a": 6})
    bootstrap = _bootstrap(events=events, elements=_elements(start_prices=True))
    metadata = write_snapshot(
        root / "snapshots",
        source="fpl-live",
        captured_at_utc="2026-09-02T09:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: bootstrap, FIXTURES_PAYLOAD: json.dumps(calendar).encode()},
    )
    snapshot = read_snapshot(root / "snapshots", metadata.snapshot_id)
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = InSeasonProjection(
        season=SEASON,
        gameweek=2,
        source_snapshot_id=metadata.snapshot_id,
        model_name="squadopt-deterministic-baseline",
        model_version="in-season-carry-over-v1",
        feature_contract_version="synthetic-device-horizon-v1",
        expected_points={
            1000 + index: 1.0 + ((index * 137) % 1700) / 100 for index in range(1, 25)
        },
    )
    handoff_path = write_projection_handoff(root / "handoff.json", handoff)
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=SEASON)
    builder = member_horizon_builder(snapshot, season=SEASON, in_season=handoff)
    return {
        "root": root,
        "snapshot": snapshot,
        "inputs": inputs,
        "projection": projection,
        "rules": rules,
        "builder": builder,
        "bootstrap": bootstrap,
        "handoff_path": handoff_path,
    }


def held_member(world: dict[str, Any], free: int, bank: int = 50) -> HeldSquad:
    prices = world["projection"].table.set_index("player_id").price_tenths
    return HeldSquad(
        season=SEASON,
        decided_gameweek=1,
        squad_player_ids=DISCRETIONARY_SQUAD,
        purchase_prices={
            player: int(prices[player]) - (3 if player == 1012 else 0)
            for player in DISCRETIONARY_SQUAD
        },
        bank_tenths=bank,
        free_transfers=free,
        chips_used={},
    )


def member_picks(world: dict[str, Any], held: HeldSquad, entry_id: int = 1) -> EntryPicks:
    return EntryPicks(
        entry_id=entry_id,
        season=SEASON,
        gameweek=1,
        squad=tuple(held.squad_player_ids),
        starting_xi=tuple(held.squad_player_ids[:11]),
        captain=1001,
        vice_captain=1002,
        bank_tenths=held.bank_tenths,
        free_transfers=held.free_transfers,
        purchase_prices=held.purchase_prices,
        purchase_prices_known=True,
        free_transfers_known=True,
        source_snapshot_id=world["inputs"].snapshot_id,
    )


def build_horizon_fixture(root: Path) -> dict[str, Any]:
    world = horizon_world(root)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    horizon = device_plan_horizon(inputs, projection, rules, world["builder"])
    document = device_plan_table(inputs, projection, rules, league_id=9, horizon=horizon)
    members = []
    for entry_id, free in enumerate((0, 1, 5), start=1):
        held = held_member(world, free)
        references = {}
        for window in (3, 5):
            request = HorizonPlanRequest(
                snapshot_root=root / "snapshots",
                snapshot_id=inputs.snapshot_id,
                ledger_root=root / f"ledger-{entry_id}",
                artifact_root=root / f"artifacts-{entry_id}",
                in_season_projection=world["handoff_path"],
                season=SEASON,
                from_gameweek=2,
                gameweeks=window,
            )
            # Synthetic initial state replaces only the ledger read. The complete
            # application command builds, solves, verifies and serializes the result.
            built = []
            original_build = server_model._build_model

            def capture_model(*args, _original=original_build, _built=built, **kwargs):
                artifacts = _original(*args, **kwargs)
                _built.append(artifacts)
                return artifacts

            with (
                patch(
                    "squadopt.application.horizon_plans.held_squad_from_ledger", return_value=held
                ),
                patch.object(server_model, "_build_model", side_effect=capture_model),
            ):
                result = plan_horizon(request)
            assert result.solver_status is SolverStatus.OPTIMAL
            primary = round(
                result.plan.diagnostics["scaled_model_objective_value"]
                * result.plan.diagnostics["objective_weight_scale"]
                * OptimizationConfig().expected_points_scale
            )
            artifacts = built[-1]
            alternative = artifacts.model.clone()
            alternative.add(artifacts.primary_objective == primary)
            differences = []
            for index, week in enumerate(result.plan.weeks):
                players = artifacts.players_by_week[index].player_id.tolist()
                for family, chosen in (
                    (artifacts.transfer_in_vars[index], set(week.transfers_in.player_id)),
                    (artifacts.transfer_out_vars[index], set(week.transfers_out.player_id)),
                ):
                    differences.extend(
                        1 - variable if player in chosen else variable
                        for player, variable in zip(players, family, strict=True)
                    )
            alternative.add(sum(differences) >= 1)
            alternative.maximize(artifacts.primary_objective)
            uniqueness = cp_model.CpSolver()
            uniqueness.parameters.num_search_workers = 1
            uniqueness.parameters.max_time_in_seconds = 30
            uniqueness.parameters.max_deterministic_time = 10
            uniqueness_status = uniqueness.solve(alternative)
            assert uniqueness_status in (cp_model.INFEASIBLE, cp_model.OPTIMAL, cp_model.FEASIBLE)
            published = window_payload(
                member_picks(world, held, entry_id),
                projection,
                result.plan,
                league_id=9,
                window=window,
            )
            references[str(window)] = {
                "objective": result.plan.objective_value,
                "objective_scaled": primary,
                "unique_moves": uniqueness_status == cp_model.INFEASIBLE,
                "tiebreak_completed": result.plan.diagnostics["tiebreak_completed"],
                "presentation": {
                    field: published[field]
                    for field in (
                        "window",
                        "moves",
                        "transfer_hit_points",
                        "expected_gain_vs_hold",
                        "expected_own_points",
                        "captain",
                        "vice_captain",
                        "starting_xi",
                        "bench",
                        "plan_weeks",
                    )
                },
                "weeks": [
                    {
                        "gameweek": week.gameweek,
                        "squad": week.selected_squad.player_id.tolist(),
                        "starting_xi": week.starting_xi.player_id.tolist(),
                        "captain": int(week.captain.player_id),
                        "transfers_in": week.transfers_in.player_id.tolist(),
                        "transfers_out": week.transfers_out.player_id.tolist(),
                        "bank_after_tenths": week.bank_after_tenths,
                        "free_transfers_before": week.free_transfers_before,
                        "free_transfers_after": week.free_transfers_for_next_gameweek,
                        "transfer_hit_points": week.transfer_hit_points,
                        "expected_points": week.projected_score,
                    }
                    for week in result.plan.weeks
                ],
            }
        members.append(
            {
                "entry_id": entry_id,
                "entry": device_plan_entry(inputs, projection, held, rules, horizon=horizon),
                "reference": references,
            }
        )
    return {"document": document, "members": members}


def test_horizon_preserves_every_one_week_field_as_identical_bytes(tmp_path: Path) -> None:
    world = horizon_world(tmp_path)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    horizon = device_plan_horizon(inputs, projection, rules, world["builder"])
    assert horizon is not None
    for factory, arguments in (
        (device_plan_table, {"league_id": 9}),
        (device_plan_capture_table, {"bootstrap": world["bootstrap"]}),
    ):
        before = factory(inputs, projection, rules, **arguments)
        after = factory(inputs, projection, rules, **arguments, horizon=horizon)
        assert after.pop("horizon") == horizon
        assert (
            json.dumps(before, ensure_ascii=False).encode()
            == json.dumps(after, ensure_ascii=False).encode()
        )
    assert horizon["contract_version"] == DEVICE_PLAN_HORIZON_CONTRACT_VERSION
    assert horizon["windows"] == [3, 5]
    expected = world["builder"]((2, 3, 4, 5, 6))
    for week in horizon["weeks"]:
        table = expected.table.loc[expected.table.gameweek.eq(week["gameweek"])]
        assert [row["expected_points"] for row in week["players"]] == table.expected_points.tolist()
        assert [row["coefficients"] for row in week["players"]] == [
            list(row)
            for row in objective_coefficients(table.expected_points.tolist(), OptimizationConfig())
        ]


def test_horizon_does_not_remove_one_week_inputs_when_future_calendar_is_missing(
    tmp_path: Path,
) -> None:
    world = horizon_world(tmp_path)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    assert device_plan_horizon(inputs, projection, rules, None) is None
    assert (
        device_plan_horizon(
            replace(inputs, published_gameweeks=frozenset({1, 2})),
            projection,
            rules,
            world["builder"],
        )
        is None
    )

    def missing(_weeks):
        raise DataSourceError("missing captured calendar")

    assert device_plan_horizon(inputs, projection, rules, missing) is None


@pytest.mark.parametrize("window", [3, 5])
def test_horizon_uses_the_window_policy_and_carries_no_one_week_transfer_value(
    tmp_path: Path, window: int
) -> None:
    world = horizon_world(tmp_path)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    inputs = replace(inputs, published_gameweeks=frozenset(range(1, 2 + window)))
    first = int(inputs.deadline.gameweek)
    assert member_planning_policy(rules, first).values_carried_transfers
    one_week = device_plan_table(inputs, projection, rules, league_id=9)
    assert any(one_week["rules"]["banked_values_scaled"])
    with patch(
        "squadopt.application.device_plan.member_window_policy", wraps=member_window_policy
    ) as policy:
        horizon = device_plan_horizon(inputs, projection, rules, world["builder"])
    policy.assert_called_once_with(rules, gameweek=first, transfer_cap=1, weeks=window)
    assert horizon is not None
    assert horizon["rules"]["banked_transfer_value_scaled"] == 0
    assert horizon["rules"]["max_transfers_per_gameweek"] == 1


def test_horizon_publishes_the_transfer_cap_returned_by_the_window_policy(tmp_path: Path) -> None:
    world = horizon_world(tmp_path)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    policy = member_window_policy(rules, gameweek=2, transfer_cap=2, weeks=5)
    with patch("squadopt.application.device_plan.member_window_policy", return_value=policy):
        horizon = device_plan_horizon(inputs, projection, rules, world["builder"])
    assert horizon is not None
    assert horizon["rules"]["max_transfers_per_gameweek"] == 2


@pytest.mark.parametrize(
    "mismatch",
    [
        "season",
        "capture",
        "player_id",
        "name",
        "team_id",
        "position",
        "price_tenths",
        "expected_points",
        "fingerprint",
    ],
)
def test_a_changed_horizon_logs_once_and_preserves_the_one_week_document(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mismatch: str
) -> None:
    world = horizon_world(tmp_path)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    horizon = world["builder"]((2, 3, 4, 5, 6))
    before = json.dumps(device_plan_table(inputs, projection, rules, league_id=9)).encode()
    if mismatch == "season":
        horizon = replace(horizon, season="2024-25")
    elif mismatch == "capture":
        horizon = replace(horizon, source_snapshot_id="synthetic-other-capture")
    elif mismatch == "fingerprint":
        horizon.table.loc[horizon.table.index[0], "price_tenths"] += 1
    else:
        table = horizon.table.copy()
        if mismatch == "player_id":
            table["player_id"] += 10000
        elif mismatch in ("price_tenths", "expected_points"):
            row = table.index[(table.gameweek == 2) & (table.fixture_count > 0)][0]
            table.loc[row, mismatch] += 1
        elif mismatch == "position":
            table.loc[table.index[0], "position"] = (
                "DEF" if table.iloc[0].position == "GK" else "GK"
            )
        elif mismatch == "team_id":
            team = table.iloc[0].team_id
            table.loc[table.index[0], "team_id"] = (
                f"{team}-changed" if isinstance(team, str) else int(team) + 10000
            )
        else:
            table.loc[table.index[0], mismatch] = "synthetic-changed"
        horizon = replace(horizon, table=table)

    result = device_plan_horizon(inputs, projection, rules, lambda _weeks: horizon)

    assert result is None
    records = [
        record for record in caplog.records if record.name == "squadopt.application.device_plan"
    ]
    assert len(records) == 1
    assert records[0].getMessage().startswith("Skipping device horizon:")
    assert (
        json.dumps(
            device_plan_table(inputs, projection, rules, league_id=9, horizon=result)
        ).encode()
        == before
    )


def test_horizon_inputs_change_only_the_device_document_in_the_built_tree(tmp_path: Path) -> None:
    world = horizon_world(tmp_path / "world")
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    held = held_member(world, 1)
    picks = EntryPicks(
        entry_id=1,
        season=SEASON,
        gameweek=1,
        squad=tuple(held.squad_player_ids),
        starting_xi=tuple(held.squad_player_ids[:11]),
        captain=1001,
        vice_captain=1002,
        bank_tenths=held.bank_tenths,
        free_transfers=held.free_transfers,
        purchase_prices=held.purchase_prices,
        purchase_prices_known=True,
        free_transfers_known=True,
        source_snapshot_id=inputs.snapshot_id,
    )
    for name, horizon in (
        ("before", None),
        ("after", device_plan_horizon(inputs, projection, rules, world["builder"])),
    ):
        build_league_views(
            _Provider({1: picks}),
            (EntryRegistration(1, "synthetic-member", "2026-09-02T09:00:00Z"),),
            inputs,
            projection,
            rules,
            league_id=9,
            league_name="Synthetic League",
            out_dir=tmp_path / name / "league",
            now=datetime(2026, 9, 2, 10, tzinfo=UTC),
            device_only=True,
            device_horizon=horizon,
        )
    before = tmp_path / "before" / "league"
    after = tmp_path / "after" / "league"
    assert {path.relative_to(before) for path in before.rglob("*") if path.is_file()} == {
        path.relative_to(after) for path in after.rglob("*") if path.is_file()
    }
    for path in before.rglob("*"):
        if not path.is_file() or path.name == "device-plan.json":
            continue
        relative = path.relative_to(before)
        updated = after / relative
        if relative.parts[0] == "entries":
            entry = json.loads(updated.read_text(encoding="utf-8"))
            assert entry["payload"]["device_plan"].pop("horizon") == {"windows": [3, 5]}
            assert path.read_bytes() == json.dumps(entry, indent=2).encode(), path.name
        else:
            assert path.read_bytes() == updated.read_bytes(), path.name
    assert check_tree([str(after.parent)]) == 0


@pytest.mark.parametrize("windows", [None, [3], [3, 5]])
def test_member_device_metadata_changes_no_existing_one_week_field(
    tmp_path: Path, windows: list[int] | None
) -> None:
    world = horizon_world(tmp_path)
    inputs, projection, rules = (world[key] for key in ("inputs", "projection", "rules"))
    held = held_member(world, 1)
    before = device_plan_entry(inputs, projection, held, rules)
    after = device_plan_entry(
        inputs,
        projection,
        held,
        rules,
        horizon=None if windows is None else {"windows": windows},
    )
    assert after is not None
    if windows is None:
        assert "horizon" not in after
    else:
        assert after.pop("horizon") == {"windows": windows}
    assert json.dumps(before).encode() == json.dumps(after).encode()


def test_recorded_horizon_answers_are_the_server_application_answers(tmp_path: Path) -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _same(recorded, build_horizon_fixture(tmp_path)) == []


if __name__ == "__main__":
    with TemporaryDirectory() as temporary:
        FIXTURE.write_text(
            json.dumps(build_horizon_fixture(Path(temporary)), indent=2) + "\n", encoding="utf-8"
        )
