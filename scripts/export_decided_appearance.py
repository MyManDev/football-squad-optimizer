"""Write the appearance probabilities each settled week's decision actually used.

    python -m scripts.export_decided_appearance --data-root <checkout>/data --dry-run
    python -m scripts.export_decided_appearance --data-root <checkout>/data

``scripts.measure_double_reduction`` takes these as ``--fitted`` and refuses to guess them,
because its question (#531 item 1) is about the numbers the week used, and a re-fit with more
history than the week had answers a different one. This finds them without guessing:

* the weeks are the settled outcome tables under ``--outcomes-dir`` (what
  ``scripts.export_settled_outcomes`` writes), and each week's decision capture is its table's
  own pre-deadline capture;
* the projection is the handoff kept for that capture whose fingerprint the ledger's decision
  names, and no other: a capture can hold several handoffs and one was decided from;
* a handoff that states ``appearance_probability`` (written from gameweek 6 on) is read as it
  stands;
* an older handoff that does not is rebuilt through the producer's own
  ``_component_table(include_components=True)`` from the same capture, the path
  ``scripts._phase_e_live`` already uses, and the rebuild is kept only if its component
  fingerprint and every expected point equal the handoff's. A rebuild that differs is a
  different projection and is refused.

A player the component route did not model (the direct-control route) has no appearance
probability and gets no row, so the measurement leaves him out rather than reading a zero.
The output is evidence under ``artifacts/`` (ADR 0003 tiers) with a manifest that names, per
week, the handoff, how its probabilities were obtained and how many rows it gave.

Reads the captures, handoffs, ledger and archive; writes only the output pair. Solves
nothing, promotes nothing.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, repository_provenance, write_json

from squadopt.application.projection_handoff import _component_table
from squadopt.application.settled_outcomes import DEFAULT_OUTPUT_DIR as SETTLED_OUTCOMES_DIR
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD
from squadopt.data.sources.fpl_live import FIXTURES_PAYLOAD, gameweek_deadlines, live_payload
from squadopt.live.recommendation import InSeasonProjection, read_projection_handoff
from squadopt.prediction.component_dataset import COMPONENT_HISTORY_WINDOW

CONTRACT_VERSION: Final = "decided_appearance_v1"
FITTED_COLUMNS: Final = ("season", "gameweek", "player_id", "fitted_appearance_probability")
DEFAULT_OUTPUT: Final = Path("artifacts") / "double_reduction" / "decided_appearance.csv"
STATED: Final = "stated_in_handoff"
REBUILT: Final = "rebuilt_and_fingerprint_verified"

#: Rebuild one handoff's components from its capture: the component table and its diagnostics.
Rebuild = Callable[[InSeasonProjection], tuple[pd.DataFrame, Mapping[str, object]]]


class DecidedAppearanceError(RuntimeError):
    """The week's own appearance probabilities cannot be established; nothing is guessed."""


@dataclass(frozen=True, slots=True)
class SettledWeek:
    season: str
    gameweek: int
    decision_capture: str


