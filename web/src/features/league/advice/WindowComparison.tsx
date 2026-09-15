import { MULTIWEEK_MESSAGES } from "./multiweekMessages";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "./WindowComparison.module.css";

export function WindowComparison({
  advice,
  rivalName,
}: {
  advice: EntryAdvice;
  rivalName: string;
}) {
  const { locale, messages, language } = useLanguage();
  const c = advice.window_comparison;
  if (!c) return null;
  const copy = messages.leagueMembers;
  const windowCopy = MULTIWEEK_MESSAGES[language];
  const gap = (value: number | null) => (value === null ? "—" : points(value, 1, locale));
  return (
    <section aria-label={windowCopy.windowComparisonTitle}>
      <h3>{windowCopy.windowComparisonTitle}</h3>
      <p>
        {windowCopy.windowRivalBasis(
          rivalName,
          c.rival_gameweek,
          c.overlap_actual,
          c.overlap_minimum === null ? `≤ ${c.overlap_maximum}` : `≥ ${c.overlap_minimum}`,
        )}
      </p>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{copy.strategyLegend}</th>
            <th>{windowCopy.windowFirstNet}</th>
            <th>{windowCopy.windowTotalNet(advice.window)}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>{copy.strategies["saf-puan"].name}</th>
            <td>{points(c.control_first_week_net_points, 1, locale)}</td>
            <td>{points(c.control_total_net_points, 1, locale)}</td>
          </tr>
          <tr>
            <th>
              {advice.mode === "ortak-koru"
                ? copy.strategies["ortak-koru"].name
                : copy.strategies["fark-yarat"].name}
            </th>
            <td>{points(c.first_week_net_points, 1, locale)}</td>
            <td>{points(c.total_net_points, 1, locale)}</td>
          </tr>
        </tbody>
      </table>
      <p>
        <strong>
          {windowCopy.windowDifference(signedPoints(c.net_points_difference, 1, locale))}
        </strong>
      </p>
      <p>{windowCopy.windowComparisonNote}</p>
      <p>
        {copy.strategyLegend}: {c.solver_status}; {copy.strategies["saf-puan"].name}:{" "}
        {c.control_solver_status}.
      </p>
      {c.control_solver_status === "FEASIBLE" ? (
        <p>
          {copy.strategies["saf-puan"].name}:{" "}
          {c.control_optimality_gap === null
            ? copy.unprovenPlanGapUnknown
            : copy.unprovenPlanBodyWindow(gap(c.control_optimality_gap), advice.window)}
        </p>
      ) : null}
    </section>
  );
}
