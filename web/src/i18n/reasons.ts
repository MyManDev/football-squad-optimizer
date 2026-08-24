import type { Messages, ReasonParams } from "./messages";

/**
 * Payload documents carry stable codes beside their English prose; the page
 * translates the code and falls back to the recorded sentence whenever the
 * code is unknown or absent (documents from older builders).
 */

export function reasonText(
  messages: Messages,
  code: string | undefined,
  params: Record<string, unknown> | undefined,
  fallback: string,
): string {
  const table = messages.reasonCodes as unknown as Record<string, (values: ReasonParams) => string>;
  const build = code ? table[code] : undefined;
  return build ? build((params ?? {}) as ReasonParams) : fallback;
}

export function verdictText(
  messages: Messages,
  code: string | undefined,
  params: Record<string, unknown> | undefined,
  fallback: string,
): string {
  const table = messages.verdictCodes as unknown as Record<
    string,
    (values: ReasonParams) => string
  >;
  const build = code ? table[code] : undefined;
  return build ? build((params ?? {}) as ReasonParams) : fallback;
}

export function riskText(
  messages: Messages,
  status: string,
  blockers: readonly string[],
  fallback: string,
): string {
  const table = messages.riskReasons as unknown as Record<string, string>;
  if (status === "unavailable") {
    const lines = blockers.map((blocker) => table[blocker]).filter(Boolean);
    return lines.length > 0 ? lines.join(" ") : fallback;
  }
  return table[status] ?? fallback;
}
