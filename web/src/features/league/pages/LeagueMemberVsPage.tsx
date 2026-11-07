import { useState } from "react";
import { Link, useParams } from "react-router";

import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { memberAddress } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../dataErrors";
import type { SuggestionHistory, WeekReview } from "../history/historyData";
import { useSuggestionHistory } from "../queries";
import { useLeague, useLeagueId } from "../useLeague";
import styles from "./LeagueMemberVsPage.module.css";
import { breakdown, movesOf, otherPlans, plainPlan } from "./vsBreakdown";
import { DifferenceBars, NetBars, WeekStrip } from "./VsCharts";

/**
 * VS SQUADOPT: one gameweek at a time, in detail. What the member would have scored with
 * SquadOpt's plan against what they scored; what the plan said (moves, captain, chip, and
 * each other plan recorded that week) beside what the member did; where the difference came
 * from (captain, transfers, hits, the rest of the squad); and SquadOpt's squad with every
 * player's points. The latest settled week opens first; a selector moves between weeks. The
 * owner asked for this page to analyse, so it is the one page that says things in sentences.
 */
export function LeagueMemberVsPage() {
  const { messages } = useLanguage();
  const { league } = useLeague();
  const copy = messages.suggestionHistory;
  const parameter = useParams().entryId ?? "";
  const entryId = Number(parameter);
  const valid = /^[1-9]\d*$/.test(parameter) && Number.isSafeInteger(entryId);
  const query = useSuggestionHistory(entryId, valid);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (query.isPending) return <EmptyState title={messages.common.loading} />;
  if (query.isError) {
    const missing = query.error instanceof LeagueDataMissing;
    return (
      <EmptyState page title={missing ? copy.empty : copy.unreadable}>
        {missing ? null : (
          <button type="button" onClick={() => void query.refetch()}>
            {copy.retry}
          </button>
        )}
        <p>
          <Link to={memberAddress(league.leagueId, entryId)}>{copy.back}</Link>
        </p>
      </EmptyState>
    );
  }
  return <LeagueMemberVsView key={entryId} history={query.data} />;
}

/** A week both sides scored: the only kind the comparison can draw. */
function comparable(week: WeekReview): boolean {
  return (
    week.status === "available" &&
    week.suggested !== null &&
    week.actual !== null &&
    week.net_difference !== null
  );
}

export function LeagueMemberVsView({ history }: { history: SuggestionHistory }) {
  const { messages, locale } = useLanguage();
  const leagueId = useLeagueId();
  const copy = messages.vsSquadopt;
  const { entry_id: entryId, weeks } = history.payload;
  const compared = weeks.filter(comparable).sort((a, b) => b.gameweek - a.gameweek);
  const [chosen, setChosen] = useState<number | null>(null);
  const week = compared.find((item) => item.gameweek === chosen) ?? compared[0] ?? null;
  const fmt = (value: number | null | undefined) =>
    value == null ? "—" : points(value, Number.isInteger(value) ? 0 : 1, locale);
  const signed = (value: number | null) =>
    value === null ? "—" : signedPoints(value, Number.isInteger(value) ? 0 : 1, locale);
  return (
    <div className={styles.page}>
      <header>
        <Link to={memberAddress(leagueId, entryId)}>{messages.suggestionHistory.back}</Link>
        <h1>{copy.title}</h1>
      </header>
      {week === null ? (
        <EmptyState title={messages.suggestionHistory.empty} />
      ) : (
        <>
          <WeekStrip
            weeks={compared.map((item) => ({
              gameweek: item.gameweek,
              difference: item.net_difference!,
            }))}
            chosen={week.gameweek}
            onSelect={setChosen}
            label={messages.suggestionHistory.week}
            weekName={messages.suggestionHistory.gameweek}
            format={(value) => signed(value)}
          />
          <WeekAnalysis week={week} fmt={fmt} signed={signed} />
        </>
      )}
    </div>
  );
}

