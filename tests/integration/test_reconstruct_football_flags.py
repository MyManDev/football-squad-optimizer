"""Original synthetic captures through the retained flag training-row producer."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest
from tests.fixtures.football_flag_fixtures import native_case
from tests.unit.test_source_fpl_live import _element

from squadopt.application import football_live
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.live.football_artifact import forecast_digest


@dataclass
class RetainedPairs:
    root: Path
    target: CapturedSnapshot
    pairs: tuple[tuple[CapturedSnapshot, CapturedSnapshot], ...]
    native_calls: list[tuple[str, dict]]

    def rewrite(self, snapshot, *, payloads=None, captured_at=None):
        metadata = write_snapshot(
            self.root,
            source="fpl-live",
            captured_at_utc=captured_at or snapshot.metadata.captured_at_utc,
            payloads=dict(snapshot.payloads) if payloads is None else payloads,
        )
        return read_snapshot(self.root, metadata.snapshot_id)

    def reconstruct(self, pairs=None):
        return football_live.reconstruct_flag_training(
            self.target, Path("unused-synthetic-archive"), self.pairs if pairs is None else pairs
        )


@pytest.fixture
def retained_pairs(tmp_path, monkeypatch):
    """Only native fitting is substituted; capture parsing and flag reconstruction are real."""
    native = native_case().components.loc[lambda f: f.player_code.isin((1, 2))].copy()
    native_by_capture = {}
    calls = []
    deadlines = {
        1: "2026-08-01T10:00:00Z",
        6: "2026-10-03T10:00:00Z",
        7: "2026-10-10T10:00:00Z",
        8: "2026-10-17T10:00:00Z",
        9: "2026-10-24T10:00:00Z",
    }

    def capture(week, *, settled=False):
        deadline = pd.Timestamp(deadlines[week])
        captured = (
            deadline + pd.Timedelta(days=2)
            if settled
            else deadline - pd.Timedelta(hours=48 if week == 7 else 24)
        )
        kickoff = deadline + pd.Timedelta(days=1, hours=5)
        boot = {
            "events": [
                {
                    "id": gw,
                    "deadline_time": clock,
                    "is_next": gw == week,
                    "finished": gw < week or (gw == week and settled),
                }
                for gw, clock in deadlines.items()
            ],
            "teams": [
                {"id": club, "code": club, "name": f"Club {club}", "short_name": f"C{club}"}
                for club in (1, 2)
            ],
            "elements": [
                _element(
                    id=100 + player,
                    code=player,
                    team=player,
                    element_type=1,
                    status="d",
                    chance_of_playing_next_round=75,
                    news="Synthetic retained flag",
                    news_added=(captured - pd.Timedelta(hours=2)).isoformat(),
                )
                for player in (1, 2)
            ],
        }
        fixtures = [
            {
                "id": week * 10 + 1,
                "event": week,
                "team_h": 1,
                "team_a": 2,
                "kickoff_time": kickoff.isoformat(),
                "finished": settled,
            }
        ]
        payloads = {
            "bootstrap-static.json": json.dumps(boot).encode(),
            "fixtures.json": json.dumps(fixtures).encode(),
        }
        if settled:
            outcomes = ((75, 1), (15, 0)) if week == 6 else ((0, 0), (90, 1))
            payloads[f"event-gw{week:02d}-live.json"] = json.dumps(
                {
                    "elements": [
                        {
                            "id": 100 + player,
                            "stats": {"minutes": minutes, "starts": starts},
                            "explain": [{"fixture": week * 10 + 1}],
                        }
                        for player, (minutes, starts) in enumerate(outcomes, 1)
                    ]
                }
            ).encode()
            payloads[f"event-gw{7 if week == 6 else 6:02d}-live.json"] = b"wrong event payload"
        metadata = write_snapshot(
            tmp_path, source="fpl-live", captured_at_utc=captured.isoformat(), payloads=payloads
        )
        snapshot = read_snapshot(tmp_path, metadata.snapshot_id)
        components = native.assign(GW=week, fixture=week * 10 + 1, kickoff=kickoff.isoformat())
        companion = {"rows": components.to_dict("records")}
        companion["fingerprint"] = forecast_digest(companion)
        native_by_capture[snapshot.metadata.snapshot_id] = companion
        return snapshot

    pairs = tuple((capture(week), capture(week, settled=True)) for week in (6, 7))
    target = capture(8)

    def native_producer(snapshot, archive_root, **options):
        assert archive_root == Path("unused-synthetic-archive")
        calls.append((snapshot.metadata.snapshot_id, options))
        return {}, copy.deepcopy(native_by_capture[snapshot.metadata.snapshot_id])

    monkeypatch.setattr(football_live, "produce_football_components", native_producer)
    return RetainedPairs(tmp_path, target, pairs, calls)


def test_two_retained_pairs_reconstruct_causal_training_and_exact_event_labels(retained_pairs):
    rows = retained_pairs.reconstruct()
    assert [(row.input.gameweek, row.input.player_code, row.observed_states) for row in rows] == [
        (6, 1, (2,)),
        (6, 2, (4,)),
        (7, 1, (0,)),
        (7, 2, (3,)),
    ]
    for row in rows:
        before, after = retained_pairs.pairs[row.input.gameweek - 6]
        reference = pd.Timestamp(row.input.deadline_at) - pd.Timedelta(seconds=1)
        assert pd.Timestamp(row.input.decision_at) == reference
        expected_age = (24 if row.input.gameweek == 6 else 48) - 1 / 3600
        assert row.input.capture_age_hours == expected_age
        assert row.input.news_age_hours == expected_age + 2
        assert row.input.native_basis_kind == "out_of_fold"
        assert row.input.native_basis_fit_cutoff == before.metadata.captured_at_utc
        assert row.settled_at == after.metadata.captured_at_utc
    assert retained_pairs.native_calls == [
        (
            before.metadata.snapshot_id,
            {
                "gameweeks": (week,),
                "training_seasons": ("2022-23", "2023-24", "2024-25", "2026-27"),
                "role_minutes": True,
                "retained_role_history": True,
            },
        )
        for week, (before, _) in zip((6, 7), retained_pairs.pairs, strict=True)
    ]


@pytest.mark.parametrize("side", [0, 1], ids=["decision", "settlement"])
def test_other_season_pair_member_refuses_before_native_fitting(retained_pairs, side):
    pair = list(retained_pairs.pairs[0])
    payloads = dict(pair[side].payloads)
    boot = json.loads(payloads["bootstrap-static.json"])
    boot["events"][0]["deadline_time"] = "2023-08-01T10:00:00Z"
    payloads["bootstrap-static.json"] = json.dumps(boot).encode()
    pair[side] = retained_pairs.rewrite(pair[side], payloads=payloads)
    with pytest.raises(ValueError, match="same captured season"):
        retained_pairs.reconstruct((tuple(pair),))
    assert retained_pairs.native_calls == []


def test_repeated_week_refuses_instead_of_double_counting_labels(retained_pairs):
    with pytest.raises(ValueError, match=r"unique.*target/future"):
        retained_pairs.reconstruct((retained_pairs.pairs[0],) * 2)
    assert len(retained_pairs.native_calls) == 1


@pytest.mark.parametrize("week", [8, 9], ids=["target", "future"])
def test_target_or_future_training_refuses_before_native_fitting(retained_pairs, week):
    before = retained_pairs.target
    if week == 9:
        payloads = dict(before.payloads)
        boot = json.loads(payloads["bootstrap-static.json"])
        for event in boot["events"]:
            event["is_next"] = event["id"] == 9
        payloads["bootstrap-static.json"] = json.dumps(boot).encode()
        before = retained_pairs.rewrite(
            before, payloads=payloads, captured_at="2026-10-23T10:00:00Z"
        )
    with pytest.raises(ValueError, match=r"unique.*target/future"):
        retained_pairs.reconstruct(((before, retained_pairs.pairs[0][1]),))
    assert retained_pairs.native_calls == []


@pytest.mark.parametrize("clock", ["2026-10-16T10:00:00Z", "2026-10-16T11:00:00Z"])
def test_settlement_at_or_after_target_capture_refuses_before_native_fitting(retained_pairs, clock):
    before, after = retained_pairs.pairs[0]
    after = retained_pairs.rewrite(after, captured_at=clock)
    with pytest.raises(ValueError, match="settlement must precede"):
        retained_pairs.reconstruct(((before, after),))
    assert retained_pairs.native_calls == []


def test_missing_named_event_payload_cannot_fall_back_to_another_week(retained_pairs):
    before, after = retained_pairs.pairs[0]
    payloads = dict(after.payloads)
    del payloads["event-gw06-live.json"]
    after = retained_pairs.rewrite(after, payloads=payloads)
    with pytest.raises(KeyError, match=r"event-gw06-live\.json"):
        retained_pairs.reconstruct(((before, after),))


@pytest.mark.parametrize("change", ["unfinished", "other_week"])
def test_one_unsettled_club_fixture_refuses_the_whole_reconstruction(retained_pairs, change):
    before, after = retained_pairs.pairs[1]
    payloads = dict(after.payloads)
    fixtures = json.loads(payloads["fixtures.json"])
    fixtures[0]["finished" if change == "unfinished" else "event"] = (
        False if change == "unfinished" else 8
    )
    payloads["fixtures.json"] = json.dumps(fixtures).encode()
    after = retained_pairs.rewrite(after, payloads=payloads)
    with pytest.raises(DataError, match="not settled in its target gameweek"):
        retained_pairs.reconstruct((retained_pairs.pairs[0], (before, after)))
    assert len(retained_pairs.native_calls) == 2
