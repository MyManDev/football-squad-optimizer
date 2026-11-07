import { useContext, useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useSearchParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { crossfade } from "../../../design/viewTransition";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { memberAddress } from "../../../lib/leagueAddresses";
import { ScoreboardSection } from "../components/ScoreboardCard";
import { LeagueContext } from "../LeagueContext";
import { useLeagueMembers, useLeagueScoreboard } from "../queries";
import { leagueRace } from "../race/leagueRace";
import { LeagueRaceCard } from "../race/LeagueRaceCard";
import { useForwardedLeague } from "./ForwardedLeagueContext";
import { MAX_STANDINGS_PAGE } from "../forwarder/documents";
import { standingsPage, useForwardedStandings } from "./reads";
import styles from "./ForwardedLeaguePage.module.css";

/**
 * A classic league the site does not publish, as its standings (#983 step 4): rank, team,
 * manager and total, read from the FPL forwarder a page of fifty at a time as the visitor
 * requests a page. Only that page is rendered, including in country leagues. Each team opens its member
 * page under the league. Nothing is published for such a league, so no history, race,
 * scoreboard or published plan appears here.
 */
export function ForwardedLeaguePage() {
  const [search] = useSearchParams();
  const league = useForwardedLeague();
  const named = search.get("page");
  // A table address naming no page opens at the page the tab last read of this league, so
  // the way back from a member's page in a country league lands where the visitor was.
  // Browsing within the table always names its page, so only an arrival reads as none.
  const remembered = named === null && league !== null ? rememberedPage(league.leagueId) : 1;
  if (remembered > 1) {
    const next = new URLSearchParams(search);
    next.set("page", String(remembered));
    return <Navigate to={{ search: `?${next.toString()}` }} replace />;
  }
  return <ForwardedLeagueTable key={standingsPage(named)} />;
}

const PAGE_KEY = (leagueId: number) => `squadopt.forwarded.page.${leagueId}`;

/** The page of this league the tab last read, 1 where it read none; the tab's own memory. */
function rememberedPage(leagueId: number): number {
  try {
    return standingsPage(sessionStorage.getItem(PAGE_KEY(leagueId)) ?? 1);
  } catch {
    return 1;
  }
}

function rememberPage(leagueId: number, page: number): void {
  try {
    if (page === 1) sessionStorage.removeItem(PAGE_KEY(leagueId));
    else sessionStorage.setItem(PAGE_KEY(leagueId), String(page));
  } catch {
    // A tab that keeps nothing opens at page 1, as before.
  }
}

/**
 * The scoreboard and the race a listed league's pages show, read through the forwarded
 * league's tree: the members' seasons and the game's events, built on the device. Drawn only
 * where the gate stood a tree above the page.
 */
function ForwardedLeagueCards() {
  const scoreboard = useLeagueScoreboard();
  const members = useLeagueMembers();
  const view = members.data?.payload;
  const race =
    scoreboard.data && view
      ? leagueRace(scoreboard.data.payload, view.members, view.scored_gameweek)
      : null;
  return (
    <>
      <ScoreboardSection />
      {race && view ? <LeagueRaceCard race={race} members={view.members} /> : null}
    </>
  );
}

function ForwardedLeagueTable() {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const words = messages.forwarded;
  const league = useForwardedLeague();
  const tree = useContext(LeagueContext);
  const [search, setSearch] = useSearchParams();
  const page = standingsPage(search.get("page"));
  const leagueId = league?.leagueId ?? null;
  useEffect(() => {
    if (leagueId !== null) rememberPage(leagueId, page);
  }, [leagueId, page]);
  const [pageInput, setPageInput] = useState(String(page));
  const [invalid, setInvalid] = useState(false);
  const standings = useForwardedStandings(league?.leagueId ?? null, page);

  function go(nextPage: number) {
    const next = new URLSearchParams(search);
    next.set("page", String(nextPage));
    crossfade(() => setSearch(next));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = pageInput.trim();
    const requested = Number(value);
    if (
      !/^\d+$/.test(value) ||
      !Number.isSafeInteger(requested) ||
      requested < 1 ||
      requested > MAX_STANDINGS_PAGE
    ) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    go(requested);
  }

  if (league === null) return <EmptyState title={messages.shell.notFound} />;
  const rows = standings.data?.results ?? [];
  const name = league.leagueName ?? words.leagueTitle(league.leagueId);
  return (
    <div className={styles.page} data-forwarded-league={league.leagueId}>
      <h1 className={styles.title} id="league-table-title">
        {name}
      </h1>
      {tree !== null ? <ForwardedLeagueCards /> : null}
      <form className={styles.pagination} onSubmit={submit} aria-label={words.pagination}>
        <button
          type="button"
          aria-label={words.previousPage}
          disabled={page === 1 || standings.isFetching}
          onClick={() => go(page - 1)}
        >
          ←
        </button>
        <input
          aria-label={words.page}
          inputMode="numeric"
          enterKeyHint="go"
          value={pageInput}
          aria-invalid={invalid}
          onChange={(event) => {
            setPageInput(event.target.value);
            setInvalid(false);
          }}
        />
        <button type="submit" disabled={standings.isFetching}>
          {words.go}
        </button>
        <button
          type="button"
          aria-label={words.nextPage}
          disabled={!standings.data?.has_next || page >= MAX_STANDINGS_PAGE || standings.isFetching}
          onClick={() => go(page + 1)}
        >
          →
        </button>
      </form>
      {standings.isPending ? (
        <p className={styles.note} role="status">
          {words.loading}
        </p>
      ) : null}
      {standings.isError ? (
        <div className={styles.more}>
          <p className={styles.note} role="status">
            {words.moreFailed}
          </p>
          <button
            className={styles.moreButton}
            type="button"
            onClick={() => void standings.refetch()}
          >
            {words.retry}
          </button>
        </div>
      ) : null}
      <table className={styles.table}>
        <caption className="visually-hidden">{copy.caption(name)}</caption>
        <thead>
          <tr>
            <th scope="col" className={styles.rank}>
              {copy.rank}
            </th>
            <th scope="col">{copy.team}</th>
            <th scope="col" className={styles.total}>
              {copy.total}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.entry}>
              <td className={`${styles.rank} num`}>{row.rank > 0 ? row.rank : ""}</td>
              <td>
                <div className={styles.teamCell}>
                  <Link
                    className={styles.teamName}
                    to={memberAddress(league.leagueId, row.entry)}
                    state={{ leaguePage: page }}
                  >
                    {row.entry_name || copy.unknownTeam}
                  </Link>
                  <span className={styles.manager}>{row.player_name || copy.unknownMember}</span>
                </div>
              </td>
              <td className={`${styles.total} num`}>{points(row.total, 0, locale)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
