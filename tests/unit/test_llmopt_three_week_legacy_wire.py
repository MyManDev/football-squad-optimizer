"""Replay the four browser POSTs captured from the pre-release develop checkout."""

import json
from pathlib import Path

import pytest
from tests.unit.test_api_advice_post import _world

from squadopt.platform.advice_read import PreferencePlayers

FIXTURE = Path(__file__).parents[1] / "fixtures" / "llmopt" / "develop_three_week_requests.json"


@pytest.mark.parametrize("master", [False, True])
def test_three_week_legacy_posts_reach_the_develop_cache_keys(tmp_path: Path, master: bool) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    players = PreferencePlayers(
        squad=frozenset(range(1, 16)), roster=frozenset([*range(1, 16), 9081401, 9081402, 9081403])
    )
    client, _, queue = _world(
        tmp_path,
        preference_players=lambda *_: players,
        llmopt_vnext=master,
        llmopt_vnext_three_week=False,
    )
    # Use the same published member as the browser, with the fixture's fixed deployment identity.
    directory = tmp_path / "site" / "league" / "members.json"
    envelope = json.loads(directory.read_text(encoding="utf-8"))
    envelope["payload"]["members"][0]["entry_id"] = 35249001
    directory.write_text(json.dumps(envelope), encoding="utf-8")
    for request in fixture["requests"]:
        response = client.post(
            request["path"],
            content=request["body"].encode(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]
        job = next(job for job in queue.jobs() if job.job_id == job_id)
        assert job.contract_version == "backend_jobs_v1"
        assert job.cache_key == request["cache_key"]
    assert len(queue.jobs()) == 4
