"""Audit the live season's projections against what happened, and against the game's own forecast.

The protocol is ``docs/live_projection_audit_prereg.md`` and the arithmetic is
``squadopt.evaluation.live_projection_audit``. This runner finds what the disk allows:

* a gameweek is audited when a capture exists from before its deadline, a projection handoff
  was made from that capture, and a later capture holds the gameweek's settled live payload;
* gameweek 1 is read for our decided projection only, from the ledger, because its capture
  was lost and with it the game's forecast;
* every other settled gameweek is named with the reason it could not be read.

Which handoff a gameweek pools is the one its published advice read: the retained
``member_advice_record_v2`` records of the last publish before the deadline name a capture
and a handoff fingerprint, the rule ``docs/defcon_component_prereg.md`` section 4 uses. Every
other handoff of that capture is shown beside it and never pooled, and one the ledger records
as ``replay``, or that only advice published after the deadline names, is labelled ``replay``.
A week whose retained advice names no pre-deadline handoff is listed with the reason and not
pooled; no later file stands in for it.

No solver runs, so the record is deterministic given the captures and is **regenerated** after
each settled gameweek. It names every capture and handoff it read, so a number that moved can
be traced to an input that moved. ``--through-gameweek`` bounds the settled weeks it reads,
and a run bounded at a fixed reading date (gameweek 9 or 15) also takes that dated pooled
reading. A dated reading already in the record is carried into every regeneration as it
stands, and a run that would give it different numbers is refused.

    python -m scripts.measure_live_projection_audit --data-root <checkout>/data \
        [--through-gameweek 9]
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.application.advice_record import MEMBER_ADVICE_RECORD_CONTRACT_VERSION
from squadopt.data.errors import DataError
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
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
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
#: The pooled readings the protocol fixes: after gameweek 9 and after gameweek 15.
DATED_POOLED_GAMEWEEKS: Final = (9, 15)
#: Which handoff a gameweek pools, stated in the record so a check can tell which rule wrote it.
POOLING_RULE: Final = (
    "the handoff written before the deadline that the week's published advice read: the one "
    "the retained advice records of the last publish before the deadline name, with their "
    "capture (docs/defcon_component_prereg.md section 4); a week whose retained advice names "
    "no such handoff is not pooled, and a handoff written after the deadline is labelled "
    "replay and never pooled"
)
#: The labels a gameweek's handoffs carry. Only ``pooled`` enters the pool.
POOLED, REPLAY, BESIDE = "pooled", "replay", "beside"
#: Fields of a dated pooled reading that say when and from what it was taken, not what it read.
_DATED_CLOCK_FIELDS: Final = ("taken_at_utc", "settled_capture")


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--through-gameweek", type=int, default=None)
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


@dataclass(frozen=True, slots=True)
class PublishedHandoff:
    """The capture and handoff the week's last pre-deadline publish read, as its records say."""

    snapshot_id: str
    captured_at_utc: str
    handoff_fingerprint: str
    published_at_utc: str
    records: int


@dataclass(frozen=True, slots=True)
class WeekPublication:
    """What the retained advice records say about one gameweek.

    ``published`` is the handoff to pool, or ``None`` with ``reason`` saying why there is none.
    ``after_deadline`` holds the handoffs that only advice published at or after the deadline
    names: written after it, so a replay whatever the ledger says.
    """

    published: PublishedHandoff | None
    reason: str | None
    after_deadline: frozenset[str]


