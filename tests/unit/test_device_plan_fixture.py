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
