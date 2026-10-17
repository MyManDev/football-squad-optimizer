"""The mean-reversion discount runner: its arms, its readings and its refusals.

The runner builds the protocol's arms (the weekly control with no cap, the three-week arms
under the member window's cap of one transfer with a second from two banked free
transfers), walks them through a chain factory, and merges per-season artifacts into the
committed record. The chain itself is stubbed here; its arithmetic is tested beside it in
``test_mean_reversion_discount.py``.
"""

import json
from pathlib import Path
from typing import ClassVar

import pytest
import scripts.measure_mean_reversion_discount as cli

from squadopt.experiments import (
    MEAN_REVERSION_PROJECTION_RULE,
    NAIVE_PROJECTION_RULE,
    SeasonChainConfig,
)
from squadopt.experiments.season_chain import SeasonChainResult, SeasonChainWeek

OPTIMIZATION = cli.measurement_optimization_config()


def test_the_arms_follow_the_protocol() -> None:
    arms = cli.build_arms("2024-25", [0.75, 0.9, 0.6], OPTIMIZATION)
    assert [arm.label for arm in arms] == ["L1", "L3_naive", "L3_mr_0.75", "L3_mr_0.9", "L3_mr_0.6"]
    control, naive, *reverted = arms
    assert control.config.lookahead == 1
    assert control.config.projection_rule == NAIVE_PROJECTION_RULE
    assert control.config.frozen_transfer_config.max_transfers_per_gameweek is None
    assert control.config.frozen_transfer_config.allow_two_free_transfers is False
    assert naive.config.lookahead == 3
    assert naive.config.projection_rule == NAIVE_PROJECTION_RULE
    assert naive.config.mean_reversion_factor is None
    for arm, rho in zip(reverted, [0.75, 0.9, 0.6], strict=True):
        assert arm.config.lookahead == 3
        assert arm.config.projection_rule == MEAN_REVERSION_PROJECTION_RULE
        assert arm.config.mean_reversion_factor == rho
    for arm in (naive, *reverted):
        transfer = arm.config.frozen_transfer_config
        assert transfer.max_transfers_per_gameweek == 1
        assert transfer.allow_two_free_transfers is True
    for arm in arms:
        transfer = arm.config.frozen_transfer_config
        assert transfer.transfer_hit_cost_points == 8.0
        assert transfer.hit_points_charged == 4.0
        assert transfer.banked_transfer_value_points == 0.0
        assert transfer.horizon_discount_factor == 1.0
        assert transfer.max_free_transfers == 5
        assert dict(transfer.chip_holding_value_points) == {}
        assert arm.config.chip_windows == ()
        assert arm.config.hit_points_charged == 4.0
        assert arm.config.sell_on_fee_halved is True
        assert arm.config.form_window == 5
        assert arm.config.candidate_pool_per_position == 20
        assert arm.config.cheap_pool_per_position == 8
        assert arm.config.optimization_config is OPTIMIZATION
    assert (
        cli.build_arms("2021-22", [], OPTIMIZATION)[
            0
        ].config.frozen_transfer_config.max_free_transfers
        == 2
    )
    pilot = cli.build_arms("2024-25", [0.75], OPTIMIZATION, end_gameweek=9)
    assert all(arm.config.end_gameweek == 9 for arm in pilot)


