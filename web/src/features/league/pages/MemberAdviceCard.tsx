import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints } from "../../../lib/format";
import { comparedRivalPlayers } from "../advice/rivalPlayers";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import type {
  AdviceMove,
  AdvicePlayer,
  EntryAdvice,
  EntrySquad,
  EntryView,
  LeagueViewEnvelope,
} from "../types";
import type { AdviceIssue, ShownAdvice } from "./memberPageTypes";
import styles from "./LeagueMemberPage.module.css";

/**
 * Why no advice is shown, in the two states the page can tell apart. A combination the
 * producer never solved is a normal outcome; a document that failed to load is a fault,
 * and saying "not published yet" for it would tell the reader to wait for a publish that
 * already happened — on a page whose squad, read from the same build, is above it.
 */
export function MissingAdviceCard({
  issue,
  canCompute,
  reason,
  onRetry,
}: {
  issue: AdviceIssue;
  canCompute: boolean;
  reason?: string | null;
  onRetry?: () => void;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const issueCopy =
    issue === "not-computed"
      ? [copy.adviceNotComputed, copy.adviceNotComputedBody]
      : issue === "unavailable"
        ? [copy.adviceUnreadable, copy.adviceUnreadableBody]
        : [copy.publicationStates[issue].title, copy.publicationStates[issue].body];
  return (
    <Card title={copy.advice}>
      <p className={styles.honesty}>
        <strong>{issueCopy[0]}</strong>
      </p>
      <p className={styles.muted}>{issueCopy[1]}</p>
      {reason ? (
        <p className={styles.muted}>
          {Object.hasOwn(copy.publicationReasons, reason)
            ? copy.publicationReasons[reason]
            : copy.publicationReasonUnknown}
        </p>
      ) : null}
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          {copy.retryPublishedRead}
        </button>
      ) : null}
      {canCompute ? <p className={styles.muted}>{copy.adviceRequestHint}</p> : null}
    </Card>
  );
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function hasPublishedPlan(view: EntryAdvice): boolean {
  return (
    (view.solver_status === "OPTIMAL" || view.solver_status === "FEASIBLE") &&
    view.starting_xi?.length === 11 &&
    view.bench?.length === 4 &&
    view.captain != null &&
    view.vice_captain != null
  );
}

