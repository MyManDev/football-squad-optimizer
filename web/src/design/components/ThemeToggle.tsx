import { useEffect, useState } from "react";

import { useLanguage } from "../../i18n/context";
import styles from "./ThemeToggle.module.css";

type Theme = "light" | "dark";
const KEY = "squadopt.theme";

/**
 * Two states, deliberately: light and dark. A viewer who has never chosen starts from
 * their OS preference, read once — from then on the choice is explicit and stored, and
 * the page never silently follows the OS again. (An earlier third "auto" state was
 * removed: three-way cycling made the button's next stop unpredictable.)
 */
function readStored(): Theme {
  try {
    const value = window.localStorage.getItem(KEY);
    if (value === "light" || value === "dark") return value;
  } catch {
    /* storage may be unavailable; fall through to the OS preference */
  }
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

function apply(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

export function ThemeToggle() {
  const { messages } = useLanguage();
  const [theme, setTheme] = useState<Theme>(readStored);
  useEffect(() => {
    apply(theme);
    try {
      window.localStorage.setItem(KEY, theme);
    } catch {
      /* storage may be unavailable; the choice still applies for this view */
    }
  }, [theme]);
  const next: Theme = theme === "light" ? "dark" : "light";
  const labels: Record<Theme, string> = {
    light: messages.theme.light,
    dark: messages.theme.dark,
  };
  return (
    <button
      type="button"
      className={styles.button}
      onClick={() => setTheme(next)}
      aria-label={messages.theme.switchTo(labels[theme], labels[next])}
      title={`${messages.theme.label}: ${labels[theme]}`}
    >
      {labels[theme]}
    </button>
  );
}
