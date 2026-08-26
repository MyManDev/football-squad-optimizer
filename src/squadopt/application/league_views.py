"""Render per-member league views: the JSON tree the site's league pages read.

The web side (Package 5) reads ``data/league/members.json``, ``entry-{id}.json`` and
``advice-{id}.json`` under the provisional contract its ``PROVISIONAL_CONTRACT.md``
records; this module is the producing half. It consumes the `EntryPicksProvider` seam —
today a test double, after #127 the capture-built provider — and turns each member's
held squad into a transfer recommendation with the same function that decides our own
gameweek.

Two rules are load-bearing and tested rather than asserted:

- **Independence.** A member's advice is computed from that member's picks and the
  shared projection only. Nothing here reads the ledger, the system's own squad, or any
  other member's state — the system cannot protect its rank by advising anyone worse,
  and the invariance test pins that as bit-for-bit fact.
- **One failure does not sink the batch.** A member whose picks cannot be read or whose
  plan cannot be solved is recorded as failed with the reason, and the rest render.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.application.entries import (
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    EntryRegistration,
    held_squad_from_picks,
)
from squadopt.data.errors import DataError
from squadopt.live import (
    Projection,
    RecommendationInputs,
    SeasonRules,
    build_transfer_recommendation,
)

LEAGUE_VIEW_CONTRACT_VERSION = "provisional_league_ui_v1"

# The site addresses advice by mode and window. Only this pair is computed: the plan is a
# one-week expected-points optimisation, and the competitive modes are priced on the
# decision controls rather than solved here. Publishing a file for a combination nobody
# computed would make the site show an answer where none was measured, so the other
# combinations are simply absent and the page says so.
COMPUTED_MODE = "saf-puan"
COMPUTED_WINDOW = 1


@dataclass(frozen=True, slots=True)
class MemberViewResult:
    """What one member's render produced, or why it did not."""

    entry_id: int
    label: str
    rendered: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MemberStanding:
    """Where a member sits in the league, as the standings page reports it.

    Declared here rather than imported from the data adapter so this module states what
    it needs rather than what one source happens to publish: a caller reading a different
    standings source maps into this and nothing else changes.

    Points are optional, and ``None`` is a claim rather than a placeholder: it says the
    capture does not prove this member's score for the week being published — no history
    row for it, or the week not yet final. A zero would say the member scored nothing,
    which is a different and possibly untrue statement. Both must survive to the page, so
    the renderer distinguishes them rather than collapsing both to falsy.
    """

    entry_id: int
    team_name: str
    manager_name: str
    rank: int
    gameweek_points: int | None = None
    total_points: int | None = None


@dataclass(frozen=True, slots=True)
class LeagueViewsReport:
    league_id: int
    season: str
    gameweek: int
    members: tuple[MemberViewResult, ...]
    files: tuple[str, ...]

    @property
    def rendered_count(self) -> int:
        return sum(1 for member in self.members if member.rendered)


def _envelope(payload: Mapping[str, object], *, generated_at_utc: str) -> dict[str, object]:
    return {
        "contract_version": LEAGUE_VIEW_CONTRACT_VERSION,
        "generated_at_utc": generated_at_utc,
        "source_kind": "live",
        "payload": dict(payload),
    }


def _advice_player(row: "pd.Series[Any]") -> dict[str, object]:
    name = str(row["name"])
    return {
        "player_id": int(str(row["player_id"])),
        "name": name,
        "short_name": name.rsplit(" ", 1)[-1],
        "position": str(row["position"]),
        "team": str(row["team_id"]),
    }


def _entry_player(
    row: "pd.Series[Any]", *, role: str, is_captain: bool, bench_order: int | None
) -> dict[str, object]:
    name = str(row["name"])
    return {
        "player_id": int(str(row["player_id"])),
        "name": name,
        "short_name": name.rsplit(" ", 1)[-1],
        "position": str(row["position"]),
        "team": str(row["team_id"]),
        "price_tenths": int(str(row["price_tenths"])),
        "expected_points": float(str(row["expected_points"])),
        "event_points": None,
        "is_captain": is_captain,
        "bench_order": bench_order,
        "role": role,
    }


