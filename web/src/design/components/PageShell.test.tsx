import userEvent from "@testing-library/user-event";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../i18n/messages";
import { MOTION_MS, REDUCED_MOTION_QUERY } from "../motion";
import { DESKTOP_QUERY, PHONE_QUERY, type ShellLayout } from "../shell/layout";
import { NO_IDENTITY, type ShellIdentity } from "../shell/nav";
import { FIXTURE_SHEET_ID, useShell, useShellSlot } from "../shell/ShellContext";
import { ShellPortal } from "../shell/ShellPortal";
import { SIDEBAR_STORAGE_KEY } from "../shell/sidebarPreference";
import { PageShell } from "./PageShell";

const TR = MESSAGES.tr.shell;
const LEAGUE = 352490;
const MEMBERS = `/league/${LEAGUE}/members`;
const OWN = `${MEMBERS}/35249001`;

/** A league entered and nobody claimed in it. */
const CHOSEN: ShellIdentity = { leagueId: LEAGUE, member: null };
/** The visitor entered the league and said they are Deniz Aral. */
const CLAIMED: ShellIdentity = {
  leagueId: LEAGUE,
  member: {
    entryId: 35249001,
    league: "SquadOpt Classic League",
    name: "Deniz Aral",
    team: "North Stand Notes",
  },
};

beforeEach(() => vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://squadopt-api.example"));
afterEach(() => vi.unstubAllEnvs());

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>
  );
}

function renderShell({
  path = "/",
  language = "tr",
  identity = NO_IDENTITY,
  onChangeMember,
  page = <p>page</p>,
}: {
  path?: string;
  language?: Language;
  identity?: ShellIdentity;
  onChangeMember?: () => void;
  page?: ReactNode;
} = {}) {
  const user = userEvent.setup();
  const view = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[path]}>
        <PageShell identity={identity} onChangeMember={onChangeMember}>
          {page}
        </PageShell>
        <LocationProbe />
      </MemoryRouter>
    </LanguageProvider>,
  );
  return { user, ...view };
}

/** A viewport whose layout the test decides; jsdom has no media queries of its own. */
function stubLayout(initial: ShellLayout) {
  let layout = initial;
  const listeners = new Set<() => void>();
  const matchMedia = (query: string) => ({
    media: query,
    get matches() {
      if (query === PHONE_QUERY) return layout === "phone";
      if (query === DESKTOP_QUERY) return layout === "desktop";
      return false;
    },
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  });
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: matchMedia,
  });
  return {
    resize(next: ShellLayout) {
      layout = next;
      act(() => {
        for (const listener of listeners) listener();
      });
    },
  };
}

