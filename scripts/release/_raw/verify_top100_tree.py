"""Check a league tree's Top 100 menu member by member: local (a directory) or live (a URL).

usage: verify_top100_tree.py <tree root containing league/ | https://host>
"""

import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, r"C:\Users\ertug\Desktop\football-squad-optimizer\src")
from squadopt.application.strategies.catalog import (  # noqa: E402
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
)

ROOT = sys.argv[1]
LIVE = ROOT.startswith("http")
UA = {"User-Agent": "squadopt-verify/1.0"}
LIMIT = re.compile(
    r"^The plan was chosen with the Top 100 influence at (\d+); every expected-points "
    r"number in this document is the base model's, without it\.$"
)


def read(relative: str):
    if LIVE:
        request = urllib.request.Request(f"{ROOT}/data/league/{relative}", headers=UA)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise
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


problems: list[str] = []
changed = defaultdict(int)
costs = defaultdict(list)
statuses = defaultdict(lambda: defaultdict(int))
reasons = defaultdict(int)
files = 0
members = read("members.json")["payload"]["members"]
humans = [m["entry_id"] for m in members if m.get("member_kind") == "human"]
for entry in humans:
    index = read(f"advice/{entry}/index.json")
    if index is None:
        problems.append(f"{entry}: no index")
        continue
    menu = index["payload"].get("top100")
    if not menu or not menu.get("available"):
        problems.append(f"{entry}: menu unavailable {menu}")
        continue
    base = read(f"advice/{entry}/saf-puan/1.json")
    if base is None or "top100" in base["payload"]:
        problems.append(f"{entry}: baseline missing or carries top100")
    word_on = index["payload"].get("evidence", {}).get("available") is True
    for label, paths, word in (("plain", menu["paths"], False), ("word", menu["word_paths"], True)):
        if word and not word_on and paths:
            problems.append(f"{entry}: word paths without the word")
        for weight in ("5", "10", "20", "30", "40", "50"):
            path = paths.get(weight)
            expected = f"advice/{entry}/saf-puan/1/top100-{weight}{'-hoca-sozu' if word else ''}.json"
            if path is None:
                if word_on or not word:
                    problems.append(f"{entry}: {label} {weight} missing")
                continue
            if path != expected:
                problems.append(f"{entry}: {label} {weight} path {path}")
            document = read(path)
            if document is None:
                problems.append(f"{entry}: {path} not published")
                continue
            files += 1
            payload = document["payload"]
            walk(payload, path, problems)
            top100 = payload.get("top100") or {}
            if top100.get("weight") != int(weight):
                problems.append(f"{entry}: {path} weight {top100.get('weight')}")
            if ("evidence" in payload) != word:
                problems.append(f"{entry}: {path} evidence presence wrong")
            cost = payload.get("expected_points_cost")
            ceiling = payload.get("expected_points_cost_ceiling")
            if not isinstance(cost, (int, float)) or cost < 0 or ceiling is None or ceiling < cost - 1e-9:
                problems.append(f"{entry}: {path} cost {cost} ceiling {ceiling}")
            limits = payload.get("stated_limits") or []
            if not limits or not LIMIT.match(limits[-1]) or LIMIT.match(limits[-1]).group(1) != weight:
                problems.append(f"{entry}: {path} stated limit {limits[-1:]}")
            if any(str(k).startswith("_") for k in payload):
                problems.append(f"{entry}: {path} private key")
            for move in payload.get("moves", []):
                reasons[(label, move.get("reason_code"))] += 1
            statuses[label][payload.get("solver_status")] += 1
            if not word:
                changed[int(weight)] += bool(top100.get("changed"))
                costs[int(weight)].append(cost)

print(f"members {len(humans)}, weighted documents {files}")
for weight in sorted(changed) or sorted(costs):
    values = costs[weight]
    print(
        f"  weight {weight:>2}: changed {changed[weight]}/{len(values)}, "
        f"mean price {sum(values) / len(values):.3f}, max {max(values):.3f}"
    )
print(f"  solver status {dict((k, dict(v)) for k, v in statuses.items())}")
print(f"  move reasons {dict(reasons)}")
print(f"\n{'ALL GOOD' if not problems else str(len(problems)) + ' PROBLEM(S)'}")
for problem in problems[:40]:
    print("  " + problem)
sys.exit(1 if problems else 0)
