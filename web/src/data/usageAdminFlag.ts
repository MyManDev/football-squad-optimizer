/**
 * Whether this browser belongs to someone who reads the usage record (ADR 0016). The admin
 * page sets it once it has read a report; from then on the browser sends no usage event of
 * either version, so the people reading the record do not move it, and the app shell offers
 * the heatmap mode. Clearing the site's data clears it, and the browser is counted again
 * until the admin page is opened once more.
 *
 * Neither helper throws: a storage that refuses reads as "not an admin" and keeps nothing.
 */
export const USAGE_ADMIN_KEY = "squadopt.admin";

/** True when this browser has opened the admin page successfully. */
export function isUsageAdmin(): boolean {
  try {
    return window.localStorage.getItem(USAGE_ADMIN_KEY) === "1";
  } catch {
    return false;
  }
}

/** Marks this browser as an admin's. */
export function markUsageAdmin(): void {
  try {
    window.localStorage.setItem(USAGE_ADMIN_KEY, "1");
  } catch {
    // A storage that refuses keeps nothing; the browser stays a counted visitor.
  }
}