const sidebar = () => screen.getByRole("complementary", { name: TR.sidebar });
const navLinks = () => within(screen.getByRole("navigation")).getAllByRole("link");
const location = () => screen.getByTestId("location").textContent;

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  delete (window as { matchMedia?: unknown }).matchMedia;
  document.documentElement.style.overflow = "";
  delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  window.localStorage.clear();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the app shell on a desktop", () => {
  it("has a skip link first, one main, one navigation and the sidebar landmark", () => {
    const { container } = renderShell();

    const skip = container.querySelector("a")!;
    expect(skip).toHaveTextContent(TR.skip);
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    // Main can take focus from the page's steps, but is never a stop for Tab.
    expect(screen.getByRole("main")).toHaveAttribute("tabindex", "-1");
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
    expect(sidebar()).toHaveAttribute("id", "sidebar");
    expect(within(sidebar()).getByRole("navigation")).toBeInTheDocument();
    // The phone bar belongs to the phone layout only, and nothing is a dialog.
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each(["tr", "en"] as const)(
    "offers only 'Ligini bul', the fixtures and Contribute before a league in %s",
    (language) => {
      const copy = MESSAGES[language].shell;
      renderShell({ language });

      expect(screen.getByRole("navigation", { name: copy.primary })).toBeInTheDocument();
      expect(screen.getByRole("complementary", { name: copy.sidebar })).toBeInTheDocument();

      expect(navLinks().map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
        [copy.findLeague, "/"],
        [copy.fixtures, "/fixtures"],
        [copy.contribute, "/contribute"],
      ]);
      expect(screen.getByRole("link", { name: copy.findLeague })).toHaveAttribute(
        "aria-current",
        "page",
      );
      for (const name of [copy.league, copy.squad, copy.thisWeek]) {
        expect(screen.queryByRole("link", { name })).toBeNull();
      }
      expect(screen.queryByRole("button", { name: copy.changeMember })).toBeNull();
      // The operations, analysis and admin surfaces are reachable by address only.
      expect(
        document.querySelector(
          'a[href="/status"], a[href="/league"], a[href="/admin"], a[href^="/gw/"]',
        ),
      ).toBeNull();
    },
  );

  it("sends 'Ligini bul' to the league's step with a league and nobody claimed, and nothing more", async () => {
    const { user } = renderShell({ identity: CHOSEN });
    const find = screen.getByRole("link", { name: TR.findLeague });
    expect(find).toHaveAttribute("href", MEMBERS);
    expect(find).not.toHaveAttribute("aria-current");
    for (const name of [TR.league, TR.squad, TR.thisWeek]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    expect(screen.queryByRole("button", { name: TR.changeMember })).toBeNull();
    await user.click(find);
    expect(location()).toBe(MEMBERS);
  });

  it("opens the claimed member as 'Bu hafta' and 'Kadro', and the league as 'Lig'", async () => {
    const path = `${OWN}?mode=fark-yarat&window=3`;
    const { user } = renderShell({ path, identity: CLAIMED });

    const thisWeek = screen.getByRole("link", { name: TR.thisWeek });
    const squad = screen.getByRole("link", { name: TR.squad });
    expect(thisWeek).toHaveAttribute("href", path);
    expect(thisWeek).toHaveAttribute("aria-current", "page");
    expect(squad).toHaveAttribute("href", `${path}#kadro`);
    expect(squad).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: TR.league })).toHaveAttribute("href", MEMBERS);
    expect(screen.queryByRole("link", { name: TR.findLeague })).toBeNull();

    await user.click(squad);
    expect(location()).toBe(`${path}#kadro`);
    expect(screen.getByRole("link", { name: TR.squad })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: TR.thisWeek })).not.toHaveAttribute("aria-current");
  });

  it("keeps the plan of the own page in reach for the rest of the visit, in memory only", async () => {
    const path = `${OWN}?mode=ortak-koru`;
    const { user } = renderShell({ path, identity: CLAIMED });

    await user.click(screen.getByRole("link", { name: TR.fixtures }));
    expect(location()).toBe("/fixtures");
    expect(screen.getByRole("link", { name: TR.fixtures })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: TR.thisWeek })).toHaveAttribute("href", path);
    expect(screen.getByRole("link", { name: TR.squad })).toHaveAttribute("href", `${path}#kadro`);
    expect(window.localStorage.getItem("squadopt.viewer")).toBeNull();
    expect(Object.keys(window.localStorage)).not.toContain("squadopt.member");
  });

  it("points 'Bu hafta' at the visitor's own page, not current, on a rival's page", () => {
    renderShell({ path: `${MEMBERS}/35249002?mode=agresif`, identity: CLAIMED });
    const thisWeek = screen.getByRole("link", { name: TR.thisWeek });
    expect(thisWeek).toHaveAttribute("href", OWN);
    expect(thisWeek).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: TR.squad })).toHaveAttribute("href", `${OWN}#kadro`);
  });

  it("collapses to the icon rail and remembers that in this browser", async () => {
    const first = renderShell();
    const collapse = screen.getByRole("button", { name: TR.collapseSidebar });
    expect(collapse).toHaveAttribute("aria-controls", "sidebar");
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    // On a desktop the sidebar folds in place; it is not a dialog.
    expect(collapse).not.toHaveAttribute("aria-haspopup");
    expect(sidebar()).toHaveAttribute("data-mode", "open");

    await first.user.click(collapse);
    const expand = screen.getByRole("button", { name: TR.expandSidebar });
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(expand).toHaveFocus();
    expect(sidebar()).toHaveAttribute("data-mode", "rail");
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("collapsed");
    // The rail shows icons; each link keeps its words as its name.
    for (const link of navLinks()) expect(link.querySelector(".visually-hidden")).not.toBeNull();
    expect(navLinks().map((link) => link.textContent)).toEqual([
      TR.findLeague,
      TR.fixtures,
      TR.contribute,
    ]);
    expect(screen.getByRole("group", { name: "Dil" })).toHaveClass("vertical");
    first.unmount();

    const second = renderShell({ identity: CLAIMED });
    expect(navLinks().map((link) => link.textContent)).toEqual([
      TR.thisWeek,
      TR.squad,
      TR.league,
      TR.currentSquad,
      TR.decisionTools,
      TR.whatIf,
      TR.duel,
      TR.chips,
      TR.squadCard,
      TR.fixtures,
      TR.contribute,
    ]);
    await second.user.click(screen.getByRole("button", { name: TR.expandSidebar }));
    expect(sidebar()).toHaveAttribute("data-mode", "open");
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("open");
  });

  it("opens with the sidebar when the stored value is unreadable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderShell();
    expect(sidebar()).toHaveAttribute("data-mode", "open");
  });

  it("orders the keyboard: skip link, then the sidebar's controls as they stand", async () => {
    const { user } = renderShell({ page: <button type="button">page action</button> });
    const expected = [
      screen.getByRole("link", { name: TR.skip }),
      screen.getByRole("button", { name: TR.collapseSidebar }),
      ...navLinks(),
      screen.getByRole("button", { name: /^TR/ }),
      screen.getByRole("button", { name: /^EN/ }),
      screen.getByRole("button", { name: "page action" }),
    ];
    for (const element of expected) {
      await user.tab();
      expect(element).toHaveFocus();
    }
  });

  it("puts Değiştir before the navigation in the keyboard order once the member is claimed", async () => {
    const { user } = renderShell({ identity: CLAIMED });
    const expected = [
      screen.getByRole("link", { name: TR.skip }),
      screen.getByRole("button", { name: TR.collapseSidebar }),
      screen.getByRole("button", { name: TR.changeMember }),
      ...navLinks(),
    ];
    for (const element of expected) {
      await user.tab();
      expect(element).toHaveFocus();
    }
  });

  it("scrolls to the squad once the page has drawn it", async () => {
    const scrolled: string[] = [];
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value(this: HTMLElement) {
        scrolled.push(this.id);
      },
    });
    function Late() {
      const { hash } = useLocation();
      return hash ? <section id="kadro">squad</section> : null;
    }
    const { user } = renderShell({ path: OWN, identity: CLAIMED, page: <Late /> });
    await user.click(screen.getByRole("link", { name: TR.squad }));
    expect(scrolled).toContain("kadro");
  });
});

