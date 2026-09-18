import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { points, signedPoints, utcShort } from "../../../lib/format";
import { CHIP_COPY, chipLimit, chipRescores } from "../advice/chipCopy";
import { EVIDENCE_COPY, QUOTE_WITHHELD } from "../advice/evidenceCopy";
import { comparedRivalPlayers } from "../advice/rivalPlayers";
import { TOP100_COPY, top100LimitWeight, variantLimit } from "../advice/top100Copy";
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

export function AdviceCard({
  shown,
  members = [],
  squad,
  rivalSquad,
  windowControl = null,
}: {
  shown: ShownAdvice;
  windowControl?: LeagueViewEnvelope<EntryAdvice> | null;
  members?: EntryView[];
  squad: LeagueViewEnvelope<EntrySquad>;
  rivalSquad: LeagueViewEnvelope<EntrySquad> | null;
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
  // measured as `expected_points_cost_ceiling` and this page states that — the most the
  // strategy can cost — instead of a figure it cannot stand behind. A document that is
  // unproven and carries no ceiling has no honest figure to print, so it prints none;
  // and a price below zero is a giveaway no constrained plan can hand out, so no
  // producer's number is rendered as one.
  const unproven = view.solver_status === "FEASIBLE" || view.control_solver_status === "FEASIBLE";
  const priceCeiling = view.expected_points_cost_ceiling;
  const price = unproven ? priceCeiling : (priceCeiling ?? view.expected_points_cost);
  // The pure-points plan has no price of its own; switched on, the manager's word does,
  // and it is priced against the same pure-points control a rival band is.
  const wordPriced = view.mode === "saf-puan" && view.evidence !== undefined;
  // A Top 100 weight is priced the same way, in base-model points against the plan at 0;
  // with the word on as well, the one number is the pair's.
  const top100Priced = view.top100 !== undefined;
  const strategyPriced = top100Priced && view.mode !== "saf-puan";
  const showsPrice =
    (view.mode !== "saf-puan" || wordPriced || top100Priced) && finiteNumber(price) && price >= 0;
  const evidenceCopy = EVIDENCE_COPY[language];
  const top100Copy = TOP100_COPY[language];
  const alternative = view.alternative_plan;
  const alternativePrice = unproven
    ? alternative?.expected_points_cost_ceiling
    : (alternative?.expected_points_cost_ceiling ?? alternative?.expected_points_cost);
  // A bound on the planner's objective covers the whole plan at once, so the copy has to
  // say how many gameweeks that is. A one-week document publishes no plan weeks.
  const planWeeks = view.plan_weeks?.length ?? 1;
  // A move row is a share of the plan's gain against holding, and only a document that
  // publishes that gain carries shares of it. A document from before the producer did
  // carries a different quantity on those rows, the raw difference between the two
  // players' own projections, so its numbers are not printed under this label.
  const rowsAreShares = view.expected_gain_vs_hold !== undefined;
  // A Triple Captain or Bench Boost week scores on its own basis, and the producer states
  // the rows, the gain and the lineup total on it; the sentences name that basis.
  const chipCopy = CHIP_COPY[language];
  const chipBasis =
    view.chip_choice && chipRescores(view.chip_choice.chip)
      ? chipCopy.basis[view.chip_choice.chip]
      : null;
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
      {basisNote ? (
        <p className={styles.honesty}>
          {basisNote.kind === "week"
            ? copy.freeHitSquadBasis(basisNote.week)
            : copy.squadBasisUnconfirmed}
        </p>
      ) : null}
      {view.solver_status === "FEASIBLE" ? (
        <p className={styles.honesty}>
          <Badge tone="warn">{copy.unprovenPlanBadge}</Badge>{" "}
          {finiteNumber(view.optimality_gap)
            ? planWeeks > 1
              ? copy.unprovenPlanBodyWindow(points(view.optimality_gap, 1, locale), planWeeks)
              : copy.unprovenPlanBody(points(view.optimality_gap, 1, locale))
            : top100Priced
              ? top100Copy.unproven
              : copy.unprovenPlanGapUnknown}
        </p>
      ) : null}
      {showsPrice && price != null ? (
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
              <AdviceRow
                key={move.move_id}
                move={move}
                measured={rowsAreShares}
                chipBasis={chipBasis}
              />
            ))}
          </div>
          {/* Each row is conditional on the rows above it, which is what makes them add
              up. Said once, and only where there is more than one row to read in order. */}
          {rowsAreShares && view.moves.length > 1 ? (
            <p className={styles.muted}>
              {chipBasis !== null ? chipCopy.moveRowsBasis(chipBasis) : copy.moveRowsBasis}
            </p>
          ) : null}
          {/* The week's hit charge, once, because the game charges the week and not any
              one move. Absent on documents published before the producer stated it. */}
          {view.transfer_hit_points != null ? (
            <p className={styles.muted}>
              {copy.weekTransferCost(points(view.transfer_hit_points, 1, locale))}
            </p>
          ) : null}
        </>
      )}
      {/* What the plan is worth against doing nothing, on the same basis as the rows
          above it and as the lineup total below. Rendered only where the producer
          measured it: a document without the number gets no sentence, not a zero. */}
      {finiteNumber(view.expected_gain_vs_hold) ? (
        <p className={styles.planCost}>
          <strong className="num">
            {finiteNumber(view.transfer_hit_points) && view.transfer_hit_points > 0
              ? chipBasis !== null
                ? chipCopy.planGainVsHoldBeforeCost(
                    signedPoints(view.expected_gain_vs_hold, 1, locale),
                    points(view.transfer_hit_points, 1, locale),
                    chipBasis,
                  )
                : copy.planGainVsHoldBeforeCost(
                    signedPoints(view.expected_gain_vs_hold, 1, locale),
                    points(view.transfer_hit_points, 1, locale),
                  )
              : chipBasis !== null
                ? chipCopy.planGainVsHold(
                    signedPoints(view.expected_gain_vs_hold, 1, locale),
                    chipBasis,
                  )
                : copy.planGainVsHold(signedPoints(view.expected_gain_vs_hold, 1, locale))}
          </strong>
        </p>
      ) : null}
      <RivalPlayers advice={envelope} squad={squad} rivalSquad={rivalSquad} />
      <EvidenceSection view={view} />
      <Top100Section view={view} />
      <ChipChoiceSection view={view} />
      <LineupSection view={view} chipBasis={chipBasis} />
      <StatedLimits view={view} />
      <WindowComparison view={view} control={windowControl?.payload ?? null} />
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
      <h4 className={styles.lineupSub}>{label}</h4>
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
 * A three- or five-week window: one row per gameweek — transfers, hit points, chip,
 * expected points. The moves and the lineup above are the first week's; the rest of the
 * window lives here. What the window assumes is stated above, beside every other plan's
 * assumptions. Rendered only when the producer published it, so a one-week document shows
 * nothing extra.
 */
