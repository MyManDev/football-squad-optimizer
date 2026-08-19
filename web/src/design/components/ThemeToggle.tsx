import { useEffect, useState } from "react";

import styles from "./ThemeToggle.module.css";

type Theme = "system" | "light" | "dark";
const KEY = "squadopt.theme";

function readStored(): Theme {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

const LABEL: Record<Theme, string> = { system: "Auto", light: "Light", dark: "Dark" };
const NEXT: Record<Theme, Theme> = { system: "dark", dark: "light", light: "system" };

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readStored);
  useEffect(() => {
    apply(theme);
    try {
      window.localStorage.setItem(KEY, theme);
    } catch {
      /* storage may be unavailable; the choice still applies for this view */
    }
  }, [theme]);
  return (
    <button
      type="button"
      className={styles.button}
      onClick={() => setTheme(NEXT[theme])}
      aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[NEXT[theme]]}.`}
      title={`Theme: ${LABEL[theme]}`}
    >
      {LABEL[theme]}
    </button>
  );
}
