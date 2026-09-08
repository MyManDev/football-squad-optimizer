"""The immutable record of what one member was told, for one gameweek.

The published league tree carries no gameweek in its paths: ``advice/{id}/{mode}/{window}.json``
is overwritten in place every week. That is right for a site — a member wants this week's
answer at a stable address — and fatal for looking back, because after the next publish
nothing on disk says what the previous week's advice was. A page that wants to review what
we advised has nothing to read, and no amount of re-solving recovers it: the capture, the
handoff and the code all moved on.

So the publish writes a second thing, once, and never again: for each member and gameweek,
a record of the advice documents it just emitted. Three properties make it usable as
evidence rather than as a note:

- **It is written by the call that writes the published bytes.** ``build_league_views``
  writes both, from the same picks, the same projection and the same payloads. A runner
  wrapped around the publish could not do this honestly — the weekly publish re-solves in
  a fresh worktree at whatever code is on develop, so a record assembled outside it would
  describe a different solve than the one that shipped.
- **It is scoring-complete.** Everything a later page needs to score what we advised is in
  the record: the eleven in pitch order, the bench in autosub order, the captain, the vice,
  the chip, the moves, the week's hit charge and the expected own points; the state the
  advice was computed from, so "ignored our advice" and "could not afford it" stay
  different answers; and the provenance that says which model, which planner policy and
  which commit produced it. Nothing has to be re-solved, and nothing may be inferred.
- **It refuses to change.** A second publish of the same week either writes exactly the
  same document — a no-op — or is refused with the difference named. It is never mutated
  silently, because a record that can be rewritten proves nothing about what was published.

What it deliberately does not do: score anything, compare anything, or read the season
ledger. It records; a review page is a separate piece of work reading these documents.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from squadopt.application.entries import EntryPicks
from squadopt.data.errors import DataError
from squadopt.live.ledger import (
    prune_stale_staging,
    record_lock,
    staging_directory,
    verify_manifest,
    write_manifest,
)
from squadopt.live.recommendation import Projection
from squadopt.live.transfers import MEMBER_PLANNING_POLICY, MEMBER_PLANNING_POLICY_ID

MEMBER_ADVICE_RECORD_CONTRACT_VERSION: Final = "member_advice_record_v1"

#: What the record's player ids are. Everything the projection, the prices and the picks
#: provider publish is the FPL **element code** — the identifier that survives a transfer
#: window — not the per-season element id the game's own endpoints use in URLs. A later
#: join that reads these as element ids silently finds no one, so the record names its own
#: identity space rather than leaving the reader to infer it (``platform/capture_context``
#: is where the mapping from element id to code is applied).
PLAYER_ID_SPACE: Final = "fpl_element_code"

RECORD_FILE: Final = "advice.json"

_COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
#: How many differing fields a refusal names before it stops listing them.
_DIFFERENCE_LIMIT: Final = 12


class AdviceRecordError(DataError):
    """An advice record could not be built, written, or trusted."""


class AdviceRecordConflictError(AdviceRecordError):
    """A week already recorded was published again with different bytes."""


@dataclass(frozen=True, slots=True)
class PublishedAdvice:
    """One advice document exactly as it was published, with its address and its bytes.

    ``relative_path`` is the path under the league tree the site addresses it by;
    ``raw`` is the file's bytes, so the record's digest is of what was actually written
    rather than of a re-rendering of the payload.
    """

    strategy: str
    window: int
    rival_entry_id: int | None
    relative_path: str
    payload: Mapping[str, object]
    raw: bytes


def repository_commit() -> str | None:
    """The commit the emitting process is running, or ``None`` when it cannot be read.

    ``SQUADOPT_REPOSITORY_COMMIT`` wins, as it does for the CLI's run context, so a build
    from an exported tree can still state its provenance. Otherwise ``git rev-parse HEAD``
    in the working tree this module was imported from. A commit that cannot be resolved is
    recorded as absent: an unknown provenance and a wrong one are not the same thing, and
    only one of them can be published.
    """

    supplied = os.environ.get("SQUADOPT_REPOSITORY_COMMIT", "").strip().lower()
    if _COMMIT_PATTERN.fullmatch(supplied):
        return supplied
    root = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            shell=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    return value if _COMMIT_PATTERN.fullmatch(value) else None


def record_directory(root: Path, season: str, gameweek: int, entry_id: int) -> Path:
    """``<root>/<season>/gw<NN>/entry-<id>`` — one document per season, week and member.

    The gameweek is in the path, which is the whole point: the published tree's addresses
    have no week in them and are overwritten, and these are neither.
    """

    if not isinstance(season, str) or not season.strip():
        raise AdviceRecordError("season must be non-empty text.")
    for name, value in (("gameweek", gameweek), ("entry_id", entry_id)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise AdviceRecordError(f"{name} must be a positive integer.")
    return Path(root) / season.strip() / f"gw{gameweek:02d}" / f"entry-{entry_id}"


def _player_ids(document: Mapping[str, object]) -> set[int]:
    found: set[int] = set()
    for key in ("starting_xi", "bench"):
        value = document.get(key)
        if isinstance(value, list):
            found.update(int(str(item)) for item in value)
    for key in ("captain", "vice_captain"):
        value = document.get(key)
        if value is not None:
            found.add(int(str(value)))
    moves = document.get("moves")
    if isinstance(moves, list):
        for move in moves:
            if not isinstance(move, Mapping):
                continue
            for side in ("player_out", "player_in"):
                player = move.get(side)
                if player is not None:
                    found.add(int(str(player)))
    return found


def _lineup_ids(payload: Mapping[str, object], key: str) -> list[int] | None:
    """The published lineup's player ids, in the order the payload published them."""

    value = payload.get(key)
    if not isinstance(value, list):
        return None
    return [int(str(player["player_id"])) for player in value if isinstance(player, Mapping)]


