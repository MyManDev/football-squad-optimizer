import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import {
  entryAddress,
  FIND_YOURSELF,
  leagueAddress,
  leagueIdInAddress,
  legacyLeagueAddress,
  membersAddress,
  PICK_HERE,
} from "../../../lib/leagueAddresses";
import { FplIdHelp } from "../components/FplIdHelp";
import { LeagueDataMissing, lookupPublishedLeague } from "../data";
import type { PublishedLeague } from "../directory";
import type { LeagueRefusal } from "../forwarded/reads";
import { useLeagueIdentity } from "../identity/useLeagueIdentity";
import styles from "./LeagueEntryPage.module.css";

type State =
  | "idle"
  | "invalid"
  | "loading"
  | "unsupported"
  | "missing"
  | "failed"
  | "headToHead"
  | "unknownLeague"
  | "cannotOpen";

const REFUSAL_STATE: Record<LeagueRefusal, State> = {
  head_to_head: "headToHead",
  unknown: "unknownLeague",
  unavailable: "cannotOpen",
};

/** A positive whole number as the field holds it, or null. */
function idIn(value: string): number | null {
  const trimmed = value.trim();
  const id = Number(trimmed);
  return /^\d+$/.test(trimmed) && Number.isSafeInteger(id) && id > 0 ? id : null;
}

/**
 * The league number, the first of the two steps in front of every league page. A
 * connected league opens its members list, where the second step asks who the visitor is
 * and then opens their own page. A league the site does not publish opens at its own
 * address, where the league gate reads it from the FPL forwarder (#983 step 4). Under it,
 * a team number opens that one team's page on its own.
 *
 * `inPlace`: the gate rendered this form at a league address. A connected league then
 * opens the page the address named under that league (an address from before the number
 * is rewritten with it), or the members list where the address named another league.
 *
 * `stay` (with `inPlace`): the gate rendered this form in front of a page whose address
 * names no league. A connected league keeps the address, and the member step follows there.
 * Those pages need a published league, so an unpublished one is named as such there.
 *
 * `unopened`: the gate read the league in the address from the forwarder and it did not
 * open. The form says why, offers the leagues the site lists (`listed`) when the forwarder
 * could not answer, and `onRetry` reads it again.
 */