export function AdviceCard({
  shown,
  members = [],
  squad,
  rivalSquad,
}: {
  shown: ShownAdvice;
  members?: EntryView[];
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { envelope, origin } = shown;
  const view = envelope.payload;
  const basisWeek = /^pre_free_hit_gw(\d{2})$/.exec(squad.payload.squad_basis ?? "")?.[1];
  const rival =
    view.rival_entry_id === undefined
      ? null
      : (members.find(
          (member) => member.member_kind === "human" && member.entry_id === view.rival_entry_id,
        ) ?? null);
  const rivalName = rival ? (rival.team_name ?? rival.manager_name ?? null) : null;
  // A price tag is a difference between two solved plans. It is the cost itself only
  // where both proofs finished; where one did not, the producer publishes the bound it
  // measured as `expected_points_cost_ceiling` and this page states that — the most the
  // strategy can cost — instead of a figure it cannot stand behind. A document that is
  // unproven and carries no ceiling has no honest figure to print, so it prints none;
  // and a price below zero is a giveaway no constrained plan can hand out, so no
  // producer's number is rendered as one.
  const unproven = view.solver_status === "FEASIBLE" || view.control_solver_status === "FEASIBLE";
  const priceCeiling = view.expected_points_cost_ceiling;
  const price = unproven ? priceCeiling : (priceCeiling ?? view.expected_points_cost);
  const showsPrice = view.mode !== "saf-puan" && finiteNumber(price) && price >= 0;
  const alternative = view.alternative_plan;
  const alternativePrice = unproven
    ? alternative?.expected_points_cost_ceiling
    : (alternative?.expected_points_cost_ceiling ?? alternative?.expected_points_cost);
  return (
    <Card
      title={copy.advice}
      aside={
        <>
          {origin === "computed" ? <Badge tone="good">{copy.adviceComputedBadge}</Badge> : null}{" "}
          <ExampleDataBadge sourceKind={envelope.source_kind} />
        </>
      }
    >
      {origin === "published-while-computing" ? (
        <p className={styles.honesty}>{copy.advicePublishedWhileComputing}</p>
      ) : null}
      {origin === "baseline-while-computing" ? (
        <p className={styles.honesty}>{copy.adviceBaselineWhileComputing}</p>
      ) : null}
      <p className={styles.honesty}>{copy.honestyRule}</p>
      <p className={styles.honesty}>{copy.independentAdviceRule}</p>
      {basisWeek ? (
        <p className={styles.honesty}>{copy.freeHitSquadBasis(Number(basisWeek))}</p>
      ) : null}
      {view.solver_status === "FEASIBLE" ? (
        <p className={styles.honesty}>
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
          {finiteNumber(view.optimality_gap)
            ? copy.unprovenPlanBody(points(view.optimality_gap, 1, locale))
            : copy.unprovenPlanGapUnknown}
        </p>
      ) : null}
      {showsPrice && price != null ? (
        <p className={styles.planCost}>
          <strong className="num">
            {unproven
              ? copy.planCostAtMost(points(price, 1, locale))
              : copy.planCost(points(price, 1, locale))}
          </strong>
          {(rivalName ?? view.rival_label) ? (
            <span> · {copy.planRival(rivalName ?? String(view.rival_label))}</span>
          ) : null}
        </p>
      ) : null}
      {view.control_solver_status === "FEASIBLE" ? (
        <p className={styles.honesty}>
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
          {finiteNumber(view.control_optimality_gap)
            ? copy.controlUnprovenBody(points(view.control_optimality_gap, 1, locale))
            : copy.controlGapUnknown}
        </p>
      ) : null}
      {finiteNumber(view.overlap_count) && finiteNumber(view.expected_gap_vs_rival) ? (
        <p className={styles.muted}>
          {copy.overlapLine(view.overlap_count)} ·{" "}
          {copy.gapLine(signedPoints(view.expected_gap_vs_rival, 1, locale))}
          {view.captain_agreement ? ` · ${copy.captainShared}` : ""}
        </p>
      ) : null}
      {view.plan_kind && finiteNumber(view.transfer_cap) && finiteNumber(view.overlap_target) ? (
        <p className={styles.muted}>
          {view.plan_kind === "within_free_transfers"
            ? finiteNumber(view.overlap_applied)
              ? copy.planWithinFree(view.transfer_cap, view.overlap_target, view.overlap_applied)
              : copy.planWithinFreeUnknown(view.transfer_cap, view.overlap_target)
            : copy.planWithHits(view.transfer_cap, view.overlap_target)}
          {alternative &&
          finiteNumber(alternative.overlap_applied) &&
          finiteNumber(alternativePrice) &&
          alternativePrice >= 0
            ? ` ${
                alternative.kind === "with_hits"
                  ? (unproven ? copy.alternativeWithHitsAtMost : copy.alternativeWithHits)(
                      alternative.overlap_applied,
                      finiteNumber(alternative.transfer_hit_points)
                        ? points(alternative.transfer_hit_points, 0, locale)
                        : copy.hitPointsNotPublished,
                      points(alternativePrice, 1, locale),
                    )
                  : (unproven ? copy.alternativeWithinFreeAtMost : copy.alternativeWithinFree)(
                      alternative.overlap_applied,
                      points(alternativePrice, 1, locale),
                    )
              }`
            : ""}
        </p>
      ) : null}
      {view.moves.length === 0 ? (
        <p className={styles.muted}>{hasPublishedPlan(view) ? copy.noMove : copy.noPlanInRecord}</p>
      ) : (
        <>
          <div className={styles.moves}>
            {view.moves.map((move) => (
              <AdviceRow key={move.move_id} move={move} />
            ))}
          </div>
          {/* The week's hit charge, once, because the game charges the week and not any
              one move. Absent on documents published before the producer stated it. */}
          {view.transfer_hit_points != null ? (
            <p className={styles.muted}>
              {copy.weekTransferCost(points(view.transfer_hit_points, 1, locale))}
            </p>
          ) : null}
        </>
      )}
      <RivalPlayers advice={envelope} squad={squad} rivalSquad={rivalSquad} />
      <LineupSection view={view} />
      <WindowSection view={view} />
      <p className={styles.diagnostic}>{copy.diagnosticOnly}</p>
    </Card>
  );
}

function RivalPlayers({
  advice,
  squad,
  rivalSquad,
}: {
  advice: LeagueViewEnvelope<EntryAdvice>;
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
}) {
  const copy = useLanguage().messages.leagueMembers;
  if (advice.payload.rival_entry_id == null) return null;
  const comparison = comparedRivalPlayers(advice, squad, rivalSquad);
  return (
    <section className={styles.lineup} aria-label={copy.rivalPlayersTitle}>
      <h3 className={styles.lineupTitle}>{copy.rivalPlayersTitle}</h3>
      <p className={styles.honesty}>{copy.rivalPlayersBasis}</p>
      {comparison ? (
        <dl>
          {(["shared", "recommendedOnly", "rivalOnly"] as const).map((kind) => (
            <div key={kind}>
              <dt>{copy.rivalPlayerGroups[kind]}</dt>
              <dd>
                {comparison[kind].map((player) => player.name).join(", ") || copy.rivalPlayersNone}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className={styles.muted}>{copy.rivalPlayersUnavailable}</p>
      )}
    </section>
  );
}

/**
 * A three- or five-week window: what it assumes, in the producer's own sentences, and
 * one row per gameweek — transfers, hit points, chip, expected points. The moves and
 * the lineup above are the first week's; the rest of the window lives here. Rendered
 * only when the producer published it, so a one-week document shows nothing extra.
 */
function WindowSection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const weeks = view.plan_weeks;
  if (!weeks || weeks.length === 0) return null;
  const limits = view.stated_limits ?? [];
  const names = (players: AdvicePlayer[]) =>
    players.length === 0 ? "—" : players.map((player) => player.name).join(", ");
  const title = copy.windowTitle(weeks.length);
  return (
    <section className={styles.window} aria-label={title}>
      <h3 className={styles.lineupTitle}>{title}</h3>
      <p className={styles.honesty}>{copy.windowRule}</p>
      {limits.length > 0 ? (
        <>
          <h4 className={styles.lineupSub}>{copy.windowLimitsLabel}</h4>
          <ul className={styles.limits}>
            {limits.map((sentence) => (
              <li key={sentence}>
                {Object.hasOwn(copy.statedLimits, sentence)
                  ? copy.statedLimits[sentence]
                  : copy.statedLimitUnknown}
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <div className={styles.windowScroll}>
        <table className={styles.windowTable}>
          <thead>
            <tr>
              <th scope="col">{copy.windowWeek}</th>
              <th scope="col">{copy.in}</th>
              <th scope="col">{copy.out}</th>
              <th scope="col" className={styles.right}>
                {copy.windowHits}
              </th>
              <th scope="col">{copy.chipLabel}</th>
              <th scope="col" className={styles.right}>
                {copy.windowPoints}
              </th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((week) => (
              <tr key={week.gameweek}>
                <th scope="row" className="num">
                  {copy.windowWeekOf(week.gameweek)}
                </th>
                <td>{names(week.transfers_in)}</td>
                <td>{names(week.transfers_out)}</td>
                <td className={`${styles.right} num`}>
                  {points(week.transfer_hit_points, 0, locale)}
                </td>
                <td>{week.chip ? (copy.chipNames[week.chip] ?? week.chip) : "—"}</td>
                <td className={`${styles.right} num`}>{points(week.expected_points, 1, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * The rest of the decision: armband, chip, the eleven and the bench order. Rendered only
 * when the producer published them — a document from before the producer carried the
 * plan week, or a decision handed over without it, shows the moves alone.
 */
function LineupSection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { captain, vice_captain: vice, starting_xi: eleven, bench } = view;
  if (!captain || !vice || !eleven || !bench) return null;
  const chipName = view.chip ? (copy.chipNames[view.chip] ?? view.chip) : null;
  const mark = (player: AdvicePlayer) =>
    player.player_id === captain.player_id ? "C" : player.player_id === vice.player_id ? "V" : null;
  return (
    <section className={styles.lineup} aria-label={copy.lineupTitle}>
      <h3 className={styles.lineupTitle}>{copy.lineupTitle}</h3>
      <p className={styles.honesty}>{copy.lineupRule}</p>
      {finiteNumber(view.expected_own_points) ? (
        <p className={styles.planCost}>
          <strong className="num">
            {copy.expectedOwnPoints(points(view.expected_own_points, 1, locale))}
          </strong>
        </p>
      ) : null}
      <dl className={styles.armband}>
        <div>
          <dt>{copy.captainLabel}</dt>
          <dd>
            <strong>{captain.name}</strong>{" "}
            <span className={styles.muted}>
              {captain.team} · {captain.position}
            </span>
          </dd>
        </div>
        <div>
          <dt>{copy.viceCaptainLabel}</dt>
          <dd>
            <strong>{vice.name}</strong>{" "}
            <span className={styles.muted}>
              {vice.team} · {vice.position}
            </span>
          </dd>
        </div>
        <div>
          <dt>{copy.chipLabel}</dt>
          <dd>{chipName ? <Badge tone="good">{chipName}</Badge> : copy.chipNone}</dd>
        </div>
      </dl>
      <h4 className={styles.lineupSub}>{copy.startingXiLabel}</h4>
      <div className={styles.bench}>
        {eleven.map((player, index) => (
          <LineupRow key={player.player_id} player={player} order={index + 1} mark={mark(player)} />
        ))}
      </div>
      <h4 className={styles.lineupSub}>{copy.benchOrderLabel}</h4>
      <div className={styles.bench}>
        {bench.map((player, index) => (
          <LineupRow key={player.player_id} player={player} order={index + 1} mark={null} />
        ))}
      </div>
    </section>
  );
}

function LineupRow({
  player,
  order,
  mark,
}: {
  player: AdvicePlayer;
  order: number;
  mark: "C" | "V" | null;
}) {
  const { locale } = useLanguage();
  return (
    <div className={styles.benchRow}>
      <span className="num">{order}</span>
      <strong>
        {player.name}
        {mark ? (
          <>
            {" "}
            <Badge tone={mark === "C" ? "good" : "neutral"}>{mark}</Badge>
          </>
        ) : null}
      </strong>
      <span className={styles.muted}>
        {player.team} · {player.position}
      </span>
      <span className={`${styles.benchPoints} num`}>
        {player.expected_points != null ? `${points(player.expected_points, 1, locale)} xP` : ""}
      </span>
    </div>
  );
}

type MemberCopy = ReturnType<typeof useLanguage>["messages"]["leagueMembers"];

/** The caption under a move, keyed on the reason the producer stated for it. */
function reasonFor(copy: MemberCopy, code: AdviceMove["reason_code"]): string {
  if (code === "window_value") return copy.windowValueReason;
  if (code === "points_gain") return copy.pointsGainReason;
  return copy.modeTradeoffReason;
}

function AdviceRow({ move }: { move: AdviceMove }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <article className={styles.move}>
      <div className={styles.movePlayers}>
        <span>
          {copy.out}: <strong>{move.player_out?.name ?? "—"}</strong>
        </span>
        <span>
          {copy.in}: <strong>{move.player_in?.name ?? "—"}</strong>
        </span>
      </div>
      <div className={styles.moveNumbers}>
        <span>{copy.projectedGain(points(move.expected_points_delta, 1, locale))}</span>
      </div>
      <p className={styles.muted}>{reasonFor(copy, move.reason_code)}</p>
    </article>
  );
}
