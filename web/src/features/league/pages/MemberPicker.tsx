import { useEffect, useMemo, useRef } from "react";
import { Link, useLocation } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { arrivedToPick } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../data";
import type { RosterEntry } from "../identity/useLeagueIdentity";
import type { useLeagueMembers } from "../queries";
import styles from "./MemberPicker.module.css";

/**
 * "Sen kimsin?": the league's members by name, each a button that enters as that member
 * at once. The names are sorted by name, never in the file's order, which is the
 * standings. Nothing else of a member is shown here: no points, rank or value. The entry
 * number stays out of the markup too: each button carries no value attribute.
 *
 * A view only: the member gate decides when it shows and what a choice does.
 */
export function MemberPicker({
  members,
  rows,
  onConfirm,
}: {
  members: ReturnType<typeof useLeagueMembers>;
  /** The human members, once read; the system's own team is never among them. */
  rows: readonly RosterEntry[] | undefined;
  onConfirm: (entry: RosterEntry) => void;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.memberPicker;
  const listCopy = messages.leagueMembers;
  const location = useLocation();
  const heading = useRef<HTMLHeadingElement>(null);

  const sorted = useMemo(() => {
    const collator = new Intl.Collator(locale, { sensitivity: "base" });
    const byName = (a: string | null, b: string | null) =>
      a === null ? (b === null ? 0 : 1) : b === null ? -1 : collator.compare(a, b);
    return [...(rows ?? [])].sort(
      (a, b) =>
        byName(a.managerName, b.managerName) ||
        byName(a.teamName, b.teamName) ||
        a.entryId - b.entryId,
    );
  }, [rows, locale]);

  // Arriving to choose (from the league number, or from Değiştir) puts focus on the
  // question. Only a new arrival moves it, so the effect follows the location's key.
  const arrived = arrivedToPick(location.state);
  useEffect(() => {
    if (arrived) heading.current?.focus();
  }, [location.key, arrived]);

  let body;
  if (members.isPending) body = <EmptyState title={listCopy.loading} />;
  else if (members.isError) {
    const missing = members.error instanceof LeagueDataMissing;
    body = (
      <EmptyState title={missing ? listCopy.notAvailable : listCopy.membersUnreadable}>
        {missing ? null : (
          <button type="button" className={styles.retry} onClick={() => void members.refetch()}>
            {messages.leagueEntry.retry}
          </button>
        )}
      </EmptyState>
    );
  } else if (sorted.length === 0) body = <EmptyState title={copy.empty} />;
  else
    body = (
      <div role="group" className={styles.group} aria-labelledby="member-picker-legend">
        <p id="member-picker-legend" className={styles.legend}>
          {copy.legend}
        </p>
        <ul className={styles.list}>
          {sorted.map((row) => (
            <li key={row.entryId}>
              <button type="button" className={styles.option} onClick={() => onConfirm(row)}>
                <span className={styles.names}>
                  <span className={styles.manager}>
                    {row.managerName ?? listCopy.unknownMember}
                  </span>
                  <span className="visually-hidden">, </span>
                  <span className={styles.team}>{row.teamName ?? listCopy.unknownTeam}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );

  return (
    <section className={styles.page} aria-labelledby="member-picker-title" data-member-picker="">
      <h1 id="member-picker-title" ref={heading} tabIndex={-1} className={styles.title}>
        {copy.title}
      </h1>
      {body}
      <Link className={styles.other} to="/">
        {copy.otherLeague}
      </Link>
    </section>
  );
}
