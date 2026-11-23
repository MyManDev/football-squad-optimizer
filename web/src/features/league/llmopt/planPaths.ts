import { checkedPreferences, type DecisionPreferences } from "../advice/decisionPreferences";

/** A real delayed acquisition, preserving every existing rule. */
export function delayedBuyPreferences(
  reference: DecisionPreferences,
  players: number[],
): DecisionPreferences | null {
  if (
    !players.length ||
    players.length > 15 ||
    new Set(players).size !== players.length ||
    players.some((id) => !Number.isSafeInteger(id) || id < 1) ||
    reference.frozen_weeks?.some((week) => week.week === 1 || week.week === 2)
  )
    return null;
  const second = reference.week_rules?.find((row) => row.week === 2)?.rules;
  if (second?.hold_transfers) return null;
  try {
    return checkedPreferences({
      ...reference,
      hold_opening_transfers: true,
      week_rules: [
        ...(reference.week_rules ?? []).filter((row) => row.week !== 2),
        {
          week: 2,
          rules: {
            keep_players: [],
            avoid_players: [],
            no_hits: false,
            save_chips: false,
            ...second,
            buy_players: [...new Set([...(second?.buy_players ?? []), ...players])].sort(
              (a, b) => a - b,
            ),
          },
        },
      ],
    });
  } catch {
    return null;
  }
}
