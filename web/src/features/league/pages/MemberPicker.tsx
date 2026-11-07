import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { PageLoading } from "../../../design/components/PageLoading";
import { useLanguage } from "../../../i18n/context";
import { arrivedToPick } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../data";
import type { RosterEntry } from "../identity/useLeagueIdentity";
import type { useLeagueMembers } from "../queries";
import { matchingMembers } from "./memberSearch";
import styles from "./MemberPicker.module.css";

/**
 * "Sen kimsin?": the league's members by name, each a button that enters as that member
 * at once. The names are sorted by name, never in the file's order, which is the
 * standings. Nothing else of a member is shown here: no points, rank or value. The entry
 * number stays out of the markup too: each button carries no value attribute.
 *
 * Above the list a field narrows it: a part of a name, or the team number the game gives,
 * for a league where two members share a name. While the typed text matches none of the
 * rows read so far and the league has more (`more`), the picker asks for the next page
 * (`onMore`) until a row matches or the pages run out.
 *
 * A view only: the member gate decides when it shows and what a choice does.
 */
export function MemberPicker({
  members,
  rows,
  more = false,
  reading = false,
  onMore,
  onConfirm,
}: {
  members: ReturnType<typeof useLeagueMembers>;
  /** The human members, once read; the system's own team is never among them. */
  rows: readonly RosterEntry[] | undefined;
  /** Whether the league has members beyond the rows read so far. */
  more?: boolean;
  /** Whether a further page of members is being read now. */
  reading?: boolean;
  /** Asks for the next page of members. */
  onMore?: () => void;
  onConfirm: (entry: RosterEntry) => void;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.memberPicker;
  const listCopy = messages.leagueMembers;
  const location = useLocation();
  const heading = useRef<HTMLHeadingElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [typed, setTyped] = useState("");

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
  const shown = useMemo(() => matchingMembers(sorted, typed), [sorted, typed]);

  // A name typed that no row read so far carries asks for the next page, while there is one.
  const seeking = typed.trim() !== "" && shown.length === 0 && more;
  useEffect(() => {
    if (seeking && !reading) onMore?.();
  }, [seeking, reading, onMore]);

  // Arriving to choose (from the league number, or from Değiştir) puts focus on the
  // question. Only a new arrival moves it, so the effect follows the location's key.
  const arrived = arrivedToPick(location.state);
  useEffect(() => {
    if (arrived) heading.current?.focus({ preventScroll: true });
  }, [location.key, arrived]);

  let body;
  if (members.isPending) body = <PageLoading label={listCopy.loading} />;
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
      <div
        role="group"
        className={styles.group}
        aria-labelledby="member-picker-legend"
        aria-busy={seeking && reading ? true : undefined}
      >
        <p id="member-picker-legend" className={styles.legend}>
          {copy.legend}
        </p>
        <input
          type="search"
          className={styles.search}
          aria-label={copy.search}
          placeholder={copy.search}
          autoComplete="off"
          enterKeyHint="search"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
        />
        {shown.length === 0 ? (
          seeking ? (
            <PageLoading label={listCopy.loading} />
          ) : (
            <p className={styles.noMatch} role="status">
              {copy.noMatch}
            </p>
          )
        ) : (
          <ul className={styles.list}>
            {shown.map((row) => (
              <li key={row.entryId}>
                <button
                  type="button"
                  className={styles.option}
                  data-selected={selected === row.entryId || undefined}
                  onClick={() => {
                    setSelected(row.entryId);
                    onConfirm(row);
                  }}
                >
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
        )}
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
