import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { useDecisionSelection } from "../decisionSelection";
import { MODE_PRICE_FOLDS, WINDOWS, getPlayModes } from "../modePrices";
import styles from "./DecisionControls.module.css";

export function DecisionControls({ variant = "default" }: { variant?: "default" | "entry" }) {
  const { locale, messages } = useLanguage();
  const copy = messages.decision;
  const playModes = getPlayModes(
    copy.modes,
    locale,
    variant === "entry" ? "point-cost" : "measured",
  );
  const { mode, windowSize, update } = useDecisionSelection();

  const competitive = mode !== "saf-puan";

  return (
    <Card title={copy.title} aside={<Badge tone="accent">{copy.shareable}</Badge>}>
      <p className={styles.intro}>{variant === "entry" ? copy.entryIntro : copy.intro}</p>

      <div className={styles.controls}>
        <fieldset className={styles.fieldset}>
          <legend>{copy.horizon}</legend>
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
                <span>{copy.week(window)}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>{copy.mode}</legend>
          <div className={styles.modeOptions}>
            {playModes.map((option) => (
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

        {variant === "default" ? (
          <label className={styles.leagueField}>
            <span>{copy.leagueId}</span>
            <input type="text" inputMode="numeric" placeholder={copy.leaguePlaceholder} disabled />
            <small>{copy.leagueHelp}</small>
          </label>
        ) : null}
      </div>

      {competitive ? (
        <div className={styles.diagnostic} role="note">
          <Badge tone="warn">{copy.diagnostic}</Badge>
          <span>
            <strong>{copy.diagnosticTitle(windowSize)}</strong> {copy.diagnosticBody}
          </span>
        </div>
      ) : null}

      <p className={styles.sourceNote}>
        {copy.sourceBefore}
        <code>mode_price_list</code>
        {copy.sourceAfter(MODE_PRICE_FOLDS)}
      </p>
    </Card>
  );
}
