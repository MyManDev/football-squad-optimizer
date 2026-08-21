import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { LanguageToggle } from "../../i18n/LanguageToggle";
import { useLanguage } from "../../i18n/context";
import styles from "./PageShell.module.css";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", key: "squad", end: true },
  { to: "/moves", key: "moves", end: false },
  { to: "/rivals", key: "rivals", end: false },
  { to: "/league", key: "league", end: false },
  { to: "/analysis", key: "analysis", end: false },
] as const;

type NavKey = (typeof NAV)[number]["key"];

const navLabel = (messages: ReturnType<typeof useLanguage>["messages"], key: NavKey) =>
  messages.shell[key];

export function PageShell({ children }: { children: ReactNode }) {
  const { messages } = useLanguage();
  return (
    <div className={styles.shell}>
      <a className="visually-hidden" href="#main">
        {messages.shell.skip}
      </a>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.wordmark}>SquadOpt</span>
          <span className={styles.tagline}>{messages.shell.tagline}</span>
        </div>
        <nav aria-label={messages.shell.primary} className={styles.nav}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? styles.navActive : styles.navLink)}
            >
              {navLabel(messages, item.key)}
            </NavLink>
          ))}
        </nav>
        <div className={styles.preferences}>
          <LanguageToggle />
          <ThemeToggle />
        </div>
      </header>
      <main id="main" className={styles.main}>
        {children}
      </main>
      <footer className={styles.footer}>
        <span>{messages.shell.footer}</span>
        <NavLink to="/status" className={styles.footerLink}>
          {messages.shell.operations}
        </NavLink>
      </footer>
    </div>
  );
}
