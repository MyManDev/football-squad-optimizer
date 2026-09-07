"""Every atomic writer's scratch name fits where the file it publishes fits.

Windows resolves paths against a 260 character limit. A scratch name derived from the
target -- ``.{name}.tmp-{pid}-{token}`` -- spends about twenty characters more than the
name it will become, so a writer could fail in a directory where its own output fits.
The CRT reports the overflow as ``FileNotFoundError: [Errno 2]``, which reads like a
vanishing temporary directory rather than a name that is too long, so the defect was
diagnosed as a race twice before it was measured.

``src/squadopt/platform/artifacts.py`` fixed this first (#403): a fixed-width
``.{token}.tmp`` created exclusively, retried a bounded number of times. This module
holds the remaining writers to the same property, by name rather than by residue -- the
"no leftover temporary" assertions scattered through the suite pass just as happily
against a name that overflows, so they cannot be the thing that keeps this fixed.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from scripts import export_player_evidence, run_shadow_calibration

from squadopt.application import site
from squadopt.experiments import shadow_report
from squadopt.live import ledger
from squadopt.platform import artifacts, manifest

#: ``.`` + eight hex characters + ``.tmp``.
_SCRATCH_NAME_LENGTH = 13

#: A name of the shape these writers actually publish, long enough that a fixed-width
#: scratch beside it is shorter than it is. The point is not that 13 characters beats
#: every conceivable name -- it does not beat ``a.json`` -- but that the width does not
#: track the target, so a deep directory that holds the target holds the scratch too.
_TYPICAL_TARGET = "recommendation.json"

Reserve = Callable[[Path], Path]

_WRITERS: tuple[tuple[str, Reserve], ...] = (
    ("platform.artifacts", lambda path: artifacts._write_scratch(path, b"{}\n")),
    ("platform.manifest", lambda path: manifest._write_scratch(path, b"{}\n")),
    ("application.site", lambda path: site._write_scratch(path, b"{}\n")),
    ("live.ledger", lambda path: ledger._write_scratch(path, b"{}\n")),
    ("experiments.shadow_report", lambda path: shadow_report._write_scratch(path, b"{}\n")),
    (
        "scripts.run_shadow_calibration",
        lambda path: run_shadow_calibration._write_scratch(path, b"{}\n"),
    ),
    ("scripts.export_player_evidence", export_player_evidence._temporary),
)


@pytest.mark.parametrize(("writer", "reserve"), _WRITERS, ids=[name for name, _ in _WRITERS])
def test_a_scratch_name_never_outgrows_the_file_it_publishes(
    writer: str, reserve: Reserve, tmp_path: Path
) -> None:
    """The scratch name is fixed width, not derived from the target it will become.

    A 200-character target and a typical one must reserve names of the same length. The
    old naming failed this: it grew with the target and overshot it by the ``.tmp-`` and
    the process id, which is exactly the overflow the 260 character limit reports as a
    missing file.
    """

    long_target = tmp_path / ("published_" + "x" * 200 + ".json")
    typical_target = tmp_path / _TYPICAL_TARGET

    long_scratch = reserve(long_target)
    typical_scratch = reserve(typical_target)

    for target, scratch in ((long_target, long_scratch), (typical_target, typical_scratch)):
        assert scratch.parent == target.parent, f"{writer} put its scratch somewhere else"
        assert len(scratch.name) == _SCRATCH_NAME_LENGTH
        assert scratch.name.startswith(".") and scratch.name.endswith(".tmp")
        assert scratch.is_file(), f"{writer} did not reserve the name it returned"

    assert len(typical_scratch.name) <= len(typical_target.name)


@pytest.mark.parametrize(("writer", "reserve"), _WRITERS, ids=[name for name, _ in _WRITERS])
def test_an_outstanding_scratch_name_is_never_handed_out_twice(
    writer: str, reserve: Reserve, tmp_path: Path
) -> None:
    """Exclusive creation, not the process id, is what makes the reservation unique.

    Dropping the pid from the name is only safe because the file is created with
    ``O_EXCL`` and a collision retries, so two live reservations beside the same target
    cannot name the same file.
    """

    target = tmp_path / "report.json"
    first = reserve(target)
    second = reserve(target)

    assert first != second
    assert first.is_file() and second.is_file()
