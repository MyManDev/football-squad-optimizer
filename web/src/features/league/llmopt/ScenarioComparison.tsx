import type { ReactNode } from "react";

import { useLanguage } from "../../../i18n/context";
import type { ComputePhase } from "../advice/useAdviceJob";
import { LLMOPT_COPY } from "./copy";
import { summarizeRevision, type PlanRevision } from "./planRevision";
import { RevisionComparison } from "./RevisionComparison";
import styles from "./LLMOptPage.module.css";

export function ScenarioComparison({
  reference,
  planContextEnabled,
  replay,
  optimized,
  description,
  proven,
  conflict,
  children,
}: {
  reference: PlanRevision;
  planContextEnabled: boolean;
  replay: ComputePhase;
  optimized: ComputePhase;
  description: string;
  proven: boolean;
  conflict: boolean;
  children: ReactNode;
}) {
  const { language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const original = replay.phase === "done" ? summarizeRevision(replay.envelope.payload) : undefined;
  const reoptimized =
    optimized.phase === "done" ? summarizeRevision(optimized.envelope.payload) : undefined;
  const movesOnly = {
    ...reference,
    net: null,
    weeks: reference.weeks.map((week) => ({ ...week, bank: undefined, freeTransfers: undefined })),
  };
  const outcome = original
    ? copy.scenarioFeasible
    : proven
      ? copy.scenarioInfeasible
      : conflict
        ? copy.scenarioConflict
        : replay.phase === "requesting" || replay.phase === "waiting"
          ? copy.scenarioChecking
          : copy.scenarioUnverified;
  return (
    <RevisionComparison
      planContextEnabled={planContextEnabled}
      previous={original ?? movesOnly}
      revised={reoptimized}
      scenario
      introduction={
        <div className={styles.scenarioNotes}>
          <p>
            <strong>{description}</strong>
          </p>
          <p className={styles.notice} role="status">
            {outcome}
          </p>
        </div>
      }
    >
      {children}
    </RevisionComparison>
  );
}
