/**
 * The deadline reminder on the page (ADR 0013): whether this browser can hold one, and the
 * steps that turn it on and off. Turning it on registers the service worker, asks the
 * browser's permission, subscribes with the Worker's public key and sends the subscription as
 * `push_subscription_v1`; turning it off unsubscribes and asks the Worker to drop the row.
 * Nothing here is React; the hook in useDeadlineReminder.ts drives it.
 */

export const SERVICE_WORKER_PATH = "/sw.js";
export const KEY_PATH = "/api/v1/push/key";
export const SUBSCRIPTIONS_PATH = "/api/v1/push/subscriptions";
export const SUBSCRIPTION_CONTRACT = "push_subscription_v1";

export type ReminderSupport = "unsupported" | "denied" | "available";

export interface ReminderTarget {
  leagueId: number;
  entryId: number;
  language: "tr" | "en";
}

/** What the page needs from the browser; a test hands in its own. */
export interface ReminderBrowser {
  serviceWorker: Pick<ServiceWorkerContainer, "register" | "getRegistration"> | undefined;
  pushManager: boolean;
  notification:
    | { permission: NotificationPermission; requestPermission(): Promise<NotificationPermission> }
    | undefined;
  fetch: typeof fetch;
}

export function pageBrowser(): ReminderBrowser {
  return {
    serviceWorker: typeof navigator === "undefined" ? undefined : navigator.serviceWorker,
    pushManager: typeof window !== "undefined" && "PushManager" in window,
    notification: typeof Notification === "undefined" ? undefined : Notification,
    fetch: (input, init) => fetch(input, init),
  };
}

/** Whether the control is drawn at all: the browser must do push, and must not have refused. */
export function reminderSupport(browser: ReminderBrowser): ReminderSupport {
  if (!browser.serviceWorker || !browser.pushManager || !browser.notification) return "unsupported";
  if (browser.notification.permission === "denied") return "denied";
  return "available";
}

/** The Push API's applicationServerKey from the Worker's base64url public key. */
export function keyBytes(publicKey: string): Uint8Array {
  const padded = publicKey
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(Math.ceil(publicKey.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function toBase64Url(buffer: ArrayBuffer | null): string {
  if (buffer === null) return "";
  let text = "";
  for (const byte of new Uint8Array(buffer)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** The request body the Worker reads, from a subscription and the page it is for. */
export function subscriptionBody(subscription: PushSubscription, target: ReminderTarget) {
  return {
    contract_version: SUBSCRIPTION_CONTRACT,
    endpoint: subscription.endpoint,
    keys: {
      p256dh: toBase64Url(subscription.getKey("p256dh")),
      auth: toBase64Url(subscription.getKey("auth")),
    },
    language: target.language,
    league_id: target.leagueId,
    entry_id: target.entryId,
  };
}

/** The subscription this browser holds for the site, if the service worker is registered. */
export async function currentSubscription(
  browser: ReminderBrowser,
): Promise<PushSubscription | null> {
  const registration = await browser.serviceWorker?.getRegistration(SERVICE_WORKER_PATH);
  if (!registration) return null;
  return registration.pushManager.getSubscription();
}

/**
 * Turns the reminder on. Resolves to the subscription kept, or null when the browser's
 * permission was not given; throws when the Worker or the push service refuses.
 */
export async function enableReminder(
  browser: ReminderBrowser,
  target: ReminderTarget,
): Promise<PushSubscription | null> {
  if (!browser.serviceWorker || !browser.notification) return null;
  const permission =
    browser.notification.permission === "granted"
      ? "granted"
      : await browser.notification.requestPermission();
  if (permission !== "granted") return null;
  const registration = await browser.serviceWorker.register(SERVICE_WORKER_PATH);
  const keyAnswer = await browser.fetch(KEY_PATH, { headers: { accept: "application/json" } });
  if (!keyAnswer.ok) throw new Error(`key ${keyAnswer.status}`);
  const { public_key: publicKey } = (await keyAnswer.json()) as { public_key: string };
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(publicKey) as BufferSource,
    }));
  const kept = await browser.fetch(SUBSCRIPTIONS_PATH, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(subscriptionBody(subscription, target)),
  });
  if (!kept.ok) {
    await subscription.unsubscribe().catch(() => false);
    throw new Error(`subscribe ${kept.status}`);
  }
  return subscription;
}

/** Turns the reminder off: the row at the Worker first, then the browser's subscription. */
export async function disableReminder(browser: ReminderBrowser): Promise<void> {
  const subscription = await currentSubscription(browser);
  if (subscription === null) return;
  await browser
    .fetch(SUBSCRIPTIONS_PATH, {
      method: "DELETE",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    })
    .catch(() => null);
  await subscription.unsubscribe();
}
