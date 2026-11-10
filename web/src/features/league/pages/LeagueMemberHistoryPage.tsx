import { memberAddress } from "../../../lib/leagueAddresses";
import { useLeague, useLeagueId } from "../useLeague";
import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { recordUsage } from "../../../data/usage";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useShellLayout } from "../../../design/shell/layout";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { RowDetailsFigures, RowDetailsToggle } from "../components/RowDetails";
import { useOpenRows } from "../components/useOpenRows";
import { LeagueDataMissing } from "../dataErrors";
import type { SuggestionHistory, WeekReview } from "../history/historyData";
import styles from "./LeagueMemberHistoryPage.module.css";
import { summarizeHistory } from "../history/historySummary";
import { PersonalSeasonReport } from "../history/PersonalSeasonReport";
import { useSuggestionHistory } from "../queries";

export function LeagueMemberHistoryPage() {
  useEffect(() => recordUsage({ step: "tool" }), []);
  const { messages } = useLanguage();
  const { league } = useLeague();
  const leagueId = league.leagueId;
  const copy = messages.suggestionHistory;
  const parameter = useParams().entryId ?? "";
  const entryId = Number(parameter);
  const valid = /^[1-9]\d*$/.test(parameter) && Number.isSafeInteger(entryId);
  // The member page's latest-week card reads the same document under the same key.
  const query = useSuggestionHistory(entryId, valid);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (query.isPending) return <EmptyState title={messages.common.loading} />;
  if (query.isError) {
    const missing = query.error instanceof LeagueDataMissing;
    return (
      <EmptyState page title={missing ? copy.empty : copy.unreadable}>
        {missing ? (
          <p>{copy.emptyBody}</p>
        ) : (
          <button type="button" onClick={() => void query.refetch()}>
            {copy.retry}
          </button>
        )}
        <p>
          <Link to={memberAddress(leagueId, entryId)} className={styles.back}>
            {copy.back}
          </Link>
        </p>
      </EmptyState>
    );
  }
  return <LeagueMemberHistoryView key={entryId} history={query.data} />;
}

export function LeagueMemberHistoryView({ history }: { history: SuggestionHistory }) {
  const { messages } = useLanguage();
  const leagueId = useLeagueId();
  const copy = messages.suggestionHistory;
  const { entry_id: entryId, weeks } = history.payload;
  const [selected, setSelected] = useState<number | null>(null);
  const ordered = [...weeks].sort((a, b) => b.gameweek - a.gameweek);
  const week = ordered.find((item) => item.gameweek === selected);
  return (
    <div className={styles.page}>
      <header>
        <Link to={memberAddress(leagueId, entryId)} className={styles.back}>
          {copy.back}
        </Link>
        <h1>{copy.title}</h1>
      </header>
      <PersonalSeasonReport history={history} />
      {weeks.length === 0 ? (
        <EmptyState title={copy.empty}>
          <p>{copy.emptyBody}</p>
        </EmptyState>
      ) : (
        <>
          <label className={styles.selector}>
            {copy.week}
            <select
              value={week?.gameweek ?? "overview"}
              onChange={(event) =>
                setSelected(event.target.value === "overview" ? null : Number(event.target.value))
              }
            >
              <option value="overview">{copy.overview}</option>
              {ordered.map((item) => (
                <option key={item.gameweek} value={item.gameweek}>
                  {copy.gameweek(item.gameweek)}
                </option>
              ))}
            </select>
          </label>
          {week ? (
            <WeekResult week={week} />
          ) : (
            <HistoryOverview weeks={weeks} onSelect={setSelected} />
          )}
        </>
      )}
    </div>
  );
}

/**
 * On a phone the table keeps the week and the two net scores on the screen, with no sideways
 * scroll; each week's two differences fold out under its row, and the footer carries the
 * season's difference under its label.
 */
