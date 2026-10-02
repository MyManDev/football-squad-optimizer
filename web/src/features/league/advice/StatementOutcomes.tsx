import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import { isInjurySourceInstant } from "./officialInjuryFacts";
import styles from "../pages/LeagueMemberPage.module.css";

const REASONS: Record<string, [string, string]> = {
  explicit_evidence: [
    "Açık yokluk haberi uygulandı.",
    "The explicit absence statement was applied.",
  ],
  explicit_full_match_restriction: [
    "Tam maç süresi kısıtı uygulandı.",
    "The full-match minute restriction was applied.",
  ],
  publication_unverified: [
    "Kaynak yayın zamanı doğrulanamadı.",
    "The source publication time was not verified.",
  ],
  upcoming_league_scope_unverified: [
    "Haberin bu lig maçına ait olduğu doğrulanamadı.",
    "The statement could not be tied to this league fixture.",
  ],
  source_span_unresolved: [
    "Alıntı kaynak metinde doğrulanamadı.",
    "The quote could not be verified in the source text.",
  ],
  source_documents_unverified: [
    "Kaynak belgeler doğrulanamadı.",
    "The source documents were not verified.",
  ],
  categorical_statement_has_no_probability: [
    "Nitel ifade tek başına sayısal değişiklik için yeterli değil.",
    "The qualitative statement alone cannot supply a numerical adjustment.",
  ],
  conflicting_sources: [
    "Çelişen açıklamalar nedeniyle uygulanmadı.",
    "Conflicting statements prevented an update.",
  ],
  duplicate_evidence_or_source: [
    "Aynı kaynağın tekrarı birlikte uygulanmadı.",
    "Duplicate source evidence was not applied together.",
  ],
  ambiguous_fixture_scope: ["Hangi maça ait olduğu belirsiz.", "The target fixture is ambiguous."],
  missing_components: [
    "Gerekli maç bileşenleri bulunmuyor.",
    "Required fixture components are missing.",
  ],
  invalid_source_timing: [
    "Haber zamanı bu karara uygun değil.",
    "The statement timing is not valid for this decision.",
  ],
  future_evidence: [
    "Karardan sonraki bilgi kullanılmadı.",
    "Information arriving after the decision was not used.",
  ],
  expired_evidence: ["Haberin geçerlilik süresi dolmuş.", "The statement has expired."],
  outside_projection: [
    "Oyuncu bu tahmin kapsamında değil.",
    "The player is outside this forecast.",
  ],
  unsupported_contract: [
    "Bu tahmin haberin gerektirdiği bileşenleri taşımıyor.",
    "The forecast lacks the components required by this statement.",
  ],
  zero_prior_without_conditional_mean: [
    "Sıfır tahmini geri kuracak koşullu temel bulunmuyor.",
    "No conditional baseline is available to restore a zero forecast.",
  ],
};
function safeSource(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? value : null;
  } catch {
    return null;
  }
}
export function StatementOutcomes({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const rows = view.participation_evidence?.statement_outcomes;
  if (!rows?.length) return null;
  const tr = language === "tr";
  const names = new Map(view.official_information?.players.map((p) => [p.player_id, p.name]) ?? []);
  for (const player of [...(view.starting_xi ?? []), ...(view.bench ?? [])])
    names.set(player.player_id, player.name);
  return (
    <div data-testid="statement-outcomes">
      <h4>{tr ? "Oyuncu bazında haber etkisi" : "News effect by player"}</h4>
      <ul className={styles.assumptionList}>
        {rows.map((row, i) => {
          const source = safeSource(row.source_url);
          const explanation =
            REASONS[row.reason]?.[tr ? 0 : 1] ??
            (row.applied
              ? tr
                ? "Doğrulanmış açıklama uygulandı."
                : "Verified statement applied."
              : tr
                ? "Bu açıklama gerekli koşulları sağlamadığı için tahmini değiştirmedi."
                : "This statement did not meet the requirements for changing the forecast.");
          // A player the answer does not name is said so; an id is not a name.
          const name =
            names.get(row.player_id) ?? (tr ? "Adı yayımlanmayan oyuncu" : "Unnamed player");
          return (
            <li key={row.player_id + ":" + i}>
              <strong>{name}</strong> ·{" "}
              {row.applied ? (tr ? "Uygulandı" : "Applied") : tr ? "Uygulanmadı" : "Not applied"}
              <p>{explanation}</p>
              {/* The source's own publication instant, read strictly: a day alone is not an
                  instant and is not shown as one. */}
              {isInjurySourceInstant(row.source_published_at) && (
                <>
                  {tr ? "Kaynak yayın zamanı" : "Source published"}:{" "}
                  <time dateTime={row.source_published_at}>
                    {utcShort(row.source_published_at, locale)}
                  </time>
                </>
              )}
              {source && (
                <>
                  {" "}
                  ·{" "}
                  <a
                    href={source}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={tr ? `Kaynak: ${name}` : `Source: ${name}`}
                  >
                    {tr ? "Kaynak" : "Source"}
                  </a>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
