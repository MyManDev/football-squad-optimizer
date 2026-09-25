"""Check a published league tree using the three release checks from the tooling seed.

Each check expects what each member's advice index declares. An absence the index states
in the producer's own shape, with a string reason (a menu this run left out, a window or
rival pair that did not solve, a member with no advice this week), is reported and is not
a finding; a document the index names that the tree lacks is, and so is an index the
page's validator would refuse or an absence stated without its reason.
"""

import argparse
import json
import math
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
#: The pure-points strategy, whose longer windows need no rival.
PURE = "saf-puan"
#: The Top 100 weights beyond the published plan (``TOP100_WEIGHTS`` without zero). The
#: page offers each of them wherever the index names its file, whatever else it lists.
MENU_WEIGHTS = (5, 10, 20, 30, 40, 50)
#: The keys of the index the producer writes for a member it could not advise
#: (``_refused_member_index`` in ``squadopt.application.league_views``), and no others.
REFUSED_INDEX_KEYS = frozenset(
    {
        "league_id",
        "season",
        "gameweek",
        "entry_id",
        "window",
        "windows",
        "strategies",
        "rival_entry_ids",
        "default_rival_entry_id",
        "suggested_strategy",
        "computed",
        "unavailable",
    }
)
#: ``Number.MAX_SAFE_INTEGER``, the page's bound on an id.
MAX_SAFE_INTEGER = 2**53 - 1


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


def _number(value: object) -> bool:
    """A JSON number: ``typeof value === "number"`` on the page."""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive(value: object) -> bool:
    """``Number.isSafeInteger(value) && value > 0``, as the page reads an id."""

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value).is_integer()
        and 0 < value <= MAX_SAFE_INTEGER
    )


def _window(value: object) -> bool:
    return _number(value) and value in (1, 3, 5)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def page_refusal(index: object, entry: int) -> str | None:
    """What the page's ``assertAdviceIndex`` refuses in this index, or None when it would not.

    A port of ``web/src/features/league/publicationShape.ts``: an index the page throws on
    is a member page that shows an error, so the checker must not pass it either.
    """

    if not isinstance(index, dict):
        return "not an object"
    strategies = index.get("strategies")
    rivals = index.get("rival_entry_ids")
    computed = index.get("computed")
    unavailable = index.get("unavailable")
    windows = index.get("windows", {})
    checks = (
        ("entry_id", _number(index.get("entry_id")) and index.get("entry_id") == entry),
        ("league_id", _positive(index.get("league_id"))),
        ("gameweek", _positive(index.get("gameweek"))),
        ("season", isinstance(index.get("season"), str)),
        ("window", _window(index.get("window"))),
        (
            "strategies",
            isinstance(strategies, list) and all(isinstance(s, str) for s in strategies),
        ),
        ("rival_entry_ids", isinstance(rivals, list) and all(_positive(r) for r in rivals)),
        (
            "default_rival_entry_id",
            "default_rival_entry_id" in index
            and (
                index["default_rival_entry_id"] is None
                or _positive(index["default_rival_entry_id"])
            ),
        ),
        (
            "computed",
            isinstance(computed, list)
            and all(
                isinstance(row, dict)
                and isinstance(row.get("strategy"), str)
                and _positive(row.get("rival_entry_id"))
                and ("window" not in row or _window(row["window"]))
                and row.get("path")
                == (
                    f"advice/{entry}/{row['strategy']}/{int(row.get('window', 1))}"
                    f"/vs-{int(row['rival_entry_id'])}.json"
                )
                for row in computed
            ),
        ),
        (
            "unavailable",
            isinstance(unavailable, list)
            and all(
                isinstance(row, dict)
                and isinstance(row.get("strategy"), str)
                and isinstance(row.get("reason"), str)
                and "rival_entry_id" in row
                and (row["rival_entry_id"] is None or _positive(row["rival_entry_id"]))
                and ("window" not in row or _window(row["window"]))
                for row in unavailable
            ),
        ),
        (
            "windows",
            isinstance(windows, dict)
            and all(
                isinstance(items, list) and all(_window(w) for w in items)
                for items in windows.values()
            ),
        ),
    )
    for field, ok in checks:
        if not ok:
            return field
    suggestion = index.get("suggested_strategy")
    if suggestion is not None and not (
        isinstance(suggestion, dict)
        and suggestion.get("strategy") in ("saf-puan", "ortak-koru", "fark-yarat")
        and isinstance(suggestion.get("rule_id"), str)
        and suggestion.get("band") in ("behind", "level", "ahead")
        and _positive(suggestion.get("rival_entry_id"))
        and _finite(suggestion.get("points_ahead_of_rival"))
        and _positive(suggestion.get("scored_gameweek"))
        and _finite(suggestion.get("gameweeks_remaining"))
        and _finite(suggestion.get("band_edge_points"))
    ):
        return "suggested_strategy"
    return None