def _entry_squad_payload(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    *,
    league_id: int,
    member_row: Mapping[str, object],
    missing: list[str],
    scored_gameweek: int | None,
) -> dict[str, object]:
    """The member's own squad, as the site's entry page renders it."""

    pool = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    starters: list[dict[str, object]] = []
    bench: list[dict[str, object]] = []
    bench_index = 0
    for player_id in picks.squad:
        row = pool.get(int(player_id))
        if row is None:
            continue
        if int(player_id) in set(picks.starting_xi):
            starters.append(
                _entry_player(
                    row,
                    role="starter",
                    is_captain=int(player_id) == int(picks.captain),
                    bench_order=None,
                )
            )
        else:
            bench_index += 1
            bench.append(
                _entry_player(row, role="bench", is_captain=False, bench_order=bench_index)
            )
    return {
        "league_id": int(league_id),
        "season": picks.season,
        "gameweek": picks.gameweek + 1,
        "scored_gameweek": scored_gameweek,
        "entry": dict(member_row),
        "starting_xi": starters,
        "bench": bench,
        "bank_tenths": int(picks.bank_tenths),
        "free_transfers": int(picks.free_transfers),
        "free_transfers_known": bool(picks.free_transfers_known),
        "chips_used": {name: list(weeks) for name, weeks in picks.chips_used.items()},
        "purchase_prices_known": bool(picks.purchase_prices_known),
        "source_snapshot_id": picks.source_snapshot_id,
        # Comparing a member's gameweek score with ours needs both scores; the standings
        # view does not carry points yet, so this stays absent rather than guessed.
        "squadopt_comparison": None,
        "data_quality": "partial" if missing else "complete",
        "missing_fields": list(missing),
    }


def _member_advice(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
) -> dict[str, object]:
    """One member's advice payload — from their squad and the shared projection only."""

    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    recommendation = build_transfer_recommendation(inputs, projection, held, rules)
    transfers = recommendation.transfers
    moves: list[dict[str, object]] = []
    if transfers is not None:
        by_id = {int(str(row["player_id"])): row for _, row in recommendation.squad.iterrows()}
        pool_by_id = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
        record = transfers.as_record()
        outs_raw = record.get("transfers_out", [])
        ins_raw = record.get("transfers_in", [])
        outs = [int(str(v)) for v in outs_raw] if isinstance(outs_raw, list | tuple) else []
        ins = [int(str(v)) for v in ins_raw] if isinstance(ins_raw, list | tuple) else []
        for index in range(max(len(outs), len(ins))):
            player_out = outs[index] if index < len(outs) else None
            player_in = ins[index] if index < len(ins) else None
            delta = 0.0
            if player_in is not None and player_in in by_id:
                delta += float(str(by_id[player_in]["expected_points"]))
            if player_out is not None and player_out in pool_by_id:
                delta -= float(str(pool_by_id[player_out]["expected_points"]))
            moves.append(
                {
                    "move_id": f"gw{picks.gameweek + 1:02d}-{index + 1}",
                    "player_out": (
                        _advice_player(pool_by_id[player_out])
                        if player_out is not None and player_out in pool_by_id
                        else None
                    ),
                    "player_in": (
                        _advice_player(by_id[player_in])
                        if player_in is not None and player_in in by_id
                        else None
                    ),
                    "expected_points_delta": delta,
                    "expected_points_cost": float(str(record.get("transfer_hit_points", 0.0))),
                    "reason_code": "window_value",
                }
            )
    missing: list[str] = []
    if not picks.free_transfers_known:
        missing.append("free_transfers")
    if not picks.purchase_prices_known:
        missing.append("purchase_prices")
    return {
        "season": picks.season,
        "gameweek": picks.gameweek + 1,
        "entry_id": picks.entry_id,
        "league_id": league_id,
        "mode": COMPUTED_MODE,
        "window": COMPUTED_WINDOW,
        "source_snapshot_id": picks.source_snapshot_id,
        "moves": moves,
        "data_quality": "partial" if missing else "complete",
        "missing_fields": missing,
    }


