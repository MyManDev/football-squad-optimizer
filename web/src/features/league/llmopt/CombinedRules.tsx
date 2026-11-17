import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { LLMOPT_COPY } from "./copy";
import styles from "./LLMOptPage.module.css";

/** The preferred rules the plan with all preferences applies and leaves out, and its cost. */
export function CombinedRules({
  applied,
  leftOut,
  cost,
  infeasible,
}: {
  applied: readonly { key: string; label: string }[];
  leftOut: readonly { key: string; label: string }[];
  /** Expected points lost against the base plan, once both plans are in. */
  cost?: number;
  infeasible: boolean;
}) {
  const titleId = useId();
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const price = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 3,
  });
  return (
    <section className={styles.preferencePrices} aria-labelledby={titleId}>
      <h4 id={titleId} className={styles.lineupTitle}>
        {copy.combinedRules}
      </h4>
      {infeasible && <p role="status">{copy.combinedInfeasible}</p>}
      {cost !== undefined && <p>{copy.combinedCost(price.format(cost))}</p>}
      <ul>
        {applied.map(({ key, label }) => (
          <li key={key} data-combined="applied">
            <strong>{label}</strong>
            <span>{copy.combinedApplied}</span>
          </li>
        ))}
        {leftOut.map(({ key, label }) => (
          <li key={key} data-combined="left-out">
            <strong>{label}</strong>
            <span>{copy.combinedLeftOut}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