def member_index(read: Callable[[str], Any], entry: int) -> tuple[dict[str, Any] | None, str]:
    """A member's advice index, or the finding that keeps every check from reading it."""

    envelope = read(f"advice/{entry}/index.json")
    if envelope is None:
        return None, f"{entry}: no index"
    index = envelope.get("payload") if isinstance(envelope, dict) else None
    refused_field = page_refusal(index, entry)
    if refused_field is not None:
        return None, f"{entry}: index the page refuses ({refused_field})"
    assert isinstance(index, dict)
    return index, ""


def refusal(index: dict[str, Any]) -> str | None:
    """The reason a refused member's index states, or None when it is not one.

    Recognised only in the exact shape the producer writes for a member it could not
    advise (``_refused_member_index``): its keys and no others, the pure-points strategy
    first, no window named for any strategy, nothing computed, no suggestion, and one
    ``unavailable`` row per strategy with no rival and the same string reason.
    """

    strategies = index.get("strategies")
    rows = index.get("unavailable")
    if (
        set(index) != REFUSED_INDEX_KEYS
        or not isinstance(strategies, list)
        or not strategies
        or strategies[0] != PURE
        or len(set(strategies)) != len(strategies)
        or not isinstance(rows, list)
        or not rows
        or not isinstance(rows[0], dict)
    ):
        return None
    reason = rows[0].get("reason")
    if (
        not isinstance(reason, str)
        or index["window"] != 1
        or index["windows"] != {strategy: [] for strategy in strategies}
        or index["computed"] != []
        or index["suggested_strategy"] is not None
        or rows
        != [
            {"strategy": strategy, "rival_entry_id": None, "reason": reason}
            for strategy in strategies
        ]
    ):
        return None
    return reason


def stated_unavailable(index: dict[str, Any]) -> dict[tuple[str, int, int | None], str]:
    """Every (strategy, window, rival) the index says did not solve, with its reason.

    A row without a window is the one-week pair, as the producer writes it and the page
    reads it. ``page_refusal`` has already refused any row without a string strategy and
    reason, so every row here states its reason.
    """

    return {
        (row["strategy"], row.get("window", 1), row["rival_entry_id"]): row["reason"]
        for row in index["unavailable"]
    }


def menu_absence(menu: object) -> str | None:
    """The reason a Top 100 menu the index states absent gives, or None when it is not so
    stated: ``available`` false and a string reason, the producer's shape and nothing else.
    """

    if isinstance(menu, dict) and menu.get("available") is False:
        reason = menu.get("reason")
        if isinstance(reason, str):
            return reason
    return None


def print_absences(absences: list[tuple[int, str]]) -> None:
    """Name what the indexes say is absent, one line per statement; none of it is a finding."""

    grouped: defaultdict[str, list[int]] = defaultdict(list)
    for entry, statement in absences:
        grouped[statement].append(entry)
    for statement, entries in sorted(grouped.items()):
        members = ", ".join(str(entry) for entry in entries)
        print(f"  stated absence, {len(entries)} member(s): {statement} ({members})")


def check_variants(read: Callable[[str], Any]) -> list[str]:
    problems: list[str] = []
    absences: list[tuple[int, str]] = []
    kinds: Counter[tuple[str, int, bool]] = Counter()
    statuses: Counter[tuple[int, str | None]] = Counter()
    ceilings: dict[int, list[float]] = {}
    members = read("members.json")["payload"]["members"]
    humans = [m["entry_id"] for m in members if m.get("member_kind") == "human"]
    for entry in humans:
        index, finding = member_index(read, entry)
        if index is None:
            problems.append(finding)
            continue
        refused = refusal(index)
        if refused is not None:
            absences.append((entry, f"no advice this week: {refused}"))
            continue
        rival = index["default_rival_entry_id"]
        windows = index.get("windows") or {}
        stated = stated_unavailable(index)
        for (strategy, window, rival_id), reason in stated.items():
            against = f" vs {rival_id}" if rival_id is not None else ""
            absences.append((entry, f"{strategy} window {window}{against} not solved: {reason}"))
        # Every pure-points window the index names has its file, the one-week plan every
        # member is shown included, whatever the menu and the word say; a member with
        # advice always has that one.
        pure_windows = windows.get(PURE, [])
        if 1 not in pure_windows:
            problems.append(f"{entry}: index names no one-week {PURE} window")
        for window in pure_windows:
            if read(f"advice/{entry}/{PURE}/{window}.json") is None:
                problems.append(f"{entry}: advice/{entry}/{PURE}/{window}.json not published")
        # The longer pure-points windows, and, against the default rival, every rival
        # strategy's windows: the menu is built from these and nothing else.
        longer = [window for window in pure_windows if window != 1]
        strategies = [s for s in index["strategies"] if s != PURE] if rival is not None else []
        rival_windows = {
            strategy: [1, *(w for w in windows.get(strategy, []) if w != 1)]
            for strategy in strategies
        }
        for strategy in strategies:
            for window in longer:
                if (
                    window not in rival_windows[strategy]
                    and (strategy, window, rival) not in stated
                ):
                    problems.append(
                        f"{entry}: {strategy} window {window} neither published nor stated "
                        f"unavailable (windows {windows.get(strategy)})"
                    )
        menu = index.get("top100")
        documents: list[dict[str, Any]] = []
        expected: set[tuple[str, int, int | None, int]] = set()
        if isinstance(menu, dict) and menu.get("available") is True:
            documents = menu.get("documents") or []
            expected |= {(PURE, w, None, s) for w in longer for s in MENU_WEIGHTS}
            expected |= {
                (strategy, window, rival, s)
                for strategy, strategy_windows in rival_windows.items()
                for window in strategy_windows
                if (strategy, window, rival) not in stated
                for s in MENU_WEIGHTS
            }
        elif (absent := menu_absence(menu)) is not None:
            absences.append((entry, f"Top 100 menu not published: {absent}"))
        elif menu is None:
            problems.append(f"{entry}: index has no top100 entry")
        else:
            problems.append(f"{entry}: top100 entry malformed {menu!r}")
        got = {(d["strategy"], d["window"], d["rival_entry_id"], d["weight"]) for d in documents}
        for missing in sorted(expected - got, key=str):
            problems.append(f"{entry}: no document for {missing}")
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
        print(
            f"  window {window}: ceiling mean {sum(values) / len(values):.2f}, "
            f"max {max(values):.2f}"
        )
    print_absences(absences)
    print(f"\n{'ALL GOOD' if not problems else str(len(problems)) + ' PROBLEM(S)'}")
    for problem in problems[:40]:
        print("  " + problem)

    return problems


