"""Audit the live season's projections against what happened, and against the game's own forecast.

The protocol is ``docs/live_projection_audit_prereg.md`` and the arithmetic is
``squadopt.evaluation.live_projection_audit``. This runner finds what the disk allows:

* a gameweek is audited when a capture exists from before its deadline, a projection handoff
  was made from that capture, and a later capture holds the gameweek's settled live payload;
* gameweek 1 is read for our decided projection only, from the ledger, because its capture
  was lost and with it the game's forecast;
* every other settled gameweek is named with the reason it could not be read.

No solver runs, so the record is deterministic given the captures and is **regenerated** after
each settled gameweek rather than guarded against overwriting. It names every capture and
handoff it read, so a number that moved can be traced to an input that moved.

    python -m scripts.measure_live_projection_audit --data-root <checkout>/data
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    availability_snapshot,
    game_forecast,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    player_snapshot,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.evaluation.live_projection_audit import (
    LIVE_PROJECTION_AUDIT_CONTRACT_VERSION,
    TOP_PER_POSITION,
    audit_frame,
    pool,
    summarise_gameweek,
)
from squadopt.live import infer_season
from squadopt.live.recommendation import InSeasonProjection, read_projection_handoff
from squadopt.prediction.availability import apply_availability

DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "live_projection_audit.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "live_projection_audit.md"
#: No "better than" before this many gameweeks are pooled (the protocol's own number).
MINIMUM_POOLED_GAMEWEEKS = 6


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args(argv)


def _multipliers(bootstrap: bytes) -> dict[int, float]:
    """The availability rule's own multiplier, read by scaling a projection of ones."""

    availability = availability_snapshot(bootstrap)
    ones = pd.DataFrame(
        {"player_id": availability["player_id"].astype("int64"), "expected_points": 1.0}
    ).reset_index(drop=True)
    scaled = apply_availability(ones, availability).multiplier.reset_index(drop=True)
    return {int(p): float(v) for p, v in zip(ones["player_id"], scaled, strict=True)}


def _prior_minutes_per_week(bootstrap: bytes) -> dict[int, float] | None:
    """Season minutes the capture states for each player, over the gameweeks it had scored.

    Blank and double gameweeks make this approximate for the clubs they touch; the
    buckets it feeds are wide. With no gameweek scored there is no prior to state.
    """

    weeks = len(scored_gameweeks(bootstrap))
    if weeks == 0:
        return None
    prior: dict[int, float] = {}
    for element in json.loads(bootstrap)["elements"]:
        code, minutes = element.get("code"), element.get("minutes")
        # A missing figure is absent, never zero.
        if isinstance(code, int) and isinstance(minutes, int) and not isinstance(minutes, bool):
            prior[code] = minutes / weeks
    return prior


def _handoffs(handoff_root: Path, capture_id: str) -> list[InSeasonProjection]:
    directory = handoff_root / "by-capture" / capture_id
    if not directory.is_dir():
        return []
    return [read_projection_handoff(path) for path in sorted(directory.glob("*.json"))]


def _ledger_decision(ledger_root: Path, season: str, gameweek: int) -> Mapping[str, object] | None:
    path = ledger_root / season / f"gw{gameweek:02d}" / "decision.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else None


def _ledger_mode(decision: Mapping[str, object] | None) -> str | None:
    metadata = decision.get("metadata") if decision else None
    mode = metadata.get("mode") if isinstance(metadata, dict) else None
    return mode if isinstance(mode, str) else None


def _ledger_handoff_fingerprint(decision: Mapping[str, object] | None) -> str | None:
    metadata = decision.get("metadata") if decision else None
    value = metadata.get("projection_handoff_fingerprint") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) else None


