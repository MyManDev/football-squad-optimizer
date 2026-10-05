"""The configuration guide's worked example is the command's own output.

The guide walks through one synthetic run line by line. Those lines are read out of the guide
and looked for in what the command prints for that run, so the example cannot drift from the
report it explains.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from tests.unit.test_club_news_acquire import _Provider
from tests.unit.test_club_news_acquisition_report import _plain_opener
from tests.unit.test_club_news_observation_clock import (
    _Clock,
    _command,
    _environment,
    _roster_snapshot,
)

from squadopt.platform.club_news_acquire import main
from squadopt.platform.club_news_provider import register_provider

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "club_news_configuration.md"


def _example_lines() -> list[str]:
    text = GUIDE.read_text(encoding="utf-8")
    begin, end = "<!-- worked-example: begin -->", "<!-- worked-example: end -->"
    assert text.count(begin) == text.count(end) == 1
    block = text.split(begin, 1)[1].split(end, 1)[0]
    return [line for line in block.splitlines() if line.strip() and not line.startswith("```")]


def test_the_worked_example_quotes_what_the_command_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = "fake-guide-example"
    register_provider(name, lambda config: _Provider())
    roster_id = _roster_snapshot(tmp_path / "snapshots")

    code = main(
        _command(tmp_path, roster_id, "--club", "Arsenal", "--dry-run", "--max-model-calls", "1"),
        environ=_environment(name),
        opener=_plain_opener(),
        now=_Clock(step=timedelta(seconds=20)),
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out.splitlines()
    assert code == 0
    quoted = _example_lines()
    assert len(quoted) >= 15
    missing = [line for line in quoted if line not in printed]
    assert missing == []
    # Quoted in the order the command prints them.
    positions = [printed.index(line) for line in quoted]
    assert positions == sorted(positions)


def test_the_guide_does_not_call_an_empty_answer_or_a_ready_key_news() -> None:
    """The four things the example keeps apart are each named in the guide."""

    text = GUIDE.read_text(encoding="utf-8")
    section = text.split("## One run, read line by line", 1)[1].split("\n## ", 1)[0]
    for phrase in (
        "The settings are ready.",
        "What was covered.",
        "The answer was empty.",
        "Nothing was applied",
    ):
        assert phrase in section
