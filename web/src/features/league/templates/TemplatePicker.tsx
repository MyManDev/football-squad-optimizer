/**
 * The template picker: apply a named {strategy, window} in one tap, save your own.
 *
 * Applying a template sets the same URL parameters the decision controls read, so
 * the whole selection stays shareable — the address bar is the state. Triggering
 * the computation itself is the compute-flow's work; until it lands, applying a
 * template shows exactly what the published site can show for that combination.
 */

import { useState } from "react";
import { useSearchParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { isPlayMode, type PlayMode } from "../../moves/modePrices";
import {
  builtinTemplates,
  LocalTemplateStore,
  type GameTemplate,
  type TemplateStore,
} from "./templateStore";
import styles from "./TemplatePicker.module.css";

const DEFAULT_STORE = new LocalTemplateStore();

export function TemplatePicker({ store = DEFAULT_STORE }: { store?: TemplateStore }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const modeCopy = messages.decision.modes;
  const [searchParams, setSearchParams] = useSearchParams();
  const [saved, setSaved] = useState<GameTemplate[]>(() => store.list());
  const [draftName, setDraftName] = useState("");

  const builtins = builtinTemplates({
    "saf-puan": modeCopy.pure,
    garantici: modeCopy.safe,
    agresif: modeCopy.aggressive,
    "asiri-agresif": modeCopy.extreme,
  });

  const activeMode: PlayMode = isPlayMode(searchParams.get("mode"))
    ? (searchParams.get("mode") as PlayMode)
    : "saf-puan";
  const activeWindow = searchParams.get("window") ?? "1";

  function apply(template: GameTemplate): void {
    const next = new URLSearchParams(searchParams);
    next.set("mode", template.strategy);
    next.set("window", String(template.window));
    setSearchParams(next);
  }

  function saveCurrent(): void {
    const name = draftName.trim();
    if (!name) return;
    const template: GameTemplate = {
      id: `own:${name.toLowerCase().replace(/\s+/g, "-")}`,
      name,
      strategy: activeMode,
      window: Number(activeWindow) === 3 ? 3 : Number(activeWindow) === 5 ? 5 : 1,
      rival: "nearest_above",
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
    <Card tone="muted" title={copy.templatesTitle}>
      <p className={styles.hint}>{copy.templatesBody}</p>
      <div className={styles.list}>
        {[...builtins, ...saved].map((template) => {
          const active =
            template.strategy === activeMode && String(template.window) === activeWindow;
          return (
            <span key={template.id} className={styles.item}>
              <button
                type="button"
                className={active ? styles.templateActive : styles.template}
                onClick={() => apply(template)}
              >
                {template.name}
                <span className={styles.meta}>
                  {copy.templateMeta(template.strategy, template.window)}
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
      </div>
      <div className={styles.saveRow}>
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
      </div>
    </Card>
  );
}
