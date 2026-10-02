"""Synthetic training-population wiring: no archive read, model fit or live capture."""

from pathlib import Path

import pandas as pd
import pytest
from tests.unit.test_football_fixture_components import _producer_world

from squadopt.data.sources.football_history import ARCHIVE_SEASONS


def _selection_world(monkeypatch):
    producer, snapshot, _ = _producer_world(monkeypatch)
    accesses = []
    fits = []
    monkeypatch.setattr(producer, "ARCHIVE_SEASONS", ARCHIVE_SEASONS)

    def archive(root, *, seasons=None):
        accesses.append(("archive", seasons))
        return pd.DataFrame(
            {
                "season": list(seasons),
                "kickoff": pd.to_datetime([f"{season[:4]}-10-01T15:00:00Z" for season in seasons]),
            }
        )

    def captured(*args, **kwargs):
        accesses.append(("captured", kwargs["season"]))
        return pd.DataFrame(
            {"season": ["2026-27"], "kickoff": [pd.Timestamp("2026-09-01T15:00:00Z")]}
        )

    def read_bytes(path):
        accesses.append(("hash", path.as_posix()))
        return path.as_posix().encode()

    class Model:
        def __init__(self, training, history, *, cutoff):
            self.cutoff = cutoff
            fits.append((training.copy(), history.copy()))

    monkeypatch.setattr(producer, "archive_history", archive)
    monkeypatch.setattr(producer, "captured_history", captured)
    monkeypatch.setattr(
        producer, "causal_training", lambda history: history.loc[history.season.ne("2022-23")]
    )
    monkeypatch.setattr(producer, "FixtureFootballModel", Model)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    return producer, snapshot, accesses, fits


def test_allowlist_prevents_excluded_archive_and_current_reads_and_records_populations(
    monkeypatch, tmp_path
):
    producer, snapshot, accesses, fits = _selection_world(monkeypatch)
    served, companion = producer.produce_football_components(
        snapshot,
        tmp_path,
        training_seasons=("2024-25", "2022-23", "2023-24"),
    )
    assert len(fits) == 1
    assert accesses[0] == ("archive", ("2022-23", "2023-24", "2024-25"))
    assert not any(kind == "captured" for kind, _ in accesses)
    hashes = [path for kind, path in accesses if kind == "hash"]
    assert len(hashes) == 12
    assert all("2025-26" not in path and "2026-27" not in path for path in hashes)
    selection = served["training_selection"]
    assert selection == {
        "contract_version": "football_training_selection_v1",
        "allowed_seasons": ["2022-23", "2023-24", "2024-25"],
        "archive_seasons_read": ["2022-23", "2023-24", "2024-25"],
        "captured_history_included": False,
        "captured_history_season": None,
        "prior_only_seasons": ["2022-23"],
        "history_rows_by_season": {"2022-23": 1, "2023-24": 1, "2024-25": 1},
        "supervised_rows_by_season": {"2023-24": 1, "2024-25": 1},
    }
    assert companion["training_selection"] == selection
    assert companion["training_selection"] is not selection
    assert companion["forecast_fingerprint"] == served["fingerprint"]
    assert served["training_rows"] == 2


def test_current_season_only_never_reads_or_hashes_an_archive(monkeypatch, tmp_path):
    producer, snapshot, accesses, fits = _selection_world(monkeypatch)
    result = producer.produce_football_forecast(snapshot, tmp_path, training_seasons=("2026-27",))
    assert accesses == [("captured", "2026-27")]
    assert len(fits) == 1
    assert result["archive_hashes"] == {}
    assert result["training_selection"]["captured_history_season"] == "2026-27"
    assert result["training_selection"]["supervised_rows_by_season"] == {"2026-27": 1}


def test_explicit_current_inclusion_is_identified_and_changes_fingerprint(monkeypatch, tmp_path):
    producer, snapshot, _, fits = _selection_world(monkeypatch)
    archive = producer.produce_football_forecast(snapshot, tmp_path, training_seasons=("2024-25",))
    mixed = producer.produce_football_forecast(
        snapshot, tmp_path, training_seasons=("2024-25", "2026-27")
    )
    assert len(fits) == 2
    assert archive["fingerprint"] != mixed["fingerprint"]
    assert mixed["training_selection"]["history_rows_by_season"] == {"2024-25": 1, "2026-27": 1}
    assert mixed["training_rows"] == 2


@pytest.mark.parametrize(
    "selected", [(), "2024-25", ("2024-25", "2024-25"), ("2024-25", "2099-00"), (None,), (2024,)]
)
def test_invalid_whole_selection_fails_before_any_training_read_or_fit(
    monkeypatch, tmp_path, selected
):
    producer, snapshot, accesses, fits = _selection_world(monkeypatch)
    with pytest.raises(ValueError, match="Training seasons"):
        producer.produce_football_forecast(snapshot, tmp_path, training_seasons=selected)
    assert accesses == []
    assert fits == []


def test_empty_selected_history_fails_before_fit_or_hash(monkeypatch, tmp_path):
    producer, snapshot, accesses, fits = _selection_world(monkeypatch)
    monkeypatch.setattr(producer, "captured_history", lambda *a, **kw: pd.DataFrame())
    with pytest.raises(ValueError, match="no usable history"):
        producer.produce_football_forecast(snapshot, tmp_path, training_seasons=("2026-27",))
    assert accesses == []
    assert fits == []
