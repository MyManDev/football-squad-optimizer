/**
 * A browser for the reminder's tests: a service worker whose push manager answers as told, a
 * permission that is granted or refused, and a fetch that records each request and answers
 * the key and the subscription routes.
 */

import { vi } from "vitest";

import type { ReminderBrowser } from "./deadlineReminder";

const KEY =
  "BK7BePS7FVBicBLMvkKWkFAILk4LJNZLLgTcbdG-AjIMqK76zCrXiEmw-9arKEAPnf1UdoigvohfcBRxC9PsJ58";

export function fakeBrowser({
  held = false,
  pushManager = true,
  permission = "default" as NotificationPermission,
  granted = true,
} = {}): ReminderBrowser & { requests: string[] } {
  const subscription = (endpoint: string) =>
    ({
      endpoint,
      getKey: () => new Uint8Array(16).buffer,
      unsubscribe: async () => {
        current = null;
        return true;
      },
    }) as unknown as PushSubscription;
  let current: PushSubscription | null = held
    ? subscription("https://push.example.net/send/x")
    : null;
  const registration = {
    pushManager: {
      getSubscription: async () => current,
      subscribe: async () => {
        current = subscription("https://push.example.net/send/y");
        return current;
      },
    },
  } as unknown as ServiceWorkerRegistration;
  const requests: string[] = [];
  return {
    requests,
    serviceWorker: {
      register: async () => registration,
      getRegistration: async () => registration,
    } as unknown as ReminderBrowser["serviceWorker"],
    pushManager,
    notification: {
      permission,
      requestPermission: async () => (granted ? "granted" : "denied") as NotificationPermission,
    },
    fetch: vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(`${init?.method ?? "GET"} ${String(input)}`);
      return String(input).endsWith("/key")
        ? new Response(JSON.stringify({ contract_version: "push_key_v1", public_key: KEY }))
        : new Response(null, { status: 204 });
    }) as unknown as typeof fetch,
  };
}
