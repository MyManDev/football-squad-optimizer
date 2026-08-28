"""Batch-level E2E and failure semantics for deterministic horizon planning."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pytest
from scripts.run_transfer_horizon_batch import _horizons
from tests.unit.test_horizon_application import _request, _world

from squadopt.application import (
    HorizonBatchRequest,
    HorizonBatchResult,
    HorizonPlanRequest,
    HorizonPlanResult,
    plan_horizon,
    plan_horizon_batch,
)
from squadopt.data.errors import DataError


def _batch_request(tmp_path: Path, *, horizons: tuple[int, ...] = (1, 3)) -> HorizonBatchRequest:
    world = _world(tmp_path)
    single = _request(world, tmp_path)
    return HorizonBatchRequest(
        snapshot_root=single.snapshot_root,
        ledger_root=single.ledger_root,
        artifact_root=single.artifact_root,
        in_season_projection=single.in_season_projection,
        snapshot_id=single.snapshot_id,
        horizons=horizons,
        shadow_horizons=frozenset(value for value in horizons if value > 1),
    )


def test_batch_joins_control_and_shadow_without_publishing_local_paths(tmp_path: Path) -> None:
    request = _batch_request(tmp_path)

    first = plan_horizon_batch(request)
    second = plan_horizon_batch(request)

    assert isinstance(first, HorizonBatchResult)
    assert [plan.last_gameweek - plan.first_gameweek + 1 for plan in first.plans] == [1, 3]
    assert first.created is True and second.created is False
    assert first.batch_fingerprint == second.batch_fingerprint
    assert first.manifest_path == second.manifest_path
    assert first.manifest == second.manifest

    raw = first.manifest_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert [row["decision_role"] for row in payload["horizons"]] == [
        "live_control",
        "research_shadow",
    ]
    assert payload["public_advice_policy"] == "only_the_one_week_control_is_decision_eligible"
    assert str(tmp_path) not in raw
    assert "%" not in raw
    assert "probability" not in raw.lower()
    assert "olas\u0131l\u0131k" not in raw.lower()


def test_a_failed_shadow_leaves_reusable_evidence_but_no_batch_manifest(tmp_path: Path) -> None:
    request = _batch_request(tmp_path)

    def fail_second(single: HorizonPlanRequest) -> HorizonPlanResult:
        if single.gameweeks == 3:
            raise DataError("synthetic shadow failure")
        return plan_horizon(single)

    with pytest.raises(DataError, match="synthetic shadow failure"):
        plan_horizon_batch(request, planner=fail_second)

    assert list(request.artifact_root.rglob("transfer_horizon_*.json"))
    assert not list(request.artifact_root.rglob("horizon_batch_*.json"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"horizons": (3, 5), "shadow_horizons": frozenset({3, 5})}, "one-week"),
        ({"horizons": (1, 3, 3)}, "unique"),
        ({"horizons": (3, 1)}, "increasing"),
        ({"horizons": (1, 2)}, "Unsupported"),
        ({"shadow_horizons": frozenset({5})}, "subset"),
        ({"shadow_horizons": frozenset({1})}, "live control"),
    ],
)
def test_batch_contract_rejects_ambiguous_policy(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    request = HorizonBatchRequest(
        snapshot_root=tmp_path / "snapshots",
        ledger_root=tmp_path / "ledger",
        artifact_root=tmp_path / "artifacts",
        in_season_projection=tmp_path / "handoff.json",
        horizons=(1,),
        shadow_horizons=frozenset(),
    )
    with pytest.raises(DataError, match=message):
        replace(request, **changes)


def test_cli_horizon_parser_is_explicit() -> None:
    assert _horizons("1,3,5") == (1, 3, 5)
    with pytest.raises(argparse.ArgumentTypeError, match="integers"):
        _horizons("one,three")
