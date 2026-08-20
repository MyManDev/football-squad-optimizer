import { useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { MODE_PRICE_FOLDS, PLAY_MODES, isPlayMode, type PlayMode } from "../modePrices";
import styles from "./DecisionControls.module.css";

const WINDOWS = [1, 3, 5] as const;
type WindowSize = (typeof WINDOWS)[number];

function isWindowSize(value: string | null): value is `${WindowSize}` {
  return WINDOWS.some((window) => String(window) === value);
}

export function DecisionControls() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawMode = searchParams.get("mode");
  const rawWindow = searchParams.get("window");
  const mode: PlayMode = isPlayMode(rawMode) ? rawMode : "saf-puan";
  const windowSize: WindowSize = isWindowSize(rawWindow) ? (Number(rawWindow) as WindowSize) : 1;

  function update(key: "mode" | "window", value: string) {
    const next = new URLSearchParams(searchParams);
    next.set(key, value);
    setSearchParams(next);
  }

  const competitive = mode !== "saf-puan";

  return (
    <Card title="Karar görünümü" aside={<Badge tone="accent">URL&apos;de paylaşılabilir</Badge>}>
      <p className={styles.intro}>
        Pencere ve oyun modu, öneriyi hangi açıdan okumak istediğini kaydeder. Bu ekran mevcut
        ledger kararını gösterir; seçim değiştirmek henüz yeni bir optimizasyon çalıştırmaz.
      </p>

      <div className={styles.controls}>
        <fieldset className={styles.fieldset}>
          <legend>Planlama penceresi</legend>
          <div className={styles.windowOptions}>
            {WINDOWS.map((window) => (
              <label className={styles.windowOption} key={window}>
                <input
                  type="radio"
                  name="window"
                  value={window}
                  checked={windowSize === window}
                  onChange={() => update("window", String(window))}
                />
                <span>{window} hafta</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>Oyun modu</legend>
          <div className={styles.modeOptions}>
            {PLAY_MODES.map((option) => (
              <label className={styles.modeOption} key={option.value}>
                <input
                  type="radio"
                  name="mode"
                  value={option.value}
                  checked={mode === option.value}
                  onChange={() => update("mode", option.value)}
                />
                <span className={styles.modeBody}>
                  <span className={styles.modeHead}>
                    <strong>{option.label}</strong>
                    <span className={styles.price}>{option.price}</span>
                  </span>
                  <span className={styles.description}>{option.description}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className={styles.leagueField}>
          <span>Lig numarası</span>
          <input type="text" inputMode="numeric" placeholder="Lig başlayınca bağlanır" disabled />
          <small>Gerçek lig bağlantısı GW2 capture&apos;ıyla açılacak.</small>
        </label>
      </div>

      {competitive ? (
        <div className={styles.diagnostic} role="note">
          <Badge tone="warn">diagnostik</Badge>
          <span>
            <strong>Lig-içi {windowSize} haftalık sonuç bir olasılık değildir.</strong> Senaryolar
            kalabalığın ölçülen +7,19 puan/hafta üstünlüğünü yalnız kısmen fiyatlıyor; bu nedenle
            rekabetçi pencere yalnız yön gösterir.
          </span>
        </div>
      ) : null}

      <p className={styles.sourceNote}>
        Fiyat etiketleri <code>mode_price_list</code> ölçümünün 0 puan bütçe hücresinden, sentetik
        risk-neutral rakibe karşı {MODE_PRICE_FOLDS} fold üzerinden gelir.
      </p>
    </Card>
  );
}