def _opening_week(
    ledger_root: Path, season: str, outcomes: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, object]] | None:
    """Gameweek 1 from the ledger: the decided numbers are all that survived."""

    path = ledger_root / season / "gw01" / "projections.csv"
    if not path.is_file():
        return None
    table = pd.read_csv(path)
    frame = audit_frame(
        table.loc[:, ["player_id", "position", "price_tenths"]],
        outcomes,
        expected_points=None,
        multipliers=None,
        decided=dict(zip(table["player_id"].astype(int), table["expected_points"], strict=True)),
        game=None,
    )
    decision = _ledger_decision(ledger_root, season, 1)
    described: dict[str, object] = {
        "source": "ledger projections.csv (availability already applied)",
        "model_version": decision.get("model_version") if decision else None,
        "ledger_mode": _ledger_mode(decision),
        "note": (
            "The capture this projection was made from was lost on 2026-09-10, and with it "
            "the game's forecast and the unconditional projection. An opening-week model, "
            "read for our decided numbers only and never pooled."
        ),
    }
    return frame, described


def measure(data_root: Path) -> dict[str, object]:
    snapshot_root = data_root / "snapshots"
    handoff_root = data_root / "handoffs"
    ledger_root = data_root / "ledger"
    identifiers = list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    if not identifiers:
        raise SystemExit(f"No live capture under {snapshot_root}.")
    captures: list[CapturedSnapshot] = [read_snapshot(snapshot_root, i) for i in identifiers]
    settled = captures[-1]
    settled_bootstrap = settled.payloads[BOOTSTRAP_PAYLOAD]
    season = infer_season(settled)
    deadlines = {d.gameweek: d.deadline_utc for d in gameweek_deadlines(settled_bootstrap)}

    gameweeks: dict[str, object] = {}
    not_audited: dict[str, str] = {}
    primary_frames: dict[int, pd.DataFrame] = {}
    for gameweek in sorted(scored_gameweeks(settled_bootstrap)):
        payload = settled.payloads.get(live_payload(gameweek))
        if payload is None:
            not_audited[str(gameweek)] = "the newest capture holds no settled payload for it"
            continue
        outcomes = live_event_outcomes(payload, settled_bootstrap, gameweek=gameweek)
        moment = as_instant(deadlines[gameweek])
        before = [c for c in captures if as_instant(c.metadata.captured_at_utc) < moment]
        if not before:
            opening = _opening_week(ledger_root, season, outcomes) if gameweek == 1 else None
            if opening is None:
                not_audited[str(gameweek)] = (
                    "no capture from before its deadline survives, so neither our projection "
                    "nor the game's forecast can be read"
                )
                continue
            frame, described = opening
            gameweeks[str(gameweek)] = {
                "deadline_utc": deadlines[gameweek],
                "pre_deadline_capture": None,
                "projections": [{**described, "reading": summarise_gameweek(frame)}],
            }
            continue

        capture = before[-1]
        bootstrap = capture.payloads[BOOTSTRAP_PAYLOAD]
        handoffs = _handoffs(handoff_root, capture.metadata.snapshot_id)
        if not handoffs:
            not_audited[str(gameweek)] = (
                f"no projection handoff was kept for {capture.metadata.snapshot_id}, the last "
                "capture before its deadline"
            )
            continue
        players = player_snapshot(bootstrap)
        multipliers = _multipliers(bootstrap)
        forecast = game_forecast(bootstrap)
        prior_minutes = _prior_minutes_per_week(bootstrap)
        decision = _ledger_decision(ledger_root, season, gameweek)
        held = _ledger_handoff_fingerprint(decision)
        readings: list[dict[str, object]] = []
        for handoff in handoffs:
            frame = audit_frame(
                players,
                outcomes,
                expected_points=handoff.expected_points,
                multipliers=multipliers,
                game=forecast,
                prior_minutes_per_week=prior_minutes,
            )
            in_ledger = held is not None and handoff.fingerprint == held
            if in_ledger or (gameweek not in primary_frames and handoff is handoffs[-1]):
                primary_frames[gameweek] = frame
            readings.append(
                {
                    "model_name": handoff.model_name,
                    "model_version": handoff.model_version,
                    "handoff_fingerprint": handoff.fingerprint,
                    "in_ledger": in_ledger,
                    "ledger_mode": _ledger_mode(decision) if in_ledger else None,
                    "reading": summarise_gameweek(frame),
                }
            )
        hours = (moment - as_instant(capture.metadata.captured_at_utc)).total_seconds() / 3600
        gameweeks[str(gameweek)] = {
            "deadline_utc": deadlines[gameweek],
            "pre_deadline_capture": capture.metadata.snapshot_id,
            "hours_before_deadline": round(hours, 2),
            "projections": readings,
        }

    pooled = pool(primary_frames)
    pooled["comparison_may_be_stated"] = len(primary_frames) >= MINIMUM_POOLED_GAMEWEEKS
    pooled["primary_projection_rule"] = (
        "the handoff the ledger's decision names for that gameweek; where the ledger names "
        "none of the kept handoffs, the last one by file name"
    )
    return {
        "contract_version": LIVE_PROJECTION_AUDIT_CONTRACT_VERSION,
        "prereg": "docs/live_projection_audit_prereg.md",
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "season": season,
        "settled_capture": settled.metadata.snapshot_id,
        "captures_read": list(identifiers),
        "top_per_position": TOP_PER_POSITION,
        "minimum_pooled_gameweeks": MINIMUM_POOLED_GAMEWEEKS,
        "descriptive_only": True,
        "operational_control_changed": False,
        "gameweeks": gameweeks,
        "not_audited": not_audited,
        "pooled": pooled,
    }


