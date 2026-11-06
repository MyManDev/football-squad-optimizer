export type PitchPointsKind = "expected" | "actual";

export function playerPoints(
  player: { expectedPoints: number | null; eventPoints?: number | null },
  kind: PitchPointsKind,
): number | null {
  return kind === "actual" ? (player.eventPoints ?? null) : player.expectedPoints;
}
