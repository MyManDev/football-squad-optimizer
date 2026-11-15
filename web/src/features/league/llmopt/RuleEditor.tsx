import { useState, type FormEvent } from "react";

import { clubCountKey } from "../advice/decisionPreferences";

import type { LLMOptCopy } from "./copy";
import {
  CONSTRAINT_KINDS,
  constraintKey,
  isPlayerKind,
  MAX_CONSTRAINTS,
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
  const [both, setBoth] = useState(false);
  const availablePlayers = kind === "keep_player" ? players.filter(({ held }) => held) : players;
  const player = availablePlayers.find(({ id }) => String(id) === playerId);
  const clubs = [...new Set(players.map(({ team }) => team).filter(Boolean))].sort();
  const selectedClub = clubs.find((name) => name === club);
  const listFull = draft.hard.length + draft.soft.length >= MAX_CONSTRAINTS;

  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || (strength !== "comparison" && listFull)) return;
    let rule: Constraint;
    if (isPlayerKind(kind)) {
      if (!player) return;
      rule = { kind, player_id: player.id };
    } else if (kind === "club_count") {
      if (!selectedClub) return;
      rule = {
        kind,
        club: selectedClub,
        count: clubCount,
        ...(clubScope === "transfers_in" ? { scope: clubScope } : {}),
      };
    } else {
      rule = { kind };
    }
    if (strength === "comparison") {
      change({
        ...draft,
        comparison: both && kind === "include_player" ? { ...rule, both: true } : rule,
      });
    } else {
      const key = constraintKey(rule);
      const replaces = (row: Constraint, inGroup: Strength) =>
        constraintKey(row) === key ||
        (strength === inGroup &&
          row.kind === "club_count" &&
          rule.kind === "club_count" &&
          clubCountKey(row) === clubCountKey(rule));
      const hard = draft.hard.filter((row) => !replaces(row, "hard"));
      const soft = draft.soft.filter((row) => !replaces(row, "soft"));
      (strength === "hard" ? hard : soft).push(rule);
      change({ ...draft, hard, soft });
    }
  }

  function label(rule: Constraint) {
    if (rule.kind === "club_count") {
      const scope = rule.scope === "transfers_in" ? copy.clubTransfers : copy.clubSquad;
      return `${rule.club} · ${scope} · ${rule.count}`;
    }
    if (!("player_id" in rule)) return copy.rules[rule.kind];
    const selected = players.find(({ id }) => id === rule.player_id);
    return `${copy.rules[rule.kind]} · ${selected?.name ?? rule.player_id}`;
  }

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
            (strength !== "comparison" && listFull) ||
            (isPlayerKind(kind) && !player) ||
            (kind === "club_count" && !selectedClub)
          }
          type="submit"
        >
          {copy.add}
        </button>
      </form>
    </>
  );
}
