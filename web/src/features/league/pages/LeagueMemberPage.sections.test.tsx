/**
 * The phone's section strip: 'Hamle · Kadro' under the phone bar, two in-page links (not
 * tabs: the page is one document) that land on the decision's heading and the squad; the
 * tools are pages of their own in the sidebar. Only a phone draws it. A link whose section
 * is not in the page is left out, and a closed week, which drops the plan settings, keeps
 * both. The section
 * being read is the current location, as the page's IntersectionObservers report it; the
 * strip is drawn once the decision's heading has gone up behind the phone bar.
 */
import { act, cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PHONE_QUERY } from "../../../design/shell/layout";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { withLeague } from "../../../testSupport/league";
import { LeagueMemberView } from "./LeagueMemberPage";
import { MemberSections } from "./MemberSections";
import type { LeagueMemberViewProps } from "./memberPageTypes";

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!;
const MEMBERS = mockLeagueMembersEnvelope.payload.members;

/**
 * jsdom has no IntersectionObserver; this one keeps what it observes and reports the
 * crossings a test makes, with the band's top edge read from its own root margin. Like a
 * browser's, it first reports each target once as it stands: here, the page at its top.
 */
class FakeObserver {
  static made: FakeObserver[] = [];
  readonly targets: Element[] = [];
  readonly callback: IntersectionObserverCallback;
  readonly options: IntersectionObserverInit;
  disconnected = false;

  constructor(callback: IntersectionObserverCallback, options: IntersectionObserverInit = {}) {
    this.callback = callback;
    this.options = options;
    FakeObserver.made.push(this);
  }

  observe(target: Element) {
    this.targets.push(target);
  }

  unobserve() {}

  disconnect() {
    this.disconnected = true;
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  /** The band's top edge in px, from a root margin such as '-56px 0px 100000px 0px'. */
  get edge(): number {
    return Number(/^-(\d+)px/.exec(this.options.rootMargin ?? "")?.[1] ?? 0);
  }

  /** The first report, the page at its top: every section below every line. */
  arrive() {
    // A band with no lower end holds a section below its line whole; the band of the
    // screen alone (the tools' end) holds none of the tools there.
    const endless = /\s[1-9]\d{4,}px/.test(this.options.rootMargin ?? "");
    for (const target of this.targets)
      this.report(target, 1000, { intersecting: endless, ratio: endless ? 1 : 0 });
  }

  report(target: Element, top: number, { intersecting = false, ratio = 0 } = {}) {
    const entry = {
      target,
      isIntersecting: intersecting,
      intersectionRatio: ratio,
      boundingClientRect: { top } as DOMRectReadOnly,
      rootBounds: { top: this.edge } as DOMRectReadOnly,
    } as IntersectionObserverEntry;
    act(() => this.callback([entry], this as unknown as IntersectionObserver));
  }
}

/** The live observer watching `target`; with `threshold`, the one asking for that alone. */
function observerOf(target: Element, threshold?: number): FakeObserver {
  const found = FakeObserver.made.find(
    (observer) =>
      !observer.disconnected &&
      observer.targets.includes(target) &&
      (threshold === undefined || observer.options.threshold === threshold),
  );
  if (!found) throw new Error("nothing observes that element");
  return found;
}

/** What a browser's observers report once the page is in the document. */
function arrive() {
  for (const observer of FakeObserver.made.filter((made) => !made.disconnected)) observer.arrive();
}

/** The shell's phone layout, under 600 px. */
function phone() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      media: query,
      matches: query === PHONE_QUERY,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
}