def settled_weeks(outcomes_dir: Path) -> list[SettledWeek]:
    """The settled weeks on disk, from the manifests the settled outcome export writes."""

    weeks: dict[tuple[str, int], SettledWeek] = {}
    for path in sorted(Path(outcomes_dir).glob("settled_outcomes_*.manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        try:
            week = SettledWeek(
                season=str(manifest["season"]),
                gameweek=int(manifest["gameweek"]),
                decision_capture=str(manifest["pre_deadline_snapshot_id"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DecidedAppearanceError(
                f"{path.name} is not a settled outcome manifest."
            ) from error
        known = weeks.setdefault((week.season, week.gameweek), week)
        if known.decision_capture != week.decision_capture:
            raise DecidedAppearanceError(
                f"Two settled tables for {week.season} GW{week.gameweek:02d} name different "
                f"decision captures ({known.decision_capture}, {week.decision_capture})."
            )
    return sorted(weeks.values(), key=lambda week: (week.season, week.gameweek))


def decided_handoff(data_root: Path, week: SettledWeek) -> InSeasonProjection:
    """The handoff kept for the week's decision capture that the ledger decided from."""

    label = f"{week.season} GW{week.gameweek:02d}"
    decision_path = data_root / "ledger" / week.season / f"gw{week.gameweek:02d}" / "decision.json"
    if not decision_path.is_file():
        raise DecidedAppearanceError(f"No ledger decision for {label} at {decision_path}.")
    document = json.loads(decision_path.read_text(encoding="utf-8"))
    metadata = document.get("metadata") if isinstance(document, dict) else None
    fingerprint = (
        metadata.get("projection_handoff_fingerprint") if isinstance(metadata, dict) else None
    )
    if not isinstance(fingerprint, str) or not fingerprint:
        raise DecidedAppearanceError(f"The ledger decision for {label} names no handoff.")
    directory = data_root / "handoffs" / "by-capture" / week.decision_capture
    kept = (
        [read_projection_handoff(path) for path in sorted(directory.glob("*.json"))]
        if directory.is_dir()
        else []
    )
    matches = [handoff for handoff in kept if handoff.fingerprint == fingerprint]
    if not matches:
        raise DecidedAppearanceError(
            f"The ledger decided {label} from handoff {fingerprint}, and none of the "
            f"{len(kept)} handoff(s) kept for {week.decision_capture} has that fingerprint."
        )
    handoff = matches[0]
    if (handoff.season, handoff.gameweek) != (week.season, week.gameweek):
        raise DecidedAppearanceError(
            f"Handoff {fingerprint} projects {handoff.season} GW{handoff.gameweek:02d}, "
            f"not {label}."
        )
    return handoff


def fitted_appearance(
    handoff: InSeasonProjection, rebuild: Rebuild
) -> tuple[dict[int, float], str]:
    """The handoff's own appearance probabilities, and how they were obtained."""

    if handoff.appearance_probability is not None:
        return {int(k): float(v) for k, v in handoff.appearance_probability.items()}, STATED
    expected_fingerprint = handoff.diagnostics.get("component_fingerprint")
    if not expected_fingerprint:
        raise DecidedAppearanceError(
            f"Handoff {handoff.fingerprint} states no appearance probability and no component "
            "fingerprint, so no rebuild of it can be verified."
        )
    table, diagnostics = rebuild(handoff)
    if diagnostics.get("component_fingerprint") != expected_fingerprint:
        raise DecidedAppearanceError(
            f"The rebuilt components of handoff {handoff.fingerprint} have fingerprint "
            f"{diagnostics.get('component_fingerprint')}, not the handoff's "
            f"{expected_fingerprint}: the code no longer reproduces that week's projection."
        )
    rebuilt = table.set_index("player_id")["expected_points"].astype("float64").sort_index()
    original = (
        pd.DataFrame(
            {
                "player_id": list(handoff.expected_points),
                "expected_points": list(handoff.expected_points.values()),
            }
        )
        .set_index("player_id")["expected_points"]
        .astype("float64")
        .sort_index()
    )
    if not rebuilt.equals(original):
        raise DecidedAppearanceError(
            f"The rebuilt expected points of handoff {handoff.fingerprint} differ from the "
            "handoff's own."
        )
    stated = table.loc[table["appearance_probability"].notna()]
    return (
        {
            int(player): float(chance)
            for player, chance in zip(
                stated["player_id"].astype("int64"),
                stated["appearance_probability"].astype("float64"),
                strict=True,
            )
        },
        REBUILT,
    )


def rebuild_from_capture(snapshot_root: Path, archive_root: Path) -> Rebuild:
    """The producer's component table for a handoff, from the capture it was projected from."""

    def rebuild(handoff: InSeasonProjection) -> tuple[pd.DataFrame, Mapping[str, object]]:
        capture = read_snapshot(snapshot_root, handoff.source_snapshot_id)
        bootstrap = capture.payloads[BOOTSTRAP_PAYLOAD]
        deadlines = [
            row for row in gameweek_deadlines(bootstrap) if row.gameweek == handoff.gameweek
        ]
        if not deadlines:
            raise DecidedAppearanceError(
                f"{handoff.source_snapshot_id} publishes no GW{handoff.gameweek:02d} deadline."
            )
        weeks = range(max(1, handoff.gameweek - COMPONENT_HISTORY_WINDOW), handoff.gameweek)
        missing = [week for week in weeks if live_payload(week) not in capture.payloads]
        if missing or FIXTURES_PAYLOAD not in capture.payloads:
            raise DecidedAppearanceError(
                f"{handoff.source_snapshot_id} lacks what the producer read "
                f"(settled weeks {missing}, fixtures present: "
                f"{FIXTURES_PAYLOAD in capture.payloads})."
            )
        # The handoff's own points stand in for the producer's fallback. Only direct-control
        # rows read it, and their handoff value is that fallback, so the rebuild must return
        # every expected point unchanged or be refused.
        fallback = pd.DataFrame(
            {
                "player_id": list(handoff.expected_points),
                "expected_points": list(handoff.expected_points.values()),
            }
        )
        return _component_table(
            archive_root,
            bootstrap=bootstrap,
            fixtures=capture.payloads[FIXTURES_PAYLOAD],
            event_payloads={week: capture.payloads[live_payload(week)] for week in weeks},
            season=handoff.season,
            target=handoff.gameweek,
            source_snapshot_id=handoff.source_snapshot_id,
            captured_at_utc=capture.metadata.captured_at_utc,
            deadline_utc=deadlines[0].deadline_utc,
            fallback=fallback,
            include_components=True,
        )

    return rebuild


def collect(
    data_root: Path, weeks: Sequence[SettledWeek], rebuild: Rebuild
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Every settled week's rows, and what each week's rows were read from."""

    frames: list[pd.DataFrame] = []
    described: list[dict[str, object]] = []
    for week in weeks:
        handoff = decided_handoff(data_root, week)
        chances, source = fitted_appearance(handoff, rebuild)
        frame = pd.DataFrame(
            {
                "season": week.season,
                "gameweek": week.gameweek,
                "player_id": list(chances),
                "fitted_appearance_probability": list(chances.values()),
            },
            columns=list(FITTED_COLUMNS),
        ).sort_values("player_id", kind="stable")
        frames.append(frame)
        described.append(
            {
                "season": week.season,
                "gameweek": week.gameweek,
                "decision_capture": week.decision_capture,
                "handoff_fingerprint": handoff.fingerprint,
                "model_version": handoff.model_version,
                "component_fingerprint": handoff.diagnostics.get("component_fingerprint"),
                "source": source,
                "players_in_handoff": len(handoff.expected_points),
                "rows": len(frame),
            }
        )
    table = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=list(FITTED_COLUMNS))
    )
    return table, described


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=None,
        help="the historical archive the producer trains on (default: <data-root>/raw/vaastav-fpl)",
    )
    parser.add_argument("--outcomes-dir", type=Path, default=REPOSITORY_ROOT / SETTLED_OUTCOMES_DIR)
    parser.add_argument("--output", type=Path, default=REPOSITORY_ROOT / DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    data_root = arguments.data_root
    archive_root = arguments.archive_root or data_root / "raw" / "vaastav-fpl"
    weeks = settled_weeks(arguments.outcomes_dir)
    if not weeks:
        print(f"No settled outcome manifest under {arguments.outcomes_dir}; nothing to read.")
        return 1
    try:
        table, described = collect(
            data_root, weeks, rebuild_from_capture(data_root / "snapshots", archive_root)
        )
    except (DecidedAppearanceError, DataSourceError) as error:
        print(f"Refused: {error}")
        return 1
    for week in described:
        print(
            f"  gw{int(str(week['gameweek'])):02d}  {week['source']}  handoff "
            f"{str(week['handoff_fingerprint'])[:12]}  rows {week['rows']} of "
            f"{week['players_in_handoff']}"
        )
    if arguments.dry_run:
        print("Dry run: nothing written.")
        return 0
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False, lineterminator="\n")
    write_json(
        output.with_suffix(".manifest.json"),
        {
            "contract_version": CONTRACT_VERSION,
            "table_file": output.name,
            "table_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "rows": len(table),
            "weeks": described,
            "provenance": repository_provenance(),
        },
    )
    print(f"Wrote {output} and its manifest")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main
    sys.exit(main())
