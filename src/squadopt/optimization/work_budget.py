"""One explicit capacity shared by all nested calls in an admitted solve."""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from squadopt.optimization.models import SolverExecutionError


class WorkBudgetExhausted(SolverExecutionError):
    """No subsequent solver invocation may start in this allocation."""


@dataclass(slots=True)
class WorkBudget:
    limit: float
    cp_used: float = 0.0
    native_reserved: float = 0.0
    calls: int = 0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.cp_used - self.native_reserved)

    def cp_limit(self, configured: float) -> float:
        if self.remaining <= 0:
            raise WorkBudgetExhausted("The admitted planning work is exhausted.")
        self.calls += 1
        return min(configured, self.remaining)

    def reserve_native(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds <= 0:
            raise WorkBudgetExhausted("The native solve has no finite work allowance.")
        units = math.ceil(seconds / 30.0)
        if units > self.remaining:
            raise WorkBudgetExhausted("The native solve cannot fit the admitted work.")
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