function WeekAnalysis({
  week,
  fmt,
  signed,
}: {
  week: WeekReview;
  fmt: (value: number | null | undefined) => string;
  signed: (value: number | null) => string;
}) {
  const { messages } = useLanguage();
  const copy = messages.vsSquadopt;
  const history = messages.suggestionHistory;
  const suggested = week.suggested!;
  const actual = week.actual!;
  const detail = actual.details ?? null;
  const plan = plainPlan(week);
  const moves = movesOf(plan);
  const byName = new Map(week.players.map((player) => [player.name, player]));
  const captain = week.players.find((player) => player.captain) ?? null;
  const parts = breakdown(week);
  const favoursSystem = week.net_difference! >= 0;
  const chipWord =
    suggested.chip === "3xc"
      ? history.triple
      : suggested.chip
        ? history[suggested.chip]
        : history.noChip;
  const starters = week.players.filter((player) => player.role === "starter");
  const bench = week.players.filter((player) => player.role === "bench");
  return (
    <section
      className={styles.week}
      aria-labelledby={`vs-week-${week.gameweek}`}
      data-testid="vs-week"
    >
      <h2 id={`vs-week-${week.gameweek}`}>{history.gameweek(week.gameweek)}</h2>
      <figure className={styles.figure}>
        <NetBars
          suggested={suggested.net_points}
          actual={actual.net_points}
          labels={{ squadopt: copy.squadopt, you: copy.you }}
          format={(value) => fmt(value)}
        />
        <figcaption>
          <p className={styles.headline} data-testid="vs-headline">
            {favoursSystem
              ? copy.wouldHave(fmt(suggested.net_points), fmt(actual.net_points))
              : copy.youBeat(fmt(actual.net_points), fmt(suggested.net_points))}
          </p>
          <p className={styles.difference}>
            {copy.difference}: <strong>{signed(week.net_difference)}</strong>{" "}
            <span className={styles.favour}>
              {favoursSystem ? copy.favoursSquadopt : copy.favoursYou}
            </span>
          </p>
        </figcaption>
      </figure>

      <div className={styles.sides}>
        <Card title={copy.said}>
          <dl className={styles.facts}>
            <dt>{copy.transfers}</dt>
            <dd>
              {moves.length === 0 ? (
                copy.none
              ) : (
                <ul className={styles.moves}>
                  {moves.map((move, index) => (
                    <li key={index}>
                      {move.out} → <strong>{move.in}</strong>
                      <span className={styles.movePoints}>
                        {copy.pointsOf(fmt(byName.get(move.in)?.realized_points ?? null))}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </dd>
            <dt>{copy.captain}</dt>
            <dd>
              {captain === null ? (
                "—"
              ) : (
                <>
                  <strong>{captain.name}</strong>
                  <span className={styles.movePoints}>
                    {copy.countedOf(fmt(captain.realized_points), fmt(captain.counted_points))}
                  </span>
                </>
              )}
            </dd>
            <dt>{copy.chip}</dt>
            <dd>{chipWord}</dd>
            <dt>{copy.hits}</dt>
            <dd>{fmt(suggested.transfer_hit_points)}</dd>
            <dt>{copy.net}</dt>
            <dd className={styles.net}>{fmt(suggested.net_points)}</dd>
          </dl>
          {otherPlans(week).length > 0 ? (
            <div className={styles.otherPlans}>
              <h3>{copy.otherPlans}</h3>
              <ul>
                {otherPlans(week).map((row) => (
                  <li key={row.published_path}>
                    <strong>{copy.planName(row.strategy, row.window)}</strong>
                    {": "}
                    {copy.planSaid(
                      movesOf(row).map((move) => `${move.out} → ${move.in}`),
                      row.captain,
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>

        <Card title={copy.did}>
          {detail === null ? <p className={styles.muted}>{copy.noDetails}</p> : null}
          <dl className={styles.facts}>
            {detail !== null ? (
              <>
                <dt>{copy.transfers}</dt>
                <dd>
                  {detail.transfers.length === 0 ? (
                    copy.none
                  ) : (
                    <ul className={styles.moves}>
                      {detail.transfers.map((move, index) => (
                        <li key={index}>
                          {move.player_out} → <strong>{move.player_in.name}</strong>
                          <span className={styles.movePoints}>
                            {copy.pointsOf(fmt(move.player_in.points))}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
                <dt>{copy.captain}</dt>
                <dd>
                  <strong>{detail.captain.name}</strong>
                  <span className={styles.movePoints}>
                    {copy.countedOf(fmt(detail.captain.points), fmt(detail.captain.counted_points))}
                  </span>
                </dd>
              </>
            ) : null}
            <dt>{copy.hits}</dt>
            <dd>{fmt(actual.transfer_hit_points)}</dd>
            <dt>{copy.net}</dt>
            <dd className={styles.net}>{fmt(actual.net_points)}</dd>
          </dl>
        </Card>
      </div>

      {parts !== null ? (
        <Card title={copy.why}>
          <DifferenceBars
            parts={parts}
            labels={{
              captain: copy.captain,
              transfers: copy.transfers,
              hits: copy.hits,
              lineup: copy.lineup,
            }}
            format={(value) => signed(value)}
          />
          <table className={`${styles.breakdown} visually-hidden`} data-testid="vs-breakdown">
            <tbody>
              {(
                [
                  [copy.captain, parts.captain],
                  [copy.transfers, parts.transfers],
                  [copy.hits, parts.hits],
                  [copy.lineup, parts.lineup],
                ] as const
              ).map(([label, value]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{signed(value)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">{copy.difference}</th>
                <td>{signed(week.net_difference)}</td>
              </tr>
            </tfoot>
          </table>
        </Card>
      ) : null}

      {week.players.length > 0 ? (
        <Card title={copy.squad}>
          <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.squad}>
            <table className={styles.squad}>
              <thead>
                <tr>
                  <th scope="col">{copy.player}</th>
                  <th scope="col">{copy.points}</th>
                  <th scope="col">{copy.counted}</th>
                </tr>
              </thead>
              <tbody>
                {[...starters, ...bench].map((player) => (
                  <tr key={player.player_id} data-role={player.role}>
                    <th scope="row">
                      {player.name}
                      {player.captain ? <span className={styles.badge}> C</span> : null}
                      {player.role === "bench" ? (
                        <span className={styles.benchWord}> {copy.bench}</span>
                      ) : null}
                    </th>
                    <td>{fmt(player.realized_points)}</td>
                    <td>{fmt(player.counted_points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </section>
  );
}
