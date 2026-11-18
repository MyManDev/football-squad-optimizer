"""Restart-safe run admission; this lock is always acquired before the queue lock.

Reservations are published before queue intent. A crash may waste capacity, but cannot
grant another attempt. Run metadata never changes the immutable answer or spec key.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from squadopt.contracts.llmopt_run import RunReference, job_capacity, run_capacity
from squadopt.data.atomic import replace_retrying
from squadopt.optimization.work_budget import WorkBudget
from squadopt.platform.queue_contracts import JobQueue
from squadopt.platform.storage._queue_lock import QueueFileLock


class RunAdmissionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RunTransaction:
    def __init__(self, store: FileRunStore, state: dict[str, Any]) -> None:
        self.store = store
        self.state = state

    def bind(self, ref: RunReference, binding: str, window: int, key: str, queue: JobQueue) -> None:
        runs = self.state["runs"]
        if ref.run_id not in runs:
            if ref.stage != "base":
                raise RunAdmissionError("RUN_BASE_REQUIRED", "Compute the main plan first.")
            runs[ref.run_id] = {
                "binding": binding,
                "window": window,
                "base": key,
                "closed": False,
                "base_cached": False,
                "requests": {},
                "reserved": 0.0,
            }
            self.store._save(self.state)
        run = runs[ref.run_id]
        if run["closed"]:
            raise RunAdmissionError("RUN_CANCELLED", "This planning run has ended.")
        if run["binding"] != binding or run["window"] != window:
            raise RunAdmissionError("RUN_CONTEXT_CHANGED", "The planning data changed.")
        if ref.stage == "base" and run["base"] != key:
            raise RunAdmissionError("RUN_BASE_CHANGED", "Confirm a new planning run.")
        if ref.stage != "base" and not run["base_cached"]:
            identifier = run["requests"].get(run["base"])
            base = queue.load(identifier) if identifier is not None else None
            if base is None or base.status != "completed":
                raise RunAdmissionError("RUN_BASE_REQUIRED", "Compute the main plan first.")

    def previous(self, ref: RunReference, key: str) -> str | None:
        value = self.state["runs"][ref.run_id]["requests"].get(key)
        return str(value) if value is not None else None

    def reserve(self, ref: RunReference, key: str, job_id: str) -> None:
        run = self.state["runs"][ref.run_id]
        previous = run["requests"].get(key)
        if previous is not None:
            if previous != job_id:
                raise RunAdmissionError("RUN_REQUEST_CHANGED", "The original request is retained.")
            return
        units = job_capacity(run["window"])
        if len(set(run["requests"].values())) >= 4 or run["reserved"] + units > run_capacity(
            run["window"]
        ):
            raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The completed plans are available.")
        run["requests"][key] = job_id
        run["reserved"] += units
        job = self.state["jobs"].setdefault(job_id, {"limit": units, "runs": [], "receipt": None})
        if ref.run_id not in job["runs"]:
            job["runs"].append(ref.run_id)
        self.store._save(self.state)

    def cached(self, ref: RunReference) -> None:
        if ref.stage == "base":
            self.state["runs"][ref.run_id]["base_cached"] = True
            self.store._save(self.state)


class FileRunStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = self.root / "ledger.json"
        self.lock = QueueFileLock(self.root / ".runs.lock")

    @contextmanager
    def transaction(self) -> Iterator[RunTransaction]:
        with self.lock.hold():
            try:
                state = json.loads(self.path.read_bytes())
                if (
                    not isinstance(state, dict)
                    or set(state) != {"contract_version", "runs", "jobs"}
                    or state["contract_version"] != "llmopt_run_ledger_v1"
                    or not isinstance(state["runs"], dict)
                    or not isinstance(state["jobs"], dict)
                ):
                    raise ValueError("Invalid run ledger.")
                self._validate(state)
            except FileNotFoundError:
                state = {"contract_version": "llmopt_run_ledger_v1", "runs": {}, "jobs": {}}
            except (ValueError, UnicodeError) as error:
                raise RunAdmissionError(
                    "RUN_STORE_UNAVAILABLE", "Planning work is unavailable."
                ) from error
            yield RunTransaction(self, state)

    @staticmethod
    def _validate(state: dict[str, Any]) -> None:
        for identifier, run in state["runs"].items():
            if re.fullmatch(r"[0-9a-f]{32}", identifier) is None or not isinstance(run, dict):
                raise ValueError("Invalid planning run identity.")
            if set(run) != {
                "binding",
                "window",
                "base",
                "closed",
                "base_cached",
                "requests",
                "reserved",
            }:
                raise ValueError("Invalid planning run fields.")
            if (
                type(run["window"]) is not int
                or run["window"] not in (1, 3)
                or type(run["closed"]) is not bool
                or type(run["base_cached"]) is not bool
            ):
                raise ValueError("Invalid planning run coordinates.")
            if not isinstance(run["requests"], dict) or len(run["requests"]) > 4:
                raise ValueError("Invalid planning run requests.")
            if not run["closed"] and (
                not isinstance(run["binding"], str)
                or re.fullmatch(r"[0-9a-f]{64}", run["binding"]) is None
            ):
                raise ValueError("Invalid planning run binding.")
            reserved = run["reserved"]
            if (
                type(reserved) not in (int, float)
                or not math.isfinite(reserved)
                or reserved != len(run["requests"]) * job_capacity(run["window"])
            ):
                raise ValueError("Invalid planning run reservation.")
            for key, job_id in run["requests"].items():
                job = state["jobs"].get(job_id)
                if (
                    re.fullmatch(r"[0-9a-f]{64}", key) is None
                    or not isinstance(job, dict)
                    or identifier not in job.get("runs", [])
                ):
                    raise ValueError("Invalid planning job association.")
        for job in state["jobs"].values():
            if (
                not isinstance(job, dict)
                or set(job) != {"limit", "runs", "receipt"}
                or job["limit"] not in (21.0, 122.0)
                or not isinstance(job["runs"], list)
                or not job["runs"]
                or any(owner not in state["runs"] for owner in job["runs"])
            ):
                raise ValueError("Invalid planning job allocation.")

    def _save(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".run-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, sort_keys=True, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            replace_retrying(Path(name), self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def cancel(self, run_id: str, queue: JobQueue, at_utc: str) -> None:
        with self.transaction() as tx:
            run = tx.state["runs"].get(run_id)
            if run is None:
                # A tombstone also closes a request racing its first admission.
                tx.state["runs"][run_id] = {
                    "closed": True,
                    "binding": "",
                    "window": 1,
                    "base": "",
                    "base_cached": False,
                    "requests": {},
                    "reserved": 0.0,
                }
            else:
                run["closed"] = True
            self._save(tx.state)
            if run is not None:
                for identifier in set(run["requests"].values()):
                    job = tx.state["jobs"][identifier]
                    if not any(not tx.state["runs"][owner]["closed"] for owner in job["runs"]):
                        queue.cancel_pending(identifier, at_utc=at_utc)

    def allocation(self, job_id: str) -> WorkBudget | None:
        with self.transaction() as tx:
            job = tx.state["jobs"].get(job_id)
            if job is None:
                return None
            if not any(not tx.state["runs"][owner]["closed"] for owner in job["runs"]):
                raise RunAdmissionError("RUN_CANCELLED", "This planning run has ended.")
            # Retries cannot reset work: previous execution was charged its entire limit.
            if job["receipt"] is not None:
                raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The admitted work was used.")
            job["receipt"] = {"started": True}
            self._save(tx.state)
            return WorkBudget(float(job["limit"]))

    def finish(self, job_id: str, budget: WorkBudget) -> None:
        with self.transaction() as tx:
            job = tx.state["jobs"][job_id]
            job["receipt"] = {
                "cp_used": budget.cp_used,
                "native_reserved": budget.native_reserved,
                "calls": budget.calls,
            }
            self._save(tx.state)
            if not any(not tx.state["runs"][owner]["closed"] for owner in job["runs"]):
                raise RunAdmissionError("RUN_CANCELLED", "This planning run has ended.")