export function LeagueEntryPage({
  inPlace = false,
  stay = false,
  unpublishedLeagueId = null,
  unopened = null,
  listed = [],
  onRetry,
}: {
  inPlace?: boolean;
  stay?: boolean;
  unpublishedLeagueId?: number | null;
  unopened?: { leagueId: number; refusal: LeagueRefusal } | null;
  listed?: readonly PublishedLeague[];
  onRetry?: () => void;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueEntry;
  const navigate = useNavigate();
  const location = useLocation();
  const { leagueId: remembered, chooseLeague } = useLeagueIdentity();
  const initialLeague = unopened?.leagueId ?? unpublishedLeagueId ?? remembered;
  const [value, setValue] = useState(initialLeague === null ? "" : String(initialLeague));
  const [state, setState] = useState<State>(
    unopened !== null
      ? REFUSAL_STATE[unopened.refusal]
      : unpublishedLeagueId === null
        ? "idle"
        : "unsupported",
  );
  // The number the last lookup asked for, named in the answer about it.
  const [asked, setAsked] = useState(unopened?.leagueId ?? unpublishedLeagueId ?? 0);
  const [entry, setEntry] = useState("");
  const [entryInvalid, setEntryInvalid] = useState(false);
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
    const leagueId = idIn(value);
    if (leagueId === null) {
      setState("invalid");
      return;
    }
    setState("loading");
    setAsked(leagueId);
    try {
      const result = await lookupPublishedLeague(leagueId);
      if (!active.current) return;
      if (result.status === "connected") {
        const here = inPlace && !stay ? legacyLeagueAddress(location.pathname, leagueId) : null;
        if (here !== null) {
          // An address from before the number, rewritten with it: the member step is asked
          // there, and its state puts focus on the picker as on the other two paths. The
          // gate at the new address chooses the league it names, as it does for any league
          // reached by its address. Choosing it here first would let the gate rewrite the
          // old address on its own before this navigation lands, without the step state.
          navigate(`${here}${location.search}${location.hash}`, {
            replace: true,
            state: PICK_HERE,
          });
          return;
        }
        chooseLeague(leagueId);
        if (inPlace && stay)
          navigate(
            { pathname: location.pathname, search: location.search, hash: location.hash },
            { replace: true, state: PICK_HERE },
          );
        else navigate(membersAddress(leagueId), { replace: inPlace, state: FIND_YOURSELF });
      } else if (stay) {
        setState("unsupported");
      } else if (onRetry !== undefined && leagueIdInAddress(location.pathname) === leagueId) {
        // The league this address names, asked for again: the gate reads it once more.
        setState(unopened === null ? "idle" : REFUSAL_STATE[unopened.refusal]);
        onRetry();
      } else {
        // Not published: its own address, where the gate reads it from the forwarder.
        navigate(leagueAddress(leagueId), { replace: inPlace });
      }
    } catch (error) {
      if (active.current) setState(error instanceof LeagueDataMissing ? "missing" : "failed");
    }
  }

  function submitEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const entryId = idIn(entry);
    if (entryId === null) {
      setEntryInvalid(true);
      return;
    }
    navigate(entryAddress(entryId));
  }

  const status =
    state === "idle"
      ? ""
      : state === "unsupported"
        ? copy.unsupported(asked)
        : state === "headToHead"
          ? copy.headToHead(asked)
          : state === "unknownLeague"
            ? copy.unknownLeague(asked)
            : state === "cannotOpen"
              ? copy.cannotOpen(asked)
              : copy[state];
  const others = listed.filter((league) => league.leagueId !== asked);

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
          {/* Where the number is found, folded right under the field that asks for it, so a
              visitor who does not know it looks no further than the field. */}
          <FplIdHelp />
          <button type="submit" disabled={state === "loading"}>
            {copy.submit}
          </button>
          <p id="league-entry-status" role="status">
            {status}
          </p>
          {/* A forwarder that could not answer: the same league again, or a listed one. */}
          {state === "cannotOpen" && onRetry !== undefined ? (
            <button type="button" className={styles.secondary} onClick={onRetry}>
              {copy.retry}
            </button>
          ) : null}
          {state === "cannotOpen" && others.length > 0 ? (
            <nav aria-labelledby="league-entry-listed" className={styles.listed}>
              <h2 id="league-entry-listed" className={styles.listedTitle}>
                {copy.listedLeagues}
              </h2>
              <ul>
                {others.map((league) => (
                  <li key={league.leagueId}>
                    <Link to={leagueAddress(league.leagueId)}>{league.leagueName}</Link>
                  </li>
                ))}
              </ul>
            </nav>
          ) : null}
        </form>
        {/* One team on its own, by its number. A page that needs a league asks for one only. */}
        {stay ? null : (
          <form onSubmit={submitEntry} className={`${styles.form} ${styles.entryForm}`}>
            <label htmlFor="entry-id">{copy.entryLabel}</label>
            <p id="entry-id-hint" className={styles.hint}>
              {copy.entryHint}
            </p>
            <input
              id="entry-id"
              name="entryId"
              inputMode="numeric"
              autoComplete="off"
              value={entry}
              onChange={(event) => {
                setEntry(event.target.value);
                setEntryInvalid(false);
              }}
              aria-invalid={entryInvalid}
              aria-describedby="entry-id-hint entry-id-status"
            />
            <button type="submit" className={styles.secondary}>
              {copy.entrySubmit}
            </button>
            <p id="entry-id-status" aria-live="polite">
              {entryInvalid ? copy.entryInvalid : ""}
            </p>
          </form>
        )}
      </Card>
    </div>
  );
}
