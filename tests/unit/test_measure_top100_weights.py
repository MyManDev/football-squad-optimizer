"""A changed score alone is not evidence that a decision improved or even changed."""

from scripts.measure_top100_weights import summarize_rows


def test_summary_pairs_solved_members_and_ignores_score_only_changes():
    base = {
        "window": 1,
        "weight_percent": 0,
        "member": 1,
        "status": "solved",
        "solver_status": "OPTIMAL",
        "starting_xi": [1, 2],
        "captain": 1,
        "moves": [[3, 4]],
        "base_first_week_net": 12,
        "mean_xi_support": 0.4,
        "weighted_first_week_net": 12,
    }
    rows = [
        base,
        {**base, "member": 2},
        {**base, "weight_percent": 50, "starting_xi": [2, 1], "weighted_first_week_net": 18},
        {"window": 1, "weight_percent": 50, "member": 2, "status": "refused"},
    ]
    result = summarize_rows(rows)[1]
    assert result["members"] == 2
    assert result["matched"] == 1
    assert result["refused"] == 1
    assert result["changed_first_week"] == 0
    assert result["base_first_week_net_delta"] == 0
    assert result["realized_net_points"] is None
