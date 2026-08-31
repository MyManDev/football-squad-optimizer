"""Binding an export to one exact model: every refusal the contract promises.

Several of these defects are named first by ``squadopt.preflight``, which this
module runs before its own checks; the assertions below pin that the defect is
refused and named, not which of the two layers speaks first. The module's own
checks stay as defence in depth for callers holding an already-preflighted frame.
"""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
import pytest

from squadopt.experiments.residual_manifest import (
    DECLARED_PREDICTED_POINTS_DECIMALS,
    RESIDUAL_SOURCE_MANIFEST_CONTRACT_VERSION,
    ResidualSourceError,
    load_residual_source_manifest,
    manifest_to_dict,
    write_residual_source_manifest,
)
from squadopt.experiments.shadow_report import LOCKED_HOLDOUT_SEASON, ShadowReportError
from squadopt.preflight import RESIDUAL_EXPORT_COLUMNS

MODEL_NAME = "squadopt-deterministic-baseline"
MODEL_VERSION = "in-season-carry-over-v1"
FEATURE_CONTRACT = "in-season-carry-over-features-v1"
COMMIT = "a" * 40
POSITIONS = ("GK", "DEF", "MID", "FWD")


def _table(seasons: tuple[str, ...] = ("2021-22", "2022-23")) -> pd.DataFrame:
    rows = []
    for season in seasons:
        for gameweek in (2, 3, 4):
            for index in range(6):
                predicted = 2.0 + index * 0.5
                realized = predicted + (index - 2)
                rows.append(
                    {
                        "fold_id": f"{season}-gw{gameweek:02d}",
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": 100 + index,
                        "team_id": 1 + index % 3,
                        "position": POSITIONS[index % 4],
                        "predicted_points": predicted,
                        "realized_points": float(realized),
                        "residual": float(realized) - predicted,
                    }
                )
    return pd.DataFrame(rows).loc[:, list(RESIDUAL_EXPORT_COLUMNS)]


def _write(tmp_path: Path, table: pd.DataFrame, **overrides: object) -> tuple[Path, Path]:
    table_path = tmp_path / "in_season_residuals.csv"
    with table_path.open("w", encoding="utf-8", newline="") as handle:
        table.to_csv(handle, index=False, lineterminator="\n")
    digest = hashlib.sha256(table_path.read_bytes()).hexdigest()
    document: dict[str, object] = {
        "contract_version": "oos_residual_export_v1",
        "candidate_label": "in_season_carry_over_blend",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "feature_contract_version": FEATURE_CONTRACT,
        "training_contract_version": MODEL_VERSION,
        "evaluation_objective": "single_gameweek_realized_squad_points_v1",
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] <= 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": COMMIT,
        "dataset_snapshot_id": "vaastav-fpl@" + "b" * 40,
        "table_sha256": digest,
        "created_at_utc": "2026-08-28T12:00:00+00:00",
        "locked_holdout_accessed": False,
        "predicted_points_decimals": DECLARED_PREDICTED_POINTS_DECIMALS,
    }
    document.update(overrides)
    manifest_path = tmp_path / "in_season_residuals.manifest.json"
    manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return table_path, manifest_path


def _load(table_path: Path, manifest_path: Path, **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "expect_model_name": MODEL_NAME,
        "expect_model_version": MODEL_VERSION,
    }
    kwargs.update(overrides)
    return load_residual_source_manifest(table_path, manifest_path, **kwargs)  # type: ignore[arg-type]


def test_a_valid_export_binds_and_round_trips(tmp_path: Path) -> None:
    manifest = _load(*_write(tmp_path, _table()))
    assert manifest.contract_version == RESIDUAL_SOURCE_MANIFEST_CONTRACT_VERSION  # type: ignore[attr-defined]
    assert manifest.model_version == MODEL_VERSION  # type: ignore[attr-defined]
    assert manifest.source_seasons == ("2021-22", "2022-23")  # type: ignore[attr-defined]
    assert manifest.decision_gameweek_min == 2  # type: ignore[attr-defined]
    assert manifest.opening_gameweeks_included is False  # type: ignore[attr-defined]
    assert manifest.locked_holdout_excluded is True  # type: ignore[attr-defined]
    document = manifest_to_dict(manifest)  # type: ignore[arg-type]
    assert isinstance(document, Mapping)
    assert document["first_fold_id"] == "2021-22-gw02"
    assert document["last_fold_id"] == "2022-23-gw04"


def test_serialization_is_deterministic_and_lf(tmp_path: Path) -> None:
    manifest = _load(*_write(tmp_path, _table()))
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    write_residual_source_manifest(manifest, first)  # type: ignore[arg-type]
    write_residual_source_manifest(manifest, second)  # type: ignore[arg-type]
    assert first.read_bytes() == second.read_bytes()
    assert b"\r" not in first.read_bytes()


def test_a_modified_residual_table_is_rejected(tmp_path: Path) -> None:
    table_path, manifest_path = _write(tmp_path, _table())
    table_path.write_text(
        table_path.read_text(encoding="utf-8").replace("2.0", "2.5", 1), encoding="utf-8"
    )
    with pytest.raises(ResidualSourceError, match="changed after it was described"):
        _load(table_path, manifest_path)


def test_a_wrong_model_name_or_version_is_rejected(tmp_path: Path) -> None:
    paths = _write(tmp_path, _table())
    with pytest.raises(ResidualSourceError, match="may not describe another"):
        _load(*paths, expect_model_name="squadopt-learned-rate")
    with pytest.raises(ResidualSourceError, match="may not describe another"):
        _load(*paths, expect_model_version="form_window_05_v1")


