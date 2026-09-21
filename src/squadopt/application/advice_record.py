"""The immutable record of what one member was told, for one gameweek.

The published league tree carries no gameweek in its paths: ``advice/{id}/{mode}/{window}.json``
is overwritten in place every week. That is right for a site — a member wants this week's
answer at a stable address — and fatal for looking back, because after the next publish
nothing on disk says what the previous week's advice was. A page that wants to review what
we advised has nothing to read, and no amount of re-solving recovers it: the capture, the
handoff and the code all moved on.

So the publish writes a second thing, once per publish and never twice for the same one:
for each member, gameweek **and capture**, a record of the advice documents it just
emitted. Three properties make it usable as evidence rather than as a note:

- **It is written by the call that writes the published bytes.** ``build_league_views``
  writes both, from the same picks, the same projection and the same payloads. A runner
  wrapped around the publish could not do this honestly: it would be describing a solve
  it did not perform. The weekly run publishes the preview tree it built, so its league
  stage is that call and writes the record when the run is going to publish.
- **It is scoring-complete.** Everything a later page needs to score what we advised is in
  the record: the eleven in pitch order, the bench in autosub order, the captain, the vice,
  the chip, the moves, the week's hit charge and the expected own points; the state the
  advice was computed from, so "ignored our advice" and "could not afford it" stay
  different answers; and the provenance that says which model, which planner policy and
  which commit produced it. Nothing has to be re-solved, and nothing may be inferred.
- **It refuses to change.** A second build *of the same capture* either says exactly what
  the first said — a no-op, including when only the publication clock has moved — or is
  refused with the difference named. It is never mutated silently, because a record that
  can be rewritten proves nothing about what was published. That refusal is also the
  divergence detector: the same capture must solve to the same advice, and when it did
  not, this is what surfaced it.

A gameweek is normally published more than once — a mid-week publish so members see
something, then another shortly before the deadline with fresh availability — and each of
those is a *different capture*. Keying the record by season, gameweek and entry alone made
the first publish win: the second was refused as a rewrite, so the advice that actually
stood at the deadline, the advice a member acted on, never reached the record while the
record held an earlier version nobody used. The capture is therefore part of the key, one
path segment of its own, and each publish writes its own record without blocking any other.
Create-once still holds within a capture, which is where it was ever earning anything.

The reader that answers the review page's question — which record was the last one written
from a capture preceding the deadline — is :func:`load_member_advice_record_for_deadline`,
and :func:`recorded_captures` lists what a week holds.

What it deliberately does not do: score anything, compare anything, or read the season
ledger. It records; a review page is a separate piece of work reading these documents.
"""

import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from squadopt.application.entries import EntryPicks
from squadopt.data.atomic import replace_retrying
from squadopt.data.errors import DataError, RenameRefusedError
from squadopt.data.source_revision import is_source_revision, source_revision
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.ledger import (
    prune_stale_staging,
    record_lock,
    staging_directory,
    verify_manifest,
    write_manifest,
)
from squadopt.live.recommendation import Projection
from squadopt.live.transfers import MEMBER_PLANNING_POLICY, MEMBER_PLANNING_POLICY_ID

#: ``v2`` keys a record by its capture as well, and carries the capture in the document.
#: ``v1`` was one record per season, gameweek and entry, addressed at ``entry-<id>/`` with
#: no capture anywhere in it, so the two shapes cannot be read as one — see
#: ``LEGACY_LAYOUT_NOTE`` for why no migration is written.
#:
#: A nullable field added to the document does not move this. The version separates shapes
#: that cannot be read as one, which is what v1 and v2 are: a reader of v2 that meets a key
#: it does not know ignores it, and a reader that wants a key an older document lacks gets
#: ``None``, which the document means rather than a value it is missing. Moving the version
#: for an additive field would make every older record unreadable to gain nothing, and this
#: string is read nowhere outside this module, so the move would be inert as well. A field
#: whose absence cannot be read as absent, or a changed meaning for an existing key, is what
#: moves it.
MEMBER_ADVICE_RECORD_CONTRACT_VERSION: Final = "member_advice_record_v2"

#: What the record's player ids are. Everything the projection, the prices and the picks
#: provider publish is the FPL **element code** — the identifier that survives a transfer
#: window — not the per-season element id the game's own endpoints use in URLs. A later
#: join that reads these as element ids silently finds no one, so the record names its own
#: identity space rather than leaving the reader to infer it (``platform/capture_context``
#: is where the mapping from element id to code is applied).
PLAYER_ID_SPACE: Final = "fpl_element_code"

