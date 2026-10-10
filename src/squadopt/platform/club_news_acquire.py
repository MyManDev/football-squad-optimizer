"""Acquire one week's club news and name the capture it wrote.

    python -m scripts.capture_club_news --roster-snapshot <id>

The consumption half of this lane has been production code for a while:
``rotation_export`` rebuilds a week from a capture with no network and no model at all. The
acquisition half existed only as a twenty-five line helper inside an integration test, so the
path worked and had no name. This is that helper, promoted, with the things a test does not
need: a registry it did not choose, refusals it has to record, and an id it has to print.

**It runs before the FPL capture, not after.**
:mod:`squadopt.features.rotation_evidence` refuses any week whose club documents carry a fetch
instant at or after the decision capture, because a document read after the decision cannot
have informed it. That is a rule about the order of the week, and this command is the step it
constrains.

**The roster comes from a capture already on disk**, named by ``--roster-snapshot``, rather
than from a fresh call to the platform. The roster is only there so the model can resolve a
short name to a player; fetching one would add a second network target to a command whose
whole reach should be the club hosts the registry names.

**There is no fixture path here.** A run with no key refuses, loudly, from
``club_news_provider``. "We could not ask" and "the fixture said" are different facts, and a
convenience branch in this command would be the one place that quietly merged them.

**Four instants, four meanings.** They are kept apart because each answers a different
question, and a run that let one stand in for another would report a time nobody observed.

- *Publication*: when the club says an article was published. It comes from the held page's
  own verifiable fields and is never rewritten by this command.
- *Fetch*: when one page was read. Each document carries its own.
- *Coding observation*: the one instant the week's coding looks from. It is taken once, after
  the last page was read, and it is what the document selection, the model's decision
  context and the target-deadline check all use. Taken before the fetch, as it used to be,
  it turned an article published while the pages were being read into one "published after
  the observation" although the page in hand already carried it.
- *Capture completion*: when the capture was written, after coding and still before the
  target deadline.

The target gameweek is settled before any page is read, from the instant the run started.
The coding observation must still fall before that same deadline. If the deadline passed
while the pages were being read, the run stops: it does not code against a closed week, and
it does not move to the next gameweek on its own.
The same check runs again just before the capture is written. If the deadline passed while
the model was answering, or the clock went back past the observation, the run stops with
Refused and writes nothing; the calls it made are spent.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from squadopt.contracts.injuries import require_official_injury_source
from squadopt.data.claim_identity import roster_from_short_names
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import (
    ClubNewsError,
    ClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_capture import (
    CodedClub,
    read_captured_responses,
    write_club_news_capture,
)
from squadopt.data.sources.club_news_selection import DocumentSelection, select_coding_documents
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    gameweek_deadlines,
    next_open_deadline,
    short_name_roster,
    team_names,
)
from squadopt.data.timestamps import as_instant
from squadopt.live.recommendation import season_from_bootstrap
from squadopt.platform.club_news_coverage import (
    build_club_news_coverage,
    build_coding_stage_report,
    format_club_news_coverage,
    format_coding_stage,
)
from squadopt.platform.club_news_fetch import (
    ClubSource,
    Opener,
    default_opener,
    fetch_registered_documents,
    load_club_sources,
)
from squadopt.platform.club_news_provider import (
    CodingProviderConfig,
    bind_coding_provider,
    check_coding_provider,
    code_week,
    coding_as_of,
    require_provider_dependency,
    resolve_provider_config,
    validate_provider_config,
)
from squadopt.platform.official_injury_capture import (
    read_official_injury_capture,
    registered_details_links,
)

REPOSITORY_ROOT = Path.cwd()

#: The fetcher's own defaults, named here so `acquire_week` can forward them rather than
#: re-declare what "no opener was given" means.
_default_opener = default_opener


def _utc_instant() -> datetime:
    return datetime.now(UTC)


DEFAULT_REGISTRY: Final = Path("data") / "sources" / "club_news_sources.json"
DEFAULT_SNAPSHOT_ROOT: Final = Path("data") / "snapshots"


@dataclass(frozen=True, slots=True)
class AcquiredWeek:
    """What one acquisition produced, before anything was written.

    The three coverage lists are computed here rather than downstream because this is the
    only moment that knows all of them: the registry says what was declared, the fetch says
    what was read, and the coding says what survived into an answer. Ten minutes later, from
    the payloads alone, a club whose second page was refused is indistinguishable from a club
    that only registered one.
    """

    documents: tuple[RawDocument, ...]
    coded: tuple[CodedClub, ...]
    clubs_declared: tuple[str, ...]
    clubs_covered: tuple[str, ...]
    clubs_partially_covered: tuple[str, ...]
    refused_pages: tuple[tuple[str, str], ...]
    refused_coding: tuple[tuple[str, str], ...]
    reused_clubs: tuple[str, ...] = ()
    document_selection: DocumentSelection | None = None
    #: The instant the coding looked from, when this run took one after the fetch.
    coding_observed_at: str | None = None
    #: Calls to the provider begun in this run, answered or failed.
    model_calls_attempted: int = 0
    #: Which kind of refusal each entry of ``refused_coding`` was, in the same order.
    coding_refusal_kinds: tuple[tuple[str, str], ...] = ()


def _coverage(
    sources: Sequence[ClubSource],
    documents: Sequence[RawDocument],
    coded: Sequence[CodedClub],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Declared, covered, and covered-in-part, as the evidence contract defines them.

    **Covered means read *and* coded.** A club whose pages were read but whose call failed has
    nothing that survives into evidence, and the table would refuse it anyway: provenance is
    per club, and a covered club with no response is a club the manifest cannot describe. It
    is the same rule the contract already states for a club whose every claim lost its
    citation.

    **Partly covered means covered, with at least one registered page unread.** It narrows
    coverage and never replaces it, so every name here is also in the covered list.
    """

    declared = tuple(dict.fromkeys(source.club for source in sources))
    answered = {entry.club for entry in coded}
    read_by_club: dict[str, set[str]] = {}
    for document in documents:
        read_by_club.setdefault(document.club, set()).add(document.requested_url)

    covered = tuple(club for club in declared if club in answered and club in read_by_club)
    registered: dict[str, set[str]] = {}
    for source in sources:
        registered.setdefault(source.club, set()).add(source.url)
    partial = tuple(
        club for club in covered if not registered.get(club, set()) <= read_by_club.get(club, set())
    )
    return declared, covered, partial


