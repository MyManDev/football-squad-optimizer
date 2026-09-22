"""Exercise durable moderation and the actual HTTP boundary with isolated storage."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.contributions import ContributionsLimitedError, ContributionStore

BASE = "/api/v1/contributions"


@pytest.mark.parametrize("content", [None, "not-json", "{}"])
def test_missing_or_invalid_roster_refuses_submission(tmp_path, content):
    path = tmp_path / "players.json"
    if content is None:
        path.unlink()
    else:
        path.write_text(content)
    store = ContributionStore(tmp_path / "inbox.db")
    with TestClient(create_app(data_root=tmp_path, contributions=store)) as client:
        assert client.get(BASE + "/players").status_code == 503
        assert client.post(BASE, json=body()).status_code == 503
    assert store.pending() == []


def test_roster_player_outside_prediction_pool_can_contribute(tmp_path, published_catalog):
    published_catalog["players"].append(
        {"id": 998877, "name": "Reserve", "team_id": 10, "team": "Arsenal", "position": "DEF"}
    )
    (tmp_path / "players.json").write_text(json.dumps(published_catalog))
    store = ContributionStore(tmp_path / "inbox.db")
    with TestClient(create_app(data_root=tmp_path, contributions=store)) as client:
        assert client.post(BASE, json=body(player_id=998877)).status_code == 202
    assert store.pending()[0]["player_id"] == 998877


@pytest.fixture(autouse=True)
def published_catalog(tmp_path):
    document = {
        "contract_version": "player_catalog_v1",
        "season": "2026-27",
        "source_snapshot_id": "fpl-live-test",
        "captured_at_utc": "2026-09-22T12:00:00Z",
        "teams": [{"id": 10, "name": "Arsenal"}],
        "players": [
            {"id": 1, "name": "Player", "team_id": 10, "team": "Arsenal", "position": "GK"}
        ],
    }
    (tmp_path / "players.json").write_text(json.dumps(document))
    return document


def body(**changes):
    return {
        "season": "2026-27",
        "player_id": 1,
        "author": "Supporter",
        "body": "Played deeper in the second half.",
        "source": "https://example.com/report",
        "consent": True,
        **changes,
    }


def test_real_http_submission_moderation_restart_and_retraction(tmp_path):
    path = tmp_path / "contributions.sqlite3"
    store = ContributionStore(path)
    with TestClient(
        create_app(
            data_root=tmp_path, contributions=store, allowed_origins=("https://site.example",)
        )
    ) as client:
        assert client.get(BASE + "/players").json()["players"][0]["id"] == 1
        preflight = client.options(
            BASE,
            headers={
                "Origin": "https://site.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert preflight.status_code == 200
        response = client.post(BASE, json=body())
        assert response.status_code == 202
        comment_id = response.json()["id"]
        assert client.post(BASE, json=body()).json()["id"] == comment_id
        assert (
            client.get(BASE, params={"season": "2026-27", "player_id": 1}).json()["comments"] == []
        )
        assert client.post(BASE + "/approve", json={"id": comment_id}).status_code == 404
    reopened = ContributionStore(path)
    assert len(reopened.pending()) == 1
    reopened.moderate(comment_id, "approved")
    public = reopened.public("2026-27", 1)
    assert public[0]["body"] == body()["body"]
    assert "client" not in public[0] and "status" not in public[0]
    assert reopened.public("2025-26", 1) == []
    assert reopened.public("2026-27", 2) == []
    reopened.moderate(comment_id, "rejected")
    assert reopened.public("2026-27", 1) == []
    assert b"testclient" not in path.read_bytes()


@pytest.mark.parametrize(
    "change",
    [
        {"consent": False},
        {"player_id": True},
        {"player_id": 2},
        {"season": "2025-26"},
        {"body": "short"},
        {"body": "x" * 1501},
        {"author": " "},
        {"body": "bad\x1bterminal"},
        {"source": "javascript:alert(1)"},
        {"source": "https://user:password@example.com"},
        {"extra": "unrecognised"},
    ],
)
def test_invalid_input_never_saved(tmp_path, change):
    store = ContributionStore(tmp_path / "inbox.db")
    with TestClient(create_app(data_root=tmp_path, contributions=store)) as client:
        assert client.post(BASE, json=body(**change)).status_code == 422
        assert store.pending() == []


def test_bounded_body_and_content_type(tmp_path):
    with TestClient(
        create_app(data_root=tmp_path, contributions=ContributionStore(tmp_path / "db"))
    ) as client:
        assert (
            client.post(
                BASE, content=b"x" * 12001, headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
        assert (
            client.post(
                BASE, content="not json", headers={"Content-Type": "application/json"}
            ).status_code
            == 422
        )
        assert client.post(BASE, data=body()).status_code == 415


def submit(store, client, text, stamp=100000):
    return store.submit(
        season="2026-27",
        player_id=1,
        player_name="Player",
        author="Supporter",
        body=text,
        source="",
        client=client,
        now=stamp,
    )


def test_concurrent_quota_and_hourly_recovery(tmp_path):
    store = ContributionStore(tmp_path / "db")
    store.pending()  # initialise schema before independent connections race

    def attempt(index):
        try:
            return submit(store, "same-client", f"Observation number {index}")
        except ContributionsLimitedError:
            return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        result = list(executor.map(attempt, range(8)))
    assert sum(value is not None for value in result) == 3
    assert len(store.pending()) == 3
    assert submit(store, "same-client", "Later observation", stamp=103601)


def test_global_limit_bounds_distributed_abuse_and_pagination(tmp_path):
    store = ContributionStore(tmp_path / "db")
    for index in range(50):
        identity = submit(store, str(index), f"Observation {index}")
        store.moderate(identity, "approved")
    with pytest.raises(ContributionsLimitedError):
        submit(store, "new-visitor", "Another comment")
    rows = store.public("2026-27", 1)
    assert len(rows) == 50
    assert rows[0]["id"] > rows[-1]["id"]
    assert store.public("2026-27", 1, before=rows[-1]["id"]) == []


def test_store_unavailable_fails_honestly(tmp_path: Path):
    path = tmp_path / "not-a-database"
    path.write_text("broken database")
    with TestClient(
        create_app(data_root=tmp_path, contributions=ContributionStore(path))
    ) as client:
        assert client.post(BASE, json=body()).status_code == 503
