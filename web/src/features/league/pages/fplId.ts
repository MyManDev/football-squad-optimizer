/**
 * The number typed, or the one in a link to the game pasted whole: a league's from its
 * `/leagues/<id>/` address, a team's from `/entry/<id>/`. `kind` says which the field asks for.
 */
export function idIn(value: string, kind: "league" | "entry" = "league"): number | null {
  const trimmed = value.trim();
  const linked = new RegExp(`/${kind === "league" ? "leagues" : "entry"}/(\\d+)(?:/|$|\\?)`).exec(
    trimmed,
  );
  const digits = linked?.[1] ?? trimmed;
  const id = Number(digits);
  return /^\d+$/.test(digits) && Number.isSafeInteger(id) && id > 0 ? id : null;
}
