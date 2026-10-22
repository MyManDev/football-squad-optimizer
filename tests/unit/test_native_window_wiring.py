"""Every server path that renders a three-week window hands its primary search to the
native executor: the serial league mapper, the pool worker and the API advice worker.

The executor is replaced by a recording fake that refuses, so each search falls back to
CP-SAT and the render completes as it did before the switch. All inputs are synthetic.
"""

import functools
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_advice_worker as worker_fixture
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit.test_live_football_model import _forecast
from tests.unit.test_publication_services import publication_world

import squadopt.platform.advice_worker as advice_worker
import squadopt.platform.publication_workers as publication_workers
from squadopt.application.league_views import MemberRender, MemberRenderTask, render_member
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.planning.native_highs import CP_SAT_BACKEND, NativeWindowOutcome
from squadopt.platform.advice_switches import AdviceSwitchInputs

REFUSAL = "recorded by the wiring test"


class RecordingExecutor:
    """Stands in for ``execute_native_window``: notes each call, then refuses it."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, packet: Any, seconds: float) -> Any:
        assert {"cost", "bounds", "rows", "seed"} <= set(packet)
        self.calls.append(seconds)
        raise RuntimeError(REFUSAL)


@pytest.fixture(name="recorder")
def _recorder(monkeypatch: pytest.MonkeyPatch) -> RecordingExecutor:
    recorder = RecordingExecutor()
    # Each composition root imports the port by name, so each binding is replaced.
    monkeypatch.setattr(publication_workers, "execute_native_window", recorder)
    monkeypatch.setattr(advice_worker, "execute_native_window", recorder)
    return recorder


def _three_week_task(request: Any) -> MemberRenderTask:
    return MemberRenderTask(
        entry_id=worker_fixture.ENTRY_ID,
        label="Synthetic member",
        season=str(request.season),
        gameweek=int(request.gameweek),
        league_id=int(request.league_id),
        rival_ids=(),
        default_rival_id=None,
        rival_strategies=(),
        windows=(3,),
        chips=False,
    )


def _worker_context(
    request: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The pool worker's own context for this capture, with a horizon that covers a window.

    The publication fixture's calendar lacks fields the capture's horizon reads, so its
    windows are refused before any search. A synthetic football forecast for the same
    capture covers gameweeks 2 to 6 and stands in as the horizon builder.
    """

    monkeypatch.setattr(publication_workers, "_WORKER_CONTEXT", {})
    publication_workers._worker_init(
        str(request.snapshot_root),
        request.snapshot_id,
        str(request.season),
        str(request.handoff_path),
        str(request.archive_root),
        request.gameweek,
        request=request,
    )
    context = publication_workers._WORKER_CONTEXT
    path = tmp_path / "football-forecast.json"
    path.write_text(json.dumps(_forecast(context["inputs"])), encoding="utf-8")
    context["horizon_builder"] = read_football_forecast(path, context["inputs"]).build_horizon
    return context


def _assert_three_week_window_reached_the_executor(
    render: MemberRender, recorder: RecordingExecutor
) -> None:
    assert recorder.calls, "the three-week render never reached the native executor"
    assert all(seconds > 0 for seconds in recorder.calls)
    assert [weeks for weeks, _ in render.window_payloads] == [3]
    assert render.native_windows
    assert set(render.native_windows) == {NativeWindowOutcome(3, CP_SAT_BACKEND, None, REFUSAL)}
    assert len(render.native_windows) == len(recorder.calls)


def test_the_serial_league_mapper_binds_the_native_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorder: RecordingExecutor
) -> None:
    request = publication_world(tmp_path)
    context = dict(_worker_context(request, tmp_path, monkeypatch))
    task = _three_week_task(request)
    with publication_workers.league_mapper(request, workers=1) as mapper:
        renders = list(mapper(functools.partial(render_member, **context), [task]))
    _assert_three_week_window_reached_the_executor(renders[0], recorder)
    # The binding ends with the mapper: the same render outside it never starts a child.
    calls = len(recorder.calls)
    outside = render_member(task, **context)
    assert len(recorder.calls) == calls and outside.native_windows == ()
    assert [weeks for weeks, _ in outside.window_payloads] == [3]


def test_the_pool_worker_binds_the_native_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorder: RecordingExecutor
) -> None:
    request = publication_world(tmp_path)
    _worker_context(request, tmp_path, monkeypatch)
    # ``_render_in_worker`` is what each spawned pool process runs; it is called here in
    # this process so the fake replaces the executor it binds.
    render = publication_workers._render_in_worker(_three_week_task(request))
    _assert_three_week_window_reached_the_executor(render, recorder)


def test_the_api_advice_worker_binds_the_native_executor_and_logs_its_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorder: RecordingExecutor
) -> None:
    artifacts = tmp_path / "artifacts"
    world = worker_fixture._deployment(tmp_path, monkeypatch, artifact_root=artifacts)
    backend = world["backend"]
    identity = backend.contexts.identity()
    # The football forecast covers gameweeks 2 to 6, so this capture can answer a window.
    path = football_artifact_path(artifacts, world["snapshot_id"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_forecast(identity.inputs)))
    football = read_football_forecast(path, identity.inputs)
    capture = replace(
        backend.contexts.capture(identity.context),
        switches=AdviceSwitchInputs(football=football),
    )
    monkeypatch.setattr(
        backend.contexts,
        "capture",
        lambda context: capture if context == identity.context else None,
    )
    client = TestClient(app_for_capture(backend, worker_fixture.world_module.GW2_CAPTURED_AT))
    accepted = client.post(
        f"/api/v1/leagues/{worker_fixture.LEAGUE_ID}/entries/{worker_fixture.ENTRY_ID}/advice",
        json={"strategy": "saf-puan", "window": 3, "model": "football"},
    )
    assert accepted.status_code == 202, accepted.text
    fields: dict[str, object] = {}
    compute = advice_worker.build_advice_compute(
        backend.contexts, backend.job_specs, job_log_fields=fields
    )
    document = json.loads(compute(backend.queue.jobs()[0]))
    assert document["payload"]["window"] == 3
    assert recorder.calls, "the three-week answer never reached the native executor"
    # The job's terminal log event carries which backend answered and why; the answer
    # itself does not.
    assert fields["window_solvers"] == [
        {
            "weeks": 3,
            "solves": len(recorder.calls),
            "native": 0,
            "fallback": len(recorder.calls),
            "backends": [CP_SAT_BACKEND],
            "native_versions": [],
            "fallback_reasons": {REFUSAL: len(recorder.calls)},
        }
    ]
    assert "window_solvers" not in document["payload"]
    assert REFUSAL not in json.dumps(document)
