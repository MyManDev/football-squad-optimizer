import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";

import { LanguageToggle } from "../../i18n/LanguageToggle";
import { useLanguage } from "../../i18n/context";
import {
  BrandMark,
  CalendarIcon,
  ChevronIcon,
  CloseIcon,
  MenuIcon,
  NavIcon,
  PersonIcon,
  PlanIcon,
} from "../shell/icons";
import { useShellLayout } from "../shell/layout";
import {
  memberAt,
  navItems,
  NO_IDENTITY,
  type MemberContext,
  type NavItem,
  type ShellIdentity,
} from "../shell/nav";
import { FIXTURE_SHEET_ID, ShellContext, type ShellContextValue } from "../shell/ShellContext";
import { readSidebarCollapsed, writeSidebarCollapsed } from "../shell/sidebarPreference";
import { crossfade } from "../viewTransition";
import styles from "./PageShell.module.css";

const FOCUSABLE =
  'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/** Whether a slot holds anything, kept current as a page renders into it and leaves it. */
function useSlotFilled(slot: HTMLElement | null): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!slot) return () => undefined;
      const observer = new MutationObserver(onChange);
      observer.observe(slot, { childList: true });
      return () => observer.disconnect();
    },
    [slot],
  );
  return useSyncExternalStore(
    subscribe,
    () => (slot?.childElementCount ?? 0) > 0,
    () => false,
  );
}

/** A link to an id inside the page (the squad's '#kadro') scrolls there once it has rendered. */
function useScrollToHash(hash: string, key: string) {
  useEffect(() => {
    let id: string;
    try {
      id = decodeURIComponent(hash.slice(1));
    } catch {
      return;
    }
    if (!id) return;
    const reveal = () => {
      const target = document.getElementById(id);
      target?.scrollIntoView?.({ block: "start" });
      return target !== null;
    };
    if (reveal()) return;
    // The page may still be reading its documents; wait a little for the target to appear.
    let timer = 0;
    const observer = new MutationObserver(() => {
      if (reveal()) stop();
    });
    const stop = () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
    timer = window.setTimeout(stop, 5000);
    observer.observe(document.body, { childList: true, subtree: true });
    return stop;
  }, [hash, key]);
}

/**
 * Direction D's app shell, around every page.
 *
 * One copy of every control, which the stylesheet moves between three layouts: under
 * 600 px a sticky phone bar and the sidebar as a drawer; from 600 to 1179 px a 72 px icon
 * rail that opens the full sidebar over the page; from 1180 px the sidebar beside the page,
 * open at 264 px or collapsed to the rail (the choice is kept in this browser). The phone
 * bar exists only in the phone layout; everything else is rendered once in every layout.
 *
 * The sidebar holds the brand, the identity block, the navigation, the PLAN slot and a
 * footer with the language switch. A page fills the PLAN slot through `ShellPortal`; the
 * shell reads no document of its own.
 *
 * `identity` is the league the visitor entered and the member they said they are in it,
 * handed in by the app (design/ reads nothing of the league feature). It decides the
 * navigation, and with a member it draws the identity block: the league, the member and
 * Değiştir, which calls `onChangeMember`, the one way to say you are someone else. The
 * rail, too narrow for the block, shows it as one icon (as it shows the plan) that opens
 * the sidebar with focus on Değiştir.
 */