beforeEach(() => {
  FakeObserver.made = [];
  vi.stubGlobal("IntersectionObserver", FakeObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (window as { matchMedia?: unknown }).matchMedia;
});

function show(language: Language, props: Partial<LeagueMemberViewProps> = {}) {
  const view = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
        {withLeague(
          <LeagueMemberView
            squad={SQUAD}
            advice={mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)}
            members={MEMBERS}
            index={mockEntryAdviceIndex(ENTRY).payload}
            {...props}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
  arrive();
  return view;
}

const strip = (language: Language) =>
  screen.getByRole("navigation", { name: MESSAGES[language].leagueMembers.sectionsLabel });
const names = (language: Language) => {
  const copy = MESSAGES[language].leagueMembers;
  return [copy.sectionMove, copy.sectionSquad];
};
const link = (language: Language, name: string) =>
  within(strip(language)).getByRole("link", { name });
/** The element an in-page link lands on. */
const target = (anchor: HTMLElement) =>
  document.getElementById(anchor.getAttribute("href")!.slice(1));

describe.each(["tr", "en"] as const)("the phone's section strip (%s)", (language) => {
  const copy = MESSAGES[language].leagueMembers;

  it("links the decision and the squad, in the page's order", () => {
    phone();
    show(language);
    const links = within(strip(language)).getAllByRole("link");
    expect(links.map((anchor) => anchor.textContent)).toEqual(names(language));
    expect(links.map((anchor) => anchor.getAttribute("href"))).toEqual([
      "#entry-advice-title",
      "#kadro",
    ]);
    // One page, not tab panels: plain links, with no tab roles anywhere in the strip.
    expect(within(strip(language)).queryByRole("tablist")).toBeNull();
    expect(within(strip(language)).queryByRole("tab")).toBeNull();
    const [move, squad] = links.map((anchor) => target(anchor)!);
    expect(move).toBe(screen.getByRole("heading", { name: copy.decisionTitle, level: 2 }));
    expect(squad).toBe(screen.getByRole("region", { name: copy.squadAfterTitle }));
    // The tools are no longer at the foot of the page.
    expect(screen.queryByText(copy.chipsAndTransfers)).toBeNull();
    // In the order the page reads: the strip, the decision, the squad.
    const order = [strip(language), move, squad];
    for (let index = 1; index < order.length; index += 1)
      expect(
        order[index - 1]!.compareDocumentPosition(order[index]!) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    // At the top of the page the decision is the current section.
    expect(link(language, copy.sectionMove)).toHaveAttribute("aria-current", "location");
    expect(link(language, copy.sectionSquad)).not.toHaveAttribute("aria-current");
  });

  it("is drawn on a phone only", () => {
    show(language);
    expect(screen.queryByRole("navigation", { name: copy.sectionsLabel, hidden: true })).toBeNull();
    expect(document.getElementById("kadro")).not.toBeNull();
  });

  it("keeps both on a closed week", () => {
    phone();
    show(language, { deadlinePassed: "2026-09-18T17:30:00Z" });
    expect(document.getElementById("plan-settings")).toBeNull();
    const links = within(strip(language)).getAllByRole("link");
    expect(links.map((anchor) => anchor.textContent)).toEqual(names(language));
  });

  it("marks the section being read as the current location as the page scrolls", () => {
    phone();
    const { unmount } = show(language);
    const heading = screen.getByRole("heading", { name: copy.decisionTitle, level: 2 });
    const squad = document.getElementById("kadro")!;
    const holder = strip(language).parentElement!;
    const current = () =>
      within(strip(language))
        .getAllByRole("link")
        .filter((anchor) => anchor.getAttribute("aria-current") === "location")
        .map((anchor) => anchor.textContent);

    // Away while the decision's heading is in view; drawn once it has gone up behind the
    // phone bar, and away again when it comes back.
    expect(holder).not.toHaveAttribute("data-shown");
    observerOf(heading).report(heading, -30);
    expect(holder).toHaveAttribute("data-shown");

    // The squad's top goes up past the reading line under the strip: 'Kadro' is current.
    const line = observerOf(squad);
    line.report(squad, line.edge - 8, { intersecting: true, ratio: 0.9 });
    expect(current()).toEqual([copy.sectionSquad]);
    // Back at the top of the page, the decision.
    line.report(squad, line.edge + 400, { intersecting: true, ratio: 1 });
    expect(current()).toEqual([copy.sectionMove]);

    observerOf(heading).report(heading, 64, { intersecting: true, ratio: 1 });
    expect(holder).not.toHaveAttribute("data-shown");

    const made = [...FakeObserver.made];
    unmount();
    expect(made.every((observer) => observer.disconnected)).toBe(true);
  });
});

describe("the strip on its own", () => {
  const copy = MESSAGES.tr.leagueMembers;
  const alone = (page: ReactNode) => {
    const view = render(
      <LanguageProvider initialLanguage="tr">
        {page}
        <MemberSections />
      </LanguageProvider>,
    );
    arrive();
    return view;
  };

  it("leaves out a link whose section is not in the page", () => {
    alone(<h2 id="entry-advice-title">{copy.decisionTitle}</h2>);
    const links = within(screen.getByRole("navigation", { name: copy.sectionsLabel })).getAllByRole(
      "link",
    );
    expect(links.map((anchor) => anchor.textContent)).toEqual([copy.sectionMove]);
  });

  it("reads where the sections are from its observers, never from a scroll listener", () => {
    const listen = vi.spyOn(window, "addEventListener");
    const listenDocument = vi.spyOn(document, "addEventListener");
    alone(
      <>
        <h2 id="entry-advice-title">{copy.decisionTitle}</h2>
        <section id="kadro" aria-label={copy.memberSquad} />
      </>,
    );
    const events = [...listen.mock.calls, ...listenDocument.mock.calls].map(([type]) => type);
    expect(events).not.toContain("scroll");
    expect(FakeObserver.made.length).toBeGreaterThan(0);
  });

  it("links nothing and stays away where the browser has no IntersectionObserver", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    const { container } = alone(<h2 id="entry-advice-title">{copy.decisionTitle}</h2>);
    expect(screen.queryByRole("navigation", { hidden: true })).toBeNull();
    expect(screen.queryByRole("link", { hidden: true })).toBeNull();
    // The holder stays, so the page's scroll padding still counts the strip.
    expect(container.querySelector("h2 + div")).not.toHaveAttribute("data-shown");
  });
});
