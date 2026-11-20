"""Restart-safe run admission; this lock is always acquired before the queue lock.

Reservations are published before queue intent. A crash may waste capacity, but cannot
grant another attempt. Run metadata never changes the immutable answer or spec key.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.contracts.llmopt_run import RunReference, job_capacity, run_capacity
from squadopt.data.atomic import replace_retrying
from squadopt.optimization.work_budget import WorkBudget, WorkBudgetExhausted
from squadopt.platform.queue_contracts import JobQueue
from squadopt.platform.storage._queue_lock import QueueFileLock

CANCEL_TTL_SECONDS = 300
MAX_CANCELLED_IDS = 1024


class RunAdmissionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reservation(job: dict[str, Any]) -> float:
    receipt = job.get("receipt")
    if isinstance(receipt, dict) and "attempt" in receipt and "charged" in receipt:
        return float(receipt["charged"])
    return float(job["limit"])


def _spent(receipt: dict[str, Any]) -> float:
    return float(receipt["cp_used"] + receipt["native_reserved"] + receipt["unconfirmed"])


def _bundle_receipt(attempt: int, *, finished: bool = False) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "pending": 0.0,
        "unconfirmed": 0.0,
        "cp_used": 0.0,
        "native_reserved": 0.0,
        "calls": 0,
        "finished": finished,
    }


def _close_grant(receipt: dict[str, Any]) -> None:
    receipt["unconfirmed"] += receipt["pending"]
    receipt.update(pending=0.0, finished=True)


class BundleWorkJournal:
    """Persist each solver grant before the current queue attempt may use it."""

    def __init__(self, store: FileRunStore, job_id: str, attempt: int) -> None:
        self.store = store
        self.job_id = job_id
        self.attempt = attempt

    @contextmanager
    def _update(self) -> Iterator[tuple[dict[str, Any], float]]:
        with self.store.transaction() as tx:
            job = tx.state["jobs"][self.job_id]
            receipt = job["receipt"]
            if receipt["attempt"] != self.attempt or receipt.get("finished"):
                raise WorkBudgetExhausted("This attempt no longer owns the planning work.")
            yield receipt, float(job["limit"])
            self.store._save(tx.state)

    def begin_cp(self, requested: float) -> float:
        with self._update() as (receipt, limit):
            remaining = limit - _spent(receipt)
            grant = min(requested, remaining)
            single = limit / 3
            if grant > single:
                grant = min(grant, max(single, remaining - single / 4))
            if grant <= 0 or receipt["pending"] != 0:
                raise WorkBudgetExhausted("No further planning work can start.")
            receipt["pending"] = grant
            receipt["calls"] += 1
            return grant

    def finish_cp(self, used: float) -> None:
        with self._update() as (receipt, _):
            if receipt["pending"] <= 0 or not math.isfinite(used) or used < 0:
                raise WorkBudgetExhausted("The planning work cannot be confirmed.")
            receipt["cp_used"] += used
            receipt["pending"] = 0.0

    def abandon_cp(self) -> float:
        with self._update() as (receipt, _):
            grant = float(receipt["pending"])
            receipt["unconfirmed"] += grant
            receipt["pending"] = 0.0
            return grant

    def reserve_native(self, units: int) -> None:
        with self._update() as (receipt, limit):
            if receipt["pending"] or units > limit - _spent(receipt):
                raise WorkBudgetExhausted("The native solve cannot fit the admitted work.")
            receipt["native_reserved"] += units
            receipt["calls"] += 1


class RunTransaction:
    def __init__(self, store: FileRunStore, state: dict[str, Any]) -> None:
        self.store = store
        self.state = state
        self.repair_candidate: str | None = None

    def bind(
        self,
        ref: RunReference,
        binding: str,
        window: int,
        key: str,
        queue: JobQueue,
        *,
        capture: str | None = None,
    ) -> None:
        runs = self.state["runs"]
        if ref.run_id in self.state["cancelled"]:
            raise RunAdmissionError("RUN_CANCELLED", "This planning run has ended.")
        if ref.run_id not in runs:
            if ref.stage != "base":
                raise RunAdmissionError("RUN_BASE_REQUIRED", "Compute the main plan first.")
            runs[ref.run_id] = {
                "binding": binding,
                "capture": capture,
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
        if run["capture"] is None and capture is not None:
            run["capture"] = capture
            self.store._save(self.state)
        if ref.stage == "base" and run["base"] != key:
            raise RunAdmissionError("RUN_BASE_CHANGED", "Confirm a new planning run.")
        if ref.stage == "repair" and window != 3:
            raise RunAdmissionError("RUN_REPAIR_INVALID", "Server repairs require three weeks.")
        if ref.stage != "base" and not run["base_cached"]:
            identifier = run["requests"].get(run["base"])
            base = queue.load(identifier) if identifier is not None else None
            proved_failure = (
                ref.stage == "repair"
                and base is not None
                and base.status == "failed"
                and base.error is not None
                and (
                    base.error.code == "CHIP_NOT_HELD"
                    or (
                        base.error.code == "PLAN_NOT_FOUND" and base.error.infeasibility is not None
                    )
                )
            )
            if not proved_failure and (base is None or base.status != "completed"):
                raise RunAdmissionError("RUN_BASE_REQUIRED", "Compute the main plan first.")

    def previous(self, ref: RunReference, key: str) -> str | None:
        value = self.state["runs"][ref.run_id]["requests"].get(key)
        return str(value) if value is not None else None

    def completed_answer(
        self, ref: RunReference, key: str, document: bytes, queue: JobQueue
    ) -> bool:
        identifier = self.previous(ref, key)
        if identifier is None:
            return False
        allocation = self.state["jobs"][identifier]
        receipt = allocation["receipt"]
        if (
            allocation["limit"] != job_capacity(3)
            or not isinstance(receipt, dict)
            or "answer_sha256" not in receipt
        ):
            return False
        job = queue.load(identifier)
        return (
            job is not None
            and job.status == "completed"
            and job.contract_version == "backend_jobs_v2"
            and job.cache_key == key
            and receipt["answer_sha256"] == hashlib.sha256(document).hexdigest()
        )

    def release_failed_bundles(self, run_id: str, queue: JobQueue) -> None:
        owners: set[str] = set()
        for identifier in self.state["runs"][run_id]["requests"].values():
            job = self.state["jobs"][identifier]
            receipt = job["receipt"]
            if job["limit"] not in (63, 366) or (
                receipt is not None and ("attempt" not in receipt or "charged" in receipt)
            ):
                continue
            record = queue.load(identifier)
            if record is None or record.status not in ("failed", "cancelled"):
                continue
            if receipt is None:
                # Allocation never published its first grant, so no solver could start.
                receipt = job["receipt"] = _bundle_receipt(record.attempt, finished=True)
            _close_grant(receipt)
            receipt["charged"] = min(job["limit"], _spent(receipt))
            owners.update(job["runs"])
        if owners:
            for owner in owners:
                run = self.state["runs"][owner]
                run["reserved"] = math.fsum(
                    _reservation(self.state["jobs"][identifier])
                    for identifier in run["requests"].values()
                )
            self.store._save(self.state)

    def reserve(
        self, ref: RunReference, key: str, job_id: str, *, preference_bundle: bool = False
    ) -> None:
        run = self.state["runs"][ref.run_id]
        previous = run["requests"].get(key)
        if previous is not None:
            if previous != job_id:
                raise RunAdmissionError("RUN_REQUEST_CHANGED", "The original request is retained.")
            return
        units = job_capacity(run["window"]) * (3 if preference_bundle else 1)
        # A candidate needs room for its own solve and the selected-plan replay.
        if self.repair_candidate == key and (
            len(run["requests"]) >= 3 or run["reserved"] + 2 * units > run_capacity(run["window"])
        ):
            raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The completed plans are available.")
        if len(set(run["requests"].values())) >= 4 or run["reserved"] + units > run_capacity(
            run["window"]
        ):
            raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The completed plans are available.")
        run["requests"][key] = job_id
        self._remember_candidate(run)
        job = self.state["jobs"].setdefault(
            job_id, {"limit": units, "runs": [], "receipt": None, "legacy_consumer": False}
        )
        if ref.run_id not in job["runs"]:
            job["runs"].append(ref.run_id)
        run["reserved"] = math.fsum(
            _reservation(self.state["jobs"][identifier]) for identifier in run["requests"].values()
        )
        self.store._save(self.state)

    def cached(self, ref: RunReference) -> None:
        run = self.state["runs"][ref.run_id]
        changed = self._remember_candidate(run)
        if ref.stage == "base":
            run["base_cached"] = True
        if ref.stage == "base" or changed:
            self.store._save(self.state)

    def _remember_candidate(self, run: dict[str, Any]) -> bool:
        key = self.repair_candidate
        if key is None or key in run.get("repair_candidates", []):
            return False
        run.setdefault("repair_candidates", []).append(key)
        return True

    def legacy_consumer(self, job_id: str) -> None:
        """An anonymous join owns the answer independently of every identified run."""
        job = self.state["jobs"].get(job_id)
        if job is not None and not job["legacy_consumer"]:
            job["legacy_consumer"] = True
            self.store._save(self.state)

    def prune(self, capture: str, queue: JobQueue) -> None:
        """Retire obsolete captures only after all their computations are terminal."""
        removed = set()
        loaded = {}
        for identifier, run in self.state["runs"].items():
            if run["capture"] is None or run["capture"] == capture:
                continue
            identifiers = set(run["requests"].values())
            for job_id in identifiers:
                if job_id not in loaded:
                    loaded[job_id] = queue.load(job_id)
            if any(
                (queued := loaded[job_id]) is not None and not queued.is_terminal
                for job_id in identifiers
            ):
                continue
            removed.add(identifier)
        if not removed:
            return
        for identifier in removed:
            del self.state["runs"][identifier]
        for job_id, job in tuple(self.state["jobs"].items()):
            job["runs"] = [owner for owner in job["runs"] if owner not in removed]
            if not job["runs"]:
                del self.state["jobs"][job_id]
        self.store._save(self.state)


class FileRunStore:
    def __init__(
        self, root: Path | str, *, capture_for_key: Callable[[str], str | None] | None = None
    ) -> None:
        self.root = Path(root)
        self.path = self.root / "ledger.json"
        self.lock = QueueFileLock(self.root / ".runs.lock")
        self._capture_for_key = capture_for_key

    @contextmanager
    def transaction(self, *, at_utc: str | None = None) -> Iterator[RunTransaction]:
        with self.lock.hold():
            now = (datetime.fromisoformat(at_utc) if at_utc else datetime.now(UTC)).timestamp()
            try:
                state = json.loads(self.path.read_bytes())
                migrated = self._migrate(state, now)
                if (
                    not isinstance(state, dict)
                    or set(state) != {"contract_version", "runs", "jobs", "cancelled"}
                    or state["contract_version"] != "llmopt_run_ledger_v2"
                    or not isinstance(state["runs"], dict)
                    or not isinstance(state["jobs"], dict)
                ):
                    raise ValueError("Invalid run ledger.")
                self._validate(state)
                expired = [key for key, expiry in state["cancelled"].items() if expiry <= now]
                for key in expired:
                    del state["cancelled"][key]
                if migrated or expired:
                    self._save(state)
            except FileNotFoundError:
                state = {
                    "contract_version": "llmopt_run_ledger_v2",
                    "runs": {},
                    "jobs": {},
                    "cancelled": {},
                }
            except (ValueError, UnicodeError) as error:
                raise RunAdmissionError(
                    "RUN_STORE_UNAVAILABLE", "Planning work is unavailable."
                ) from error
            yield RunTransaction(self, state)

    def _migrate(self, state: Any, now: float) -> bool:
        if not isinstance(state, dict) or state.get("contract_version") != "llmopt_run_ledger_v1":
            return False
        if set(state) != {"contract_version", "runs", "jobs"}:
            raise ValueError("Invalid old run ledger.")
        if not isinstance(state["runs"], dict) or not isinstance(state["jobs"], dict):
            raise ValueError("Invalid old run ledger maps.")
        state["cancelled"] = {}
        for identifier, run in tuple(state["runs"].items()):
            if not isinstance(run, dict) or set(run) != {
                "binding",
                "window",
                "base",
                "closed",
                "base_cached",
                "requests",
                "reserved",
            }:
                raise ValueError("Invalid old planning run fields.")
            if not isinstance(run["requests"], dict):
                raise ValueError("Invalid old planning run requests.")
            if run["closed"] and run["binding"] == "" and run["requests"] == {}:
                state["cancelled"][identifier] = now + CANCEL_TTL_SECONDS
                del state["runs"][identifier]
                continue
            run["capture"] = None
            if self._capture_for_key is not None:
                for key in dict.fromkeys([run["base"], *run["requests"]]):
                    capture = self._capture_for_key(key)
                    if capture is not None:
                        run["capture"] = capture
                        break
        for job in state["jobs"].values():
            if not isinstance(job, dict) or set(job) != {"limit", "runs", "receipt"}:
                raise ValueError("Invalid old planning job fields.")
            # The old ledger did not record anonymous joins. Do not revoke a
            # possible existing consumer during migration.
            job["legacy_consumer"] = True
        self._trim_cancelled(state)
        state["contract_version"] = "llmopt_run_ledger_v2"
        return True

    @staticmethod
    def _trim_cancelled(state: dict[str, Any]) -> None:
        oldest = sorted(state["cancelled"], key=lambda key: (state["cancelled"][key], key))
        for key in oldest[: max(0, len(oldest) - MAX_CANCELLED_IDS)]:
            del state["cancelled"][key]

    @staticmethod
    def _validate(state: dict[str, Any]) -> None:
        if not isinstance(state["cancelled"], dict) or len(state["cancelled"]) > MAX_CANCELLED_IDS:
            raise ValueError("Invalid bounded cancellations.")
        for identifier, expiry in state["cancelled"].items():
            if (
                re.fullmatch(r"[0-9a-f]{32}", identifier) is None
                or type(expiry) not in (int, float)
                or not math.isfinite(expiry)
                or expiry < 0
            ):
                raise ValueError("Invalid cancellation expiry.")
        for identifier, run in state["runs"].items():
            if re.fullmatch(r"[0-9a-f]{32}", identifier) is None or not isinstance(run, dict):
                raise ValueError("Invalid planning run identity.")
            if set(run) - {"repair_candidates"} != {
                "binding",
                "capture",
                "window",
                "base",
                "closed",
                "base_cached",
                "requests",
                "reserved",
            }:
                raise ValueError("Invalid planning run fields.")
            candidates = run.get("repair_candidates", [])
            if (
                not isinstance(candidates, list)
                or len(candidates) > 2
                or any(
                    not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                    for key in candidates
                )
                or len(set(candidates)) != len(candidates)
            ):
                raise ValueError("Invalid planning repair candidates.")
            if (
                (run["capture"] is not None and not isinstance(run["capture"], str))
                or type(run["window"]) is not int
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
                or reserved > run_capacity(run["window"])
                or reserved
                != math.fsum(
                    _reservation(state["jobs"].get(job_id, {"limit": -1}))
                    for job_id in run["requests"].values()
                )
            ):
                raise ValueError("Invalid planning run reservation.")
            for key, job_id in run["requests"].items():
                job = state["jobs"].get(job_id)
                if (
                    re.fullmatch(r"[0-9a-f]{64}", key) is None
                    or not isinstance(job, dict)
                    or identifier not in job.get("runs", [])
                    or job.get("limit")
                    not in (job_capacity(run["window"]), 3 * job_capacity(run["window"]))
                ):
                    raise ValueError("Invalid planning job association.")
        for job in state["jobs"].values():
            if (
                not isinstance(job, dict)
                or set(job) != {"limit", "runs", "receipt", "legacy_consumer"}
                or job["limit"] not in (21.0, 63.0, 122.0, 366.0)
                or not isinstance(job["runs"], list)
                or not job["runs"]
                or type(job["legacy_consumer"]) is not bool
                or any(owner not in state["runs"] for owner in job["runs"])
            ):
                raise ValueError("Invalid planning job allocation.")
            receipt = job["receipt"]
            if not isinstance(receipt, dict) or "attempt" not in receipt:
                continue
            if (
                type(receipt["attempt"]) is not int
                or receipt["attempt"] < 1
                or type(receipt.get("calls")) is not int
                or receipt["calls"] < 0
                or type(receipt.get("finished")) is not bool
                or any(
                    type(receipt.get(field)) not in (int, float)
                    or not math.isfinite(receipt[field])
                    or receipt[field] < 0
                    for field in ("pending", "cp_used", "native_reserved", "unconfirmed")
                )
                or (
                    "charged" in receipt
                    and (
                        type(receipt["charged"]) not in (int, float)
                        or not math.isfinite(receipt["charged"])
                        or not 0 <= receipt["charged"] <= job["limit"]
                    )
                )
            ):
                raise ValueError("Invalid bundle work receipt.")

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

    def cancel(
        self, run_id: str, queue: JobQueue, at_utc: str, *, capture: str | None = None
    ) -> None:
        with self.transaction(at_utc=at_utc) as tx:
            if capture is not None:
                tx.prune(capture, queue)
            run = tx.state["runs"].get(run_id)
            if run is None:
                # Cover an in-flight first admission without a permanent run row.
                now = datetime.fromisoformat(at_utc).timestamp()
                tx.state["cancelled"].setdefault(run_id, now + CANCEL_TTL_SECONDS)
                self._trim_cancelled(tx.state)
            else:
                run["closed"] = True
            self._save(tx.state)
            if run is not None:
                for identifier in set(run["requests"].values()):
                    job = tx.state["jobs"][identifier]
                    if not job["legacy_consumer"] and not any(
                        not tx.state["runs"][owner]["closed"] for owner in job["runs"]
                    ):
                        queue.cancel_pending(identifier, at_utc=at_utc)

    def allocation(self, job_id: str, *, attempt: int = 1) -> WorkBudget | None:
        with self.transaction() as tx:
            job = tx.state["jobs"].get(job_id)
            if job is None:
                return None
            if job["limit"] in (63, 366):
                receipt = job["receipt"]
                if (
                    attempt > 1
                    and not job["legacy_consumer"]
                    and all(tx.state["runs"][owner]["closed"] for owner in job["runs"])
                ):
                    if (
                        isinstance(receipt, dict)
                        and "attempt" in receipt
                        and attempt > receipt["attempt"]
                    ):
                        _close_grant(receipt)
                        receipt["attempt"] = attempt
                        self._save(tx.state)
                    raise RunAdmissionError("RUN_CANCELLED", "This planning run has ended.")
                if receipt is None:
                    receipt = job["receipt"] = _bundle_receipt(attempt)
                elif (
                    "attempt" not in receipt
                    or attempt <= receipt["attempt"]
                    or "charged" in receipt
                ):
                    raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The admitted work was used.")
                else:
                    _close_grant(receipt)
                    receipt.update(attempt=attempt, pending=0.0, finished=False)
                self._save(tx.state)
                return WorkBudget(
                    max(0.0, job["limit"] - _spent(receipt)),
                    journal=BundleWorkJournal(self, job_id, attempt),
                )
            # Retries cannot reset work: previous execution was charged its entire limit.
            if job["receipt"] is not None:
                raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The admitted work was used.")
            job["receipt"] = {"started": True}
            self._save(tx.state)
            return WorkBudget(float(job["limit"]))

    def finish(
        self, job_id: str, budget: WorkBudget, *, rollback_answer: bytes | None = None
    ) -> None:
        with self.transaction() as tx:
            job = tx.state["jobs"][job_id]
            if isinstance(budget.journal, BundleWorkJournal):
                receipt = job["receipt"]
                if receipt["attempt"] != budget.journal.attempt or receipt["finished"]:
                    return
                _close_grant(receipt)
            else:
                job["receipt"] = {
                    "cp_used": budget.cp_used,
                    "native_reserved": budget.native_reserved,
                    "calls": budget.calls,
                }
                if rollback_answer is not None and job["limit"] == job_capacity(3):
                    job["receipt"]["answer_sha256"] = hashlib.sha256(rollback_answer).hexdigest()
            self._save(tx.state)
