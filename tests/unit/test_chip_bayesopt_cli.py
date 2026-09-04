"""CLI tests for the chip holding value / hit cost Bayesian search runner.

The season chain is replaced by a deterministic stand-in so the test exercises the
search loop, the season-robust objective, and the artifact shape, not the walk itself.
"""

import json
import sys
from pathlib import Path

import pytest
import scripts.run_chip_bayesopt as cli

SEASONS = "1998-99,1999-00"


def _fake_season_net(
    task: tuple[str, dict[str, float], str],
) -> tuple[str, float, dict[str, object]]:
    season, values, mode = task
    assert mode in {"hybrid", "value"}
    # A smooth, season-dependent surface: peaked at 3xc=20 / wildcard=16 / hit cost 6,
    # with the second season 30 points lower and more sensitive to the hit cost.
    base = 2000.0 if season == "1998-99" else 1970.0
    net = (
        base
        - abs(values["threexc_hold"] - 20.0)
        - abs(values["wildcard_hold"] - 16.0)
        - (2.0 if season == "1998-99" else 6.0) * abs(values["planning_hit_cost"] - 6.0)
    )
    return season, net, {"chips_played": {}, "transfer_hit_points": 0.0}


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra: str) -> int:
    monkeypatch.setattr(cli, "_init_worker", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_season_net", _fake_season_net)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_chip_bayesopt",
            "--archive-root",
            str(tmp_path),
            "--seasons",
            SEASONS,
            "--workers",
            "1",
            "--evaluation-budget",
            "6",
            "--initial-design-size",
            "4",
            "--json-output",
            str(tmp_path / "chip_bayesopt.json"),
            "--markdown-output",
            str(tmp_path / "chip_bayesopt.md"),
            *extra,
        ],
    )
    return cli.main()


def test_the_runner_records_every_evaluation_with_its_season_nets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, tmp_path) == 0

    document = json.loads((tmp_path / "chip_bayesopt.json").read_text(encoding="utf-8"))
    assert document["contract_version"] == cli.CHIP_BAYESOPT_CONTRACT_VERSION
    assert document["locked_holdout_accessed"] is False
    assert document["measurement_only"] is True
    assert document["seasons"] == SEASONS.split(",")
    assert len(document["evaluations"]) == 6
    phases = [e["phase"] for e in document["evaluations"]]
    assert phases[:4] == ["initial_design"] * 4
    for evaluation in document["evaluations"]:
        nets = evaluation["season_net"]
        assert set(nets) == set(SEASONS.split(","))
        mean = sum(nets.values()) / len(nets)
        assert evaluation["mean_net"] == pytest.approx(mean)
        assert evaluation["objective_value"] == pytest.approx(mean - evaluation["season_spread"])
    recommended = document["recommended_evaluation"]
    assert recommended is not None
    assert recommended["robust_score"] == max(e["objective_value"] for e in document["evaluations"])
    markdown = (tmp_path / "chip_bayesopt.md").read_text(encoding="utf-8")
    assert "not a promotion" in markdown


def test_the_runner_refuses_the_locked_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(monkeypatch, tmp_path, "--seasons", "2024-25,2025-26") == 1
    assert not (tmp_path / "chip_bayesopt.json").exists()
