import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { Link, NavLink, useLocation } from "react-router";

import { LanguageToggle } from "../../i18n/LanguageToggle";
import { useLanguage } from "../../i18n/context";
import {
  BrandMark,
  CalendarIcon,
  ChevronIcon,
  CloseIcon,
  MenuIcon,
  NavIcon,
  PlanIcon,
  StatusIcon,
} from "../shell/icons";
import { useShellLayout } from "../shell/layout";
import { memberAt, memberInContext, navItems, type MemberContext } from "../shell/nav";
import { FIXTURE_SHEET_ID, ShellContext, type ShellContextValue } from "../shell/ShellContext";
import { readSidebarCollapsed, writeSidebarCollapsed } from "../shell/sidebarPreference";
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
 * The sidebar holds the brand, the WHO slot, the navigation, the PLAN slot and a footer
 * with the language switch and the operations link. A page fills the two slots through
 * `ShellPortal`; the shell reads no document of its own.
 *
 * `viewerEntryId` is the member the visitor said they are, held in memory only; with no
 * member in the address, 'Bu hafta' opens that member's page.
 */
export function PageShell({
  children,
  viewerEntryId = null,
}: {
  children: ReactNode;
  viewerEntryId?: number | null;
}) {
  const { messages } = useLanguage();
  const copy = messages.shell;
  const location = useLocation();
  const layout = useShellLayout();

  const [drawerState, setDrawerOpen] = useState(false);
  const [sheetState, setSheetOpen] = useState(false);
  const [sheets, setSheets] = useState(0);
  const [collapsed, setCollapsed] = useState(readSidebarCollapsed);
  const [whoSlot, setWhoSlot] = useState<HTMLElement | null>(null);
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

  // The member page last opened stays in reach for the rest of the visit, in memory only.
  const here = memberAt(location);
  if (here) {
    const search = here.search ?? (lastSeen?.entryId === here.entryId ? lastSeen.search : "");
    if (lastSeen?.entryId !== here.entryId || lastSeen.search !== search)
      setLastSeen({ entryId: here.entryId, search });
  }
  const items = navItems(location, memberInContext(location, viewerEntryId, lastSeen));

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

  // Opening moves focus to the drawer's close button; closing returns it to the opener.
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const wasOverlay = useRef(false);
  useEffect(() => {
    if (overlay && !wasOverlay.current) {
      returnFocus.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      if (drawerOpen) toggleRef.current?.focus();
    } else if (!overlay && wasOverlay.current) {
      const opener = returnFocus.current;
      returnFocus.current = null;
      if (opener?.isConnected) opener.focus();
      else (layout === "phone" ? menuRef.current : toggleRef.current)?.focus();
    }
    wasOverlay.current = overlay;
  }, [overlay, drawerOpen, layout]);

  // The rail's plan button opens the sidebar and, on a desktop, puts focus in the plan.
  const focusPlan = useRef(false);
  useEffect(() => {
    if (!focusPlan.current || collapsed) return;
    focusPlan.current = false;
    const target =
      planSlot?.querySelector<HTMLElement>("input:checked:not([disabled])") ??
      planSlot?.querySelector<HTMLElement>(FOCUSABLE);
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
      focusPlan.current = true;
      setDesktopCollapsed(false);
    } else setDrawerOpen(true);
  };
  const closeDrawer = () => setDrawerOpen(false);

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

  const shell = useMemo<ShellContextValue>(
    () => ({
      drawerOpen,
      setDrawerOpen,
      sheetOpen,
      setSheetOpen,
      sheetAvailable: sheets > 0,
      registerSheet,
      whoSlot,
      planSlot,
    }),
    [drawerOpen, sheetOpen, sheets, registerSheet, whoSlot, planSlot],
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
            {shell.sheetAvailable ? (
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
              <NavLink to="/fixtures" className={styles.phoneFixtures}>
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
              <button
                ref={toggleRef}
                type="button"
                className={styles.toggle}
                aria-label={toggleLabel}
                aria-expanded={drawerOpen ? undefined : layout === "desktop" ? !collapsed : false}
                onClick={onToggle}
              >
                {toggleIcon}
              </button>
            </div>
            <div className={styles.body}>
              <div ref={setWhoSlot} className={styles.who} />
              <nav aria-label={copy.primary} className={styles.nav}>
                {items.map((item) => (
                  <Link
                    key={item.key}
                    to={item.to}
                    className={styles.navItem}
                    aria-current={item.active ? "page" : undefined}
                    onClick={closeDrawer}
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
                    onClick={openPlan}
                  >
                    <PlanIcon />
                  </button>
                </div>
              ) : null}
              <div className={styles.footer}>
                <LanguageToggle vertical={rail} />
                <NavLink to="/status" className={styles.status} onClick={closeDrawer}>
                  {rail ? <StatusIcon /> : null}
                  <span className={rail ? "visually-hidden" : undefined}>{copy.operations}</span>
                </NavLink>
              </div>
            </div>
          </div>
        </aside>
        <main id="main" className={styles.main} inert={drawerOpen}>
          {children}
        </main>
        {overlay ? (
          <div className={styles.scrim} aria-hidden="true" onClick={closeOverlays} />
        ) : null}
      </div>
    </ShellContext.Provider>
  );
}
