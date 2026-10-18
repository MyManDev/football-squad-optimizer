"""The declared second feature contract of the Phase C components.

v2 adds the one-gameweek and ten-gameweek windows for minutes and appearance over the same
shifted primitives; nothing else changes. These tests pin its columns, the v1 export and the
walk refusing it, the v2 export naming its table and manifest block, the comparison arm that
reads it against the gradient-boosting arm on the v1 features, and the two refusals that keep
the feature contracts of a pair as declared: the plain arm refuses a pair on two contracts,
and the windows arm refuses a control that is not on the v1 contract.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
from scripts.compare_component_oof_development import main as compare_main
from scripts.export_component_oof import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    OOF_CONTRACT_VERSION,
    build_oof_table,
    main,
)
from tests.unit.test_export_component_oof_v2 import (
    LOCKED,
    ORDER,
    SMALL,
    THREE,
    _decisions,
    _panels,
)

from squadopt.data.errors import DataError
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
    COMPONENT_MODEL_VERSION,
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


def _common(*, estimator: str | None = GRADIENT_BOOSTING_ESTIMATOR) -> tuple[str, ...]:
    """The v2 development scope over the three synthetic seasons, on one estimator."""

    scope = ("--development-scope", "v2", "--seasons", ",".join(THREE))
    return scope if estimator is None else (*scope, "--estimator", estimator)


def _pair(directory: Path, *exports: tuple[Path, Path, Path]) -> Path:
    """Copy the exported tables, rosters and manifests into one artifact directory."""

    directory.mkdir()
    for paths in exports:
        for path in paths:
            (directory / path.name).write_bytes(path.read_bytes())
    return directory


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


def test_the_walk_refuses_an_unknown_feature_contract() -> None:
    with pytest.raises(DataError, match="Unknown feature contract 'v3'"):
        build_oof_table(
            _frame_v2(6, 12, ORDER),
            _decisions(range(3, 5)),
            season_order=ORDER,
            config=SMALL,
            contract_version=DEVELOPMENT_OOF_CONTRACT_VERSION,
            feature_contract="v3",
        )


def test_the_v1_contract_walk_refuses_the_v2_feature_contract() -> None:
    # The frame carries every v2 column, so only the contract guard can refuse this walk.
    with pytest.raises(DataError, match="v2 feature contract is a Phase C v2 development arm"):
        build_oof_table(
            _frame_v2(6, 12, ORDER),
            _decisions(range(3, 5)),
            season_order=ORDER,
            config=SMALL,
            contract_version=OOF_CONTRACT_VERSION,
            feature_contract="v2",
        )


def test_the_v2_export_names_the_feature_contract_and_the_comparison_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = _run_export(tmp_path / "control", monkeypatch, *_common())
    candidate = _run_export(
        tmp_path / "candidate", monkeypatch, *_common(), "--feature-contract", "v2"
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

    artifact_dir = _pair(tmp_path / "pair", control, candidate)
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
    arms = report["arms"]
    assert arms["control"]["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert arms["candidate"]["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert arms["control"]["feature_contract_version"] == FEATURE_CONTRACT_VERSION
    assert arms["candidate"]["feature_contract_version"] == FEATURE_CONTRACT_VERSION_V2
    assert report["primary_season"]["season"] == LOCKED


def test_the_plain_arm_refuses_a_pair_on_two_feature_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A linear control on the v1 features and a boosted candidate on the v2 features pass
    # every check of the plain gradient-boosting arm that runs before the contract agreement
    # (equal weighting, the linear and the boosted model versions, one commit), so the
    # refusal can only come from the two arms carrying different feature contracts.
    control = _run_export(tmp_path / "control", monkeypatch, *_common(estimator=None))
    candidate = _run_export(
        tmp_path / "candidate", monkeypatch, *_common(), "--feature-contract", "v2"
    )
    control_manifest = json.loads(control[2].read_text(encoding="utf-8"))
    assert control_manifest["model_version"] == COMPONENT_MODEL_VERSION
    assert control_manifest["feature_contract_version"] == FEATURE_CONTRACT_VERSION
    artifact_dir = _pair(tmp_path / "pair", control, candidate)
    capsys.readouterr()

    returned = compare_main(
        [
            "--artifact-dir",
            str(artifact_dir),
            "--candidate-arm",
            "gradient_boosting",
            "--control",
            control[0].name[:-4],
            "--candidate",
            candidate[0].name[:-4],
            "--output-dir",
            str(tmp_path / "comparison"),
        ]
    )

    assert returned == 1
    assert "The two arms disagree on feature_contract_version." in capsys.readouterr().out
    assert not (tmp_path / "comparison").exists()


def test_the_windows_arm_refuses_a_control_on_the_v2_feature_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The v2 table read as its own control passes every other check of the windows arm, so
    # only the declared control contract can refuse it.
    candidate = _run_export(
        tmp_path / "candidate", monkeypatch, *_common(), "--feature-contract", "v2"
    )
    artifact_dir = _pair(tmp_path / "pair", candidate)
    capsys.readouterr()

    returned = compare_main(
        [
            "--artifact-dir",
            str(artifact_dir),
            "--candidate-arm",
            "gradient_boosting_windows",
            "--control",
            candidate[0].name[:-4],
            "--output-dir",
            str(tmp_path / "comparison"),
        ]
    )

    assert returned == 1
    expected = (
        "The gradient_boosting_windows control must carry the feature contract "
        f"{FEATURE_CONTRACT_VERSION!r}, got {FEATURE_CONTRACT_VERSION_V2!r}."
    )
    assert expected in capsys.readouterr().out
    assert not (tmp_path / "comparison").exists()
