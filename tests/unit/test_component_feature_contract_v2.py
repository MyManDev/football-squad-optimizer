"""The declared second feature contract of the Phase C components.

v2 adds the one-gameweek and ten-gameweek windows for minutes and appearance over the same
shifted primitives; nothing else changes. These tests pin its columns, the v1 export refusing
it, the v2 export naming its table and manifest block, and the comparison arm that reads it
against the gradient-boosting arm on the v1 features.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
from scripts.compare_component_oof_development import main as compare_main
from scripts.export_component_oof import DEVELOPMENT_OOF_CONTRACT_VERSION, main
from tests.unit.test_export_component_oof_v2 import LOCKED, THREE, _decisions, _panels

from squadopt.evaluation import read_phase_c_component_handoff
from squadopt.features.component_targets import build_component_targets
from squadopt.prediction.component_dataset import (
    COMPONENT_FEATURE_CONFIG_V2,
    FEATURE_CONTRACT_VERSION,
    FEATURE_CONTRACT_VERSION_V2,
    FEATURE_CONTRACTS,
    build_component_frame,
    component_feature_columns,
)
from squadopt.prediction.component_models import (
    GRADIENT_BOOSTING_ESTIMATOR,
    GRADIENT_BOOSTING_MODEL_VERSION,
)

V2_COLUMNS = component_feature_columns(COMPONENT_FEATURE_CONFIG_V2)


def _frame_v2(gameweeks: int, players: int, seasons: Sequence[str] = THREE) -> pd.DataFrame:
    """A synthetic frame carrying every v2 feature column, in the shape the export reads."""

    panel = _panels(gameweeks, players, seasons)
    features = panel.loc[:, ["season", "gameweek", "player_id", "price_tenths"]].copy(deep=True)
    for offset, column in enumerate(V2_COLUMNS, start=1):
        if column == "price_tenths":
            continue
        if column == "fixture_count":
            features[column] = (1 + (panel["player_id"] % 4 == 0)).astype("int64")
        elif column == "home_fixture_count":
            features[column] = (panel["player_id"] % 2).astype("int64")
        else:
            features[column] = (panel["player_id"] % 7 * offset + panel["gameweek"]).astype(
                "float64"
            )
    return build_component_frame(
        features, build_component_targets(panel), config=COMPONENT_FEATURE_CONFIG_V2
    )


def _run_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *arguments: str
) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    panel = _panels(6, 12, THREE)
    frame = _frame_v2(6, 12, THREE)
    monkeypatch.setattr(
        "scripts.export_component_oof._modelling_frame",
        lambda archive_root, seasons, **_: (panel, frame),
    )
    monkeypatch.setattr(
        "scripts.export_component_oof.season_ranks",
        lambda panel: {season: rank for rank, season in enumerate(THREE)},
    )
    monkeypatch.setattr(
        "scripts.export_component_oof.walk_forward_decision_points",
        lambda panel, *, seasons: _decisions(range(3, 7), tuple(seasons)),
    )
    monkeypatch.setattr("scripts.export_component_oof._git_revision", lambda: ("0" * 40, False))
    output = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--archive-root",
            str(tmp_path),
            "--output-dir",
            str(output),
            "--minimum-training-rows",
            "10",
            *arguments,
        ],
    )
    assert main() == 0
    written = sorted(output.glob("*.manifest.json"))
    assert len(written) == 1
    name = written[0].name[: -len(".manifest.json")]
    return output / f"{name}.csv", output / f"{name}.roster.csv", written[0]


def test_the_v2_contract_adds_the_one_and_ten_week_windows_only() -> None:
    v1 = component_feature_columns()
    assert FEATURE_CONTRACTS["v1"] == (FEATURE_CONTRACT_VERSION, FEATURE_CONTRACTS["v1"][1])
    assert FEATURE_CONTRACTS["v2"][0] == FEATURE_CONTRACT_VERSION_V2 != FEATURE_CONTRACT_VERSION
    added = [column for column in V2_COLUMNS if column not in v1]
    assert added == [
        "minutes_last_1",
        "minutes_last_10",
        "appearance_rate_last_1",
        "appearance_rate_last_10",
    ]
    assert all(column in V2_COLUMNS for column in v1)


def test_the_v1_scope_refuses_the_v2_feature_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["export_component_oof", "--feature-contract", "v2"])
    assert main() == 1
    assert "--development-scope v2" in capsys.readouterr().out


def test_the_v2_export_names_the_feature_contract_and_the_comparison_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seasons = ",".join(THREE)
    common = (
        "--development-scope",
        "v2",
        "--estimator",
        GRADIENT_BOOSTING_ESTIMATOR,
        "--seasons",
        seasons,
    )
    control = _run_export(tmp_path / "control", monkeypatch, *common)
    candidate = _run_export(
        tmp_path / "candidate", monkeypatch, *common, "--feature-contract", "v2"
    )
    table_path, _, manifest_path = candidate
    assert table_path.name.endswith("_equal_gradient_boosting_features_v2.csv")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["feature_contract_version"] == FEATURE_CONTRACT_VERSION_V2
    assert manifest["feature_contract"]["minutes_windows"] == [1, 3, 5, 10]
    assert manifest["feature_columns"] == list(V2_COLUMNS)
    assert "--feature-contract v2" in manifest["reproduce"]
    assert all(
        record["feature_contract_version"] == FEATURE_CONTRACT_VERSION_V2
        for record in manifest["folds"]
    )
    handoff = read_phase_c_component_handoff(
        *candidate, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
    )
    assert handoff.feature_contract_version == FEATURE_CONTRACT_VERSION_V2
    assert handoff.model_version == GRADIENT_BOOSTING_MODEL_VERSION
    control_manifest = json.loads(control[2].read_text(encoding="utf-8"))
    assert control_manifest["feature_contract_version"] == FEATURE_CONTRACT_VERSION

    artifact_dir = tmp_path / "pair"
    artifact_dir.mkdir()
    for paths in (control, candidate):
        for path in paths:
            (artifact_dir / path.name).write_bytes(path.read_bytes())
    assert (
        compare_main(
            ["--artifact-dir", str(artifact_dir), "--candidate-arm", "gradient_boosting_windows"]
        )
        == 0
    )
    report = json.loads(
        (artifact_dir / "comparison_gradient_boosting_windows" / "comparison.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["arms"]["control"]["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert report["arms"]["candidate"]["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert report["primary_season"]["season"] == LOCKED
    # The plain gradient-boosting arm still demands one feature contract on both sides.
    assert (
        compare_main(
            [
                "--artifact-dir",
                str(artifact_dir),
                "--candidate-arm",
                "gradient_boosting",
                "--control",
                control[0].name[:-4],
                "--candidate",
                table_path.name[:-4],
            ]
        )
        == 1
    )
