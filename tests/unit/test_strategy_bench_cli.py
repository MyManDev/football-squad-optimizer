"""The strategy bench CLI must refuse the locked holdout before any loader runs.

The first bench run (8f8d3cb) loaded the panel with the loader's default season
list, which includes the locked 2025-26 holdout; these tests pin the corrected
boundary: validation precedes loading, the history list is explicit, and the
artifact's provenance and ``holdout_untouched`` derive from what was actually
loaded rather than being asserted.
"""

import sys

import pandas as pd
import pytest
import scripts.measure_strategy_bench as cli
from scripts._experiment_cli import artifact_metadata


def test_history_seasons_are_explicit_and_exclude_the_holdout() -> None:
    assert cli.HISTORY_SEASONS == ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    assert cli.LOCKED_HOLDOUT_SEASON not in cli.HISTORY_SEASONS


def test_requesting_the_holdout_never_calls_the_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli, "build_panel", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["measure_strategy_bench", "--seasons", "2025-26"])
    assert cli.main() == 1
    assert calls == []


def test_a_season_outside_the_population_never_calls_the_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli, "build_panel", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(sys, "argv", ["measure_strategy_bench", "--seasons", "2020-21"])
    assert cli.main() == 1
    assert calls == []


def test_the_loader_receives_the_explicit_history_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_build_panel(root: object, **kwargs: object) -> pd.DataFrame:
        captured.update(kwargs)
        raise RuntimeError("stop after capture")

    monkeypatch.setattr(cli, "build_panel", fake_build_panel)
    monkeypatch.setattr(sys, "argv", ["measure_strategy_bench"])
    with pytest.raises(RuntimeError, match="stop after capture"):
        cli.main()
    assert captured["seasons"] == cli.HISTORY_SEASONS
    assert cli.LOCKED_HOLDOUT_SEASON not in captured["seasons"]  # type: ignore[operator]


def test_a_panel_carrying_the_holdout_aborts_before_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = pd.DataFrame({"season": ["2024-25", cli.LOCKED_HOLDOUT_SEASON]})
    monkeypatch.setattr(cli, "build_panel", lambda *a, **k: panel)

    def fail(*a: object, **k: object) -> None:
        pytest.fail("nothing downstream of the invariant may run")

    monkeypatch.setattr(cli, "build_control_residual_table", fail)
    monkeypatch.setattr(cli, "write_json", fail)
    monkeypatch.setattr(cli, "write_text", fail)
    monkeypatch.setattr(sys, "argv", ["measure_strategy_bench"])
    assert cli.main() == 1


def test_loaded_seasons_reads_the_panel_not_the_configuration() -> None:
    panel = pd.DataFrame({"season": ["2021-22", "2021-22", "2020-21"]})
    assert cli._loaded_seasons(panel) == ("2020-21", "2021-22")


def test_artifact_metadata_records_the_actually_loaded_seasons() -> None:
    meta = artifact_metadata(panel_rows=3, history_seasons=("2020-21", "2021-22"))
    provenance = meta["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["history_seasons"] == ["2020-21", "2021-22"]


def test_artifact_metadata_default_stays_the_full_supported_range() -> None:
    provenance = artifact_metadata(panel_rows=3)["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["history_seasons"][-1] == "2025-26"
