import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
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
import { usePageViewport } from "../shell/usePageViewport";
import { arriveWithoutSnapshot, crossfade } from "../viewTransition";
import { MatchScene } from "./MatchScene";
import styles from "./PageShell.module.css";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Direction D's app shell, around every page.
 *
 * One copy of every control, which the stylesheet moves between three layouts: under
 * 600 px a sticky phone bar and the sidebar as a drawer; from 600 to 1179 px a 72 px icon
 * rail that opens the full sidebar over the page; from 1180 px the sidebar beside the page,
 * open at 264 px or collapsed to the rail (the choice is kept in this browser). The phone
 * bar exists only in the phone layout; everything else is rendered once in every layout.
 *
 * The sidebar holds the brand, the identity block, the navigation and a footer with the
 * language switch. The shell reads no document of its own.
 *
 * `identity` is the league the visitor entered and the member they said they are in it,
 * handed in by the app (design/ reads nothing of the league feature). It decides the
 * navigation, and with a member it draws the identity block: the league, the member and
 * Değiştir, which calls `onChangeMember`, the one way to say you are someone else. The
 * rail, too narrow for the block, shows it as one icon that opens the sidebar with focus
 * on Değiştir.
 *
 * `live` is the LIVE page the phone bar's pill opens, handed in only while one of the
 * member's matches is in its window; null, the bar has no pill. Below 360 px the pill's
 * room comes from Fikstür, which then shows its icon alone.
 */
