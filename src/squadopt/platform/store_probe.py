"""Prove the shared mount actually provides what the adapters were built on.

ADR 0006 does not ask for "a persistent disk". It names the primitives the queue and the
cache were reviewed against and requires them to be **proven before ingress**: exclusive
create (`O_EXCL`, the claim marker), hard-link create-once (`os.link` from a finished
temporary file — cache entries, job submission, the open-job index), and mtime as a
heartbeat. A mount that persists but silently does not honour those is not a smaller
version of the right store; it is a store on which two workers can run one job and two
writers can both win.

So this probe exercises the real syscalls on the real configured path rather than checking
that a directory exists. A failure keeps the service unready. There is deliberately no
local-disk fallback: falling back would trade a loud startup failure for a quiet
correctness one, which is ADR 0005's trigger firing silently.

**What this cannot prove, and does not claim.** Persistence across a replacement, and
visibility between two containers, are properties of the deployment, not of one process.
What the probe establishes is that *this* process's writes land and are immediately visible
in the shared directory through the same listing every other mounter reads — which is the
part a process can honestly test. Each process leaves a marker naming itself; whether the
other container sees it is answered by looking, from there, at the store. A green probe on
a laptop's local disk is evidence about that laptop and nothing else.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = ["StoreProbeResult", "probe_store"]

_PROBE_DIRECTORY = "probe"


@dataclass(frozen=True, slots=True)
class StoreProbeResult:
    """Which primitives the mount actually provided, and why any of them did not."""

    ok: bool
    checks: Mapping[str, bool]
    detail: Mapping[str, str]

    def failures(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, passed in self.checks.items() if not passed))


def probe_store(root: Path | str, *, process_id: str | None = None) -> StoreProbeResult:
    """Exercise the store's primitives once and report what it did, never raising.

    Raising would turn a mount problem into a crash loop that hides the diagnosis; the
    caller wants an unready service *and* the reason, which is what this returns.
    """

    identity = process_id or f"{os.getpid()}-{time.time_ns():x}"
    directory = Path(root) / _PROBE_DIRECTORY
    checks: dict[str, bool] = {}
    detail: dict[str, str] = {}
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return StoreProbeResult(
            ok=False,
            checks={
                "writable_root": False,
                "exclusive_create": False,
                "hard_link_no_overwrite": False,
                "heartbeat_mtime": False,
                "shared_listing": False,
            },
            detail={"writable_root": str(error)},
        )
    checks["writable_root"] = True

    marker = directory / f"{identity}.marker"
    _check(checks, detail, "exclusive_create", lambda: _exclusive_create(marker))
    _check(
        checks,
        detail,
        "hard_link_no_overwrite",
        lambda: _hard_link_no_overwrite(directory, identity),
    )
    _check(checks, detail, "heartbeat_mtime", lambda: _heartbeat_mtime(marker))
    _check(checks, detail, "shared_listing", lambda: _shared_listing(directory, marker))
    return StoreProbeResult(ok=all(checks.values()), checks=checks, detail=detail)


def _check(
    checks: dict[str, bool],
    detail: dict[str, str],
    name: str,
    run: Callable[[], None],
) -> None:
    try:
        run()
    except Exception as error:  # a failed primitive is a report, never a crash
        checks[name] = False
        detail[name] = f"{type(error).__name__}: {error}"
    else:
        checks[name] = True


def _exclusive_create(marker: Path) -> None:
    """``O_EXCL`` must succeed exactly once: it is what makes a claim exclusive."""

    marker.unlink(missing_ok=True)
    descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        second = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return
    os.close(second)
    raise OSError("O_EXCL created an existing name twice; a claim here is not exclusive.")


def _hard_link_no_overwrite(directory: Path, identity: str) -> None:
    """``os.link`` must create and must refuse to replace: the cache's write-once rule."""

    target = directory / f"{identity}.link"
    target.unlink(missing_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"probe")
        os.link(temporary, target)
        try:
            os.link(temporary, target)
        except FileExistsError:
            return
        raise OSError("os.link overwrote an existing name; write-once cannot hold here.")
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        with contextlib.suppress(FileNotFoundError):
            target.unlink()


def _heartbeat_mtime(marker: Path) -> None:
    """A refreshed mtime must be observable, or a lease cannot be renewed."""

    before = marker.stat().st_mtime_ns
    os.utime(marker, ns=(before + 1_000_000_000, before + 1_000_000_000))
    if marker.stat().st_mtime_ns <= before:
        raise OSError("mtime did not advance; a heartbeat would be invisible here.")


def _shared_listing(directory: Path, marker: Path) -> None:
    """This process's write must appear in the directory every mounter reads."""

    names = set(os.listdir(directory))
    if marker.name not in names:
        raise OSError(f"{marker.name} is not visible in the store's own listing.")