// A move between pages from the navigation is one crossfade (#1131); jsdom has no View
// Transitions, so a browser that has them is stood in for, keeping each update it runs.
describe("moving between pages from the navigation", () => {
  let started: Array<Promise<void> | void> = [];
  let startedAt = 0;
  beforeEach(() => {
    started = [];
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      writable: true,
      value: vi.fn((update: () => Promise<void> | void) => {
        startedAt = performance.now();
        started.push(update());
        return {};
      }),
    });
  });
  afterEach(() => {
    delete (document as { startViewTransition?: unknown }).startViewTransition;
  });

  it("crossfades into the page a link names once its address has landed", async () => {
    const { user } = renderShell({ path: OWN, identity: CLAIMED });
    await user.click(screen.getByRole("link", { name: TR.league }));
    expect(document.startViewTransition).toHaveBeenCalledOnce();
    let settledAt = Number.POSITIVE_INFINITY;
    await act(async () => {
      await started[0];
      settledAt = performance.now();
    });
    expect(location()).toBe(MEMBERS);
    expect(screen.getByRole("link", { name: TR.league })).toHaveAttribute("aria-current", "page");
    // The address landing ends the wait, not the data time that caps it.
    expect(settledAt - startedAt).toBeLessThan(MOTION_MS.data);

    // The page already open changes nothing, so its link starts no transition.
    await user.click(screen.getByRole("link", { name: TR.league }));
    expect(document.startViewTransition).toHaveBeenCalledOnce();
  });

  it("moves at once under reduced motion", async () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: query === REDUCED_MOTION_QUERY,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }),
    });
    const { user } = renderShell({ path: OWN, identity: CLAIMED });
    await user.click(screen.getByRole("link", { name: TR.fixtures }));
    expect(document.startViewTransition).not.toHaveBeenCalled();
    expect(location()).toBe("/fixtures");
  });
});

