"""Causal target windows, grouped chronological partitions and safe value diagnostics."""

import json

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments import continuation_diagnostic as module


def _store(root, *, missing_week=None):
    for directory in module.DIRECTORIES:
        for season in module.SEASONS:
            folder = root / directory
            folder.mkdir(exist_ok=True)
            weeks = [
                {
                    **dict.fromkeys(module.FEATURES, 1),
                    "gameweek": w,
                    "net_points": w * 10,
                }
                for w in range(1, 11)
                if w != missing_week
            ]
            (folder / f"{season}.json").write_text(json.dumps({"chains": [{"weeks": weeks}]}))


@pytest.mark.parametrize("window", [3, 5])
def test_target_uses_only_complete_next_calendar_weeks(tmp_path, window):
    _store(tmp_path)
    rows, digests = module.load_rows(tmp_path, window)
    assert len(digests) == 24
    assert len(rows) == 24 * (10 - window)
    first = rows.loc[rows.gameweek.eq(1)]
    assert first.target.eq(np.mean(np.arange(2, 2 + window) * 10)).all()
    assert "net_points" not in module.FEATURES
    assert not set(module.FEATURES) & {
        "captain_realized_points",
        "bench_realized_points",
        "planned_chips",
    }


def test_missing_calendar_week_does_not_shorten_return_horizon(tmp_path):
    _store(tmp_path, missing_week=4)
    rows, _ = module.load_rows(tmp_path, 3)
    assert set(rows.gameweek) == {5, 6, 7}


def test_deadline_weights_do_not_count_cloned_policies_as_new_observations():
    rows = pd.DataFrame({"season": ["s"] * 4, "gameweek": [1, 1, 1, 2], "source": list("abcd")})
    weights = module.group_weights(rows)
    assert weights[:3].sum() == pytest.approx(weights[3])


def _frame():
    return pd.DataFrame(
        [
            {
                **{k: float(w) for k in module.FEATURES},
                "gameweek": w,
                "target": 2.0 * w,
                "season": season,
                "source": season,
            }
            for season in module.SEASONS
            for w in range(1, 11)
        ]
    )


def test_unknown_and_nonfinite_observations_fall_back_without_training_leak():
    train = _frame().iloc[:10].copy()
    test = train.iloc[:3].copy()
    test.iloc[1, test.columns.get_loc("bank_after_tenths")] = 1000
    test.iloc[2, test.columns.get_loc("bank_after_tenths")] = float("nan")
    pred, info = module.fit_predict(train, test, "ridge")
    assert np.isfinite(pred).all()
    assert pred[1:].tolist() == [11.0, 11.0]
    assert info["fallback_rows"] == 2
    assert abs(pred[0] - 2.0) < abs(11.0 - 2.0)


def test_nonfinite_training_is_rejected():
    train = _frame()
    train.loc[0, "target"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        module.fit_predict(train, train, "ridge")


def test_selection_never_fits_future_seasons(monkeypatch):
    calls = []

    def fit(train, test, kind, **kwargs):
        calls.append((set(train.season), set(test.season)))
        return np.ones(len(test)), {}

    monkeypatch.setattr(module, "fit_predict", fit)
    monkeypatch.setattr(module, "block_interval", lambda *args: (0, 0))
    result = module.study(_frame())
    assert calls[:4] == [(set(module.SEASONS[:2]), {"2023-24"})] * 4
    assert calls[4:] == [(set(module.SEASONS[:3]), {"2024-25"})] * 6
    assert result["promotion"] is False
    assert result["independent_holdout"] is False
    assert result["policy_evaluated"] is False