RECORD_FILE: Final = "advice.json"

#: How many differing fields a refusal names before it stops listing them.
_DIFFERENCE_LIMIT: Final = 12
#: What may be a capture's path segment. A snapshot identifier is
#: ``{source}-{stamp}-{digest}`` (``src/squadopt/data/snapshots.py``) and so is already
#: safe, but this is the segment of a path that is written to, so it is checked rather
#: than trusted: no
#: separator, no ``.``/``..``, and a length bound because the whole record path has to stay
#: inside Windows' limit with a staging sibling's name on top of it.
_CAPTURE_SEGMENT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")

#: What happens to a record written under the pre-capture key. Nothing: none exists.
#:
#: ``v1`` wrote ``<season>/gw<NN>/entry-<id>/advice.json``; ``v2`` writes
#: ``<season>/gw<NN>/entry-<id>/<snapshot id>/advice.json``. No ``v1`` record existed on any
#: disk when the key changed — the record had never been written by a real publish — so a
#: migration would be code with nothing to migrate, and it is deliberately not written.
#: What *is* written is the refusal below, because the failure mode of ignoring the question
#: is the bad one: a reader that listed capture directories would simply not see a ``v1``
#: file sitting beside them, and would answer "we told them nothing" while the evidence lay
#: unread in the same directory. So both the reader and the writer refuse and name the file.
#: Moving one by hand is mechanical where its ``state.source_snapshot_id`` names a capture —
#: that field is the same identifier the new segment uses — and impossible where it is null,
#: which is exactly why the choice is a person's and not a silent rename.
LEGACY_LAYOUT_NOTE: Final = (
    "It was written under the pre-capture key (contract member_advice_record_v1), which "
    "addressed one record per week rather than one per publish. There is no migration: no "
    "such record existed when the key changed, and the two shapes are never read as one. "
    "Move it under the directory named by the capture its own state.source_snapshot_id "
    "states, or delete it, before this week can be read or written again."
)


class AdviceRecordError(DataError):
    """An advice record could not be built, written, or trusted."""


class AdviceRecordConflictError(AdviceRecordError):
    """A capture already recorded was built again with different bytes."""


class AdviceRecordNotLandedError(AdviceRecordError):
    """A complete record could not be moved into place, so nothing was recorded.

    Deliberately not a conflict. A conflict is two different answers for one capture and
    needs a person to decide which is true; this is the filesystem refusing a rename for
    the whole retry budget, with the record staged, verified and never published. Nothing
    on disk disagrees with anything, and re-running the publish of this capture records
    it. Reporting the two as one error would have an operator hunting a divergence that
    does not exist while the week's evidence is simply missing.
    """


@dataclass(frozen=True, slots=True)
class RecordCapture:
    """The capture one record was built from: which capture, and when it was taken.

    Both halves are load-bearing and neither is derivable from the other here. The
    identifier is the record's key — it is the path segment that lets two publishes of one
    gameweek coexist. The instant is what the review page's question is asked in terms of:
    a record counts as "what we told them" only if its capture preceded the deadline, and
    parsing that instant back out of the identifier's stamp would be reading a display
    format as data.
    """

    snapshot_id: str
    captured_at_utc: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not _CAPTURE_SEGMENT.fullmatch(
            self.snapshot_id
        ):
            raise AdviceRecordError(
                f"snapshot_id must be one safe path segment of at most 96 characters, got "
                f"{self.snapshot_id!r}."
            )
        try:
            object.__setattr__(
                self,
                "captured_at_utc",
                normalize_utc_timestamp(self.captured_at_utc, label="captured_at_utc"),
            )
        except DataError as error:
            raise AdviceRecordError(str(error)) from error

    @property
    def instant(self) -> datetime:
        """The capture instant, for comparison with a deadline."""

        return as_instant(self.captured_at_utc)

    def to_document(self) -> dict[str, object]:
        return {"snapshot_id": self.snapshot_id, "captured_at_utc": self.captured_at_utc}


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
    """The commit the emitting process is running, or ``None`` when none can be stood behind.

    Resolved by ``data/source_revision``, which every stamp in this repository now shares.
    This is the one caller that uses the answer as a *description* rather than an identity,
    so it is also the one that publishes absence: an unknown provenance and a wrong one are
    not the same thing, and only one of them may be written down.

    Two cases read as absent. Nothing named the commit at all, and the checkout on disk is
    not that commit -- it is modified, or it is on a different HEAD than the value that was
    declared. The second is the one that used to publish a falsehood: measured on a modified
    checkout, this function returned a full SHA describing none of the bytes that produced the
    advice. A record is evidence, so it says nothing rather than something untrue, and a
    reader of ``provenance.repository_commit`` can take a value there as the tree that ran.

    What it deliberately does not do is refuse. The record is the only evidence of what a
    member was told; losing it because git is missing would protect a footnote by destroying
    the document it annotates.
    """

    resolved = source_revision()
    if resolved is None or resolved.matches_checkout is False:
        return None
    return resolved.commit


