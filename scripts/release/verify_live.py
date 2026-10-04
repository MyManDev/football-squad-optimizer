"""Verify the live site after a deployment: the smoke checks, the assets, then the content.

The checks mirror SMOKE_CHECKS in web/scripts/smoke-deployment.mjs, and a test holds the two
lists equal so that adding a route there cannot leave this verifier behind. The site's league
directory (``/data/leagues.json``) says which league trees it publishes; a site from before
the directory publishes the one legacy tree. The routes must return 200 carrying the SPA
document, the documents must return 200 and parse as JSON, and each tree's entry 0 must be
ABSENT (404), because entry 0 does not exist and a 200 there means the absent-document rule
has been lost. Reading that last check as "must be 200" inverts it.

Then the content. Two things can be wrong there and only one of them used to fail the run:
the publication must be the one just deployed rather than the previous one, and it must be
of the gameweek the release is for. The second is what ``--settled`` states. Without it the
verifier printed the settled weeks and returned ALL GOOD whatever they were, so a release
that published an unsettled week, or last week's, passed.

A request that gets no answer at all (a refused or reset connection, a DNS failure, a
timeout) is a failed check with status 0, not a traceback. A content document is one counted
failure when it does not come back with status 200, does not parse as a JSON object, or has a
payload that is not an object, and so is a members or gameweeks list holding anything but
objects. An index whose latest entry is not an object names no season, which is also counted.
Each of these ends the run with its failure count rather than a traceback.
"""

import argparse
import http.client
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = "https://squadopt.mymandev.com"
UA = {"User-Agent": "squadopt-verify/1.0"}

#: The HTML routes of SMOKE_CHECKS, in its order. `/fixtures` was added there and not here,
#: which is the drift the test now refuses.
ROUTES = [
    "/",
    "/moves",
    "/rivals",
    "/league",
    # A nested client-side route is the first thing a path-scoped not-found rule would
    # break; the address from before the league number is served on every site.
    "/league/members/0",
    "/status",
    "/fixtures",
]
DOCUMENTS = ["/data/index.json"]
DIRECTORY = "/data/leagues.json"
#: A name no build produces (web/scripts/smoke-deployment.mjs ABSENT_ASSET): a missing
#: asset must answer 404, not the shell an edge would keep for that name.
ABSENT_ASSET = "/assets/smoke-absent-asset.js"
#: An asset name inside the shell or a chunk, as the build emits it under assets/.
ASSET_NAME = re.compile(
    rb"""(?:/assets/|["'`]assets/|\./)([A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8}\.(?:js|css|wasm|woff2?))"""
)
MAX_ASSETS = 400
#: The one tree a site from before the directory publishes.
LEGACY_TREE = "league"
SEASON = re.compile(r"^\d{4}-\d{2}$")


def fetch(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE + path, headers=UA)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
        # URLError covers refused connections and DNS, OSError timeouts and resets during the
        # read, and HTTPException a response cut short.
        print(f"  network error on {path}: {error}")
        return 0, b""


def _document(path: str) -> dict[str, Any] | None:
    """The JSON object at ``path``, or None after printing why it could not be read."""

    status, body = fetch(path)
    document: object = None
    if status == 200:
        try:
            document = json.loads(body)
        except (ValueError, RecursionError):
            # RecursionError is what the parser raises for nesting deeper than it recurses.
            document = None
    if not isinstance(document, dict):
        print(f"  BAD {status} could not read {path}")
        return None
    return document


def _payload(document: dict[str, Any] | None, path: str) -> dict[str, Any] | None:
    """The payload object of ``document``, or None after printing why it could not be read.

    ``_document`` has already reported a document it could not read, so only a readable
    document whose payload is missing or is not an object is reported here. Either way the
    caller counts one failure for the document.
    """

    if document is None:
        return None
    payload = document.get("payload")
    if not isinstance(payload, dict):
        print(f"  BAD could not read the payload of {path}")
        return None
    return payload


