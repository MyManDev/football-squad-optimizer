import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { LeagueDataMissing, lookupPublishedLeague, SUPPORTED_LEAGUE_ID } from "../data";
import styles from "./LeagueEntryPage.module.css";

type State = "idle" | "invalid" | "loading" | "unsupported" | "missing" | "failed";

export function LeagueEntryPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueEntry;
  const navigate = useNavigate();
  const [value, setValue] = useState("");
  const [state, setState] = useState<State>("idle");
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
    if (leagueId !== SUPPORTED_LEAGUE_ID) {
      setState("unsupported");
      return;
    }
    setState("loading");
    try {
      const result = await lookupPublishedLeague(leagueId);
      if (!active.current) return;
      if (result === "connected") navigate("/league/members");
      else setState("unsupported");
    } catch (error) {
      if (active.current) setState(error instanceof LeagueDataMissing ? "missing" : "failed");
    }
  }

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>{copy.title}</h1>
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
            {state === "idle" ? "" : copy[state]}
          </p>
        </form>
      </Card>
    </div>
  );
}
