import { createContext, useContext } from "react";

/**
 * What the app shell shares with the page inside it.
 *
 * The shell owns the overlay a page may put on the phone bar's 'Fikstür' button, and the
 * focus of the page: `focusPage` moves it to the page once a step in front of it is done.
 * Nothing here is persisted: the sheet is closed on every visit and on every navigation.
 */
export interface ShellContextValue {
  /** The page's fixture sheet is open (phones only). */
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
  /** Announce a fixture sheet for as long as the page shows one; call the result to withdraw it. */
  registerSheet: () => () => void;
  /**
   * Focus the page: main at once, then the page's heading once it is drawn, unless the
   * visitor has moved focus elsewhere by then.
   */
  focusPage: () => void;
}

/** The id a page gives its fixture sheet, so the phone bar's button can name what it controls. */
export const FIXTURE_SHEET_ID = "fixture-sheet";

export const ShellContext = createContext<ShellContextValue | null>(null);

/** The shell around this page, or null when the page renders on its own (unit tests). */
export function useShell(): ShellContextValue | null {
  return useContext(ShellContext);
}
