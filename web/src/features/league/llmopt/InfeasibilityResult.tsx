import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { money } from "../../../lib/format";
import type { AdviceRequest } from "../advice/adviceClient";
import type { PlanInfeasibility } from "../advice/planInfeasibility";
import { LLMOPT_COPY } from "./copy";
import type { CatalogPlayer, PlanDraft } from "./intent";
import { repairOptions } from "./planRepairs";
import styles from "./LLMOptPage.module.css";

export function InfeasibilityResult({
  diagnosis,
  request,
  draft,
  players,
  disabled,
  change,
}: {
  diagnosis: PlanInfeasibility;
  request: AdviceRequest;
  draft: PlanDraft;
  players: readonly CatalogPlayer[];
  disabled: boolean;
  change: (draft: PlanDraft) => void;
}) {
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const title = useId();
  const minimum = request.preferences?.min_bank;
  const bank =
    diagnosis.bank?.required === minimum?.tenths && diagnosis.bank?.week === minimum?.week
      ? diagnosis.bank
      : undefined;
  const repairs = bank
    ? diagnosis.repairs
    : diagnosis.repairs.filter(({ kind }) => kind !== "lower_bank_floor");
  const options = repairOptions(draft, request, repairs, players);
  const absolute = (week: number) => (request.gameweek ?? 1) + week - 1;
  const budget = (tenths: number) => money(tenths, locale);
  const after =
    bank?.week === undefined ? copy.bankAfterFinal : copy.bankAfterWeek(absolute(bank.week));
  const bankReason =
    bank &&
    (bank.exact
      ? copy.bankShortfall(
          after,
          budget(bank.required),
          budget(bank.reachable),
          budget(bank.required - bank.reachable),
        )
      : copy.bankWitness(after, budget(bank.required), budget(bank.reachable)));
  return (
    <section className={styles.infeasibility} aria-labelledby={title}>
      <h4 className={styles.lineupTitle} id={title}>
        {copy.infeasibilityTitle}
      </h4>
      <p role="status">{bankReason ?? copy.infeasibilityProof}</p>
      {options.length > 0 && (
        <ul className={styles.repairOptions}>
          {options.map(({ repair, draft: next }, index) => {
            const player =
              "player_id" in repair
                ? (players.find(({ id }) => id === repair.player_id)?.name ??
                  String(repair.player_id))
                : "";
            const description =
              repair.kind === "lower_bank_floor"
                ? repair.tenths === 0
                  ? copy.removeBankMinimum
                  : copy.lowerBankMinimum(budget(repair.tenths))
                : repair.kind === "defer_purchase"
                  ? copy.deferPurchase(player, absolute(repair.from_week), absolute(repair.to_week))
                  : copy.releasePurchase(player, absolute(repair.week));
            const item = `${title}-${index}`;
            return (
              <li key={item}>
                <span id={item}>{description}</span>
                <button
                  className={styles.revise}
                  type="button"
                  aria-describedby={item}
                  disabled={disabled}
                  onClick={() => change(next)}
                >
                  {copy.applyRepair}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
