"""Produce the in-season projection handoff a mid-season decision needs.

    python -m scripts.build_projection_handoff                    # latest capture
    python -m scripts.build_projection_handoff --snapshot-id ...  # a named capture
    python -m scripts.build_projection_handoff --dry-run          # report, write nothing

The live path projects the opening gameweek itself and refuses every later one without a
handoff from the model that produced it. This is that model's entry point: it reads one
capture, projects the deadline that capture is open for, and writes the file the tick waits
for.

Three contracts are worth stating because two of them fail late rather than loudly.

The handoff must be produced from **the capture the decision will run on**: the live path
compares ``source_snapshot_id`` and refuses a projection made from a different capture,
because a projection of another roster is not a projection of this one. So on a deadline day
the order is capture, then this script, then decide -- not a handoff prepared earlier in the
week.

The in-season history comes from that same capture, which is only safe because the counters
in it have been shown to describe the current season once the season's first match has
kicked off (``docs/capture_season_phase.md``). ``in_season_totals`` refuses a capture taken
before that, so a handoff cannot quietly be built from last season's totals.

And the model version must be a promoted in-season control. Pinning it is a reviewed
decision made in ``live``; this script only reports the identity it is claiming, so a
refusal downstream is legible rather than mysterious.

Nothing is fetched. The capture is already on disk.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    gameweek_deadlines,
    in_season_totals,
    next_open_deadline,
    player_snapshot,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.features.cross_season import carry_over_as_of
from squadopt.live import (
    CONTROL_MODEL_NAME,
    IN_SEASON_CONTROL_MODEL_VERSIONS,
    InSeasonProjection,
    handoff_path_for,
    infer_season,
    read_projection_handoff,
    write_projection_handoff,
)
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
    InSeasonBlendConfig,
    blend_in_season_projection,
)
from squadopt.prediction.opening import build_opening_projection_from_snapshot

DEFAULT_SNAPSHOT_ROOT: Final = Path("data/snapshots")
DEFAULT_HANDOFF_ROOT: Final = Path("data/handoffs")


def _latest_snapshot_id(snapshot_root: Path) -> str:
    """Return the most recent capture's identifier.

    Identifiers begin with the capture instant in a sortable spelling, so the newest is the
    last in lexical order.
    """

    directories = sorted(path.name for path in snapshot_root.iterdir() if path.is_dir())
    if not directories:
        raise SystemExit(f"No captures under {snapshot_root}.")
    return directories[-1]


def build(
    snapshot_root: Path,
    archive_root: Path,
    handoff_root: Path,
    *,
    snapshot_id: str | None = None,
    gameweek: int | None = None,
    config: InSeasonBlendConfig | None = None,
    dry_run: bool = False,
) -> tuple[InSeasonProjection, Path | None, dict[str, object]]:
    """Project one capture's open deadline and write the handoff for it."""

    identifier = _latest_snapshot_id(snapshot_root) if snapshot_id is None else snapshot_id
    snapshot = read_snapshot(snapshot_root, identifier)
    bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
    fixtures = snapshot.payloads[FIXTURES_PAYLOAD]
    captured_at = snapshot.metadata.captured_at_utc
    season = infer_season(snapshot)

    # The deadline this capture is open for, read from the capture rather than supplied,
    # for the same reason the season is: a hand-passed gameweek can be the wrong one, and
    # the live path would then refuse the handoff after the work was done.
    target = (
        next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=captured_at).gameweek
        if gameweek is None
        else gameweek
    )
    # Every gameweek before the target has been played, so that is the in-season sample.
    played = target - 1

    roster = player_snapshot(bootstrap)
    history = in_season_totals(bootstrap, fixtures, captured_at_utc=captured_at)
    panel = build_panel(archive_root)
    carried = carry_over_as_of(panel, target_season=season)
    # The opening control's own output, used only where a player has neither an in-season
    # record nor a carried one, so both paths price such a player identically by
    # construction rather than by two copies of one rule agreeing.
    fallback = build_opening_projection_from_snapshot(panel, roster, season=season)

    blend = blend_in_season_projection(
        roster, carried, history, fallback, gameweeks_played=played, config=config
    )

    expected = {
        int(code): float(points)
        for code, points in zip(
            blend.table["player_id"].astype("int64").tolist(),
            blend.table["expected_points"].astype("float64").tolist(),
            strict=True,
        )
    }
    projection = InSeasonProjection(
        season=season,
        gameweek=target,
        source_snapshot_id=identifier,
        model_name=CONTROL_MODEL_NAME,
        model_version=IN_SEASON_MODEL_VERSION,
        feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
        expected_points=expected,
        diagnostics=blend.diagnostics,
    )

    path = handoff_path_for(handoff_root, season, target)
    written: Path | None = None
    if not dry_run:
        written = write_projection_handoff(path, projection)
        # Read it back through the consumer's own reader. The fingerprint check makes this
        # a measurement of producer-consumer agreement rather than a claim about it.
        reread = read_projection_handoff(written)
        if reread.fingerprint != projection.fingerprint:
            raise SystemExit(f"The handoff written to {written} does not read back identically.")

    report: dict[str, object] = {
        "snapshot_id": identifier,
        "captured_at_utc": captured_at,
        "season": season,
        "gameweek": target,
        "gameweeks_played": played,
        "handoff_path": str(path),
        "fingerprint": projection.fingerprint,
        "model_name": CONTROL_MODEL_NAME,
        "model_version": IN_SEASON_MODEL_VERSION,
        "version_is_promoted": IN_SEASON_MODEL_VERSION in IN_SEASON_CONTROL_MODEL_VERSIONS,
        **blend.diagnostics,
    }
    return projection, written, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument(
        "--snapshot-id", default=None, help="capture to project (default: the most recent)"
    )
    parser.add_argument(
        "--gameweek",
        type=int,
        default=None,
        help="override the deadline read from the capture; normally unnecessary",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args()

    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    _, written, report = build(
        arguments.snapshot_root,
        arguments.archive_root,
        arguments.handoff_root,
        snapshot_id=arguments.snapshot_id,
        gameweek=arguments.gameweek,
        dry_run=arguments.dry_run,
    )

    print(f"Capture   {report['snapshot_id']}  ({report['captured_at_utc']})")
    print(f"Target    {report['season']} gameweek {report['gameweek']}")
    print(f"Played    {report['gameweeks_played']} gameweek(s) of in-season history")
    print()
    print("Projection routes")
    for key in (
        "players",
        "players_with_in_season_minutes",
        "players_blended_two_stage",
        "players_shrunk_against_the_price_prior",
        "players_from_carry_over_only",
        "players_priced_from_the_prior",
    ):
        print(f"  {key:42} {report[key]}")
    print(f"  {'in_season_weight':42} {report['in_season_weight']}")
    print(f"  {'carry_over_weight':42} {report['carry_over_weight']}")
    print()
    print(f"Identity  {report['model_name']} / {report['model_version']}")
    if not report["version_is_promoted"]:
        print(
            "  This version is NOT in IN_SEASON_CONTROL_MODEL_VERSIONS, so a decision "
            "made from this handoff will be refused at verification. Pinning it is the "
            "promotion decision and belongs in a reviewed change to 'live'."
        )
    print(f"Fingerprint {report['fingerprint']}")
    if written is None:
        print("\nDry run: nothing written.")
    else:
        print(f"\nWrote {written} and read it back identically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