def build_league_views(
    provider: EntryPicksProvider,
    registrations: tuple[EntryRegistration, ...],
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    league_name: str,
    out_dir: Path,
    standings: Mapping[int, MemberStanding] | None = None,
    scored_gameweek: int | None = None,
    now: datetime | None = None,
) -> LeagueViewsReport:
    """Render every registered member's squad and advice under ``out_dir``.

    The system's own squad is deliberately not an input: member advice must be
    invariant to it (the test pins this bit-for-bit), and the system's row on the
    members page is rendered by the site from its own ledger views, not here.
    """

    placings = dict(standings or {})
    # A score and the week it belongs to are one fact. The members view is labelled with
    # the *upcoming* gameweek, so points travelling without their own week would be read
    # under the wrong heading — publish both or neither.
    if scored_gameweek is None and any(
        placing.gameweek_points is not None or placing.total_points is not None
        for placing in placings.values()
    ):
        raise ValueError(
            "Member points were supplied without the gameweek they were scored in. "
            "The number and its week ship together or not at all."
        )

    def _row(entry_id: int, label: str, quality: str) -> dict[str, object]:
        placing = placings.get(entry_id)
        return {
            "member_kind": "human",
            "entry_id": entry_id,
            "manager_name": placing.manager_name if placing else label,
            "team_name": placing.team_name if placing else None,
            "rank": placing.rank if placing else 0,
            "gameweek_points": placing.gameweek_points if placing else None,
            "total_points": placing.total_points if placing else None,
            "movement": "unknown",
            "movement_places": None,
            "data_quality": quality,
        }

    generated = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    season = inputs.season
    gameweek = int(inputs.deadline.gameweek)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    results: list[MemberViewResult] = []
    member_rows: list[dict[str, object]] = []
    for registration in registrations:
        entry_id = int(registration.entry_id)
        try:
            picks = provider.picks(entry_id, season, gameweek - 1)
            advice = _member_advice(picks, inputs, projection, rules, league_id=league_id)
        except (EntryError, DataError) as error:
            results.append(MemberViewResult(entry_id, registration.label, False, reason=str(error)))
            member_rows.append(_row(entry_id, registration.label, "empty"))
            continue
        quality = str(advice["data_quality"])
        member_row = _row(entry_id, registration.label, quality)
        raw_missing = advice.get("missing_fields")
        missing = [str(field) for field in raw_missing] if isinstance(raw_missing, list) else []

        # The site addresses these by path: entries/{id}.json for the squad, and
        # advice/{id}/{mode}/{window}.json for a decision under one mode and horizon.
        squad_path = out / "entries" / f"{entry_id}.json"
        squad_path.parent.mkdir(parents=True, exist_ok=True)
        squad_payload = _entry_squad_payload(
            picks,
            inputs,
            projection,
            league_id=league_id,
            member_row=member_row,
            missing=missing,
            scored_gameweek=scored_gameweek,
        )
        squad_path.write_text(
            json.dumps(_envelope(squad_payload, generated_at_utc=generated), indent=2),
            encoding="utf-8",
        )
        written.append(f"entries/{entry_id}.json")

        advice_path = out / "advice" / str(entry_id) / COMPUTED_MODE / f"{COMPUTED_WINDOW}.json"
        advice_path.parent.mkdir(parents=True, exist_ok=True)
        advice_path.write_text(
            json.dumps(_envelope(advice, generated_at_utc=generated), indent=2),
            encoding="utf-8",
        )
        written.append(f"advice/{entry_id}/{COMPUTED_MODE}/{COMPUTED_WINDOW}.json")

        results.append(MemberViewResult(entry_id, registration.label, True))
        member_rows.append(member_row)
    # The standings order is the league's order; registry order is arbitrary.
    if placings:
        member_rows.sort(
            key=lambda row: (int(str(row["rank"])) or 10**6, int(str(row["entry_id"])))
        )
    members_payload = {
        "league_id": int(league_id),
        "league_name": str(league_name),
        "season": season,
        "gameweek": gameweek,
        "public_after_deadline": True,
        "scored_gameweek": scored_gameweek,
        "members": member_rows,
    }
    members_path = out / "members.json"
    members_path.write_text(
        json.dumps(_envelope(members_payload, generated_at_utc=generated), indent=2),
        encoding="utf-8",
    )
    written.append(members_path.name)
    return LeagueViewsReport(
        league_id=int(league_id),
        season=season,
        gameweek=gameweek,
        members=tuple(results),
        files=tuple(sorted(written)),
    )
