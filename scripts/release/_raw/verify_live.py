"""Verify the live site after a deployment: the ten smoke checks, then the content.

The ten checks mirror SMOKE_CHECKS in web/scripts/smoke-deployment.mjs. Seven routes must
return 200 carrying the SPA document, two documents must return 200 and parse as JSON, and one
document must be ABSENT (404), because entry 0 does not exist and a 200 there means the
absent-document rule has been lost. Reading that tenth check as "must be 200" inverts it.

Then the content: the publication must be the one just deployed, not the previous one.
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "https://squadopt.mymandev.com"
UA = {"User-Agent": "squadopt-verify/1.0"}

ROUTES = ["/", "/moves", "/rivals", "/league", "/league/members/0", "/analysis", "/status"]
DOCUMENTS = ["/data/index.json", "/data/league/members.json"]
ABSENT = "/data/league/entries/0.json"


def fetch(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, headers=UA)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def main(expected_generated_after: str) -> int:
    failures = 0

    print("== ten smoke checks ==")
    for path in ROUTES:
        status, body = fetch(path)
        ok = status == 200 and b'id="root"' in body
        failures += not ok
        print(f"  {'ok ' if ok else 'BAD'} {status} html   {path}")
    for path in DOCUMENTS:
        status, body = fetch(path)
        try:
            json.loads(body)
            parsed = True
        except Exception:  # noqa: BLE001
            parsed = False
        ok = status == 200 and parsed
        failures += not ok
        print(f"  {'ok ' if ok else 'BAD'} {status} json   {path}")
    status, body = fetch(ABSENT)
    ok = status == 404 and b'id="root"' not in body
    failures += not ok
    print(f"  {'ok ' if ok else 'BAD'} {status} absent {ABSENT}  (must be 404, not the shell)")

    print("\n== content ==")
    _, body = fetch("/data/league/members.json")
    members = json.loads(body)
    generated = members.get("generated_at_utc", "")
    payload = members.get("payload", {})
    fresh = generated > expected_generated_after
    failures += not fresh
    print(f"  {'ok ' if fresh else 'BAD'} generated_at_utc {generated}  (must be after {expected_generated_after})")
    print(f"  gameweek={payload.get('gameweek')} scored_gameweek={payload.get('scored_gameweek')} members={len(payload.get('members', []))}")
    movement: dict[str, int] = {}
    for member in payload.get("members", []):
        movement[member.get("movement")] = movement.get(member.get("movement"), 0) + 1
    print(f"  movement={movement}")

    _, body = fetch("/data/league/scoreboard.json")
    score = json.loads(body).get("payload", {})
    weeks = score.get("gameweeks", [])
    settled = [w.get("gameweek") for w in weeks if w.get("finished") and w.get("data_checked")]
    print(f"  scoreboard gameweeks={len(weeks)} settled={settled}")

    _, body = fetch("/data/2026-27/status.json")
    status_doc = json.loads(body).get("payload", {})
    print(f"  status next_gameweek={status_doc.get('next_gameweek')} deadline={status_doc.get('next_deadline_utc')}")

    print(f"\n{'ALL GOOD' if failures == 0 else str(failures) + ' FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-09-12T10:50:08Z"))
