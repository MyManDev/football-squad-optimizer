"""Where a reused answer says it came from, through a chain of runs.

A run given an earlier capture reuses that capture's answers when nothing about the question
changed. The capture it writes records, for each reused answer, the capture the answer was
coded in. That has to stay the coding capture however many runs reuse it: an origin that
moved one capture along with every run would point at a capture that never asked the model.

Offline throughout: the opener, the clock and the provider are injected.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from tests.unit.test_club_news_acquire import _Provider
from tests.unit.test_club_news_observation_clock import (
    STARTED,
    _Clock,
    _command,
    _environment,
    _opener,
    _roster_snapshot,
    _text,
)

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument, RosterPlayer
from squadopt.data.sources.club_news_capture import read_captured_responses
from squadopt.platform.club_news_acquire import main
from squadopt.platform.club_news_provider import register_provider


def test_a_reused_answer_names_the_capture_it_was_coded_in_through_every_later_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class _Counting(_Provider):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            calls.append(documents[0].club)
            # Reuse requires the held answer to name the model the run asked for.
            return replace(super().code(documents, roster), model_identifier="fake-model-1")

    name = "fake-reuse-origin"
    register_provider(name, lambda config: _Counting())
    snapshots = tmp_path / "snapshots"
    roster_id = _roster_snapshot(snapshots)
    published = _text(STARTED - timedelta(hours=3))

    def _run(clock: _Clock, *extra: str) -> tuple[str, str]:
        # Capture completion is its own clock; keep it on this synthetic week's timeline.
        monkeypatch.setattr(
            "squadopt.platform.club_news_acquire._utc_now",
            lambda: _text(clock.readings[-1] + timedelta(seconds=30)),
        )
        code = main(
            _command(tmp_path, roster_id, *extra),
            environ=_environment(name),
            opener=_opener(published),
            now=clock,
            sleeper=lambda _: None,
        )
        printed = capsys.readouterr().out
        assert code == 0, printed
        capture = next(
            line.split()[-1] for line in printed.splitlines() if line.startswith("Capture")
        )
        return capture, printed

    first, _ = _run(_Clock(STARTED))
    asked = list(calls)
    assert asked == ["Arsenal", "Man Utd"]

    second, second_printed = _run(
        _Clock(STARTED + timedelta(minutes=30), timedelta(seconds=1)),
        "--previous-news-capture",
        str(snapshots / first),
    )
    third, third_printed = _run(
        _Clock(STARTED + timedelta(minutes=60), timedelta(seconds=1)),
        "--previous-news-capture",
        str(snapshots / second),
    )

    # Nothing was asked again in either later run.
    assert calls == asked
    assert len({first, second, third}) == 3
    for printed in (second_printed, third_printed):
        assert "Call budget   3; 0 attempted; no automatic provider retry" in printed
        assert "Answer reused from an earlier capture: 2 [Arsenal, Man Utd]" in printed
    coded_first = read_captured_responses(read_snapshot(snapshots, first))
    assert [entry.reused_from_snapshot for entry in coded_first] == [None, None]
    for capture in (second, third):
        entries = read_captured_responses(read_snapshot(snapshots, capture))
        assert [entry.club for entry in entries] == ["Arsenal", "Man Utd"]
        # The capture the answers were coded in, not the capture handed to this run.
        assert [entry.reused_from_snapshot for entry in entries] == [first, first]
        assert [entry.response for entry in entries] == [entry.response for entry in coded_first]
