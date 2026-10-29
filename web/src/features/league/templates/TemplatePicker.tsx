/**
 * The template picker: apply a named {strategy, window} in one tap, save your own.
 *
 * Applying a template sets the same URL parameters the decision controls read, so
 * the whole selection stays shareable — the address bar is the state. Triggering
 * the computation itself is the compute-flow's work; until it lands, applying a
 * template shows exactly what the published site can show for that combination.
 *
 * The member page puts the picker at the top of the plan settings, one compact row of chips
 * over the strategy and window it sets, so the plan is chosen in one place. A built-in chip
 * is named by its strategy and adds only its window; a member's own chip says the whole
 * selection it stands for, since its name is the member's.
 */

import { useState } from "react";
import { useSearchParams } from "react-router";

import { useLanguage } from "../../../i18n/context";
import { isPlayMode } from "../../../lib/decisionVocabulary";
import { isMemberStrategy, type AdviceStrategy } from "../types";
import {
  builtinTemplates,
  LocalTemplateStore,
  type GameTemplate,
  type TemplateStore,
} from "./templateStore";
import styles from "./TemplatePicker.module.css";

const DEFAULT_STORE = new LocalTemplateStore();

export function TemplatePicker({
  store = DEFAULT_STORE,
  canApply,
}: {
  store?: TemplateStore;
  canApply?: (selection: URLSearchParams) => boolean;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const [searchParams, setSearchParams] = useSearchParams();
  const [saved, setSaved] = useState<GameTemplate[]>(() => store.list());
  const [draftName, setDraftName] = useState("");

  const builtins = builtinTemplates({
    "saf-puan": copy.strategies["saf-puan"].name,
    "ortak-koru": copy.strategies["ortak-koru"].name,
    "fark-yarat": copy.strategies["fark-yarat"].name,
  });

  const rawMode = searchParams.get("mode");
  const activeMode: AdviceStrategy = isMemberStrategy(rawMode)
    ? rawMode
    : isPlayMode(rawMode)
      ? rawMode
      : "saf-puan";
  const activeWindow = searchParams.get("window") ?? "1";
  const rawRival = Number(searchParams.get("rival"));
  const activeRival: number | "nearest_above" =
    Number.isInteger(rawRival) && rawRival > 0 ? rawRival : "nearest_above";

  function selectionFor(template: GameTemplate): URLSearchParams {
    const next = new URLSearchParams(searchParams);
    next.set("mode", template.strategy);
    next.set("window", String(template.window));
    // A named rival travels with the template; the standings neighbour is the
    // producer's default and needs no parameter.
    if (template.rival === "nearest_above") next.delete("rival");
    else next.set("rival", String(template.rival));
    return next;
  }

  function apply(template: GameTemplate): void {
    const next = selectionFor(template);
    if (!canApply || canApply(next)) setSearchParams(next);
  }

  function saveCurrent(): void {
    const name = draftName.trim();
    if (!name) return;
    const template: GameTemplate = {
      id: `own:${name.toLowerCase().replace(/\s+/g, "-")}`,
      name,
      strategy: activeMode,
      window: Number(activeWindow) === 3 ? 3 : Number(activeWindow) === 5 ? 5 : 1,
      rival: activeRival,
    };
    store.save(template);
    setSaved(store.list());
    setDraftName("");
  }

  function removeTemplate(id: string): void {
    store.remove(id);
    setSaved(store.list());
  }

  return (
    <fieldset className={styles.presets}>
      <legend className={styles.legend}>{copy.templatesTitle}</legend>
      <div className={styles.list}>
        {[...builtins, ...saved].map((template) => {
          const active =
            template.strategy === activeMode &&
            String(template.window) === activeWindow &&
            template.rival === activeRival;
          return (
            <span key={template.id} className={styles.item}>
              <button
                type="button"
                className={active ? styles.templateActive : styles.template}
                disabled={canApply ? !canApply(selectionFor(template)) : false}
                onClick={() => apply(template)}
              >
                {template.name}
                <span className={styles.meta}>
                  {template.builtin
                    ? messages.decision.week(template.window)
                    : copy.templateMeta(
                        isMemberStrategy(template.strategy)
                          ? copy.strategies[template.strategy].name
                          : template.strategy,
                        template.window,
                        template.rival === "nearest_above"
                          ? copy.computeRivalNearest
                          : `#${template.rival}`,
                      )}
                </span>
              </button>
              {template.builtin ? null : (
                <button
                  type="button"
                  aria-label={copy.templateRemove(template.name)}
                  className={styles.remove}
                  onClick={() => removeTemplate(template.id)}
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
        {/* Saving the current selection is the row's last chip: a name and one button. */}
        <span className={styles.saveRow}>
          <input
            className={styles.nameInput}
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
            placeholder={copy.templateNamePlaceholder}
            aria-label={copy.templateNamePlaceholder}
          />
          <button type="button" className={styles.save} onClick={saveCurrent}>
            {copy.templateSave}
          </button>
        </span>
      </div>
    </fieldset>
  );
}
