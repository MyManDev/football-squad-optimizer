import userEvent from "@testing-library/user-event";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../i18n/messages";
import { DESKTOP_QUERY, PHONE_QUERY, type ShellLayout } from "../shell/layout";
import { FIXTURE_SHEET_ID, useShell, useShellSlot } from "../shell/ShellContext";
import { ShellPortal } from "../shell/ShellPortal";
import { SIDEBAR_STORAGE_KEY } from "../shell/sidebarPreference";
import { PageShell } from "./PageShell";

const TR = MESSAGES.tr.shell;

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>
  );
}

function renderShell({
  path = "/",
  language = "tr",
  viewerEntryId = null,
  page = <p>page</p>,
}: {
  path?: string;
  language?: Language;
  viewerEntryId?: number | null;
  page?: ReactNode;
} = {}) {
  const user = userEvent.setup();
  const view = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[path]}>
        <PageShell viewerEntryId={viewerEntryId}>{page}</PageShell>
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
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
    expect(sidebar()).toHaveAttribute("id", "sidebar");
    expect(within(sidebar()).getByRole("navigation")).toBeInTheDocument();
    // The phone bar belongs to the phone layout only, and nothing is a dialog.
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each(["tr", "en"] as const)(
    "names the navigation from the catalogue and keeps the system pages unlinked in %s",
    (language) => {
      const copy = MESSAGES[language].shell;
      renderShell({ language });

      expect(screen.getByRole("navigation", { name: copy.primary })).toBeInTheDocument();
      expect(screen.getByRole("complementary", { name: copy.sidebar })).toBeInTheDocument();

      expect(navLinks().map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
        [copy.thisWeek, "/"],
        [copy.league, "/league/members"],
        [copy.fixtures, "/fixtures"],
        [copy.contribute, "/contribute"],
      ]);
      expect(screen.getByRole("link", { name: copy.thisWeek })).toHaveAttribute(
        "aria-current",
        "page",
      );
      const aside = screen.getByRole("complementary", { name: copy.sidebar });
      const status = within(aside).getByRole("link", { name: copy.operations });
      expect(status).toHaveAttribute("href", "/status");
      const hrefs = within(aside)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href"));
      expect(hrefs).toEqual(["/", "/league/members", "/fixtures", "/contribute", "/status"]);
      expect(
        document.querySelector('a[href="/league"], a[href="/admin"], a[href^="/gw/"]'),
      ).toBeNull();
    },
  );

  it("opens the member in the address as 'Bu hafta', with its plan, and its squad as 'Kadro'", async () => {
    const path = "/league/members/35249001?mode=fark-yarat&window=3";
    const { user } = renderShell({ path });

    const thisWeek = screen.getByRole("link", { name: TR.thisWeek });
    const squad = screen.getByRole("link", { name: TR.squad });
    expect(thisWeek).toHaveAttribute("href", path);
    expect(thisWeek).toHaveAttribute("aria-current", "page");
    expect(squad).toHaveAttribute("href", `${path}#kadro`);
    expect(squad).not.toHaveAttribute("aria-current");

    await user.click(squad);
    expect(location()).toBe(`${path}#kadro`);
    expect(screen.getByRole("link", { name: TR.squad })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: TR.thisWeek })).not.toHaveAttribute("aria-current");
  });

  it("keeps the member page in reach for the rest of the visit, in memory only", async () => {
    const path = "/league/members/35249001?mode=ortak-koru";
    const { user } = renderShell({ path });

    await user.click(screen.getByRole("link", { name: TR.fixtures }));
    expect(location()).toBe("/fixtures");
    expect(screen.getByRole("link", { name: TR.fixtures })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: TR.thisWeek })).toHaveAttribute("href", path);
    expect(screen.getByRole("link", { name: TR.squad })).toHaveAttribute("href", `${path}#kadro`);
    expect(window.localStorage.getItem("squadopt.viewer")).toBeNull();
    expect(Object.keys(window.localStorage)).not.toContain("squadopt.member");
  });

  it("opens the member the visitor claimed when the address names none", () => {
    renderShell({ path: "/fixtures", viewerEntryId: 42 });
    expect(screen.getByRole("link", { name: TR.thisWeek })).toHaveAttribute(
      "href",
      "/league/members/42",
    );
    expect(screen.getByRole("link", { name: TR.squad })).toHaveAttribute(
      "href",
      "/league/members/42#kadro",
    );
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
      TR.thisWeek,
      TR.league,
      TR.fixtures,
      TR.contribute,
    ]);
    expect(screen.getByRole("link", { name: TR.operations })).toHaveAttribute("href", "/status");
    expect(screen.getByRole("group", { name: "Dil" })).toHaveClass("vertical");
    first.unmount();

    const second = renderShell();
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
      screen.getByRole("link", { name: TR.operations }),
      screen.getByRole("button", { name: "page action" }),
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
    const { user } = renderShell({ path: "/league/members/7", page: <Late /> });
    await user.click(screen.getByRole("link", { name: TR.squad }));
    expect(scrolled).toContain("kadro");
  });
});