function WindowSection({ view }: { view: EntryAdvice }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const weeks = view.plan_weeks;
  if (!weeks || weeks.length === 0) return null;
  const names = (players: AdvicePlayer[]) =>
    players.length === 0 ? "—" : players.map((player) => player.name).join(", ");
  const title = copy.windowTitle(weeks.length);
  return (
    <section className={styles.window} aria-label={title}>
      <h3 className={styles.lineupTitle}>{title}</h3>
      <p className={styles.honesty}>{copy.windowRule}</p>
      <div
        className={styles.windowScroll}
        tabIndex={0}
        role="region"
        aria-label={`${copy.windowWeek}: ${weeks.map((week) => week.gameweek).join(", ")}`}
      >
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
/**
 * What the club's own page said, as the producer applied it. The words are the source's,
 * cut from the captured bytes; the category is the model's; the role is the declared
 * rule's. Example data says so on the section itself, not only in a badge elsewhere.
 */
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

function LineupSection({ view, chipBasis }: { view: EntryAdvice; chipBasis: string | null }) {
  const { language, locale, messages } = useLanguage();
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
            {chipBasis !== null
              ? CHIP_COPY[language].expectedOwnPoints(
                  points(view.expected_own_points, 1, locale),
                  chipBasis,
                )
              : copy.expectedOwnPoints(points(view.expected_own_points, 1, locale))}
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

function AdviceRow({
  move,
  measured,
  chipBasis,
}: {
  move: AdviceMove;
  measured: boolean;
  chipBasis: string | null;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const reason =
    move.reason_code === "manager_word"
      ? EVIDENCE_COPY[language].moveReason
      : move.reason_code === "top100_preference"
        ? TOP100_COPY[language].moveReason
        : reasonFor(copy, move.reason_code);
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
        <span>
          {measured && finiteNumber(move.expected_points_delta)
            ? chipBasis !== null
              ? CHIP_COPY[language].projectedGain(
                  signedPoints(move.expected_points_delta, 1, locale),
                  chipBasis,
                )
              : copy.projectedGain(signedPoints(move.expected_points_delta, 1, locale))
            : copy.projectedGainUnknown}
        </span>
      </div>
      <p className={styles.muted}>{reason}</p>
    </article>
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
