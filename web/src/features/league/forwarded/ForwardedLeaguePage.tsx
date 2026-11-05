import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { memberAddress } from "../../../lib/leagueAddresses";
import { useForwardedLeague } from "./ForwardedLeagueContext";
import { standingRows, useForwardedStandings } from "./reads";
import styles from "./ForwardedLeaguePage.module.css";

/**
 * A classic league the site does not publish, as its standings (#983 step 4): rank, team,
 * manager and total, read from the FPL forwarder a page of fifty at a time as the visitor
 * scrolls or asks for more, up to the forwarder's twenty pages. Each team opens its member
 * page under the league. Nothing is published for such a league, so no history, race,
 * scoreboard or published plan appears here.
 */
export function ForwardedLeaguePage() {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const words = messages.forwarded;
  const league = useForwardedLeague();
  const standings = useForwardedStandings(league?.leagueId ?? null);
  const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = standings;
  const more = useRef<HTMLDivElement>(null);

  // The next page is read as the end of the table comes near, while the last read did not
  // fail; after a failure the button reads it again.
  useEffect(() => {
    const node = more.current;
    if (
      node === null ||
      !hasNextPage ||
      isFetchingNextPage ||
      isFetchNextPageError ||
      typeof IntersectionObserver === "undefined"
    ) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void fetchNextPage();
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage]);

  if (league === null) return <EmptyState title={messages.shell.notFound} />;
  const rows = standingRows(standings.data?.pages);
  const name = league.leagueName ?? words.leagueTitle(league.leagueId);
  return (
    <div className={styles.page} data-forwarded-league={league.leagueId}>
      <h1 className={styles.title} id="league-table-title">
        {name}
      </h1>
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
                  <Link className={styles.teamName} to={memberAddress(league.leagueId, row.entry)}>
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
      <div ref={more} className={styles.more}>
        {isFetchNextPageError ? (
          <p className={styles.note} role="status">
            {words.moreFailed}
          </p>
        ) : null}
        {hasNextPage ? (
          <button
            type="button"
            className={styles.moreButton}
            disabled={isFetchingNextPage}
            onClick={() => void fetchNextPage()}
          >
            {isFetchNextPageError ? words.retry : words.more}
          </button>
        ) : null}
      </div>
    </div>
  );
}
