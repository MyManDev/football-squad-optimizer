import { useEffect, useMemo, useRef, useState } from "react";

import { useLanguage } from "../../../i18n/context";
import { MESSAGES } from "../../../i18n/messages";
import { figure } from "../../../lib/format";
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
  const [shareFailed, setShareFailed] = useState(false);
  const data = useMemo(() => cardData(view, squad), [view, squad]);
  const preview = useRef<HTMLImageElement>(null);
  // False once the tool is gone (a plan switch unmounts it): a card that finishes drawing
  // after that gets no object URL, since nothing would be left to revoke it.
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const url = state.phase === "ready" ? state.url : null;
  // Only the card on screen keeps an object URL: a redraw or leaving the page revokes it.
  useEffect(
    () => () => {
      if (url !== null) URL.revokeObjectURL(url);
    },
    [url],
  );
  // A new card takes the focus, so the keyboard lands on what was made.
  useEffect(() => {
    if (url !== null) preview.current?.focus();
  }, [url]);

  if (data === null) return <p className={styles.note}>{copy.cardUnavailable}</p>;

  // The page's own labels, and its figures as it prints the same plan: the expected points
  // as the squad heading does, the hit as the gain strip says it.
  const cardCopy: CardCopy = {
    title: copy.cardWeekTitle,
    captain: copy.captainLabel,
    viceCaptain: copy.viceCaptainLabel,
    captainMark: copy.captainMark,
    viceMark: copy.viceMark,
    bench: copy.bench,
    transfers: copy.cardTransfers,
    noTransfers: copy.cardNoTransfers,
    hit: (value) => copy.hitPointsFact(value.toLocaleString(locale, { maximumFractionDigits: 1 })),
    expectedPoints: copy.cardExpectedPoints,
    chip: copy.chipLabel,
    chipNames: copy.chipNames,
    formatPoints: (value) => figure(value, locale),
  };
  const fileName = `squadopt-gw${data.gameweek}.png`;
  const busy = state.phase === "drawing";

  const toggle = (field: CardField) =>
    setFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });

  const create = async () => {
    // The button keeps the focus while the card is drawn, so a second press ends here.
    if (busy) return;
    setState({ phase: "drawing" });
    setShareFailed(false);
    try {
      const card = squadCardSvg(data, fields, cardCopy);
      const blob = await draw(card.svg, card.width, card.height);
      if (!mounted.current) return;
      const file = new File([blob], fileName, { type: "image/png" });
      setState({ phase: "ready", url: URL.createObjectURL(blob), file, data, fields, language });
    } catch {
      if (mounted.current) setState({ phase: "failed" });
    }
  };

  const share = async (file: File) => {
    setShareFailed(false);
    try {
      await navigator.share({ files: [file] });
    } catch (error) {
      // A share the member cancels is no failure; any other refusal is said.
      const cancelled = error instanceof DOMException && error.name === "AbortError";
      if (!cancelled && mounted.current) setShareFailed(true);
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
              disabled={busy}
            />
            {copy.cardFieldNames[field]}
          </label>
        ))}
      </fieldset>
      <button
        type="button"
        className={styles.action}
        onClick={() => void create()}
        aria-disabled={busy}
      >
        {busy ? copy.cardDrawing : copy.cardCreate}
      </button>
      {state.phase === "failed" ? (
        <p className={styles.note} role="alert">
          {copy.cardFailed}
        </p>
      ) : null}
      <p className="visually-hidden" role="status">
        {drawn !== null ? copy.cardReady : ""}
      </p>
      {drawn !== null ? (
        <div className={styles.result}>
          <img
            ref={preview}
            className={styles.preview}
            src={drawn.url}
            alt={copy.cardPreviewAlt(data.gameweek)}
            tabIndex={-1}
          />
          <div className={styles.actions}>
            <a className={styles.action} href={drawn.url} download={fileName}>
              {copy.cardSave}
            </a>
            {canShare ? (
              <button
                type="button"
                className={styles.action}
                onClick={() => void share(drawn.file)}
              >
                {copy.cardShare}
              </button>
            ) : null}
          </div>
          {shareFailed ? (
            <p className={styles.note} role="alert">
              {copy.cardShareFailed}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
