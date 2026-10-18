import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { arrivedToPick } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../data";
import type { RosterEntry } from "../identity/useLeagueIdentity";
import type { useLeagueMembers } from "../queries";
import { useLeague } from "../useLeague";
import styles from "./MemberPicker.module.css";

/**
 * "Sen kimsin?": the league's members by name, one to pick, and Onayla under them. The
 * names are sorted by name, never in the file's order, which is the standings. Nothing
 * else of a member is shown here: no points, rank or value.
 *
 * A view only: the member gate decides when it shows and what Onayla does.
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
  const { league } = useLeague();
  const location = useLocation();
  const heading = useRef<HTMLHeadingElement>(null);
  const [selected, setSelected] = useState<number | null>(null);

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
  const canConfirm = rows?.some((row) => row.entryId === selected) ?? false;

  // Arriving to choose (from the league number, or from Değiştir) puts focus on the
  // question. Only a new arrival moves it, so the effect follows the location's key.
  const arrived = arrivedToPick(location.state);
  useEffect(() => {
    if (arrived) heading.current?.focus();
  }, [location.key, arrived]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const row = rows?.find((entry) => entry.entryId === selected);
    if (row) onConfirm(row);
  }

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
      <form className={styles.form} onSubmit={submit}>
        <fieldset className={styles.group}>
          <legend className={styles.legend}>{copy.legend}</legend>
          <div className={styles.list}>
            {sorted.map((row) => (
              <label key={row.entryId} className={styles.option}>
                <input
                  type="radio"
                  className={styles.radio}
                  name="member"
                  value={row.entryId}
                  checked={selected === row.entryId}
                  onChange={() => setSelected(row.entryId)}
                />
                <span className={styles.names}>
                  <span className={styles.manager}>
                    {row.managerName ?? listCopy.unknownMember}
                  </span>
                  <span className="visually-hidden">, </span>
                  <span className={styles.team}>{row.teamName ?? listCopy.unknownTeam}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <button type="submit" className={styles.confirm} disabled={!canConfirm}>
          {copy.confirm}
        </button>
      </form>
    );

  return (
    <section className={styles.page} aria-labelledby="member-picker-title" data-member-picker="">
      <h1 id="member-picker-title" ref={heading} tabIndex={-1} className={styles.title}>
        {copy.title}
      </h1>
      <p className={styles.league}>{copy.league(league.leagueName)}</p>
      {body}
      <Link className={styles.other} to="/">
        {copy.otherLeague}
      </Link>
    </section>
  );
}