def _week(gameweek: int, realized: float, hits: float, squad: tuple[str, ...]) -> SeasonChainWeek:
    return SeasonChainWeek(
        gameweek=gameweek,
        realized_points=realized,
        transfer_hit_points=hits,
        transfer_count=1 if gameweek > 2 else 0,
        paid_transfer_count=int(hits // 4),
        free_transfers_before=1,
        free_transfers_after=1,
        chip=None,
        planned_chips={},
        lookahead_gameweeks=1,
        solver_status="OPTIMAL" if gameweek % 2 == 0 else "FEASIBLE",
        relative_gap=None if gameweek % 2 == 0 else 0.01,
        projected_points=50.0,
        captain_realized_points=8.0,
        bench_realized_points=3.0,
        bank_after_tenths=5,
        squad_sell_value_tenths=990,
        pool_size=100,
        carried_blank_rows=0,
        carried_unexplained_rows=0,
        squad_player_ids=squad,
    )


class _StubChain:
    """Returns a fixed walk whose numbers depend on the arm, and remembers its config."""

    configs: ClassVar[list[SeasonChainConfig]] = []

    def __init__(self, panel: object, counts: object, config: SeasonChainConfig) -> None:
        self.config = config
        _StubChain.configs.append(config)

    def run(self) -> SeasonChainResult:
        bonus = 0.0 if self.config.mean_reversion_factor is None else 10.0
        hits = 4.0 if self.config.lookahead == 1 else 0.0
        return SeasonChainResult(
            season=self.config.season,
            lookahead=self.config.lookahead,
            chips_enabled=False,
            weeks=(
                _week(2, 50.0 + bonus, 0.0, ("a", "b")),
                _week(3, 60.0 + bonus, hits, ("a", "c")),
                _week(4, 55.0 + bonus, hits, ("a", "d")),
                _week(5, 58.0 + bonus, 0.0, ("a", "c")),
            ),
            opening_squad_ids=("a", "b"),
            diagnostics={"projection_rule": self.config.projection_rule},
        )


def test_the_runner_walks_every_arm_through_the_chain_factory() -> None:
    _StubChain.configs = []
    arms = cli.build_arms("2024-25", [0.75], OPTIMIZATION)
    records = cli.run_season(object(), object(), arms, chain_factory=_StubChain)
    assert [record["variant"] for record in records] == ["L1", "L3_naive", "L3_mr_0.75"]
    assert [config.lookahead for config in _StubChain.configs] == [1, 3, 3]
    assert records[2]["mean_reversion_factor"] == 0.75
    assert records[0]["mean_reversion_factor"] is None
    assert all(float(str(record["seconds_per_decision"])) >= 0.0 for record in records)
    assert records[2]["net_points"] == records[1]["net_points"] + 40.0


def test_reversals_count_a_purchase_sold_within_three_gameweeks() -> None:
    weeks = [
        {"gameweek": 2, "squad_player_ids": ["a", "b"]},
        {"gameweek": 3, "squad_player_ids": ["a", "c"]},  # c bought at 3
        {"gameweek": 4, "squad_player_ids": ["a", "d"]},  # c sold at 4: reversal
        {"gameweek": 7, "squad_player_ids": ["a", "e"]},  # d bought 4, sold 7: reversal
        {"gameweek": 11, "squad_player_ids": ["a", "f"]},  # e bought 7, sold 11: not
        {"gameweek": 12, "squad_player_ids": ["g", "f"]},  # a is an opening player: not
    ]
    assert cli.reversal_count(weeks) == 2


def test_the_verdict_reads_the_three_clauses_of_the_gate() -> None:
    def comparison(mean: float, low: float, nets: dict[str, float]) -> dict[str, object]:
        return {
            "mean_weekly_advantage_points": mean,
            "weekly_advantage_block_bootstrap_interval": (low, low + 2.0),
            "season_net_advantage_points": nets,
        }

    passing = cli.verdict(comparison(2.0, 0.5, {"a": 10.0, "b": -1.0, "c": 5.0}))
    assert passing["certified"] is True and passing["status"] == "certified"
    assert cli.verdict(comparison(1.4, 0.5, {"a": 10.0}))["certified"] is False
    assert cli.verdict(comparison(2.0, -0.1, {"a": 10.0}))["certified"] is False
    failing = cli.verdict(comparison(2.0, 0.5, {"a": 10.0, "b": -1.0, "c": -5.0}))
    assert failing["certified"] is False
    assert failing["losing_seasons"] == ["b", "c"]
    assert failing["status"] == "measured, not certified"
    assert cli.verdict(None)["certified"] is False
    assert cli.NOISE_FLOOR_POINTS_PER_GAMEWEEK == 1.5


def _season_document(season: str, tmp_path: Path) -> Path:
    arms = cli.build_arms(season, [0.75, 0.9, 0.6], OPTIMIZATION)
    records = cli.run_season(object(), object(), arms, chain_factory=_StubChain)
    document = {
        "contract_version": cli.CONTRACT_VERSION,
        "repository_commit": "a" * 40,
        "working_tree_dirty": False,
        "archive_commit": "b" * 40,
        "started_at_utc": "2026-10-17T10:00:00+00:00",
        "finished_at_utc": "2026-10-17T11:00:00+00:00",
        "provenance": {"repository_commit": "a" * 40},
        "environment": {
            "platform": "test",
            "logical_cpu_count": 4,
            "python": "3.x",
            "ortools": "9.x",
        },
        "development_scope": "v2" if season == "2025-26" else "v1",
        "seasons": [season],
        "rhos": [0.75, 0.9, 0.6],
        "pilot_gameweeks": None,
        "solver_limits": {
            "solver_time_limit_seconds": 60.0,
            "solver_deterministic_time_limit": 8.0,
        },
        "chains": records,
    }
    path = tmp_path / f"{season}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_the_merge_writes_the_record_its_twin_and_the_expansion(tmp_path: Path) -> None:
    sources = [_season_document(season, tmp_path) for season in ("2024-25", "2025-26")]
    json_output = tmp_path / "record.json"
    markdown_output = tmp_path / "record.md"
    expansion = tmp_path / "weeks.json"
    assert (
        cli.main(
            [
                "--merge",
                ",".join(str(path) for path in sources),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
                "--expansion-output",
                str(expansion),
                "--bootstrap-resamples",
                "50",
            ]
        )
        == 0
    )
    document = json.loads(json_output.read_text(encoding="utf-8"))
    assert document["repository_commit"] == "a" * 40
    assert document["working_tree_dirty"] is False
    assert document["protocol"] == cli.PROTOCOL_PATH
    assert document["development_scope"] == "v2"
    assert document["locked_holdout_accessed"] is True
    assert document["seasons"] == ["2024-25", "2025-26"]
    assert document["noise_floor_points_per_gameweek"] == 1.5
    assert document["bootstrap"]["seed"] == 0
    assert document["expansion"]["sha256"] == cli._sha256(expansion)
    assert len(document["chains"]) == 10
    assert all(
        chain["carried_blank_rows"] == 0 and chain["carried_unexplained_rows"] == 0
        for chain in document["chains"]
    )
    assert len(document["merge_repository_commit"]) == 40
    assert isinstance(document["merge_working_tree_dirty"], bool)
    assert [item["path"] for item in document["merged_from"]] == [str(p) for p in sources]
    assert all(
        item["sha256"] == cli._sha256(path)
        for item, path in zip(document["merged_from"], sources, strict=True)
    )
    assert all("weeks" not in chain and len(chain["weekly"]) == 4 for chain in document["chains"])
    keys = {(c["variant"], c["baseline"]) for c in document["comparisons"]}
    assert keys == {
        ("L3_mr_0.75", "L3_naive"),
        ("L3_mr_0.9", "L3_naive"),
        ("L3_mr_0.6", "L3_naive"),
        ("L3_mr_0.75", "L1"),
        ("L3_mr_0.9", "L1"),
        ("L3_mr_0.6", "L1"),
        ("L3_naive", "L1"),
    }
    primary = next(
        c
        for c in document["comparisons"]
        if (c["variant"], c["baseline"]) == ("L3_mr_0.75", "L3_naive")
    )
    assert primary["mean_weekly_advantage_points"] == 10.0
    assert primary["paired_gameweeks"] == 8
    decomposition = next(
        d for d in document["decompositions"] if (d["variant"], d["baseline"]) == ("L3_naive", "L1")
    )
    assert decomposition["mean_weekly_hit_points"] == -2.0
    assert decomposition["season_selection_points"] == {"2024-25": 0.0, "2025-26": 0.0}
    # Every stubbed week is identical, so the interval is degenerate and the gate reads it.
    assert document["verdict"]["clears_noise_floor"] is True
    assert document["verdict"]["losing_seasons"] == []
    expansion_document = json.loads(expansion.read_text(encoding="utf-8"))
    assert all("weeks" in chain for chain in expansion_document["chains"])
    twin = markdown_output.read_text(encoding="utf-8")
    assert twin.startswith("# A mean-reversion discount")
    assert "## Verdict" in twin and "`L3_mr_0.75` minus `L3_naive` (primary)" in twin
    assert "| Carried blank | Carried holes |" in twin and "protocol step 4" in twin
    assert chr(0x2014) not in twin and chr(0x2013) not in twin


def test_a_pilot_writes_nowhere_under_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli, "build_panel", lambda *a, **k: calls.append(a))
    assert (
        cli.main(
            [
                "--archive-root",
                str(tmp_path),
                "--seasons",
                "2024-25",
                "--pilot-gameweeks",
                "8",
                "--json-output",
                str(cli.DOCS_ROOT / "research" / "pilot.json"),
            ]
        )
        == 1
    )
    assert calls == []


def test_the_holdout_is_refused_under_scope_v1_before_the_loader_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli, "build_panel", lambda *a, **k: calls.append(a))
    assert cli.main(["--archive-root", str(tmp_path), "--seasons", "2025-26"]) == 1
    assert calls == []
    assert (
        cli.main(
            [
                "--archive-root",
                str(tmp_path),
                "--seasons",
                "2024-25",
                "--json-output",
                str(cli.DOCS_ROOT / "research" / "x.json"),
            ]
        )
        == 1
    )
    assert calls == []