def _instant(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise DataError(f"{label} is not text")
    return as_instant(normalize_utc_timestamp(value, label=label))


def _published_handoff(
    record_root: Path, season: str, gameweek: int, deadline_utc: str
) -> WeekPublication:
    """The handoff the week's published advice read, by the DEFCON protocol's rule.

    Every retained record of the week is read, from every member. A record counts when it was
    published strictly before the deadline from a capture taken before the deadline and no
    later than the publish. The last such publish is the week's published advice, and every
    record of that instant has to name one capture and one handoff. File times are never read:
    they are not evidence of when a record was written.
    """

    directory = record_root / season / f"gw{gameweek:02d}"
    deadline = as_instant(deadline_utc)
    before: list[tuple[datetime, str, str, str | None]] = []
    named_before: set[str] = set()
    named_after: set[str] = set()
    paths = sorted(directory.glob("entry-*/*/advice.json")) if directory.is_dir() else []
    for path in paths:
        if path.parent.name.startswith(".") or path.parent.parent.name.startswith("."):
            # A hidden sibling is a writer's staging directory, never a landed record.
            continue
        where = path.relative_to(record_root).as_posix()
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise DataError("not a JSON object")
            if (
                document.get("contract_version") != MEMBER_ADVICE_RECORD_CONTRACT_VERSION
                or document.get("season") != season
                or document.get("gameweek") != gameweek
            ):
                raise DataError("it states another contract, season or gameweek")
            capture = document.get("capture")
            provenance = document.get("provenance")
            if not isinstance(capture, dict) or not isinstance(provenance, dict):
                raise DataError("it carries no capture or provenance block")
            snapshot_id = capture.get("snapshot_id")
            if not isinstance(snapshot_id, str) or snapshot_id != path.parent.name:
                raise DataError("its capture is not the directory it is filed under")
            captured_at = capture.get("captured_at_utc")
            captured = _instant(captured_at, "capture.captured_at_utc")
            published = _instant(document.get("generated_at_utc"), "generated_at_utc")
            fingerprint = provenance.get("projection_handoff_fingerprint")
            if fingerprint is not None and not isinstance(fingerprint, str):
                raise DataError("its handoff fingerprint is not text")
        except (OSError, ValueError, DataError) as error:
            return WeekPublication(
                None, f"the retained advice record {where} cannot be read ({error})", frozenset()
            )
        if published >= deadline:
            if fingerprint is not None:
                named_after.add(fingerprint)
            continue
        if captured >= deadline or captured > published:
            return WeekPublication(
                None,
                f"the retained advice record {where} was published before the deadline from a "
                "capture taken after the deadline or after the publish",
                frozenset(),
            )
        assert isinstance(captured_at, str)
        before.append((published, snapshot_id, captured_at, fingerprint))
        if fingerprint is not None:
            named_before.add(fingerprint)
    after = frozenset(named_after - named_before)
    if not before:
        reason = "no retained advice record of it was published before its deadline" + (
            ", only after it" if paths else ""
        )
        return WeekPublication(None, reason, after)
    last = max(item[0] for item in before)
    identities = {(item[1], item[2], item[3]) for item in before if item[0] == last}
    if len(identities) != 1:
        return WeekPublication(
            None,
            "the records of the last publish before its deadline name "
            f"{len(identities)} different captures or handoffs",
            after,
        )
    snapshot_id, captured_at, fingerprint = next(iter(identities))
    if fingerprint is None:
        return WeekPublication(
            None,
            "the last advice published before its deadline names no projection handoff",
            after,
        )
    published_handoff = PublishedHandoff(
        snapshot_id=snapshot_id,
        captured_at_utc=captured_at,
        handoff_fingerprint=fingerprint,
        published_at_utc=last.isoformat().replace("+00:00", "Z"),
        records=sum(1 for item in before if item[0] == last),
    )
    return WeekPublication(published_handoff, None, after)


def _label(
    handoff: InSeasonProjection,
    *,
    published: str | None,
    held: str | None,
    ledger_mode: str | None,
    after_deadline: frozenset[str],
) -> str:
    if published is not None and handoff.fingerprint == published:
        return POOLED
    if handoff.fingerprint in after_deadline or (
        held == handoff.fingerprint and ledger_mode == "replay"
    ):
        return REPLAY
    return BESIDE


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
        "label": BESIDE,
        "note": (
            "The capture this projection was made from was lost on 2026-09-10, and with it "
            "the game's forecast and the unconditional projection. An opening-week model, "
            "read for our decided numbers only and never pooled."
        ),
    }
    return frame, described


