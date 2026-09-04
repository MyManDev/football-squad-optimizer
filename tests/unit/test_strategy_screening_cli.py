"""The strategy screening must refuse the locked holdout at the loader boundary."""

import sys

import pandas as pd
import pytest
import scripts.measure_strategy_screening as cli


def test_history_seasons_are_explicit_and_exclude_the_holdout() -> None:
    assert cli.HISTORY_SEASONS == ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
    assert cli.LOCKED_HOLDOUT_SEASON not in cli.HISTORY_SEASONS


def test_the_loader_receives_only_the_explicit_history_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_build_panel(root: object, **kwargs: object) -> pd.DataFrame:
        captured.update(kwargs)
        raise RuntimeError("stop after loader boundary")

    monkeypatch.setattr(cli, "build_panel", fake_build_panel)
    monkeypatch.setattr(sys, "argv", ["measure_strategy_screening"])
    with pytest.raises(RuntimeError, match="loader boundary"):
        cli.main()

    assert captured["seasons"] == cli.HISTORY_SEASONS
    assert cli.LOCKED_HOLDOUT_SEASON not in captured["seasons"]  # type: ignore[operator]


def test_an_unexpected_holdout_row_aborts_before_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = pd.DataFrame({"season": ["2024-25", cli.LOCKED_HOLDOUT_SEASON]})
    monkeypatch.setattr(cli, "build_panel", lambda *args, **kwargs: panel)

    def fail(*args: object, **kwargs: object) -> None:
        pytest.fail("nothing downstream of the holdout invariant may run")

    monkeypatch.setattr(cli, "build_control_residual_table", fail)
    monkeypatch.setattr(cli, "write_json", fail)
    monkeypatch.setattr(cli, "write_text", fail)
    monkeypatch.setattr(sys, "argv", ["measure_strategy_screening"])
    assert cli.main() == 1


def test_loaded_seasons_and_metadata_come_from_the_panel() -> None:
    panel = pd.DataFrame({"season": ["2021-22", "2021-22", "2020-21"]})
    loaded = cli._loaded_seasons(panel)
    assert loaded == ("2020-21", "2021-22")
    provenance = cli._metadata(
        panel_rows=len(panel), created_utc="2026-08-28T12:00:00+00:00", loaded_seasons=loaded
    )["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["history_seasons"] == ["2020-21", "2021-22"]
