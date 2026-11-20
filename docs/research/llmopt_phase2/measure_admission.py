"""Offline admission replay on the immutable Phase 1 member-week identities.

This measures the actual submit/queue/run adapters, not football quality or solve time.
The harness completes the base with explicitly synthetic bytes and fails follow-ups;
its purpose is counting admissions, including retries, restarts and a fifth request.
Run separately from tests: python -m docs.research.llmopt_phase2.measure_admission
"""

import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from docs.research.llmopt_phase1.benchmark import snapshots

from squadopt.contracts.llmopt_run import RunReference
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import (
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
    PreferencePlayers,
)
from squadopt.platform.advice_runs import FileRunStore, RunAdmissionError
from squadopt.platform.advice_submit import AdviceSubmitService
from squadopt.platform.jobs_contract import JobError

STAMP = "2026-11-18T00:00:00Z"
ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs/research/llmopt_phase2_admission.json"


class Context:
    def __init__(self, context):
        self.context = context

    def current(self):
        return self.context


def replay(root, inputs, entry, window, producer):
    member = inputs.members[entry]
    held = member["held"]
    context = AdviceRequestContext(
        "advice_v1",
        inputs.capture,
        inputs.table["season"],
        inputs.gameweek,
        hashlib.sha256(json.dumps(inputs.table, sort_keys=True).encode()).hexdigest(),
        producer,
        "d" * 64,
    )
    directory = root / "site/league"
    directory.mkdir(parents=True)
    (directory / "members.json").write_text(
        json.dumps(
            {
                "contract_version": "provisional_league_ui_v1",
                "payload": {
                    "league_id": 352490,
                    "league_name": "Phase 1 admission fixture",
                    "season": context.season,
                    "gameweek": context.gameweek,
                    "members": [{"member_kind": "human", "entry_id": entry}],
                },
            }
        ),
        encoding="utf-8",
    )
    queue, cache = FileJobQueue(root / "jobs"), FileAdviceCache(root / "cache")

    def service():
        return AdviceSubmitService(
            AdviceReadStore(
                FileLeagueDirectory(root / "site"),
                cache,
                Context(context),
                {"saf-puan": False},
                llmopt_vnext=True,
                preference_players=lambda *_: PreferencePlayers(frozenset(held), frozenset(held)),
            ),
            queue,
            runs=FileRunStore(root / "runs"),
        )

    identifier = hashlib.sha256(f"{inputs.gameweek}:{entry}:{window}".encode()).hexdigest()[:32]
    fields = dict(
        league_id=352490,
        entry_id=entry,
        strategy="saf-puan",
        window=window,
        rival_entry_id=None,
        idempotency_key=None,
        client_bucket="offline",
        at_utc=STAMP,
    )
    ref = RunReference(identifier, "base")
    main = service().submit(**fields, run=ref)
    synthetic = json.dumps(
        {
            "contract_version": "provisional_league_ui_v1",
            "generated_at_utc": STAMP,
            "source_kind": "live",
            "payload": {
                "season": context.season,
                "gameweek": context.gameweek,
                "entry_id": entry,
                "league_id": 352490,
                "mode": "saf-puan",
                "window": window,
                "moves": [],
                "data_quality": "complete",
                "missing_fields": [],
            },
        }
    ).encode()
    run_advice_worker_once(queue, cache, lambda _: synthetic, at_utc=STAMP)
    replays = 0
    for keep in ([held[0]], [held[1]], held[:3]):
        prefs = DecisionPreferences.parse({"keep_players": keep, "net_points_priority": True})
        followup = RunReference(identifier, "followup")
        accepted = service().submit(**fields, run=followup, preferences=prefs)
        claimed = queue.claim(at_utc=STAMP)
        queue.store(
            claimed.transition(
                "failed",
                at_utc=STAMP,
                error=JobError("ADVICE_FAILED", "Synthetic harness termination."),
            )
        )
        for _ in range(2):
            repeated = service().submit(**fields, run=followup, preferences=prefs)
            assert repeated.job.job_id == accepted.job.job_id
            replays += 1
    try:
        service().submit(
            **fields,
            run=RunReference(identifier, "followup"),
            preferences=DecisionPreferences.parse({"keep_players": [held[2]]}),
        )
    except RunAdmissionError as error:
        refusal = error.code
    else:
        raise AssertionError("The fifth server job was admitted.")
    assert refusal == "RUN_BUDGET_EXHAUSTED"
    assert service().submit(**fields, run=ref).kind == "hit"
    state = json.loads((root / "runs/ledger.json").read_text(encoding="utf-8"))
    run = state["runs"][identifier]
    assert len(queue.jobs()) == 4 and main.job is not None
    return dict(
        gameweek=inputs.gameweek,
        entry_id=entry,
        window=window,
        server_jobs=len(queue.jobs()),
        restarted_replays=replays,
        extra_jobs_from_replays=0,
        fifth_request=refusal,
        reserved_units=run["reserved"],
    )


def main():
    producer = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    rows = []
    with TemporaryDirectory(prefix="lp2-admit-") as temporary:
        for _, inputs in snapshots():
            for entry in sorted(inputs.members):
                for window in (1, 3):
                    root = Path(temporary) / f"{inputs.gameweek}-{entry}-{window}"
                    rows.append(replay(root, inputs, entry, window, producer))
    record = dict(
        producer_repository_commit=producer,
        runner_sha256=hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        frozen_inputs="docs/research/llmopt_phase1/inputs.json",
        scope="local admission adapters; synthetic completions; no solver-quality or latency claim",
        network_requests=0,
        solver_calls=0,
        member_weeks=20,
        runs=len(rows),
        max_jobs=max(row["server_jobs"] for row in rows),
        extra_jobs_from_replays=sum(row["extra_jobs_from_replays"] for row in rows),
        rows=rows,
    )
    OUTPUT.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in record.items() if key != "rows"}))


if __name__ == "__main__":
    main()
