import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { withRequestDeadline } from "../../../data/request";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import type { EntrySquad } from "../types";
import {
  checkedPreferences,
  preferencesFromUrl,
  preferencesKey,
  type DecisionPreferences,
} from "./decisionPreferences";
import styles from "./MemberDecisionControls.module.css";

interface Player {
  id: number;
  name: string;
  team: string;
  position: string;
}

export function DecisionPreferencesPanel({
  squad,
  available,
}: {
  squad: EntrySquad;
  available: boolean;
}) {
  const { language } = useLanguage();
  const tr = language === "tr";
  const [params, setParams] = useSearchParams();
  const selected = preferencesFromUrl(params);
  const preferences = selected.value ?? checkedPreferences(undefined);
  const [catalog, setCatalog] = useState<Player[]>([]);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [team, setTeam] = useState("");
  const [position, setPosition] = useState("");
  const owned = [...squad.starting_xi, ...squad.bench];
  useEffect(() => {
    if (!available) return;
    const controller = new AbortController();
    const origin = ((import.meta.env.VITE_ADVICE_API_ORIGIN as string | undefined) ?? "").replace(
      /\/$/,
      "",
    );
    void withRequestDeadline(
      async (signal) => {
        const response = await fetch(`${origin}/api/v1/contributions/players`, {
          signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Roster unavailable");
        const value = (await response.json()) as { season?: string; players?: Player[] };
        if (
          value.season !== squad.season ||
          !Array.isArray(value.players) ||
          !value.players.every(
            (p) =>
              p &&
              Number.isSafeInteger(p.id) &&
              p.id > 0 &&
              typeof p.name === "string" &&
              typeof p.team === "string" &&
              ["GK", "DEF", "MID", "FWD"].includes(p.position),
          )
        )
          throw new Error("Invalid roster");
        if (!controller.signal.aborted) {
          setCatalog(value.players);
          setCatalogFailed(false);
        }
      },
      { signal: controller.signal },
    ).catch(() => {
      if (!controller.signal.aborted) setCatalogFailed(true);
    });
    return () => controller.abort();
  }, [available, squad.season]);
  function update(patch: Partial<DecisionPreferences>) {
    const next = new URLSearchParams(params);
    const value = checkedPreferences({ ...preferences, ...patch });
    const key = preferencesKey(value);
    if (key) next.set("preferences", key);
    else next.delete("preferences");
    if (patch.save_chips === true) next.delete("chip");
    setParams(next);
  }
  function clear() {
    const next = new URLSearchParams(params);
    next.delete("preferences");
    setParams(next);
  }
  const unknownHeld = preferences.keep_players.some((id) => !owned.some((p) => p.player_id === id));
  const conflict =
    !selected.valid ||
    (selected.value &&
      ((params.get("mode") ?? "saf-puan") !== "saf-puan" ||
        params.get("llm") === "on" ||
        (preferences.save_chips && params.has("chip"))));
  const nameOf = (id: number) =>
    catalog.find((p) => p.id === id)?.name ??
    owned.find((p) => p.player_id === id)?.name ??
    `#${id}`;
  return (
    <Card title={tr ? "Karar tercihlerim" : "My decision preferences"}>
      <p>
        {tr
          ? "Bu kurallar seçtiğiniz 1, 3 veya 5 haftanın tamamında geçerlidir. Oyuncuyu tutmak ilk 11 garantisi değildir. Tahmin puanları değişmez; optimizer bu sınırlar içinde karar verir."
          : "These constraints apply throughout the selected 1, 3 or 5 weeks. Keeping a player does not guarantee a start. Forecast points stay unchanged; the optimizer decides within these limits."}
      </p>
      {!available && (
        <p>
          {tr
            ? "Tercihli hesaplama bu veri görüntüsü için henüz kullanılabilir değil."
            : "Preference computation is not available for this capture."}
        </p>
      )}
      {unknownHeld && (
        <p role="alert">
          {tr
            ? "Tutulması istenen oyuncu bu kadroda yok. İlgili tercihi kaldırın veya doğru üyenin sayfasını açın."
            : "A kept player is not in this squad. Remove that preference or open the correct member."}
        </p>
      )}
      {conflict && (
        <p role="alert">
          {tr
            ? "Tercihler geçersiz veya seçiminizle çelişiyor. Saf puanı seçin, teknik direktör yorumunu kapatın; çipleri saklarken başka çip seçmeyin. Tercihler sessizce kaldırılmaz."
            : "Invalid or conflicting preferences. Select pure points, turn manager news off and do not choose a chip while saving chips. Preferences are never silently discarded."}
        </p>
      )}
      <fieldset className={styles.fieldset} disabled={!available || !selected.valid}>
        <legend>{tr ? "Oyuncular" : "Players"}</legend>
        <label className={styles.rivalField}>
          {tr ? "Kadroda tut" : "Keep in squad"}
          <select
            value=""
            onChange={(event) =>
              update({ keep_players: [...preferences.keep_players, Number(event.target.value)] })
            }
          >
            <option value="" disabled>
              {tr ? "Oyuncu seç" : "Choose player"}
            </option>
            {owned.map((p) => (
              <option
                key={p.player_id}
                value={p.player_id}
                disabled={
                  preferences.keep_players.includes(p.player_id) ||
                  preferences.avoid_players.includes(p.player_id)
                }
              >
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <p>
          {tr
            ? "Kadroya alma seçimi, oyuncu zaten kadrodaysa ilk hafta çıkarılmasını da gerektirir. Bu kısıtlar bütçe veya transfer haklarıyla çelişirse plan üretilemez."
            : "Avoid also requires selling an already owned player in the first week. Conflicts with budget or transfer rights may leave no feasible plan."}
        </p>
        <label className={styles.rivalField}>
          {tr ? "Alınmayacak oyuncunun takımı" : "Avoid player's team"}
          <select
            value={team}
            onChange={(e) => {
              setTeam(e.target.value);
              setPosition("");
            }}
          >
            <option value="">{tr ? "Takım seç" : "Choose team"}</option>
            {[...new Set(catalog.map((p) => p.team))].sort().map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label className={styles.rivalField}>
          {tr ? "Pozisyon" : "Position"}
          <select value={position} disabled={!team} onChange={(e) => setPosition(e.target.value)}>
            <option value="">{tr ? "Pozisyon seç" : "Choose position"}</option>
            {[...new Set(catalog.filter((p) => p.team === team).map((p) => p.position))].map(
              (p) => (
                <option key={p}>{p}</option>
              ),
            )}
          </select>
        </label>
        <label className={styles.rivalField}>
          {tr ? "Kadroya alma" : "Avoid player"}
          <select
            value=""
            disabled={!position || preferences.avoid_players.length >= 15}
            onChange={(e) =>
              update({ avoid_players: [...preferences.avoid_players, Number(e.target.value)] })
            }
          >
            <option value="" disabled>
              {tr ? "Oyuncu seç" : "Choose player"}
            </option>
            {catalog
              .filter((p) => p.team === team && p.position === position)
              .map((p) => (
                <option
                  key={p.id}
                  value={p.id}
                  disabled={
                    preferences.keep_players.includes(p.id) ||
                    preferences.avoid_players.includes(p.id)
                  }
                >
                  {p.name}
                </option>
              ))}
          </select>
        </label>
        {catalogFailed && (
          <p role="status">
            {tr
              ? "Oyuncu listesi yüklenemedi. Kadroda tut ve kaynak tercihleri kullanılabilir."
              : "Player list unavailable. Keep and resource preferences remain available."}
          </p>
        )}
        {(["keep_players", "avoid_players"] as const).map((key) => (
          <ul key={key}>
            {preferences[key].map((id) => (
              <li key={id}>
                {key === "keep_players" ? (tr ? "Tut" : "Keep") : tr ? "Alma" : "Avoid"}:{" "}
                {nameOf(id)}{" "}
                <button
                  type="button"
                  onClick={() => update({ [key]: preferences[key].filter((p) => p !== id) })}
                  aria-label={`${tr ? "Kaldır" : "Remove"} ${nameOf(id)}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        ))}
        <label className={styles.option}>
          <input
            type="checkbox"
            checked={preferences.no_hits}
            onChange={(e) => update({ no_hits: e.target.checked })}
          />
          {tr ? "Puan cezası doğuran transfer yapma" : "No paid transfers"}
        </label>
        <label className={styles.option}>
          <input
            type="checkbox"
            checked={preferences.save_chips}
            onChange={(e) => update({ save_chips: e.target.checked })}
          />
          {tr ? "Çipleri pencere boyunca sakla" : "Save chips throughout the window"}
        </label>
      </fieldset>
      {(selected.value || !selected.valid) && (
        <button type="button" onClick={clear}>
          {tr ? "Tercihleri temizle" : "Clear preferences"}
        </button>
      )}
    </Card>
  );
}
