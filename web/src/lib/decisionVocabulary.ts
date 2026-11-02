/** The words a decision request is made of: the four play modes and the planning windows. */
export type PlayMode = "saf-puan" | "garantici" | "agresif" | "asiri-agresif";
export const WINDOWS = [1, 3, 5] as const;
export type WindowSize = (typeof WINDOWS)[number];

export function isPlayMode(value: string | null): value is PlayMode {
  return ["saf-puan", "garantici", "agresif", "asiri-agresif"].includes(value ?? "");
}
