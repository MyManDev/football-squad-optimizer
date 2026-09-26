"""Set the stated price of every recorded choice beside what that choice realized.

The protocol is ``docs/live_price_honesty_prereg.md`` and the arithmetic is
``squadopt.application.live_price_honesty``. This runner walks the advice records of every
member, takes for each settled gameweek the record ``weekly_suggestion_eval`` would take (the
last one captured and published before the deadline), and scores the control and every
one-week setting of that record on the gameweek's settled outcomes.

No solver runs and no advice is rebuilt, so the record is deterministic given the records and
the captures, and it is **regenerated** after a settled gameweek rather than guarded against
overwriting. A verdict is carried only once six gameweeks are pooled.

    python -m scripts.measure_live_price_honesty --data-root <checkout>/data
"""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import (
    REPOSITORY_ROOT,
    repository_provenance,
    write_json,
    write_text,
)

from squadopt.application.live_price_honesty import (
    LIVE_PRICE_HONESTY_CONTRACT_VERSION,
    MINIMUM_GAMEWEEKS_FOR_INTERVAL,
    PricedPair,
    pairs_for_record,
    reading,
)
from squadopt.application.weekly_suggestion_eval import SUPPORTED_LEAGUE_ID, review_member_weeks
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import live_event_outcomes, live_payload
from squadopt.data.timestamps import as_instant
from squadopt.live import infer_season

DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "live_price_honesty.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "live_price_honesty.md"


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--season", default="2026-27")
    parser.add_argument("--through-gameweek", type=int, default=None)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args(argv)


def measure(data_root: Path, season: str, through_gameweek: int | None) -> dict[str, Any]:
    record_root, snapshot_root = data_root / "advice_records", data_root / "snapshots"
    captures = [
        read_snapshot(snapshot_root, identifier)
        for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    ]
    captures = [capture for capture in captures if infer_season(capture) == season]
    if not captures:
        raise SystemExit(f"No live capture of {season} under {snapshot_root}.")
    anchor = max(captures, key=lambda item: as_instant(item.metadata.captured_at_utc))
    entries = sorted(
        {
            int(directory.name.removeprefix("entry-"))
            for directory in (record_root / season).glob("gw[0-9][0-9]/entry-*")
            if directory.is_dir()
        }
    )
    selected: dict[tuple[int, int], dict[str, Any]] = {}
    reviews = review_member_weeks(
        record_root=record_root,
        snapshot_root=snapshot_root,
        as_of_snapshot=anchor,
        season=season,
        league_id=SUPPORTED_LEAGUE_ID,
        entry_ids=entries,
        selected_records=selected,
    )
    by_identifier = {capture.metadata.snapshot_id: capture for capture in captures}
    outcomes: dict[tuple[str, int], pd.DataFrame] = {}
    pairs: list[PricedPair] = []
    left_out: dict[str, int] = {}
    not_read: dict[str, int] = {}
    inputs: dict[str, dict[str, set[str]]] = {}
    for entry_id, weeks in reviews.items():
        for week in weeks:
            if through_gameweek is not None and week.gameweek > through_gameweek:
                continue
            if week.status != "available" or week.outcome_snapshot_id is None:
                reason = f"gw{week.gameweek:02d}: {week.reason or week.status}"
                not_read[reason] = not_read.get(reason, 0) + 1
                continue
            key = (week.outcome_snapshot_id, week.gameweek)
            if key not in outcomes:
                capture = by_identifier[week.outcome_snapshot_id]
                outcomes[key] = live_event_outcomes(
                    capture.payloads[live_payload(week.gameweek)],
                    capture.payloads[BOOTSTRAP_PAYLOAD],
                    gameweek=week.gameweek,
                )
            record = selected[entry_id, week.gameweek]
            found, skipped = pairs_for_record(record, outcomes[key])
            pairs.extend(found)
            for reason, count in skipped.items():
                left_out[reason] = left_out.get(reason, 0) + count
            used = inputs.setdefault(
                str(week.gameweek), {"advice_captures": set(), "outcome_captures": set()}
            )
            used["advice_captures"].add(str(record["capture"]["snapshot_id"]))
            used["outcome_captures"].add(week.outcome_snapshot_id)
    document = reading(pairs)
    gameweeks = document["pooled"]["gameweeks"]  # type: ignore[index]
    return {
        "contract_version": LIVE_PRICE_HONESTY_CONTRACT_VERSION,
        "protocol": "docs/live_price_honesty_prereg.md",
        # Which code wrote the record: a committed record has to be checkable against it.
        "provenance": repository_provenance(),
        "season": season,
        "through_gameweek": through_gameweek,
        "members": len(entries),
        "minimum_gameweeks_for_interval": MINIMUM_GAMEWEEKS_FOR_INTERVAL,
        "criterion_evaluated": len(gameweeks) >= MINIMUM_GAMEWEEKS_FOR_INTERVAL,
        "inputs": {
            week: {name: sorted(values) for name, values in used.items()}
            for week, used in sorted(inputs.items())
        },
        "member_weeks_not_read": dict(sorted(not_read.items())),
        "left_out": dict(sorted(left_out.items())),
        "reading": document,
        "pairs": [asdict(pair) for pair in pairs if pair.binding],
    }


