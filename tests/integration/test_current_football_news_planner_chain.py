"""Four offline source-to-real-planner paths, with one bounded solve per case.

All source files and model components are synthetic. Only HTTP is mocked: the
acquisition command, citation replay, sealed bundle, minute binding and 3/5-week
planner are real. These checks establish integration, not predictive superiority.
"""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from tests.integration.test_openai_news_minute_chain import FAKE_KEY, _Transport
from tests.unit.test_club_news_acquire import _registry, _Reply
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_minute_integration import world
from tests.unit.test_joint_role_minute_evidence import joint_documents
from tests.unit.test_live_transfers import CHIPS, _game_config

from squadopt.application import rotation_export
from squadopt.application.manager_words import WORDS_SHOWN
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data._long_paths import addressable
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news_coding import ROTATION_CLAIM_CODING_CONTRACT_VERSION
from squadopt.data.sources.fpl_live import FIXTURES_PAYLOAD
from squadopt.live import project, read_inputs, read_projection_handoff
from squadopt.live import transfers as live_transfers
from squadopt.live.football_artifact import (
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.live.rules import read_season_rules
from squadopt.live.transfers import HeldSquad
from squadopt.optimization import OptimizationConfig
from squadopt.platform import club_news_acquire, football_bundle
from squadopt.platform.advice_switches import load_switch_inputs
from squadopt.platform.club_news_fetch import ClubSource
from squadopt.platform.club_news_openai import OpenAIClubNewsProvider, OpenAIReply
from squadopt.platform.club_news_provider import resolve_provider_config

CLUB = "Club 3"
URL = "https://club.example/news/team-update"
QUOTE = "Player 3 cannot complete the full upcoming Premier League match."
OTHER_QUOTE = "Player 9 is expected to start the upcoming Premier League match."
PUBLISHED = "2026-09-22T10:00:00Z"
FETCHED = "2026-09-22T11:00:00Z"
DEADLINE = "2026-09-23T12:00:00Z"


@pytest.fixture
def publication_case(tmp_path):
    """Extend the existing joint fixture, without fitting or reading an archive."""
    served, companion, calendar, clubs = deepcopy(joint_documents())
    source_rows = [row for row in companion["rows"] if row["GW"] == 7]
    source_week = [row for row in served["rows"] if row["gameweek"] == 7]
    for week in (8, 9, 10):
        for source in source_rows:
            row = deepcopy(source)
            row.update(
                GW=week,
                fixture=source["fixture"] + 100 * (week - 7),
                kickoff=(pd.Timestamp(source["kickoff"]) + timedelta(weeks=week - 7)).isoformat(),
            )
            companion["rows"].append(row)
        served["rows"].extend({**source, "gameweek": week} for source in source_week)
    companion["gameweeks"] = [6, 7, 8, 9, 10]
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    calendar = pd.DataFrame(companion["rows"])[
        ["GW", "fixture", "club", "opponent", "home", "kickoff"]
    ].drop_duplicates()
    _, inputs, _, _ = world((served, companion, calendar, clubs))
    fixtures = [
        {
            "id": int(row.fixture),
            "event": int(row.GW),
            "team_h": int(row.club) + 100,
            "team_a": int(row.opponent) + 100,
            "kickoff_time": row.kickoff,
        }
        for row in calendar.loc[calendar.home.eq(1)].itertuples()
    ]
    return {
        "artifact_root": tmp_path / "artifacts",
        "snapshot": SimpleNamespace(payloads={FIXTURES_PAYLOAD: json.dumps(fixtures).encode()}),
        "inputs": inputs,
        "document": served,
        "companion": companion,
        "bootstrap_extra": {"game_config": _game_config(), "chips": CHIPS},
    }


class _UnavailableTransport:
    def __init__(self):
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return OpenAIReply(status_code=503, body=b"offline provider unavailable")


def _acquire(case, tmp_path, monkeypatch, capsys, mode):
    source = ClubSource(club=CLUB, url=URL, terms_read_on=date(2026, 9, 1))
    registry = _registry(tmp_path / "sources.json", (source,))
    html = (
        f'<html><head><meta property="article:published_time" content="{PUBLISHED}">'
        f"</head><body><p>Coach: {QUOTE}</p><p>Coach: {OTHER_QUOTE}</p></body></html>"
    ).encode()

    def opener(request, timeout):
        assert timeout > 0
        url = request.full_url
        return _Reply(url, b"User-agent: *\nAllow: /\n" if url.endswith("robots.txt") else html)

    claim = {
        "player_name": "Player 3",
        "team_name": CLUB,
        "disposition": "stated_full_match_unavailable",
        "fixture_scope": "upcoming_premier_league",
        "speaker": "manager",
        "source_url": URL,
        "quote": QUOTE if mode != "malformed" else "An invented sentence absent from the source.",
        "paraphrase": "The manager explicitly limited the next league match.",
    }
    claims = [] if mode == "empty" else [claim]
    if mode == "malformed":
        claims.append(
            {
                **claim,
                "player_name": "Player 9",
                "disposition": "stated_expected_to_start",
                "quote": OTHER_QUOTE,
                "paraphrase": "The other player is expected to start the next league match.",
            }
        )
    answer = json.dumps(
        {
            "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            "documents": [
                {"url": URL, "published_at_utc": PUBLISHED, "published_precision": "instant"}
            ],
            "claims": claims,
        }
    )
    transport = (
        _UnavailableTransport() if mode == "failure" else _Transport(answer, "synthetic-revision")
    )
    config = resolve_provider_config(
        {
            "SQUADOPT_LLM_PROVIDER": "openai",
            "SQUADOPT_LLM_MODEL": "synthetic-model",
            "SQUADOPT_LLM_API_KEY": FAKE_KEY,
        }
    )

    def build(environ, *, settings_file, target_context):
        assert target_context["season"] == "2026-27" and target_context["gameweek"] == 6
        assert pd.Timestamp(target_context["deadline"]) == pd.Timestamp(DEADLINE)
        return (
            OpenAIClubNewsProvider(
                api_key=FAKE_KEY,
                model_identifier=config.model_identifier,
                target_context=target_context,
                transport=transport,
            ),
            replace(config, target_context=target_context),
        )

    monkeypatch.setattr(club_news_acquire, "build_coding_provider", build)
    monkeypatch.setattr(club_news_acquire, "_utc_now", lambda: FETCHED)
    before = set(case["snapshot_root"].iterdir())
    status = club_news_acquire.main(
        [
            "--roster-snapshot",
            str(case["snapshot_id"]),
            "--snapshot-root",
            str(case["snapshot_root"]),
            "--registry",
            str(registry),
            "--max-model-calls",
            "1",
        ],
        environ={},
        opener=opener,
        now=lambda: datetime.fromisoformat(FETCHED.replace("Z", "+00:00")),
        sleeper=lambda _: None,
    )
    output = capsys.readouterr().out
    assert FAKE_KEY not in output
    assert (transport.calls if mode == "failure" else len(transport.calls)) == 1
    capture_lines = [line for line in output.splitlines() if line.startswith("Capture ")]
    if mode == "failure":
        assert status == 1 and not capture_lines
        assert "Nothing was coded" in output
        assert set(case["snapshot_root"].iterdir()) == before
        return None
    assert status == 0 and len(capture_lines) == 1, output
    capture_id = capture_lines[0].split()[-1]
    assert (case["snapshot_root"] / capture_id).is_dir()
    return capture_id