def _number(value: object, places: int = 3) -> str:
    return f"{value:+.{places}f}" if isinstance(value, float) else "n/a"


def _row(label: str, reading: Mapping[str, object]) -> str:
    everyone = reading["all_players"]
    top = reading["top_per_position"]
    rank = reading["rank_agreement_within_position"]
    split = reading["appearance_split"]
    assert isinstance(everyone, dict) and isinstance(top, dict)
    assert isinstance(rank, dict) and isinstance(split, dict)
    share = split.get("share_on_players_who_did_not_appear")
    return (
        f"| {label} | {everyone.get('players', 0)} | "
        f"{_number(everyone.get('mean_absolute_error')).lstrip('+')} | "
        f"{_number(everyone.get('bias'))} | "
        f"{_number(top.get('mean_absolute_error')).lstrip('+')} | {_number(top.get('bias'))} | "
        f"{_number(rank.get('weighted_mean')).lstrip('+')} | "
        f"{_number(share).lstrip('+')} |"
    )


_HEADER = (
    "| forecast | players | MAE | bias | MAE, top per position | bias, top per position | "
    "rank agreement within position | share of forecast points on players who did not appear |\n"
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
)


_ABSENT_SPLITS = (
    ("by_position", "position"),
    ("by_price_band", "price band"),
    ("by_forecast_size", "size of the forecast"),
    ("by_our_availability_rule", "our availability rule"),
)


def _absent_cell(block: object) -> str:
    if not isinstance(block, dict) or not block.get("players"):
        return "none"
    return f"{block['forecast_points']:.1f} ({block['players']})"


