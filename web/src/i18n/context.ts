import { createContext, useContext } from "react";

import { MESSAGES, type Language, type Messages } from "./messages";

export interface LanguageContextValue {
  language: Language;
  locale: "tr-TR" | "en-GB";
  messages: Messages;
  setLanguage: (language: Language) => void;
}

export const LanguageContext = createContext<LanguageContextValue>({
  language: "tr",
  locale: "tr-TR",
  messages: MESSAGES.tr,
  setLanguage: () => undefined,
});

export function useLanguage(): LanguageContextValue {
  return useContext(LanguageContext);
}
