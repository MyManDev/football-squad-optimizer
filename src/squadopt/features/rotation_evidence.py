"""What a club said about who will start, as a table a decision can be made from.

The sibling of ``player_evidence_v1`` and deliberately built to the same discipline: one row
per roster player in the decision capture, always; every value stamped with the capture it
came from; and **absent distinguished from zero** in every column where the two could be
confused. What it adds is a claim, and the claim is the reason this file is careful.

**One claim field, and it is categorical.** ``rotation_disposition`` is a value from a closed
vocabulary or it is missing. There is no probability, likelihood, chance, score or confidence
anywhere in the table, and there never will be: a generated number of that kind is forbidden
on a member-facing surface *and* is an unmeasured claim besides. A ``confidence`` column is a
probability wearing a different hat, so it is in the forbidden set beside the obvious ones,
and the forbidden set is checked against this schema at import time rather than only against
a table at export time.

**The citation is a pointer, not a quote.** Columns 18-20 carry the source document's digest
and a byte span into it. The card resolves those against the locally held snapshot bytes when
it renders, so a member reads the manager's own words while this table carries none of them --
and the words shown are provably the words captured, because the digest is checked first.

**The chain is frozen before the decision.** Every club document must have been fetched
strictly before the decision capture was taken, and a week that breaks that is refused rather
than published with a caveat: if the bytes were fetched after the capture, the words could
have been chosen after seeing it. What that refusal does *not* cover is the model's own call
instant, which closes where the response gets a capture of its own.

**Absent and zero, twice over.** ``rotation_claim_observed`` and ``model_evidence_observed``
are never missing: they say whether the process ran and produced anything for this player, so
a player nobody wrote about is distinguishable from a player who was written about and not
mentioned. Every feed field a payload does not carry refuses the build rather than becoming a
column of nulls, because a missing field is the source having renamed something, not an
observation of nothing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.claim_identity import (
    ResolvedClaim,
    resolve_claim_player,
    roster_from_short_names,
)
from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    PUBLISHED_PRECISIONS,
    ROTATION_DISPOSITIONS,
    RawDocument,
)
from squadopt.data.sources.club_news_claims import ParsedClaim
from squadopt.data.sources.club_news_coding import UnlocatableClaim
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    availability_snapshot,
    fixture_snapshot,
    news_snapshot,
    scout_snapshot,
    short_name_roster,
    team_codes,
    team_names,
)
from squadopt.data.timestamps import as_instant

#: This table's contract. A row written under one version is not readable under another.
CONTRACT_VERSION: Final = "rotation_evidence_v2"

#: The locked holdout. Evidence for it is not built, listed or fingerprinted.
LOCKED_HOLDOUT_SEASON: Final = "2025-26"

#: How the feed's editorial note is read, as three states that must never collapse into one
#: another. A player who has never been flagged carries no stamp at all; a player who was
#: flagged and has since been cleared carries an empty note with the stamp still on it.
#: "Nothing is wrong with him" and "nobody has said anything about him" are different facts.
FEED_NEWS_STATES: Final[tuple[str, ...]] = ("never_flagged", "cleared", "flagged")

#: How far before the deadline a kickoff counts as midweek. Four days, so a Tuesday or
#: Wednesday match before a Saturday deadline is inside it and the previous weekend is not.
MIDWEEK_WINDOW_DAYS: Final = 4

#: The gameweek before which there is no previous round to have been played midweek.
MIN_TARGET_GAMEWEEK: Final = 2

#: The 28 columns, in the one order they are ever written or read. The "absent means" contract
#: for each lives in ``docs/rotation_evidence_contract.md`` and in the builder's guards.
ROTATION_EVIDENCE_COLUMNS: Final[tuple[str, ...]] = (
    "contract_version",
    "season",
    "target_gameweek",
    "player_id",
    "captured_at_utc",
    "deadline_timestamp_utc",
    "source_snapshot_ids",
    "timing_verified",
    "feed_status",
    "feed_chance_of_playing_next_round",
    "feed_news_state",
    "feed_news_added_utc",
    "feed_scout_risk_count",
    "feed_scout_news_link_present",
    "club_source_covered",
    "rotation_claim_observed",
    "rotation_claim_unresolved",
    "rotation_disposition",
    "rotation_claim_source_sha256",
    "rotation_claim_span_start",
    "rotation_claim_span_end",
    "rotation_claim_published_at_utc",
    "rotation_claim_published_precision",
    "rotation_claim_speaker",
    "model_identifier",
    "prompt_sha256",
    "model_response_sha256",
    "model_evidence_observed",
    "fixture_context_midweek",
)

# The pandas dtype each column is cast to. The nullable families carry ``pd.NA`` rather than a
# sentinel, so a missing count is never a zero and a missing flag is never False. Left to
# inference, a span column would be int64 when a claim was located and object when none was,
# and the same contract would then carry different dtypes across weeks.
_ROTATION_EVIDENCE_DTYPES: Final[Mapping[str, str]] = {
    "contract_version": "string",
    "season": "string",
    "target_gameweek": "int64",
    "player_id": "int64",
    "captured_at_utc": "string",
    "deadline_timestamp_utc": "string",
    "source_snapshot_ids": "string",
    "timing_verified": "boolean",
    "feed_status": "string",
    "feed_chance_of_playing_next_round": "Int64",
    "feed_news_state": "string",
    "feed_news_added_utc": "string",
    "feed_scout_risk_count": "Int64",
    "feed_scout_news_link_present": "boolean",
    "club_source_covered": "boolean",
    "rotation_claim_observed": "boolean",
    "rotation_claim_unresolved": "boolean",
    "rotation_disposition": "string",
    "rotation_claim_source_sha256": "string",
    "rotation_claim_span_start": "Int64",
    "rotation_claim_span_end": "Int64",
    "rotation_claim_published_at_utc": "string",
    "rotation_claim_published_precision": "string",
    "rotation_claim_speaker": "string",
    "model_identifier": "string",
    "prompt_sha256": "string",
    "model_response_sha256": "string",
    "model_evidence_observed": "boolean",
    "fixture_context_midweek": "boolean",
}

#: Names that would carry an identity, a raw quote or a generated number if they ever
#: appeared. The last group matters as much as the first: a ``confidence`` column is a
#: probability wearing a different hat, and so are ``score`` and ``p_start``.
FORBIDDEN_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        # Inherited from the Phase B evidence export, so the two tables forbid the same things.
        "entry",
        "entry_id",
        "entry_name",
        "player_name",
        "manager_name",
        "team_name",
        "news",
        # Free text and identities this table must never store, only point at.
        "quote",
        "text",
        "snippet",
        "headline",
        "title",
        "url",
        "source_url",
        "manager",
        "speaker_name",
        "reason",
        "notes",
        "summary",
        "rationale",
        # Generated numbers, under every name one arrives wearing.
        "probability",
        "likelihood",
        "chance",
        "score",
        "confidence",
        "p_start",
    }
)

# Checked here rather than only at export time. The export-time guard intersects the forbidden
# set with a table's own columns, which cannot fire while the exact-column check runs first --
# so it protects a caller's table and not the schema. This one protects the schema: adding a
# forbidden name to the tuple above stops the import, at the moment someone writes it.
_COLLIDING: Final[frozenset[str]] = frozenset(ROTATION_EVIDENCE_COLUMNS) & FORBIDDEN_COLUMNS
if _COLLIDING:
    raise AssertionError(f"{CONTRACT_VERSION} declares forbidden column(s) {sorted(_COLLIDING)!r}.")

_MISSING_DTYPES: Final[frozenset[str]] = frozenset(ROTATION_EVIDENCE_COLUMNS) ^ frozenset(
    _ROTATION_EVIDENCE_DTYPES
)
if _MISSING_DTYPES:
    raise AssertionError(
        f"{CONTRACT_VERSION} column and dtype tables disagree on {sorted(_MISSING_DTYPES)!r}."
    )


@dataclass(frozen=True, slots=True)
class ModelProvenance:
    """Which model said it, from which prompt, and which response the rows came from.

    **One of these per club**, collected in :class:`ClubModelProvenance`. That was written
    here as a prediction before the model call existed -- "in production a model is called
    once per club, so this becomes one of these per club" -- and it is now what the table
    takes: a row's ``model_response_sha256`` is the digest of *that player's club's*
    response, not of whichever response happened to be the only one.
    """

    identifier: str
    version: str
    prompt_sha256: str
    response_sha256: str

    def __post_init__(self) -> None:
        for name in ("identifier", "version", "prompt_sha256", "response_sha256"):
            if not str(getattr(self, name)).strip():
                raise InvalidValueError(
                    f"Model provenance {name} must be non-empty; without it a claim cannot "
                    "be replayed."
                )


@dataclass(frozen=True, slots=True)
class ClubModelProvenance:
    """One :class:`ModelProvenance` per club, and the week held to a single instrument.

    A model is called once per club, so a week has as many responses as clubs it read. The
    table needs to say which of them a given row came from: two players from different clubs
    have their dispositions from two different responses, and a single digest written across
    every row would make one of those claims point at bytes it was never coded from.

    **The identity is checked for agreement rather than recorded per club.** The manifest
    carries one ``model_identifier``, one ``model_version`` and one ``prompt_sha256``, so a
    week answered by two different models -- or asked two different questions -- is a mixture
    the manifest cannot express. That is refused here rather than averaged, for the same
    reason the coding call declares no fallback model: a week whose claims came from
    somewhere other than the model the manifest names is not a week anyone can check.

    The mapping is copied on construction. A caller that kept a reference to its own dict and
    edited it afterwards would be editing a manifest that has already been written.
    """

    by_club: Mapping[str, ModelProvenance]

    def __post_init__(self) -> None:
        if not self.by_club:
            raise InvalidValueError(
                "Model provenance must name at least one club; a week in which no club was "
                "coded carries no provenance rather than an empty one."
            )
        for club, provenance in self.by_club.items():
            if not club.strip():
                raise InvalidValueError(
                    f"A club must be named; {club!r} keys provenance {provenance.identifier!r}."
                )
        for field_name in ("identifier", "version", "prompt_sha256"):
            values = {getattr(entry, field_name) for entry in self.by_club.values()}
            if len(values) > 1:
                raise InvalidValueError(
                    f"The clubs disagree about {field_name}: {sorted(values)!r}. The manifest "
                    "states one of each, so a week coded by more than one model, or under "
                    "more than one prompt, is refused rather than recorded as if it were one."
                )
        object.__setattr__(self, "by_club", MappingProxyType(dict(self.by_club)))

    @property
    def identifier(self) -> str:
        """The model every club was coded by."""

        return next(iter(self.by_club.values())).identifier

    @property
    def version(self) -> str:
        """The model version that answered every club."""

        return next(iter(self.by_club.values())).version

    @property
    def prompt_sha256(self) -> str:
        """The one question, digested. The instrument, not the sample."""

        return next(iter(self.by_club.values())).prompt_sha256

    @property
    def response_sha256s(self) -> tuple[str, ...]:
        """Every response digest the week holds, sorted and without repeats.

        Deduplicated because one response can legitimately cover several clubs -- the fixture
        provider answers once for all of them -- and a manifest listing the same digest twice
        would imply two calls where there was one.
        """

        return tuple(sorted({entry.response_sha256 for entry in self.by_club.values()}))

    def response_sha256_for(self, club: str) -> str:
        """The digest of the response that coded ``club``, or refuse.

        Refusing is the point. A claim attributed to a club nobody called is a claim with no
        bytes behind it, and writing some other club's digest beside it would give it a
        citation to a response that never mentioned him.
        """

        provenance = self.by_club.get(club)
        if provenance is None:
            raise DataSourceError(
                f"No model response is recorded for {club!r}, yet a claim was placed on one "
                f"of its players. The week coded {sorted(self.by_club)!r}."
            )
        return provenance.response_sha256


def _news_state(news: object, news_added: object) -> str:
    """Read the feed's editorial note as one of three states.

    The stamp, not the text, decides whether a player has ever been flagged. A note that has
    been emptied keeps its stamp, and that is the ``cleared`` state -- which is a statement
    about the player, unlike ``never_flagged``, which is a statement about the feed.
    """

    stamped = not (news_added is None or news_added is pd.NA)
    if not stamped:
        return "never_flagged"
    written = "" if news is None or news is pd.NA else str(news).strip()
    return "flagged" if written else "cleared"


def _team_code_by_name(bootstrap: bytes) -> dict[str, int]:
    """Map a club's published name to its persistent code.

    Two hops, because the payload keys clubs by a per-season integer that denotes different
    clubs in different seasons, while the fixture table identifies one by its persistent code.
    """

    names = team_names(bootstrap)
    codes = team_codes(bootstrap)
    mapping: dict[str, int] = {}
    for season_id, name in names.items():
        code = codes.get(season_id)
        if code is None:
            raise DataSourceError(
                f"Team id {season_id} has a name but no persistent code; the two team "
                "readings disagree about the same capture."
            )
        mapping[name] = code
    return mapping


def _midweek_clubs(
    fixtures: pd.DataFrame, *, target_gameweek: int, deadline_timestamp_utc: str
) -> frozenset[int]:
    """Clubs with a kickoff in the four days before the deadline, or a refusal.

    Coverage is checked before the answer is given. If any fixture in the target gameweek or
    the one before it has no kickoff time, then for at least one club we cannot say whether it
    played in the window -- and a ``False`` that means "we could not tell" is the failure this
    whole table is built to avoid. So the build refuses instead, naming the gap.

    ``kickoff_time_utc`` is nullable by contract precisely because a fixture can be assigned to
    a gameweek before its time is confirmed. Nothing has read it until now; this is its first
    consumer, and the refusal is what makes reading it safe.
    """

    deadline = as_instant(deadline_timestamp_utc)
    window_start = deadline - timedelta(days=MIDWEEK_WINDOW_DAYS)
    relevant = fixtures.loc[fixtures["gameweek"].isin([target_gameweek - 1, target_gameweek])]
    if relevant.empty:
        raise DataSourceError(
            f"The captured calendar holds no fixtures for gameweeks "
            f"{target_gameweek - 1} or {target_gameweek}, so whether a club played in the "
            f"{MIDWEEK_WINDOW_DAYS} days before the deadline cannot be read."
        )
    unknown = relevant.loc[relevant["kickoff_time_utc"].isna(), "fixture_id"].tolist()
    if unknown:
        raise DataSourceError(
            f"{len(unknown)} fixture(s) around gameweek {target_gameweek} carry no kickoff "
            f"time (for example {unknown[:5]!r}), so the {MIDWEEK_WINDOW_DAYS}-day window "
            "before the deadline is not covered. A midweek flag would mean 'we could not "
            "tell' rather than 'did not play', so the build refuses."
        )
    kickoffs = pd.to_datetime(relevant["kickoff_time_utc"], utc=True, errors="raise")
    inside = relevant.loc[(kickoffs >= window_start) & (kickoffs < deadline)]
    return frozenset(int(value) for value in inside["team_id"].tolist())


@dataclass(frozen=True, slots=True)
class _ClaimRow:
    """One resolved claim, reduced to the columns a row carries."""

    disposition: str
    source_sha256: str
    span_start: int
    span_end: int
    published_at_utc: str | None
    published_precision: str
    speaker: str


def _resolved_claims(
    claims: Sequence[ParsedClaim], roster: pd.DataFrame
) -> tuple[dict[int, _ClaimRow], dict[str, int]]:
    """Place each claim on a player, counting the ones that could not be placed.

    An unplaced claim does not refuse the week. The three reasons are counted separately
    because they mean different things -- a club we never read, a name that matches nobody,
    and a name that matches two players -- and a resolver that guessed at the third would
    attribute a manager's words to the wrong footballer.
    """

    seam_roster = roster_from_short_names(roster)
    placed: dict[int, _ClaimRow] = {}
    unresolved: dict[str, int] = {}
    for claim in claims:
        identity = resolve_claim_player(claim.player_name, claim.team_name, seam_roster)
        if not isinstance(identity, ResolvedClaim):
            unresolved[identity.reason] = unresolved.get(identity.reason, 0) + 1
            continue
        if identity.player_id in placed:
            raise InvalidValueError(
                f"Two claims resolve to player {identity.player_id}; the table carries one "
                "disposition per player and the parser is supposed to have refused this."
            )
        placed[identity.player_id] = _ClaimRow(
            disposition=claim.disposition,
            source_sha256=claim.source_sha256,
            span_start=claim.span_start,
            span_end=claim.span_end,
            published_at_utc=claim.published_at_utc,
            published_precision=claim.published_precision,
            speaker=claim.speaker,
        )
    return placed, unresolved


def _unverifiable_players(
    dropped: Sequence[UnlocatableClaim], roster: pd.DataFrame
) -> frozenset[int]:
    """Which roster players had a claim whose citation could not be verified.

    Resolved through the same seam the placed claims use, so "the model wrote about him" is
    decided the same way whichever side of the locator the claim came out on. A dropped claim
    naming somebody the roster does not carry is itself dropped: it would be a source error
    about a player this week never had, and the table has no row to put it on.
    """

    seam_roster = roster_from_short_names(roster)
    players: set[int] = set()
    for claim in dropped:
        identity = resolve_claim_player(claim.player_name, claim.team_name, seam_roster)
        if isinstance(identity, ResolvedClaim):
            players.add(identity.player_id)
    return frozenset(players)


def _timing_verified(
    *,
    captured_at_utc: str,
    deadline: datetime,
    claim: _ClaimRow | None,
    fetched: Sequence[str],
) -> bool:
    """Whether every instant this row rests on is strictly before the deadline.

    A day-precision dateline is deliberately not compared. It names a calendar day and no
    time, so testing it against an instant would require inventing one -- and the invented
    time would decide the answer. Such a row's timing rests on the capture and fetch instants,
    which are ours and are exact. The contract document says so rather than leaving a reader
    to assume the check is stronger than it is.
    """

    instants = [captured_at_utc, *fetched]
    if claim is not None and claim.published_precision == "instant":
        if claim.published_at_utc is None:
            raise InvalidValueError(
                "A claim with instant precision must carry the instant it was published."
            )
        instants.append(claim.published_at_utc)
    return all(as_instant(value) < deadline for value in instants)


def _require_documents_precede_the_capture(
    documents: Sequence[RawDocument], captured_at_utc: str
) -> None:
    """Refuse a week whose club documents were fetched after the decision capture.

    This is the half of the lane's ordering constraint that a per-row flag cannot express.
    ``timing_verified`` says every instant a row rests on is earlier than the *deadline*,
    which is a fact about the claim. This is a fact about the **method**: if the club bytes
    were fetched after the capture was taken, then whoever fetched them could have looked at
    the capture first, noticed a player who looked wrong, and gone hunting for words about
    him. No amount of promptness escapes that, and no column can record it as partially
    true — the artifact is either built on a chain that was frozen before the decision or it
    is not, so the build refuses rather than publishing a table with a caveat.

    **What this does not close.** The model's own call instant is not checked here, because a
    response carries no timestamp and the club-news capture arrives as an identifier rather
    than as a snapshot. That half closes in A6, where the response is written into a capture
    with its own stamped instant. Said here rather than left for a reader to assume the check
    is stronger than it is.
    """

    captured = as_instant(captured_at_utc)
    late = [
        document.requested_url
        for document in documents
        if as_instant(document.fetched_at_utc) >= captured
    ]
    if late:
        raise DataSourceError(
            f"{len(late)} club document(s) were fetched at or after the decision capture at "
            f"{captured_at_utc} (for example {late[:3]!r}). The claim chain has to be frozen "
            "before the capture, or the words could have been chosen after seeing it."
        )


def _require_provenance_covers_claimed_clubs(
    model: ClubModelProvenance, roster: pd.DataFrame, placed: Mapping[int, _ClaimRow]
) -> None:
    """Name every club that has a claim but no response, at once.

    Before the rows rather than inside them, in the house style of the configuration reader:
    a caller that wired the provenance up wrongly wants the whole list, not the first club
    the loop happens to reach.
    """

    club_by_player = {
        int(player_id): str(team_name)
        for player_id, _web_name, team_name in roster.itertuples(index=False, name=None)
    }
    missing = sorted(
        {
            club_by_player[identifier]
            for identifier in placed
            if identifier in club_by_player and club_by_player[identifier] not in model.by_club
        }
    )
    if missing:
        raise DataSourceError(
            f"Claims were placed on players of {missing!r}, but no model response is recorded "
            f"for those clubs; the week coded {sorted(model.by_club)!r}. A disposition whose "
            "response cannot be named is not traceable to any bytes."
        )


def build_rotation_evidence_table(
    *,
    season: str,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    decision_snapshot: CapturedSnapshot,
    claims: Sequence[ParsedClaim],
    documents: Sequence[RawDocument],
    clubs_declared: Sequence[str],
    clubs_covered: Sequence[str],
    model: ClubModelProvenance | None,
    unverifiable_claims: Sequence[UnlocatableClaim] = (),
    club_news_snapshot_id: str | None = None,
) -> pd.DataFrame:
    """Build one week's rotation evidence: one row per roster player, always.

    ``season`` is required and not derived, for the same reason Phase B requires it: the
    captured payloads publish no season label and guessing one would mislabel every row.

    The completeness identity is ``row_count == roster_size``. There is no arithmetic identity
    available for a model's coverage -- nothing here sums to a known total the way elite picks
    do -- so the honest replacement is that every roster player gets a row and the flags say
    what was and was not observed for him.

    Diagnostics the manifest needs but no column should carry ride on ``DataFrame.attrs``:
    which clubs were declared and covered, which documents were read and their digests, how
    many claims were coded, how many could not be placed and why, and how many players nothing
    was said about.
    """

    if season == LOCKED_HOLDOUT_SEASON:
        raise DataSourceError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout; evidence for it is not built, "
            "listed or fingerprinted."
        )
    if not season.strip():
        raise InvalidValueError("season must be non-empty.")
    if target_gameweek < MIN_TARGET_GAMEWEEK:
        raise InvalidValueError(
            f"A midweek reading needs the previous round, so the target gameweek must be at "
            f"least {MIN_TARGET_GAMEWEEK}, got {target_gameweek}."
        )
    if not clubs_declared:
        raise InvalidValueError(
            "At least one club must be declared; a week that set out to read nothing has no "
            "coverage to record."
        )
    uncovered = sorted(set(clubs_covered) - set(clubs_declared))
    if uncovered:
        raise InvalidValueError(
            f"Clubs {uncovered!r} are covered but were never declared; coverage cannot exceed "
            "what the week set out to read."
        )
    deadline = as_instant(deadline_timestamp_utc)

    bootstrap = decision_snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    fixtures_payload = decision_snapshot.payloads.get(FIXTURES_PAYLOAD)
    if bootstrap is None or fixtures_payload is None:
        raise DataSourceError(
            f"The decision capture must carry {BOOTSTRAP_PAYLOAD!r} and {FIXTURES_PAYLOAD!r}; "
            f"it holds {sorted(decision_snapshot.payloads)!r}."
        )

    roster = short_name_roster(bootstrap)
    feed = news_snapshot(bootstrap).set_index("player_id")
    availability = availability_snapshot(bootstrap).set_index("player_id")
    scout = scout_snapshot(bootstrap).set_index("player_id")
    fixtures = fixture_snapshot(
        fixtures_payload,
        bootstrap,
        season=season,
        snapshot_id=decision_snapshot.metadata.snapshot_id,
        captured_at_utc=decision_snapshot.metadata.captured_at_utc,
    )
    midweek = _midweek_clubs(
        fixtures,
        target_gameweek=target_gameweek,
        deadline_timestamp_utc=deadline_timestamp_utc,
    )
    code_by_name = _team_code_by_name(bootstrap)
    placed, unresolved = _resolved_claims(claims, roster)
    unverifiable = _unverifiable_players(unverifiable_claims, roster)
    if model is not None:
        _require_provenance_covers_claimed_clubs(model, roster, placed)

    captured_at_utc = decision_snapshot.metadata.captured_at_utc
    decision_id = decision_snapshot.metadata.snapshot_id
    _require_documents_precede_the_capture(documents, captured_at_utc)
    fetched_by_digest = {document.requested_url: document.fetched_at_utc for document in documents}
    covered = {name for name in clubs_covered}

    rows: list[dict[str, object]] = []
    for player_id, web_name, team_name in roster.itertuples(index=False, name=None):
        identifier = int(player_id)
        del web_name
        club = str(team_name)
        if identifier not in feed.index or identifier not in scout.index:
            raise DataSourceError(
                f"Player {identifier} is on the roster but absent from the feed readings of "
                "the same capture; the capture disagrees with itself."
            )
        claim = placed.get(identifier)
        club_covered = club in covered
        fetched = [] if claim is None else sorted(set(fetched_by_digest.values()))
        team_code = code_by_name.get(club)
        if team_code is None:
            raise DataSourceError(
                f"Club {club!r} is on the roster but has no persistent code in the same capture."
            )
        # Only the snapshots this row was actually read from. A capture that contributed
        # nothing to it is not a source, and listing it would let the row claim an input it
        # never used.
        sources = {decision_id}
        if claim is not None and club_news_snapshot_id:
            sources.add(club_news_snapshot_id)
        rows.append(
            {
                "contract_version": CONTRACT_VERSION,
                "season": season,
                "target_gameweek": target_gameweek,
                "player_id": identifier,
                "captured_at_utc": captured_at_utc,
                "deadline_timestamp_utc": deadline_timestamp_utc,
                "source_snapshot_ids": ";".join(sorted(sources)),
                "timing_verified": _timing_verified(
                    captured_at_utc=captured_at_utc,
                    deadline=deadline,
                    claim=claim,
                    fetched=fetched,
                ),
                "feed_status": feed.loc[identifier, "status"],
                "feed_chance_of_playing_next_round": availability.loc[
                    identifier, "chance_of_playing"
                ],
                "feed_news_state": _news_state(
                    feed.loc[identifier, "news"], feed.loc[identifier, "news_added_utc"]
                ),
                "feed_news_added_utc": feed.loc[identifier, "news_added_utc"],
                "feed_scout_risk_count": scout.loc[identifier, "scout_risk_count"],
                "feed_scout_news_link_present": scout.loc[identifier, "scout_news_link_present"],
                "club_source_covered": club_covered,
                # Never NA. False says the process ran and produced no disposition for him,
                # which is a different fact from his club never having been read.
                "rotation_claim_observed": claim is not None,
                # Never NA either, and the reason this column exists: True says a claim was
                # made about him and its citation could not be verified. Without it that
                # player reads as "his club was read and said nothing about him", which is
                # false -- something was said, and we could not stand behind the quote.
                "rotation_claim_unresolved": identifier in unverifiable,
                "rotation_disposition": pd.NA if claim is None else claim.disposition,
                "rotation_claim_source_sha256": pd.NA if claim is None else claim.source_sha256,
                "rotation_claim_span_start": pd.NA if claim is None else claim.span_start,
                "rotation_claim_span_end": pd.NA if claim is None else claim.span_end,
                "rotation_claim_published_at_utc": (
                    pd.NA
                    if claim is None or claim.published_at_utc is None
                    else claim.published_at_utc
                ),
                "rotation_claim_published_precision": (
                    pd.NA if claim is None else claim.published_precision
                ),
                "rotation_claim_speaker": pd.NA if claim is None else claim.speaker,
                "model_identifier": pd.NA if model is None else model.identifier,
                "prompt_sha256": pd.NA if model is None else model.prompt_sha256,
                # This player's club's response, not the week's only one. Two players from
                # two clubs were coded by two calls, and a single digest across every row
                # would give one of them a citation to bytes he never appeared in.
                "model_response_sha256": (
                    pd.NA if model is None or claim is None else model.response_sha256_for(club)
                ),
                # Computed from the model's own coverage rather than aliased to the column
                # above. Today the model is the only claim source, so the two agree on every
                # row; a later feed-derived disposition would set one without the other, and
                # a table that had aliased them could not say so.
                "model_evidence_observed": model is not None and claim is not None,
                "fixture_context_midweek": team_code in midweek,
            }
        )

    if not rows:
        raise DataSourceError("The decision capture declares no squad-eligible players.")

    table = pd.DataFrame(rows, columns=list(ROTATION_EVIDENCE_COLUMNS))
    table = table.astype(dict(_ROTATION_EVIDENCE_DTYPES))
    table = table.sort_values("player_id", kind="stable").reset_index(drop=True)
    _require_closed_vocabularies(table)

    table.attrs.update(
        {
            "roster_size": len(roster),
            "roster_snapshot_id": decision_id,
            "source_snapshot_ids": _union_of_row_sources(table),
            "clubs_declared": tuple(sorted(set(clubs_declared))),
            "clubs_covered": tuple(sorted(covered)),
            "documents_read": len(documents),
            "document_sha256s": tuple(
                sorted({claim.source_sha256 for claim in claims}),
            ),
            "claims_coded": len(placed),
            # Two different "unresolved". This one counts claims whose *player* could not be
            # resolved -- a name matching nobody, or two footballers. The one below counts
            # claims whose *citation* could not be verified, which is a source error about a
            # player we did identify. Near names, unrelated facts.
            "claims_unresolved": tuple(sorted(unresolved.items())),
            "claims_unverifiable_citation": len(unverifiable_claims),
            "players_with_unverifiable_citation": tuple(sorted(unverifiable)),
            "claims_ambiguous": unresolved.get("ambiguous", 0),
            "players_not_addressed": len(roster) - len(placed),
            "model_identifier": None if model is None else model.identifier,
            "model_version": None if model is None else model.version,
            "prompt_sha256": None if model is None else model.prompt_sha256,
            "response_sha256s": () if model is None else model.response_sha256s,
            "deadline_timestamp_utc": deadline_timestamp_utc,
        }
    )
    return table


def _union_of_row_sources(table: pd.DataFrame) -> tuple[str, ...]:
    """Every snapshot any row was read from, sorted.

    Per-row provenance is what the contract asks for, so the manifest carries the union
    rather than a single value. Phase B's table can compare its manifest against one row's
    field because its provenance is constant; this one cannot, and the reader knows it.
    """

    identifiers: set[str] = set()
    for value in table["source_snapshot_ids"].tolist():
        identifiers.update(part for part in str(value).split(";") if part)
    return tuple(sorted(identifiers))


def _require_closed_vocabularies(table: pd.DataFrame) -> None:
    """Every categorical column carries a declared value or nothing at all."""

    for column, allowed in (
        ("rotation_disposition", ROTATION_DISPOSITIONS),
        ("rotation_claim_published_precision", PUBLISHED_PRECISIONS),
        ("rotation_claim_speaker", CLAIM_SPEAKERS),
        ("feed_news_state", FEED_NEWS_STATES),
    ):
        observed = {str(value) for value in table[column].dropna().tolist()}
        unknown = sorted(observed - set(allowed))
        if unknown:
            raise InvalidValueError(
                f"{column} carries {unknown!r}, outside its closed vocabulary {list(allowed)!r}."
            )


__all__ = [
    "CONTRACT_VERSION",
    "FEED_NEWS_STATES",
    "FORBIDDEN_COLUMNS",
    "MIDWEEK_WINDOW_DAYS",
    "MIN_TARGET_GAMEWEEK",
    "ROTATION_EVIDENCE_COLUMNS",
    "ClubModelProvenance",
    "ModelProvenance",
    "build_rotation_evidence_table",
]
