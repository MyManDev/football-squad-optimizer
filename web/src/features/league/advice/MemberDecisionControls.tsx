/**
 * The member's own decision controls: strategy, rival, window.
 *
 * The strategies are the catalogue's computable ones — the producer publishes a file per
 * (strategy, rival) and an index that says which exist — so every option here names
 * something that was actually solved from this member's squad, or says plainly that it
 * was not. The rival list is the league's other members; the standings neighbour the
 * producer chose is the default and is labelled as such. Windows beyond one week are
 * shown and disabled: the site does not compute them for members, and it says why
 * rather than hiding the choice.
 *
 * Selection lives in the URL (`mode`, `rival`, `window`), the same parameters the
 * templates set and the compute panel reads, so the whole state stays shareable.
 */

import { useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { WINDOWS, type WindowSize } from "../../moves/modePrices";
import {
  MEMBER_STRATEGIES,
  isMemberStrategy,
  strategyNeedsRival,
  type EntryAdviceIndex,
  type EntryView,
  type HumanEntryView,
  type MemberStrategy,
} from "../types";
import { rivalCandidates } from "./adviceSelection";
import styles from "./MemberDecisionControls.module.css";

export function MemberDecisionControls({
  entryId,
  members,
  index,
}: {
  entryId: number;
  members: EntryView[];
  index: EntryAdviceIndex | null;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const [searchParams, setSearchParams] = useSearchParams();
  const rawMode = searchParams.get("mode");
  const strategy: MemberStrategy = isMemberStrategy(rawMode) ? rawMode : "saf-puan";
  const rawWindow = Number(searchParams.get("window"));
  const windowSize: WindowSize = rawWindow === 3 ? 3 : rawWindow === 5 ? 5 : 1;
  const candidates = rivalCandidates(members, entryId).filter(
    (member): member is HumanEntryView => member.member_kind === "human",
  );
  const rivalIds: number[] = index
    ? index.rival_entry_ids
    : candidates.map((member) => member.entry_id);
  const defaultRival = index?.default_rival_entry_id ?? null;
  const rawRival = Number(searchParams.get("rival"));
  const chosenRival: number | null = rivalIds.includes(rawRival)
    ? rawRival
    : (defaultRival ?? rivalIds[0] ?? null);
  const unavailable = new Set(
    (index?.unavailable ?? [])
      .filter((entry) => entry.strategy === strategy)
      .map((entry) => entry.rival_entry_id),
  );

  function update(changes: Record<string, string | null>): void {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setSearchParams(next);
  }

  function nameOf(rivalId: number): string {
    const member = candidates.find((candidate) => candidate.entry_id === rivalId);
    return member?.team_name ?? member?.manager_name ?? `#${rivalId}`;
  }

  const needsRival = strategyNeedsRival(strategy);

  return (
    <Card
      title={copy.strategyTitle}
      aside={<Badge tone="accent">{messages.decision.shareable}</Badge>}
    >
      <p className={styles.intro}>{copy.strategyIntro}</p>
      <div className={styles.controls}>
        <fieldset className={styles.fieldset}>
          <legend>{copy.strategyLegend}</legend>
          <div className={styles.options}>
            {MEMBER_STRATEGIES.map((slug) => (
              <label className={styles.option} key={slug}>
                <input
                  type="radio"
                  name="strategy"
                  value={slug}
                  checked={strategy === slug}
                  onChange={() => update({ mode: slug })}
                />
                <span className={styles.body}>
                  <strong>{copy.strategies[slug].name}</strong>
                  <span className={styles.description}>{copy.strategies[slug].description}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {needsRival ? (
          <fieldset className={styles.fieldset}>
            <legend>{copy.rivalLegend}</legend>
            {rivalIds.length === 0 ? (
              <p className={styles.note}>{copy.rivalNone}</p>
            ) : (
              <label className={styles.rivalField}>
                <span>{copy.rivalLabel}</span>
                <select
                  value={chosenRival ?? ""}
                  onChange={(event) =>
                    update({
                      rival:
                        Number(event.target.value) === defaultRival ? null : event.target.value,
                    })
                  }
                >
                  {rivalIds.map((rivalId) => (
                    <option key={rivalId} value={rivalId}>
                      {nameOf(rivalId)}
                      {rivalId === defaultRival ? ` ${copy.rivalDefaultSuffix}` : ""}
                      {unavailable.has(rivalId) ? ` ${copy.rivalUnavailableSuffix}` : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <p className={styles.note}>{copy.rivalNote}</p>
          </fieldset>
        ) : null}

        <fieldset className={styles.fieldset}>
          <legend>{copy.windowLegend}</legend>
          <div className={styles.windows}>
            {WINDOWS.map((window) => (
              <label className={styles.windowOption} key={window}>
                <input
                  type="radio"
                  name="window"
                  value={window}
                  checked={windowSize === window}
                  disabled={window !== 1}
                  onChange={() => update({ window: String(window) })}
                />
                <span>{messages.decision.week(window)}</span>
              </label>
            ))}
          </div>
          <p className={styles.note}>{copy.windowNotComputed}</p>
        </fieldset>
      </div>
      <p className={styles.honesty}>{copy.honestyRule}</p>
    </Card>
  );
}
