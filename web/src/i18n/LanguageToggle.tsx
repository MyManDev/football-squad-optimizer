import { useLanguage } from "./context";
import styles from "./LanguageToggle.module.css";

/** `vertical` stacks TR over EN, for the sidebar's 72 px icon rail. */
export function LanguageToggle({ vertical = false }: { vertical?: boolean }) {
  const { language, messages, setLanguage } = useLanguage();
  return (
    <div
      className={vertical ? `${styles.toggle} ${styles.vertical}` : styles.toggle}
      role="group"
      aria-label={messages.language.label}
    >
      {(["tr", "en"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={language === value}
          aria-label={`${value.toUpperCase()} · ${messages.language[value]}`}
          onClick={() => setLanguage(value)}
        >
          {value.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
