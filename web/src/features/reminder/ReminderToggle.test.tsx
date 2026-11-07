/**
 * The reminder's control: hidden where the browser cannot hold a reminder, "Hatırlat" when
 * off, "Hatırlatma açık" and pressed when on, and one click each way.
 */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES } from "../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../testSupport/honesty";
import type { ReminderBrowser } from "./deadlineReminder";
import { ReminderToggle } from "./ReminderToggle";

afterEach(cleanup);

const TARGET = { leagueId: 352490, entryId: 35249001, language: "tr" as const };

function browser(held: boolean) {
  let subscription: PushSubscription | null = held
    ? ({
        endpoint: "https://push.example.net/send/x",
        getKey: () => new Uint8Array(16).buffer,
        unsubscribe: async () => {
          subscription = null;
          return true;
        },
      } as unknown as PushSubscription)
    : null;
  const registration = {
    pushManager: {
      getSubscription: async () => subscription,
      subscribe: async () => {
        subscription = {
          endpoint: "https://push.example.net/send/y",
          getKey: () => new Uint8Array(16).buffer,
          unsubscribe: async () => {
            subscription = null;
            return true;
          },
        } as unknown as PushSubscription;
        return subscription;
      },
    },
  } as unknown as ServiceWorkerRegistration;
  const made: ReminderBrowser = {
    serviceWorker: {
      register: async () => registration,
      getRegistration: async () => registration,
    } as unknown as ReminderBrowser["serviceWorker"],
    pushManager: true,
    notification: { permission: "default", requestPermission: async () => "granted" },
    fetch: vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/key")
        ? new Response(
            JSON.stringify({
              contract_version: "push_key_v1",
              public_key:
                "BK7BePS7FVBicBLMvkKWkFAILk4LJNZLLgTcbdG-AjIMqK76zCrXiEmw-9arKEAPnf1UdoigvohfcBRxC9PsJ58",
            }),
          )
        : new Response(null, { status: 204 }),
    ) as unknown as typeof fetch,
  };
  return made;
}

const open = (made: ReminderBrowser, language: "tr" | "en" = "tr", target = TARGET) =>
  render(
    <LanguageProvider initialLanguage={language}>
      <ReminderToggle target={target} browser={made} />
    </LanguageProvider>,
  );

describe.each(["tr", "en"] as const)("the reminder control in %s", (language) => {
  const copy = MESSAGES[language].reminder;

  it("reads off, then on and pressed after a click, with no sentence about it", async () => {
    const { container } = open(browser(false), language);
    const button = await screen.findByRole("button", { name: copy.off });
    expect(button).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(button);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: copy.on })).toHaveAttribute("aria-pressed", "true"),
    );
    expect(container.textContent).toBe(copy.on);
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(container.textContent).not.toMatch(AS_A_CAVEAT);
  });

  it("reads on where the browser already holds a subscription, and off after a click", async () => {
    open(browser(true), language);
    const button = await screen.findByRole("button", { name: copy.on });
    await userEvent.click(button);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: copy.off })).toHaveAttribute(
        "aria-pressed",
        "false",
      ),
    );
  });
});

describe("where the browser cannot hold a reminder", () => {
  it("draws nothing", async () => {
    const made = { ...browser(false), pushManager: false };
    const { container } = open(made);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing without a member to remind", async () => {
    const { container } = open(browser(false), "tr", null as unknown as typeof TARGET);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
