"""Serve a genuine frozen one-week planning page and worker exclusively on loopback."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from threading import Event
from time import monotonic, perf_counter, sleep

import uvicorn
from docs.research.llmopt_phase8.measure import (
    ROOT,
    complete,
    frozen_documents,
    publication,
    runtime,
)
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from squadopt.platform.advice_worker import DEFAULT_IDLE_SECONDS
from squadopt.platform.contributions import ContributionStore

HERE = ROOT / "docs/research/llmopt_week_first"
BUILD = ROOT / ".codex-tmp/week-first-web"
PORT = 8818
ORIGIN = f"http://127.0.0.1:{PORT}"


@lru_cache(maxsize=64)
def archived(commit, name):
    result = subprocess.run(
        ["git", "show", f"{commit}:web/public/data/{name}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if not result.returncode else None


def browser_replay(root, frozen, inputs, entry, enabled, producer):
    """Each arm gets a fresh browser process, real filesystem stores and a serial worker."""
    commit = frozen["source_commit"]
    _, squad = frozen_documents(frozen, inputs, entry)
    root.mkdir(parents=True)
    (root / "players.json").write_bytes(archived(commit, "players.json"))
    local = runtime(
        root,
        frozen,
        inputs,
        entry,
        enabled,
        False,
        producer,
        data_root=root,
        contributions=ContributionStore(root / "contributions.sqlite"),
    )
    members = publication(commit, "members")
    fixtures = json.loads(archived(commit, "fixtures.json"))["payload"]
    deadline = next(row for row in fixtures["gameweeks"] if row["gameweek"] == squad["gameweek"])
    held = inputs.members[entry]["held"]
    case = f"gw{inputs.gameweek}-{entry}"
    initial = {
        "origin": ORIGIN,
        "case": case,
        "entryId": entry,
        "leagueId": members["league_id"],
        "asOfUtc": local.stamp,
        "deadline": deadline["deadline_utc"],
        "window": 1,
        "enabled": enabled,
        "managerName": squad["entry"]["manager_name"],
        "teamName": squad["entry"]["team_name"],
        "leagueName": members["league_name"],
        "draft": {
            "window": 1,
            "hard": [],
            "soft": [
                {"kind": "keep_player", "player_id": held[0]},
                {"kind": "keep_player", "player_id": held[1]},
                {"kind": "no_hits"},
            ],
        },
    }
    app = local.app
    passes = []
    boundaries = {}
    jobs = []
    stop = Event()

    @app.post("/__measurement/pass/{cache}")
    def measure_pass(cache: str):
        if [*passes, cache] not in (["cold"], ["cold", "warm"]):
            raise HTTPException(409)
        boundaries[cache] = perf_counter()
        passes.append(cache)
        return {"cache": cache}

    @app.get("/data/{path:path}")
    def frozen_data(path: str):
        if not path.endswith(".json") or any(p in ("", ".", "..") for p in path.split("/")):
            raise HTTPException(404)
        data = archived(commit, path)
        if data is None:
            raise HTTPException(404)
        return Response(data, media_type="application/json")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith(("api/", "__measurement/")):
            raise HTTPException(404)
        asset = (BUILD / path).resolve()
        if not asset.is_relative_to(BUILD):
            raise HTTPException(404)
        if asset.is_file():
            return FileResponse(asset)
        if path.startswith("league/") or not path:
            return FileResponse(BUILD / "index.html")
        raise HTTPException(404)

    def work():
        while not stop.is_set():
            if not (local.queue.enqueued.keys() - local.queue.claimed.keys()):
                stop.wait(DEFAULT_IDLE_SECONDS)
                continue
            if not passes:
                raise ValueError("A browser job was opened before confirming the first draft.")
            job = complete(local.queue, local.cache, local.compute, local.runs, local.stamp, "")
            queued = local.queue.load(job["job_id"])
            spec = local.specs.get(queued.cache_key)
            prefs = json.loads(spec.switch("preferences").get("value", "{}"))
            job["preferences"] = prefs
            price_rules = len(prefs.get("keep_players", ())) + int(bool(prefs.get("no_hits")))
            job["stage"] = {0: "base", 1: "individual_prices"}.get(price_rules, "combined")
            jobs.append(job)

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error", access_log=False)
    )
    with ThreadPoolExecutor(max_workers=2) as threads:
        serving = threads.submit(server.run)
        working = threads.submit(work)
        try:
            timeout = monotonic() + 15
            while not server.started:
                if serving.done():
                    serving.result()
                    raise RuntimeError("Local server stopped before listening.")
                if monotonic() >= timeout:
                    raise RuntimeError("Local server did not start.")
                sleep(0.02)
            process = subprocess.run(
                ["node", str(HERE / "first_plan.mjs")],
                input=json.dumps(initial),
                capture_output=True,
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                timeout=300,
            )
            if process.returncode:
                raise RuntimeError(f"{case}/{enabled}: {process.stderr}")
            observed = json.loads(process.stdout)
        finally:
            stop.set()
            server.should_exit = True
            working.result()
            serving.result()
    if passes != ["cold", "warm"] or set(local.queue.enqueued) != {j["job_id"] for j in jobs}:
        raise ValueError("Browser pass boundaries or server publication counts disagree.")
    for job in jobs:
        published_at = local.queue.enqueued[job["job_id"]]
        if published_at < boundaries["cold"]:
            raise ValueError("The browser opened a job before the first measurement boundary.")
        job["cache_pass"] = "warm" if published_at >= boundaries["warm"] else "cold"
    for cache in passes:
        result = observed[cache]
        result["jobs"] = [j for j in jobs if j["cache_pass"] == cache]
        if not 0 < result["first_visible_seconds"] <= result["total_seconds"]:
            raise ValueError(f"{case}/{enabled}/{cache}: bad visible timeline: {result}")
    return {"case": case, "window": 1, "release": "mixed" if enabled else "off", **observed}