function HistoryOverview({
  weeks,
  onSelect,
}: {
  weeks: WeekReview[];
  onSelect: (week: number) => void;
}) {
  const { messages, locale } = useLanguage();
  const copy = messages.suggestionHistory;
  const summary = summarizeHistory(weeks);
  const format = (value: number | null | undefined) =>
    value == null ? "—" : points(value, 1, locale);
  const signed = (value: number | null) => (value === null ? "—" : signedPoints(value, 1, locale));
  const phone = useShellLayout() === "phone";
  const fold = useOpenRows();
  const details = messages.leagueMembers.storyDetail;
  return (
    <Card title={copy.overview}>
      <div className={styles.overviewScroll} tabIndex={0} role="region" aria-label={copy.overview}>
        <table className={styles.overviewTable}>
          <thead>
            <tr>
              {(phone
                ? [copy.week, copy.systemNet, copy.memberNet]
                : [copy.week, copy.systemNet, copy.memberNet, copy.weekDifference, copy.cumulative]
              ).map((label) => (
                <th key={label} scope="col">
                  {label}
                </th>
              ))}
              {phone ? (
                <th scope="col">
                  <span className="visually-hidden">{details}</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {summary.rows.map(({ week, cumulative }) => {
              const open = phone && fold.isOpen(week.gameweek);
              const detailsId = `history-week-${week.gameweek}-details`;
              const difference = signed(week.status === "available" ? week.net_difference : null);
              return (
                <Fragment key={week.gameweek}>
                  <tr>
                    <th scope="row">
                      <button
                        type="button"
                        className={styles.weekLink}
                        onClick={() => onSelect(week.gameweek)}
                        aria-label={`${messages.common.gameweekShort(week.gameweek)}, ${copy.gameweek(week.gameweek)}`}
                      >
                        {messages.common.gameweekShort(week.gameweek)}
                      </button>
                      {week.status === "unsettled" && (
                        <span className={styles.rowStatus}>{copy.unsettled}</span>
                      )}
                      {week.advice_source === "requested_server" && (
                        <span className={styles.rowStatus}>{copy.requested}</span>
                      )}
                    </th>
                    <td>
                      {format(week.status === "available" ? week.suggested?.net_points : null)}
                    </td>
                    <td>{format(week.status === "available" ? week.actual?.net_points : null)}</td>
                    {phone ? (
                      <td className={styles.detailsCell}>
                        <RowDetailsToggle
                          open={open}
                          controls={detailsId}
                          label={`${details}, ${copy.gameweek(week.gameweek)}`}
                          onToggle={() => fold.toggle(week.gameweek)}
                        />
                      </td>
                    ) : (
                      <>
                        <td>{difference}</td>
                        <td>{signed(cumulative)}</td>
                      </>
                    )}
                  </tr>
                  {open ? (
                    <tr id={detailsId} className={styles.detailRow}>
                      <td colSpan={4}>
                        <RowDetailsFigures
                          figures={[
                            { label: copy.weekDifference, value: difference },
                            { label: copy.cumulative, value: signed(cumulative) },
                          ]}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">
                {copy.total}
                {phone ? (
                  <span className={styles.rowStatus}>
                    {copy.difference}: {signed(summary.difference)}
                  </span>
                ) : null}
              </th>
              <td>{format(summary.suggested)}</td>
              <td>{format(summary.actual)}</td>
              {phone ? (
                <td />
              ) : (
                <>
                  <td>{signed(summary.difference)}</td>
                  <td>{signed(summary.difference)}</td>
                </>
              )}
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

function WeekResult({ week }: { week: WeekReview }) {
  const { messages, locale } = useLanguage();
  const copy = messages.suggestionHistory;
  const format = (value: number | null | undefined) =>
    value == null ? "—" : points(value, 1, locale);
  const { suggested, actual } = week;
  const chip =
    suggested?.chip === "3xc" ? copy.triple : suggested?.chip ? copy[suggested.chip] : copy.noChip;
  return (
    <>
      <Card title={copy.gameweek(week.gameweek)}>
        {week.advice_source === "requested_server" && (
          <span className={styles.rowStatus}>{copy.requested}</span>
        )}
        {week.status !== "available" || !suggested ? (
          <EmptyState title={week.status === "unsettled" ? copy.unsettled : copy.unavailable} />
        ) : (
          <>
            <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.title}>
              <table className={styles.scores}>
                <thead>
                  <tr>
                    <th scope="col">{copy.gameweek(week.gameweek)}</th>
                    <th scope="col">{copy.suggested}</th>
                    <th scope="col">{copy.actual}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">{copy.gross}</th>
                    <td>{format(suggested.gross_points)}</td>
                    <td>{format(actual?.gross_points)}</td>
                  </tr>
                  <tr>
                    <th scope="row">{copy.hits}</th>
                    <td>{format(suggested.transfer_hit_points)}</td>
                    <td>{format(actual?.transfer_hit_points)}</td>
                  </tr>
                  <tr>
                    <th scope="row">{copy.net}</th>
                    <td>
                      <strong>{format(suggested.net_points)}</strong>
                    </td>
                    <td>
                      <strong>{format(actual?.net_points)}</strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className={styles.difference}>
              {copy.difference}:{" "}
              <strong>
                {week.net_difference === null ? "—" : signedPoints(week.net_difference, 1, locale)}
              </strong>
            </p>
            <dl className={styles.facts}>
              <div>
                <dt>{copy.captainBonus}</dt>
                <dd>{format(suggested.captain_bonus_points)}</dd>
              </div>
              <div>
                <dt>{copy.autosubs}</dt>
                <dd>{format(suggested.autosub_points)}</dd>
              </div>
              <div>
                <dt>{copy.chip}</dt>
                <dd>{chip}</dd>
              </div>
            </dl>
          </>
        )}
      </Card>
      <SuggestedMove week={week} />
      {week.status === "available" && (
        <Card title={copy.players}>
          <div className={styles.tableWrap} tabIndex={0} role="region" aria-label={copy.players}>
            <table className={styles.players}>
              <thead>
                <tr>
                  {[copy.player, copy.role, copy.realized].map((label) => (
                    <th scope="col" key={label}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {week.players.map((player) => (
                  <tr key={player.player_id}>
                    <th scope="row">
                      {player.name}
                      <span className={styles.position}>{player.position}</span>
                    </th>
                    <td>
                      {player.role === "starter" ? copy.starter : copy.bench}
                      {player.captain
                        ? ` · ${copy.captain}`
                        : player.vice_captain
                          ? ` · ${copy.vice}`
                          : ""}
                      {(player.captain || player.vice_captain) && player.multiplier > 1
                        ? ` (x${player.multiplier})`
                        : ""}
                    </td>
                    <td>{format(player.realized_points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

/** The week's plain one-week plan: no rival, no Top 100 setting, no manager's word, no chip. */
function SuggestedMove({ week }: { week: WeekReview }) {
  const { messages } = useLanguage();
  const copy = messages.suggestionHistory;
  const plan = week.recorded_plans?.find(
    (row) =>
      row.strategy === "saf-puan" &&
      row.rival_entry_id === null &&
      row.top100_weight === undefined &&
      row.managers_word === undefined &&
      row.chip === null,
  );
  if (!plan) return null;
  const moves = plan.moves.filter((move) => move.player_out !== null && move.player_in !== null);
  return (
    <details className={styles.plan}>
      <summary>{copy.recordedPlans}</summary>
      <p>
        <strong>
          {messages.leagueMembers.strategies["saf-puan"].name},{" "}
          {messages.decision.week(plan.window)}
        </strong>
      </p>
      {plan.captain !== null && (
        <p>
          {copy.captain}: {plan.captain}
        </p>
      )}
      {plan.moves.length === 0 && <p>{copy.noRecordedMoves}</p>}
      {moves.length > 0 && (
        <ul>
          {moves.map((move, index) => (
            <li key={index}>
              {messages.leagueMembers.out}: {move.player_out}; {messages.leagueMembers.in}:{" "}
              {move.player_in}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