export function PageShell({
  children,
  identity = NO_IDENTITY,
  onChangeMember,
  whoExtra = null,
  live = null,
}: {
  children: ReactNode;
  identity?: ShellIdentity;
  onChangeMember?: () => void;
  /** A control drawn in the identity block after Değiştir; the shell knows nothing of it. */
  whoExtra?: ReactNode;
  /** The address the phone bar's LIVE pill opens, or null for no pill. */
  live?: string | null;
}) {
  const { messages } = useLanguage();
  const copy = messages.shell;
  const location = useLocation();
  const layout = useShellLayout();

  const [drawerState, setDrawerOpen] = useState(false);
  const [sheetState, setSheetOpen] = useState(false);
  const [sheets, setSheets] = useState(0);
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [lastSeen, setLastSeen] = useState<MemberContext | null>(null);
  const [shown, setShown] = useState({ layout, pathname: location.pathname });

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
      if (event.key === "Escape") closeOverlays();
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
  const panelRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const markerRef = useRef<HTMLSpanElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const whoChangeRef = useRef<HTMLButtonElement>(null);
  const whoRailRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const wasOverlay = useRef(false);
  useLayoutEffect(() => {
    const nav = navRef.current;
    const marker = markerRef.current;
    if (!nav || !marker) return;
    const place = () => {
      const selected = nav.querySelector<HTMLElement>('[aria-current="page"]');
      marker.hidden = !selected;
      if (!selected) return;
      marker.style.height = `${selected.offsetHeight}px`;
      marker.style.transform = `translateY(${selected.offsetTop}px)`;
    };
    place();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(place);
    observer.observe(nav);
    return () => observer.disconnect();
  }, [location.pathname, location.search, location.hash, identity, mode]);

  useEffect(() => {
    if (!drawerOpen) return;
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const controls = [
        ...(panelRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]',
        ) ?? []),
      ].filter((node) => node.getClientRects().length > 0);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus({ preventScroll: true });
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", trap);
    return () => document.removeEventListener("keydown", trap);
  }, [drawerOpen]);
  // The rail's identity icon opened the drawer. The icon itself is gone while the drawer
  // is open, so focus returns to the one drawn again when it closes.
  const openedFromWho = useRef(false);
  useEffect(() => {
    if (overlay && !wasOverlay.current) {
      returnFocus.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (drawerOpen)
        ((openedFromWho.current ? whoChangeRef.current : null) ?? toggleRef.current)?.focus({
          preventScroll: true,
        });
    } else if (!overlay && wasOverlay.current) {
      const opener = openedFromWho.current ? whoRailRef.current : returnFocus.current;
      returnFocus.current = null;
      openedFromWho.current = false;
      const active = document.activeElement;
      const onPage = active instanceof Node && (mainRef.current?.contains(active) ?? false);
      if (onPage) {
        // Focus is already on the page; it stays there.
      } else if (opener?.isConnected) opener.focus({ preventScroll: true });
      else
        (layout === "phone" ? menuRef.current : toggleRef.current)?.focus({ preventScroll: true });
    }
    wasOverlay.current = overlay;
  }, [overlay, drawerOpen, layout]);

  // The rail's identity icon opens the sidebar on a desktop and puts focus on Değiştir.
  const focusAfterExpand = useRef(false);
  useEffect(() => {
    if (!focusAfterExpand.current || collapsed) return;
    focusAfterExpand.current = false;
    (whoChangeRef.current ?? toggleRef.current)?.focus({ preventScroll: true });
  }, [collapsed]);

  const setDesktopCollapsed = (next: boolean) => {
    setCollapsed(next);
    writeSidebarCollapsed(next);
  };
  const onToggle = () => {
    if (layout === "desktop") setDesktopCollapsed(!collapsed);
    else {
      if (!drawerOpen) toggleRef.current?.focus({ preventScroll: true });
      setDrawerOpen(!drawerOpen);
    }
  };
  const openWho = () => {
    if (layout === "desktop") {
      focusAfterExpand.current = true;
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
  useLayoutEffect(() => arriveWithoutSnapshot(mainRef.current), [location.pathname]);
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
    const options = { preventScroll: true };
    if (!hash.current) window.scrollTo({ top: 0, behavior: "instant" });
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
      sheetOpen,
      setSheetOpen,
      registerSheet,
      focusPage,
    }),
    [sheetOpen, registerSheet, focusPage],
  );

  usePageViewport(focusPage);

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
      <span className={styles.phoneFixturesText}>{copy.fixtures}</span>
    </span>
  );
  const liveHere = live !== null && location.pathname === live;

  return (
    <ShellContext.Provider value={shell}>
      <div
        className={styles.shell}
        data-layout={layout}
        data-collapsed={layout === "desktop" && collapsed ? "true" : undefined}
        data-drawer={drawerOpen ? "open" : undefined}
      >
        <MatchScene tall={layout === "phone"} arrival={location.pathname} />
        <a className="visually-hidden" href="#main" inert={overlay}>
          {copy.skip}
        </a>
        {layout === "phone" ? (
          <header
            className={styles.phoneBar}
            inert={overlay}
            data-phone-bar
            data-live={live !== null || undefined}
          >
            <button
              ref={menuRef}
              type="button"
              className={styles.menuButton}
              aria-label={copy.openMenu}
              aria-controls="sidebar"
              aria-expanded={drawerOpen}
              aria-haspopup="dialog"
              onClick={(event) => {
                event.currentTarget.focus({ preventScroll: true });
                setDrawerOpen(true);
              }}
            >
              <MenuIcon />
            </button>
            <span className={styles.phoneBrand}>
              <BrandMark small className={styles.mark} />
              <span className={styles.phoneWordmark}>SquadOpt</span>
            </span>
            {live !== null ? (
              <Link
                to={live}
                className={styles.phoneLive}
                aria-current={liveHere ? "page" : undefined}
                data-live-pill
                onClick={(event) => follow(event, { key: "live", to: live, active: liveHere })}
              >
                <span className={styles.phoneLiveFace}>
                  <span className={styles.phoneLiveDot} aria-hidden="true" />
                  {copy.live}
                </span>
              </Link>
            ) : null}
            {sheets > 0 ? (
              <button
                type="button"
                className={styles.phoneFixtures}
                aria-controls={FIXTURE_SHEET_ID}
                aria-expanded={sheetOpen}
                aria-haspopup="dialog"
                onClick={(event) => {
                  event.currentTarget.focus({ preventScroll: true });
                  setSheetOpen(true);
                }}
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
            ref={panelRef}
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
                  {whoExtra}
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
              <nav ref={navRef} aria-label={copy.primary} className={styles.nav}>
                <span ref={markerRef} className={styles.navMarker} aria-hidden="true" />
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
              <div className={styles.footer}>
                <LanguageToggle vertical={rail} />
                <ThemeToggle vertical={rail} />
              </div>
            </div>
          </div>
        </aside>
        {/* A page's fixture sheet is rendered outside main, so main can be inert while
            the sheet is open as well as while the drawer is. */}
        <main id="main" ref={mainRef} tabIndex={-1} className={styles.main} inert={overlay}>
          {children}
        </main>
        <div
          className={styles.scrim}
          data-open={overlay || undefined}
          aria-hidden="true"
          onClick={closeOverlays}
        />
      </div>
    </ShellContext.Provider>
  );
}
