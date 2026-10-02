"""The device-plan parity fixture still says what the planner says.

The web test holds the device solver to the fixture's recorded answers; this test holds
the recorded answers to the planner. A planner change that moves an answer fails here,
and the fixture is carried by rerunning ``scripts/export_device_plan_fixture.py``.
"""

import json

from scripts.export_device_plan_fixture import FIXTURE, build_fixture


def test_the_recorded_answers_are_the_planner_s() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rebuilt = json.loads(json.dumps(build_fixture()))
    assert rebuilt["document"] == recorded["document"]
    assert [m["entry"] for m in rebuilt["members"]] == [m["entry"] for m in recorded["members"]]
    for fresh, held in zip(rebuilt["members"], recorded["members"], strict=True):
        assert fresh["reference"] == held["reference"], fresh["entry_id"]


def test_the_fixture_covers_a_paid_transfer_and_every_free_transfer_count() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    members = recorded["members"]
    assert any(m["reference"]["transfer_hit_points"] > 0 for m in members)
    assert {m["entry"]["free_transfers"] for m in members} >= {1, 2, 3, 5}
    assert all(m["reference"]["solver_status"] == "OPTIMAL" for m in members)
