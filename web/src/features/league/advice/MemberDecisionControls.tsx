/**
 * The member's own decision controls: strategy, rival, window.
 *
 * The strategies are the catalogue's computable ones — the producer publishes a file per
 * (strategy, rival) and an index that says which exist — so every option here names
 * something that was actually solved from this member's squad, or says plainly that it
 * was not. The rival list is the league's other members; the standings neighbour the
 * producer chose is the default and is labelled as such. Where it named no default, no
 * rival is shown as chosen — the request would name none, and a control that displayed
 * one would demand a choice the member appeared to have made. Windows are enabled only
 * where the index lists them — pure points at three and five weeks when this publish
 * solved them — and the note says what a longer window assumes; a rival strategy stays at
 * one week, and a window nobody computed is shown disabled rather than hidden. A window
 * carried in from another strategy falls back to one the index lists, and says it did.
 *
 * One option may carry the producer's declared rule as a label: the rule reads the
 * member's points gap to their rival and the gameweeks left, and names one of the three.
 * It marks, it does not choose — the checked option is still whatever the URL says — and
 * the note beside it says the rule is written down rather than measured.
 *
 * Selection lives in the URL (`mode`, `rival`, `window`), the same parameters the
 * templates set and the compute panel reads, so the whole state stays shareable.
 */

import { useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { WINDOWS } from "../../moves/modePrices";
import { strategyNeedsRival, type EntryAdviceIndex, type EntryView } from "../types";
import { resolvePublishedAdvice } from "./adviceSelection";
import styles from "./MemberDecisionControls.module.css";

/** The gap as the rule read it: signed, so behind and ahead are visibly different. */
function signedPoints(points: number): string {
  return points > 0 ? `+${points}` : String(points);
}

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
  const selection = resolvePublishedAdvice(
    searchParams,
    index?.league_id ?? 0,
    entryId,
    members,
    index,
  );
  const { strategy, window: windowSize, rivalEntryId: chosenRival } = selection.request;
  const candidates = members.filter(
    (member) => member.member_kind === "human" && member.entry_id !== entryId,
  );
  const rivalIds = selection.rivals.map((rival) => rival.entryId);
  const defaultRival = index?.default_rival_entry_id ?? null;
  const windows = selection.windows;

  function strategySelection(slug: string) {
    const next = new URLSearchParams(searchParams);
    next.set("mode", slug);
    const offered = resolvePublishedAdvice(next, index?.league_id ?? 0, entryId, members, index);
    if (!offered.windows.includes(offered.request.window) && offered.windows[0]) {
      next.set("window", String(offered.windows[0]));
    }
    return {
      next,
      offered: resolvePublishedAdvice(next, index?.league_id ?? 0, entryId, members, index),
    };
  }

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
  // The producer's declared rule marks one of the three from the member's points gap
  // and the weeks left. It is a label on an option the member may ignore, never a
  // preselection: the checked strategy is still whatever the URL says.
  const suggested = index?.suggested_strategy ?? null;

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
            {selection.strategies.map((slug) => (
              <label className={styles.option} key={slug}>
                <input
                  type="radio"
                  name="strategy"
                  value={slug}
                  checked={
                    strategy === slug &&
                    (!searchParams.has("mode") || searchParams.get("mode") === slug)
                  }
                  disabled={
                    strategySelection(slug).offered.windows.length === 0 ||
                    (strategyNeedsRival(slug) &&
                      !strategySelection(slug).offered.rivals.some((rival) => rival.path))
                  }
                  onChange={() => setSearchParams(strategySelection(slug).next)}
                />
                <span className={styles.body}>
                  <span className={styles.heading}>
                    <strong>{copy.strategies[slug].name}</strong>
                    {suggested?.strategy === slug ? (
                      <Badge tone="neutral">{copy.rulePickBadge}</Badge>
                    ) : null}
                  </span>
                  <span className={styles.description}>{copy.strategies[slug].description}</span>
                </span>
              </label>
            ))}
          </div>
          {suggested ? (
            <p className={styles.note}>
              {copy.rulePickNote(
                nameOf(suggested.rival_entry_id),
                signedPoints(suggested.points_ahead_of_rival),
                suggested.gameweeks_remaining,
              )}
            </p>
          ) : null}
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
                  {chosenRival === null ? (
                    <option value="" disabled>
                      {copy.rivalChoose}
                    </option>
                  ) : null}
                  {rivalIds.map((rivalId) => (
                    <option
                      key={rivalId}
                      value={rivalId}
                      disabled={!selection.rivals.find((rival) => rival.entryId === rivalId)?.path}
                    >
                      {nameOf(rivalId)}
                      {rivalId === defaultRival ? ` ${copy.rivalDefaultSuffix}` : ""}
                      {selection.rivals.find((rival) => rival.entryId === rivalId)?.path
                        ? ""
                        : ` ${copy.rivalUnavailableSuffix}`}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {rivalIds.length > 0 && chosenRival === null ? (
              <p className={styles.note}>{copy.rivalNoDefault}</p>
            ) : null}
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
                  disabled={!windows.includes(window)}
                  onChange={() => update({ window: String(window) })}
                />
                <span>{messages.decision.week(window)}</span>
              </label>
            ))}
          </div>
          <p className={styles.note}>
            {windows.length > 1 ? copy.windowLimits : copy.windowNotComputed}
          </p>
        </fieldset>
      </div>
      <p className={styles.honesty}>{copy.honestyRule}</p>
    </Card>
  );
}
