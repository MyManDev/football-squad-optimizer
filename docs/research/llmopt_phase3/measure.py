"""Local API, immutable queue and real-worker replay on the frozen twenty member-weeks.

Run separately from tests: python -m docs.research.llmopt_phase3.measure
The frozen expected-point table is an input, not a forecast recomputed by this runner.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from docs.research.llmopt_phase1 import benchmark
from fastapi.testclient import TestClient
from scripts.measure_window_solver_highs import _players_frame, window_call

from squadopt.api.app import create_app
from squadopt.application.advice_capabilities import menu_capabilities
from squadopt.application.entries import EntryPicks
from squadopt.contracts.preference_bundle import BUNDLE_VERSION
from squadopt.data.sources.fpl_live import GameweekDeadline
from squadopt.live import Projection, RecommendationInputs
from squadopt.live.rules import (
    SEASON_RULES_CONTRACT_VERSION,
    ChipWindow,
    ScoringRules,
    SeasonRules,
    TransferRules,
)
from squadopt.planning import ProjectionHorizon
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import AdviceReadStore, AdviceRequestContext, PreferencePlayers
from squadopt.platform.advice_runs import FileRunStore
from squadopt.platform.advice_submit import AdviceSubmitService
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.capture_context import AdviceCaptureContext

ROOT = Path(__file__).resolve().parents[3]
SOURCES = (
    Path(__file__).relative_to(ROOT),
    *(
        Path(f"src/squadopt/{name}.py")
        for name in (
            "api/app",
            "contracts/preference_bundle",
            "contracts/priority_preferences",
            "platform/advice_read",
            "platform/advice_submit",
            "platform/advice_runs",
            "platform/advice_worker",
            "platform/advice_preference_bundle",
            "application/advice_menu",
            "application/advice_chip_strategy",
            "live/transfers",
            "planning/optimizer",
            "optimization/work_budget",
        )
    ),
)


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class FrozenProvider:
    def __init__(self, picks):
        self.value = picks

    def holds(self, entry_id, gameweek):
        return entry_id == self.value.entry_id and gameweek == self.value.gameweek

    def picks(self, entry_id, season, gameweek):
        assert (entry_id, season, gameweek) == (
            self.value.entry_id,
            self.value.season,
            self.value.gameweek,
        )
        return self.value


class FrozenContexts:
    def __init__(self, capture):
        self.value = capture

    def current(self):
        return self.value.context

    def capture(self, context):
        assert context == self.value.context
        return self.value


class FrozenDirectory:
    def __init__(self, inputs, entry):
        self.value = dict(
            season=inputs.table["season"],
            gameweek=inputs.gameweek,
            members=[dict(entry_id=entry, member_kind="human")],
        )

    def league(self, _league_id):
        return self.value


class ScoringNotUsed:
    """A guard: this replay must consume frozen points without invoking a scorer."""

    def __getattribute__(self, name):
        if name.startswith("__"):
            return object.__getattribute__(self, name)
        raise AssertionError("The frozen-point replay must not invoke scoring.")


def make_capture(frozen, inputs, entry, scenario, producer):
    table = inputs.table
    block = inputs.members[entry]
    players = _players_frame(table)
    frame = players.copy(deep=True)
    instant = datetime.strptime(inputs.capture.split("-")[-2], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    stamp = instant.isoformat().replace("+00:00", "Z")
    source = inputs.capture
    season = table["season"]
    deadline = (instant + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    recommendation = RecommendationInputs(
        source,
        stamp,
        season,
        GameweekDeadline(inputs.gameweek, deadline, False),
        players,
        pd.DataFrame(),
        published_gameweeks=frozenset(inputs.fixture_counts),
    )
    held = tuple(map(int, block["held"]))
    current = dict(zip(players.player_id, players.price_tenths, strict=True))
    sell = {int(key): int(value) for key, value in block["sell_tenths"].items()}
    # Static frozen prices need only the exact initial sale proceeds. Choose an
    # equivalent purchase basis, not a claim about unavailable historic purchases.
    purchase = {
        player: int(
            current[player]
            if sell[player] == current[player]
            else 2 * sell[player] - current[player]
        )
        for player in held
    }
    picks = EntryPicks(
        entry,
        season,
        inputs.gameweek - 1,
        held,
        held[:11],
        held[0],
        held[1],
        0 if scenario == "tight_bank" else int(block["bank_tenths"]),
        int(block["free_transfers"]),
        purchase_prices=purchase,
        purchase_prices_known=True,
        source_snapshot_id=source,
    )
    rules = table["rules"]
    financial = TransferRules(
        rules["squad_size"],
        rules["starting_size"],
        rules["max_players_per_team"],
        1000,
        rules["max_free_transfers"] - 1,
        None,
        0.5,
        False,
    )
    season_rules = SeasonRules(
        SEASON_RULES_CONTRACT_VERSION,
        season,
        source,
        ScoringNotUsed(),
        financial,
        tuple(
            ChipWindow(name, 1, 1, 38, "transfer" if name in ("wildcard", "freehit") else "team")
            for name in ("wildcard", "freehit", "3xc", "bboost")
        ),
    )
    context = AdviceRequestContext(
        "provisional_league_ui_v1",
        source,
        season,
        inputs.gameweek,
        frozen["projection_file_sha256"],
        producer,
        hashlib.sha256(f"frozen-api-replay:{source}:{entry}:{scenario}".encode()).hexdigest(),
    )

    def horizon_builder(weeks):
        call = window_call(inputs, entry, len(weeks)) if len(weeks) > 1 else None
        if call is not None:
            horizon = call.horizon.table.rename(columns={"buy_price_tenths": "price_tenths"})
        else:
            horizon = frame.assign(gameweek=weeks[0])
        horizon = horizon.copy(deep=True)
        horizon["fixture_count"] = [
            inputs.fixture_counts[int(week)].get(str(team), 0)
            for week, team in zip(horizon.gameweek, horizon.team_id, strict=True)
        ]
        horizon["home_fixture_count"] = 0  # Unused by this precomputed-point path.
        return ProjectionHorizon(
            horizon,
            season,
            source,
            frozen["projection"]["model_name"],
            frozen["projection"]["model_version"],
            frozen["projection"]["feature_contract_version"],
            "frozen_phase1_points_v1",
        )

    capture = AdviceCaptureContext(
        context,
        recommendation,
        Projection(frame, (), {}),
        season_rules,
        FrozenProvider(picks),
        horizon_builder,
    )
    assert not isinstance(capture.rules.scoring, ScoringRules)
    return capture, stamp


def bundles(held, chip):
    first, second, third = held[:3]
    choices = []
    for mask in range(4):
        patch = {"keep_players": sorted([third, *([first] if mask & 1 else [])])}
        if mask & 2:
            patch["avoid_players"] = [second]
        choices.append(
            dict(
                accepted=mask,
                applied=[*([0] if mask & 1 else []), *([1] if mask & 2 else []), 2],
                selection=dict(preferences=patch, chip=chip),
            )
        )
    legacy = dict(
        contract_version=BUNDLE_VERSION,
        program=None,
        slots=[
            dict(preferences=dict(keep_players=[first]), chip=chip),
            dict(preferences=dict(avoid_players=[second]), chip=chip),
        ],
        prices=[
            dict(outcome=0, ceiling=None),
            dict(outcome=1, ceiling=None),
            dict(outcome="skipped", ceiling=None),
        ],
        choices=choices,
    )
    priority = dict(
        contract_version=BUNDLE_VERSION,
        slots=[],
        prices=[],
        choices=[],
        program=dict(
            max_total_cost_tenths=15,
            preferences=[
                dict(rules=dict(keep_players=[first]), priority=1),
                dict(rules=dict(avoid_players=[second]), priority=2),
                dict(rules=dict(keep_players=[third]), priority=3),
            ],
        ),
    )
    return (("legacy_prices", legacy), ("priority_total", priority))


def compact_result(result):
    def component(row):
        if row is None:
            return None
        payload = row["payload"]
        return dict(
            status=row["status"],
            error_code=row["error_code"],
            expected_net_points=None
            if payload is None
            else sum(
                week["expected_points"] - week["transfer_hit_points"]
                for week in payload["plan_weeks"]
            ),
            decision_sha256=None
            if payload is None
            else hashlib.sha256(
                json.dumps(
                    payload["plan_weeks"],
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest(),
            priority=None if payload is None else payload.get("priority_preferences"),
        )

    return dict(
        components=[component(row) for row in result["components"]],
        selected=component(result["selected"]),
        applied=result["applied"],
        accepted=result["accepted"],
        budget_exhausted=result["budget_exhausted"],
    )


def measure_case(root, frozen, inputs, entry, scenario, window, producer):
    capture, stamp = make_capture(frozen, inputs, entry, scenario, producer)
    contexts = FrozenContexts(capture)
    cache, queue = FileAdviceCache(root / "answers"), FileJobQueue(root / "queue")
    specs, runs = FileAdviceJobSpecStore(root / "specs"), FileRunStore(root / "runs")
    held = tuple(map(int, inputs.members[entry]["held"]))
    roster = frozenset(int(player["id"]) for player in inputs.table["players"])
    league = inputs.table["league_id"]
    reader = AdviceReadStore(
        FrozenDirectory(inputs, entry),
        cache,
        contexts,
        {"saf-puan": False},
        capabilities=menu_capabilities(),
        llmopt_vnext=True,
        llmopt_vnext_three_week=True,
        preference_bundles=True,
        preference_players=lambda *_: PreferencePlayers(
            frozenset(held), roster, frozenset(capture.inputs.players.team_id)
        ),
        chip_availability=lambda *_: {entry: ("wildcard", "freehit", "3xc", "bboost")},
    )
    submit = AdviceSubmitService(reader, queue, specs=specs, runs=runs)
    app = create_app(
        advice_store=reader,
        advice_submit=submit,
        llmopt_vnext=reader.llmopt_vnext,
        llmopt_vnext_three_week=reader.llmopt_vnext_three_week,
        utc_now=lambda: datetime.fromisoformat(stamp),
    )
    compute = build_advice_compute(contexts, specs, cache=cache, runs=runs)
    route = f"/api/v1/leagues/{league}/entries/{entry}/advice"
    outsiders = sorted(roster - set(held))
    preferences = dict(net_points_priority=True, save_chips=True)
    if scenario == "conflicting_instructions":
        preferences.update(hold_transfers=True, include_players=[outsiders[0]])
    chip = scenario if scenario in ("wildcard", "freehit") else None
    if chip:
        preferences["save_chips"] = False
    rows = []
    with TestClient(app) as client:
        for mode, bundle in bundles(held, chip):
            run_id = hashlib.sha256(
                f"{inputs.gameweek}:{entry}:{window}:{mode}".encode()
            ).hexdigest()[:32]
            ref = dict(contract_version="llmopt_run_v1", run_id=run_id, stage="base")
            body = dict(strategy="saf-puan", window=window, preferences=preferences, run=ref)
            if chip:
                body["chip"] = chip
            base = client.post(route, json=body)
            main_cached = base.status_code == 200
            assert base.status_code in (200, 202), base.text
            if base.status_code == 202:
                assert run_advice_worker_once(
                    queue, cache, compute, at_utc=stamp, terminal_at_utc=lambda: stamp
                )
                main_job = queue.load(base.json()["job_id"])
                base = client.get(
                    route,
                    params=dict(
                        strategy="saf-puan",
                        window=window,
                        preferences=json.dumps(preferences),
                        **({"chip": chip} if chip else {}),
                    ),
                )
            else:
                main_job = None
            parent = None
            repeated = 0
            if base.status_code == 200:
                body = {**body, "run": {**ref, "stage": "followup"}, "preference_bundle": bundle}
                parent = client.post(route, json=body)
                assert parent.status_code in (200, 202), parent.text
                if parent.status_code == 202:
                    assert run_advice_worker_once(
                        queue, cache, compute, at_utc=stamp, terminal_at_utc=lambda: stamp
                    )
                    parent = client.post(route, json=body)
                assert parent.status_code == 200, parent.text
                before = len(queue.jobs())
                # Reconstruct API services while retaining the immutable collaborators.
                rebuilt = AdviceSubmitService(
                    reader, queue, specs=specs, runs=FileRunStore(root / "runs")
                )
                restarted = create_app(
                    advice_store=reader,
                    advice_submit=rebuilt,
                    llmopt_vnext=reader.llmopt_vnext,
                    llmopt_vnext_three_week=reader.llmopt_vnext_three_week,
                )
                with TestClient(restarted) as replay:
                    for _ in range(3):
                        repeated += 1
                        assert replay.post(route, json=body).status_code == 200
                assert len(queue.jobs()) == before
            with runs.transaction(at_utc=stamp) as tx:
                state = tx.state["runs"][run_id]
                ids = sorted(set(state["requests"].values()))
                jobs = [queue.load(identifier) for identifier in ids]
                assert all(job.contract_version == "backend_jobs_v2" for job in jobs)
                receipts = [tx.state["jobs"][identifier]["receipt"] for identifier in ids]
                allocations = [tx.state["jobs"][identifier]["limit"] for identifier in ids]
                reserved = state["reserved"]
            assert len(ids) <= 2
            if base.status_code == 200:
                main_status = base.json()["payload"].get("solver_status")
            else:
                assert main_job is not None and main_job.error is not None
                main_status = main_job.error.code
            rows.append(
                dict(
                    case=f"gw{inputs.gameweek}-{entry}",
                    scenario=scenario,
                    window=window,
                    mode=mode,
                    main_cache_hit=main_cached,
                    main_status=main_status,
                    expected_main_outcome=(
                        main_status == "PLAN_NOT_FOUND"
                        if scenario == "conflicting_instructions"
                        else base.status_code == 200
                    ),
                    admitted_server_jobs=len(ids),
                    reserved_units=reserved,
                    job_ids=ids,
                    terminal_statuses=[job.status for job in jobs],
                    receipts=receipts,
                    allocations=allocations,
                    within_allocation=all(
                        receipt["cp_used"] + receipt["native_reserved"] <= allocation
                        for receipt, allocation in zip(receipts, allocations, strict=True)
                    ),
                    repeated_requests=repeated,
                    extra_jobs_from_repeats=0,
                    result=None
                    if parent is None
                    else compact_result(parent.json()["payload"]["preference_bundle_result"]),
                )
            )
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/research/llmopt_phase3_jobs.json"
    )
    parser.add_argument(
        "--checkpoint", type=Path, default=ROOT / ".codex-tmp/p3-measure-progress.json"
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    producer = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    provenance = dict(
        producer_repository_commit=producer,
        llmopt_vnext=True,
        llmopt_vnext_three_week=True,
        source_sha256={path.as_posix(): digest(ROOT / path) for path in SOURCES},
        frozen_manifest_sha256=digest(ROOT / "docs/research/llmopt_phase1/inputs.json"),
    )
    original = json.loads((ROOT / "docs/research/llmopt_phase1_baseline.json").read_bytes())
    scenarios = {row["case"]: row["scenario"] for row in original["rows"]}
    rows, cases = [], 0
    if args.resume:
        previous = json.loads(args.checkpoint.read_bytes())
        if previous.get("provenance") != provenance:
            raise ValueError("Checkpoint code, producing commit or frozen inputs changed.")
        rows, cases = previous["rows"], previous["completed_member_weeks"]
        if type(cases) is not int or not 0 <= cases <= 20 or len(rows) != cases * 4:
            raise ValueError("The checkpoint does not contain complete member-weeks.")
        if any(not row["expected_main_outcome"] or not row["within_allocation"] for row in rows):
            raise ValueError("A failed checkpoint cannot be resumed as acceptance evidence.")
    skip = cases
    visited = 0
    with TemporaryDirectory(prefix="lp3-api-") as directory:
        for frozen, inputs in benchmark.snapshots():
            for entry in sorted(inputs.members):
                visited += 1
                if visited <= skip:
                    continue
                if args.limit is not None and cases >= args.limit:
                    break
                case = f"gw{inputs.gameweek}-{entry}"
                for window in (1, 3):
                    measured = measure_case(
                        Path(directory) / f"{case}-{window}",
                        frozen,
                        inputs,
                        entry,
                        scenarios[case],
                        window,
                        producer,
                    )
                    rows.extend(measured)
                    print(
                        f"{case} window={window} "
                        + " ".join(
                            f"{row['mode']}={row['admitted_server_jobs']}:{row['main_status']}"
                            for row in measured
                        ),
                        flush=True,
                    )
                cases += 1
                args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
                pending = args.checkpoint.with_suffix(".tmp")
                pending.write_text(
                    json.dumps(
                        dict(
                            provenance=provenance,
                            completed_member_weeks=cases,
                            rows=rows,
                        ),
                        indent=2,
                        allow_nan=False,
                    )
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                pending.replace(args.checkpoint)
                if any(
                    not row["expected_main_outcome"] or not row["within_allocation"]
                    for row in rows[-4:]
                ):
                    raise RuntimeError(
                        f"{case} failed its outcome or work contract; see {args.checkpoint}."
                    )
    report = dict(
        contract_version="llmopt_phase3_jobs_v1",
        **provenance,
        member_weeks=cases,
        windows=[1, 3],
        maximum_server_jobs=max(row["admitted_server_jobs"] for row in rows),
        all_expected_main_outcomes=all(row["expected_main_outcome"] for row in rows),
        all_work_within_allocation=all(row["within_allocation"] for row in rows),
        live_network_requests=0,
        execution=(
            "Sequential local API and real worker; frozen precomputed points, no scoring, "
            "forecasting, live requests or concurrent tests. Total arm reuses the completed "
            "main answer when feasible."
        ),
        rows=rows,
    )
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