def _comparable(reading: Mapping[str, object]) -> str:
    """A dated reading without its clock, in one canonical text, for comparison."""

    kept = {key: value for key, value in reading.items() if key not in _DATED_CLOCK_FIELDS}
    return json.dumps(kept, sort_keys=True, default=str)


def _dated_readings(
    previous: Mapping[str, object] | None,
    season: str,
    taken: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    """Every dated pooled reading the record keeps: the earlier ones as they stand, plus this.

    A dated reading is taken once. A regeneration carries each one it finds in the record
    verbatim, and a run that reads a fixed date again keeps the reading already there when it
    reads the same numbers and is refused when it does not: a changed number there is a
    changed input, which a person has to look at before anything is replaced.
    """

    carried: dict[int, dict[str, object]] = {}
    earlier = previous.get("dated_pooled_readings", []) if previous else []
    if not isinstance(earlier, list):
        raise SystemExit("The existing record's dated pooled readings are not a list.")
    if earlier and previous is not None and previous.get("season") != season:
        raise SystemExit(
            f"The existing record is of season {previous.get('season')!r} and holds dated "
            f"pooled readings; this run reads {season!r}. Write to another output."
        )
    for reading in earlier:
        if not isinstance(reading, dict) or not isinstance(reading.get("through_gameweek"), int):
            raise SystemExit("The existing record holds a dated pooled reading with no week.")
        carried[int(reading["through_gameweek"])] = dict(reading)
    if taken is not None:
        week = taken["through_gameweek"]
        assert isinstance(week, int)
        existing = carried.get(week)
        if existing is None:
            carried[week] = dict(taken)
        elif _comparable(existing) != _comparable(taken):
            raise SystemExit(
                f"The record already holds the pooled reading through gameweek {week}, taken "
                f"{existing.get('taken_at_utc')}, and this run reads different numbers for it. "
                "A dated reading is never replaced: the inputs it read have changed, so find "
                "out why before anything is written."
            )
    return [carried[week] for week in sorted(carried)]


def measure(
    data_root: Path,
    *,
    through_gameweek: int | None = None,
    previous: Mapping[str, object] | None = None,
) -> dict[str, object]:
    snapshot_root = data_root / "snapshots"
    handoff_root = data_root / "handoffs"
    ledger_root = data_root / "ledger"
    record_root = data_root / "advice_records"
    identifiers = list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    if not identifiers:
        raise SystemExit(f"No live capture under {snapshot_root}.")
    if through_gameweek is not None and through_gameweek < 1:
        raise SystemExit("--through-gameweek must be a positive gameweek.")
    captures: list[CapturedSnapshot] = [read_snapshot(snapshot_root, i) for i in identifiers]
    by_identifier = {capture.metadata.snapshot_id: capture for capture in captures}
    settled = captures[-1]
    settled_bootstrap = settled.payloads[BOOTSTRAP_PAYLOAD]
    season = infer_season(settled)
    deadlines = {d.gameweek: d.deadline_utc for d in gameweek_deadlines(settled_bootstrap)}
    weeks = sorted(
        gameweek
        for gameweek in scored_gameweeks(settled_bootstrap)
        if through_gameweek is None or gameweek <= through_gameweek
    )

    gameweeks: dict[str, object] = {}
    not_audited: dict[str, str] = {}
    not_pooled: dict[str, str] = {}
    pooled_handoffs: dict[str, str] = {}
    primary_frames: dict[int, pd.DataFrame] = {}
    for gameweek in weeks:
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
            not_pooled[str(gameweek)] = (
                "an opening-week model read from the ledger, with no capture and no handoff"
            )
            continue

        week = _published_handoff(record_root, season, gameweek, deadlines[gameweek])
        published = week.published
        reason = week.reason
        capture: CapturedSnapshot | None = None
        if published is not None:
            capture = by_identifier.get(published.snapshot_id)
            if capture is None:
                reason = (
                    f"the capture {published.snapshot_id} its published advice read is not "
                    "among the captures on disk"
                )
            elif as_instant(capture.metadata.captured_at_utc) != as_instant(
                published.captured_at_utc
            ):
                reason = (
                    f"the capture {published.snapshot_id} on disk and its published advice "
                    "disagree on when it was taken"
                )
                capture = None
        source = "published_advice"
        if capture is None:
            # Shown for the record, never pooled: no publish read this capture.
            published = None
            capture = before[-1]
            source = "last_before_deadline"
        bootstrap = capture.payloads[BOOTSTRAP_PAYLOAD]
        handoffs = _handoffs(handoff_root, capture.metadata.snapshot_id)
        if not handoffs:
            which = (
                "the capture its published advice read"
                if source == "published_advice"
                else "the last capture"
            )
            not_audited[str(gameweek)] = (
                f"no projection handoff was kept for {capture.metadata.snapshot_id}, {which} "
                "before its deadline"
            )
            continue
        if published is not None and not any(
            handoff.fingerprint == published.handoff_fingerprint for handoff in handoffs
        ):
            reason = (
                f"the handoff {published.handoff_fingerprint[:8]} its published advice read is "
                f"not kept for {capture.metadata.snapshot_id}"
            )
            published = None
        players = player_snapshot(bootstrap)
        multipliers = _multipliers(bootstrap)
        forecast = game_forecast(bootstrap)
        prior_minutes = _prior_minutes_per_week(bootstrap)
        decision = _ledger_decision(ledger_root, season, gameweek)
        held = _ledger_handoff_fingerprint(decision)
        mode = _ledger_mode(decision)
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
            label = _label(
                handoff,
                published=None if published is None else published.handoff_fingerprint,
                held=held,
                ledger_mode=mode,
                after_deadline=week.after_deadline,
            )
            if label == POOLED and gameweek not in primary_frames:
                primary_frames[gameweek] = frame
                pooled_handoffs[str(gameweek)] = handoff.fingerprint
            readings.append(
                {
                    "model_name": handoff.model_name,
                    "model_version": handoff.model_version,
                    "handoff_fingerprint": handoff.fingerprint,
                    "label": label,
                    "in_ledger": in_ledger,
                    "ledger_mode": mode if in_ledger else None,
                    "reading": summarise_gameweek(frame),
                }
            )
        if gameweek not in primary_frames:
            not_pooled[str(gameweek)] = reason or "no handoff of its capture was published"
        hours = (moment - as_instant(capture.metadata.captured_at_utc)).total_seconds() / 3600
        gameweeks[str(gameweek)] = {
            "deadline_utc": deadlines[gameweek],
            "pre_deadline_capture": capture.metadata.snapshot_id,
            "capture_source": source,
            "published_at_utc": week.published.published_at_utc
            if week.published is not None and source == "published_advice"
            else None,
            "hours_before_deadline": round(hours, 2),
            "projections": readings,
        }

    generated = datetime.now(UTC).replace(microsecond=0).isoformat()
    pooled = pool(primary_frames)
    pooled["comparison_may_be_stated"] = len(primary_frames) >= MINIMUM_POOLED_GAMEWEEKS
    pooled["primary_projection_rule"] = POOLING_RULE
    taken: dict[str, object] | None = None
    if (
        through_gameweek in DATED_POOLED_GAMEWEEKS
        and through_gameweek in weeks
        and live_payload(through_gameweek) in settled.payloads
    ):
        taken = {
            "through_gameweek": through_gameweek,
            "taken_at_utc": generated,
            "settled_capture": settled.metadata.snapshot_id,
            "pooled_handoffs": dict(pooled_handoffs),
            "not_pooled": dict(not_pooled),
            "pooled": pooled,
        }
    # The record is JSON: compare what will be written, not the objects that produced it.
    if taken is not None:
        taken = json.loads(json.dumps(taken, default=str))
    return {
        "contract_version": LIVE_PROJECTION_AUDIT_CONTRACT_VERSION,
        "prereg": "docs/live_projection_audit_prereg.md",
        "generated_at_utc": generated,
        "season": season,
        "settled_capture": settled.metadata.snapshot_id,
        "through_gameweek": through_gameweek,
        "captures_read": list(identifiers),
        "top_per_position": TOP_PER_POSITION,
        "minimum_pooled_gameweeks": MINIMUM_POOLED_GAMEWEEKS,
        "descriptive_only": True,
        "operational_control_changed": False,
        "gameweeks": gameweeks,
        "not_audited": not_audited,
        "not_pooled": not_pooled,
        "pooled_handoffs": pooled_handoffs,
        "pooled": pooled,
        "dated_pooled_readings": _dated_readings(previous, season, taken),
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
        f"{record['generated_at_utc']} from settled capture `{record['settled_capture']}`"
        + (
            f", reading settled gameweeks through {record['through_gameweek']}."
            if record.get("through_gameweek") is not None
            else "."
        ),
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
                f"forecasts from `{capture}`, {entry['hours_before_deadline']} hours before it"
                + (
                    f", the capture the advice published at {entry['published_at_utc']} read."
                    if entry.get("capture_source") == "published_advice"
                    else ", the last capture before it: no published advice is read from it."
                )
                if capture
                else "no capture from before it survives."
            )
        )
        for projection in entry["projections"]:
            reading = projection["reading"]
            title = projection.get("model_version") or "ours"
            tags = [_LABELS[str(projection.get("label", BESIDE))]]
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
    left_out = record.get("not_pooled") or {}
    assert isinstance(left_out, dict)
    if left_out:
        lines += ["## Not pooled", ""]
        lines += [f"- Gameweek {gameweek}: {reason}." for gameweek, reason in left_out.items()]
        lines.append("")
    pooled = record["pooled"]
    assert isinstance(pooled, dict)
    lines += ["## Pooled", "", f"Each gameweek pools {pooled['primary_projection_rule']}.", ""]
    lines += _pooled_lines(pooled, record)
    dated = record.get("dated_pooled_readings") or []
    assert isinstance(dated, list)
    for reading in dated:
        lines += [
            "",
            f"## Dated pooled reading through gameweek {reading['through_gameweek']}",
            "",
            f"Taken {reading['taken_at_utc']} from settled capture `{reading['settled_capture']}`"
            " and kept as it stands in every later regeneration. Pooled handoffs: "
            + (
                ", ".join(
                    f"GW{week} `{fingerprint[:8]}`"
                    for week, fingerprint in reading["pooled_handoffs"].items()
                )
                or "none"
            )
            + ".",
            "",
        ]
        lines += _pooled_lines(reading["pooled"], record)
    return "\n".join(lines) + "\n"


