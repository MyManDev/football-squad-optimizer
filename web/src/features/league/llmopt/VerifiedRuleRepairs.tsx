import { useEffect, useRef, useState } from "react";
import { isTimeoutError } from "../../../data/request";
import { useLanguage } from "../../../i18n/context";
import { AdviceApiError, type AdviceClient } from "../advice/adviceClient";
import type { EntryAdvice, EntrySquad } from "../types";
import { LLMOPT_COPY } from "./copy";
import { expectedNet } from "./planComparison";
import { planIdentity } from "./planHistory";
import type { PlanRevision } from "./planRevision";
import type { PlanRequest } from "./planRun";
import {
  candidateRequest,
  computeRepairPlan,
  matchesRepair,
  RepairEnvelopeTooLarge,
  verificationRequest,
  type RepairRun,
} from "./repairComputation";
import { isMissingRepairInput, type RepairChoice, type RepairStatus } from "./ruleRepairChoices";
import styles from "./LLMOptPage.module.css";

interface Witness {
  choice: RepairChoice;
  run: RepairRun;
  request: PlanRequest;
  answer: EntryAdvice;
  id: string;
  net: number;
}

function failureCode(error: unknown) {
  if (isTimeoutError(error)) return "PATIENCE_EXHAUSTED";
  if (error instanceof AdviceApiError && error.code) return error.code;
  return error instanceof Error ? error.message : "";
}

export function VerifiedRuleRepairs({
  analysis,
  client,
  squad,
  window,
  forwarded,
  reference,
  disabled,
  begin,
  current,
  apply,
}: {
  analysis: { status: RepairStatus; sentence: string; choices: RepairChoice[] };
  client: AdviceClient;
  squad: EntrySquad;
  window: 1 | 3;
  forwarded?: boolean;
  reference?: PlanRevision;
  disabled: boolean;
  begin: (signal: AbortSignal) => Promise<RepairRun>;
  current: (run: RepairRun) => Promise<boolean>;
  apply: (choice: RepairChoice, plan: EntryAdvice, id: string) => void;
}) {
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const [witnesses, setWitnesses] = useState<Witness[]>([]);
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(false);
  const [pendingReplay, setPendingReplay] = useState<Witness | null>(null);
  const [problem, setProblem] = useState<
    "unconfirmed" | "missing" | "budget" | "wait" | "tooLarge" | null
  >(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function work(operation: (signal: AbortSignal) => Promise<void>) {
    if (active.current || disabled) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setProblem(null);
    try {
      await operation(controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) {
        const code = failureCode(error);
        setProblem(
          code === "RUN_BUDGET_EXHAUSTED"
            ? "budget"
            : code === "PATIENCE_EXHAUSTED"
              ? "wait"
              : isMissingRepairInput(code)
                ? "missing"
                : "unconfirmed",
        );
        setChecked(false);
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      active.current = null;
    }
  }
  function check() {
    void work(async (signal) => {
      const run = await begin(signal);
      if (signal.aborted) return;
      setChecked(true);
      let stage: "repair" | "base" = run.failedBase ? "repair" : "base";
      const found = witnesses.filter(
        (witness) => witness.run.runId === run.runId && witness.run.dataId === run.dataId,
      );
      setWitnesses(found);
      let oversized = false;
      for (const choice of analysis.choices.slice(0, 2)) {
        if (stage === "repair" && !(await current(run))) throw new Error("RUN_CONTEXT_CHANGED");
        if (signal.aborted) return;
        try {
          const request = candidateRequest(
            choice.draft,
            { squad, window, forwarded, reference },
            run,
            stage,
          );
          if (!request) continue;
          stage = "repair";
          if (found.some((witness) => JSON.stringify(witness.request) === JSON.stringify(request)))
            continue;
          const answer = await computeRepairPlan(
            client,
            request,
            squad.source_snapshot_id!,
            run.dataId,
            signal,
          );
          const net = expectedNet(answer);
          if (net === null || !verificationRequest(request, answer)) continue;
          const id = await planIdentity(answer);
          if (signal.aborted) return;
          if (!(await current(run))) throw new Error("RUN_CONTEXT_CHANGED");
          if (!signal.aborted) {
            found.push({ choice, request, answer, id, net, run });
            setWitnesses([...found]);
          }
        } catch (error) {
          if (error instanceof RepairEnvelopeTooLarge) {
            oversized = true;
            continue;
          }
          const code = failureCode(error);
          if (code === "PLAN_NOT_FOUND") continue;
          throw error;
        }
      }
      if (oversized && !found.length) setProblem("tooLarge");
    });
  }
  function select(witness: Witness) {
    void work(async (signal) => {
      setPendingReplay(witness);
      if (!(await current(witness.run)) || signal.aborted) throw new Error("RUN_CONTEXT_CHANGED");
      const request = verificationRequest(witness.request, witness.answer);
      if (!request) throw new Error("RUN_CONTEXT_CHANGED");
      const plan = await computeRepairPlan(
        client,
        request,
        squad.source_snapshot_id!,
        witness.run.dataId,
        signal,
      );
      if (signal.aborted) return;
      if (!matchesRepair(witness.answer, plan) || !(await current(witness.run)))
        throw new Error("RUN_CONTEXT_CHANGED");
      if (!signal.aborted) {
        setPendingReplay(null);
        apply(witness.choice, plan, witness.id);
      }
    });
  }
  return (
    <section className={styles.infeasibility} data-rule-repairs aria-busy={busy}>
      <p role="status">{problem ? copy.repairs[problem] : analysis.sentence}</p>
      {analysis.status === "conflict" && analysis.choices.length > 0 && !checked && (
        <button
          type="button"
          className={styles.revise}
          disabled={disabled || busy}
          onClick={pendingReplay ? () => select(pendingReplay) : check}
        >
          {copy.repairs.check}
        </button>
      )}
      {witnesses.length > 0 && (
        <ul className={styles.repairOptions}>
          {witnesses.map((witness) => (
            <li
              key={witness.choice.label}
              data-repair-plan={witness.id}
              data-repair-net={witness.net}
            >
              <button
                type="button"
                className={styles.revise}
                disabled={disabled || busy}
                onClick={() => select(witness)}
              >
                {witness.choice.label}
              </button>
              <span>
                {witness.net.toLocaleString(locale, { maximumFractionDigits: 3 })}{" "}
                {copy.repairs.netPoints}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
