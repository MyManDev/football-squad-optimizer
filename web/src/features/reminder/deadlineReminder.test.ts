/**
 * The reminder's steps against a fake browser: what the control needs to be drawn, the
 * request that turns it on, and the two removals that turn it off.
 */

import { describe, expect, it, vi } from "vitest";

import {
  KEY_PATH,
  SERVICE_WORKER_PATH,
  SUBSCRIPTIONS_PATH,
  disableReminder,
  enableReminder,
  keyBytes,
  reminderSupport,
  subscriptionBody,
  type ReminderBrowser,
} from "./deadlineReminder";

const PUBLIC_KEY =
  "BK7BePS7FVBicBLMvkKWkFAILk4LJNZLLgTcbdG-AjIMqK76zCrXiEmw-9arKEAPnf1UdoigvohfcBRxC9PsJ58";
const TARGET = { leagueId: 352490, entryId: 35249001, language: "tr" as const };

function fakeSubscription(endpoint = "https://push.example.net/send/abc") {
  const keys: Record<string, ArrayBuffer> = {
    p256dh: new Uint8Array(65).fill(4).buffer,
    auth: new Uint8Array(16).fill(7).buffer,
  };
  return {
    endpoint,
    getKey: (name: string) => keys[name] ?? null,
    unsubscribe: vi.fn(async () => true),
  } as unknown as PushSubscription & { unsubscribe: ReturnType<typeof vi.fn> };
}

/** A browser whose service worker and push manager answer as told. */
function browser({
  permission = "default" as NotificationPermission,
  granted = true,
  existing = null as PushSubscription | null,
  registered = true,
  keyStatus = 200,
  keepStatus = 204,
} = {}) {
  const subscription = fakeSubscription();
  const pushManager = {
    getSubscription: vi.fn(async () => existing),
    subscribe: vi.fn(async () => subscription),
  };
  const registration = { pushManager } as unknown as ServiceWorkerRegistration;
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === KEY_PATH) {
      return new Response(
        JSON.stringify({ contract_version: "push_key_v1", public_key: PUBLIC_KEY }),
        {
          status: keyStatus,
        },
      );
    }
    return new Response(null, { status: keepStatus });
  });
  const made: ReminderBrowser = {
    serviceWorker: {
      register: vi.fn(async () => registration),
      getRegistration: vi.fn(async () => (registered ? registration : undefined)),
    } as unknown as ReminderBrowser["serviceWorker"],
    pushManager: true,
    notification: {
      permission,
      requestPermission: vi.fn(
        async () => (granted ? "granted" : "denied") as NotificationPermission,
      ),
    },
    fetch: fetchImpl as unknown as typeof fetch,
  };
  return { made, calls, subscription, pushManager };
}

describe("whether the control is drawn", () => {
  it("needs a service worker, a push manager and a permission not refused", () => {
    expect(reminderSupport(browser().made)).toBe("available");
    expect(reminderSupport({ ...browser().made, serviceWorker: undefined })).toBe("unsupported");
    expect(reminderSupport({ ...browser().made, pushManager: false })).toBe("unsupported");
    expect(reminderSupport({ ...browser().made, notification: undefined })).toBe("unsupported");
    expect(reminderSupport(browser({ permission: "denied" }).made)).toBe("denied");
  });
});

describe("turning the reminder on", () => {
  it("asks permission, registers the worker, subscribes with the Worker's key and sends the subscription", async () => {
    const { made, calls, subscription, pushManager } = browser();
    const kept = await enableReminder(made, TARGET);
    expect(kept).toBe(subscription);
    expect(made.notification!.requestPermission).toHaveBeenCalledTimes(1);
    expect(made.serviceWorker!.register).toHaveBeenCalledWith(SERVICE_WORKER_PATH);
    const [options] = (pushManager.subscribe.mock.calls[0] ?? []) as unknown as [
      PushSubscriptionOptionsInit,
    ];
    expect(options.userVisibleOnly).toBe(true);
    expect(new Uint8Array(options.applicationServerKey as ArrayBuffer)).toEqual(
      keyBytes(PUBLIC_KEY),
    );
    expect(keyBytes(PUBLIC_KEY)).toHaveLength(65);
    expect(calls.map((call) => call.url)).toEqual([KEY_PATH, SUBSCRIPTIONS_PATH]);
    expect(calls[1]!.init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[1]!.init?.body))).toEqual(
      subscriptionBody(subscription, TARGET),
    );
    expect(subscriptionBody(subscription, TARGET)).toMatchObject({
      contract_version: "push_subscription_v1",
      endpoint: subscription.endpoint,
      language: "tr",
      league_id: 352490,
      entry_id: 35249001,
    });
  });

  it("stops at a refused permission, sending nothing", async () => {
    const { made, calls } = browser({ granted: false });
    expect(await enableReminder(made, TARGET)).toBeNull();
    expect(calls).toEqual([]);
    expect(made.serviceWorker!.register).not.toHaveBeenCalled();
  });

  it("reuses a subscription the browser already holds, and asks no permission it already has", async () => {
    const existing = fakeSubscription("https://push.example.net/send/old");
    const { made, calls, pushManager } = browser({ permission: "granted", existing });
    expect(await enableReminder(made, TARGET)).toBe(existing);
    expect(made.notification!.requestPermission).not.toHaveBeenCalled();
    expect(pushManager.subscribe).not.toHaveBeenCalled();
    expect(JSON.parse(String(calls[1]!.init?.body)).endpoint).toBe(existing.endpoint);
  });

  it("drops the browser's subscription again when the Worker refuses to keep it", async () => {
    const { made, subscription } = browser({ keepStatus: 400 });
    await expect(enableReminder(made, TARGET)).rejects.toThrow("subscribe 400");
    expect(subscription.unsubscribe).toHaveBeenCalledTimes(1);
  });
});

describe("turning the reminder off", () => {
  it("asks the Worker to drop the row, then unsubscribes the browser", async () => {
    const existing = fakeSubscription();
    const { made, calls } = browser({ existing });
    await disableReminder(made);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe(SUBSCRIPTIONS_PATH);
    expect(calls[0]!.init?.method).toBe("DELETE");
    expect(JSON.parse(String(calls[0]!.init?.body))).toEqual({ endpoint: existing.endpoint });
    expect(existing.unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("does nothing where no subscription is held", async () => {
    const { made, calls } = browser({ registered: false });
    await disableReminder(made);
    expect(calls).toEqual([]);
  });
});
