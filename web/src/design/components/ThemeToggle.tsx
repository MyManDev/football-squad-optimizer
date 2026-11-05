import { useLanguage } from "../../i18n/context";
import { chooseColourScheme, useColourScheme } from "../colourScheme";
import { MoonIcon, SunIcon } from "../shell/icons";
import styles from "./SegmentedToggle.module.css";

const ICON = { light: SunIcon, dark: MoonIcon } as const;

/** Day | Night beside the language switch; `vertical` stacks them for the 72 px icon rail. */
export function ThemeToggle({ vertical = false }: { vertical?: boolean }) {
  const { messages } = useLanguage();
  const scheme = useColourScheme();
  return (
    <div
      className={vertical ? `${styles.toggle} ${styles.vertical}` : styles.toggle}
      role="group"
      aria-label={messages.colourScheme.label}
    >
      {(["light", "dark"] as const).map((value) => {
        const Icon = ICON[value];
        return (
          <button
            key={value}
            type="button"
            aria-pressed={scheme === value}
            aria-label={messages.colourScheme[value]}
            title={messages.colourScheme[value]}
            onClick={() => chooseColourScheme(value)}
          >
            <Icon />
          </button>
        );
      })}
    </div>
  );
}