#: Builds the provider once the coding observation instant is known. Raising
#: :class:`ClubNewsError` here stops the week before any model request.
BindCoding = Callable[[str], tuple[ClubNewsProvider, CodingProviderConfig]]


def _instant_text(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def acquire_week(
    *,
    sources: Sequence[ClubSource],
    provider: ClubNewsProvider | None = None,
    config: CodingProviderConfig | None = None,
    roster: Sequence[RosterPlayer],
    opener: Opener = _default_opener,
    now: Callable[[], datetime] = _utc_instant,
    sleeper: Callable[[float], None] = time.sleep,
    check_robots: bool = True,
    max_calls: int | None = None,
    previous: Sequence[CodedClub] = (),
    additional_article_urls: Mapping[str, Sequence[str]] | None = None,
    bind_coding: BindCoding | None = None,
) -> AcquiredWeek:
    """Read the registered pages, code them club by club, and report what happened.

    Nothing is written here. The caller decides where a capture goes, and a rehearsal can walk
    this whole function without a store. ``opener`` and ``now`` are the fetcher's own
    parameters, forwarded rather than re-invented, so an offline test drives this exactly as
    it drives the fetch.

    The coding side is given in one of two ways. ``bind_coding`` is the acquisition command's:
    after the last page is read this function takes one instant from ``now`` and hands it
    over, and what comes back is the provider and configuration built for that instant. The
    selection, the model's decision context and the caller's own deadline check then all look
    from the same moment. ``provider`` with ``config`` is the direct form, for a caller that
    has already settled its context; nothing is observed here in that case.

    The documents are selected once, and that one selection is both what is coded and what
    is reported.
    """

    direct = provider is not None and config is not None
    if direct == (bind_coding is not None) or (provider is None) != (config is None):
        raise ClubNewsError(
            "Give either a provider with its configuration, or bind_coding, and not both."
        )
    documents, refused_pages = fetch_registered_documents(
        sources,
        opener=opener,
        now=now,
        sleeper=sleeper,
        check_robots=check_robots,
        additional_article_urls=additional_article_urls,
    )
    observed_at: str | None = None
    if bind_coding is not None:
        if not documents:
            # Nothing was read, so there is nothing to observe and no adapter to build.
            declared, _covered, _partial = _coverage(sources, documents, ())
            return AcquiredWeek(
                documents=(),
                coded=(),
                clubs_declared=declared,
                clubs_covered=(),
                clubs_partially_covered=(),
                refused_pages=refused_pages,
                refused_coding=(),
            )
        # After the fetch, never before. The order is checked rather than assumed: a page
        # stamped later than the instant the coding looks from would be read "in the future"
        # of its own selection, so the week stops.
        observed_at = _instant_text(now())
        late = [d for d in documents if as_instant(d.fetched_at_utc) > as_instant(observed_at)]
        if late:
            raise ClubNewsError(
                f"The coding observation {observed_at} is earlier than {len(late)} page "
                f"read(s), the latest at {max(d.fetched_at_utc for d in late)}; the clock "
                "went backwards, so nothing was coded."
            )
        provider, config = bind_coding(observed_at)
    if provider is None or config is None:  # pragma: no cover - excluded by the check above
        raise ClubNewsError("No coding provider was given.")
    selection = select_coding_documents(documents, as_of=coding_as_of(config))
    coding = code_week(
        provider,
        config,
        documents,
        roster,
        max_calls=max_calls,
        previous=previous,
        selection=selection,
    )
    coded, refused_coding = coding.coded, coding.refused
    declared, covered, partial = _coverage(sources, documents, coded)
    return AcquiredWeek(
        documents=documents,
        coded=coded,
        clubs_declared=declared,
        clubs_covered=covered,
        clubs_partially_covered=partial,
        refused_pages=refused_pages,
        refused_coding=refused_coding,
        reused_clubs=tuple(entry.club for entry in coded if any(entry is old for old in previous)),
        document_selection=selection,
        coding_observed_at=observed_at,
        model_calls_attempted=coding.calls_attempted,
        coding_refusal_kinds=coding.refusal_kinds,
    )


def select_club_sources(
    sources: Sequence[ClubSource], clubs: Sequence[str] | None
) -> tuple[ClubSource, ...]:
    """Restrict both fetches and model calls before contacting any host.

    Exact registry names are required; a typo must never broaden a paid run.
    Registry order is preserved, and duplicate selections do not repeat a call.
    """
    if clubs is None:
        return tuple(sources)
    selected = {name.strip() for name in clubs}
    known = {source.club for source in sources}
    if not selected or "" in selected or not selected <= known:
        raise ClubNewsError("Every selected club must exactly match a registered club name.")
    return tuple(source for source in sources if source.club in selected)


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roster-snapshot",
        help="a capture already on disk whose bootstrap supplies the short-name roster",
    )
    parser.add_argument("--registry", type=Path, default=REPOSITORY_ROOT / DEFAULT_REGISTRY)
    parser.add_argument(
        "--snapshot-root", type=Path, default=REPOSITORY_ROOT / DEFAULT_SNAPSHOT_ROOT
    )
    parser.add_argument("--settings-file", type=Path, help="private [llm] TOML settings")
    parser.add_argument(
        "--club",
        action="append",
        help="restrict acquisition to this exact registry club; repeat for more clubs",
    )
    parser.add_argument(
        "--capture-root",
        type=Path,
        help="write new news captures here; roster still comes from --snapshot-root",
    )
    parser.add_argument(
        "--max-model-calls",
        type=int,
        default=3,
        help="maximum paid requests in this run, from zero to twenty (default: 3)",
    )
    parser.add_argument(
        "--previous-news-capture",
        type=Path,
        help="optional earlier capture directory for unchanged evidence reuse",
    )
    parser.add_argument(
        "--official-injury-capture",
        type=Path,
        help="held official league injury capture; referrals remain inside selected registry paths",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="fetch and code, but write nothing")
    mode.add_argument(
        "--check-config", action="store_true", help="offline settings/dependency check"
    )
    arguments = parser.parse_args(argv)
    if not 0 <= arguments.max_model_calls <= 20:
        parser.error("--max-model-calls must be between zero and twenty")
    if not arguments.check_config and not arguments.roster_snapshot:
        parser.error("--roster-snapshot is required unless --check-config is selected")
    return arguments