def _absent_table(forecasts: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Forecast points on players who did not appear, by where they sat."""

    blocks: dict[str, dict[str, object]] = {}
    for name, summary in forecasts.items():
        block = summary.get("absent_forecast")
        if isinstance(block, dict):
            blocks[name] = block
    if not blocks:
        return []
    names = list(blocks)
    lines = [
        "",
        "Forecast points on players who did not appear, as points (players):",
        "",
        "| split | bucket | " + " | ".join(names) + " |",
        "| --- | --- | " + " | ".join("---:" for _ in names) + " |",
        "| all | all | " + " | ".join(_absent_cell(blocks[name]) for name in names) + " |",
    ]
    for key, title in _ABSENT_SPLITS:
        first = blocks[names[0]][key]
        assert isinstance(first, dict)
        for bucket in first:
            cells = []
            for name in names:
                split = blocks[name][key]
                assert isinstance(split, dict)
                cells.append(_absent_cell(split.get(bucket)))
            lines.append(f"| {title} | {bucket} | " + " | ".join(cells) + " |")
    return lines


def _prior_table(forecasts: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Forecast against realized points by how much the player had been playing."""

    blocks: dict[str, dict[str, object]] = {}
    for name, summary in forecasts.items():
        block = summary.get("by_prior_minutes")
        if isinstance(block, dict) and isinstance(block.get("buckets"), dict):
            blocks[name] = block["buckets"]
    if not blocks:
        return []
    lines = [
        "",
        "By minutes a gameweek played this season before the deadline:",
        "",
        "| forecast | prior minutes | players | appeared | forecast points | "
        "realized points | MAE | bias |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, buckets in blocks.items():
        for label, block in buckets.items():
            assert isinstance(block, dict)
            if not block.get("players"):
                continue
            lines.append(
                f"| {name} | {label} | {block['players']} | {block['appeared']} | "
                f"{block['forecast_points']:.1f} | {block['realized_points']:.1f} | "
                f"{_number(block.get('mean_absolute_error')).lstrip('+')} | "
                f"{_number(block.get('bias'))} |"
            )
    return lines


def _markdown(record: Mapping[str, object]) -> str:
    lines = [
        "# Live projection audit",
        "",
        f"Contract `{record['contract_version']}`, season {record['season']}, generated "
        f"{record['generated_at_utc']} from settled capture `{record['settled_capture']}`.",
        "Descriptive only: no gate, no interval, nothing promoted. Bias is realized minus "
        'forecast, so a negative bias is a forecast that ran high. "Top per position" is '
        "each forecast's own highest forecast players, so those columns describe different "
        "players for different forecasts; the paired line under a table uses one set. "
        "Protocol: `docs/live_projection_audit_prereg.md`.",
        "",
    ]
    gameweeks = record["gameweeks"]
    assert isinstance(gameweeks, dict)
    for gameweek, entry in gameweeks.items():
        lines += [f"## Gameweek {gameweek}", ""]
        capture = entry["pre_deadline_capture"]
        lines.append(
            f"Deadline {entry['deadline_utc']}; "
            + (
                f"forecasts from `{capture}`, {entry['hours_before_deadline']} hours before it."
                if capture
                else "no capture from before it survives."
            )
        )
        for projection in entry["projections"]:
            reading = projection["reading"]
            title = projection.get("model_version") or "ours"
            tags = []
            if projection.get("in_ledger"):
                tags.append(f"in the ledger as `{projection.get('ledger_mode')}`")
            if projection.get("note"):
                tags.append(str(projection["note"]))
            lines += ["", f"**{title}**" + (f" ({'; '.join(tags)})" if tags else ""), "", _HEADER]
            for name, summary in reading["forecasts"].items():
                lines.append(_row(name, summary))
            lines += _absent_table(reading["forecasts"])
            lines += _prior_table(reading["forecasts"])
            paired = reading.get("ours_decided_minus_game")
            if isinstance(paired, dict) and paired.get("players"):
                lines += [
                    "",
                    "Absolute error, ours as decided minus the game's forecast: "
                    f"{_number(paired['mean_absolute_error_difference'])} over "
                    f"{paired['players']} players, "
                    f"{_number(paired['top_per_position_difference'])} over the game's top "
                    f"{record['top_per_position']} per position "
                    f"({paired['top_per_position_players']} players). One gameweek; players "
                    "share fixtures, so no interval is given.",
                ]
        lines.append("")
    skipped = record["not_audited"]
    assert isinstance(skipped, dict)
    if skipped:
        lines += ["## Not audited", ""]
        lines += [f"- Gameweek {gameweek}: {reason}." for gameweek, reason in skipped.items()]
        lines.append("")
    pooled = record["pooled"]
    assert isinstance(pooled, dict)
    lines += ["## Pooled", ""]
    if not pooled.get("gameweeks"):
        lines.append("Nothing to pool yet.")
    else:
        lines.append(
            f"Rests on {pooled['rests_on_gameweeks']} gameweek(s): {pooled['gameweeks']}. "
            + (
                "Enough gameweeks for the comparison to be stated."
                if pooled["comparison_may_be_stated"]
                else f"Fewer than {record['minimum_pooled_gameweeks']}, so no forecast is "
                "called better than another here."
            )
        )
        lines += ["", _HEADER]
        for name, summary in pooled["forecasts"].items():
            lines.append(_row(name, summary))
        lines += _absent_table(pooled["forecasts"])
        lines += _prior_table(pooled["forecasts"])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    record = measure(arguments.data_root)
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    audited = ", ".join(record["gameweeks"]) or "none"  # type: ignore[arg-type]
    print(f"Audited gameweeks: {audited}")
    print(f"Wrote {arguments.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
