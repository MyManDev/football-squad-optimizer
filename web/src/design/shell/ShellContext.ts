import { createContext, useContext } from "react";

/**
 * What the app shell shares with the page inside it.
 *
 * The shell owns the sidebar drawer (phones, and tablets when the rail is expanded) and
 * the overlay a page may put on the phone bar's 'Fikstür' button. It also owns one empty
 * place in the sidebar, the PLAN slot, which a page fills through `ShellPortal`, and the
 * focus of the page: `focusPage` moves it to the page once a step in front of it is done.
 * Nothing here is persisted: the drawer and the sheet are closed on every visit and on
 * every navigation.
 */
export interface ShellContextValue {
  /** The sidebar is open over the page (phone drawer, or the tablet rail expanded). */
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  /** The page's fixture sheet is open (phones only). */
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
  /** A page has registered a fixture sheet, so the phone bar's 'Fikstür' opens it. */
  sheetAvailable: boolean;
  /** Announce a fixture sheet for as long as the page shows one; call the result to withdraw it. */
  registerSheet: () => () => void;
  planSlot: HTMLElement | null;
  /**
   * Focus the page: main at once, then the page's heading once it is drawn, unless the
   * visitor has moved focus elsewhere by then.
   */
  focusPage: () => void;
}

export type ShellSlot = "plan";

/** The id a page gives its fixture sheet, so the phone bar's button can name what it controls. */
export const FIXTURE_SHEET_ID = "fixture-sheet";

export const ShellContext = createContext<ShellContextValue | null>(null);

/** The shell around this page, or null when the page renders on its own (unit tests). */
export function useShell(): ShellContextValue | null {
  return useContext(ShellContext);
}

/** The sidebar element a page may render into, or null without a shell or before it mounts. */
export function useShellSlot(slot: ShellSlot): HTMLElement | null {
  const shell = useContext(ShellContext);
  if (!shell) return null;
  return slot === "plan" ? shell.planSlot : null;
}
