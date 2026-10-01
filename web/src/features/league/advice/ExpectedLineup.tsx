import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "Beklenen puan nasıl hesaplandı?",
    explanation:
      "İlk 11, oynayamayanların yerine girebilen yedekler ve kaptan oynamazsa yardımcı kaptana geçen ek puan birlikte hesaplanır. Yedeklere sabit bir puan payı eklenmez.",
    starting_points: "İlk 11",
    autosub_points: "Otomatik değişikliklerden gelen puan",
    captain_bonus_points: "Kaptanın ek puanı",
    vice_bonus_points: "Kaptan oynamazsa yardımcısının ek puanı",
    bench_boost_points: "Yedek Gücü puanı",
    hits: "Transfer cezası",
    net: "Ceza sonrası beklenen puan",
    assumptions: "Oynama varsayımları",
    unknown: "Bu tahmin ek oynama varsayımlarına dayanır; gerçekleşecek puan değildir.",
    rules: {
      independent_player_week_appearances:
        "Oyuncuların bu hafta oynayıp oynamaması birbirinden bağımsız kabul edilir. Birlikte dinlendirilme veya aynı habere bağlı değişimler modellenmez.",
      unconditional_weekly_points_already_include_appearance:
        "Oyuncu puanları sahaya çıkmayı zaten hesaba katar; aynı etki puana ikinci kez uygulanmaz.",
      conditional_player_points_unaffected_by_other_appearances:
        "Bir oyuncunun sahaya çıktığında beklenen puanı, takım arkadaşları veya rakipleri oynamadığında değişmez kabul edilir.",
      any_positive_gameweek_minutes_including_cameos_block_autosubs:
        "Kısa süre de olsa oynayan bir oyuncunun yerine yedek girmez.",
      no_card_only_participation_outside_the_appearance_model:
        "Hiç süre almadan görülen kartların otomatik değişikliğe etkisi bu tahminde yer almaz.",
      double_gameweek_appearance_probability_is_supplied_by_the_caller:
        "Bir haftada birden fazla maçı olan oyuncu, o haftaki maçlardan en az birinde süre alırsa oynamış sayılır.",
    },
  },
  en: {
    title: "How are expected points calculated?",
    explanation:
      "The starting eleven, eligible automatic substitutes and the vice-captain bonus when the captain does not play are scored together. No fixed share of bench points is added.",
    starting_points: "Starting eleven",
    autosub_points: "Automatic substitute points",
    captain_bonus_points: "Captain bonus",
    vice_bonus_points: "Vice-captain bonus when the captain does not play",
    bench_boost_points: "Bench Boost points",
    hits: "Transfer hits",
    net: "Expected points after hits",
    assumptions: "Playing assumptions",
    unknown: "This forecast uses additional playing assumptions; it is not a realized score.",
    rules: {
      independent_player_week_appearances:
        "Whether each player appears this week is treated as independent. Shared rotation or news affecting several players is not modeled.",
      unconditional_weekly_points_already_include_appearance:
        "Player points already account for participation; the same effect is not applied to their points a second time.",
      conditional_player_points_unaffected_by_other_appearances:
        "A player's expected points when they appear are assumed unchanged when teammates or opponents do not play.",
      any_positive_gameweek_minutes_including_cameos_block_autosubs:
        "Even a brief appearance prevents an automatic substitute from replacing that player.",
      no_card_only_participation_outside_the_appearance_model:
        "The effect of a card received without playing any minutes on automatic substitutions is not included in this forecast.",
      double_gameweek_appearance_probability_is_supplied_by_the_caller:
        "A player with several matches in one gameweek counts as appearing if they play in at least one of those matches.",
    },
  },
};

export function ExpectedLineup({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const expectation = view.lineup_expectation;
  if (!expectation) return null;
  const copy = COPY[language];
  const terms = [
    "starting_points",
    "autosub_points",
    "captain_bonus_points",
    "vice_bonus_points",
    "bench_boost_points",
  ] as const;
  const assumptions = [
    ...new Set(
      expectation.assumptions.map((rule) =>
        Object.hasOwn(copy.rules, rule)
          ? copy.rules[rule as keyof typeof copy.rules]
          : copy.unknown,
      ),
    ),
  ];
  return (
    <section
      className={styles.adviceSection}
      aria-label={copy.title}
      data-testid="lineup-expectation"
    >
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      <p className={styles.muted}>{copy.explanation}</p>
      <ul>
        {terms.map((term) => (
          <li key={term}>
            {copy[term]}: <strong className="num">{points(expectation[term], 1, locale)}</strong>
          </li>
        ))}
        <li>
          {copy.hits}:{" "}
          <span className="num">{points(view.transfer_hit_points ?? 0, 1, locale)}</span>
        </li>
      </ul>
      <p>
        {copy.net}:{" "}
        <strong className="num">{points(expectation.expected_net_points, 1, locale)}</strong>
      </p>
      <details>
        <summary>{copy.assumptions}</summary>
        <ul>
          {assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
