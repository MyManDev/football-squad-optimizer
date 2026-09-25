"""Check a published league tree using the three release checks from the tooling seed."""

import argparse
import json
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN, FORBIDDEN_TEXT_PATTERN

LIMIT = re.compile(
    r"^The plan was chosen with the Top 100 influence at (\d+); every expected-points "
    r"number in this document is the base model's, without it\.$"
)
QUOTE_FORBIDDEN = re.compile(
    r"%|per\s?cent|percentage|probabilit|olas\u0131l|\bP\(|chance|likelihood|odds|quantile|spread"
    r"|\btail\b|ihtimal|şans|yüzde(?!n\b)|kantil|yay\u0131l\u0131m|\bkuyruk\b"
    r"|\b50\s*[-/]\s*50\b|fifty[\s-]fifty",
    re.IGNORECASE,
)


class Tree:
    def __init__(self, root: str) -> None:
        self.root = root.rstrip("/")
        self.live = self.root.startswith(("https://", "http://"))
        self.word_files: dict[str, str] = {}

    def read(self, relative: str) -> Any:
        if self.live:
            request = urllib.request.Request(
                f"{self.root}/data/league/{relative}",
                headers={"User-Agent": "squadopt-verify/1.0"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                raise
        else:
            path = Path(self.root) / "league" / relative
            if not path.is_file():
                return None
            raw = path.read_text(encoding="utf-8")
        if self.live and relative.endswith("/hoca-sozu.json"):
            self.word_files[relative] = raw
        try:
            return json.loads(raw)
        except ValueError as error:
            if self.live:
                return None
            raise ValueError(f"{path} exists and does not parse as JSON") from error


def walk(node: object, where: str, problems: list[str]) -> None:
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


def price_problem(payload: dict[str, Any]) -> str | None:
    """What is wrong with a priced document's price and ceiling, or None.

    The price is never negative. Its ceiling is the price itself when the pure-points plan
    it is measured against was proven, and absent when that plan was found without a
    proof: the solver's bound is on its objective and bounds no price. A document with no
    control of its own (the manager's word that binds nobody) is its own anchor.
    """

    cost = payload.get("expected_points_cost")
    ceiling = payload.get("expected_points_cost_ceiling")
    if not isinstance(cost, (int, float)) or cost < 0:
        return f"cost {cost} ceiling {ceiling}"
    anchor = payload.get("control_solver_status") or payload.get("solver_status")
    if anchor == "FEASIBLE":
        return None if ceiling is None else f"ceiling {ceiling} over an unproven control"
    if not isinstance(ceiling, (int, float)) or abs(ceiling - cost) > 1e-9:
        return f"cost {cost} ceiling {ceiling}"
    return None


def check_variants(read: Callable[[str], Any]) -> list[str]:
    problems: list[str] = []
    kinds: Counter[tuple[str, int, bool]] = Counter()
    statuses: Counter[tuple[int, str | None]] = Counter()
    ceilings: dict[int, list[float]] = {}
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
        targets = [
            (d["path"], d["strategy"], d["window"], d["rival_entry_id"], d["weight"])
            for d in documents
        ]
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
            if (
                p["mode"],
                p["window"],
                p.get("rival_entry_id"),
                (p.get("top100") or {}).get("weight", 0),
            ) != (
                strategy,
                window,
                rival_id,
                weight,
            ):
                problems.append(f"{entry}: {path} identity mismatch")
            ceiling = p.get("expected_points_cost_ceiling")
            price = price_problem(p)
            if price is not None:
                problems.append(f"{entry}: {path} {price}")
            elif ceiling is not None:
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
        print(
            f"  window {window}: ceiling mean {sum(values) / len(values):.2f}, "
            f"max {max(values):.2f}"
        )
    print(f"\n{'ALL GOOD' if not problems else str(len(problems)) + ' PROBLEM(S)'}")
    for problem in problems[:40]:
        print("  " + problem)

    return problems


def check_top100(read: Callable[[str], Any]) -> list[str]:
    problems: list[str] = []
    changed: defaultdict[int, int] = defaultdict(int)
    costs: defaultdict[int, list[float]] = defaultdict(list)
    statuses: defaultdict[str, defaultdict[str | None, int]] = defaultdict(lambda: defaultdict(int))
    reasons: defaultdict[tuple[str, str | None], int] = defaultdict(int)
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
        for label, paths, word in (
            ("plain", menu["paths"], False),
            ("word", menu["word_paths"], True),
        ):
            if word and not word_on and paths:
                problems.append(f"{entry}: word paths without the word")
            for weight in ("5", "10", "20", "30", "40", "50"):
                path = paths.get(weight)
                expected = (
                    f"advice/{entry}/saf-puan/1/top100-{weight}{'-hoca-sozu' if word else ''}.json"
                )
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
                price = price_problem(payload)
                if price is not None:
                    problems.append(f"{entry}: {path} {price}")
                limits = payload.get("stated_limits") or []
                limit = LIMIT.match(limits[-1]) if limits else None
                if limit is None or limit.group(1) != weight:
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
    for weight_value in sorted(changed) or sorted(costs):
        values = costs[weight_value]
        print(
            f"  weight {weight_value:>2}: changed {changed[weight_value]}/{len(values)}, "
            f"mean price {sum(values) / len(values):.3f}, max {max(values):.3f}"
        )
    print(f"  solver status {dict((k, dict(v)) for k, v in statuses.items())}")
    print(f"  move reasons {dict(reasons)}")
    print(f"\n{'ALL GOOD' if not problems else str(len(problems)) + ' PROBLEM(S)'}")
    for problem in problems[:40]:
        print("  " + problem)

    return problems


def check_word(tree: Tree) -> list[str]:
    read = tree.read
    problems: list[str] = []

    def check(ok: object, label: str) -> None:
        print(f"  {'ok ' if ok else 'BAD'} {label}")
        if not ok:
            problems.append(label)

    members = read("members.json")["payload"]["members"]
    humans = [m for m in members if m.get("member_kind") == "human"]
    print(f"members: {len(members)} ({len(humans)} human)")
    available = 0
    binding = 0
    withheld = 0
    shown = 0
    for member in humans:
        entry = member["entry_id"]
        advice_dir = f"advice/{entry}"
        index = read(f"{advice_dir}/index.json")["payload"]
        evidence = index.get("evidence")
        if not isinstance(evidence, dict):
            check(False, f"{entry}: index has no evidence entry")
            continue
        word_file = f"{advice_dir}/saf-puan/1/hoca-sozu.json"
        word_exists = (
            read(word_file) is not None
            if tree.live
            else (Path(tree.root) / "league" / word_file).is_file()
        )
        if not evidence.get("available"):
            check(
                not word_exists,
                f"{entry}: unavailable ({evidence.get('reason')}) and no file",
            )
            continue
        available += 1
        check(
            evidence.get("path") == f"advice/{entry}/saf-puan/1/hoca-sozu.json",
            f"{entry}: index path",
        )
        check(word_exists, f"{entry}: hoca-sozu.json exists")
        doc = read(word_file)["payload"]
        base = read(f"{advice_dir}/saf-puan/1.json")["payload"]
        ev = doc.get("evidence") or {}
        check(doc.get("mode") == "saf-puan" and doc.get("window") == 1, f"{entry}: saf-puan/1")
        check(ev.get("binding") == evidence.get("binding"), f"{entry}: binding agrees with index")
        check(
            len(ev.get("applied", [])) == evidence.get("applied_count"),
            f"{entry}: applied count agrees",
        )
        cost = float(doc.get("expected_points_cost", -1))
        price = price_problem(doc)
        check(price is None, f"{entry}: price {cost:.2f} ({price or 'ceiling agrees'})")
        if ev.get("binding"):
            binding += 1
            check(len(ev.get("applied", [])) > 0, f"{entry}: binding word shows its statements")
        else:
            check(cost == 0.0, f"{entry}: non-binding word costs nothing")
            check(
                doc.get("captain") == base.get("captain"), f"{entry}: non-binding keeps the captain"
            )
        barred = {a["player_id"] for a in ev.get("applied", []) if a.get("role")}
        not_starting = {
            a["player_id"] for a in ev.get("applied", []) if a.get("role") == "not_starting"
        }
        eleven = {p["player_id"] for p in doc.get("starting_xi") or []}
        check(not (eleven & not_starting), f"{entry}: nobody benched by the word starts")
        captain = (doc.get("captain") or {}).get("player_id")
        vice = (doc.get("vice_captain") or {}).get("player_id")
        check(captain not in barred and vice not in barred, f"{entry}: armband and vice not barred")
        for item in ev.get("applied", []):
            status = item.get("words_status")
            if status == "withheld_figure":
                withheld += 1
                check(item.get("words") is None, f"{entry}: withheld quote carries no words")
            elif item.get("words"):
                shown += 1
                check(not QUOTE_FORBIDDEN.search(item["words"]), f"{entry}: shown quote is clean")
        for move in doc.get("moves", []):
            check(
                move.get("reason_code") in {"points_gain", "manager_word"},
                f"{entry}: move reason {move.get('reason_code')}",
            )

    print(
        f"\navailable {available}/{len(humans)}, binding {binding}, quotes shown {shown}, "
        f"withheld {withheld}"
    )

    word_files = (
        tree.word_files
        if tree.live
        else {
            path.relative_to(Path(tree.root)).as_posix(): path.read_text(encoding="utf-8")
            for path in Path(tree.root).rglob("hoca-sozu.json")
        }
    )
    hits = [
        path
        for path, text in word_files.items()
        if "80%" in text or re.search(r"per\s?cent", text, re.IGNORECASE)
    ]
    check(not hits, f"no switched-on file carries the figure ({hits[:3]})")
    print("\nALL GOOD" if not problems else f"\n{len(problems)} FAILURE(S)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="Directory containing league/, or the site's origin URL.")
    args = parser.parse_args(argv)
    tree = Tree(args.root)
    if not tree.live and not (Path(tree.root) / "league" / "members.json").is_file():
        print(
            f"Missing {Path(tree.root) / 'league' / 'members.json'}; "
            "pass the directory containing league/, such as <preview>/data."
        )
        return 1
    findings = []
    checks: tuple[tuple[str, Callable[[], list[str]]], ...] = (
        ("variants", lambda: check_variants(tree.read)),
        ("top100", lambda: check_top100(tree.read)),
        ("word", lambda: check_word(tree)),
    )
    for name, check in checks:
        print(f"Checking {name}")
        try:
            findings.extend(check())
        except (OSError, ValueError, KeyError, TypeError) as error:
            findings.append(f"{name}: unreadable tree: {error}")
            print(findings[-1])
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