def entry_directory(root: Path, season: str, gameweek: int, entry_id: int) -> Path:
    """``<root>/<season>/gw<NN>/entry-<id>`` — every record this member has for this week.

    The gameweek is in the path, which is the whole point: the published tree's addresses
    have no week in them and are overwritten, and these are neither. What is *below* this
    is one directory per capture, because a week is published more than once.
    """

    if not isinstance(season, str) or not season.strip():
        raise AdviceRecordError("season must be non-empty text.")
    for name, value in (("gameweek", gameweek), ("entry_id", entry_id)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise AdviceRecordError(f"{name} must be a positive integer.")
    return Path(root) / season.strip() / f"gw{gameweek:02d}" / f"entry-{entry_id}"


def record_directory(
    root: Path, season: str, gameweek: int, entry_id: int, snapshot_id: str
) -> Path:
    """``<root>/<season>/gw<NN>/entry-<id>/<snapshot id>`` — one publish's record.

    A path segment per capture, rather than a capture field inside a single week's file or
    a suffix on its name, for three reasons. Each publish's write is then an ordinary
    create-once of a fresh directory, so the existing lock, staging and manifest primitives
    keep working unchanged and no writer ever edits another's bytes. The week's directory
    lists its publishes by listing itself, which is what the reader below needs. And the
    key is visible in the path, so an operator looking at the tree can see which capture a
    record came from without opening it.
    """

    directory = entry_directory(root, season, gameweek, entry_id)
    if not isinstance(snapshot_id, str) or not _CAPTURE_SEGMENT.fullmatch(snapshot_id):
        raise AdviceRecordError(
            f"snapshot_id must be one safe path segment of at most 96 characters, got "
            f"{snapshot_id!r}."
        )
    return directory / snapshot_id


def _refuse_legacy_layout(directory: Path) -> None:
    """Refuse a member-week directory that holds a record in the pre-capture shape.

    ``v1`` put ``advice.json`` directly here; ``v2`` puts a capture directory here. Reading
    on would silently ignore the ``v1`` file, and writing on would leave it unreadable
    beside the new records, so both stop and name it.
    """

    legacy = directory / RECORD_FILE
    if legacy.is_file():
        raise AdviceRecordError(f"{legacy} is not a capture directory. {LEGACY_LAYOUT_NOTE}")


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


def _flag(payload: Mapping[str, object], key: str) -> bool | None:
    """A published boolean, or ``None`` where the document does not carry one.

    A missing field is not ``False``. A document published before its producer
    carried this says nothing about which budget stopped its search, and a record
    that read it as ``False`` would say the clock did not, which nobody measured.
    """

    value = payload.get(key)
    return value if isinstance(value, bool) else None


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
    apart from one that changed *what it said* — the distinction
    :func:`record_member_advice` makes to tell a replay from a disagreement.
    """

    payload = advice.payload
    starting_xi = _lineup_ids(payload, "starting_xi")
    bench = _lineup_ids(payload, "bench")
    captain = _player_id(payload, "captain")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    settings: dict[str, object] = {
        key: _number(payload, key)
        for key in ("expected_points_cost", "expected_points_cost_ceiling")
        if payload.get(key) is not None
    }
    top100 = payload.get("top100")
    if isinstance(top100, Mapping) and top100.get("weight") is not None:
        settings["top100_weight"] = int(str(top100["weight"]))
    if "evidence" in payload:
        settings["managers_word"] = True
    return {
        **settings,
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
        # And whether the wall clock stopped it, so a settled record can tell a plan the
        # budget ended from one that was a property of the machine's load. The work spent
        "wall_clock_stopped_the_search": _flag(payload, "wall_clock_stopped_the_search"),
        # The work spent is deliberately not here, and the reason is reproducibility rather
        # than path. Two runs of the same publish disagree on it in the last decimal digit:
        # member 2199732 read 1.2949777377880984 and then ...82 on the same capture under the
        # same budget, measured against the committed `member_plan_determinism` record. The
        # record of a capture must be rebuildable to the same bytes, so a field that wobbles
        # below the last digit anyone would read cannot be in it. What ends the search is a
        # category and does not wobble.
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


def _published_forecast(index: tuple[str, bytes]) -> dict[str, object]:
    """Keep the exact forecast fragment emitted by the member index writer."""
    path, raw = index
    try:
        document = json.loads(raw)["payload"]["chip_forecast"]
        # The index writer uses indent=2; this field is inside its payload. Keep
        # its actual indentation too, then prove these exact bytes are present.
        fragment = json.dumps(document, indent=2).replace("\n", "\n    ").encode("utf-8")
        if raw.count(fragment) != 1:
            raise ValueError("The exact forecast fragment is not unique in its index.")
    except (KeyError, TypeError, ValueError) as error:
        raise AdviceRecordError(
            "The published index does not carry an exact chip forecast."
        ) from error
    return {
        "document_json": fragment.decode("utf-8"),
        "document_sha256": _sha256(fragment),
        "published_index_path": path,
        "published_index_sha256": _sha256(raw),
    }


def build_member_advice_record(
    picks: EntryPicks,
    projection: Projection,
    published: Sequence[PublishedAdvice],
    *,
    capture: RecordCapture,
    league_id: int,
    generated_at_utc: str,
    league_view_contract_version: str,
    told: Mapping[str, object] | None = None,
    transfer_config_fingerprint: str | None = None,
    commit: str | None = None,
    published_index: tuple[str, bytes] | None = None,
) -> dict[str, object]:
    """Assemble one member's record for one gameweek from what was just published.

    ``capture`` is the capture this publish read, and it is the record's key: a week
    published twice from two captures is two records, not a rewrite of one.

    ``generated_at_utc`` is the timestamp the published envelopes carry, not the moment
    this runs: the record describes a publication, and stamping it with its own clock
    would make every re-publish differ for a reason that has nothing to do with the advice.
    The envelopes' own clock still moves — nothing in the site's build fixes it — so a
    re-publish of one capture moves this field and every ``published_sha256`` computed
    over bytes carrying it; :func:`record_member_advice` is where that is read as a replay.

    ``told`` names the document the member's page points at, so a later page can tell what
    we told them from what we merely also computed.
    """

    if not published:
        raise AdviceRecordError(
            f"Entry {picks.entry_id} published no advice documents; a record of nothing "
            "would say a member was advised when they were not."
        )
    if picks.source_snapshot_id is not None and picks.source_snapshot_id != capture.snapshot_id:
        raise AdviceRecordError(
            f"Entry {picks.entry_id}'s picks were read from capture "
            f"{picks.source_snapshot_id!r}, but this record would be keyed by "
            f"{capture.snapshot_id!r}. The key has to name the capture the advice was built "
            "from, or the record is filed under a publish that never happened."
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
        # The capture this publish read: the fourth part of the record's key, in the
        # document as well as in the path so a file that has been moved still says which
        # publish it is, and so the reader can order publishes without parsing a path.
        "capture": capture.to_document(),
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
            # What the whole squad sells for, which the endpoints state even where they
            # state no purchase price. It is the budget the plan was held to, so the
            # record carries it beside the bank rather than leaving a reader to add up
            # current prices and get a larger number than the member could ever raise.
            "squad_sell_value_tenths": (
                None
                if picks.squad_sell_value_tenths is None
                else int(picks.squad_sell_value_tenths)
            ),
            # Absent, not empty: an unknown purchase price is a different fact from a
            # purchase price of nothing.
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
        **({"chip_forecast": _published_forecast(published_index)} if published_index else {}),
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
    hand at the worst possible moment. This names the fields instead, so the operator can
    see at a glance what a re-publish changed about the advice.
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


#: What a clock-derived field is blanked to before two records are compared. A constant
#: rather than ``None`` so that a field *missing* on one side stays missing, and is still
#: reported as a difference instead of matching a blanked one.
_REPLAYED: Final = "<moved by the publication clock>"


def _without_publication_clock(record: Mapping[str, object]) -> dict[str, object]:
    """The record with the fields a re-publish moves for no reason blanked out.

    ``generated_at_utc`` is the clock the published envelopes
    carry, and every ``published_sha256`` is a digest of bytes that carry it, so all of
    them move when one capture is published again and not a word of the advice changes.
    The optional forecast's index digest also includes that same publication clock.
    Its exact document bytes, document digest and path are still compared.

    Every other field is left alone and compared — ``advice_sha256`` above all, the digest
    of the payload alone, which is precisely the field that says whether what the member
    was told changed. Blanking named clock fields rather than comparing a list of allowed
    ones means a field added to the record later is compared by default: a new way for two
    builds to disagree is refused until someone decides otherwise, not forgiven by silence.
    """

    stripped = dict(record)
    if "generated_at_utc" in stripped:
        stripped["generated_at_utc"] = _REPLAYED
    advice = stripped.get("advice")
    if isinstance(advice, list):
        stripped["advice"] = [_document_without_publication_clock(item) for item in advice]
    forecast = stripped.get("chip_forecast")
    if isinstance(forecast, Mapping) and "published_index_sha256" in forecast:
        # Blanked because the index it digests carries the publication clock,
        # not because index digests are unimportant. The stored bytes never change.
        stripped["chip_forecast"] = {**forecast, "published_index_sha256": _REPLAYED}
    return stripped


def _document_without_publication_clock(document: object) -> object:
    if not isinstance(document, Mapping) or "published_sha256" not in document:
        return document
    return {**document, "published_sha256": _REPLAYED}


def _reconciled(
    recorded: Mapping[str, object], incoming: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    """Both records, prepared for comparison: clock blanked, and an unknown revision matched.

    The clock blanking is :func:`_without_publication_clock` and is explained there. What is
    added here is the one case where a difference is not a disagreement: exactly one side
    knows ``provenance.repository_commit`` and the other published ``null``.

    That is one publish not knowing, not two publishes contradicting each other. It happens
    when a capture is published once from a checkout that could not be stood behind -- git
    absent, or the tree modified -- and published again from one that could. Nothing about
    the advice changed; one record simply declined to guess. Refusing the week over it would
    fail a run on a footnote, which is the opposite of what recording provenance is for.

    Four things this deliberately does not do. It does not touch the bytes on disk: the known
    value is copied onto the unknown side **for the comparison only**, so a record that said
    ``null`` still says ``null`` afterwards and is never quietly upgraded. It does not forgive
    two differing commits -- catching those is the entire reason the field exists, and they
    still conflict and are still named. It requires the field present on both sides, so a
    record missing it altogether is still a difference rather than a match. And the known side
    has to be spelled like a revision: ``null`` against something that is not a commit is not
    a build declining to guess, it is a document this system did not write, and forgiving that
    would forgive anything at all appearing in the provenance block.
    """

    left = _without_publication_clock(recorded)
    right = _without_publication_clock(incoming)
    left_provenance, right_provenance = left.get("provenance"), right.get("provenance")
    if not isinstance(left_provenance, Mapping) or not isinstance(right_provenance, Mapping):
        return left, right
    if "repository_commit" not in left_provenance or "repository_commit" not in right_provenance:
        return left, right
    was, now = left_provenance["repository_commit"], right_provenance["repository_commit"]
    if was is None and is_source_revision(now):
        left["provenance"] = {**left_provenance, "repository_commit": now}
    elif now is None and is_source_revision(was):
        right["provenance"] = {**right_provenance, "repository_commit": was}
    return left, right


def _is_replay(recorded: Mapping[str, object], incoming: Mapping[str, object]) -> bool:
    """Whether the incoming record says exactly what the recorded one says.

    The same comparison the refusal message is built from, run over both records as
    :func:`_reconciled` prepares them, so the predicate and the message can never drift
    apart: if nothing else differs, one capture was published twice and said the same thing
    both times, which is a replay rather than a disagreement.
    """

    return not _differences(*_reconciled(recorded, incoming))


def _conflict(directory: Path, recorded: Mapping[str, object], record: Mapping[str, object]) -> str:
    """The refusal, naming what disagreed — which is never the publication clock.

    Both sides go through :func:`_reconciled` first, exactly as :func:`_is_replay` does. A
    refusal getting this far means something other than the publication clock moved, so
    listing the clock would be worse than useless: it always moves on a re-publish, it is
    never the reason, and at four fields on a three-document member it displaces the fields
    that *are* the reason out of a message that only names the first ``_DIFFERENCE_LIMIT``.
    The same argument covers a revision one side did not know: reconciled there too, so it
    cannot displace the real difference out of the list either.
    """

    differences = _differences(*_reconciled(recorded, record))
    differences.sort(key=lambda field: field.startswith(("advice[", "advice:")))
    shown = differences[:_DIFFERENCE_LIMIT]
    more = len(differences) - len(shown)
    lines = [
        f"An advice record already exists at {directory} and this build of the same capture "
        "advises something different. Recorded advice is immutable: it is the only evidence "
        "of what the member was told, so it is refused rather than rewritten. Check the "
        "capture, rotation table, Top 100 export and code revision for changes. The "
        "publication's own clock is not listed; a re-publish that moved only that is a replay "
        "and would not have been refused.",
    ]
    lines += [f"  {difference}" for difference in shown]
    if more > 0:
        lines.append(f"  ... and {more} more differing field(s).")
    return "\n".join(lines)


def load_member_advice_record(
    root: Path, season: str, gameweek: int, entry_id: int, snapshot_id: str
) -> dict[str, object]:
    """Read one publish's record, refusing a directory whose files fail their own digests."""

    directory = record_directory(root, season, gameweek, entry_id, snapshot_id)
    _refuse_legacy_layout(directory.parent)
    if not directory.is_dir():
        raise AdviceRecordError(f"No advice record at {directory}.")
    return _read_record(directory)


def _read_record(directory: Path) -> dict[str, object]:
    verify_manifest(directory)
    document: dict[str, object] = json.loads((directory / RECORD_FILE).read_text(encoding="utf-8"))
    return document


def _record_capture(record: Mapping[str, object]) -> RecordCapture:
    """The capture a record states, which is the capture it is keyed by."""

    block = record.get("capture")
    if not isinstance(block, Mapping):
        raise AdviceRecordError(
            "An advice record must carry a capture block naming the capture it was built "
            f"from; got {_short(block)}. {LEGACY_LAYOUT_NOTE}"
        )
    snapshot_id = block.get("snapshot_id")
    captured_at = block.get("captured_at_utc")
    if not isinstance(snapshot_id, str) or not isinstance(captured_at, str):
        raise AdviceRecordError(
            "An advice record's capture block must carry snapshot_id and captured_at_utc "
            f"as text; got {_short(snapshot_id)} and {_short(captured_at)}."
        )
    return RecordCapture(snapshot_id, captured_at)


def recorded_captures(
    root: Path, season: str, gameweek: int, entry_id: int
) -> tuple[RecordCapture, ...]:
    """Every capture this member's week has a record from, oldest capture first.

    Ordered by capture instant and then by identifier, so the order is a property of the
    evidence rather than of the filesystem: file modification times order when a record was
    *copied*, not when its capture was taken, and a record restored from a backup would
    otherwise sort as the newest thing on disk.

    An empty tuple means the week has no record at all — which is a different answer from
    "it has records, but none from before the deadline", and the reader below keeps the two
    apart.
    """

    directory = entry_directory(root, season, gameweek, entry_id)
    _refuse_legacy_layout(directory)
    if not directory.is_dir():
        return ()
    captures: list[RecordCapture] = []
    for child in sorted(directory.iterdir()):
        # A hidden sibling is a staging directory or a lock left by a writer, not a record.
        if not child.is_dir() or child.name.startswith("."):
            continue
        capture = _record_capture(_read_record(child))
        if capture.snapshot_id != child.name:
            raise AdviceRecordError(
                f"{child} holds a record that names capture {capture.snapshot_id!r}. A record "
                "is addressed by the capture it states, so this directory cannot be trusted "
                "to be the publish its name claims."
            )
        captures.append(capture)
    return tuple(sorted(captures, key=lambda capture: (capture.instant, capture.snapshot_id)))


def load_member_advice_record_for_deadline(
    root: Path, season: str, gameweek: int, entry_id: int, *, deadline_utc: str
) -> dict[str, object]:
    """The latest capture whose recorded publication also precedes ``deadline_utc``.

    This is the question a review page asks, and the only one it may ask: its whole claim
    is "this is what we told you", and a week is published more than once, so the record
    that matters is the last one a member could still have acted on. Later captures are not
    that; neither is an earlier capture first published after entries locked. Ordering
    remains by capture time for this legacy reader; the evaluation reader separately
    selects by publication time.

    Strictly preceding: a capture taken at the deadline instant is not information the
    member had before entries locked, and half a second either side of a lock is exactly
    where a generous comparison would put words in our mouth.

    The deadline is the caller's to supply rather than something the record carries. The
    record is immutable and the fixture calendar is not — the game moves deadlines — so a
    frozen copy of one would be an old answer that no correction could reach.

    Two answers this deliberately refuses to invent:

    - **No capture precedes the deadline.** Raises, and says whether the week has no record
      at all or only records built after the deadline. The nearest later record is *not*
      returned in its place: it says what we would have advised, not what we did.
    - **Two records share the last capture instant before it.** Raises, naming both. Which
      of them a member saw is not recorded anywhere, and neither the write order nor the
      files' timestamps are evidence of it, so choosing would be a guess presented as fact.
    """

    deadline = _deadline_instant(deadline_utc)
    captures = recorded_captures(root, season, gameweek, entry_id)
    where = entry_directory(root, season, gameweek, entry_id)
    if not captures:
        raise AdviceRecordError(
            f"No advice record for {season} gameweek {gameweek}, entry {entry_id}: nothing "
            f"under {where}."
        )
    before = [capture for capture in captures if capture.instant < deadline]
    if not before:
        raise AdviceRecordError(
            f"{season} gameweek {gameweek}, entry {entry_id} has {len(captures)} advice "
            f"record(s) under {where}, and every one of them was built from a capture at or "
            f"after the deadline {deadline_utc} (earliest {captures[0].captured_at_utc}). "
            "None of them is what the member was told before the deadline, and the nearest "
            "later one is not returned instead: it says what we would have advised, not "
            "what we did."
        )
    records: dict[str, dict[str, object]] = {}
    for capture in before:
        record = load_member_advice_record(root, season, gameweek, entry_id, capture.snapshot_id)
        stamp = record.get("generated_at_utc")
        if not isinstance(stamp, str):
            raise AdviceRecordError("Recorded publication time is missing.")
        try:
            published = as_instant(normalize_utc_timestamp(stamp, label="generated_at_utc"))
        except DataError as error:
            raise AdviceRecordError(str(error)) from error
        if published < deadline:
            records[capture.snapshot_id] = record
    before = [capture for capture in before if capture.snapshot_id in records]
    if not before:
        raise AdviceRecordError(
            "No advice record was published before the deadline; a pre-deadline capture "
            "does not establish that its advice was available in time."
        )
    latest = before[-1]
    tied = [capture for capture in before if capture.instant == latest.instant]
    if len(tied) > 1:
        raise AdviceRecordError(
            f"{season} gameweek {gameweek}, entry {entry_id} has {len(tied)} advice records "
            f"sharing the last capture instant before {deadline_utc} "
            f"({latest.captured_at_utc}): {', '.join(capture.snapshot_id for capture in tied)}. "
            "Which of them a member saw is not recorded, and file timestamps are not "
            "evidence of it, so one is not chosen for you."
        )
    return records[latest.snapshot_id]


def _deadline_instant(deadline_utc: str) -> datetime:
    try:
        return as_instant(normalize_utc_timestamp(deadline_utc, label="deadline_utc"))
    except DataError as error:
        raise AdviceRecordError(str(error)) from error


def record_member_advice(root: Path, record: Mapping[str, object]) -> Path:
    """Freeze one member's publish. The same advice is a no-op; different advice is refused.

    Both cases are real, and both are about *one capture*. The same capture has been built
    twice, so a rebuild that reproduces the same advice must not fail the run — there is
    nothing to disagree about.

    The same advice is not the same bytes, and the difference is the whole of this. The
    published envelopes are stamped with the moment the publish ran, and nothing in the
    site's build fixes that clock, so re-publishing one capture — which
    ``scripts.publish_gameweek_site`` does whenever it is re-run for a snapshot id — moves
    ``generated_at_utc`` and every ``published_sha256`` taken over bytes carrying it, while
    every payload stays byte-identical. That is a replay, and the first record stands.

    What a replay costs is worth stating rather than burying. The kept record's
    ``published_sha256`` names the bytes of the *first* publish, and the file now at that
    address carries the later stamp, so that digest no longer matches what is on disk.
    ``advice_sha256`` still does, and it is the digest that answers what the member was
    told. The alternative is rewriting a record so it carries a newer clock, and a record
    that can be rewritten proves nothing about what was published.

    A rebuild of that same capture that produces *different advice* is the case that
    matters: advice also depends on the projection handoff, switch artifacts, settings
    and code revision. Changed advice at the same capture's address is refused with
    the difference named; a changed publication clock does not soften that refusal.

    A *different* capture is not that. It is the next publish of the week — the mid-week
    build and the one taken shortly before the deadline are both real advice — and it lands
    at its own address rather than colliding with the earlier one.

    The record is built in a staging sibling and published by one rename, so it exists
    complete or not at all. A rename the system refuses while it still holds a handle on
    the bytes just written is waited out rather than treated as a verdict, and only a
    refusal that outlasts the whole budget gives up, as ``AdviceRecordNotLandedError``,
    which says the run recorded nothing, not that anything disagreed.
    """

    season = str(record["season"])
    gameweek = int(str(record["gameweek"]))
    entry_id = int(str(record["entry_id"]))
    capture = _record_capture(record)
    directory = record_directory(root, season, gameweek, entry_id, capture.snapshot_id)
    _refuse_legacy_layout(directory.parent)
    payload = encode_record(record)

    def _settled() -> Path:
        verify_manifest(directory)
        existing = (directory / RECORD_FILE).read_bytes()
        if existing == payload:
            return directory
        recorded = json.loads(existing.decode("utf-8"))
        if _is_replay(recorded, record):
            # The same advice, published again from the same capture at a later minute.
            # The first record stands: keeping it is what create-once means, and rewriting
            # it to carry the newer clock is the mutation this module exists to prevent.
            return directory
        raise AdviceRecordConflictError(_conflict(directory, recorded, record))

    if directory.exists():
        return _settled()
    with record_lock(directory):
        # Re-check under the lock: another writer may have landed the record between the
        # check above and the lock, and the second writer must not overwrite the first.
        if directory.exists():
            return _settled()
        # Staging siblings of a capture directory live in the member's week directory, so
        # that is the directory swept for the ones a dead writer left behind.
        prune_stale_staging(Path(root) / season / f"gw{gameweek:02d}", f"entry-{entry_id}")
        staging = staging_directory(directory)
        staging.mkdir(parents=True)
        landed = False
        try:
            (staging / RECORD_FILE).write_bytes(payload)
            write_manifest(staging, contract_version=MEMBER_ADVICE_RECORD_CONTRACT_VERSION)
            verify_manifest(staging)
            # One rename: the record exists complete or does not exist at all. Windows
            # refuses that rename while anything still holds a handle on the bytes written
            # a moment ago, and the same rename then succeeds, so it is waited out rather
            # than failed. It used to be a plain os.replace inside a clause that deleted
            # the staging and re-raised: a scanner reading advice.json for a fraction of a
            # second was enough to destroy a complete record of a capture that is already
            # spent, and to do it for a reason the next attempt would not have had.
            try:
                replace_retrying(staging, directory)
                landed = True
            except PermissionError:
                if not directory.exists():
                    raise
                # The one refusal no retry survives: a record is already at this address.
                # Under the lock that means another writer landed between the check above
                # and here, and the occupant is the answer - the same advice replays, and
                # different advice is the conflict it has always been. Ours is redundant
                # either way, so it is the staging that goes, not the record.
                return _settled()
            except RenameRefusedError as error:
                raise AdviceRecordNotLandedError(
                    f"The advice record for entry {entry_id} in {season} gameweek "
                    f"{gameweek} was staged complete and could not be published: {error} "
                    "Nothing was recorded for this capture and nothing was overwritten; "
                    "re-run the publish of this capture to record it."
                ) from error
        finally:
            # Everything that did not land is removed here, and only here: a staging that
            # landed *is* the record directory, and a staging that did not holds bytes
            # that are either incomplete or now redundant. Leaving one behind would leave
            # a half-written record beside the real ones for the stale sweep to find.
            if not landed:
                shutil.rmtree(staging, ignore_errors=True)
    return directory


__all__: tuple[str, ...] = (
    "LEGACY_LAYOUT_NOTE",
    "MEMBER_ADVICE_RECORD_CONTRACT_VERSION",
    "PLAYER_ID_SPACE",
    "RECORD_FILE",
    "AdviceRecordConflictError",
    "AdviceRecordError",
    "AdviceRecordNotLandedError",
    "PublishedAdvice",
    "RecordCapture",
    "build_member_advice_record",
    "encode_record",
    "entry_directory",
    "load_member_advice_record",
    "load_member_advice_record_for_deadline",
    "record_directory",
    "record_member_advice",
    "recorded_captures",
    "repository_commit",
)
