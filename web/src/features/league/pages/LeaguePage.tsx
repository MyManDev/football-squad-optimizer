import { useLanguage } from "../../../i18n/context";
import { ScoreboardSection } from "../components/ScoreboardCard";
import { useLeagueScoreboard } from "../queries";
import styles from "./LeaguePage.module.css";

export function LeaguePage() {
  const { messages } = useLanguage();
  const copy = messages.league;
  // The read the table below makes, so the season costs no second one.
  const season = useLeagueScoreboard().data?.payload.season;
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          {season ? (
            <div className={styles.kicker}>
              {copy.season} {season}
            </div>
          ) : null}
          <h1 className={styles.title}>{copy.title}</h1>
        </div>
      </header>

      <ScoreboardSection />
    </div>
  );
}
