import { useEffect, useMemo, useState } from "react";

import { useLanguage } from "../../../i18n/context";
import { MESSAGES } from "../../../i18n/messages";
import { points } from "../../../lib/format";
import type { EntryAdvice, EntrySquad } from "../types";
import { drawCard } from "./drawCard";
import {
  CARD_FIELDS,
  DEFAULT_CARD_FIELDS,
  cardData,
  squadCardSvg,
  type CardCopy,
  type CardField,
} from "./cardModel";
import styles from "./SquadCard.module.css";

type Props = {
  view: EntryAdvice;
  squad: EntrySquad;
  /** The SVG-to-PNG step; tests replace the browser's canvas with their own. */
  draw?: typeof drawCard;
};

type State =
  | { phase: "idle" }
  | { phase: "drawing" }
  | {
      phase: "ready";
      url: string;
      file: File;
      // What the card was drawn from; a new plan, choice or language makes it stale.
      data: unknown;
      fields: ReadonlySet<CardField>;
      language: string;
    }
  | { phase: "failed" };

/**
 * The shareable squad card (#1135 part 3): the member picks the fields, and the card is drawn
 * on this device from the plan on screen. It is saved or shared from here; the page uploads
 * nothing.
 */
export function SquadCard({ view, squad, draw = drawCard }: Props) {
  const { language, locale } = useLanguage();
  const copy = MESSAGES[language].leagueMembers;
  const [fields, setFields] = useState<ReadonlySet<CardField>>(new Set(DEFAULT_CARD_FIELDS));
  const [state, setState] = useState<State>({ phase: "idle" });
  const data = useMemo(() => cardData(view, squad), [view, squad]);

  useEffect(
    () => () => {
      if (state.phase === "ready") URL.revokeObjectURL(state.url);
    },
    [state],
  );

  if (data === null) return <p className={styles.note}>{copy.cardUnavailable}</p>;

  const cardCopy: CardCopy = {
    title: copy.cardWeekTitle,
    captain: copy.cardCaptain,
    viceCaptain: copy.cardViceCaptain,
    bench: copy.cardBench,
    transfers: copy.cardTransfers,
    noTransfers: copy.cardNoTransfers,
    hit: copy.cardHit,
    expectedPoints: copy.cardExpectedPoints,
    chip: copy.cardChip,
    chipNames: copy.chipNames,
    formatPoints: (value) => points(value, 1, locale),
  };
  const fileName = `squadopt-gw${data.gameweek}.png`;

  const toggle = (field: CardField) =>
    setFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });

  const create = async () => {
    setState({ phase: "drawing" });
    try {
      const card = squadCardSvg(data, fields, cardCopy);
      const blob = await draw(card.svg, card.width, card.height);
      const file = new File([blob], fileName, { type: "image/png" });
      setState({ phase: "ready", url: URL.createObjectURL(blob), file, data, fields, language });
    } catch {
      setState({ phase: "failed" });
    }
  };

  const drawn =
    state.phase === "ready" &&
    state.data === data &&
    state.fields === fields &&
    state.language === language
      ? state
      : null;
  const canShare =
    drawn !== null &&
    typeof navigator !== "undefined" &&
    typeof navigator.canShare === "function" &&
    navigator.canShare({ files: [drawn.file] });

  return (
    <div className={styles.card}>
      <fieldset className={styles.fields}>
        <legend>{copy.cardFieldsLegend}</legend>
        {CARD_FIELDS.map((field) => (
          <label key={field} className={styles.field}>
            <input
              type="checkbox"
              checked={fields.has(field)}
              onChange={() => toggle(field)}
              disabled={state.phase === "drawing"}
            />
            {copy.cardFieldNames[field]}
          </label>
        ))}
      </fieldset>
      <button
        type="button"
        className={styles.action}
        onClick={() => void create()}
        disabled={state.phase === "drawing"}
      >
        {state.phase === "drawing" ? copy.cardDrawing : copy.cardCreate}
      </button>
      {state.phase === "failed" ? (
        <p className={styles.note} role="alert">
          {copy.cardFailed}
        </p>
      ) : null}
      {drawn !== null ? (
        <div className={styles.result}>
          <img
            className={styles.preview}
            src={drawn.url}
            alt={copy.cardPreviewAlt(data.gameweek)}
          />
          <div className={styles.actions}>
            <a className={styles.action} href={drawn.url} download={fileName}>
              {copy.cardSave}
            </a>
            {canShare ? (
              <button
                type="button"
                className={styles.action}
                onClick={() => void navigator.share({ files: [drawn.file] }).catch(() => undefined)}
              >
                {copy.cardShare}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
