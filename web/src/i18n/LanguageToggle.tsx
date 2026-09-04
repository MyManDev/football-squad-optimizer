import { useLanguage } from "./context";
import styles from "./LanguageToggle.module.css";

export function LanguageToggle() {
  const { language, messages, setLanguage } = useLanguage();
  return (
    <div className={styles.toggle} role="group" aria-label={messages.language.label}>
      {(["tr", "en"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={language === value}
          aria-label={`${value.toUpperCase()} — ${messages.language[value]}`}
          onClick={() => setLanguage(value)}
        >
          {value.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
