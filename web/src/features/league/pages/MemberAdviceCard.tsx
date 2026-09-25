import { useId, type CSSProperties } from "react";

import { Badge } from "../../../design/components/Badge";
import { useLanguage } from "../../../i18n/context";
import { clubCodesFromFixtures, type ClubCodes } from "../../../lib/clubs";
import { figure, points, signedFigure, signedPoints, utcShort } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import { CHIP_COPY, chipLimit, chipRescores, type ChipCopy } from "../advice/chipCopy";
import { EVIDENCE_COPY, QUOTE_WITHHELD } from "../advice/evidenceCopy";
import { comparedRivalPlayers } from "../advice/rivalPlayers";
import { publishedPrice } from "../advice/publishedPrice";
import { TOP100_COPY, top100LimitWeight, variantLimit } from "../advice/top100Copy";
import { clubWeeks, nextThree } from "../clubFixtures";
import { ClubMark } from "../components/ClubMark";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { BoardArrow, CheckIcon } from "../components/memberIcons";
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
import board from "./MemberDecision.module.css";
import lineup from "./MemberLineup.module.css";

/**
 * Why no advice is shown, in the two states the page can tell apart. A combination the
 * producer never solved is a normal outcome; a document that failed to load is a fault,
 * and saying "not published yet" for it would tell the reader to wait for a publish that
 * already happened, on a page whose squad, read from the same build, is on the same page.
 * It stands where the substitution boards would, under the decision heading.
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
    <div className={board.missing}>
      <p className={board.missingTitle}>
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
        <p>
          <button type="button" className={board.retry} onClick={onRetry}>
            {copy.retryPublishedRead}
          </button>
        </p>
      ) : null}
      {canCompute ? <p className={styles.muted}>{copy.adviceRequestHint}</p> : null}
    </div>
  );
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Which squad the card says this advice stands on, in the three states it can tell apart. */
type SquadBasisNote = { kind: "week"; week: number } | { kind: "unconfirmed" } | null;

/**
 * A squad document carrying no basis is the genuinely empty case: it claims nothing, every
 * document published before the field is in it, and so the card says nothing. Two documents
 * naming different bases are not that case. Something was claimed and this page cannot
 * confirm it, and the rotation evidence contract keeps exactly that apart from silence with
 * its own `rotation_claim_unresolved` column, because folding it into "nothing was said"
 * asserts a silence that never happened. So the disagreement gets its own sentence here,
 * and that sentence names no week: a wrong week is worse than no week.
 */
