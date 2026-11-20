"""The family readout distinguishes violated rules, transfer ties and unproved outcomes."""

import json
from pathlib import Path

from docs.research.llmopt_phase1.benchmark import snapshots
from docs.research.llmopt_phase4.rule_cases import check_decision, rule_cases
from docs.research.llmopt_phase4.rule_readout import comparison


def test_historical_decisions_expose_the_new_rule_stimuli_without_solving():
    reference = Path(__file__).resolve().parents[2] / "docs/research/llmopt_phase4_scope_audit.json"
    controls = {
        r["case"]: r
        for r in json.loads(reference.read_bytes())["rows"]
        if r["profile"] == "served_no_added_rule"
    }
    checked = 0
    for _, inputs in snapshots():
        for entry, captured in inputs.members.items():
            control = controls[f"gw{inputs.gameweek}-{entry}"]
            block = dict(captured, bank_tenths=control["bank_tenths"])
            week = control["server"]["weeks"][0]
            device = control["device"]["answer"]
            original = {
                "in": device["transfers_in"],
                "out": device["transfers_out"],
                "xi": device["starting_xi"],
                "squad": device["squad"],
                "captain": device["captain"],
                "chip": device["chip"],
                "bank": device["bank_after_tenths"],
                "hit": device["transfer_hit_points"],
                "objective_scaled": device["objective_scaled"],
                "published_net_scaled": (
                    device["expected_own_points"] - device["transfer_hit_points"]
                )
                * inputs.table["rules"]["expected_points_scale"],
            }
            rules, expectations = rule_cases(inputs.table, block, week, inputs.gameweek)
            reasons = {
                name: check_decision(inputs.table, block, r, original)["errors"]
                for name, r in rules.items()
            }
            assert reasons == {
                "keep": ["keep"],
                "avoid": ["avoid"],
                "buy": ["buy"],
                "club": ["club"],
                "bank": ["bank floor"],
                "hit": ["buy"],
                "frozen": [],
            }
            assert (
                len(rules["hit"]["week_rules"][0]["rules"]["buy_players"])
                == block["free_transfers"] + 1
            )
            for family, expected in expectations.items():
                if family == "hit" and inputs.gameweek == 9:
                    assert expected == dict(
                        feasible=False,
                        minimum_hit_points=4,
                        free_transfers=block["free_transfers"],
                        required_arrivals=block["free_transfers"] + 1,
                    )
                    continue
                assert expected["feasible"]
                witness = expected["witness"]
                decision = {
                    **witness,
                    "squad": sorted(
                        (set(block["held"]) - set(witness["out"])) | set(witness["in"])
                    ),
                }
                assert (
                    check_decision(inputs.table, block, rules[family], decision, published=False)[
                        "errors"
                    ]
                    == []
                )
            wrong_cost = {
                **original,
                "published_net_scaled": original["published_net_scaled"] + 0.01,
            }
            assert check_decision(inputs.table, block, rules["frozen"], wrong_cost)["errors"] == [
                "published_net_scaled"
            ]
            checked += 1
    assert checked == 20


def test_failed_or_missing_scores_never_count_as_ties_and_distinct_valid_ties_remain_visible():
    primary = dict(
        deterministic_limit=20,
        wall_seconds=1800,
        linearization=2,
        net_points=True,
        protect_hold=True,
    )
    decision = {"squad": [1], "in": [1], "out": [3], "audit": {"errors": [], "net_scaled": 12000}}
    server = dict(
        status="FEASIBLE",
        decision=decision,
        allocation=21,
        settings=primary,
        cp_statuses=["FEASIBLE"],
        cp_used=4,
        observed_cp_units=4,
        receipt_calls=1,
        native_reserved=0,
        other_solver_calls=[],
    )
    device = dict(
        status="OPTIMAL",
        decision={**decision, "squad": [2], "in": [2]},
        alternatives=[],
        selection="plain",
        statuses=["Optimal"],
    )
    result = comparison(server, device, True)
    assert result["outcome"] == "transfer_tie"
    assert not result["status_equal"]
    bad = {**decision, "audit": {"errors": ["bank floor"], "net_scaled": 12000}}
    assert comparison(server, {**device, "alternatives": [bad]}, True)["outcome"] == "mismatch"
    no_server = {**server, "status": "PLAN_NOT_FOUND", "decision": None}
    no_device = {**device, "status": "INFEASIBLE", "decision": None}
    assert comparison(no_server, no_device, False)["outcome"] == "mismatch"
    proved_server = {**no_server, "status": "INFEASIBLE"}
    proved = comparison(proved_server, no_device, False)
    assert proved["outcome"] == "both_infeasible"
    assert not proved["objective_equal"]
    assert comparison(proved_server, no_device, True, fixed_week=True)["outcome"] == "mismatch"
    assert comparison(proved_server, no_device, True)["outcome"] == "mismatch"
    assert comparison(server, device, False)["outcome"] == "mismatch"
    for incorrect in (
        dict(cp_used=0),
        dict(observed_cp_units=4.001),
        dict(receipt_calls=0),
        dict(other_solver_calls=[dict(backend="highs-native", status="OPTIMAL")]),
    ):
        assert comparison({**server, **incorrect}, device, True)["outcome"] == "mismatch"
