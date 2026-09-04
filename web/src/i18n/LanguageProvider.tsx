import { useEffect, useMemo, useState, type ReactNode } from "react";

import { LanguageContext, type LanguageContextValue } from "./context";
import { MESSAGES, type Language } from "./messages";

export const LANGUAGE_STORAGE_KEY = "squadopt.language";

function readStoredLanguage(): Language {
  try {
    const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return value === "en" || value === "tr" ? value : "tr";
  } catch {
    return "tr";
  }
}

export function LanguageProvider({
  children,
  initialLanguage,
}: {
  children: ReactNode;
  initialLanguage?: Language;
}) {
  const [language, setLanguage] = useState<Language>(initialLanguage ?? readStoredLanguage);

  useEffect(() => {
    document.documentElement.lang = language;
    document
      .querySelector('meta[name="description"]')
      ?.setAttribute("content", MESSAGES[language].shell.metaDescription);
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    } catch {
      /* The view still changes when storage is unavailable. */
    }
  }, [language]);

  const value = useMemo<LanguageContextValue>(
    () => ({
      language,
      locale: language === "tr" ? "tr-TR" : "en-GB",
      messages: MESSAGES[language],
      setLanguage,
    }),
    [language],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}