def _objects(payload: dict[str, Any] | None, key: str, path: str) -> list[dict[str, Any]] | None:
    """The objects listed at ``payload[key]`` (none when the key is absent), or None.

    A payload that could not be read has been reported already and gives None silently, so
    the caller counts one failure for the document whichever read failed. A value that is
    not a list of objects is reported here.
    """

    if payload is None:
        return None
    value = payload.get(key, [])
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    print(f"  BAD {key} of {path} is not a list of objects")
    return None


#: A league tree the site publishes: its id (None for the legacy tree, which carries no
#: directory line) and its path under data/.
Tree = tuple[int | None, str]
LEGACY: Tree = (None, LEGACY_TREE)


def published_trees() -> tuple[list[Tree], bool]:
    """The league trees the site publishes, and whether the directory could be read.

    One tree per directory line; the legacy tree alone where the site publishes no directory.
    A directory that cannot be read or lists no league is a failure, and the legacy tree is
    checked in its place so the rest of the run still reports.
    """

    status, body = fetch(DIRECTORY)
    if status == 404:
        return [LEGACY], True
    rows: object = None
    if status == 200:
        try:
            rows = json.loads(body)["payload"]["leagues"]
        except (ValueError, RecursionError, KeyError, TypeError):
            rows = None
    if not isinstance(rows, list):
        print(f"  BAD {status} {DIRECTORY} is not a league directory")
        return [LEGACY], False
    trees: list[Tree] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            league_id = row.get("league_id")
            trees.append((league_id if isinstance(league_id, int) else None, row["path"]))
    if not trees:
        print(f"  BAD {DIRECTORY} lists no league")
        return [LEGACY], False
    return trees, True


def check_assets() -> int:
    """Every asset the live shell reaches answers as itself, never as the HTML shell.

    Run from the operator's machine, so it reads the edge members near the operator reach:
    an asset name an edge cached as the shell before the deploy built it is served as HTML
    there while the deployment's own smoke, run elsewhere, sees the real file. Returns the
    number of failures; each is printed.
    """

    status, shell = fetch("/")
    queue = [name.decode() for name in ASSET_NAME.findall(shell)] if status == 200 else []
    if not queue:
        print(f"  BAD {status} the shell names no asset")
        return 1
    seen: set[str] = set()
    failures = 0
    while queue:
        batch = sorted({name for name in queue if name not in seen})
        seen.update(batch)
        if len(seen) > MAX_ASSETS:
            print(f"  BAD more than {MAX_ASSETS} assets reached")
            return failures + 1
        queue = []
        for name in batch:
            status, body = fetch(f"/assets/{name}")
            served_shell = body.lstrip()[:15].lower().startswith(b"<!doctype html")
            if status != 200 or served_shell:
                failures += 1
                print(
                    f"  BAD {status} asset /assets/{name}"
                    + ("  (the HTML shell)" if served_shell else "")
                )
                continue
            if name.endswith((".js", ".css")):
                queue.extend(found.decode() for found in ASSET_NAME.findall(body))
    if not failures:
        print(f"  ok  {len(seen)} assets, each served as itself")
    return failures


def smoke_checks(trees: list[Tree]) -> tuple[list[str], list[str], list[str]]:
    """The routes, documents and absent documents the smoke checks for these trees.

    Each listed league adds its member page by its numbered address, and every tree adds
    its members document and the entry 0 document it must refuse.
    """

    routes = [*ROUTES]
    documents = [*DOCUMENTS]
    absent: list[str] = []
    for league_id, tree in trees:
        if league_id is not None:
            routes.append(f"/league/{league_id}/members/0")
        documents.append(f"/data/{tree}/members.json")
        absent.append(f"/data/{tree}/entries/0.json")
    return routes, documents, absent


