import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { figure, money, signedPoints } from "../../../lib/format";
import { PointsUnit } from "../components/PointsUnit";
import type { EntrySquad } from "../types";
import { isDevicePlanEntry, type DevicePlanPlayer } from "./types";
import { useWhatIf, type WhatIfDependencies } from "./useWhatIf";
import type { WhatIfBreak } from "./whatIf";
import styles from "./WhatIfPanel.module.css";

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;

/**
 * The what-if mode (#1132): the member starts from the advised fifteen, removes players
 * and adds others from the capture's table, and reads at once the bank, the expected
 * points and the difference to the advice, net of each side's hit. A rule the fifteen
 * breaks is said in words beside it, never refused in silence, and one button returns to
 * the advised fifteen. Every number is the device solve's own reading of the squad.
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
  const whatIf = useWhatIf(squad, advised, dependencies);
  const { phase, document, account, advisedAccount, points } = whatIf;

  if (phase !== "ready" || document === null || account === null || advisedAccount === null) {
    const said = {
      idle: null,
      loading: copy.whatIfLoading,
      unpublished: copy.whatIfUnpublished,
      failed: copy.whatIfFailed,
      "other-capture": copy.whatIfOtherCapture,
      ready: null,
    }[phase];
    return (
      <div className={styles.whatIf}>
        {phase === "idle" ? (
          <button type="button" className={styles.action} onClick={whatIf.start}>
            {copy.whatIfStart}
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
  const offered = POSITIONS.map((code) => ({
    code,
    players: document.players
      .filter((player) => player.position === code && !chosen.has(player.id))
      .sort((a, b) => b.expected_points - a.expected_points || a.id - b.id),
  }));

  return (
    <div className={styles.whatIf}>
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
                  onClick={() => whatIf.remove(player.id)}
                >
                  {copy.whatIfRemove}
                </button>
              </li>
            ))}
          </ol>
        );
      })}

      <label className={styles.add} htmlFor={addId}>
        <span>{copy.whatIfAdd}</span>
        <select
          id={addId}
          value=""
          onChange={(event) => {
            const id = Number(event.target.value);
            if (Number.isSafeInteger(id) && id > 0) whatIf.add(id);
          }}
        >
          <option value="">{copy.whatIfAdd}</option>
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
      </label>

      <button type="button" className={styles.action} disabled={!changed} onClick={whatIf.reset}>
        {copy.whatIfReset}
      </button>
    </div>
  );
}
