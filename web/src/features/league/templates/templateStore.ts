/**
 * Game templates: a named {strategy, window, rival} the member applies in one tap.
 *
 * Two sources feed the list. The built-in templates come from the play-mode
 * vocabulary the site already computes — one per mode, at the one-week window —
 * and each carries the evidence label its mode already carries elsewhere; nothing
 * here invents a claim. A member's own templates are combinations they named
 * themselves, stored where the viewer claim is stored: in their browser.
 *
 * `TemplateStore` is the seam. Today's implementation is `localStorage`; the
 * authenticated future stores server-side behind the same interface, and the pages
 * never know which one they were handed — the plan's stated design for this step.
 */

import type { PlayMode, WindowSize } from "../../moves/modePrices";

const STORAGE_KEY = "squadopt.templates";

export interface GameTemplate {
  id: string;
  name: string;
  strategy: PlayMode;
  window: WindowSize;
  /** A specific member's entry id, or the standings neighbour just above you. */
  rival: number | "nearest_above";
  builtin?: boolean;
}

export interface TemplateStore {
  list(): GameTemplate[];
  save(template: GameTemplate): void;
  remove(id: string): void;
}

function isTemplate(value: unknown): value is GameTemplate {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.id === "string" &&
    candidate.id.length > 0 &&
    typeof candidate.name === "string" &&
    candidate.name.trim().length > 0 &&
    typeof candidate.strategy === "string" &&
    (candidate.window === 1 || candidate.window === 3 || candidate.window === 5) &&
    (candidate.rival === "nearest_above" ||
      (typeof candidate.rival === "number" &&
        Number.isInteger(candidate.rival) &&
        candidate.rival > 0))
  );
}

export class LocalTemplateStore implements TemplateStore {
  list(): GameTemplate[] {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw === null) return [];
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(isTemplate);
    } catch {
      // A blocked or corrupted store reads as "no saved templates", never an error.
      return [];
    }
  }

  save(template: GameTemplate): void {
    if (!isTemplate(template) || template.builtin) return;
    const others = this.list().filter((existing) => existing.id !== template.id);
    this.write([...others, template]);
  }

  remove(id: string): void {
    this.write(this.list().filter((existing) => existing.id !== id));
  }

  private write(templates: GameTemplate[]): void {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(templates));
    } catch {
      // Saving templates is a convenience; a refusing browser refuses quietly.
    }
  }
}

/**
 * One ready-made template per computed play mode, at the one-week window — the
 * combinations the producer actually publishes today. Names come from the caller
 * (the i18n layer), so this module carries no copy.
 */
export function builtinTemplates(names: Record<PlayMode, string>): GameTemplate[] {
  const modes: PlayMode[] = ["saf-puan", "garantici", "agresif", "asiri-agresif"];
  return modes.map((mode) => ({
    id: `builtin:${mode}:1`,
    name: names[mode],
    strategy: mode,
    window: 1 as WindowSize,
    rival: "nearest_above" as const,
    builtin: true,
  }));
}