def _sealed_news(case, tmp_path, capture_id):
    exported = export_rotation_evidence(
        RotationExportRequest(
            "2026-27",
            6,
            DEADLINE,
            case["snapshot_id"],
            case["snapshot_root"],
            None,
            tmp_path / "rotation",
            club_news_snapshot=capture_id,
        ),
        repository_commit="0" * 40,
    )
    return football_bundle.seal_football_bundle(
        **case, news_capture_id=capture_id, rotation_table_path=exported["table_path"]
    )


def _assert_legal_path(plan, held, policy, window):
    assert plan.has_solution and tuple(w.gameweek for w in plan.weeks) == tuple(
        range(6, 6 + window)
    )
    prior, bank, free = set(held.squad_player_ids), held.bank_tenths, held.free_transfers
    purchases = dict(held.purchase_prices)
    for week in plan.weeks:
        squad = set(week.selected_squad.player_id)
        xi, bench = set(week.starting_xi.player_id), set(week.bench.player_id)
        assert len(squad) == 15 and len(xi) == 11 and len(bench) == 4
        assert xi.isdisjoint(bench) and xi | bench == squad
        assert week.selected_squad.groupby("position").size().to_dict() == {
            "GK": 2,
            "DEF": 5,
            "MID": 5,
            "FWD": 3,
        }
        shape = week.starting_xi.groupby("position").size().to_dict()
        assert shape["GK"] == 1 and shape["DEF"] >= 3 and shape["MID"] >= 2 and shape["FWD"] >= 1
        assert week.selected_squad.groupby("team_id").size().max() <= 3
        assert week.captain.player_id in xi and week.vice_captain_id in xi
        assert week.captain.player_id != week.vice_captain_id
        incoming, outgoing = squad - prior, prior - squad
        assert set(week.transfers_in.player_id) == incoming
        assert set(week.transfers_out.player_id) == outgoing
        assert week.transfer_count == len(incoming) == len(outgoing)
        # Market is 50; a 45 purchase sells for 47, a rebuy at 50 for 50.
        proceeds = sum(purchases[p] + (50 - purchases[p]) // 2 for p in outgoing)
        assert week.bank_before_tenths == bank
        bank += proceeds - 50 * len(incoming)
        assert week.bank_after_tenths == bank >= 0
        assert week.free_transfers_before == free
        assert week.paid_transfer_count == max(0, len(incoming) - free)
        assert week.transfer_hit_points == pytest.approx(4 * week.paid_transfer_count)
        assert week.chip is None
        free = min(policy.max_free_transfers, max(0, free - len(incoming)) + 1)
        assert week.free_transfers_for_next_gameweek == free
        purchases = {p: purchases[p] for p in prior - outgoing} | dict.fromkeys(incoming, 50)
        prior = squad


@pytest.mark.slow
@pytest.mark.parametrize(
    ("mode", "window"), [("success", 3), ("empty", 5), ("malformed", 3), ("failure", 5)]
)
def test_news_outcome_reaches_one_real_bounded_planner(
    case, tmp_path, monkeypatch, capsys, mode, window
):
    accepted_mode = "success" if mode == "failure" else mode
    capture_id = _acquire(case, tmp_path, monkeypatch, capsys, accepted_mode)
    sealed = _sealed_news(case, tmp_path, capture_id)
    marker_before = sealed.marker_path.read_bytes()
    accepted_before = read_snapshot(case["snapshot_root"], capture_id)
    if mode == "failure":
        assert _acquire(case, tmp_path, monkeypatch, capsys, "failure") is None
        assert sealed.marker_path.read_bytes() == marker_before
        assert read_snapshot(case["snapshot_root"], capture_id) == accepted_before
    validated = football_bundle.read_football_bundle(
        **{key: case[key] for key in ("artifact_root", "snapshot_root", "snapshot_id")}
    )
    assert validated.fingerprint == sealed.fingerprint and validated.news_capture_id == capture_id
    snapshot = read_snapshot(case["snapshot_root"], case["snapshot_id"])
    inputs = read_inputs(snapshot, season="2026-27")
    native = read_football_forecast(
        football_artifact_path(case["artifact_root"], inputs.snapshot_id), inputs
    )
    switches = load_switch_inputs(
        artifact_root=case["artifact_root"],
        club_news_source=None,
        snapshot_root=case["snapshot_root"],
        inputs=inputs,
        projection=project(inputs, in_season=read_projection_handoff(case["handoff_path"])),
    )
    assert switches.football is not None, switches.notes
    assert (
        switches.football_components_bound and switches.football_bundle_sha256 == sealed.fingerprint
    )
    assert switches.manager_words is not None and switches.manager_words.source_label == capture_id
    bound = switches.football
    assert_series_equal(
        bound.horizon.table.appearance_probability, native.horizon.table.appearance_probability
    )
    assert_frame_equal(
        bound.horizon.table.loc[bound.horizon.table.gameweek.gt(6)],
        native.horizon.table.loc[native.horizon.table.gameweek.gt(6)],
    )
    if accepted_mode == "success":
        old = native.projection.table.set_index("player_id")
        new = bound.projection.table.set_index("player_id")
        assert new.loc[3, "expected_points"] < old.loc[3, "expected_points"]
        assert new.loc[9, "expected_points"] > old.loc[9, "expected_points"]
        assert bound.projection.diagnostics["participation_evidence"]["minutes_reestimated"] is True
    else:
        assert_frame_equal(bound.horizon.table, native.horizon.table)
        if mode == "empty":
            assert switches.manager_words.words == ()
        else:
            # The unlocatable Player 3 claim is dropped, not turned into quiet news
            # or an actionable statement. The other genuine citation survives.
            assert [word.player_id for word in switches.manager_words.words] == [9]
            valid = switches.manager_words.words[0]
            assert valid.words == OTHER_QUOTE and valid.words_status == WORDS_SHOWN
            assert valid.disposition == "stated_expected_to_start"
            assert valid.scope_verified and valid.publication_verified
            assert switches.manager_words.clubs_covered == (CLUB,)

    horizon = replace(
        bound.horizon,
        table=bound.horizon.table.loc[
            bound.horizon.table.player_id.le(16) & bound.horizon.table.gameweek.lt(6 + window)
        ].copy(),
    )
    held = HeldSquad("2026-27", 5, tuple(range(1, 16)), dict.fromkeys(range(1, 16), 45), 10, 2, {})
    received = []
    optimize = live_transfers.optimize_observed_window

    def observed(planning_horizon, *args, **kwargs):
        received.append(planning_horizon.table.copy(deep=True))
        assert kwargs["expected_lineups"] is True
        return optimize(planning_horizon, *args, **kwargs)

    monkeypatch.setattr(live_transfers, "optimize_observed_window", observed)
    plan, policy = live_transfers.plan_transfer_horizon(
        inputs,
        horizon,
        held,
        read_season_rules(snapshot, season="2026-27"),
        optimization=OptimizationConfig(
            solver_deterministic_time_limit=5, solver_time_limit_seconds=30
        ),
    )
    assert len(received) == 1
    columns = ["gameweek", "player_id", "expected_points", "appearance_probability"]
    assert_frame_equal(received[0][columns], horizon.table[columns])
    _assert_legal_path(plan, held, policy, window)
    review = plan.diagnostics["observed_window"]
    assert review["selection_basis"] == "expected_lineup_selection_utility"
    assert review["configured_total"] == 5 and review["actual_total"] <= 5 + 1e-9
    assert plan.diagnostics["availability_information"]["source_snapshot_id"] == inputs.snapshot_id


def test_rotation_publication_long_temporary_preserves_immutable_bytes(tmp_path, monkeypatch):
    # A 232-character final path fits legacy Windows, while its 5-digit PID
    # temporary reaches MAX_PATH and is inaccessible. Also cover a longer final path.
    monkeypatch.setattr(rotation_export.os, "getpid", lambda: 54321)
    for length in (232, 280):
        target = tmp_path / ("rotation-" + "x" * 20) / "manifest.json"
        padding = max(0, length - len(str(target.absolute())))
        target = target.with_name("x" * padding + target.name)
        assert len(str(target.absolute())) >= length
        temporary_name = f".{target.name}.tmp-54321-{'0' * 16}"
        assert len(str(target.with_name(temporary_name).absolute())) >= 260
        assert rotation_export._publish_once(b"original", target) == "written"
        assert rotation_export._publish_once(b"original", target) == "replay"
        with pytest.raises(DataError, match="different content"):
            rotation_export._publish_once(b"replacement", target)
        assert Path(addressable(target)).read_bytes() == b"original"
        assert list(Path(addressable(target.parent)).glob(".*.tmp-*")) == []
