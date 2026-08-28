import { useState } from "react";
import { useNavigate } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { loadLeagueMembers } from "../../league/data";
import { useDecisionSelection } from "../decisionSelection";
import { MODE_PRICE_FOLDS, WINDOWS, getPlayModes } from "../modePrices";
import styles from "./DecisionControls.module.css";

/** A plain number, or the id inside an FPL league URL (…/leagues/352490/standings/c). */
function parseLeagueId(text: string): number | null {
  const fromUrl = text.match(/leagues\/(\d+)/);
  if (fromUrl) return Number(fromUrl[1]);
  const plain = text.trim().match(/^(\d+)$/);
  return plain ? Number(plain[1]) : null;
}

type LeagueFieldState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "invalid" }
  | { kind: "unavailable" }
  | { kind: "mismatch"; publishedId: number };

export function DecisionControls({ variant = "default" }: { variant?: "default" | "entry" }) {
  const { locale, messages } = useLanguage();
  const copy = messages.decision;
  const navigate = useNavigate();
  const [leagueInput, setLeagueInput] = useState("");
  const [leagueState, setLeagueState] = useState<LeagueFieldState>({ kind: "idle" });
  const playModes = getPlayModes(
    copy.modes,
    locale,
    variant === "entry" ? "point-cost" : "measured",
  );
  const { mode, windowSize, update } = useDecisionSelection();

  async function connectLeague() {
    const requested = parseLeagueId(leagueInput);
    if (requested === null) {
      setLeagueState({ kind: "invalid" });
      return;
    }
    setLeagueState({ kind: "checking" });
    try {
      // A static site can only open the league it precomputed; the published members
      // document says which one that is, and its absence is the honest "not yet" state.
      const members = await loadLeagueMembers();
      if (members.payload.league_id === requested) navigate("/league/members");
      else setLeagueState({ kind: "mismatch", publishedId: members.payload.league_id });
    } catch {
      setLeagueState({ kind: "unavailable" });
    }
  }

  const competitive = mode !== "saf-puan";

  return (
    <Card title={copy.title} aside={<Badge tone="accent">{copy.shareable}</Badge>}>
      <p className={styles.intro}>{variant === "entry" ? copy.entryIntro : copy.intro}</p>

      <div className={styles.controls}>
        <fieldset className={styles.fieldset}>
          <legend>{copy.horizon}</legend>
          <div className={styles.windowOptions}>
            {WINDOWS.map((window) => (
              <label className={styles.windowOption} key={window}>
                <input
                  type="radio"
                  name="window"
                  value={window}
                  checked={windowSize === window}
                  onChange={() => update("window", String(window))}
                />
                <span>{copy.week(window)}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend>{copy.mode}</legend>
          <div className={styles.modeOptions}>
            {playModes.map((option) => (
              <label className={styles.modeOption} key={option.value}>
                <input
                  type="radio"
                  name="mode"
                  value={option.value}
                  checked={mode === option.value}
                  onChange={() => update("mode", option.value)}
                />
                <span className={styles.modeBody}>
                  <span className={styles.modeHead}>
                    <strong>{option.label}</strong>
                    <span className={styles.price}>{option.price}</span>
                  </span>
                  <span className={styles.description}>{option.description}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {variant === "default" ? (
          <form
            className={styles.leagueField}
            onSubmit={(event) => {
              event.preventDefault();
              void connectLeague();
            }}
          >
            <label>
              <span>{copy.leagueId}</span>
              <div className={styles.leagueRow}>
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder={copy.leaguePlaceholder}
                  value={leagueInput}
                  onChange={(event) => {
                    setLeagueInput(event.target.value);
                    setLeagueState({ kind: "idle" });
                  }}
                />
                <button type="submit" disabled={leagueState.kind === "checking"}>
                  {copy.leagueConnect}
                </button>
              </div>
            </label>
            {leagueState.kind === "invalid" ? (
              <small role="alert">{copy.leagueInvalid}</small>
            ) : leagueState.kind === "unavailable" ? (
              <small role="alert">{copy.leagueUnavailable}</small>
            ) : leagueState.kind === "mismatch" ? (
              <small role="alert">{copy.leagueMismatch(leagueState.publishedId)}</small>
            ) : (
              <small>{copy.leagueHelp}</small>
            )}
          </form>
        ) : null}
      </div>

      {competitive ? (
        <div className={styles.diagnostic} role="note">
          <Badge tone="warn">{copy.diagnostic}</Badge>
          <span>
            <strong>{copy.diagnosticTitle(windowSize)}</strong> {copy.diagnosticBody}
          </span>
        </div>
      ) : null}

      <p className={styles.sourceNote}>
        {copy.sourceBefore}
        <code>mode_price_list</code>
        {copy.sourceAfter(MODE_PRICE_FOLDS)}
      </p>
    </Card>
  );
}