def test_a_wrong_feature_contract_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResidualSourceError, match="feature contract"):
        _load(*_write(tmp_path, _table()), expect_feature_contract_version="form_window_v1")


def test_a_missing_manifest_or_table_is_rejected(tmp_path: Path) -> None:
    table_path, manifest_path = _write(tmp_path, _table())
    manifest_path.unlink()
    with pytest.raises(ResidualSourceError, match="manifest not found"):
        _load(table_path, manifest_path)
    table_path.unlink()
    with pytest.raises(ResidualSourceError, match="table not found"):
        _load(table_path, manifest_path)


def test_duplicate_rows_are_rejected(tmp_path: Path) -> None:
    table = _table()
    doubled = pd.concat([table, table.head(1)], ignore_index=True)
    with pytest.raises(ResidualSourceError, match="repeat a"):
        _load(*_write(tmp_path, doubled))


def test_non_finite_and_missing_residuals_are_rejected(tmp_path: Path) -> None:
    table = _table()
    table.loc[0, "residual"] = float("nan")
    with pytest.raises(ResidualSourceError, match=r"non-finite|non-numeric|missing"):
        _load(*_write(tmp_path, table))
    infinite = _table()
    infinite.loc[0, "predicted_points"] = float("inf")
    infinite.loc[0, "residual"] = float("inf")
    with pytest.raises(ResidualSourceError, match=r"non-finite|missing or non-numeric"):
        _load(*_write(tmp_path, infinite))


def test_the_locked_holdout_is_refused_in_the_source(tmp_path: Path) -> None:
    table = _table(seasons=("2024-25", LOCKED_HOLDOUT_SEASON))
    with pytest.raises(ResidualSourceError, match="forbidden"):
        _load(*_write(tmp_path, table))


def test_a_cutoff_that_holds_nothing_out_is_rejected(tmp_path: Path) -> None:
    manifest = _load(*_write(tmp_path, _table()))
    source = manifest.to_shadow_source(cutoff_fold_id="2021-22-gw04")  # type: ignore[attr-defined]
    assert source.cutoff_fold_id == "2021-22-gw04"
    with pytest.raises(ResidualSourceError, match="leaves no fold after it"):
        manifest.to_shadow_source(cutoff_fold_id="2022-23-gw04")  # type: ignore[attr-defined]
    with pytest.raises(ResidualSourceError, match="precedes the export"):
        manifest.to_shadow_source(cutoff_fold_id="2020-21-gw02")  # type: ignore[attr-defined]


def test_a_malformed_fingerprint_or_fold_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResidualSourceError, match="SHA-256"):
        _load(*_write(tmp_path, _table(), table_sha256="not-a-digest"))
    manifest = _load(*_write(tmp_path, _table()))
    with pytest.raises(ResidualSourceError, match="does not match the contract"):
        manifest.to_shadow_source(cutoff_fold_id="round-two")  # type: ignore[attr-defined]


def test_empty_generation_provenance_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResidualSourceError, match=r"repository_commit|generation provenance"):
        _load(*_write(tmp_path, _table(), repository_commit=""))


def test_a_season_the_manifest_does_not_declare_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResidualSourceError, match="seasons"):
        _load(*_write(tmp_path, _table(), development_seasons=["2021-22"]))


def test_a_wrong_opening_gameweek_claim_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResidualSourceError, match="opening"):
        _load(*_write(tmp_path, _table(), opening_gameweeks_included=True))


def test_a_stale_rounding_declaration_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResidualSourceError, match="predicted_points_decimals"):
        _load(*_write(tmp_path, _table(), predicted_points_decimals=4))


def test_a_missing_rounding_declaration_is_rejected(tmp_path: Path) -> None:
    table_path, manifest_path = _write(tmp_path, _table())
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    del document["predicted_points_decimals"]
    manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ResidualSourceError, match="predicted_points_decimals is missing"):
        _load(table_path, manifest_path)


def test_the_bound_source_is_accepted_by_the_phase_2a_contract(tmp_path: Path) -> None:
    manifest = _load(*_write(tmp_path, _table()))
    source = manifest.to_shadow_source(cutoff_fold_id="2021-22-gw04")  # type: ignore[attr-defined]
    assert source.model_version == MODEL_VERSION
    assert LOCKED_HOLDOUT_SEASON not in source.seasons


def test_the_writer_refuses_the_published_site_tree(tmp_path: Path) -> None:
    manifest = _load(*_write(tmp_path, _table()))
    target = tmp_path / "web" / "public" / "data" / "source.json"
    with pytest.raises(ResidualSourceError, match="web/public"):
        write_residual_source_manifest(manifest, target)  # type: ignore[arg-type]
    assert not target.exists()


def test_a_holdout_season_cannot_reach_the_shadow_source_even_if_bound(tmp_path: Path) -> None:
    """Defence in depth: Phase 2A refuses it too, so both layers must be defeated."""

    manifest = _load(*_write(tmp_path, _table()))
    poisoned = type(manifest)(  # type: ignore[operator]
        **{
            **{
                field: getattr(manifest, field)
                for field in manifest.__dataclass_fields__  # type: ignore[attr-defined]
            },
            "source_seasons": (*manifest.source_seasons, LOCKED_HOLDOUT_SEASON),  # type: ignore[attr-defined]
        }
    )
    with pytest.raises(ShadowReportError, match="locked holdout"):
        poisoned.to_shadow_source(cutoff_fold_id="2021-22-gw04")