function Slots({ planFirst = true }: { planFirst?: boolean }) {
  const who = useShellSlot("who");
  return (
    <>
      <ShellPortal slot="who">
        <p>who block</p>
      </ShellPortal>
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
      <output data-testid="who-slot">{who ? who.tagName : "none"}</output>
    </>
  );
}

describe("the shell's slots", () => {
  it("renders a page's WHO and PLAN parts once, inside the sidebar", () => {
    const { container } = renderShell({ path: "/league/members/7", page: <Slots /> });

    expect(within(sidebar()).getByText("who block")).toBeInTheDocument();
    expect(within(sidebar()).getByRole("group", { name: "Strateji" })).toBeInTheDocument();
    expect(within(screen.getByRole("main")).queryByText("who block")).toBeNull();
    expect(within(screen.getByRole("main")).getByText("main content")).toBeInTheDocument();
    expect(container.querySelectorAll('input[name="strategy"]')).toHaveLength(2);
    expect(screen.getByTestId("who-slot")).toHaveTextContent("DIV");
    // The slot sits between the brand and the navigation, the plan after the navigation.
    const order = [...sidebar().querySelectorAll("p, nav, fieldset")].map((node) => node.tagName);
    expect(order).toEqual(["P", "NAV", "FIELDSET"]);
  });

  it("renders them inline where the page stands when there is no shell", () => {
    const { container } = render(
      <MemoryRouter>
        <Slots />
      </MemoryRouter>,
    );
    expect(screen.getByText("who block")).toBeInTheDocument();
    expect(container.querySelectorAll('input[name="strategy"]')).toHaveLength(2);
    expect(screen.getByTestId("who-slot")).toHaveTextContent("none");
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("offers the rail's plan button only while a page fills the plan, and opens the plan", async () => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, "collapsed");
    const empty = renderShell();
    expect(screen.queryByRole("button", { name: TR.changePlan })).toBeNull();
    empty.unmount();

    const { user } = renderShell({ path: "/league/members/7", page: <Slots /> });
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
    const { user } = renderShell({ path: "/league/members/7", page: <Answering /> });
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
    const { user, container } = renderShell();
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
    expect(location()).toBe("/league/members");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(container.querySelector(".scrim")).toBeNull();
  });

  it("links the phone bar's 'Fikstür' to the list, or opens the page's sheet when it has one", async () => {
    stubLayout("phone");
    function SheetPage() {
      const shell = useShell();
      const register = shell?.registerSheet;
      useEffect(() => register?.(), [register]);
      return (
        <div id={FIXTURE_SHEET_ID} data-testid="sheet" data-open={String(shell?.sheetOpen)}>
          sheet
        </div>
      );
    }
    const plain = renderShell();
    expect(
      within(screen.getByRole("banner")).getByRole("link", { name: TR.fixtures }),
    ).toHaveAttribute("href", "/fixtures");
    plain.unmount();

    const { user } = renderShell({ path: "/league/members/7", page: <SheetPage /> });
    const open = within(screen.getByRole("banner")).getByRole("button", { name: TR.fixtures });
    expect(open).toHaveAttribute("aria-controls", FIXTURE_SHEET_ID);
    expect(open).toHaveAttribute("aria-expanded", "false");

    await user.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("sheet")).toHaveAttribute("data-open", "true");
    expect(document.getElementById("sidebar")).toHaveAttribute("inert");
    expect(document.documentElement.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.getByTestId("sheet")).toHaveAttribute("data-open", "false");
    expect(open).toHaveFocus();
  });

  it("turns the phone bar's 'Fikstür' back into a link when the page withdraws its sheet", async () => {
    stubLayout("phone");
    function SheetPage({ offered }: { offered: boolean }) {
      const register = useShell()?.registerSheet;
      useEffect(() => (offered ? register?.() : undefined), [offered, register]);
      return offered ? <div id={FIXTURE_SHEET_ID}>sheet</div> : null;
    }
    const { rerender } = renderShell({ path: "/league/members/7", page: <SheetPage offered /> });
    const bar = () => within(screen.getByRole("banner"));
    expect(bar().getByRole("button", { name: TR.fixtures })).toBeInTheDocument();

    rerender(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={["/league/members/7"]}>
          <PageShell>
            <SheetPage offered={false} />
          </PageShell>
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(bar().queryByRole("button", { name: TR.fixtures })).toBeNull();
    expect(bar().getByRole("link", { name: TR.fixtures })).toHaveAttribute("href", "/fixtures");
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
    expect(navLinks()).toHaveLength(4);

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
});