describe("the identity block", () => {
  it.each(["tr", "en"] as const)(
    "shows the league, the member and their team over Değiştir in %s",
    async (language) => {
      const copy = MESSAGES[language].shell;
      const onChangeMember = vi.fn();
      const { user } = renderShell({ language, identity: CLAIMED, onChangeMember });
      const aside = screen.getByRole("complementary", { name: copy.sidebar });
      const block = within(aside);
      expect(block.getByText("SquadOpt Classic League")).toBeInTheDocument();
      expect(block.getByText("Deniz Aral")).toBeInTheDocument();
      expect(block.getByText("North Stand Notes")).toBeInTheDocument();
      const change = block.getByRole("button", { name: copy.changeMember });
      expect(change).toHaveAccessibleDescription(
        "SquadOpt Classic League: Deniz Aral, North Stand Notes",
      );
      // The block stands between the brand and the navigation.
      const order = [...aside.querySelectorAll("p, nav")].map((node) => node.tagName);
      expect(order).toEqual(["P", "NAV"]);
      await user.click(change);
      expect(onChangeMember).toHaveBeenCalledTimes(1);
    },
  );

  it("names a member with no team on one line", () => {
    renderShell({
      identity: { leagueId: LEAGUE, member: { ...CLAIMED.member!, team: null } },
    });
    expect(screen.getByRole("button", { name: TR.changeMember })).toHaveAccessibleDescription(
      "SquadOpt Classic League: Deniz Aral",
    );
  });

  it("is not there without a member", () => {
    for (const identity of [NO_IDENTITY, CHOSEN]) {
      const view = renderShell({ identity });
      expect(screen.queryByRole("button", { name: TR.changeMember })).toBeNull();
      expect(document.getElementById("sidebar-member")).toBeNull();
      view.unmount();
    }
  });

  it("keeps no empty WHO place for a page to fill", () => {
    renderShell();
    expect(sidebar().querySelector(".who")).toBeNull();
  });
});

describe("focusing the page after a step in front of it", () => {
  function Step({ heading }: { heading: boolean }) {
    const shell = useShell();
    return (
      <>
        <button type="button" onClick={() => shell?.focusPage()}>
          step done
        </button>
        {heading ? <h1>Page heading</h1> : null}
      </>
    );
  }

  function tree(heading: boolean) {
    return (
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={["/"]}>
          <PageShell>
            <Step heading={heading} />
          </PageShell>
        </MemoryRouter>
      </LanguageProvider>
    );
  }

  async function settle() {
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("focuses main at once, then the heading as soon as it is drawn", async () => {
    const { rerender } = render(tree(false));
    fireEvent.click(screen.getByRole("button", { name: "step done" }));
    expect(screen.getByRole("main")).toHaveFocus();
    rerender(tree(true));
    await settle();
    const heading = screen.getByRole("heading", { level: 1, name: "Page heading" });
    expect(heading).toHaveFocus();
    expect(heading).toHaveAttribute("tabindex", "-1");
  });

  it("focuses a heading that is already drawn at once", () => {
    render(tree(true));
    fireEvent.click(screen.getByRole("button", { name: "step done" }));
    expect(screen.getByRole("heading", { level: 1, name: "Page heading" })).toHaveFocus();
  });

  it("leaves focus where the visitor moved it before the heading came", async () => {
    const { rerender } = render(tree(false));
    fireEvent.click(screen.getByRole("button", { name: "step done" }));
    expect(screen.getByRole("main")).toHaveFocus();
    screen.getByRole("link", { name: TR.fixtures }).focus();
    rerender(tree(true));
    await settle();
    expect(screen.getByRole("link", { name: TR.fixtures })).toHaveFocus();
  });

  it("stops waiting for a heading after five seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { rerender } = render(tree(false));
    fireEvent.click(screen.getByRole("button", { name: "step done" }));
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    rerender(tree(true));
    await settle();
    expect(screen.getByRole("main")).toHaveFocus();
  });
});