def main(accepted_generated_at: str, settled_gameweek: int | None = None) -> int:
    failures = 0

    trees, directory_ok = published_trees()
    failures += not directory_ok
    routes, documents, absent_documents = smoke_checks(trees)
    absent_documents = [ABSENT_ASSET, *absent_documents]
    print(f"== {len(routes) + len(documents) + len(absent_documents) + 1} smoke checks ==")
    for path in routes:
        status, body = fetch(path)
        ok = status == 200 and b'id="root"' in body
        failures += not ok
        print(f"  {'ok ' if ok else 'BAD'} {status} html   {path}")
    for path in documents:
        status, body = fetch(path)
        try:
            json.loads(body)
            parsed = True
        except Exception:
            parsed = False
        ok = status == 200 and parsed
        failures += not ok
        print(f"  {'ok ' if ok else 'BAD'} {status} json   {path}")
    for absent in absent_documents:
        status, body = fetch(absent)
        ok = status == 404 and b'id="root"' not in body
        failures += not ok
        print(f"  {'ok ' if ok else 'BAD'} {status} absent {absent}  (must be 404, not the shell)")

    failures += check_assets()

    print("\n== content ==")
    # Every nested read below is type-checked: a document of the wrong shape inside is a
    # counted failure, where it used to end the run in an AttributeError.
    # One publication writes every tree with one stamp, so every tree must carry the
    # accepted one; the week claims below are read from each tree too.
    payloads: list[dict[str, Any]] = []
    settled_by_tree: list[list[Any]] = []
    for _league_id, tree in trees:
        if len(trees) > 1:
            print(f"  -- {tree}")
        path = f"/data/{tree}/members.json"
        document = _document(path)
        read = _payload(document, path)
        members = _objects(read, "members", path)
        failures += members is None
        payload = read or {}
        payloads.append(payload)
        generated = (document or {}).get("generated_at_utc", "")
        matches = generated == accepted_generated_at
        failures += not matches
        print(
            f"  {'ok ' if matches else 'BAD'} generated_at_utc {generated}"
            f"  (must equal accepted {accepted_generated_at})"
        )
        print(
            f"  gameweek={payload.get('gameweek')} scored_gameweek={payload.get('scored_gameweek')}"
            f" members={None if members is None else len(members)}"
        )
        movement: dict[str, int] = {}
        for member in members or []:
            value = member.get("movement")
            # A value that is not text is shown as written, and cannot fail as a dictionary
            # key.
            key = value if isinstance(value, str) else repr(value)
            movement[key] = movement.get(key, 0) + 1
        print(f"  movement={movement}")

        path = f"/data/{tree}/scoreboard.json"
        weeks = _objects(_payload(_document(path), path), "gameweeks", path)
        failures += weeks is None
        settled = [
            week.get("gameweek")
            for week in weeks or []
            if week.get("finished") and week.get("data_checked")
        ]
        settled_by_tree.append(settled)
        print(f"  scoreboard gameweeks={None if weeks is None else len(weeks)} settled={settled}")

    # The season is the one the site index names as latest, so the status document is found
    # again when the season turns over instead of being read from last season's path.
    path = "/data/index.json"
    index = _payload(_document(path), path)
    failures += index is None
    latest = (index or {}).get("latest")
    season = latest.get("season") if isinstance(latest, dict) else None
    status_doc: dict[str, Any] = {}
    if isinstance(season, str) and SEASON.match(season):
        path = f"/data/{season}/status.json"
        read = _payload(_document(path), path)
        failures += read is None
        status_doc = read or {}
    elif index is not None:
        failures += 1
        print(f"  BAD index.json names no latest season (latest={latest!r})")
    print(
        f"  status season={season} next_gameweek={status_doc.get('next_gameweek')}"
        f" deadline={status_doc.get('next_deadline_utc')}"
    )

    if settled_gameweek is not None:
        # Printing the settled weeks is not checking them: before this, a release that
        # published an unsettled week returned ALL GOOD.
        for label, ok in (
            (
                f"scoreboard settles gameweek {settled_gameweek}",
                all(settled_gameweek in settled for settled in settled_by_tree),
            ),
            (
                f"members.json scored_gameweek is {settled_gameweek}",
                all(payload.get("scored_gameweek") == settled_gameweek for payload in payloads),
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
            "Read the exact value from the league's members.json in the accepted "
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
