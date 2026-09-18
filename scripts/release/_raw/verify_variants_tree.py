"""Check the wider menu in a league tree: local directory (containing league/) or live URL."""

import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"C:\Users\ertug\Desktop\football-squad-optimizer\src")
from squadopt.application.strategies.catalog import (  # noqa: E402
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
)

ROOT = sys.argv[1]
LIVE = ROOT.startswith("http")


def read(relative):
    if LIVE:
        request = urllib.request.Request(
            f"{ROOT}/data/league/{relative}", headers={"User-Agent": "squadopt-verify/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
        try:
            return json.loads(body)
        except ValueError:
            return None
    path = Path(ROOT) / "league" / relative
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def walk(node, where, problems):
    if isinstance(node, dict):
        for key, value in node.items():
            if FORBIDDEN_FIELD_PATTERN.search(str(key)):
                problems.append(f"{where}: forbidden key {key}")
            walk(value, f"{where}.{key}", problems)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, f"{where}[{index}]", problems)
    elif isinstance(node, str) and FORBIDDEN_TEXT_PATTERN.search(node):
        problems.append(f"{where}: forbidden text {node[:80]!r}")


problems = []
kinds = Counter()
statuses = Counter()
ceilings = {}
members = read("members.json")["payload"]["members"]
humans = [m["entry_id"] for m in members if m.get("member_kind") == "human"]
for entry in humans:
    index = read(f"advice/{entry}/index.json")["payload"]
    rival = index["default_rival_entry_id"]
    menu = index.get("top100") or {}
    documents = menu.get("documents") or []
    expected = {("saf-puan", w, None, s) for w in (3, 5) for s in (5, 10, 20, 30, 40, 50)}
    if rival is not None:
        expected |= {
            (st, w, rival, s)
            for st in ("ortak-koru", "fark-yarat")
            for w in (1, 3, 5)
            for s in (5, 10, 20, 30, 40, 50)
        }
    got = {(d["strategy"], d["window"], d["rival_entry_id"], d["weight"]) for d in documents}
    for missing in sorted(expected - got, key=str):
        problems.append(f"{entry}: no document for {missing}")
    for strategy in ("ortak-koru", "fark-yarat"):
        if rival is not None and index["windows"].get(strategy) != [1, 3, 5]:
            problems.append(f"{entry}: {strategy} windows {index['windows'].get(strategy)}")
    targets = [(d["path"], d["strategy"], d["window"], d["rival_entry_id"], d["weight"]) for d in documents]
    targets += [
        (row["path"], row["strategy"], row["window"], row["rival_entry_id"], 0)
        for row in index["computed"]
        if row.get("window") in (3, 5)
    ]
    for path, strategy, window, rival_id, weight in targets:
        document = read(path)
        if document is None:
            problems.append(f"{entry}: {path} not published")
            continue
        p = document["payload"]
        walk(p, path, problems)
        kinds[(strategy, window, bool(weight))] += 1
        statuses[(window, p.get("solver_status"))] += 1
        if (p["mode"], p["window"], p.get("rival_entry_id"), (p.get("top100") or {}).get("weight", 0)) != (
            strategy, window, rival_id, weight,
        ):
            problems.append(f"{entry}: {path} identity mismatch")
        cost, ceiling = p.get("expected_points_cost"), p.get("expected_points_cost_ceiling")
        if cost is None or ceiling is None or cost < 0 or ceiling < cost - 1e-9:
            problems.append(f"{entry}: {path} cost {cost} ceiling {ceiling}")
        else:
            ceilings.setdefault(window, []).append(ceiling)
        if window > 1 and len(p.get("plan_weeks") or []) != window:
            problems.append(f"{entry}: {path} plan_weeks")
        if weight and p.get("optimality_gap") is not None:
            problems.append(f"{entry}: {path} publishes a weighted gap")
        if any(str(k).startswith("_") for k in p):
            problems.append(f"{entry}: {path} private key")

print(f"members {len(humans)}; documents by kind:")
for key, count in sorted(kinds.items(), key=str):
    print("  ", key, count)
print("status by window:", dict(statuses))
for window, values in sorted(ceilings.items()):
    print(f"  window {window}: ceiling mean {sum(values)/len(values):.2f}, max {max(values):.2f}")
print(f"\n{'ALL GOOD' if not problems else str(len(problems)) + ' PROBLEM(S)'}")
for problem in problems[:40]:
    print("  " + problem)
sys.exit(1 if problems else 0)