def _player_id(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    return int(str(value["player_id"])) if isinstance(value, Mapping) else None


def _number(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    return None if value is None else float(str(value))


def _text(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    return None if value is None else str(value)


def _moves(payload: Mapping[str, object]) -> list[dict[str, object]]:
    """The published moves as out/in pairs of player ids, with the published delta.

    A pair may name only one side: a player the projection could not resolve has no row of
    its own to point at, and the published payload carries ``null`` there. That null is
    kept rather than dropped, so the record's move count is the published move count.
    """

    raw = payload.get("moves")
    if not isinstance(raw, list):
        return []
    moves: list[dict[str, object]] = []
    for move in raw:
        if not isinstance(move, Mapping):
            continue
        moves.append(
            {
                "player_out": _player_id(move, "player_out"),
                "player_in": _player_id(move, "player_in"),
                "expected_points_delta": _number(move, "expected_points_delta"),
            }
        )
    return moves


def _advice_document(advice: PublishedAdvice) -> dict[str, object]:
    """One published document, reduced to what scoring it needs plus its two digests.

    Player names, positions and prices are not repeated per document: they are the same
    for every document in the record and live once in ``players``. What is per-document is
    the decision — who starts, in what order, who wears the armband, which chip, what
    moved and what the week's hit cost.

    Two digests, because they answer different questions. ``published_sha256`` is of the
    exact bytes at that address, envelope and generation timestamp included, so the record
    can prove which file it describes. ``advice_sha256`` is of the payload alone,
    canonically encoded, so a second publish that changed only *when* it ran can be told
    apart from one that changed *what it said*.
    """

    payload = advice.payload
    starting_xi = _lineup_ids(payload, "starting_xi")
    bench = _lineup_ids(payload, "bench")
    captain = _player_id(payload, "captain")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        # Which document this is. Several are published per member — the pure-points
        # baseline, each rival strategy against each rival, each solved window — and only
        # one of them is what the member's page points at, so every one carries its own
        # address rather than being identified by position in a list.
        "strategy": advice.strategy,
        "window": int(advice.window),
        "rival_entry_id": advice.rival_entry_id,
        "published_path": advice.relative_path,
        # The decision itself, in the published order: the eleven in pitch order and the
        # bench with the goalkeeper first, which is the order the game's autosubs walk.
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": _player_id(payload, "vice_captain"),
        "chip": _text(payload, "chip"),
        "moves": _moves(payload),
        "transfer_hit_points": _number(payload, "transfer_hit_points"),
        "expected_own_points": _number(payload, "expected_own_points"),
        # The solver's own account of this plan, as published: a proof, or a found plan
        # with the measured bound gap beside it.
        "solver_status": _text(payload, "solver_status"),
        "optimality_gap": _number(payload, "optimality_gap"),
        # Whether this document can be scored at all. A competitive mode's payload is
        # published without a lineup (the selector chose a transfer decision, not a week),
        # and the record says so rather than presenting an empty eleven as a decision.
        "scoring_complete": bool(starting_xi and bench and captain is not None),
        "published_sha256": _sha256(advice.raw),
        "advice_sha256": _sha256(encoded),
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _players_block(
    projection: Projection, wanted: Iterable[int]
) -> tuple[dict[str, dict[str, object]], list[int]]:
    """The join map for every player the record names, and the ids it could not resolve.

    A later page joining realized points onto this record needs each player's position and
    club, and the record must not make it re-read the capture to get them. A held player
    the projection has no row for is listed by id instead of being given empty fields.
    """

    pool = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    players: dict[str, dict[str, object]] = {}
    unresolved: list[int] = []
    for player in sorted({int(value) for value in wanted}):
        row = pool.get(player)
        if row is None:
            unresolved.append(player)
            continue
        players[str(player)] = {
            "name": str(row["name"]),
            "position": str(row["position"]),
            "team": str(row["team_id"]),
            "price_tenths": int(str(row["price_tenths"])),
            "expected_points": float(str(row["expected_points"])),
        }
    return players, unresolved


def build_member_advice_record(
    picks: EntryPicks,
    projection: Projection,
    published: Sequence[PublishedAdvice],
    *,
    league_id: int,
    generated_at_utc: str,
    league_view_contract_version: str,
    told: Mapping[str, object] | None = None,
    transfer_config_fingerprint: str | None = None,
    commit: str | None = None,
) -> dict[str, object]:
    """Assemble one member's record for one gameweek from what was just published.

    ``generated_at_utc`` is the timestamp the published envelopes carry, not the moment
    this runs: the record describes a publication, and stamping it with its own clock
    would make every re-publish differ for a reason that has nothing to do with the advice.

    ``told`` names the document the member's page points at, so a later page can tell what
    we told them from what we merely also computed.
    """

    if not published:
        raise AdviceRecordError(
            f"Entry {picks.entry_id} published no advice documents; a record of nothing "
            "would say a member was advised when they were not."
        )
    named: set[int] = set(int(player) for player in picks.squad)
    documents = [_advice_document(advice) for advice in published]
    for document in documents:
        named |= _player_ids(document)
    players, unresolved = _players_block(projection, named)
    diagnostics = projection.diagnostics
    return {
        "contract_version": MEMBER_ADVICE_RECORD_CONTRACT_VERSION,
        "season": picks.season,
        # The week the advice is *for*: the picks are the week before it.
        "gameweek": int(picks.gameweek) + 1,
        "entry_id": int(picks.entry_id),
        "league_id": int(league_id),
        "generated_at_utc": generated_at_utc,
        "league_view_contract_version": league_view_contract_version,
        "player_id_space": PLAYER_ID_SPACE,
        "told": dict(told) if told is not None else None,
        # The state the advice was computed from. Without it a review page cannot tell a
        # member who ignored the advice from one who could not afford it, or read a plan
        # that spent a second free transfer the source never proved they had.
        "state": {
            "picks_gameweek": int(picks.gameweek),
            "source_snapshot_id": picks.source_snapshot_id,
            "held_squad": [int(player) for player in picks.squad],
            "held_starting_xi": [int(player) for player in picks.starting_xi],
            "held_captain": int(picks.captain),
            "held_vice_captain": int(picks.vice_captain),
            "bank_tenths": int(picks.bank_tenths),
            "free_transfers": int(picks.free_transfers),
            # False means the number above is the rule-implied floor of one, not a count
            # the source published. A banked second transfer would be invisible.
            "free_transfers_known": bool(picks.free_transfers_known),
            "purchase_prices_known": bool(picks.purchase_prices_known),
            # Absent, not empty: an unknown purchase price is a different fact from a
            # purchase price of nothing, and the plan valued the squad at current prices.
            "purchase_prices": (
                {str(player): int(price) for player, price in sorted(picks.purchase_prices.items())}
                if picks.purchase_prices_known
                else None
            ),
            "chips_used": {
                name: [int(week) for week in weeks]
                for name, weeks in sorted(picks.chips_used.items())
            },
        },
        # What produced it. A number is only re-checkable against the thing that made it.
        "provenance": {
            "model_name": _text(diagnostics, "model_name"),
            "model_version": _text(diagnostics, "model_version"),
            "feature_contract_version": _text(diagnostics, "feature_contract_version"),
            "projection_source": _text(diagnostics, "projection_source"),
            "projection_handoff_contract_version": _text(
                diagnostics, "projection_handoff_contract_version"
            ),
            "projection_handoff_fingerprint": _text(diagnostics, "projection_handoff_fingerprint"),
            "projection_evidence_fingerprint": _text(
                diagnostics, "projection_evidence_fingerprint"
            ),
            "planner_policy_id": MEMBER_PLANNING_POLICY_ID,
            "planner_policy": _policy_values(),
            # The digest of every transfer-planning control the member's own plan was
            # solved under; a rival strategy additionally caps the week's transfers, and
            # the cap it applied is in that document's published bytes.
            "transfer_config_fingerprint": transfer_config_fingerprint,
            "repository_commit": commit,
        },
        "players": players,
        # Named by a document but absent from the projection, so the record has no row for
        # them. Listing the ids keeps the gap visible instead of silently shortening a map.
        "unresolved_player_ids": unresolved,
        "advice": documents,
    }


def _policy_values() -> dict[str, object]:
    values: dict[str, object] = {}
    for name, value in sorted(MEMBER_PLANNING_POLICY.items()):
        if isinstance(value, Mapping):
            values[name] = {str(k): float(str(v)) for k, v in sorted(value.items())}
        else:
            values[name] = float(str(value))
    return values


def encode_record(record: Mapping[str, object]) -> bytes:
    """The record's bytes: one stable rendering, so two identical records are equal bytes."""

    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def _differences(recorded: object, incoming: object, *, path: str = "") -> list[str]:
    """Every field where the recorded document and the incoming one disagree.

    A refusal that only says "these differ" sends a reader back to diffing two files by
    hand at the worst possible moment. This names the fields, so the operator can see at a
    glance whether a re-publish changed the advice or only the minute it ran at.
    """

    where = path or "<record>"
    if isinstance(recorded, Mapping) and isinstance(incoming, Mapping):
        found: list[str] = []
        for key in sorted({*recorded.keys(), *incoming.keys()}):
            child = f"{path}.{key}" if path else str(key)
            if key not in recorded:
                found.append(f"{child}: recorded absent, now {_short(incoming[key])}")
            elif key not in incoming:
                found.append(f"{child}: recorded {_short(recorded[key])}, now absent")
            else:
                found.extend(_differences(recorded[key], incoming[key], path=child))
        return found
    if isinstance(recorded, list) and isinstance(incoming, list):
        found = []
        if len(recorded) != len(incoming):
            found.append(f"{where}: recorded {len(recorded)} entries, now {len(incoming)}")
        # The entries both sides have are still compared, so a re-publish that added a
        # document does not hide the fact that it also changed one. The length line above
        # says the positions are not a like-for-like pairing beyond the shared prefix.
        for index, (left, right) in enumerate(zip(recorded, incoming, strict=False)):
            found.extend(_differences(left, right, path=f"{path}[{index}]"))
        return found
    if recorded != incoming:
        return [f"{where}: recorded {_short(recorded)}, now {_short(incoming)}"]
    return []


def _conflict(directory: Path, recorded: Mapping[str, object], record: Mapping[str, object]) -> str:
    differences = _differences(recorded, record)
    shown = differences[:_DIFFERENCE_LIMIT]
    more = len(differences) - len(shown)
    lines = [
        f"An advice record already exists at {directory} and this publish differs from it. "
        "Recorded advice is immutable: it is the only evidence of what the member was "
        "told, so it is refused rather than rewritten.",
    ]
    lines += [f"  {difference}" for difference in shown]
    if more > 0:
        lines.append(f"  ... and {more} more differing field(s).")
    return "\n".join(lines)


def load_member_advice_record(
    root: Path, season: str, gameweek: int, entry_id: int
) -> dict[str, object]:
    """Read one recorded week, refusing a directory whose files fail their own digests."""

    directory = record_directory(root, season, gameweek, entry_id)
    if not directory.is_dir():
        raise AdviceRecordError(f"No advice record at {directory}.")
    verify_manifest(directory)
    document: dict[str, object] = json.loads((directory / RECORD_FILE).read_text(encoding="utf-8"))
    return document


def record_member_advice(root: Path, record: Mapping[str, object]) -> Path:
    """Freeze one member's week. Identical bytes are a no-op; different bytes are refused.

    Both cases are real. The same week has been deployed twice, so a re-publish that
    reproduces the same document must not fail the run — there is nothing to disagree
    about. A re-publish that produces *different* bytes is the case that matters: it means
    the member was shown something else, or shown the same thing at a different moment,
    and overwriting the first record would destroy the only evidence of either. So it is
    refused, with the difference named.
    """

    season = str(record["season"])
    gameweek = int(str(record["gameweek"]))
    entry_id = int(str(record["entry_id"]))
    directory = record_directory(root, season, gameweek, entry_id)
    payload = encode_record(record)

    def _settled() -> Path:
        verify_manifest(directory)
        existing = (directory / RECORD_FILE).read_bytes()
        if existing == payload:
            return directory
        recorded = json.loads(existing.decode("utf-8"))
        raise AdviceRecordConflictError(_conflict(directory, recorded, record))

    if directory.exists():
        return _settled()
    with record_lock(directory):
        # Re-check under the lock: another writer may have landed the record between the
        # check above and the lock, and the second writer must not overwrite the first.
        if directory.exists():
            return _settled()
        prune_stale_staging(Path(root) / season, f"gw{gameweek:02d}")
        staging = staging_directory(directory)
        staging.mkdir(parents=True)
        try:
            (staging / RECORD_FILE).write_bytes(payload)
            write_manifest(staging, contract_version=MEMBER_ADVICE_RECORD_CONTRACT_VERSION)
            verify_manifest(staging)
            # One rename: the record exists complete or does not exist at all.
            os.replace(staging, directory)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return directory


__all__: tuple[str, ...] = (
    "MEMBER_ADVICE_RECORD_CONTRACT_VERSION",
    "PLAYER_ID_SPACE",
    "RECORD_FILE",
    "AdviceRecordConflictError",
    "AdviceRecordError",
    "PublishedAdvice",
    "build_member_advice_record",
    "encode_record",
    "load_member_advice_record",
    "record_directory",
    "record_member_advice",
    "repository_commit",
)
