"""Real producer/model/consumer connection using entirely generated training and captures."""

import json

import pandas as pd
import pytest
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.application import football_live
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, GameweekDeadline
from squadopt.live import RecommendationInputs
from squadopt.live.football_artifact import forecast_digest, read_football_forecast
from squadopt.platform.football_minute_basis import load_football_minute_basis
from squadopt.platform.football_publication import publish_football_artifacts
from squadopt.prediction.football import FixtureFootballModel


def test_actual_producer_pair_round_trips_through_live_minute_consumer(
    football_fixture,  # noqa: F811
    monkeypatch,
    tmp_path,
):
    # This fixture synthesizes every historical outcome in memory. No archive,
    # held-out season file, saved model, or live capture is opened by this test.
    _, history, roster, _, training = football_fixture
    cutoff = "2026-09-22T12:00:00+00:00"
    history, training = history.copy(), training.copy()
    for frame in (history, training):
        frame["club"] += 1
        frame["opponent"] += 1
    roster = roster.copy()
    roster["club"] += 1
    clubs = {int(row.player_id): int(row.club) for row in roster.itertuples()}
    fixtures = [
        {
            "id": week * 10 + (club - 1) // 2,
            "event": week,
            "team_h": club + 100,
            "team_a": club + 101,
            "kickoff_time": (
                pd.Timestamp(cutoff) + pd.Timedelta(days=2 + (week - 6) * 7)
            ).isoformat(),
        }
        for week in range(6, 11)
        for club in (1, 3, 5, 7)
        if not (week == 7 and club == 3)
    ]
    fixtures.append({**fixtures[0], "id": 999, "kickoff_time": "2026-09-26T15:00:00Z"})
    fixtures.append({"id": 1000, "event": None, "team_h": 101, "team_a": 102, "kickoff_time": None})
    bootstrap = {
        "teams": [{"id": club + 100, "code": club} for club in range(1, 9)],
        "elements": [{"code": player, "team": club + 100} for player, club in clubs.items()],
    }
    snapshots = tmp_path / "synthetic-snapshots"
    metadata = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=cutoff,
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode(),
        },
    )
    snapshot = read_snapshot(snapshots, metadata.snapshot_id)
    availability = pd.DataFrame(
        {
            "player_id": roster.player_id,
            "status": "d",
            "chance_of_playing": [0 if player == 2 else 50 for player in roster.player_id],
        }
    )
    inputs = RecommendationInputs(
        metadata.snapshot_id,
        metadata.captured_at_utc,
        "2026-27",
        GameweekDeadline(6, "2026-09-23T12:00:00+00:00", False),
        roster.drop(columns="club"),
        availability,
    )
    fits = []

    def fit_generated(train, prior, *, cutoff):
        fits.append(len(train))
        return FixtureFootballModel(train, prior, cutoff=cutoff)

    # Replace only source acquisition/training assembly. Both producer serializers,
    # the fitted model, horizon builder, publisher and strict readers stay real.
    monkeypatch.setattr(football_live, "archive_history", lambda root: history.copy())
    monkeypatch.setattr(football_live, "captured_history", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(football_live, "causal_training", lambda prior: training.copy())
    monkeypatch.setattr(football_live, "ARCHIVE_SEASONS", ())
    monkeypatch.setattr(football_live, "infer_season", lambda snap: inputs.season)
    monkeypatch.setattr(football_live, "read_inputs", lambda *a, **k: inputs)
    monkeypatch.setattr(football_live, "FixtureFootballModel", fit_generated)
    forbidden_archive = tmp_path / "must-not-be-created-or-read"
    served, companion = football_live.produce_football_components(snapshot, forbidden_archive)
    assert fits == [len(training)]
    assert not forbidden_archive.exists()
    fingerprint = served["fingerprint"]
    assert companion["forecast_fingerprint"] == fingerprint == forecast_digest(served)
    artifacts = tmp_path / "artifacts"
    forecast_path, component_path = publish_football_artifacts(
        artifact_root=artifacts,
        snapshot=snapshot,
        inputs=inputs,
        document=served,
        companion=companion,
    )
    loaded = read_football_forecast(forecast_path, inputs)
    result = load_football_minute_basis(
        artifact_root=artifacts,
        snapshot_root=snapshots,
        inputs=inputs,
        football=loaded,
    )
    assert result.reason is None and result.basis is not None
    assert component_path is not None and component_path.exists()
    assert loaded.fingerprint == fingerprint
    assert json.loads(forecast_path.read_text(encoding="utf-8")) == served
    raw = pd.DataFrame(companion["rows"])
    weekly = loaded.horizon.table.set_index(["gameweek", "player_id"])
    assert set(weekly.fixture_count) == {0, 1, 2}
    for (week, player), group in raw.groupby(["GW", "player_code"]):
        multiplier = 0.0 if player == 2 else 0.5
        assert weekly.loc[(week, player), "expected_points"] == pytest.approx(
            multiplier * group.expected_points.sum()
        )
        assert weekly.loc[(week, player), "appearance_probability"] == pytest.approx(
            multiplier * (1 - (1 - group.appearance_probability).prod())
        )
    pd.testing.assert_frame_equal(
        result.basis.weekly_rows.set_index(["gameweek", "player_id"])
        .sort_index()
        .sort_index(axis=1),
        weekly.sort_index().sort_index(axis=1),
        check_dtype=False,
    )
