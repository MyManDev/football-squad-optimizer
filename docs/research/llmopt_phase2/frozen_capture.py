"""Rebuild the member, static prices, rules and projections from a frozen Phase 1 case."""

import hashlib
from datetime import UTC, datetime, timedelta

import pandas as pd
from scripts.measure_window_solver_highs import _players_frame, window_call

from squadopt.application.entries import EntryPicks
from squadopt.data.sources.fpl_live import GameweekDeadline
from squadopt.live import Projection, RecommendationInputs
from squadopt.live.rules import (
    SEASON_RULES_CONTRACT_VERSION,
    ChipWindow,
    ScoringRules,
    SeasonRules,
    TransferRules,
)
from squadopt.planning import ProjectionHorizon
from squadopt.platform.advice_read import AdviceRequestContext
from squadopt.platform.capture_context import AdviceCaptureContext


class FrozenProvider:
    def __init__(self, picks):
        self.value = picks

    def holds(self, entry_id, gameweek):
        return entry_id == self.value.entry_id and gameweek == self.value.gameweek

    def picks(self, entry_id, season, gameweek):
        assert (entry_id, season, gameweek) == (
            self.value.entry_id,
            self.value.season,
            self.value.gameweek,
        )
        return self.value


class FrozenContexts:
    def __init__(self, capture):
        self.value = capture

    def current(self):
        return self.value.context

    def capture(self, context):
        assert context == self.value.context
        return self.value


class FrozenDirectory:
    def __init__(self, inputs, entry):
        self.value = dict(
            season=inputs.table["season"],
            gameweek=inputs.gameweek,
            members=[dict(entry_id=entry, member_kind="human")],
        )

    def league(self, _league_id):
        return self.value


class ScoringNotUsed:
    """A guard: this replay must consume frozen points without invoking a scorer."""

    def __getattribute__(self, name):
        if name.startswith("__"):
            return object.__getattribute__(self, name)
        raise AssertionError("The frozen-point replay must not invoke scoring.")


def make_capture(frozen, inputs, entry, scenario, producer):
    table = inputs.table
    block = inputs.members[entry]
    players = _players_frame(table)
    frame = players.copy(deep=True)
    instant = datetime.strptime(inputs.capture.split("-")[-2], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    stamp = instant.isoformat().replace("+00:00", "Z")
    source = inputs.capture
    season = table["season"]
    deadline = (instant + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    recommendation = RecommendationInputs(
        source,
        stamp,
        season,
        GameweekDeadline(inputs.gameweek, deadline, False),
        players,
        pd.DataFrame(),
        published_gameweeks=frozenset(inputs.fixture_counts),
    )
    held = tuple(map(int, block["held"]))
    current = dict(zip(players.player_id, players.price_tenths, strict=True))
    sell = {int(key): int(value) for key, value in block["sell_tenths"].items()}
    # Static frozen prices need only the exact initial sale proceeds. Choose an
    # equivalent purchase basis, not a claim about unavailable historic purchases.
    purchase = {
        player: int(
            current[player]
            if sell[player] == current[player]
            else 2 * sell[player] - current[player]
        )
        for player in held
    }
    picks = EntryPicks(
        entry,
        season,
        inputs.gameweek - 1,
        held,
        held[:11],
        held[0],
        held[1],
        0 if scenario == "tight_bank" else int(block["bank_tenths"]),
        int(block["free_transfers"]),
        purchase_prices=purchase,
        purchase_prices_known=True,
        source_snapshot_id=source,
    )
    rules = table["rules"]
    financial = TransferRules(
        rules["squad_size"],
        rules["starting_size"],
        rules["max_players_per_team"],
        1000,
        rules["max_free_transfers"] - 1,
        None,
        0.5,
        False,
    )
    season_rules = SeasonRules(
        SEASON_RULES_CONTRACT_VERSION,
        season,
        source,
        ScoringNotUsed(),
        financial,
        tuple(
            ChipWindow(name, 1, 1, 38, "transfer" if name in ("wildcard", "freehit") else "team")
            for name in ("wildcard", "freehit", "3xc", "bboost")
        ),
    )
    context = AdviceRequestContext(
        "provisional_league_ui_v1",
        source,
        season,
        inputs.gameweek,
        frozen["projection_file_sha256"],
        producer,
        hashlib.sha256(f"frozen-api-replay:{source}:{entry}:{scenario}".encode()).hexdigest(),
    )

    def horizon_builder(weeks):
        call = window_call(inputs, entry, len(weeks)) if len(weeks) > 1 else None
        if call is not None:
            horizon = call.horizon.table.rename(columns={"buy_price_tenths": "price_tenths"})
        else:
            horizon = frame.assign(gameweek=weeks[0])
        horizon = horizon.copy(deep=True)
        horizon["fixture_count"] = [
            inputs.fixture_counts[int(week)].get(str(team), 0)
            for week, team in zip(horizon.gameweek, horizon.team_id, strict=True)
        ]
        horizon["home_fixture_count"] = 0  # Unused by this precomputed-point path.
        return ProjectionHorizon(
            horizon,
            season,
            source,
            frozen["projection"]["model_name"],
            frozen["projection"]["model_version"],
            frozen["projection"]["feature_contract_version"],
            "frozen_phase1_points_v1",
        )

    capture = AdviceCaptureContext(
        context,
        recommendation,
        Projection(frame, (), {}),
        season_rules,
        FrozenProvider(picks),
        horizon_builder,
    )
    assert not isinstance(capture.rules.scoring, ScoringRules)
    return capture, stamp
