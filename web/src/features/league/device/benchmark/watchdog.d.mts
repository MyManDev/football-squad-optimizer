export interface BrowserMeasurement {
  reply: { kind: string };
  elapsed_seconds: number | null;
  outer_elapsed_seconds: number;
  censored_at_seconds?: number;
}

export function guardedBrowserSolve(
  run: () => Promise<{ reply: { kind: string }; elapsed_seconds: number | null }>,
  closeOwnContext: () => unknown,
  milliseconds?: number,
): Promise<BrowserMeasurement>;
