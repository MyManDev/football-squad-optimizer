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
 * The Top 100 influence is a row of weights beside the manager's word. Each one is a
 * file the producer solved for this member on the one-week pure-points plan; a weight
 * without a file is shown disabled, and zero switches the influence off.
 *
 * The chip row is the member's own declaration, "play this chip this gameweek": one radio
 * per chip the producer solved on the plain one-week plan, and "none". A chip combines with
 * nothing, so while one is chosen the manager's word and the Top 100 settings above 0 are
 * off, and while either of those is on the chips are; every note says which, and "none"
 * (like 0 and the unchecked word) is always one click away.
 *
 * Selection lives in the URL (`mode`, `rival`, `window`, `llm`, `top100`, `chip`), the same
 * parameters the templates set and the compute panel reads, so the whole state stays shareable.
 */

import { useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { WINDOWS } from "../../moves/modePrices";
import { strategyNeedsRival, type EntryAdviceIndex, type EntryView } from "../types";
import { CHIP_NAMES } from "../chipShape";
import { EVIDENCE_PARAMETER, resolvePublishedAdvice } from "./adviceSelection";
import { CHIP_PARAMETER } from "./chipChoice";
import { CHIP_COPY, chipReason, chipsUnavailable } from "./chipCopy";
import { EVIDENCE_COPY, evidenceUnavailable } from "./evidenceCopy";
import { TOP100_PARAMETER, TOP100_WEIGHTS } from "./top100";
import { TOP100_COPY, top100Unavailable } from "./top100Copy";
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
  const { language, messages } = useLanguage();
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
  // The word is solved for the one-week pure-points plan only.
  const evidenceApplies =
    selection.evidence.available && strategy === "saf-puan" && windowSize === 1;
  const evidenceCopy = EVIDENCE_COPY[language];
  // Only a read of registered club pages is real; anything else is example data.
  const evidenceIsReal = selection.evidence.sourceKind === "club_news_capture";
  // The producer's declared rule marks one of the three from the member's points gap
  // and the weeks left. It is a label on an option the member may ignore, never a
  // preselection: the checked strategy is still whatever the URL says.
  const suggested = index?.suggested_strategy ?? null;
  const top100Copy = TOP100_COPY[language];
  const top100 = selection.top100;
  // A setting exists wherever the producer solved one: every pure-points window, and a
  // strategy's windows against the default rival.
  const top100Applies = top100.available && top100.offered.length > 1;
  // A chip the member chose is the plain one-week plan with that chip forced. It combines
  // with nothing, so the word and the settings above 0 are off while one is chosen, and
  // the chips are off while either of those is on.
  const chipCopy = CHIP_COPY[language];
  const chip = selection.chip;
  const chipChosen = chip.chip !== null;
  const chipApplies = chip.available && strategy === "saf-puan" && windowSize === 1;
  const chipBlocked = selection.evidence.on || top100.weight !== 0;
  const chipNote = !chip.available
    ? chipsUnavailable(chipCopy, chip.reason)
    : !chipApplies
      ? chipCopy.onlyBaseline
      : chipBlocked
        ? chipCopy.blockedBySwitches
        : chip.chip !== null
          ? chipCopy.chosen(copy.chipNames[chip.chip] ?? chip.chip)
          : chip.notOffered
            ? chipCopy.notOffered
            : chipCopy.plain;
  // Why a chip the member cannot choose is off: already played, its window not open, a
  // Free Hit last gameweek, or no plan solved. Said per chip, in the producer's codes.
  const chipReasons = CHIP_NAMES.filter(
    (name) => !chip.options.includes(name) && (chip.available || chip.reasons[name] !== undefined),
  ).map((name) =>
    chipCopy.chipReasonLine(copy.chipNames[name] ?? name, chipReason(chipCopy, chip.reasons[name])),
  );
  const top100Note = chipChosen
    ? chipCopy.switchesOff
    : !top100.available
      ? top100Unavailable(top100Copy, top100.reason)
      : !top100Applies
        ? top100Copy.notForSelection
        : top100.notOffered
          ? top100Copy.notOffered
          : top100.weights.length < TOP100_WEIGHTS.length
            ? top100Copy.notSolved
            : top100Copy.published;

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
            {windows.length > 1 ? <p className={styles.note}>{top100Copy.rivalWindows}</p> : null}
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

        <fieldset className={styles.fieldset}>
          <legend>{evidenceCopy.legend}</legend>
          <label className={styles.windowOption}>
            <input
              type="checkbox"
              name={EVIDENCE_PARAMETER}
              checked={selection.evidence.on}
              disabled={!evidenceApplies || chipChosen}
              onChange={(event) =>
                update({ [EVIDENCE_PARAMETER]: event.target.checked ? "on" : null })
              }
            />
            <span>{evidenceCopy.switchLabel}</span>
            {selection.evidence.available && !evidenceIsReal ? (
              <Badge tone="warn">{copy.exampleData}</Badge>
            ) : null}
          </label>
          <p className={styles.note}>
            {chipChosen
              ? chipCopy.switchesOff
              : !selection.evidence.available
                ? evidenceUnavailable(evidenceCopy, selection.evidence.reason)
                : !evidenceApplies
                  ? evidenceCopy.onlyBaseline
                  : evidenceIsReal
                    ? evidenceCopy.sourceCapture
                    : evidenceCopy.sourceExample}
          </p>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>{top100Copy.legend}</legend>
          <div className={styles.windows}>
            {TOP100_WEIGHTS.map((weight) => (
              <label className={styles.windowOption} key={weight}>
                <input
                  type="radio"
                  name={TOP100_PARAMETER}
                  value={weight}
                  checked={top100.weight === weight}
                  disabled={
                    !top100Applies ||
                    !top100.weights.includes(weight) ||
                    (chipChosen && weight !== 0)
                  }
                  onChange={() =>
                    update({ [TOP100_PARAMETER]: weight === 0 ? null : String(weight) })
                  }
                  // Zero reads as checked while the link carries a setting the page cannot
                  // show; a click on it still has to clear that setting from the link.
                  onClick={() => {
                    if (weight === 0 && searchParams.has(TOP100_PARAMETER)) {
                      update({ [TOP100_PARAMETER]: null });
                    }
                  }}
                />
                <span>{weight === 0 ? top100Copy.zero : weight}</span>
              </label>
            ))}
          </div>
          <p className={styles.note}>{top100Note}</p>
          {top100Applies ? <p className={styles.note}>{top100Copy.help}</p> : null}
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>{chipCopy.legend}</legend>
          <div className={styles.windows}>
            <label className={styles.windowOption}>
              <input
                type="radio"
                name={CHIP_PARAMETER}
                value=""
                checked={!chipChosen}
                // Nothing to choose from and nothing in the link to clear: the row is inert.
                disabled={!chip.available && !searchParams.has(CHIP_PARAMETER)}
                onChange={() => update({ [CHIP_PARAMETER]: null })}
                // "None" reads as checked while the link carries a chip the page cannot
                // show; a click on it still has to clear that chip from the link.
                onClick={() => {
                  if (searchParams.has(CHIP_PARAMETER)) update({ [CHIP_PARAMETER]: null });
                }}
              />
              <span>{chipCopy.none}</span>
            </label>
            {CHIP_NAMES.map((name) => (
              <label className={styles.windowOption} key={name}>
                <input
                  type="radio"
                  name={CHIP_PARAMETER}
                  value={name}
                  checked={chip.chip === name}
                  disabled={!chipApplies || chipBlocked || !chip.options.includes(name)}
                  onChange={() => update({ [CHIP_PARAMETER]: name })}
                />
                <span>{copy.chipNames[name] ?? name}</span>
              </label>
            ))}
          </div>
          <p className={styles.note}>{chipNote}</p>
          {chipReasons.length > 0 ? <p className={styles.note}>{chipReasons.join(" ")}</p> : null}
          {chipApplies ? <p className={styles.note}>{chipCopy.help}</p> : null}
        </fieldset>
      </div>
      <p className={styles.honesty}>{copy.honestyRule}</p>
    </Card>
  );
}