def _number(value: object) -> str:
    return "n/a" if value is None else f"{float(str(value)):+.3f}"


_HEADER = (
    "| | Pairs | Binding | Stated cost | Realized cost | Realized minus stated | "
    "Realized above stated | Above the ceiling |\n| --- | --- | --- | --- | --- | --- | --- | --- |"
)


def _row(name: str, summary: dict[str, Any]) -> str:
    ceiling = (
        f"{summary['realized_above_ceiling']} of {summary['pairs_with_ceiling']}"
        if summary["pairs_with_ceiling"]
        else "no ceiling recorded"
    )
    return (
        f"| {name} | {summary['pairs']} | {summary['binding_pairs']} | "
        f"{_number(summary['mean_stated_cost'])} | {_number(summary['mean_realized_cost'])} | "
        f"{_number(summary['mean_realized_minus_stated'])} | "
        f"{summary['realized_above_stated']} of {summary['binding_pairs']} | {ceiling} |"
    )


def _markdown(record: dict[str, Any]) -> str:
    document = record["reading"]
    pooled = document["pooled"]
    lines = [
        "# Live price honesty",
        "",
        f"Protocol: `{record['protocol']}`. Season {record['season']}, {record['members']} "
        f"members, gameweeks read: {pooled['gameweeks'] or 'none'}. Means are over binding "
        "pairs only, in points; a pair whose plan is the control's plan is counted and not "
        "averaged.",
        "",
    ]
    if record["criterion_evaluated"]:
        interval = pooled["interval"]
        verdict = "understates: the criterion fails" if interval["understates"] else "holds"
        lines.append(
            f"**Criterion.** The 90 percent interval of realized minus stated, resampling "
            f"{interval['gameweeks']} whole gameweeks, is [{_number(interval['low'])}, "
            f"{_number(interval['high'])}]. The price {verdict}."
        )
    else:
        lines.append(
            f"**No verdict.** Fewer than {record['minimum_gameweeks_for_interval']} gameweeks, "
            "so no interval is printed and the criterion is not evaluated. Members share one "
            "projection and one set of matches; the table below is descriptive."
        )
    lines += ["", _HEADER, _row("Pooled", pooled)]
    lines += [_row(name, summary) for name, summary in document["by_family"].items()]
    lines += [
        _row(f"Gameweek {week}", summary) for week, summary in document["by_gameweek"].items()
    ]
    for title, key in (
        ("Left out", "left_out"),
        ("Member weeks not read", "member_weeks_not_read"),
    ):
        if record[key]:
            lines += ["", f"## {title}", ""]
            lines += [f"- `{reason}`: {count}" for reason, count in record[key].items()]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    record = measure(arguments.data_root, arguments.season, arguments.through_gameweek)
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(f"Gameweeks read: {record['reading']['pooled']['gameweeks'] or 'none'}")
    print(f"Wrote {arguments.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
