"""Official captured ranks are evidence of responsibility, not goal frequency."""

import json

import pandas as pd
import pytest

from squadopt.data.sources.fpl_set_pieces import captured_taker_priorities


def test_capture_uses_stable_code_and_preserves_unknown_and_ties():
    payload = {
        "elements": [
            {"id": 1, "code": 101, "penalties_order": 1, "direct_freekicks_order": None},
            {"id": 2, "code": 102, "penalties_order": 1, "corners_and_indirect_freekicks_order": 2},
        ]
    }
    table = captured_taker_priorities(json.dumps(payload).encode()).set_index("player_id")
    assert list(table.index) == [101, 102]
    assert table.penalties_order.tolist() == [1, 1]
    assert table.direct_freekicks_order.isna().all()
    assert pd.isna(table.loc[101, "corners_and_indirect_freekicks_order"])
    assert table.loc[102, "corners_and_indirect_freekicks_order"] == 2


@pytest.mark.parametrize("rank", [True, False, 0, -1, 1.5, "1"])
def test_invalid_ranks_are_not_silently_coerced(rank):
    with pytest.raises(ValueError, match="integer ranks"):
        captured_taker_priorities(
            json.dumps({"elements": [{"code": 101, "penalties_order": rank}]}).encode()
        )


def test_duplicate_stable_codes_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        captured_taker_priorities(b'{"elements":[{"code":101},{"code":101}]}')