function Slots({ planFirst = true }: { planFirst?: boolean }) {
  const plan = useShellSlot("plan");
  return (
    <>
      <ShellPortal slot="plan">
        <fieldset>
          <legend>Strateji</legend>
          <label>
            <input type="radio" name="strategy" value="a" defaultChecked={!planFirst} />A
          </label>
          <label>
            <input type="radio" name="strategy" value="b" defaultChecked={planFirst} />B
          </label>
        </fieldset>
      </ShellPortal>
      <p>main content</p>
      <output data-testid="plan-slot">{plan ? plan.tagName : "none"}</output>
    </>
  );
}

describe("the shell's plan slot", () => {
  it("renders a page's PLAN part once, inside the sidebar after the navigation", () => {
    const { container } = renderShell({ path: OWN, identity: CLAIMED, page: <Slots /> });

    expect(within(sidebar()).getByRole("group", { name: "Strateji" })).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByText("main content")).toBeInTheDocument();
    expect(container.querySelectorAll('input[name="strategy"]')).toHaveLength(2);
    expect(screen.getByTestId("plan-slot")).toHaveTextContent("DIV");
    const order = [...sidebar().querySelectorAll("nav, fieldset")].map((node) => node.tagName);
    expect(order).toEqual(["NAV", "FIELDSET"]);
  });

  it("renders it inline where the page stands when there is no shell", () => {
    const { container } = render(
      <MemoryRouter>
        <Slots />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll('input[name="strategy"]')).toHaveLength(2);
    expect(screen.getByTestId("plan-slot")).toHaveTextContent("none");
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("offers the rail's plan button only while a page fills the plan, and opens the plan", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    const empty = renderShell();
    expect(screen.queryByRole("button", { name: TR.changePlan })).toBeNull();
    empty.unmount();

    const { user } = renderShell({ path: OWN, identity: CLAIMED, page: <Slots /> });
    const plan = await screen.findByRole("button", { name: TR.changePlan });
    expect(plan).toHaveAttribute("aria-controls", "sidebar");
    expect(plan).toHaveAttribute("aria-expanded", "false");
    await user.click(plan);
    expect(sidebar()).toHaveAttribute("data-mode", "open");
    expect(screen.getByRole("radio", { name: "B" })).toHaveFocus();
    expect(screen.queryByRole("button", { name: TR.changePlan })).toBeNull();
  });
});

