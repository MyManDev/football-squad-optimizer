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
 * With a compute service answering (`capabilities`), an option the publish did not solve
 * is still offered wherever the service computes it: any window the service lists, any
 * other member as the rival, any Top 100 setting and the manager's word when the current
 * capture has their inputs. The published file is shown where there is one and the compute
 * panel takes over where there is none. Without capabilities nothing here changes.
 *
 * Selection lives in the URL (`mode`, `rival`, `window`, `llm`, `top100`, `chip`), the same
 * parameters the templates set and the compute panel reads, so the whole state stays shareable.
 *
 * The controls come in two parts. The plan part (strategy, the rival where one is needed,
 * the window and the model) is what the member changes every week; the page renders it in
 * the sidebar above Hesapla. The advanced part (the manager's word, the Top 100 weight and
 * the chip) sits on the page under a closed disclosure. `part` picks one; without it both
 * render, one after the other, so every input is on the page exactly once either way. The
 * notes that explain the options (what each strategy asks for, the declared rule, what a
 * longer window assumes) are a third part, a closed "About these options" with no input in
 * it: the sidebar puts it under Hesapla, so it never pushes the button down.
 */

import { useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { useLanguage } from "../../../i18n/context";
import { signedPoints } from "../../../lib/format";
import { WINDOWS } from "../../../lib/decisionVocabulary";
import {
  isMemberStrategy,
  strategyNeedsRival,
  type EntryAdviceIndex,
  type EntryView,
} from "../types";
import { CHIP_NAMES } from "../chipShape";
import { DisclosureIcon } from "../components/memberIcons";
import type { AdviceCapabilities } from "./adviceCapabilities";
import { EVIDENCE_PARAMETER, resolvePublishedAdvice } from "./adviceSelection";
import { AUTOMATIC_CHIP_OFFERED, CHIP_PARAMETER } from "./chipChoice";
import { CHIP_COPY, chipReason, chipsUnavailable } from "./chipCopy";
import { COMPUTE_COPY } from "./computeCopy";
import { EVIDENCE_COPY, evidenceUnavailable } from "./evidenceCopy";
import { TOP100_PARAMETER, TOP100_WEIGHTS } from "./top100";
import { TOP100_COPY, top100Unavailable } from "./top100Copy";
import styles from "./MemberDecisionControls.module.css";

/** Which part of the controls to render; all of them, in turn, when none is named. */
export type DecisionControlsPart = "plan" | "notes" | "advanced";

export function MemberDecisionControls({
  entryId,
  members,
  index,
  capabilities = null,
  part,
}: {
  entryId: number;
  members: EntryView[];
  index: EntryAdviceIndex | null;
  capabilities?: AdviceCapabilities | null;
  part?: DecisionControlsPart;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const [searchParams, setSearchParams] = useSearchParams();
  const resolve = (params: URLSearchParams) =>
    resolvePublishedAdvice(
      params,
      index?.league_id ?? 0,
      entryId,
      members,
      index,
      undefined,
      capabilities,
    );
  const selection = resolve(searchParams);
  // What the service adds to the published menu; nothing at all on a static build.
  const computable = selection.computable;
  const computeCopy = COMPUTE_COPY[language];
  const { strategy, window: windowSize, rivalEntryId: chosenRival } = selection.request;
  const candidates = members.filter(
    (member) => member.member_kind === "human" && member.entry_id !== entryId,
  );
  const rivalIds = [
    ...new Set([...selection.rivals.map((rival) => rival.entryId), ...(computable?.rivals ?? [])]),
  ];
  const defaultRival = index?.default_rival_entry_id ?? null;
  const windows = [...new Set([...selection.windows, ...(computable?.windows ?? [])])];
  const strategies = [...new Set([...selection.strategies, ...(computable?.strategies ?? [])])];
  // A rival can be chosen where its file was published or, for a window the service
  // computes, against any member it lists.
  const rivalSelectable = (rivalId: number) =>
    !!selection.rivals.find((rival) => rival.entryId === rivalId)?.path ||
    (!!computable &&
      computable.windows.includes(windowSize) &&
      computable.rivals.includes(rivalId) &&
      // A pair the producer declared impossible stays off: the service solves the same band.
      !selection.rivals.find((rival) => rival.entryId === rivalId)?.reason);

  function strategySelection(slug: string) {
    const next = new URLSearchParams(searchParams);
    next.set("mode", slug);
    const offered = resolve(next);
    const offeredWindows = [...offered.windows, ...(offered.computable?.windows ?? [])];
    if (!offeredWindows.includes(offered.request.window) && offeredWindows[0]) {
      next.set("window", String(offeredWindows[0]));
    }
    return { next, offered: resolve(next) };
  }

  /** A strategy is offered where the publish solved it or the service computes it. */
  function strategyOffered(slug: string): boolean {
    const { offered } = strategySelection(slug);
    const publishedHere =
      offered.windows.length > 0 &&
      (!strategyNeedsRival(slug) || offered.rivals.some((rival) => rival.path));
    const computedHere =
      !!offered.computable &&
      offered.computable.windows.length > 0 &&
      (!strategyNeedsRival(slug) || offered.computable.rivals.length > 0);
    return publishedHere || computedHere;
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
  // The service applies it to the same plan, from the capture's own club news.
  const evidenceComputable = computable?.word === true;
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
  const top100Computable = (computable?.top100Weights.length ?? 0) > 1;
  const weightSelectable = (weight: number) =>
    (top100Applies && top100.weights.some((offered) => offered === weight)) ||
    (top100Computable && computable!.top100Weights.some((offered) => offered === weight));
  // Legacy published chips exclude both switches. The live chip strategy permits Top100,
  // but still excludes the manager's word; explain only the applicable restriction.
  const chipCopy = CHIP_COPY[language];
  const chip = selection.chip;
  const chipOptions = [
    ...new Set([...chip.options, ...(capabilities?.chipsByEntry?.[entryId] ?? [])]),
  ];
  const chipStrategy = computable?.chipStrategy === true;
  const chipsAvailable = chipOptions.length > 0 || chipStrategy;
  const chipChosen = chip.chip !== null;
  const chipApplies =
    chipsAvailable && strategy === "saf-puan" && (windowSize === 1 || chipStrategy);
  const chipBlocked = selection.evidence.on || (top100.weight !== 0 && !chipStrategy);
  const strategyCopy = copy.chipStrategy;
  const chipSwitchesOff = chipStrategy ? strategyCopy.switchesOff : chipCopy.switchesOff;
  const chipBlockedNote = chipStrategy ? strategyCopy.blocked : chipCopy.blockedBySwitches;
  const chipNote =
    chipStrategy && !chipBlocked
      ? strategyCopy.note
      : !chipsAvailable
        ? chipsUnavailable(chipCopy, chip.reason)
        : !chipApplies
          ? chipCopy.onlyBaseline
          : chipBlocked
            ? chipBlockedNote
            : chip.chip !== null
              ? chipCopy.chosen(copy.chipNames[chip.chip] ?? chip.chip)
              : chip.notOffered
                ? chipCopy.notOffered
                : chipCopy.plain;
  // Why a chip the member cannot choose is off: already played, its window not open, a
  // Free Hit last gameweek, or no plan solved. Said per chip, in the producer's codes.
  const chipReasons = CHIP_NAMES.filter(
    (name) => !chipOptions.includes(name) && (chipsAvailable || chip.reasons[name] !== undefined),
  ).map((name) =>
    chipCopy.chipReasonLine(copy.chipNames[name] ?? name, chipReason(chipCopy, chip.reasons[name])),
  );
  const top100Note =
    chipChosen && !chipStrategy
      ? chipCopy.switchesOff
      : top100Computable && TOP100_WEIGHTS.some((weight) => !top100.weights.includes(weight))
        ? computeCopy.top100Computable
        : !top100.available
          ? top100Unavailable(top100Copy, top100.reason)
          : !top100Applies
            ? top100Copy.notForSelection
            : top100.notOffered
              ? top100Copy.notOffered
              : top100.weights.length < TOP100_WEIGHTS.length
                ? top100Copy.notSolved
                : top100Copy.published;

  // The model is offered only where the service computes the football model, or where the
  // link already asks for it (so the choice can be seen and undone).
  const showModel =
    capabilities?.models?.includes("football") === true || searchParams.get("model") === "football";
  const chosenModel = searchParams.get("model") === "football" ? "football" : "current";
  const strategyName = isMemberStrategy(strategy)
    ? copy.strategies[strategy].name
    : {
        garantici: messages.decision.modes.safe,
        agresif: messages.decision.modes.aggressive,
        "asiri-agresif": messages.decision.modes.extreme,
      }[strategy];
  // The plan in force, as D-Bu-Hafta writes it beside the heading: the strategy and the
  // window. The model is the radio group just under it, and the decision's own heading row
  // names all three.
  const now = [strategyName, messages.decision.week(windowSize)].filter(Boolean).join(" · ");

  const plan = (
    <div className={styles.plan}>
      <div className={styles.planHead}>
        <h2 className={styles.planTitle}>{copy.planTitle}</h2>
        <span className={styles.planNow}>{copy.planNow(now)}</span>
      </div>
      <fieldset className={styles.field}>
        <legend>{copy.strategyLegend}</legend>
        <div className={styles.rows}>
          {strategies.map((slug) => (
            <label className={styles.row} key={slug}>
              <input
                type="radio"
                className={styles.radio}
                name="strategy"
                value={slug}
                checked={
                  strategy === slug &&
                  (!searchParams.has("mode") || searchParams.get("mode") === slug)
                }
                disabled={!strategyOffered(slug)}
                onChange={() => setSearchParams(strategySelection(slug).next)}
              />
              <span className={styles.rowName}>{copy.strategies[slug].name}</span>
              {suggested?.strategy === slug ? (
                <span className={styles.tag}>{copy.rulePickBadge}</span>
              ) : null}
            </label>
          ))}
        </div>
        {isMemberStrategy(strategy) ? (
          <p className={styles.line}>{copy.strategies[strategy].short}</p>
        ) : null}
      </fieldset>

      {needsRival ? (
        <div className={styles.field}>
          {rivalIds.length === 0 ? (
            <p className={styles.line}>{copy.rivalNone}</p>
          ) : (
            <label className={styles.rivalField}>
              <span className={styles.label}>{copy.rivalLabel}</span>
              <select
                value={chosenRival ?? ""}
                onChange={(event) =>
                  update({
                    rival: Number(event.target.value) === defaultRival ? null : event.target.value,
                  })
                }
              >
                {chosenRival === null ? (
                  <option value="" disabled>
                    {copy.rivalChoose}
                  </option>
                ) : null}
                {rivalIds.map((rivalId) => (
                  <option key={rivalId} value={rivalId} disabled={!rivalSelectable(rivalId)}>
                    {nameOf(rivalId)}
                    {rivalId === defaultRival ? ` ${copy.rivalDefaultSuffix}` : ""}
                    {rivalSelectable(rivalId) ? "" : ` ${copy.rivalUnavailableSuffix}`}
                  </option>
                ))}
              </select>
            </label>
          )}
          {rivalIds.length > 0 && chosenRival === null ? (
            <p className={styles.line}>{copy.rivalNoDefault}</p>
          ) : null}
        </div>
      ) : null}

      <fieldset className={styles.field}>
        <legend>{copy.windowLegend}</legend>
        <div className={styles.segments}>
          {WINDOWS.map((window) => (
            <label className={styles.segment} key={window}>
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
      </fieldset>

      {showModel ? (
        <fieldset className={styles.field}>
          <legend>{copy.modelLegend}</legend>
          <div className={styles.rows}>
            {(["current", "football"] as const).map((model) => (
              <label className={styles.row} key={model}>
                <input
                  type="radio"
                  className={styles.radio}
                  name="prediction-model"
                  value={model}
                  checked={chosenModel === model}
                  disabled={model === "football" && !capabilities?.models?.includes("football")}
                  onChange={() => update({ model: model === "current" ? null : model })}
                />
                <span className={styles.rowName}>{copy.modelNames[model]}</span>
                {model === "football" ? (
                  <span className={styles.tag}>{copy.experimentalTag}</span>
                ) : null}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
    </div>
  );

  const notes = (
    <details className={styles.notes}>
      <summary>
        <DisclosureIcon className={styles.notesIcon} />
        {copy.optionNotes}
      </summary>
      <div className={styles.notesBody}>
        <p>
          {copy.strategyIntro} <Badge tone="accent">{messages.decision.shareable}</Badge>
        </p>
        <dl className={styles.descriptions}>
          {strategies.map((slug) => (
            <div key={slug}>
              <dt>{copy.strategies[slug].name}</dt>
              <dd>{copy.strategies[slug].description}</dd>
            </div>
          ))}
        </dl>
        {suggested ? (
          <p>
            {copy.rulePickNote(
              nameOf(suggested.rival_entry_id),
              signedPoints(suggested.points_ahead_of_rival, 1, locale),
              suggested.gameweeks_remaining,
            )}
          </p>
        ) : null}
        {needsRival ? (
          <>
            <p>{copy.rivalNote}</p>
            {windows.length > 1 ? <p>{top100Copy.rivalWindows}</p> : null}
            {(computable?.rivals.length ?? 0) > 0 ? <p>{computeCopy.rivalComputable}</p> : null}
          </>
        ) : null}
        <p>
          {selection.request.model === "football"
            ? copy.modelWindowNote
            : windows.length > 1
              ? copy.windowLimits
              : copy.windowNotComputed}
        </p>
        {showModel ? <p>{copy.modelNote}</p> : null}
        {computable && computable.strategies.length > 0 ? <p>{computeCopy.controlsNote}</p> : null}
      </div>
    </details>
  );

  const advanced = (
    <div className={styles.controls}>
      <fieldset className={styles.fieldset}>
        <legend>{evidenceCopy.legend}</legend>
        <label className={styles.windowOption}>
          <input
            type="checkbox"
            name={EVIDENCE_PARAMETER}
            checked={selection.evidence.on}
            disabled={(!evidenceApplies && !evidenceComputable) || chipChosen}
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
            ? chipSwitchesOff
            : !selection.evidence.available && evidenceComputable
              ? computeCopy.wordComputable
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
                  !weightSelectable(weight) || (chipChosen && weight !== 0 && !chipStrategy)
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
        {top100Applies || top100Computable ? (
          <p className={styles.note}>{top100Copy.help}</p>
        ) : null}
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
              disabled={!chipsAvailable && !searchParams.has(CHIP_PARAMETER)}
              onChange={() => update({ [CHIP_PARAMETER]: null })}
              // "None" reads as checked while the link carries a chip the page cannot
              // show; a click on it still has to clear that chip from the link.
              onClick={() => {
                if (searchParams.has(CHIP_PARAMETER)) update({ [CHIP_PARAMETER]: null });
              }}
            />
            <span>{chipStrategy ? strategyCopy.holdChips : chipCopy.none}</span>
          </label>
          {/* Off until the holding value comes from the season calendar (audit H3). */}
          {AUTOMATIC_CHIP_OFFERED && chipStrategy && (
            <label className={styles.windowOption}>
              <input
                type="radio"
                name={CHIP_PARAMETER}
                value="auto"
                checked={chip.chip === "auto"}
                disabled={chipBlocked}
                onChange={() => update({ [CHIP_PARAMETER]: "auto" })}
              />
              <span>{strategyCopy.automatic}</span>
            </label>
          )}
          {CHIP_NAMES.map((name) => (
            <label className={styles.windowOption} key={name}>
              <input
                type="radio"
                name={CHIP_PARAMETER}
                value={name}
                checked={chip.chip === name}
                disabled={!chipApplies || chipBlocked || !chipOptions.includes(name)}
                onChange={() => update({ [CHIP_PARAMETER]: name })}
              />
              <span>{copy.chipNames[name] ?? name}</span>
            </label>
          ))}
        </div>
        <p className={styles.note}>{chipNote}</p>
        {chipReasons.length > 0 ? <p className={styles.note}>{chipReasons.join(" ")}</p> : null}
        {chipApplies && !chipStrategy ? <p className={styles.note}>{chipCopy.help}</p> : null}
      </fieldset>
    </div>
  );

  if (part === "plan") return plan;
  if (part === "notes") return notes;
  if (part === "advanced") return advanced;
  return (
    <>
      {plan}
      {notes}
      {advanced}
    </>
  );
}
