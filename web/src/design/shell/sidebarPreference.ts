/**
 * Whether the desktop sidebar was left collapsed to its 72 px rail. This is a layout
 * convenience for the viewer's own browser, not a member choice: it holds no entry, no
 * plan and no language. It opens by default, and an unreadable or unknown value opens it.
 */
export const SIDEBAR_STORAGE_KEY = "squadopt.sidebar";

export function readSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

export function writeSidebarCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "collapsed" : "open");
  } catch {
    /* Storage may be unavailable; the sidebar still follows the click for this visit. */
  }
}
