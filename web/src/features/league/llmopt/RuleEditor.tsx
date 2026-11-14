import { useState, type FormEvent } from "react";

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
  const [both, setBoth] = useState(false);
  const availablePlayers = kind === "keep_player" ? players.filter(({ held }) => held) : players;
  const player = availablePlayers.find(({ id }) => String(id) === playerId);
  const listFull = draft.hard.length + draft.soft.length >= MAX_CONSTRAINTS;

  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || (strength !== "comparison" && listFull)) return;
    let rule: Constraint;
    if (isPlayerKind(kind)) {
      if (!player) return;
      rule = { kind, player_id: player.id };
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
      const hard = draft.hard.filter((row) => constraintKey(row) !== key);
      const soft = draft.soft.filter((row) => constraintKey(row) !== key);
      (strength === "hard" ? hard : soft).push(rule);
      change({ ...draft, hard, soft });
    }
  }

  function label(rule: Constraint) {
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
            disabled || (strength !== "comparison" && listFull) || (isPlayerKind(kind) && !player)
          }
          type="submit"
        >
          {copy.add}
        </button>
      </form>
    </>
  );
}
