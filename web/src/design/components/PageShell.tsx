import type { ReactNode } from "react";
import { NavLink } from "react-router";

import styles from "./PageShell.module.css";
import { ThemeToggle } from "./ThemeToggle";

const NAV = [
  { to: "/", label: "This week", end: true },
  { to: "/history", label: "History", end: false },
  { to: "/status", label: "Status", end: false },
];

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <a className="visually-hidden" href="#main">
        Skip to content
      </a>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.wordmark}>SquadOpt</span>
          <span className={styles.tagline}>a decision, and what it rests on</span>
        </div>
        <nav aria-label="Primary" className={styles.nav}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? styles.navActive : styles.navLink)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <ThemeToggle />
      </header>
      <main id="main" className={styles.main}>
        {children}
      </main>
      <footer className={styles.footer}>
        Every number on these pages was produced by the SquadOpt live path and frozen in its ledger;
        the page renders, it does not compute.
      </footer>
    </div>
  );
}
