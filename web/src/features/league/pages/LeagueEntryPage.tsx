import { useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";

import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { legacyLeagueAddress, membersAddress } from "../../../lib/leagueAddresses";
import { LeagueDataMissing, lookupPublishedLeague } from "../data";
import { useChosenLeague } from "../identity/useChosenLeague";
import styles from "./LeagueEntryPage.module.css";

type State = "idle" | "invalid" | "loading" | "unsupported" | "missing" | "failed";

/**
 * `inPlace`: the gate rendered this form at a league address. A connected league then
 * opens the page the address named under that league (an address from before the number
 * is rewritten with it), or the members list where the address named another league.
 */
export function LeagueEntryPage({ inPlace = false }: { inPlace?: boolean }) {
  const { messages } = useLanguage();
  const copy = messages.leagueEntry;
  const navigate = useNavigate();
  const location = useLocation();
  const { leagueId: remembered, choose } = useChosenLeague();
  const [value, setValue] = useState(remembered === null ? "" : String(remembered));
  const [state, setState] = useState<State>("idle");
  // The number the last lookup asked for, named in the answer that it is not published.
  const [asked, setAsked] = useState(0);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state === "loading") return;
    const trimmed = value.trim();
    const leagueId = Number(trimmed);
    if (!/^\d+$/.test(trimmed) || !Number.isSafeInteger(leagueId) || leagueId <= 0) {
      setState("invalid");
      return;
    }
    setState("loading");
    setAsked(leagueId);
    try {
      const result = await lookupPublishedLeague(leagueId);
      if (!active.current) return;
      if (result.status === "connected") {
        choose(leagueId);
        const here = inPlace ? legacyLeagueAddress(location.pathname, leagueId) : null;
        navigate(
          here === null ? membersAddress(leagueId) : `${here}${location.search}${location.hash}`,
          { replace: inPlace },
        );
      } else setState("unsupported");
    } catch (error) {
      if (active.current) setState(error instanceof LeagueDataMissing ? "missing" : "failed");
    }
  }

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>
      {/* A first visitor lands here with nothing to go on, so the page says what the site
          does before it asks for a number. */}
      <p className={styles.intro}>{copy.intro}</p>
      <Card>
        <form onSubmit={submit} className={styles.form} aria-busy={state === "loading"}>
          <label htmlFor="league-id">{copy.label}</label>
          <p id="league-entry-hint" className={styles.hint}>
            {copy.hint}
          </p>
          <input
            id="league-id"
            name="leagueId"
            inputMode="numeric"
            autoComplete="off"
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setState("idle");
            }}
            disabled={state === "loading"}
            aria-invalid={state === "invalid"}
            aria-describedby="league-entry-hint league-entry-status"
          />
          <button type="submit" disabled={state === "loading"}>
            {copy.submit}
          </button>
          <p id="league-entry-status" role="status">
            {state === "idle"
              ? ""
              : state === "unsupported"
                ? copy.unsupported(asked)
                : copy[state]}
          </p>
        </form>
      </Card>
      <details className={styles.help}>
        <summary>{copy.helpTitle}</summary>
        <p>{copy.help}</p>
      </details>
    </div>
  );
}