function squadBasisNote(entryBasis?: string, adviceBasis?: string): SquadBasisNote {
  if (entryBasis === undefined) return null;
  if (adviceBasis !== undefined && adviceBasis !== entryBasis) return { kind: "unconfirmed" };
  const week = /^pre_free_hit_gw(\d{2})$/.exec(entryBasis)?.[1];
  return week === undefined ? null : { kind: "week", week: Number(week) };
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

/**
 * The basis every number on the board is stated on.
 *
 * A move's figure is a share of the plan's gain against holding, and only a document that
 * publishes that gain carries shares of it. A document from before the producer did carries
 * a different quantity on those rows, the raw difference between the two players' own
 * projections, so its numbers are not printed under this label. A Triple Captain or Bench
 * Boost week scores on its own basis, and the producer states the rows, the gain and the
 * lineup total on it; the sentences name that basis.
 */
function adviceBasis(view: EntryAdvice, chipCopy: ChipCopy) {
  const rowsAreShares = view.expected_gain_vs_hold !== undefined;
  const scoredChip = view.chip_strategy?.selected_chip ?? view.chip_choice?.chip;
  const chipBasis = scoredChip && chipRescores(scoredChip) ? chipCopy.basis[scoredChip] : null;
  return { rowsAreShares, chipBasis };
}

/**
 * The proof stamp beside the decision heading. KANITLANDI · OPTIMAL only for a plan the
 * solver proved (OPTIMAL); a plan it found without finishing the proof (FEASIBLE) keeps the
 * "proof incomplete" badge, and its gap sentence stands under the boards. Any other status
 * claims nothing.
 */
export function AdviceStamp({ shown }: { shown: ShownAdvice }) {
  const copy = useLanguage().messages.leagueMembers;
  const view = shown.envelope.payload;
  return (
    <div className={board.stamp}>
      <p className={board.stampTags}>
        {shown.origin === "computed" ? <Badge tone="good">{copy.adviceComputedBadge}</Badge> : null}
        <ExampleDataBadge sourceKind={shown.envelope.source_kind} />
      </p>
      {view.solver_status === "OPTIMAL" ? (
        <>
          <p className={board.stampBox} data-stamp="">
            <CheckIcon />
            {copy.stampOptimal}
          </p>
          <p className={board.stampCaption}>{copy.stampOptimalCaption}</p>
        </>
      ) : view.solver_status === "FEASIBLE" ? (
        <p className={`${board.stampTags} ${board.stampUnproven}`} data-stamp="">
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>
        </p>
      ) : null}
    </div>
  );
}

/**
 * The decision itself: one substitution board per move, the gain strip, the captain line,
 * and the sentences that change how the plan may be read (the proof, the price, the rival
 * bounds). The detail sections a switch adds and the lineup follow in `AdviceDetails`.
 */
export function AdviceDecision({
  shown,
  members = [],
  squad,
  fixtures = null,
}: {
  shown: ShownAdvice;
  members?: EntryView[];
  squad: LeagueViewEnvelope<EntrySquad>;
  fixtures?: FixturesPayload | null;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { envelope, origin } = shown;
  const view = envelope.payload;
  const basisNote = squadBasisNote(squad.payload.squad_basis, view.squad_basis);
  const rival =
    view.rival_entry_id === undefined
      ? null
      : (members.find(
          (member) => member.member_kind === "human" && member.entry_id === view.rival_entry_id,
        ) ?? null);
  const rivalName = rival ? (rival.team_name ?? rival.manager_name ?? null) : null;
  // A price tag is a difference between two solved plans. It is the cost itself only
  // where both proofs finished; where one did not, the producer publishes the bound it
  // measured as `expected_points_cost_ceiling` and this page states that (the most the
  // strategy can cost) instead of a figure it cannot stand behind. A document that is
  // unproven and carries no ceiling has no honest figure to print, so it prints none;
  // and a price below zero is a giveaway no constrained plan can hand out, so no
  // producer's number is rendered as one.
  const unproven = view.solver_status === "FEASIBLE" || view.control_solver_status === "FEASIBLE";
  const explainedUnproven =
    view.solver_status === "FEASIBLE" ||
    (view.control_solver_status === "FEASIBLE" && !view.chip_choice);
  // The pure-points plan has no price of its own; switched on, the manager's word does,
  // and it is priced against the same pure-points control a rival band is.
  const wordPriced = view.mode === "saf-puan" && view.evidence !== undefined;
  // A Top 100 weight is priced the same way, in base-model points against the plan at 0;
  // with the word on as well, the one number is the pair's.
  const top100Priced = view.top100 !== undefined;
  const strategyPriced = top100Priced && view.mode !== "saf-puan";
  const price = publishedPrice({
    strategy: view.mode,
    word: wordPriced,
    top100: top100Priced,
    unproven,
    expected_points_cost: view.expected_points_cost,
    expected_points_cost_ceiling: view.expected_points_cost_ceiling,
  });
  const evidenceCopy = EVIDENCE_COPY[language];
  const top100Copy = TOP100_COPY[language];
  const alternative = view.alternative_plan;
  const alternativePrice = unproven
    ? alternative?.expected_points_cost_ceiling
    : (alternative?.expected_points_cost_ceiling ?? alternative?.expected_points_cost);
  // A bound on the planner's objective covers the whole plan at once, so the copy has to
  // say how many gameweeks that is. A one-week document publishes no plan weeks.
  const planWeeks = view.plan_weeks?.length ?? 1;
  const chipCopy = CHIP_COPY[language];
  const { rowsAreShares, chipBasis } = adviceBasis(view, chipCopy);
  const codes = clubCodesFromFixtures(fixtures);
  const reasons = view.moves.map((move) => reasonFor(copy, language, move.reason_code));
  // Boards that share a caption say it once, under them; a caption that differs stays with
  // its own board.
  const sharedReason = reasons.every((reason) => reason === reasons[0]);
  return (
    <>
      {origin === "published-while-computing" ? (
        <p className={styles.honesty}>{copy.advicePublishedWhileComputing}</p>
      ) : null}
      {origin === "baseline-while-computing" ? (
        <p className={styles.honesty}>{copy.adviceBaselineWhileComputing}</p>
      ) : null}
      {view.moves.length === 0 ? (
        <p className={board.noMove}>{hasPublishedPlan(view) ? copy.noMove : copy.noPlanInRecord}</p>
      ) : (
        <div className={board.boards}>
          <div className={board.grid}>
            {view.moves.map((move, index) => (
              <div className={board.cell} key={move.move_id}>
                <SubstitutionBoard
                  move={move}
                  index={index}
                  count={view.moves.length}
                  measured={rowsAreShares}
                  codes={codes}
                  fixtures={fixtures}
                  season={view.season}
                  gameweek={view.gameweek}
                />
                {sharedReason ? null : <p className={board.reason}>{reasons[index]}</p>}
              </div>
            ))}
          </div>
          {sharedReason ? <p className={board.reason}>{reasons[0]}</p> : null}
        </div>
      )}
      <GainStrip view={view} squad={squad.payload} measured={rowsAreShares} chipBasis={chipBasis} />
      <CaptainLine view={view} codes={codes} />
      <div className={board.states}>
        {basisNote ? (
          <p className={styles.honesty}>
            {basisNote.kind === "week"
              ? copy.freeHitSquadBasis(basisNote.week)
              : copy.squadBasisUnconfirmed}
          </p>
        ) : null}
        {view.solver_status === "FEASIBLE" ? (
          <p className={styles.honesty}>
            {finiteNumber(view.optimality_gap)
              ? planWeeks > 1
                ? copy.unprovenPlanBodyWindow(points(view.optimality_gap, 1, locale), planWeeks)
                : copy.unprovenPlanBody(points(view.optimality_gap, 1, locale))
              : top100Priced
                ? top100Copy.unproven
                : copy.unprovenPlanGapUnknown}
          </p>
        ) : null}
        {price != null ? (
          <p className={styles.planCost}>
            <strong className="num">
              {strategyPriced
                ? unproven
                  ? top100Copy.strategyCostAtMost(points(price, 1, locale))
                  : top100Copy.strategyCost(points(price, 1, locale))
                : top100Priced
                  ? wordPriced
                    ? unproven
                      ? top100Copy.combinedCostAtMost(points(price, 1, locale))
                      : top100Copy.combinedCost(points(price, 1, locale))
                    : unproven
                      ? top100Copy.costAtMost(points(price, 1, locale))
                      : top100Copy.cost(points(price, 1, locale))
                  : wordPriced
                    ? unproven
                      ? evidenceCopy.costAtMost(points(price, 1, locale))
                      : evidenceCopy.cost(points(price, 1, locale))
                    : unproven
                      ? copy.planCostAtMost(points(price, 1, locale))
                      : copy.planCost(points(price, 1, locale))}
            </strong>
            {(rivalName ?? view.rival_label) ? (
              <span> · {copy.planRival(rivalName ?? String(view.rival_label))}</span>
            ) : null}
          </p>
        ) : null}
        {view.control_solver_status === "FEASIBLE" && !view.chip_choice ? (
          <p className={styles.honesty}>
            <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
            {finiteNumber(view.control_optimality_gap)
              ? copy.controlUnprovenBody(points(view.control_optimality_gap, 1, locale))
              : copy.controlGapUnknown}
          </p>
        ) : null}
        {explainedUnproven ? <p className={styles.honesty}>{copy.unprovenPlanNextStep}</p> : null}
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
      </div>
    </>
  );
}

/**
 * What a switch adds to the plan (rival players, the club's word, the Top 100 weight, the
 * chip), what the plan assumes, and the window. Each renders only where the document
 * carries it. The week's lineup is the squad section's list view (`PlanLineup`).
 */
export function AdviceDetails({
  shown,
  squad,
  rivalSquad,
  windowControl = null,
}: {
  shown: ShownAdvice;
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
  windowControl?: LeagueViewEnvelope<EntryAdvice> | null;
}) {
  const { envelope } = shown;
  const view = envelope.payload;
  return (
    <div className={board.details}>
      <RivalPlayers advice={envelope} squad={squad} rivalSquad={rivalSquad} />
      <EvidenceSection view={view} />
      <Top100Section view={view} />
      <ChipChoiceSection view={view} />
      <ChipStrategySection view={view} />
      <StatedLimits view={view} />
      <WindowComparison view={view} control={windowControl?.payload ?? null} />
      <WindowSection view={view} />
    </div>
  );
}

/** The week's lineup as a list, on the basis the chip scores it: the pitch's list view. */
export function PlanLineup({
  view,
  codes = null,
}: {
  view: EntryAdvice;
  codes?: ClubCodes | null;
}) {
  const { language } = useLanguage();
  const { chipBasis } = adviceBasis(view, CHIP_COPY[language]);
  return <LineupSection view={view} chipBasis={chipBasis} codes={codes} />;
}

/** The decision and its details together, as one plan reads when shown on its own. */
export function AdviceCard({
  shown,
  members = [],
  squad,
  rivalSquad,
  windowControl = null,
  fixtures = null,
}: {
  shown: ShownAdvice;
  windowControl?: LeagueViewEnvelope<EntryAdvice> | null;
  members?: EntryView[];
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
  fixtures?: FixturesPayload | null;
}) {
  return (
    <>
      <AdviceDecision shown={shown} members={members} squad={squad} fixtures={fixtures} />
      <AdviceDetails
        shown={shown}
        squad={squad}
        rivalSquad={rivalSquad}
        windowControl={windowControl}
      />
    </>
  );
}

/**
 * The sentences about how this plan's numbers are built, for the page's "How was this
 * worked out?" disclosure: the lineup rule, how the boards add up, and the week's hit
 * charge, said once because the game charges the week and not any one move.
 */
export function AdviceMethodNotes({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const chipCopy = CHIP_COPY[language];
  const { rowsAreShares, chipBasis } = adviceBasis(view, chipCopy);
  const lineup = view.captain && view.vice_captain && view.starting_xi && view.bench;
  return (
    <>
      {lineup ? <p>{copy.lineupRule}</p> : null}
      {/* Each board is conditional on the boards before it, which is what makes them add
          up. Said only where there is more than one to read in order. */}
      {rowsAreShares && view.moves.length > 1 ? (
        <p>{chipBasis !== null ? chipCopy.moveRowsBasis(chipBasis) : copy.moveRowsBasis}</p>
      ) : null}
      {/* Absent on documents published before the producer stated the week's charge. */}
      {view.moves.length > 0 && view.transfer_hit_points != null ? (
        <p>{copy.weekTransferCost(points(view.transfer_hit_points, 1, locale))}</p>
      ) : null}
    </>
  );
}

type MemberCopy = ReturnType<typeof useLanguage>["messages"]["leagueMembers"];

/** The caption under a move, keyed on the reason the producer stated for it. */
function reasonFor(
  copy: MemberCopy,
  language: "tr" | "en",
  code: AdviceMove["reason_code"],
): string {
  if (code === "manager_word") return EVIDENCE_COPY[language].moveReason;
  if (code === "top100_preference") return TOP100_COPY[language].moveReason;
  if (code === "window_value") return copy.windowValueReason;
  if (code === "points_gain") return copy.pointsGainReason;
  return copy.modeTradeoffReason;
}

/**
 * The name a board or plate prints: the game's short name. Where the full name differs,
 * it is what a screen reader hears and what the page's text carries; the short name is
 * what the eye reads.
 */
function PlayerName({ player }: { player: AdvicePlayer | null }) {
  const { messages } = useLanguage();
  if (!player) return <span>{messages.suggestionHistory.unknownPlayer}</span>;
  if (player.short_name === player.name || player.short_name.trim() === "")
    return <span>{player.name}</span>;
  return (
    <>
      <span aria-hidden="true">{player.short_name}</span>
      <span className="visually-hidden">{player.name}</span>
    </>
  );
}

/**
 * The club's next three gameweeks as one line, 'BOU E · EVE D · TOT E': every opponent in
 * a double week, 'maç yok' in a blank one, and nothing at all when the calendar is absent
 * or does not list the weeks. The stylesheet shows it below 1180 px, where the fixture
 * rail is not beside the board.
 */
function FixtureStrip({
  team,
  codes,
  fixtures,
  season,
  gameweek,
}: {
  team: string;
  codes: ClubCodes;
  fixtures: FixturesPayload | null;
  season: string;
  gameweek: number;
}) {
  const copy = useLanguage().messages.leagueMembers;
  const weeks = clubWeeks(fixtures, season, team, nextThree(gameweek), codes).filter(
    (week) => week !== null,
  );
  if (weeks.length === 0) return null;
  const text = weeks
    .map((week) =>
      week.matches.length === 0
        ? copy.fixtureNone
        : week.matches
            .map((match) => `${match.opponent} ${match.home ? copy.fixtureHome : copy.fixtureAway}`)
            .join(" / "),
    )
    .join(" · ");
  return (
    <span className={board.strip}>
      <span className="visually-hidden">
        {copy.fixtureStrip(weeks[0]!.gameweek, weeks[weeks.length - 1]!.gameweek)}:{" "}
      </span>
      {text}
    </span>
  );
}

function BoardPanel({
  kind,
  player,
  codes,
  fixtures,
  season,
  gameweek,
}: {
  kind: "out" | "in";
  player: AdvicePlayer | null;
  codes: ClubCodes;
  fixtures: FixturesPayload | null;
  season: string;
  gameweek: number;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <div className={`${board.panel} ${kind === "out" ? board.out : board.in}`}>
      <span className={board.word}>
        <BoardArrow direction={kind === "out" ? "down" : "up"} />
        {kind === "out" ? copy.out : copy.in}
      </span>
      <span className={board.name}>
        <PlayerName player={player} />
        {kind === "in" ? <span className={board.new}>{copy.boardNew}</span> : null}
      </span>
      {player ? (
        <span className={board.meta}>
          <ClubMark team={player.team} codes={codes} />
          {Object.hasOwn(messages.positions, player.position) ? (
            <>
              <span className={board.sep} aria-hidden="true">
                ·
              </span>
              <span className={board.position}>
                {messages.positions[player.position as keyof typeof messages.positions]}
              </span>
            </>
          ) : null}
        </span>
      ) : null}
      {player ? (
        <FixtureStrip
          team={player.team}
          codes={codes}
          fixtures={fixtures}
          season={season}
          gameweek={gameweek}
        />
      ) : null}
    </div>
  );
}

/**
 * One move as the fourth official's board: DEĞİŞİKLİK i/n, the player going out on red
 * and the one coming in on green, each with the word, an arrow, the club and the position
 * (colour is never the only signal), and the move's share of the plan's gain in LED
 * digits, only where the producer published it as a share.
 */
function SubstitutionBoard({
  move,
  index,
  count,
  measured,
  codes,
  fixtures,
  season,
  gameweek,
}: {
  move: AdviceMove;
  index: number;
  count: number;
  measured: boolean;
  codes: ClubCodes;
  fixtures: FixturesPayload | null;
  season: string;
  gameweek: number;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const headId = useId();
  const value =
    measured && finiteNumber(move.expected_points_delta)
      ? signedFigure(move.expected_points_delta, locale)
      : null;
  return (
    <article className={board.board} aria-labelledby={headId}>
      <h3 className={board.boardHead} id={headId}>
        {copy.boardChange(index + 1, count)}
      </h3>
      <div className={board.panels}>
        <BoardPanel
          kind="out"
          player={move.player_out}
          codes={codes}
          fixtures={fixtures}
          season={season}
          gameweek={gameweek}
        />
        <BoardPanel
          kind="in"
          player={move.player_in}
          codes={codes}
          fixtures={fixtures}
          season={season}
          gameweek={gameweek}
        />
      </div>
      <p className={board.led}>
        {value !== null ? (
          <>
            <span className={board.ledValue}>{value}</span>
            <span className={board.ledLabel}>{copy.boardGainLabel}</span>
          </>
        ) : (
          <span className={board.ledUnknown}>{copy.projectedGainUnknown}</span>
        )}
      </p>
    </article>
  );
}

/**
 * What the plan is worth against doing nothing, on the same basis as the boards and the
 * lineup total: the figure, and beside it the sentence that says what it is measured
 * against. Where every board's share is published and none is below zero they are drawn
 * as one stacked bar at a fixed scale; otherwise the shares are listed with their signs.
 * A document without the gain gets no figure, not a zero. Under it, the transfers this
 * week uses of the free ones held and the week's hit charge, each only where published.
 */
function GainStrip({
  view,
  squad,
  measured,
  chipBasis,
}: {
  view: EntryAdvice;
  squad: EntrySquad;
  measured: boolean;
  chipBasis: string | null;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const chipCopy = CHIP_COPY[language];
  const gain = view.expected_gain_vs_hold;
  const hits = view.transfer_hit_points;
  const shares = view.moves.map((move) => move.expected_points_delta);
  const allShares = measured && shares.length > 0 && shares.every(finiteNumber);
  const stacked =
    allShares && finiteNumber(gain) && gain > 0 && shares.every((share) => (share ?? 0) >= 0);
  const freeKnown =
    squad.free_transfers_known === true &&
    Number.isSafeInteger(squad.free_transfers) &&
    squad.free_transfers >= 0;
  // A Wildcard or Free Hit week makes its moves without spending a free transfer (the
  // planner pins the ones used to zero and keeps those held), so it says that instead.
  const weekChip = view.chip ?? view.chip_choice?.chip ?? null;
  const unlimited = weekChip === "wildcard" || weekChip === "freehit";
  const facts = [
    // Free transfers used of those held: a move beyond them is a hit, stated beside it.
    freeKnown && view.moves.length > 0
      ? unlimited
        ? copy.freeTransfersKeptUnderChip(
            copy.chipNames[weekChip] ?? weekChip,
            squad.free_transfers,
          )
        : copy.freeTransfersUsed(
            Math.min(view.moves.length, squad.free_transfers),
            squad.free_transfers,
          )
      : null,
    finiteNumber(hits) && view.moves.length > 0
      ? copy.hitPointsFact(hits.toLocaleString(locale, { maximumFractionDigits: 1 }))
      : null,
  ].filter((fact): fact is string => fact !== null);
  if (!finiteNumber(gain) && facts.length === 0) return null;
  const cost = finiteNumber(hits) && hits > 0 ? points(hits, 1, locale) : null;
  const caption =
    cost !== null
      ? chipBasis !== null
        ? chipCopy.gainCaptionBeforeCost(cost, chipBasis)
        : copy.gainCaptionBeforeCost(cost)
      : chipBasis !== null
        ? chipCopy.gainCaption(chipBasis)
        : copy.gainCaption;
  const shortName = (move: AdviceMove) => move.player_in?.short_name || move.player_in?.name || "";
  return (
    <div className={board.gain}>
      <div className={board.gainTop}>
        {finiteNumber(gain) ? (
          <p className={board.gainHead}>
            <strong
              className={board.gainFigure}
              data-sign={gain >= 0.005 ? "up" : gain <= -0.005 ? "down" : undefined}
            >
              {signedFigure(gain, locale)}
            </strong>{" "}
            <span className={board.gainCaption}>{caption}</span>
          </p>
        ) : null}
        {facts.length > 0 ? (
          <ul className={board.facts}>
            {facts.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {stacked ? (
        <div className={board.bar} aria-hidden="true">
          <div
            className={board.segments}
            style={
              {
                "--total": shares.reduce<number>((sum, share) => sum + (share ?? 0), 0),
              } as CSSProperties
            }
          >
            {view.moves.map((move, index) => {
              const share = move.expected_points_delta!;
              // Room for a label is judged at the phone's scale, the narrower of the two.
              const room = share * 80;
              const label =
                room >= 120
                  ? `${shortName(move)} ${signedFigure(share, locale)}`
                  : room >= 44
                    ? signedFigure(share, locale)
                    : "";
              return (
                <span
                  key={move.move_id}
                  className={index % 2 === 0 ? board.segment : `${board.segment} ${board.alt}`}
                  style={{ "--share": share } as CSSProperties}
                >
                  {label}
                </span>
              );
            })}
          </div>
          <span className={board.tick}>{signedFigure(gain!, locale)}</span>
        </div>
      ) : allShares && view.moves.length > 1 ? (
        <p className={board.gainList}>
          {view.moves.map((move, index) => (
            <span key={move.move_id}>
              {index > 0 ? " · " : null}
              <span className={board.gainItem}>
                {shortName(move)} {signedFigure(move.expected_points_delta!, locale)}
              </span>
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

/** The armband: C, the captain, the club and the expected points; V and the vice-captain. */
function CaptainLine({ view, codes }: { view: EntryAdvice; codes: ClubCodes }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { captain, vice_captain: vice } = view;
  if (!captain || !vice) return null;
  return (
    <p className={board.captain}>
      <span className={board.armband}>
        <span className={board.armLabel}>{copy.captainLabel}</span>
        <span className={board.markCaptain} aria-hidden="true">
          {copy.captainMark}
        </span>
        <strong className={board.armName}>{captain.short_name || captain.name}</strong>
        <ClubMark team={captain.team} codes={codes} />
        {finiteNumber(captain.expected_points) ? (
          <span className={board.armPoints}>
            {figure(captain.expected_points, locale)} {copy.pointsUnit}
          </span>
        ) : null}
      </span>
      <span className={board.armband}>
        <span className={board.armLabel}>{copy.viceCaptainLabel}</span>
        <span className={board.markVice} aria-hidden="true">
          {copy.viceMark}
        </span>
        <strong className={board.armName}>{vice.short_name || vice.name}</strong>
        <span className={board.viceClub}>
          <ClubMark team={vice.team} codes={codes} />
        </span>
      </span>
    </p>
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
 * What the producer says this plan assumes, in its own sentences. It used to hang inside
 * the window section, which meant a one-week document could publish a limit and show it
 * to nobody: the one sentence that holds for every plan on this path is that no chip was
 * ever offered to the solver, and without it a blank chip line reads as a chip that was
 * weighed and turned down.
 */
function StatedLimits({ view }: { view: EntryAdvice }) {
  const { language, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const limits = view.stated_limits ?? [];
  if (limits.length === 0) return null;
  const weeks = view.plan_weeks?.length ?? 1;
  const label = weeks > 1 ? copy.windowLimitsLabel : copy.planLimitsLabel;
  return (
    <section className={styles.lineup} aria-label={label}>
      <h3 className={styles.lineupTitle}>{label}</h3>
      <ul className={styles.limits}>
        {limits.map((sentence) => {
          const weight = top100LimitWeight(sentence);
          const chipSentence = chipLimit(CHIP_COPY[language], sentence);
          return (
            <li key={sentence}>
              {chipSentence !== null
                ? chipSentence
                : weight !== null
                  ? TOP100_COPY[language].limit(weight)
                  : variantLimit(TOP100_COPY[language], sentence) !== null
                    ? variantLimit(TOP100_COPY[language], sentence)
                    : Object.hasOwn(copy.statedLimits, sentence)
                      ? copy.statedLimits[sentence]
                      : copy.statedLimitUnknown}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * A three- or five-week window: one row per gameweek (transfers, hit points, chip,
 * expected points). The moves and the lineup above are the first week's; the rest of the
 * window lives here. What the window assumes is stated above, beside every other plan's
 * assumptions. Rendered only when the producer published it, so a one-week document shows
 * nothing extra. The table never scrolls sideways: on a phone each week is a block of its
 * own, the week and its expected points on the first line, then who comes in, who goes
 * out, the hit points and the chip, each under its column's name.
 */
function WindowSection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const weeks = view.plan_weeks;
  if (!weeks || weeks.length === 0) return null;
  const names = (players: AdvicePlayer[]) =>
    players.length === 0 ? copy.rivalPlayersNone : players.map((player) => player.name).join(", ");
  const title = copy.windowTitle(weeks.length);
  return (
    <section className={styles.window} aria-label={title}>
      <h3 className={styles.lineupTitle}>{title}</h3>
      <p className={styles.honesty}>{copy.windowRule}</p>
      {/* The roles are stated because a phone lays each week out as a block, and a table
          whose parts change their display must still read as a table. */}
      <table className={styles.windowTable} role="table">
        <thead role="rowgroup">
          <tr role="row">
            <th scope="col" role="columnheader" className={styles.weekColumn}>
              {copy.windowWeek}
            </th>
            <th scope="col" role="columnheader">
              {copy.in}
            </th>
            <th scope="col" role="columnheader">
              {copy.out}
            </th>
            <th scope="col" role="columnheader" className={`${styles.right} ${styles.hitsColumn}`}>
              {copy.windowHits}
            </th>
            <th scope="col" role="columnheader" className={styles.chipColumn}>
              {copy.chipLabel}
            </th>
            <th
              scope="col"
              role="columnheader"
              className={`${styles.right} ${styles.pointsColumn}`}
            >
              {copy.windowPoints}
            </th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {weeks.map((week) => (
            <tr key={week.gameweek} role="row">
              <th scope="row" role="rowheader" className={`${styles.weekCell} num`}>
                {copy.windowWeekOf(week.gameweek)}
              </th>
              <td role="cell" className={styles.inCell} data-label={copy.in}>
                {names(week.transfers_in)}
              </td>
              <td role="cell" className={styles.outCell} data-label={copy.out}>
                {names(week.transfers_out)}
              </td>
              <td
                role="cell"
                className={`${styles.right} ${styles.hitsCell} num`}
                data-label={copy.windowHits}
              >
                {points(week.transfer_hit_points, 0, locale)}
              </td>
              <td role="cell" className={styles.chipCell} data-label={copy.chipLabel}>
                {week.chip ? (copy.chipNames[week.chip] ?? week.chip) : copy.rivalPlayersNone}
              </td>
              <td
                role="cell"
                className={`${styles.right} ${styles.pointsCell} num`}
                data-label={copy.windowPoints}
              >
                {points(week.expected_points, 1, locale)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** A source link only for a web address: a capture's final URL is data, not markup. */
function webAddress(url: string | null): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

/** The source's own dateline, to the day when that is all the source said. */
function dateline(iso: string | null, precision: string | null, locale: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  if (precision === "day") {
    return date.toLocaleDateString(locale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  return utcShort(iso, locale);
}

/**
 * What the club's own page said, as the producer applied it. The words are the source's,
 * cut from the captured bytes; the category is the model's; the role is the declared
 * rule's. Example data says so on the section itself, not only in a badge elsewhere.
 */
function EvidenceSection({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const copy = EVIDENCE_COPY[language];
  const evidence = view.evidence;
  if (!evidence) return null;
  const real = evidence.source_kind === "club_news_capture";
  return (
    <section className={styles.adviceSection} data-testid="managers-word">
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      {real ? (
        <p className={styles.honesty}>{copy.sourceCapture}</p>
      ) : (
        <p className={styles.honesty}>
          <Badge tone="warn">{messages.leagueMembers.exampleData}</Badge> {copy.sourceExample}
        </p>
      )}
      <p className={styles.muted}>{copy.intro(evidence.clubs_covered.length)}</p>
      {evidence.binding === undefined ? null : (
        <p className={styles.muted}>{evidence.binding ? copy.changed : copy.unchanged}</p>
      )}
      {evidence.applied.length > 0 ? (
        <ul className={styles.assumptionList}>
          {evidence.applied.map((item) => {
            const declared = item.words_status ?? (item.words ? "shown" : "unresolved");
            const status =
              declared === "shown" && item.words && QUOTE_WITHHELD.test(item.words)
                ? "withheld_figure"
                : declared;
            const href = webAddress(item.source_url);
            const speaker = item.speaker
              ? (copy.speakers[item.speaker] ?? copy.speakerUnknown)
              : copy.speakerUnknown;
            return (
              <li key={item.player_id}>
                <strong>{item.name ?? `#${item.player_id}`}</strong>{" "}
                {item.role && copy.roles[item.role] ? (
                  <Badge tone="neutral">{copy.roles[item.role]}</Badge>
                ) : null}
                {status === "shown" && item.words ? (
                  <blockquote>{item.words}</blockquote>
                ) : (
                  <p className={styles.muted}>
                    {status === "withheld_figure" ? copy.wordsWithheld : copy.wordsUnresolved}
                  </p>
                )}
                <p className={styles.muted}>
                  {copy.said(
                    speaker,
                    dateline(item.published_at_utc, item.published_precision, locale),
                  )}{" "}
                  {href ? (
                    <a href={href} rel="noopener noreferrer">
                      {copy.source}
                    </a>
                  ) : null}
                </p>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

/**
 * A Top 100 weighted plan: the setting the member chose, whether it moved their plan, and
 * what it is and is not. Rendered only on a weighted document.
 */
function Top100Section({ view }: { view: EntryAdvice }) {
  const { language } = useLanguage();
  const copy = TOP100_COPY[language];
  const top100 = view.top100;
  if (!top100) return null;
  return (
    <section className={styles.adviceSection} data-testid="top100-influence">
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      <p className={styles.muted}>
        {copy.weightLine(top100.weight)} {top100.changed ? copy.changed : copy.unchanged}
      </p>
      <p className={styles.honesty}>{copy.honesty}</p>
      <p className={styles.muted}>{copy.notStart}</p>
      <p className={styles.muted}>{copy.saturation}</p>
      {view.moves.some((move) => (move.expected_points_delta ?? 0) < 0) ? (
        <p className={styles.muted}>{copy.negativeRow}</p>
      ) : null}
    </section>
  );
}

/**
 * A chip strategy the service planned: the chip this week (or hold), the plan week by
 * week, and for the automatic strategy what its holding values are and are not. The Top
 * 100 setting is named as the weight it is, never as a share.
 */
function ChipStrategySection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const strategy = view.chip_strategy;
  if (!strategy) return null;
  const copy = messages.leagueMembers.chipStrategy;
  const name = (chip: string | null) =>
    chip ? (messages.leagueMembers.chipNames[chip] ?? chip) : copy.hold;
  return (
    <section className={styles.adviceSection} data-testid="chip-strategy">
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      <p>
        {strategy.mode === "auto" ? copy.autoThisWeek : copy.ownThisWeek}:{" "}
        <strong>{name(strategy.selected_chip)}</strong>
      </p>
      <p>
        {(view.plan_weeks ?? [])
          .map((week) => `${messages.common.gameweekShort(week.gameweek)}: ${name(week.chip)}`)
          .join(" · ")}
      </p>
      {strategy.mode === "auto" && (
        <>
          <p className={styles.honesty}>{copy.autoHonesty}</p>
          <p>{copy.autoFuture}</p>
          <ul>
            {strategy.reservations.map((reservation) => (
              <li key={`${reservation.chip}-${reservation.first_gameweek}`}>
                {name(reservation.chip)} · {copy.expiry}{" "}
                {messages.common.gameweekShort(reservation.last_gameweek)} · {copy.holdingValue}{" "}
                {points(reservation.holding_value, 1, locale)}
                {" · "}
                {reservation.remaining_opportunities} {copy.opportunities}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className={styles.muted}>
        {copy.utilityNote(strategy.top100_weight)}
        {strategy.objective_gap !== null &&
          ` ${copy.solverGap}: ${points(strategy.objective_gap, 2, locale)}.`}
      </p>
    </section>
  );
}

/**
 * A chip the member chose: which chip, what the chip week is expected to score above the
 * member's own plan without it, and that the number is one gameweek's and nothing more.
 * A gain, so it is never worded as something given up, and never as a reason to play the
 * chip now. Rendered only on a chip document.
 */
function ChipChoiceSection({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const copy = CHIP_COPY[language];
  const choice = view.chip_choice;
  if (!choice) return null;
  const name = messages.leagueMembers.chipNames[choice.chip] ?? choice.chip;
  const unproven = view.solver_status === "FEASIBLE" || view.control_solver_status === "FEASIBLE";
  return (
    <section className={styles.adviceSection} data-testid="chip-choice">
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      <p className={styles.muted}>{copy.chosen(name)}</p>
      {finiteNumber(choice.gain_vs_no_chip) ? (
        <p className={styles.planCost}>
          <strong className="num">
            {copy.gain(signedPoints(choice.gain_vs_no_chip, 1, locale))}
          </strong>
        </p>
      ) : null}
      {unproven ? <p className={styles.muted}>{copy.unproven}</p> : null}
      <p className={styles.honesty}>{copy.honesty}</p>
      {choice.chip === "freehit" ? <p className={styles.muted}>{copy.freeHit}</p> : null}
    </section>
  );
}

/**
 * The rest of the decision as the squad section's list view (D-Phone-Kadro): the plan's
 * own total, the armband and the chip, then the eleven in pitch order and the bench in its
 * order, one row a player with the position (or the bench place), the name, the club, the
 * C, V and YENİ marks the pitch carries, and the expected points as a bar at a fixed scale
 * beside the figure. Rendered only when the producer published the whole lineup: a
 * document from before the producer carried the plan week shows the moves alone. How the
 * lineup is chosen is said in the page's "How was this worked out?".
 */
function LineupSection({
  view,
  chipBasis,
  codes,
}: {
  view: EntryAdvice;
  chipBasis: string | null;
  codes: ClubCodes | null;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { captain, vice_captain: vice, starting_xi: eleven, bench } = view;
  if (!captain || !vice || !eleven || !bench) return null;
  const chipName = view.chip ? (copy.chipNames[view.chip] ?? view.chip) : null;
  const incoming = new Set(view.moves.map((move) => move.player_in?.player_id));
  const code = (position: string) =>
    Object.hasOwn(messages.positionCodes, position)
      ? messages.positionCodes[position as keyof typeof messages.positionCodes]
      : position;
  const word = (position: string) =>
    Object.hasOwn(messages.positions, position)
      ? messages.positions[position as keyof typeof messages.positions]
      : null;
  // One scale for every bar in the list: 20 px a point on the widest column, so eight
  // points fill the track; a list with a bigger figure widens the scale to hold it.
  const figures = [...eleven, ...bench]
    .map((player) => player.expected_points)
    .filter(finiteNumber);
  const scale = Math.max(8, Math.ceil(Math.max(0, ...figures)));
  return (
    <section
      className={lineup.list}
      aria-label={copy.lineupTitle}
      style={{ "--scale": scale } as CSSProperties}
    >
      <h3 className="visually-hidden">{copy.lineupTitle}</h3>
      {/* The total as the pitch's heading prints it, so switching views keeps the figure. */}
      {finiteNumber(view.expected_own_points) ? (
        <p className={lineup.own}>
          {chipBasis !== null
            ? CHIP_COPY[language].expectedOwnPoints(
                figure(view.expected_own_points, locale),
                chipBasis,
              )
            : copy.expectedOwnPoints(figure(view.expected_own_points, locale))}
        </p>
      ) : null}
      <dl className={lineup.armband}>
        <div>
          <dt>{copy.captainLabel}</dt>
          <dd>
            <span className={lineup.markCaptain} aria-hidden="true">
              {copy.captainMark}
            </span>
            <strong className={lineup.armName}>
              <PlayerName player={captain} />
            </strong>
            <ClubMark team={captain.team} codes={codes} />
          </dd>
        </div>
        <div>
          <dt>{copy.viceCaptainLabel}</dt>
          <dd>
            <span className={lineup.markVice} aria-hidden="true">
              {copy.viceMark}
            </span>
            <strong className={lineup.armName}>
              <PlayerName player={vice} />
            </strong>
            <ClubMark team={vice.team} codes={codes} />
          </dd>
        </div>
        <div>
          <dt>{copy.chipLabel}</dt>
          <dd>{chipName ? <Badge tone="good">{chipName}</Badge> : copy.chipNone}</dd>
        </div>
      </dl>
      <h4 className={lineup.title}>{copy.startingXiLabel}</h4>
      <ol className={lineup.rows}>
        {eleven.map((player, index) => (
          <LineupRow
            key={player.player_id}
            player={player}
            groupStart={index > 0 && eleven[index - 1]!.position !== player.position}
            lead={code(player.position)}
            detail={null}
            mark={
              player.player_id === captain.player_id
                ? "C"
                : player.player_id === vice.player_id
                  ? "V"
                  : null
            }
            isNew={incoming.has(player.player_id)}
            codes={codes}
          />
        ))}
      </ol>
      <h4 className={lineup.title}>{copy.benchOrderLabel}</h4>
      <ol className={lineup.rows}>
        {bench.map((player, index) => (
          <LineupRow
            key={player.player_id}
            player={player}
            groupStart={false}
            lead={String(index + 1)}
            detail={word(player.position)}
            mark={null}
            isNew={incoming.has(player.player_id)}
            codes={codes}
          />
        ))}
      </ol>
    </section>
  );
}

function LineupRow({
  player,
  groupStart,
  lead,
  detail,
  mark,
  isNew,
  codes,
}: {
  player: AdvicePlayer;
  /** The first of a new position in the eleven, set a little apart from the one before. */
  groupStart: boolean;
  /** The position code for the eleven, the published place for the bench. */
  lead: string;
  /** The position word, which the bench rows add after the club. */
  detail: string | null;
  mark: "C" | "V" | null;
  isNew: boolean;
  codes: ClubCodes | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const xp = finiteNumber(player.expected_points) ? player.expected_points : null;
  return (
    <li className={lineup.row} data-group={groupStart ? "" : undefined}>
      <span className={lineup.lead}>{lead}</span>
      <span className={lineup.player}>
        <span className={lineup.nameLine}>
          <strong className={lineup.name}>
            <PlayerName player={player} />
          </strong>
          {mark === "C" ? (
            <span
              className={lineup.markCaptain}
              role="img"
              aria-label={messages.squad.captainLabel}
            >
              {copy.captainMark}
            </span>
          ) : null}
          {mark === "V" ? (
            <span
              className={lineup.markVice}
              role="img"
              aria-label={messages.squad.viceCaptainLabel}
            >
              {copy.viceMark}
            </span>
          ) : null}
        </span>
        <span className={lineup.meta}>
          <ClubMark team={player.team} codes={codes} />
          {detail ? <span>{detail}</span> : null}
          {isNew ? <span className={lineup.new}>{copy.boardNew}</span> : null}
        </span>
      </span>
      {xp !== null ? (
        <span className={lineup.track} aria-hidden="true">
          <span className={lineup.bar} style={{ "--xp": Math.max(0, xp) } as CSSProperties} />
        </span>
      ) : (
        <span />
      )}
      <span className={lineup.value}>
        {xp !== null ? `${figure(xp, locale)} ${copy.pointsUnit}` : ""}
      </span>
    </li>
  );
}

function WindowComparison({ view, control }: { view: EntryAdvice; control: EntryAdvice | null }) {
  const { locale, language, messages } = useLanguage();
  const copy = TOP100_COPY[language];
  if (
    !control ||
    view.window <= 1 ||
    (view.mode === "saf-puan" && !view.top100) ||
    !view.source_snapshot_id ||
    view.source_snapshot_id !== control.source_snapshot_id ||
    view.entry_id !== control.entry_id ||
    view.league_id !== control.league_id ||
    view.window !== control.window ||
    view.season !== control.season ||
    view.gameweek !== control.gameweek ||
    control.mode !== "saf-puan" ||
    control.top100 !== undefined ||
    control.evidence !== undefined ||
    control.chip != null
  )
    return null;
  const total = (plan: EntryAdvice): number | null => {
    const weeks = plan.plan_weeks;
    if (
      !weeks ||
      weeks.length !== plan.window ||
      weeks.some(
        (week, index) =>
          week.gameweek !== plan.gameweek + index ||
          !finiteNumber(week.expected_points) ||
          !finiteNumber(week.transfer_hit_points),
      )
    )
      return null;
    const value = weeks.reduce(
      (sum, week) => sum + week.expected_points - week.transfer_hit_points,
      0,
    );
    return Number.isFinite(value) ? value : null;
  };
  const selected = total(view),
    pure = total(control);
  if (selected === null || pure === null) return null;
  return (
    <section aria-label={copy.windowComparisonTitle}>
      <h3 className={styles.lineupTitle}>{copy.windowComparisonTitle}</h3>
      <dl className={styles.armband}>
        <div>
          <dt>{copy.windowSelectedTotal}</dt>
          <dd className="num">{points(selected, 1, locale)}</dd>
        </div>
        <div>
          <dt>{copy.windowPureTotal}</dt>
          <dd className="num">{points(pure, 1, locale)}</dd>
        </div>
      </dl>
      <p className={styles.honesty}>{copy.windowComparisonBasis}</p>
      <p className={styles.honesty}>{messages.leagueMembers.windowLimits}</p>
    </section>
  );
}