_LABELS: Final = {
    POOLED: "pooled: the handoff the published advice read",
    REPLAY: "`replay`: written after the deadline, never pooled",
    BESIDE: "shown beside, not pooled",
}


def _pooled_lines(pooled: Mapping[str, object], record: Mapping[str, object]) -> list[str]:
    if not pooled.get("gameweeks"):
        return ["Nothing to pool yet."]
    forecasts = pooled["forecasts"]
    assert isinstance(forecasts, dict)
    lines = [
        f"Rests on {pooled['rests_on_gameweeks']} gameweek(s): {pooled['gameweeks']}. "
        + (
            "Enough gameweeks for the comparison to be stated."
            if pooled["comparison_may_be_stated"]
            else f"Fewer than {record['minimum_pooled_gameweeks']}, so no forecast is "
            "called better than another here."
        ),
        "",
        _HEADER,
    ]
    for name, summary in forecasts.items():
        lines.append(_row(name, summary))
    lines += _absent_table(forecasts)
    lines += _prior_table(forecasts)
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    previous: Mapping[str, object] | None = None
    if arguments.json_output.is_file():
        loaded = json.loads(arguments.json_output.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise SystemExit(f"{arguments.json_output} is not a JSON object.")
        previous = loaded
    record = measure(
        arguments.data_root, through_gameweek=arguments.through_gameweek, previous=previous
    )
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    audited = ", ".join(record["gameweeks"]) or "none"  # type: ignore[arg-type]
    print(f"Audited gameweeks: {audited}")
    print(f"Wrote {arguments.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
