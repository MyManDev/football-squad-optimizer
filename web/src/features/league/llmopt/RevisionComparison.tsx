import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { money, points, signedPoints } from "../../../lib/format";
import { LLMOPT_COPY } from "./copy";
import type { PlanRevision } from "./planRevision";
import styles from "./LLMOptPage.module.css";

function MetricRow({
  label,
  before,
  after,
  comparable,
  format,
  delta,
}: {
  label: string;
  before?: number | null;
  after?: number | null;
  comparable: boolean;
  format: (value: number) => string;
  delta: (value: number) => string;
}) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{before == null ? "—" : format(before)}</td>
      <td>{after == null ? "—" : format(after)}</td>
      <td>{comparable && before != null && after != null ? delta(after - before) : "—"}</td>
    </tr>
  );
}

export function RevisionComparison({
  previous,
  revised,
}: {
  previous: PlanRevision;
  revised?: PlanRevision;
}) {
  const title = useId();
  const { language, locale, messages } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const comparable = previous.window === revised?.window;
  const previousEnd = previous.weeks[previous.window - 1];
  const revisedEnd = revised?.weeks[revised.window - 1];
  const beforeWindow = previous.window === 1 ? copy.oneWeek : copy.threeWeeks;
  const afterWindow = revised ? (revised.window === 1 ? copy.oneWeek : copy.threeWeeks) : undefined;
  const weeks = Math.max(previous.weeks.length, revised?.weeks.length ?? 0);
  const number = (value: number) => points(value, 0, locale);
  const budget = (value: number) => money(value, locale);
  const transferNames = (players?: readonly { name: string }[]) =>
    players?.map(({ name }) => name).join(", ") || copy.noPlayers;
  return (
    <section className={styles.revision} aria-labelledby={title}>
      <h2 id={title}>{copy.revisionTitle}</h2>
      <table className={styles.revisionTable}>
        <thead>
          <tr>
            <td />
            <th scope="col" aria-label={copy.previousPlan}>
              {copy.previousPlan}
              <small>{beforeWindow}</small>
            </th>
            <th scope="col" aria-label={copy.revisedPlan}>
              {copy.revisedPlan}
              {afterWindow && <small>{afterWindow}</small>}
            </th>
            <th scope="col">{copy.revisionDelta}</th>
          </tr>
        </thead>
        <tbody>
          <MetricRow
            label={copy.totalNet}
            before={previous.net}
            after={revised?.net}
            comparable={comparable}
            format={(value) => points(value, 1, locale)}
            delta={(value) => signedPoints(value, 1, locale)}
          />
          <MetricRow
            label={copy.finalBank}
            before={previousEnd?.bank}
            after={revisedEnd?.bank}
            comparable={comparable}
            format={budget}
            delta={(value) => (value > 0 ? `+${budget(value)}` : budget(value))}
          />
          <MetricRow
            label={copy.finalTransfers}
            before={previousEnd?.freeTransfers}
            after={revisedEnd?.freeTransfers}
            comparable={comparable}
            format={number}
            delta={(value) => signedPoints(value, 0, locale)}
          />
        </tbody>
        {Array.from({ length: weeks }, (_, index) => {
          const before = previous.weeks[index];
          const after = revised?.weeks[index];
          const gameweek = previous.gameweek + index;
          return (
            <tbody key={gameweek} className={styles.revisionWeek}>
              <tr>
                <th scope="rowgroup" colSpan={4}>
                  {copy.week} {gameweek}
                </th>
              </tr>
              <tr>
                <th scope="row">{copy.clubTransfers}</th>
                <td>{transferNames(before?.incoming)}</td>
                <td colSpan={2}>{transferNames(after?.incoming)}</td>
              </tr>
              <tr>
                <th scope="row">{copy.outgoing}</th>
                <td>{transferNames(before?.outgoing)}</td>
                <td colSpan={2}>{transferNames(after?.outgoing)}</td>
              </tr>
              {(before?.chip || after?.chip) && (
                <tr>
                  <th scope="row">{messages.leagueMembers.chipLabel}</th>
                  <td>{before?.chip ? messages.leagueMembers.chipNames[before.chip] : "—"}</td>
                  <td colSpan={2}>
                    {after?.chip ? messages.leagueMembers.chipNames[after.chip] : "—"}
                  </td>
                </tr>
              )}
            </tbody>
          );
        })}
      </table>
    </section>
  );
}
