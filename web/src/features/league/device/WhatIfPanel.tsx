import { useEffect, useId, useRef, useState } from "react";

import { useLanguage } from "../../../i18n/context";
import { figure, money, signedPoints } from "../../../lib/format";
import { PointsUnit } from "../components/PointsUnit";
import type { EntrySquad } from "../types";
import { isDevicePlanEntry, type DevicePlanPlayer } from "./types";
import { useWhatIf, type WhatIfDependencies } from "./useWhatIf";
import type { WhatIfBreak } from "./whatIf";
import styles from "./WhatIfPanel.module.css";

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;

function isPosition(code: string): code is (typeof POSITIONS)[number] {
  return (POSITIONS as readonly string[]).includes(code);
}

/**
 * The what-if mode (#1132): the member starts from the advised fifteen, removes players
 * and adds others from the capture's table, and reads at once the bank, the expected
 * points and the difference to the advice, net of each side's hit. A rule the fifteen
 * breaks is said in words beside it, never refused in silence, and one button returns to
 * the advised fifteen. Removing a player narrows the add list to his position, so the
 * replacement is chosen from a short list; the position list widens it again. Every number is the device solve's own reading of the squad.
 */
export function WhatIfPanel({
  squad,
  advised,
  dependencies,
}: {
  squad: EntrySquad;
  /** The plan's fifteen, by player id. */
  advised: readonly number[];
  dependencies?: WhatIfDependencies;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const addId = useId();
  const positionId = useId();
  const whatIf = useWhatIf(squad, advised, dependencies);
  const { phase, document, account, advisedAccount, points } = whatIf;
  // The player chosen in the list; only the add button adds, so moving through the list
  // with the keyboard changes nothing.
  const [pick, setPick] = useState("");
  // The position the add list shows, or "" for every position.
  const [only, setOnly] = useState<"" | (typeof POSITIONS)[number]>("");
  // Where focus goes after a removal unmounts the row that held it: the next row's remove
  // button, the row before it, or the add list when the group is empty.
  const removeButtons = useRef(new Map<number, HTMLButtonElement>());
  const addList = useRef<HTMLSelectElement>(null);
  const focusNext = useRef<number | "add" | null>(null);
  useEffect(() => {
    const target = focusNext.current;
    if (target === null) return;
    focusNext.current = null;
    (target === "add" ? addList.current : removeButtons.current.get(target))?.focus();
  });

  if (phase !== "ready" || document === null || account === null || advisedAccount === null) {
    const said = {
      idle: null,
      loading: copy.whatIfLoading,
      unpublished: copy.whatIfUnpublished,
      failed: copy.whatIfFailed,
      "solver-failed": copy.whatIfSolverFailed,
      "other-capture": copy.whatIfOtherCapture,
      ready: null,
    }[phase];
    return (
      <div className={styles.whatIf}>
        {phase !== "loading" && phase !== "ready" ? (
          <button type="button" className={styles.action} onClick={whatIf.start}>
            {phase === "idle" ? copy.whatIfStart : copy.whatIfRetry}
          </button>
        ) : null}
        {said ? <p className={styles.state}>{said}</p> : null}
      </div>
    );
  }

  const byId = new Map(document.players.map((player) => [player.id, player]));
  const advisedSet = new Set(advised);
  const chosen = new Set(whatIf.squad);
  const name = (player: DevicePlanPlayer) => player.short_name || player.name;
  // What a player counts for in the bank, as the one-week problem's bank row counts him:
  // a held player at his sale price, anyone else at his price.
  const held = isDevicePlanEntry(squad.device_plan) ? squad.device_plan : null;
  const price = (player: DevicePlanPlayer) =>
    held?.held.includes(player.id)
      ? (held.sell_tenths[String(player.id)] ?? player.buy_tenths)
      : player.buy_tenths;
  const position = (code: string) =>
    Object.hasOwn(messages.positionCodes, code)
      ? messages.positionCodes[code as keyof typeof messages.positionCodes]
      : code;
  const said = (rule: WhatIfBreak) => {
    switch (rule.rule) {
      case "size":
        return copy.whatIfBreaks.size(rule.count, rule.size);
      case "position":
        return copy.whatIfBreaks.position(
          Object.hasOwn(messages.positions, rule.position)
            ? messages.positions[rule.position as keyof typeof messages.positions]
            : rule.position,
          rule.count,
          rule.required,
        );
      case "club":
        return copy.whatIfBreaks.club(rule.team, rule.count, rule.limit);
      case "budget":
        return copy.whatIfBreaks.budget(money(rule.shortTenths, locale));
    }
  };
  const tried = points?.tried ?? null;
  const difference =
    points && points.tried !== null && points.advised !== null
      ? points.tried - account.hitPoints - (points.advised - advisedAccount.hitPoints)
      : null;
  const changed =
    whatIf.squad.length !== advised.length || whatIf.squad.some((id) => !advisedSet.has(id));
  const offered = POSITIONS.filter((code) => only === "" || code === only).map((code) => ({
    code,
    players: document.players
      .filter((player) => player.position === code && !chosen.has(player.id))
      .sort((a, b) => b.expected_points - a.expected_points || a.id - b.id),
  }));

  const removeFrom = (player: DevicePlanPlayer, group: DevicePlanPlayer[]) => {
    const at = group.indexOf(player);
    const neighbour = group[at + 1] ?? group[at - 1];
    focusNext.current = neighbour ? neighbour.id : "add";
    whatIf.remove(player.id);
    if (isPosition(player.position)) setOnly(player.position);
    setPick("");
  };
  const summary = copy.whatIfSummary(
    money(account.bankTenths, locale),
    tried === null ? "-" : figure(tried, locale),
    difference === null ? "-" : signedPoints(difference, 1, locale),
  );

  return (
    <div className={styles.whatIf}>
      <p className="visually-hidden" aria-live="polite">
        {whatIf.reading ? "" : summary}
      </p>
      <dl
        className={styles.account}
        aria-busy={whatIf.reading}
        data-reading={whatIf.reading ? "" : undefined}
      >
        <div>
          <dt>{copy.whatIfBank}</dt>
          <dd className="num" data-short={account.bankTenths < 0 ? "" : undefined}>
            {money(account.bankTenths, locale)}
          </dd>
        </div>
        <div>
          <dt>{copy.whatIfPoints}</dt>
          <dd className="num">
            {tried === null ? "-" : figure(tried, locale)} <PointsUnit />
          </dd>
        </div>
        <div>
          <dt>{copy.whatIfTransfers}</dt>
          <dd className="num">
            {account.transfers}
            {account.hitPoints > 0
              ? ` · ${copy.whatIfHit(signedPoints(-account.hitPoints, 0, locale))}`
              : null}
          </dd>
        </div>
        <div className={styles.headline}>
          <dt>{copy.whatIfDifference}</dt>
          <dd className="num">
            {difference === null ? "-" : signedPoints(difference, 1, locale)} <PointsUnit />
          </dd>
        </div>
      </dl>

      {account.breaks.length > 0 || (points !== null && tried === null && !whatIf.reading) ? (
        <ul className={styles.breaks}>
          {account.breaks.map((rule) => (
            <li
              key={`${rule.rule}-${"position" in rule ? rule.position : "team" in rule ? rule.team : ""}`}
            >
              {said(rule)}
            </li>
          ))}
          {points !== null && tried === null && !whatIf.reading ? (
            <li>{copy.whatIfNoEleven}</li>
          ) : null}
        </ul>
      ) : null}

      {POSITIONS.map((code) => {
        const rows = whatIf.squad
          .map((id) => byId.get(id)!)
          .filter((player) => player.position === code);
        return rows.length === 0 ? null : (
          <ol key={code} className={styles.group} aria-label={messages.positions[code]}>
            {rows.map((player) => (
              <li
                key={player.id}
                className={styles.player}
                data-changed={advisedSet.has(player.id) ? undefined : ""}
              >
                <span className={styles.position}>{position(player.position)}</span>
                <span className={styles.name}>{name(player)}</span>
                <span className={styles.meta}>
                  {player.team} · {money(price(player), locale)}
                </span>
                <span className={`${styles.points} num`}>
                  {figure(player.expected_points, locale)}
                </span>
                <button
                  type="button"
                  className={styles.remove}
                  aria-label={copy.whatIfRemoveLabel(name(player))}
                  ref={(element) => {
                    if (element) removeButtons.current.set(player.id, element);
                    else removeButtons.current.delete(player.id);
                  }}
                  onClick={() => removeFrom(player, rows)}
                >
                  {copy.whatIfRemove}
                </button>
              </li>
            ))}
          </ol>
        );
      })}

      <div className={styles.add}>
        <div className={styles.field}>
          <label htmlFor={positionId}>{copy.whatIfPosition}</label>
          <select
            id={positionId}
            value={only}
            onChange={(event) => {
              const code = event.target.value;
              setOnly(isPosition(code) ? code : "");
              setPick("");
            }}
          >
            <option value="">{copy.whatIfAllPositions}</option>
            {POSITIONS.map((code) => (
              <option key={code} value={code}>
                {messages.positions[code]}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.field}>
          <label htmlFor={addId}>{copy.whatIfAdd}</label>
          <div className={styles.addRow}>
            <select
              id={addId}
              ref={addList}
              value={chosen.has(Number(pick)) ? "" : pick}
              onChange={(event) => setPick(event.target.value)}
            >
              <option value="">{copy.whatIfChoose}</option>
              {offered.map(({ code, players }) => (
                <optgroup key={code} label={messages.positions[code]}>
                  {players.map((player) => (
                    <option key={player.id} value={player.id}>
                      {`${name(player)} · ${player.team} · ${money(price(player), locale)} · ${figure(player.expected_points, locale)}`}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <button
              type="button"
              className={styles.action}
              disabled={pick === "" || chosen.has(Number(pick))}
              onClick={() => {
                const id = Number(pick);
                if (Number.isSafeInteger(id) && id > 0) whatIf.add(id);
                setPick("");
              }}
            >
              {copy.whatIfAddButton}
            </button>
          </div>
        </div>
      </div>

      <button
        type="button"
        className={styles.action}
        disabled={!changed}
        onClick={() => {
          whatIf.reset();
          setOnly("");
          setPick("");
        }}
      >
        {copy.whatIfReset}
      </button>
    </div>
  );
}