def check_top100(read: Callable[[str], Any]) -> list[str]:
    problems: list[str] = []
    absences: list[tuple[int, str]] = []
    changed: defaultdict[int, int] = defaultdict(int)
    costs: defaultdict[int, list[float]] = defaultdict(list)
    statuses: defaultdict[str, defaultdict[str | None, int]] = defaultdict(lambda: defaultdict(int))
    reasons: defaultdict[tuple[str, str | None], int] = defaultdict(int)
    files = 0
    members = read("members.json")["payload"]["members"]
    humans = [m["entry_id"] for m in members if m.get("member_kind") == "human"]
    for entry in humans:
        index, finding = member_index(read, entry)
        if index is None:
            problems.append(finding)
            continue
        refused = refusal(index)
        if refused is not None:
            absences.append((entry, f"no advice this week: {refused}"))
            continue
        menu = index.get("top100")
        if menu is None:
            problems.append(f"{entry}: index has no top100 entry")
            continue
        if not isinstance(menu, dict) or menu.get("available") is not True:
            absent = menu_absence(menu)
            if absent is None:
                problems.append(f"{entry}: top100 entry malformed {menu!r}")
            else:
                absences.append((entry, f"Top 100 menu not published: {absent}"))
            continue
        # A weight the menu says did not solve, with or without the word: stated only in
        # the producer's shape, with a string reason.
        stated: dict[tuple[int, bool], str] = {}
        for row in menu.get("unavailable") or []:
            if (
                isinstance(row, dict)
                and row.get("weight") in MENU_WEIGHTS
                and isinstance(row.get("word"), bool)
                and isinstance(row.get("reason"), str)
            ):
                stated[(row["weight"], row["word"])] = row["reason"]
            else:
                problems.append(f"{entry}: top100 unavailable row malformed {row!r}")
        base = read(f"advice/{entry}/saf-puan/1.json")
        if base is None or "top100" in base["payload"]:
            problems.append(f"{entry}: baseline missing or carries top100")
        word_on = (index.get("evidence") or {}).get("available") is True
        for label, paths, word in (
            ("plain", menu["paths"], False),
            ("word", menu["word_paths"], True),
        ):
            if word and not word_on and paths:
                problems.append(f"{entry}: word paths without the word")
            for weight in (str(value) for value in MENU_WEIGHTS):
                path = paths.get(weight)
                expected = (
                    f"advice/{entry}/saf-puan/1/top100-{weight}{'-hoca-sozu' if word else ''}.json"
                )
                if path is None:
                    reason = stated.get((int(weight), word))
                    if reason is not None:
                        absences.append((entry, f"Top 100 {label} {weight} not solved: {reason}"))
                    elif word_on or not word:
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
                if (
                    not isinstance(cost, (int, float))
                    or cost < 0
                    or ceiling is None
                    or ceiling < cost - 1e-9
                ):
                    problems.append(f"{entry}: {path} cost {cost} ceiling {ceiling}")
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
    print_absences(absences)
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
        index, finding = member_index(read, entry)
        if index is None:
            check(False, finding)
            continue
        refused = refusal(index)
        evidence: Any = index.get("evidence")
        if refused is None and not isinstance(evidence, dict):
            check(False, f"{entry}: index has no evidence entry")
            continue
        word_file = f"{advice_dir}/saf-puan/1/hoca-sozu.json"
        word_exists = (
            read(word_file) is not None
            if tree.live
            else (Path(tree.root) / "league" / word_file).is_file()
        )
        if refused is not None:
            check(not word_exists, f"{entry}: no advice this week ({refused}) and no file")
            continue
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
        ceiling = float(doc.get("expected_points_cost_ceiling", -1))
        check(cost >= 0 and ceiling >= cost, f"{entry}: price {cost:.2f} <= ceiling {ceiling:.2f}")
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