def _raw_claim_count(entry: CodedClub) -> int | None:
    """How many claims one coded answer states, before any is checked against its source.

    ``None`` when the answer carries no list of claims at all. That is not an empty answer:
    an answer that states nothing says so with an empty list, and one without the list
    cannot be read as either.
    """

    rows = json.loads(entry.response.text).get("claims")
    return len(rows) if isinstance(rows, list) else None


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    opener: Opener = _default_opener,
    now: Callable[[], datetime] = _utc_instant,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Run one acquisition, or say why it was refused.

    ``opener``, ``now`` and ``sleeper`` are the fetcher's own seams, forwarded so the whole
    command can be rehearsed without a network or a wall clock. Their defaults are the real
    ones, so a production run gets the real ones without being told.
    """

    arguments = _parse_arguments(argv)
    try:
        if arguments.official_injury_capture is not None:
            require_official_injury_source()
        if arguments.check_config:
            config = check_coding_provider(environ, settings_file=arguments.settings_file)
            print(
                f"Configuration valid: provider {config.provider!r}, "
                f"model {config.model_identifier!r}."
            )
            if config.provider in ("openai", "openai-compatible"):
                # The two settings that shape the request and have a default, said so an
                # operator sees the format that will be asked for and not only the model.
                print(
                    f"Response format {config.response_format!r}, completion token limit "
                    f"{config.max_completion_tokens}."
                )
            print(
                "API key configured. Offline check only; "
                "authentication and service availability were not tested."
            )
            return 0
        registry_sources = load_club_sources(arguments.registry)
        sources = select_club_sources(registry_sources, arguments.club)
        roster_snapshot = read_snapshot(arguments.snapshot_root, arguments.roster_snapshot)
        bootstrap = roster_snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
        if bootstrap is None:
            raise DataError(
                f"{arguments.roster_snapshot} carries no {BOOTSTRAP_PAYLOAD!r}, so it cannot "
                "supply the short names a claim is matched against."
            )
        league_clubs = tuple(team_names(bootstrap).values())
        if len(set(league_clubs)) != len(league_clubs):
            raise ClubNewsError("Snapshot teams must have unique exact club names.")
        unknown = {source.club for source in sources} - set(league_clubs) - {"Example FC"}
        if unknown:
            raise ClubNewsError(
                "Selected source clubs do not match exact snapshot team names: "
                f"{sorted(unknown)!r}."
            )
        roster = roster_from_short_names(short_name_roster(bootstrap))
        # The run's own start. It settles the target gameweek and bounds the inputs that
        # must already exist (an earlier capture, a referral capture); it is not what the
        # coding observes from, which is taken after the pages are read.
        as_of = _instant_text(now())
        deadlines = gameweek_deadlines(bootstrap)
        deadline = next_open_deadline(deadlines, as_of_utc=as_of)
        season = season_from_bootstrap(bootstrap)
        target_context = {
            "season": season,
            "gameweek": deadline.gameweek,
            "deadline": deadline.deadline_utc,
        }
        referrals = None
        if arguments.official_injury_capture is not None:
            central_path = arguments.official_injury_capture
            central = read_official_injury_capture(
                read_snapshot(central_path.parent, central_path.name)
            )
            age = as_instant(as_of) - as_instant(central.observed_at)
            if central.season != season or not timedelta(0) <= age <= timedelta(days=7):
                raise ClubNewsError(
                    "Official injury referrals must be from this season "
                    "and a current prior capture."
                )
            referrals = registered_details_links(central, sources)
        previous: tuple[CodedClub, ...] = ()
        if arguments.previous_news_capture is not None:
            prior_path = arguments.previous_news_capture
            prior = read_snapshot(prior_path.parent, prior_path.name)
            if as_instant(prior.metadata.captured_at_utc) >= as_instant(as_of):
                raise ClubNewsError("Previous news capture must precede this run.")
            # The capture an answer was coded in, kept through a chain of reuses. An answer
            # the earlier capture had itself reused already names where it came from; naming
            # the earlier capture instead would move its origin one step with every run.
            previous = tuple(
                replace(
                    entry,
                    reused_from_snapshot=entry.reused_from_snapshot or prior.metadata.snapshot_id,
                )
                for entry in read_captured_responses(prior)
            )
        # Resolved and checked before any page is fetched, so a missing key, an unlisted
        # model or a client library that is not installed refuses with nothing read. The
        # adapter itself is built after the fetch.
        resolved = resolve_provider_config(environ, settings_file=arguments.settings_file)
        validate_provider_config(resolved)
        require_provider_dependency(resolved)

        def _bind(observed_at: str) -> tuple[ClubNewsProvider, CodingProviderConfig]:
            if as_instant(observed_at) < as_instant(as_of):
                raise ClubNewsError(
                    f"The coding observation {observed_at} is earlier than the run's start "
                    f"{as_of}; the clock went backwards, so nothing was coded."
                )
            try:
                still_open = next_open_deadline(deadlines, as_of_utc=observed_at)
            except DataError as error:
                raise ClubNewsError(
                    f"The gameweek {deadline.gameweek} deadline {deadline.deadline_utc} passed "
                    f"while the pages were being read (observed {observed_at}), and no later "
                    "deadline is published. Nothing was coded."
                ) from error
            if (
                still_open.gameweek != deadline.gameweek
                or still_open.deadline_utc != deadline.deadline_utc
            ):
                raise ClubNewsError(
                    f"The gameweek {deadline.gameweek} deadline {deadline.deadline_utc} passed "
                    f"while the pages were being read (observed {observed_at}). Nothing was "
                    f"coded, and gameweek {still_open.gameweek} was not substituted; start a "
                    "new run for it."
                )
            return bind_coding_provider(resolved, {**target_context, "as_of": observed_at})

        week = acquire_week(
            sources=sources,
            bind_coding=_bind,
            roster=roster,
            opener=opener,
            now=now,
            sleeper=sleeper,
            max_calls=arguments.max_model_calls,
            previous=previous,
            additional_article_urls=referrals,
        )
    except (ClubNewsError, DataError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 1

    config = resolved
    # The registry line counts what this run asked for. Under --club that is the filtered
    # part of the registry, and the coverage lines below count the whole registry.
    print(
        f"Registry      {len(sources)} pages, {len(week.clubs_declared)} clubs declared"
        + (
            f" (filtered by --club from {len(registry_sources)} registered pages)"
            if arguments.club
            else ""
        )
    )
    print(f"Read          {len(week.documents)} documents")
    if week.coding_observed_at is not None:
        print(
            f"Observed      {week.coding_observed_at}, after the last page was read, for "
            f"gameweek {deadline.gameweek} (deadline {deadline.deadline_utc})"
        )
    if week.document_selection is not None:
        print(f"Selected      {len(week.document_selection.documents)} documents for coding")
        for decision in week.document_selection.decisions:
            if not decision.selected:
                print(f"  unselected  {decision.club}: {decision.reason}; {decision.source_url}")
    print(f"Coded         {len(week.coded)} clubs, provider {config.provider!r}")
    raw_claims = {entry.club: _raw_claim_count(entry) for entry in week.coded}
    claim_count = sum(count or 0 for count in raw_claims.values())
    print(f"Raw claims    {claim_count}; source validation occurs during export")
    print(f"Reused        {len(week.reused_clubs)} unchanged club responses")
    print(
        f"Call budget   {arguments.max_model_calls}; {week.model_calls_attempted} attempted; "
        "no automatic provider retry"
    )
    print(f"Covered       {len(week.clubs_covered)} clubs")
    print(f"Partly read   {len(week.clubs_partially_covered)} clubs")
    print(
        format_club_news_coverage(
            build_club_news_coverage(
                roster_clubs=league_clubs,
                registry_sources=registry_sources,
                selected_sources=sources,
                documents=week.documents,
                coded_clubs=tuple(entry.club for entry in week.coded),
                covered_clubs=week.clubs_covered,
                partially_covered_clubs=week.clubs_partially_covered,
                refused_pages=week.refused_pages,
                refused_coding=week.refused_coding,
            )
        )
    )
    if week.document_selection is not None:
        print(
            format_coding_stage(
                build_coding_stage_report(
                    roster_clubs=league_clubs,
                    read_clubs=tuple(dict.fromkeys(d.club for d in week.documents)),
                    selection=week.document_selection,
                    raw_claims=raw_claims,
                    reused_clubs=week.reused_clubs,
                    refusal_kinds=week.coding_refusal_kinds,
                    model_calls_attempted=week.model_calls_attempted,
                )
            )
        )
    for club, reason in (*week.refused_pages, *week.refused_coding):
        print(f"  refused     {club}: {reason}")
    if not week.coded:
        print("Nothing was coded, so there is no week to capture.")
        return 1
    if arguments.dry_run:
        print("Dry run: nothing written.")
        return 0

    captured_at = "unavailable"
    try:
        captured_at = _instant_text(now())
        if week.coding_observed_at is not None and as_instant(captured_at) < as_instant(
            week.coding_observed_at
        ):
            raise ClubNewsError("The clock moved backwards after coding.")
        try:
            still_open = next_open_deadline(deadlines, as_of_utc=captured_at)
        except DataError as error:
            raise ClubNewsError(
                "The coding deadline passed before the capture was written, and no later "
                "deadline is published."
            ) from error
        if (
            still_open.gameweek != deadline.gameweek
            or still_open.deadline_utc != deadline.deadline_utc
        ):
            raise DataError(
                "The coding deadline is no longer the next open deadline. "
                f"Gameweek {still_open.gameweek} was not substituted; start a new run for it."
            )
    except (ClubNewsError, DataError, ValueError) as error:
        print(
            f"Refused: gameweek {deadline.gameweek} deadline {deadline.deadline_utc} "
            f"at capture completion {captured_at}: {error} Nothing was captured."
        )
        return 1

    metadata = write_club_news_capture(
        arguments.capture_root or arguments.snapshot_root,
        documents=week.documents,
        coded=week.coded,
        clubs_declared=week.clubs_declared,
        clubs_covered=week.clubs_covered,
        captured_at_utc=captured_at,
        clubs_partially_covered=week.clubs_partially_covered,
    )
    # The id is the point of the command: the weekly runner takes it next.
    print(f"Capture       {metadata.snapshot_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the shim
    sys.exit(main())


__all__ = ["AcquiredWeek", "acquire_week", "main", "select_club_sources"]
