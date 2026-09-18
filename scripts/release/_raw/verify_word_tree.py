"""Check a built site tree before it is published: the manager's word and the rest.

Usage: python verify_word_tree.py <root that holds data/>
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]) / "data"
QUOTE_FORBIDDEN = re.compile(
    r"%|per\s?cent|percentage|probabilit|olasıl|\bP\(|chance|likelihood|odds|quantile|spread"
    r"|\btail\b|ihtimal|şans|yüzde(?!n\b)|kantil|yayılım|\bkuyruk\b"
    r"|\b50\s*[-/]\s*50\b|fifty[\s-]fifty",
    re.IGNORECASE,
)
failures = 0


def check(ok: bool, label: str) -> None:
    global failures
    failures += not ok
    print(f"  {'ok ' if ok else 'BAD'} {label}")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


members = load(ROOT / "league" / "members.json")["members"]
humans = [m for m in members if m.get("member_kind") == "human"]
print(f"members: {len(members)} ({len(humans)} human)")

available = 0
binding = 0
withheld = 0
shown = 0
for member in humans:
    entry = member["entry_id"]
    advice_dir = ROOT / "league" / "advice" / str(entry)
    index = load(advice_dir / "index.json")
    evidence = index.get("evidence")
    if not isinstance(evidence, dict):
        check(False, f"{entry}: index has no evidence entry")
        continue
    word_file = advice_dir / "saf-puan" / "1" / "hoca-sozu.json"
    if not evidence.get("available"):
        check(not word_file.exists(), f"{entry}: unavailable ({evidence.get('reason')}) and no file")
        continue
    available += 1
    check(evidence.get("path") == f"advice/{entry}/saf-puan/1/hoca-sozu.json", f"{entry}: index path")
    check(word_file.is_file(), f"{entry}: hoca-sozu.json exists")
    doc = load(word_file)
    base = load(advice_dir / "saf-puan" / "1.json")
    ev = doc.get("evidence") or {}
    check(doc.get("mode") == "saf-puan" and doc.get("window") == 1, f"{entry}: saf-puan/1")
    check(ev.get("binding") == evidence.get("binding"), f"{entry}: binding agrees with index")
    check(len(ev.get("applied", [])) == evidence.get("applied_count"), f"{entry}: applied count agrees")
    cost = float(doc.get("expected_points_cost", -1))
    ceiling = float(doc.get("expected_points_cost_ceiling", -1))
    check(cost >= 0 and ceiling >= cost, f"{entry}: price {cost:.2f} <= ceiling {ceiling:.2f}")
    if ev.get("binding"):
        binding += 1
        check(len(ev.get("applied", [])) > 0, f"{entry}: binding word shows its statements")
    else:
        check(cost == 0.0, f"{entry}: non-binding word costs nothing")
        check(doc.get("captain") == base.get("captain"), f"{entry}: non-binding keeps the captain")
    barred = {a["player_id"] for a in ev.get("applied", []) if a.get("role")}
    not_starting = {a["player_id"] for a in ev.get("applied", []) if a.get("role") == "not_starting"}
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

# No published JSON anywhere carries the fixture's figure or any quote wording.
hits = []
for path in ROOT.rglob("hoca-sozu.json"):
    text = path.read_text(encoding="utf-8")
    if "80%" in text or re.search(r"per\s?cent", text, re.IGNORECASE):
        hits.append(path.relative_to(ROOT).as_posix())
check(not hits, f"no switched-on file carries the figure ({hits[:3]})")
print("\nALL GOOD" if failures == 0 else f"\n{failures} FAILURE(S)")
sys.exit(1 if failures else 0)
