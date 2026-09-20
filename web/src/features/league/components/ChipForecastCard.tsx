import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { readChipForecast } from "../advice/chipForecast";
import { CHIP_FORECAST_COPY } from "../advice/chipForecastCopy";
import type { EntrySquad } from "../types";

export function ChipForecastCard({
  published,
  computed,
  squad,
}: {
  published?: unknown;
  computed?: unknown;
  squad: EntrySquad;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = CHIP_FORECAST_COPY[language];
  const readings = [
    { label: copy.published, value: readChipForecast(published, squad) },
    { label: copy.computed, value: readChipForecast(computed, squad) },
  ].filter((reading) => reading.value.kind !== "absent");
  if (!readings.length) return null;
  const format = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  return (
    <Card title={copy.title}>
      {readings.length === 2 && <p>{copy.separate}</p>}
      {readings.map(({ label, value }) => (
        <section key={label} aria-label={label}>
          <h3>{label}</h3>
          {value.kind === "refused" ? (
            <p>
              {copy.calendarNull} {copy.unavailable}{" "}
              {copy.reasons[value.reason as keyof typeof copy.reasons] ??
                copy.reasons.forecast_unreadable}
            </p>
          ) : value.kind === "ready" ? (
            <>
              <p>
                {value.calendarRange ? (
                  <>
                    {value.calendarHasStructure ? copy.calendarTrue : copy.calendarFalse}:{" "}
                    {value.calendarRange.first_gameweek} to {value.calendarRange.last_gameweek}.
                  </>
                ) : (
                  copy.calendarEmpty
                )}
              </p>
              {value.document.chips.length === 0 && <p>{copy.noChips}</p>}
              {value.document.chips.map((row) => {
                const relevant =
                  row.name === "bboost" ? squad.bench : [...squad.starting_xi, ...squad.bench];
                const noEstimate = relevant.every((p) =>
                  value.document.players_without_fixture_this_week.includes(p.player_id),
                );
                return (
                  <article key={row.name}>
                    <h4>{messages.leagueMembers.chipNames[row.name]}</h4>
                    <p>
                      <strong>
                        {row.verdict === "play_now"
                          ? copy.play
                          : row.verdict === "hold"
                            ? copy.hold
                            : copy.unknown}
                      </strong>
                    </p>
                    <p>
                      {copy.gain}:{" "}
                      {row.gain_this_week === null
                        ? copy.unknown
                        : format.format(row.gain_this_week)}{" "}
                      · {copy.threshold}: {format.format(row.threshold_this_week)}
                    </p>
                    {row.hold_reason === "reserved_for_structured_gameweek" && (
                      <p>{copy.reserved}</p>
                    )}
                    {row.points_at_gameweek ? (
                      <p>
                        {copy.later} {row.points_at_gameweek.gameweek}: {copy.laterGain}{" "}
                        {format.format(row.points_at_gameweek.estimated_gain)} · {copy.threshold}:{" "}
                        {format.format(row.points_at_gameweek.threshold)}. {copy.calendar}
                      </p>
                    ) : row.name === "freehit" || row.name === "wildcard" ? (
                      <p>{copy.whole}</p>
                    ) : row.verdict !== "play_now" ? (
                      <p>{noEstimate ? copy.noEstimate : copy.noLater}</p>
                    ) : null}
                    {row.structured_gameweeks !== null && (
                      <>
                        <p>{row.structured_gameweeks.length ? copy.structure : copy.noStructure}</p>
                        <ul>
                          {row.structured_gameweeks.map((week) => (
                            <li key={week.gameweek}>
                              {messages.common.gameweek(week.gameweek)}: {week.clubs_doubling}{" "}
                              {copy.doubling}, {week.clubs_blank} {copy.blank}
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                  </article>
                );
              })}
            </>
          ) : null}
        </section>
      ))}
      <p>{copy.calendar}</p>
      <p>{copy.squad}</p>
      <p>{copy.evidence}</p>
      <p>{copy.limits}</p>
      <p>{copy.action}</p>
    </Card>
  );
}