export function PageShell({
  children,
  identity = NO_IDENTITY,
  onChangeMember,
}: {
  children: ReactNode;
  identity?: ShellIdentity;
  onChangeMember?: () => void;
}) {
  const { messages } = useLanguage();
  const copy = messages.shell;
  const location = useLocation();
  const layout = useShellLayout();

  const [drawerState, setDrawerOpen] = useState(false);
  const [sheetState, setSheetOpen] = useState(false);
  const [sheets, setSheets] = useState(0);
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [planSlot, setPlanSlot] = useState<HTMLElement | null>(null);
  const [lastSeen, setLastSeen] = useState<MemberContext | null>(null);
  const [shown, setShown] = useState({ layout, pathname: location.pathname });
  const planFilled = useSlotFilled(planSlot);

  // A resize past a breakpoint, or a new page, closes whatever was open over the page.
  if (shown.layout !== layout || shown.pathname !== location.pathname) {
    setShown({ layout, pathname: location.pathname });
    if (shown.pathname !== location.pathname || layout === "desktop") setDrawerOpen(false);
    if (shown.pathname !== location.pathname || layout !== "phone") setSheetOpen(false);
  }

  // The drawer exists below 1180 px and the fixture sheet below 600 px only.
  const drawerOpen = drawerState && layout !== "desktop";
  const sheetOpen = sheetState && layout === "phone";
  const overlay = drawerOpen || sheetOpen;
  const mode =
    layout === "desktop"
      ? collapsed
        ? "rail"
        : "open"
      : layout === "phone" || drawerOpen
        ? "drawer"
        : "rail";
  const rail = mode === "rail";

  // The plan last opened on the visitor's own page stays in 'Bu hafta' for the rest of the
  // visit, in memory only. A rival's page is never recorded here.
  const here = memberAt(location);
  const own = identity.member;
  if (
    here &&
    own !== null &&
    here.leagueId === identity.leagueId &&
    here.entryId === String(own.entryId)
  ) {
    const same = lastSeen?.leagueId === here.leagueId && lastSeen.entryId === here.entryId;
    const search = here.search ?? (same ? lastSeen.search : "");
    if (!same || lastSeen.search !== search)
      setLastSeen({ leagueId: here.leagueId, entryId: here.entryId, search });
  }
  const items = navItems(location, identity, lastSeen);

  const closeOverlays = useCallback(() => {
    setDrawerOpen(false);
    setSheetOpen(false);
  }, []);

  useEffect(() => {
    if (!overlay) return;
    const onKey = (event: KeyboardEvent) => {
      // A control inside that already answered Escape (a list it closed) keeps the overlay.
      if (event.key === "Escape" && !event.defaultPrevented) closeOverlays();
    };
    document.addEventListener("keydown", onKey);
    const root = document.documentElement;
    const previousOverflow = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      root.style.overflow = previousOverflow;
    };
  }, [overlay, closeOverlays]);

  // Opening moves focus to the drawer's close button, or to Değiştir when the rail's
  // identity icon opened it; closing returns it to the opener, unless a step taken in the
  // drawer (Değiştir) has already put focus on the page.
  const mainRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const whoChangeRef = useRef<HTMLButtonElement>(null);
  const whoRailRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const wasOverlay = useRef(false);
  // The rail's identity icon opened the drawer. The icon itself is gone while the drawer
  // is open, so focus returns to the one drawn again when it closes.
  const openedFromWho = useRef(false);
  useEffect(() => {
    if (overlay && !wasOverlay.current) {
      returnFocus.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (drawerOpen)
        ((openedFromWho.current ? whoChangeRef.current : null) ?? toggleRef.current)?.focus();
    } else if (!overlay && wasOverlay.current) {
      const opener = openedFromWho.current ? whoRailRef.current : returnFocus.current;
      returnFocus.current = null;
      openedFromWho.current = false;
      const active = document.activeElement;
      const onPage = active instanceof Node && (mainRef.current?.contains(active) ?? false);
      if (onPage) {
        // Focus is already on the page; it stays there.
      } else if (opener?.isConnected) opener.focus();
      else (layout === "phone" ? menuRef.current : toggleRef.current)?.focus();
    }
    wasOverlay.current = overlay;
  }, [overlay, drawerOpen, layout]);

  // A rail button opens the sidebar on a desktop and puts focus in what it stands for:
  // the plan's chosen setting, or Değiştir.
  const focusAfterExpand = useRef<"plan" | "who" | null>(null);
  useEffect(() => {
    const goal = focusAfterExpand.current;
    if (goal === null || collapsed) return;
    focusAfterExpand.current = null;
    const target =
      goal === "who"
        ? whoChangeRef.current
        : (planSlot?.querySelector<HTMLElement>("input:checked:not([disabled])") ??
          planSlot?.querySelector<HTMLElement>(FOCUSABLE));
    (target ?? toggleRef.current)?.focus();
  }, [collapsed, planSlot]);

  const setDesktopCollapsed = (next: boolean) => {
    setCollapsed(next);
    writeSidebarCollapsed(next);
  };
  const onToggle = () => {
    if (layout === "desktop") setDesktopCollapsed(!collapsed);
    else setDrawerOpen(!drawerOpen);
  };
  const openPlan = () => {
    if (layout === "desktop") {
      focusAfterExpand.current = "plan";
      setDesktopCollapsed(false);
    } else setDrawerOpen(true);
  };
  const openWho = () => {
    if (layout === "desktop") {
      focusAfterExpand.current = "who";
      setDesktopCollapsed(false);
    } else {
      openedFromWho.current = true;
      setDrawerOpen(true);
    }
  };
  const closeDrawer = () => setDrawerOpen(false);

  // A move between pages from the navigation is one crossfade (#1131), as the step from the
  // picker to the page is. The router's own `viewTransition` prop works under a data router
  // only; this app's router hands it to the history, which ignores it. The router also sets
  // a new address as a React transition, which `crossfade`'s update cannot commit at once,
  // so the new picture waits until the address has landed, or for the data time at the
  // latest. The drawer closes inside the update and fades out with the page it stood over.
  // A link to the page already open, or a click for a new tab, is left to the link.
  const navigate = useNavigate();
  const landed = useRef<(() => void) | null>(null);
  useEffect(() => {
    landed.current?.();
    landed.current = null;
  }, [location.key]);
  const follow = (event: MouseEvent<HTMLAnchorElement>, item: NavItem) => {
    const plain =
      event.button === 0 && !event.metaKey && !event.altKey && !event.ctrlKey && !event.shiftKey;
    if (item.active || !plain) {
      closeDrawer();
      return;
    }
    event.preventDefault();
    const arrival = new Promise<void>((resolve) => {
      landed.current = resolve;
    });
    crossfade(
      () => {
        closeDrawer();
        navigate(item.to, { state: item.state });
      },
      () => arrival,
    );
  };

  const registerSheet = useCallback(() => {
    setSheets((count) => count + 1);
    let withdrawn = false;
    return () => {
      if (withdrawn) return;
      withdrawn = true;
      setSheets((count) => count - 1);
      setSheetOpen(false);
    };
  }, []);

  // Focus the page once a step in front of it is done: main at once, so focus never stays
  // on a node that is gone, then the page's heading when it is drawn, if the visitor has
  // not moved focus by then. With an id in the address the scroll to it keeps its place.
  const hash = useRef(location.hash);
  // Before any page's effect asks for focus in the same commit.
  useLayoutEffect(() => {
    hash.current = location.hash;
  }, [location.hash]);
  const stopWatching = useRef<(() => void) | null>(null);
  const focusPage = useCallback(() => {
    stopWatching.current?.();
    const main = mainRef.current;
    if (!main) return;
    const options = { preventScroll: hash.current !== "" };
    main.focus(options);
    const toHeading = () => {
      const heading = main.querySelector<HTMLElement>("h1");
      if (!heading) return false;
      if (document.activeElement === main) {
        if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
        heading.focus(options);
      }
      return true;
    };
    if (toHeading()) return;
    let timer = 0;
    const observer = new MutationObserver(() => {
      if (toHeading()) stop();
    });
    const stop = () => {
      observer.disconnect();
      window.clearTimeout(timer);
      if (stopWatching.current === stop) stopWatching.current = null;
    };
    timer = window.setTimeout(stop, 5000);
    observer.observe(main, { childList: true, subtree: true });
    stopWatching.current = stop;
  }, []);
  useEffect(() => () => stopWatching.current?.(), []);

  const changeMember = () => {
    closeOverlays();
    onChangeMember?.();
  };

  const shell = useMemo<ShellContextValue>(
    () => ({
      drawerOpen,
      setDrawerOpen,
      sheetOpen,
      setSheetOpen,
      sheetAvailable: sheets > 0,
      registerSheet,
      planSlot,
      focusPage,
    }),
    [drawerOpen, sheetOpen, sheets, registerSheet, planSlot, focusPage],
  );

  useScrollToHash(location.hash, location.key);

  const toggleLabel =
    layout === "desktop"
      ? collapsed
        ? copy.expandSidebar
        : copy.collapseSidebar
      : drawerOpen
        ? copy.closeMenu
        : copy.expandSidebar;
  const toggleIcon =
    mode === "drawer" ? (
      <CloseIcon />
    ) : (
      <ChevronIcon direction={mode === "open" ? "left" : "right"} />
    );
  // One line to a screen reader: "league: name, team". The spaces stand between the
  // lines, where the block's column does not draw them.
  const memberLine =
    own === null ? null : (
      <>
        <span className={styles.whoLeague}>{own.league}</span>
        <span className="visually-hidden">:</span>{" "}
        <span className={styles.whoName}>{own.name}</span>
        {own.team !== null ? (
          <>
            <span className="visually-hidden">,</span>{" "}
            <span className={styles.whoTeam}>{own.team}</span>
          </>
        ) : null}
      </>
    );
  // The phone bar's 'Fikstür' is the sidebar's, one tap closer.
  const fixturesItem = items.find((item) => item.key === "fixtures")!;
  const fixturesFace = (
    <span className={styles.phoneFixturesFace}>
      <CalendarIcon />
      {copy.fixtures}
    </span>
  );

  return (
    <ShellContext.Provider value={shell}>
      <div
        className={styles.shell}
        data-layout={layout}
        data-collapsed={layout === "desktop" && collapsed ? "true" : undefined}
        data-drawer={drawerOpen ? "open" : undefined}
      >
        <a className="visually-hidden" href="#main" inert={overlay}>
          {copy.skip}
        </a>
        {layout === "phone" ? (
          <header className={styles.phoneBar} inert={overlay}>
            <button
              ref={menuRef}
              type="button"
              className={styles.menuButton}
              aria-label={copy.openMenu}
              aria-controls="sidebar"
              aria-expanded={drawerOpen}
              aria-haspopup="dialog"
              onClick={() => setDrawerOpen(true)}
            >
              <MenuIcon />
            </button>
            <span className={styles.phoneBrand}>
              <BrandMark small className={styles.mark} />
              <span className={styles.phoneWordmark}>SquadOpt</span>
            </span>
            {sheets > 0 ? (
              <button
                type="button"
                className={styles.phoneFixtures}
                aria-controls={FIXTURE_SHEET_ID}
                aria-expanded={sheetOpen}
                aria-haspopup="dialog"
                onClick={() => setSheetOpen(true)}
              >
                {fixturesFace}
              </button>
            ) : (
              <NavLink
                to="/fixtures"
                className={styles.phoneFixtures}
                onClick={(event) => follow(event, fixturesItem)}
              >
                {fixturesFace}
              </NavLink>
            )}
          </header>
        ) : null}
        <aside
          id="sidebar"
          className={styles.sidebar}
          aria-label={copy.sidebar}
          data-mode={mode}
          inert={sheetOpen}
        >
          <div
            className={styles.panel}
            role={drawerOpen ? "dialog" : undefined}
            aria-modal={drawerOpen ? true : undefined}
            aria-label={drawerOpen ? copy.menu : undefined}
          >
            <div className={styles.brandRow}>
              <span className={styles.brand}>
                <BrandMark className={styles.mark} />
                <span className={rail ? "visually-hidden" : styles.wordmark}>SquadOpt</span>
              </span>
              {/* Open or collapse the sidebar; in the drawer the same button closes it. */}
              <button
                ref={toggleRef}
                type="button"
                className={styles.toggle}
                aria-label={toggleLabel}
                aria-controls={drawerOpen ? undefined : "sidebar"}
                aria-expanded={drawerOpen ? undefined : layout === "desktop" ? !collapsed : false}
                aria-haspopup={layout === "tablet" && !drawerOpen ? "dialog" : undefined}
                onClick={onToggle}
              >
                {toggleIcon}
              </button>
            </div>
            <div className={styles.body}>
              {own !== null && !rail ? (
                <div className={styles.who}>
                  <p className={styles.whoText} id="sidebar-member">
                    {memberLine}
                  </p>
                  <button
                    ref={whoChangeRef}
                    type="button"
                    className={styles.whoChange}
                    aria-describedby="sidebar-member"
                    onClick={changeMember}
                  >
                    {copy.changeMember}
                  </button>
                </div>
              ) : null}
              {own !== null && rail ? (
                <div className={styles.whoRail}>
                  <button
                    ref={whoRailRef}
                    type="button"
                    className={styles.railButton}
                    aria-label={copy.changeMember}
                    aria-describedby="sidebar-member"
                    aria-controls="sidebar"
                    aria-expanded={false}
                    aria-haspopup={layout === "desktop" ? undefined : "dialog"}
                    onClick={openWho}
                  >
                    <PersonIcon />
                  </button>
                  {/* The same line the block shows, read with the icon and in reading order. */}
                  <p className="visually-hidden" id="sidebar-member">
                    {memberLine}
                  </p>
                </div>
              ) : null}
              <nav aria-label={copy.primary} className={styles.nav}>
                {items.map((item) => (
                  <Link
                    key={item.key}
                    to={item.to}
                    state={item.state}
                    className={styles.navItem}
                    aria-current={item.active ? "page" : undefined}
                    onClick={(event) => follow(event, item)}
                  >
                    <NavIcon name={item.key} className={styles.navIcon} />
                    <span className={rail ? "visually-hidden" : undefined}>{copy[item.key]}</span>
                  </Link>
                ))}
              </nav>
              <div ref={setPlanSlot} className={styles.plan} />
              {rail && planFilled ? (
                <div className={styles.planRail}>
                  <button
                    type="button"
                    className={styles.railButton}
                    aria-label={copy.changePlan}
                    aria-controls="sidebar"
                    aria-expanded={false}
                    aria-haspopup={layout === "desktop" ? undefined : "dialog"}
                    onClick={openPlan}
                  >
                    <PlanIcon />
                  </button>
                </div>
              ) : null}
              <div className={styles.footer}>
                <LanguageToggle vertical={rail} />
              </div>
            </div>
          </div>
        </aside>
        {/* A page's fixture sheet is rendered outside main, so main can be inert while
            the sheet is open as well as while the drawer is. */}
        <main id="main" ref={mainRef} tabIndex={-1} className={styles.main} inert={overlay}>
          {children}
        </main>
        {overlay ? (
          <div className={styles.scrim} aria-hidden="true" onClick={closeOverlays} />
        ) : null}
      </div>
    </ShellContext.Provider>
  );
}
