"""A re-render asks for no capture, because what a command asks for says what it does.

`--rewrite-markdown` reads the committed record and rewrites its markdown. It returns before
any capture is opened. It nonetheless demanded `--data-root` and `--snapshot-id`, so running it
meant naming a runtime data directory and a capture id that were read by nothing.

That is not only inconvenience. A command that asks for a capture is understood to open one,
and a reader deciding whether a presentation fix is safe to run on a merged record has only the
command's own signature to go on. Asking for an unread capture says a re-render might
re-measure. It cannot, and the record it would overwrite is the run that happened.
"""

from __future__ import annotations

import pytest
from scripts.measure_member_plan_determinism import _arguments


def test_a_rewrite_needs_neither_a_data_root_nor_a_capture() -> None:
    """The point of the change, asserted on the parser rather than described in help text."""

    arguments = _arguments(["--rewrite-markdown"])

    assert arguments.rewrite_markdown is True
    assert arguments.data_root is None
    assert arguments.snapshot_id is None


def test_a_measuring_run_still_demands_both(capsys: pytest.CaptureFixture[str]) -> None:
    """Relaxing the parser must not relax the run that actually solves.

    Named individually rather than as one message, so a caller that supplied one of the two
    is told which is missing instead of being made to compare the invocation against the help.
    """

    with pytest.raises(SystemExit) as error:
        _arguments([])

    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "--data-root" in message
    assert "--snapshot-id" in message


def test_a_measuring_run_missing_only_the_capture_is_told_only_that() -> None:
    with pytest.raises(SystemExit):
        _arguments(["--data-root", "unused"])


def test_a_rewrite_may_still_be_given_them_without_being_refused() -> None:
    """They are not forbidden, only unasked for.

    Anyone with the full invocation in shell history adds `--rewrite-markdown` to it, and a
    refusal there would teach nothing and cost a working habit.
    """

    arguments = _arguments(
        ["--rewrite-markdown", "--data-root", "unused", "--snapshot-id", "also-unused"]
    )

    assert arguments.rewrite_markdown is True
