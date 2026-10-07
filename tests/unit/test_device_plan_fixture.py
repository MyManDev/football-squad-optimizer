"""The device-plan parity fixture still says what the planner says.

The web test holds the device solver to the fixture's recorded answers; this test holds
the recorded answers to the planner. A planner change that moves an answer fails here,
and the fixture is carried by rerunning ``scripts/export_device_plan_fixture.py``.
"""

import json

from scripts.export_device_plan_fixture import FIXTURE, build_fixture


def _same(fresh: object, held: object, path: str = "") -> list[str]:
    """Where two recorded answers differ: integers and ids exactly, points within 1e-9.

    A point total is a float sum, and a float sum is not byte-identical across Python
    builds and platforms; the plan it describes is, and that is what this holds.
    """

    if isinstance(fresh, float) or isinstance(held, float):
        if fresh is None or held is None or abs(float(fresh) - float(held)) > 1e-9:  # type: ignore[arg-type]
            return [f"{path}: {fresh!r} != {held!r}"]
        return []
    if isinstance(fresh, dict) and isinstance(held, dict):
        if fresh.keys() != held.keys():
            return [f"{path}: keys {sorted(fresh)} != {sorted(held)}"]
        return [d for key in fresh for d in _same(fresh[key], held[key], f"{path}.{key}")]
    if isinstance(fresh, list) and isinstance(held, list):
        if len(fresh) != len(held):
            return [f"{path}: {fresh!r} != {held!r}"]
        return [
            d
            for i, (a, b) in enumerate(zip(fresh, held, strict=True))
            for d in _same(a, b, f"{path}[{i}]")
        ]
    return [] if fresh == held else [f"{path}: {fresh!r} != {held!r}"]


def test_the_recorded_answers_are_the_planner_s() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rebuilt = json.loads(json.dumps(build_fixture()))
    assert _same(rebuilt["document"], recorded["document"], "document") == []
    for fresh, held in zip(rebuilt["members"], recorded["members"], strict=True):
        assert _same(fresh["entry"], held["entry"], "entry") == [], fresh["entry_id"]
        differences = _same(fresh["reference"], held["reference"], "reference")
        assert differences == [], (fresh["entry_id"], differences)
    assert _same(rebuilt["chips"], recorded["chips"], "chips") == []
    assert _same(rebuilt["rivals"], recorded["rivals"], "rivals") == []
    assert _same(rebuilt["preferences"], recorded["preferences"], "preferences") == []


def test_preferences_hold_every_constraint_and_prove_the_infeasible_case() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = recorded["preferences"]["cases"]
    assert {case["name"] for case in cases} == {
        "keep-held",
        "avoid-held",
        "avoid-not-held",
        "no-hits-zero-free",
        "no-hits-wildcard",
        "no-hits-freehit",
        "save-chips",
        "keep-freehit",
        "avoid-top100",
        "infeasible-no-hits-sale",
    }
    for case in cases:
        preferences, reference = case["preferences"], case["reference"]
        if case["name"] == "infeasible-no-hits-sale":
            assert reference == {"refused": True, "solver_status": "INFEASIBLE"}
            continue
        assert reference["refused"] is False
        assert reference["solver_status"] == "OPTIMAL"
        assert set(preferences["keep_players"]) <= set(reference["squad"])
        assert not set(preferences["avoid_players"]) & set(reference["squad"])
        if preferences["no_hits"]:
            assert reference["transfer_hit_points"] == 0
        if case["name"] == "no-hits-zero-free":
            assert reference["transfers_in"] == reference["transfers_out"] == []
        if case["name"] in {"no-hits-wildcard", "no-hits-freehit"}:
            assert case["entry"]["free_transfers"] == 0
            assert len(reference["transfers_in"]) > 0
    weighted = next(case for case in cases if case["name"] == "avoid-top100")
    assert weighted["top100_weight"] == 20
    assert all(
        "20" in player["top100_scaled"] for player in recorded["preferences"]["document"]["players"]
    )


def test_the_fixture_covers_a_paid_transfer_and_every_free_transfer_count() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    members = recorded["members"]
    assert any(m["reference"]["transfer_hit_points"] > 0 for m in members)
    assert {m["entry"]["free_transfers"] for m in members} >= {1, 2, 3, 5}
    assert all(m["reference"]["solver_status"] == "OPTIMAL" for m in members)


def test_the_fixture_plays_every_chip_on_its_own_basis() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    chips = recorded["chips"]
    assert {c["chip"] for c in chips} == {"wildcard", "freehit", "bboost", "3xc"}
    assert all(c["reference"]["solver_status"] == "OPTIMAL" for c in chips)
    # A rebuild pays no hits; a Bench Boost counts the fifteen, so it is worth at least
    # the eleven (exactly that with a bench of zeros); a Triple Captain counts the
    # captain once more.
    plain = {m["entry_id"]: m["reference"] for m in recorded["members"]}
    for case in chips:
        reference = case["reference"]
        if case["chip"] in {"wildcard", "freehit"}:
            assert reference["transfer_hit_points"] == 0.0
        if case["chip"] == "bboost":
            assert (
                reference["expected_own_points"] >= plain[case["entry_id"]]["expected_own_points"]
            )
        if case["chip"] == "3xc":
            assert reference["expected_own_points"] > plain[case["entry_id"]]["expected_own_points"]
        assert reference["gain_vs_no_chip"] == (
            reference["expected_own_points"] - reference["transfer_hit_points"]
        ) - (
            plain[case["entry_id"]]["expected_own_points"]
            - plain[case["entry_id"]]["transfer_hit_points"]
        )


def test_the_rival_cases_exercise_both_decisions_and_a_refusal() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    world = recorded["rivals"]
    # The producer wrote the catalogue's bands and the charge into the document.
    rules = world["document"]["rules"]
    assert rules["strategies"] == {
        "fark-yarat": {"overlap_floor": None, "overlap_ceiling": 5},
        "ortak-koru": {"overlap_floor": 9, "overlap_ceiling": None},
    }
    assert (
        rules["hit_charged_scaled"] == rules["hit_points_charged"] * rules["expected_points_scale"]
    )
    kinds = {
        "refused" if case["reference"]["refused"] else case["reference"]["plan_kind"]
        for case in world["cases"]
    }
    assert kinds == {"within_free_transfers", "with_hits", "refused"}
    # A relaxed level, an alternative beside the plan, and every proof finished.
    answered = [case["reference"] for case in world["cases"] if not case["reference"]["refused"]]
    assert any(r["overlap_applied"] != r["overlap_target"] for r in answered)
    assert any(r["alternative_plan"] is not None for r in answered)
    assert all(
        r["solver_status"] == "OPTIMAL" and r["control_solver_status"] == "OPTIMAL"
        for r in answered
    )
    # The Top 100 inputs: the document's weights, each member block naming them, and a
    # case whose decision the weight moved, so the price path is exercised.
    assert rules["top100"]["weights"] == [5, 10, 20, 30, 40, 50]
    for block in world["members"].values():
        assert block["top100_weights"] == rules["top100"]["weights"]
    assert any(case["reference"]["changed"] for case in world["top100_cases"])
    assert all(
        case["reference"]["solver_status"] == "OPTIMAL"
        and case["reference"]["control_solver_status"] == "OPTIMAL"
        for case in world["top100_cases"]
    )
    # Every player in the world is on his own number, so no tie decides a case.
    points = [p["expected_points"] for p in world["document"]["players"]]
    assert len(set(points)) == len(points)
