"""Read completed one-week server answers from an offline backend-store snapshot.

No solver, network request, queue recovery or cache repair runs here. The existing
job, spec and cache files are the durable history; this export joins them without
introducing another write in the worker's completion transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from squadopt.platform.advice_cache import advice_cache_key
from squadopt.platform.advice_documents import validate_advice_document
from squadopt.platform.advice_job_spec import AdviceJobSpec
from squadopt.platform.jobs_contract import AdviceJob, _instant, _utc


def _key(spec: AdviceJobSpec) -> str:
    context = spec.context
    return advice_cache_key(
        advice_contract_version=context.advice_contract_version,
        capture_snapshot_id=context.capture_snapshot_id,
        season=context.season,
        gameweek=context.gameweek,
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        strategy=spec.strategy,
        window=spec.window,
        rival_entry_id=spec.rival_entry_id,
        projection_handoff_fingerprint=context.projection_handoff_fingerprint,
        repository_commit=context.repository_commit,
        configuration_fingerprint=context.configuration_fingerprint,
        switches=spec.switches,
    )


def _completed(store: Path) -> list[AdviceJob]:
    jobs: dict[str, AdviceJob] = {}
    for directory in (store / "jobs", store / "jobs" / "archive"):
        for path in sorted(directory.glob("*.json")):
            job = AdviceJob.from_payload(json.loads(path.read_bytes()))
            if path.stem != job.job_id:
                raise ValueError("A job's filename differs from its recorded identity.")
            if job.job_id in jobs and jobs[job.job_id] != job:
                raise ValueError("Live and archived copies of a job disagree.")
            jobs[job.job_id] = job
    return [job for job in jobs.values() if job.status == "completed"]


def requested_history(
    store: Path,
    *,
    season: str,
    gameweek: int,
    entry_id: int,
    deadline_utc: str,
) -> dict[str, Any]:
    """Export successful plain one-week requests, including public-entry requests.

    Completion time is the queue's terminal clock, never the advice envelope's
    capture clock. A completed result proves availability, not a page view or
    adoption. Distinct full cache identities remain distinct even for one capture.
    """
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", season):
        raise ValueError("season must have the shape YYYY-YY.")
    if any(type(value) is not int or value < 1 for value in (gameweek, entry_id)):
        raise ValueError("gameweek and entry_id must be positive integers.")
    deadline_utc = _utc(deadline_utc, label="deadline_utc")
    deadline = _instant(deadline_utc)
    if not all((store / part).is_dir() for part in ("jobs", "specs", "cache")):
        raise ValueError("Expected an offline store snapshot with jobs, specs and cache.")

    records: dict[str, dict[str, Any]] = {}
    for job in _completed(store):
        key = job.cache_key
        if job.result_ref != key:
            raise ValueError("A completed job does not name its own answer.")
        spec = AdviceJobSpec.from_payload(
            json.loads((store / "specs" / key[:2] / f"{key}.json").read_bytes())
        )
        if (spec.context.season, spec.context.gameweek, spec.entry_id) != (
            season,
            gameweek,
            entry_id,
        ):
            continue
        if (
            spec.strategy != "saf-puan"
            or spec.window != 1
            or spec.rival_entry_id is not None
            or set(spec.switches) - {"public_entry"}
        ):
            continue
        if _key(spec) != key:
            raise ValueError("The request specification differs from its cache address.")
        raw = (store / "cache" / key[:2] / f"{key}.json").read_bytes()
        validate_advice_document(raw)
        document = json.loads(raw)
        payload = document["payload"]
        expected = {
            "season": season,
            "gameweek": gameweek,
            "entry_id": entry_id,
            "league_id": spec.league_id,
            "mode": "saf-puan",
            "window": 1,
            "source_snapshot_id": spec.context.capture_snapshot_id,
        }
        if (
            document["contract_version"] != spec.context.advice_contract_version
            or document.get("source_kind") != "live"
            or any(payload.get(name) != value for name, value in expected.items())
            or any(name in payload for name in ("evidence", "top100", "preferences", "plan_weeks"))
        ):
            raise ValueError("The cached advice does not identify the recorded request.")
        captured = _instant(_utc(document["generated_at_utc"], label="capture time"))
        completed = _instant(job.updated_at_utc)
        if completed < captured:
            raise ValueError("Completion precedes the advice capture.")
        # Validate candidates before choosing: damaged later evidence must not make
        # an earlier answer silently authoritative. Never backdate a late completion.
        if completed >= deadline:
            continue
        held = records.get(key)
        if held is not None and _instant(held["completed_at_utc"]) <= completed:
            continue
        records[key] = {
            "cache_key": key,
            "completed_at_utc": job.updated_at_utc,
            "request": spec.as_payload(),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "response_json": raw.decode("utf-8"),
        }
    return {
        "format": "requested_advice_export_v1",
        "season": season,
        "gameweek": gameweek,
        "entry_id": entry_id,
        "deadline_utc": deadline_utc,
        "records": sorted(
            records.values(), key=lambda row: (_instant(row["completed_at_utc"]), row["cache_key"])
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-snapshot", required=True, type=Path)
    parser.add_argument("--season", required=True)
    parser.add_argument("--gameweek", required=True, type=int)
    parser.add_argument("--entry-id", required=True, type=int)
    parser.add_argument("--deadline-utc", required=True)
    args = parser.parse_args(argv)
    try:
        document = requested_history(
            args.store_snapshot,
            season=args.season,
            gameweek=args.gameweek,
            entry_id=args.entry_id,
            deadline_utc=args.deadline_utc,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Requested history export refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(document, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
