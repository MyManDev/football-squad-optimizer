"""The backend's view of one capture: everything an advice computation needs.

The API and the worker both answer questions *about a capture*: which players exist,
what they cost, what the season's rules are, what each member holds. Building those four
collaborators together rather than per request is not an optimization — ``advise_entry``
refuses a rules object, a projection or a squad that came from a different capture than
its inputs, so they are either built from one capture or they cannot be built correctly
at all.

One translation lives here and it is load-bearing: the FPL entry endpoints name a player
by **element** id, which is a per-season number, while the projection, the prices and the
ledger name them by **code**, the identifier that survives a transfer window. Handing
element ids to a consumer that means codes does not fail loudly; it silently finds none
of the squad, which is exactly how this surfaced when the league site first rendered
(fifteen members, "no current price", zero rendered). ``scripts/build_league_site.py``
owned this class privately; application.capture_entries now owns the offline adapter,
and this module re-exports the same object for existing callers.

Serving advice needs a **projection handoff**. The opening gameweek's archive-panel route
exists in the decision path and is deliberately not offered here: a backend that answered
from an archive nobody fingerprinted would put an unidentifiable projection into the cache
key. No handoff for the capture means no context, and no context means the backend reports
itself unready rather than answering from whatever it can find.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from squadopt.application.advice import HorizonBuilder, member_horizon_builder
from squadopt.application.capture_entries import (
    CapturePicksProvider as CapturePicksProvider,
)
from squadopt.application.capture_entries import (
    capture_element_codes as capture_element_codes,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.live import (
    InSeasonProjection,
    Projection,
    RecommendationInputs,
    SeasonRules,
    infer_season,
    project,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)
from squadopt.live.tick import handoff_path_for
from squadopt.platform.advice_read import AdviceRequestContext

__all__ = [
    "AdviceCaptureContext",
    "CaptureIdentity",
    "CapturePicksProvider",
    "capture_element_codes",
    "handoff_fingerprint_for",
    "latest_snapshot_id",
    "load_capture_context",
    "load_capture_identity",
]


@dataclass(frozen=True, slots=True)
class CaptureIdentity:
    """What a capture is, without projecting it.

    The api process needs exactly this much: the identity every answer from this capture
    is filed under. Projecting is the expensive half and belongs to the worker, so the
    read side is not made to pay for it — but both sides derive the identity from this one
    function, so the key the api validates against cannot drift from the key the worker
    writes to.
    """

    context: AdviceRequestContext
    snapshot: CapturedSnapshot
    inputs: RecommendationInputs
    handoff: InSeasonProjection


@dataclass(frozen=True, slots=True)
class AdviceCaptureContext:
    """One capture, read once, as the collaborators ``advise_entry`` requires: the four
    every request needs, and the horizon builder a multi-week window needs."""

    context: AdviceRequestContext
    inputs: RecommendationInputs
    projection: Projection
    rules: SeasonRules
    provider: CapturePicksProvider
    horizon_builder: HorizonBuilder


def latest_snapshot_id(snapshot_root: Path | str) -> str | None:
    """The most recent live capture held, or ``None`` when the root holds none.

    ``None`` rather than a raise: an operator who has not yet published a capture is not
    a failure the API should log per request, it is a deployment that is not ready.

    Live captures only. Several collectors share this root and an identifier begins with
    its source, so a lexical listing orders by collector before capture time: a
    ``fpl-top100`` capture sorts after every ``fpl-live`` one however old it is. This is
    the whole of what the HTTP adapter serves advice from — there is no ``--snapshot-id``
    on a request to override it — and advice needs the game state only a live capture
    carries, so a root holding cohort captures alone reads as not ready rather than as
    ready with the wrong capture.
    """

    identifiers = list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    return identifiers[-1] if identifiers else None


def handoff_fingerprint_for(handoff_root: Path | str, season: str, gameweek: int) -> str | None:
    """The fingerprint of the handoff a capture would be projected with, or ``None``.

    Cheap on purpose: reading one small JSON is what lets a caller notice that ops
    republished a corrected handoff for a capture it has already read, without paying for
    the capture and its projection again. ``None`` when the file is absent or unreadable —
    the caller treats "cannot be confirmed" as "changed", which fails toward unready rather
    than toward serving a projection nobody can name.
    """

    path = handoff_path_for(Path(handoff_root), season, gameweek)
    try:
        return read_projection_handoff(path).fingerprint
    except Exception:
        return None


def load_capture_identity(
    *,
    snapshot_root: Path | str,
    snapshot_id: str,
    handoff_root: Path | str,
    advice_contract_version: str,
    repository_commit: str,
    configuration_fingerprint: str,
    season: str | None = None,
) -> CaptureIdentity:
    """Read one capture and its handoff far enough to name what it can answer.

    The handoff is addressed by the capture's *own* season and gameweek rather than
    configured as a path, so an operator who publishes a new capture and its handoff does
    not redeploy the backend to answer for the new week — and no client can name the file
    that gets read.
    """

    snapshot = read_snapshot(snapshot_root, snapshot_id)
    resolved_season = season or infer_season(snapshot)
    inputs = read_inputs(snapshot, season=resolved_season, gameweek=None)
    gameweek = int(inputs.deadline.gameweek)
    handoff_path = handoff_path_for(Path(handoff_root), resolved_season, gameweek)
    if not handoff_path.is_file():
        raise DataError(
            f"No projection handoff for {resolved_season} gameweek {gameweek} at "
            f"{handoff_path}. The backend answers from the same handoff the decision "
            "reads; without one it has no projection whose identity it can name."
        )
    handoff = read_projection_handoff(handoff_path)
    if handoff.source_snapshot_id != inputs.snapshot_id:
        raise DataError(
            f"The handoff at {handoff_path} was produced from capture "
            f"{handoff.source_snapshot_id!r}, not from {inputs.snapshot_id!r}."
        )
    context = AdviceRequestContext(
        advice_contract_version=advice_contract_version,
        capture_snapshot_id=inputs.snapshot_id,
        season=resolved_season,
        gameweek=gameweek,
        projection_handoff_fingerprint=handoff.fingerprint,
        repository_commit=repository_commit,
        configuration_fingerprint=configuration_fingerprint,
    )
    return CaptureIdentity(context=context, snapshot=snapshot, inputs=inputs, handoff=handoff)


def load_capture_context(identity: CaptureIdentity) -> AdviceCaptureContext:
    """Project the capture, completing the four collaborators ``advise_entry`` needs.

    Separated from the identity because this is the expensive half and only the worker
    runs it; separated *from* rather than duplicated so the api and the worker cannot
    disagree about which capture an answer belongs to.
    """

    inputs = identity.inputs
    # ``project`` refuses a handoff taken from another capture, so this is the second
    # place the capture and its projection are proved to be one question's two halves.
    projection = project(inputs, in_season=identity.handoff)
    rules = read_season_rules(identity.snapshot, season=inputs.season)
    return AdviceCaptureContext(
        context=identity.context,
        inputs=inputs,
        projection=projection,
        rules=rules,
        provider=CapturePicksProvider(identity.snapshot, inputs.snapshot_id),
        # The same capture and handoff, as the multi-week windows read them; built once
        # per window for the life of this context and shared by every request.
        horizon_builder=member_horizon_builder(
            identity.snapshot, season=inputs.season, in_season=identity.handoff
        ),
    )
