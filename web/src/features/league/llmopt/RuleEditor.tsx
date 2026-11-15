import { useState, type FormEvent } from "react";

import {
  clubCountKey,
  isHitBudget,
  isPlanWeek,
  type PlanWeekNumber,
} from "../advice/decisionPreferences";

import { ruleLabel, type LLMOptCopy } from "./copy";
import {
  CONSTRAINT_KINDS,
  constraintKey,
  isPreferenceCost,
  isPlayerKind,
  MAX_CONSTRAINTS,
  needsThreeWeeks,
  type CatalogPlayer,
  type Constraint,
  type PlanDraft,
} from "./intent";
import styles from "./LLMOptPage.module.css";

type Strength = "hard" | "soft" | "comparison";

export function RuleEditor({
  draft,
  players,
  copy,
  disabled,
  change,
}: {
  draft: PlanDraft;
  players: CatalogPlayer[];
  copy: LLMOptCopy;
  disabled: boolean;
  change: (draft: PlanDraft) => void;
}) {
  const [kind, setKind] = useState<Constraint["kind"]>("hold_transfers");
  const [strength, setStrength] = useState<Strength>("hard");
  const [playerId, setPlayerId] = useState("");
  const [club, setClub] = useState("");
  const [clubCount, setClubCount] = useState(1);
  const [clubScope, setClubScope] = useState<"squad" | "transfers_in">("squad");
  const [week, setWeek] = useState<PlanWeekNumber>();
  const [points, setPoints] = useState("4");
  const [cost, setCost] = useState("");
  const [both, setBoth] = useState(false);
  const availablePlayers = kind === "keep_player" ? players.filter(({ held }) => held) : players;
  const player = availablePlayers.find(({ id }) => String(id) === playerId);
  const clubs = [...new Set(players.map(({ team }) => team).filter(Boolean))].sort();
  const selectedClub = clubs.find((name) => name === club);
  const listFull = draft.hard.length + draft.soft.length >= MAX_CONSTRAINTS;
  const selectedWeek = week ?? (kind === "buy_player" ? 1 : undefined);
  const hitBudget = points.trim() ? Number(points) : null;
  const costInput = cost.trim();
  const maxCost = /^\d+(?:[.,]\d)?$/.test(costInput)
    ? Math.round(Number(costInput.replace(",", ".")) * 10)
    : null;
  const invalidCost = strength === "soft" && costInput !== "" && !isPreferenceCost(maxCost);

  function apply(next: PlanDraft) {
    change(needsThreeWeeks(next) ? { ...next, window: 3 } : next);
  }

  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || invalidCost || (strength !== "comparison" && listFull)) return;
    let rule: Constraint;
    const timing = selectedWeek === undefined ? {} : { week: selectedWeek };
    if (kind === "hit_budget") {
      if (!isHitBudget(hitBudget)) return;
      rule = { kind, points: hitBudget };
    } else if (isPlayerKind(kind)) {
      if (!player) return;
      rule =
        kind === "buy_player"
          ? { kind, player_id: player.id, week: selectedWeek ?? 1 }
          : { kind, player_id: player.id, ...timing };
    } else if (kind === "club_count") {
      if (!selectedClub) return;
      rule = {
        kind,
        club: selectedClub,
        count: clubCount,
        ...(clubScope === "transfers_in" ? { scope: clubScope } : {}),
        ...timing,
      };
    } else {
      rule = { kind, ...timing };
    }
    if (strength === "soft" && isPreferenceCost(maxCost)) {
      rule = { ...rule, max_cost_tenths: maxCost };
      setCost("");
    }
    if (strength === "comparison") {
      apply({
        ...draft,
        comparison: both && kind === "include_player" ? { ...rule, both: true } : rule,
      });
    } else {
      const key = constraintKey(rule);
      const replaces = (row: Constraint, inGroup: Strength) =>
        constraintKey(row) === key ||
        (strength === inGroup &&
          ((row.kind === "club_count" &&
            rule.kind === "club_count" &&
            row.week === rule.week &&
            clubCountKey(row) === clubCountKey(rule)) ||
            (row.kind === "hit_budget" && rule.kind === "hit_budget")));
      const hard = draft.hard.filter((row) => !replaces(row, "hard"));
      const soft = draft.soft.filter((row) => !replaces(row, "soft"));
      (strength === "hard" ? hard : soft).push(rule);
      apply({ ...draft, hard, soft });
    }
  }

  const label = (rule: Constraint) => {
    const description = ruleLabel(rule, players, copy);
    return rule.max_cost_tenths === undefined
      ? description
      : `${description} · ${copy.preferenceLimitLabel(rule.max_cost_tenths)}`;
  };

  const columns = [
    { strength: "hard", rules: draft.hard },
    { strength: "soft", rules: draft.soft },
    { strength: "comparison", rules: draft.comparison ? [draft.comparison] : [] },
  ] as const;

  return (
    <>
      <div className={styles.rules}>
        {columns.map(({ strength, rules }) => (
          <section key={strength} className={styles.ruleGroup}>
            <h3>{copy[strength]}</h3>
            {rules.length ? (
              <ul>
                {rules.map((rule, index) => (
                  <li key={constraintKey(rule)}>
                    <span>
                      {label(rule)}
                      {"both" in rule && rule.both ? ` · ${copy.both}` : ""}
                    </span>
                    <button
                      type="button"
                      className={styles.remove}
                      aria-label={`${copy.remove} · ${label(rule)}`}
                      disabled={disabled}
                      onClick={() => {
                        if (strength === "comparison") change({ ...draft, comparison: undefined });
                        else change({ ...draft, [strength]: rules.filter((_, i) => i !== index) });
                      }}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.muted}>{copy.empty}</p>
            )}
          </section>
        ))}
      </div>
      <form onSubmit={add} className={styles.editor}>
        <label>
          {copy.rule}
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as Constraint["kind"]);
              setPlayerId("");
              setClub("");
              setBoth(false);
              setWeek(undefined);
            }}
          >
            {CONSTRAINT_KINDS.map((key) => (
              <option key={key} value={key}>
                {copy.rules[key]}
              </option>
            ))}
          </select>
        </label>
        {isPlayerKind(kind) && (
          <label>
            {copy.player}
            <select value={playerId} onChange={(event) => setPlayerId(event.target.value)}>
              <option value="">{copy.selectPlayer}</option>
              {availablePlayers.map(({ id, name, team }) => (
                <option key={id} value={id}>
                  {name}
                  {team ? ` · ${team}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "club_count" && (
          <>
            <label>
              {copy.club}
              <select value={club} onChange={(event) => setClub(event.target.value)}>
                <option value="">{copy.selectClub}</option>
                {clubs.map((club) => (
                  <option key={club}>{club}</option>
                ))}
              </select>
            </label>
            <label>
              {copy.clubCount}
              <select
                value={clubCount}
                onChange={(event) => setClubCount(Number(event.target.value))}
              >
                {[1, 2, 3].map((count) => (
                  <option key={count}>{count}</option>
                ))}
              </select>
            </label>
            <label>
              {copy.clubCountScope}
              <select
                value={clubScope}
                onChange={(event) =>
                  setClubScope(event.target.value === "transfers_in" ? "transfers_in" : "squad")
                }
              >
                <option value="squad">{copy.clubSquad}</option>
                <option value="transfers_in">{copy.clubTransfers}</option>
              </select>
            </label>
          </>
        )}
        {kind === "hit_budget" ? (
          <label>
            {copy.hitBudget}
            <input
              type="number"
              min={0}
              max={60}
              step={1}
              value={points}
              onChange={(event) => setPoints(event.target.value)}
            />
          </label>
        ) : (
          <label>
            {copy.ruleWeek}
            <select
              value={selectedWeek ?? ""}
              onChange={(event) => {
                const value = Number(event.target.value);
                setWeek(isPlanWeek(value) ? value : undefined);
              }}
            >
              {kind !== "buy_player" && (
                <option value="">{kind === "wildcard" ? copy.thisWeek : copy.everyWeek}</option>
              )}
              {([1, 2, 3] as const)
                .filter((week) => kind !== "wildcard" || week !== 1)
                .map((week) => (
                  <option key={week} value={week}>
                    {week === 1 ? copy.thisWeek : copy.relativeWeek(week)}
                  </option>
                ))}
            </select>
          </label>
        )}
        <label>
          {copy.strength}
          <select
            value={strength}
            onChange={(event) => setStrength(event.target.value as Strength)}
          >
            {columns.map(({ strength }) => (
              <option key={strength} value={strength}>
                {copy[strength]}
              </option>
            ))}
          </select>
        </label>
        {strength === "soft" && (
          <label>
            {copy.preferenceLimit}
            <input
              inputMode="decimal"
              value={cost}
              onChange={(event) => setCost(event.target.value)}
            />
          </label>
        )}
        {strength === "comparison" && kind === "include_player" && (
          <label className={styles.checkbox}>
            <input
              type="checkbox"
              checked={both}
              onChange={(event) => setBoth(event.target.checked)}
            />
            {copy.both}
          </label>
        )}
        <button
          className={styles.secondary}
          disabled={
            disabled ||
            invalidCost ||
            (strength !== "comparison" && listFull) ||
            (isPlayerKind(kind) && !player) ||
            (kind === "club_count" && !selectedClub) ||
            (kind === "hit_budget" && !isHitBudget(hitBudget))
          }
          type="submit"
        >
          {copy.add}
        </button>
      </form>
    </>
  );
}
