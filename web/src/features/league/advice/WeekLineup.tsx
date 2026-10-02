import { useLanguage } from "../../../i18n/context";
import type { AdviceLineup, AdvicePlayer } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "Bu haftanın ilk 11’i ve yedekleri",
    starters: "İlk 11",
    captain: "Kaptan",
    vice: "Yardımcı kaptan",
    bench: "Yedek sırası",
  },
  en: {
    title: "This week's starting eleven and bench",
    starters: "Starting eleven",
    captain: "Captain",
    vice: "Vice-captain",
    bench: "Bench order",
  },
};

export function WeekLineup({
  lineup,
  gameweek,
}: {
  lineup: AdviceLineup<AdvicePlayer | string>;
  gameweek: number;
}) {
  const { language, messages } = useLanguage();
  const copy = COPY[language];
  const name = (player: AdvicePlayer | string) =>
    typeof player === "string" ? player : player.name;
  return (
    <details className={styles.muted} data-testid={`week-lineup-${gameweek}`}>
      <summary>
        {messages.common.gameweekShort(gameweek)} · {copy.title}
      </summary>
      <p>
        {copy.captain}: {name(lineup.captain)} · {copy.vice}: {name(lineup.vice_captain)}
      </p>
      <p>
        {copy.starters}: {lineup.starting_xi.map(name).join(", ")}
      </p>
      <p>
        {copy.bench}: {lineup.bench.map(name).join(" → ")}
      </p>
    </details>
  );
}
