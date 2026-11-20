"""One explicit capacity shared by all nested calls in an admitted solve."""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

from squadopt.optimization.models import SolverExecutionError


class WorkBudgetExhausted(SolverExecutionError):
    """No subsequent solver invocation may start in this allocation."""


class WorkJournal(Protocol):
    """Durable grants owned by one queue attempt."""

    def begin_cp(self, requested: float) -> float: ...

    def finish_cp(self, used: float) -> None: ...

    def abandon_cp(self) -> float: ...

    def reserve_native(self, units: int) -> None: ...


@dataclass(slots=True)
class WorkBudget:
    limit: float
    cp_used: float = 0.0
    native_reserved: float = 0.0
    calls: int = 0
    journal: WorkJournal | None = None
    unconfirmed: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.cp_used - self.native_reserved - self.unconfirmed)

    def cp_limit(self, configured: float) -> float:
        if self.remaining <= 0:
            raise WorkBudgetExhausted("The admitted planning work is exhausted.")
        limit = min(configured, self.remaining)
        if self.journal is not None:
            limit = self.journal.begin_cp(limit)
        self.calls += 1
        return limit

    def record_cp(self, used: float) -> None:
        if self.journal is not None:
            self.journal.finish_cp(used)
        self.cp_used += used

    def abandon_cp(self) -> None:
        if self.journal is not None:
            self.unconfirmed += self.journal.abandon_cp()

    def reserve_native(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds <= 0:
            raise WorkBudgetExhausted("The native solve has no finite work allowance.")
        units = math.ceil(seconds / 30.0)
        if units > self.remaining:
            raise WorkBudgetExhausted("The native solve cannot fit the admitted work.")
        if self.journal is not None:
            self.journal.reserve_native(units)
        self.native_reserved += units
        self.calls += 1


_CURRENT: ContextVar[WorkBudget | None] = ContextVar("planning_work_budget", default=None)


def current_work_budget() -> WorkBudget | None:
    return _CURRENT.get()


@contextmanager
def work_budget(budget: WorkBudget | None) -> Iterator[None]:
    token = _CURRENT.set(budget)
    try:
        yield
    finally:
        _CURRENT.reset(token)