describe("the app shell on a phone", () => {
  it("opens the sidebar from the phone bar as a modal drawer and closes it with Escape", async () => {
    stubLayout("phone");
    const { user } = renderShell();
    const menu = within(screen.getByRole("banner")).getByRole("button", { name: TR.openMenu });
    expect(menu).toHaveAttribute("aria-controls", "sidebar");
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(menu);
    const dialog = screen.getByRole("dialog", { name: TR.menu });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(sidebar()).toContainElement(dialog);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(within(dialog).getByRole("button", { name: TR.closeMenu })).toHaveFocus();
    expect(within(dialog).getByRole("navigation")).toBeInTheDocument();
    // The page behind is out of reach and does not scroll.
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");
    expect(screen.getByRole("banner", { hidden: true })).toHaveAttribute("inert");
    expect(document.documentElement.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu).toHaveFocus();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    expect(document.documentElement.style.overflow).toBe("");
  });

  it("leaves the drawer open when a control inside it already answered Escape", async () => {
    stubLayout("phone");
    // A control that closes something of its own on Escape and says so.
    function Answering() {
      return (
        <ShellPortal slot="plan">
          <input
            aria-label="answers escape"
            onKeyDown={(event) => {
              if (event.key === "Escape") event.preventDefault();
            }}
          />
        </ShellPortal>
      );
    }
    const { user } = renderShell({ path: `${MEMBERS}/7`, page: <Answering /> });
    await user.click(screen.getByRole("button", { name: TR.openMenu }));
    await user.click(screen.getByRole("textbox", { name: "answers escape" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: TR.menu })).toBeInTheDocument();
    // Escape anywhere else still closes it.
    await user.click(screen.getByRole("button", { name: TR.closeMenu }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: TR.openMenu }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes the drawer from the scrim, the close button and a navigation", async () => {
    stubLayout("phone");
    const { user, container } = renderShell({ identity: CLAIMED });
    const menu = screen.getByRole("button", { name: TR.openMenu });

    await user.click(menu);
    await user.click(container.querySelector(".scrim")!);
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(menu);
    await user.click(screen.getByRole("button", { name: TR.closeMenu }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(menu).toHaveFocus();

    await user.click(menu);
    await user.click(screen.getByRole("link", { name: TR.league }));
    expect(location()).toBe(MEMBERS);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container.querySelector(".scrim")).toBeNull();
  });

  it("links the phone bar's 'Fikstür' to the list, or opens the page's sheet when it has one", async () => {
    stubLayout("phone");
    // A page renders its sheet outside main, as the member page does.
    function SheetPage() {
      const shell = useShell();
      const register = shell?.registerSheet;
      useEffect(() => register?.(), [register]);
      return createPortal(
        <div id={FIXTURE_SHEET_ID} data-testid="sheet" data-open={String(shell?.sheetOpen)}>
          sheet
        </div>,
        document.body,
      );
    }
    const plain = renderShell();
    expect(
      within(screen.getByRole("banner")).getByRole("link", { name: TR.fixtures }),
    ).toHaveAttribute("href", "/fixtures");
    plain.unmount();

    const { user } = renderShell({ path: `${MEMBERS}/7`, page: <SheetPage /> });
    const open = within(screen.getByRole("banner")).getByRole("button", { name: TR.fixtures });
    expect(open).toHaveAttribute("aria-controls", FIXTURE_SHEET_ID);
    expect(open).toHaveAttribute("aria-expanded", "false");

    await user.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("sheet")).toHaveAttribute("data-open", "true");
    // Everything behind the sheet is out of reach: the sidebar, the phone bar and the page.
    expect(document.getElementById("sidebar")).toHaveAttribute("inert");
    expect(screen.getByRole("banner", { hidden: true })).toHaveAttribute("inert");
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");
    expect(document.documentElement.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.getByTestId("sheet")).toHaveAttribute("data-open", "false");
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    expect(open).toHaveFocus();
  });

  it("turns the phone bar's 'Fikstür' back into a link when the page withdraws its sheet", async () => {
    stubLayout("phone");
    function SheetPage({ offered }: { offered: boolean }) {
      const register = useShell()?.registerSheet;
      useEffect(() => (offered ? register?.() : undefined), [offered, register]);
      return offered ? <div id={FIXTURE_SHEET_ID}>sheet</div> : null;
    }
    const { rerender } = renderShell({ path: `${MEMBERS}/7`, page: <SheetPage offered /> });
    const bar = () => within(screen.getByRole("banner"));
    expect(bar().getByRole("button", { name: TR.fixtures })).toBeInTheDocument();

    rerender(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`${MEMBERS}/7`]}>
          <PageShell>
            <SheetPage offered={false} />
          </PageShell>
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(bar().queryByRole("button", { name: TR.fixtures })).toBeNull();
    expect(bar().getByRole("link", { name: TR.fixtures })).toHaveAttribute("href", "/fixtures");
  });

  it("closes the drawer from Değiştir and leaves focus on a heading the step put it on", async () => {
    stubLayout("phone");
    const onChangeMember = vi.fn(() => {
      // What the member gate does: the picker's heading takes focus as it arrives.
      document.querySelector<HTMLElement>("#page-heading")?.focus();
    });
    const { user } = renderShell({
      identity: CLAIMED,
      onChangeMember,
      page: (
        <h1 id="page-heading" tabIndex={-1}>
          Sen kimsin?
        </h1>
      ),
    });
    await user.click(screen.getByRole("button", { name: TR.openMenu }));
    const dialog = screen.getByRole("dialog", { name: TR.menu });
    await user.click(within(dialog).getByRole("button", { name: TR.changeMember }));
    expect(onChangeMember).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Sen kimsin?" })).toHaveFocus();
  });

  it("closes the drawer when the window grows to a desktop", async () => {
    const viewport = stubLayout("phone");
    const { user, container } = renderShell();
    await user.click(screen.getByRole("button", { name: TR.openMenu }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    viewport.resize("desktop");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container.firstElementChild).toHaveAttribute("data-layout", "desktop");
    expect(screen.queryByRole("banner")).toBeNull();
    expect(sidebar()).toHaveAttribute("data-mode", "open");
    expect(document.documentElement.style.overflow).toBe("");
  });
});

describe("the app shell on a tablet", () => {
  it("opens the full sidebar over the page from the icon rail", async () => {
    stubLayout("tablet");
    const { user } = renderShell();
    expect(screen.queryByRole("banner")).toBeNull();
    expect(sidebar()).toHaveAttribute("data-mode", "rail");
    const expand = screen.getByRole("button", { name: TR.expandSidebar });
    expect(expand).toHaveAttribute("aria-controls", "sidebar");
    expect(expand).toHaveAttribute("aria-expanded", "false");
    expect(expand).toHaveAttribute("aria-haspopup", "dialog");
    expect(navLinks()).toHaveLength(3);

    await user.click(expand);
    const dialog = screen.getByRole("dialog", { name: TR.menu });
    expect(sidebar()).toHaveAttribute("data-mode", "drawer");
    const close = within(dialog).getByRole("button", { name: TR.closeMenu });
    expect(close).toHaveFocus();
    // Inside the drawer the button only closes it.
    expect(close).not.toHaveAttribute("aria-expanded");
    expect(close).not.toHaveAttribute("aria-controls");
    expect(screen.getByRole("main", { hidden: true })).toHaveAttribute("inert");

    await user.click(close);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: TR.expandSidebar })).toHaveFocus();
    // A tablet never stores the desktop's collapse choice.
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBeNull();
  });

  it("keeps the member and Değiştir in the rail, opening the sidebar on Değiştir", async () => {
    stubLayout("tablet");
    const onChangeMember = vi.fn();
    const { user } = renderShell({ identity: CLAIMED, onChangeMember });
    expect(sidebar()).toHaveAttribute("data-mode", "rail");
    const icon = within(sidebar()).getByRole("button", { name: TR.changeMember });
    expect(icon).toHaveAccessibleDescription(
      "SquadOpt Classic League: Deniz Aral, North Stand Notes",
    );
    expect(icon).toHaveAttribute("aria-haspopup", "dialog");
    expect(icon).toHaveAttribute("aria-expanded", "false");
    // The icon stands over the navigation, as the block does.
    expect(
      icon.compareDocumentPosition(screen.getByRole("navigation")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await user.click(icon);
    const dialog = screen.getByRole("dialog", { name: TR.menu });
    const change = within(dialog).getByRole("button", { name: TR.changeMember });
    expect(change).toHaveFocus();
    expect(within(dialog).getByText("Deniz Aral")).toBeInTheDocument();
    expect(onChangeMember).not.toHaveBeenCalled();

    // Closed without changing, focus comes back to the rail's icon.
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(sidebar()).getByRole("button", { name: TR.changeMember })).toHaveFocus();

    await user.click(within(sidebar()).getByRole("button", { name: TR.changeMember }));
    await user.click(
      within(screen.getByRole("dialog", { name: TR.menu })).getByRole("button", {
        name: TR.changeMember,
      }),
    );
    expect(onChangeMember).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has no identity icon in the rail before the member is claimed", () => {
    stubLayout("tablet");
    for (const identity of [NO_IDENTITY, CHOSEN]) {
      const view = renderShell({ identity });
      expect(within(sidebar()).queryByRole("button", { name: TR.changeMember })).toBeNull();
      expect(document.getElementById("sidebar-member")).toBeNull();
      view.unmount();
    }
  });
});

describe("the collapsed desktop rail with a member claimed", () => {
  it("opens the sidebar from the identity icon with focus on Değiştir", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    const { user } = renderShell({ identity: CLAIMED });
    expect(sidebar()).toHaveAttribute("data-mode", "rail");
    const icon = within(sidebar()).getByRole("button", { name: TR.changeMember });
    expect(icon).toHaveAccessibleDescription(
      "SquadOpt Classic League: Deniz Aral, North Stand Notes",
    );
    // On a desktop the sidebar folds in place; the icon opens no dialog.
    expect(icon).not.toHaveAttribute("aria-haspopup");

    await user.click(icon);
    expect(sidebar()).toHaveAttribute("data-mode", "open");
    expect(window.localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("open");
    const change = within(sidebar()).getByRole("button", { name: TR.changeMember });
    expect(change).toHaveFocus();
    expect(change).toHaveAccessibleDescription(
      "SquadOpt Classic League: Deniz Aral, North Stand Notes",
    );
    expect(document.querySelectorAll("#sidebar-member")).toHaveLength(1);
  });
});
