"""Process scheduling for the installed member-publication service."""

import functools
import multiprocessing
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from squadopt.application.advice import member_horizon_builder
from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.league_publication import LeaguePublicationRequest
from squadopt.application.league_views import (
    MemberMapper,
    MemberRender,
    MemberRenderTask,
    render_member,
)
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    infer_season,
    project,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)

_WORKER_CONTEXT: dict[str, Any] = {}


def _worker_init(
    snapshot_root: str,
    snapshot_id: str,
    season: str,
    handoff: str | None,
    archive_root: str,
    gameweek: int | None = None,
) -> None:
    snapshot = read_snapshot(Path(snapshot_root), snapshot_id)
    season = season or infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season, gameweek=gameweek)
    panel = build_panel(Path(archive_root))
    in_season = read_projection_handoff(Path(handoff)) if handoff else None
    _WORKER_CONTEXT.update(
        provider=CapturePicksProvider(snapshot, snapshot_id),
        inputs=inputs,
        projection=project(inputs, panel, in_season=in_season),
        rules=read_season_rules(snapshot, season=season),
        # The multi-week horizon is built once per window in each worker and shared by
        # every member the worker renders; it is the same bytes in every process.
        horizon_builder=member_horizon_builder(
            snapshot, season=season, panel=panel, in_season=in_season
        ),
    )


def _render_in_worker(task: MemberRenderTask) -> MemberRender:
    return render_member(task, **_WORKER_CONTEXT)


def pool_mapper(
    executor: Executor,
) -> Callable[
    [Callable[[MemberRenderTask], MemberRender], Iterable[MemberRenderTask]],
    Iterable[MemberRender],
]:
    """A ``build_league_views`` mapper over a pool whose workers hold their own context.

    The function the batch hands over is ``render_member`` bound to the batch's own
    context; the pool cannot carry that context, so it runs the same ``render_member``
    against the worker's — and refuses anything else, so a different function can never
    be silently replaced by this one.
    """

    def mapper(
        function: Callable[[MemberRenderTask], MemberRender],
        tasks: Iterable[MemberRenderTask],
    ) -> Iterable[MemberRender]:
        if not (isinstance(function, functools.partial) and function.func is render_member):
            raise ValueError("The pool mapper runs render_member only.")
        return executor.map(_render_in_worker, list(tasks))

    return mapper


@contextmanager
def league_mapper(request: LeaguePublicationRequest, workers: int = 1) -> Iterator[MemberMapper]:
    """Yield the ordinary mapper or workers pinned to the same capture and handoff."""

    if workers < 1:
        raise ValueError("--workers must be at least 1")
    if workers == 1:
        yield map
        return
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_worker_init,
        initargs=(
            str(request.snapshot_root),
            request.snapshot_id,
            request.season or "",
            str(request.handoff_path) if request.handoff_path else None,
            str(request.archive_root),
            request.gameweek,
        ),
    ) as executor:
        yield pool_mapper(executor)
