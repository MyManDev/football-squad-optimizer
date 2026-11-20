import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import type { PriorityOutcome } from "../advice/preferenceBundle";
import { LLMOPT_COPY } from "./copy";
import styles from "./LLMOptPage.module.css";

/** The preferred rules the plan with all preferences applies and leaves out, and its cost. */
export function CombinedRules({
  rules,
  cost,
  infeasible,
  unanswered,
}: {
  rules: readonly { label: string; outcome?: PriorityOutcome }[];
  /** Expected points lost against the base plan, once both plans are in. */
  cost?: number;
  infeasible: boolean;
  unanswered: boolean;
}) {
  const titleId = useId();
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const labels = {
    applied: copy.combinedApplied,
    "left-out": copy.combinedLeftOut,
    unsearched: copy.combinedUnsearched,
  };
  const price = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 3,
  });
  return (
    <section className={styles.preferencePrices} aria-labelledby={titleId}>
      <h4 id={titleId} className={styles.lineupTitle}>
        {unanswered ? copy.requestedPreferences : copy.combinedRules}
      </h4>
      {infeasible && <p role="status">{copy.combinedInfeasible}</p>}
      {cost !== undefined && <p>{copy.combinedCost(price.format(cost))}</p>}
      <ul>
        {rules.map(({ label, outcome }, index) => (
          <li key={index} data-combined={outcome}>
            <strong>{label}</strong>
            {outcome && <span>{labels[outcome]}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
