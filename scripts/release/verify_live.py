"""Verify the live site after a deployment: the eleven smoke checks, then the content.

The checks mirror SMOKE_CHECKS in web/scripts/smoke-deployment.mjs, and a test holds the two
lists equal so that adding a route there cannot leave this verifier behind. Eight routes must
return 200 carrying the SPA document, two documents must return 200 and parse as JSON, and one
document must be ABSENT (404), because entry 0 does not exist and a 200 there means the
absent-document rule has been lost. Reading that last check as "must be 200" inverts it.

Then the content. Two things can be wrong there and only one of them used to fail the run:
the publication must be the one just deployed rather than the previous one, and it must be
of the gameweek the release is for. The second is what ``--settled`` states. Without it the
verifier printed the settled weeks and returned ALL GOOD whatever they were, so a release
that published an unsettled week, or last week's, passed.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE = "https://squadopt.mymandev.com"
UA = {"User-Agent": "squadopt-verify/1.0"}

#: The HTML routes of SMOKE_CHECKS, in its order. `/fixtures` was added there and not here,
#: which is the drift the test now refuses.
ROUTES = [
    "/",
    "/moves",
    "/rivals",
    "/league",
    "/league/members/0",
    "/analysis",
    "/status",
    "/fixtures",
]
DOCUMENTS = ["/data/index.json", "/data/league/members.json"]
ABSENT = "/data/league/entries/0.json"


def fetch(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, headers=UA)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def main(accepted_generated_at: str, settled_gameweek: int | None = None) -> int:
    failures = 0

    print(f"== {len(ROUTES) + len(DOCUMENTS) + 1} smoke checks ==")
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
        except Exception:
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
    matches = generated == accepted_generated_at
    failures += not matches
    print(
        f"  {'ok ' if matches else 'BAD'} generated_at_utc {generated}"
        f"  (must equal accepted {accepted_generated_at})"
    )
    print(
        f"  gameweek={payload.get('gameweek')} scored_gameweek={payload.get('scored_gameweek')}"
        f" members={len(payload.get('members', []))}"
    )
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
    print(
        f"  status next_gameweek={status_doc.get('next_gameweek')}"
        f" deadline={status_doc.get('next_deadline_utc')}"
    )

    if settled_gameweek is not None:
        # Printing the settled weeks is not checking them: before this, a release that
        # published an unsettled week returned ALL GOOD.
        for label, ok in (
            (f"scoreboard settles gameweek {settled_gameweek}", settled_gameweek in settled),
            (
                f"members.json scored_gameweek is {settled_gameweek}",
                payload.get("scored_gameweek") == settled_gameweek,
            ),
            (
                f"status moved past gameweek {settled_gameweek}",
                isinstance(status_doc.get("next_gameweek"), int)
                and int(status_doc["next_gameweek"]) > settled_gameweek,
            ),
        ):
            failures += not ok
            print(f"  {'ok ' if ok else 'BAD'} {label}")

    print(f"\n{'ALL GOOD' if failures == 0 else str(failures) + ' FAILURE(S)'}")
    return 1 if failures else 0


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "accepted_generated_at",
        help=(
            "the live publication's generated_at_utc must equal this accepted candidate stamp. "
            "Read the exact value from web/public/data/league/members.json in the accepted "
            "publication tree, not from the clock or the previous live site."
        ),
    )
    parser.add_argument(
        "--settled",
        type=int,
        default=None,
        help="the gameweek this release settles; asserted rather than printed",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    parsed = _arguments(sys.argv[1:])
    sys.exit(main(parsed.accepted_generated_at, parsed.settled))
