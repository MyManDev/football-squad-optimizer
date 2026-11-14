/**
 * The LIVE page as it is drawn (the synthesis of 2026-11-11, section 3.2): the heading, then
 * the member's live score and counts, one rival beside it, when the week was read, what the
 * reads since the last look changed, the fifteen grouped by their match, and the players the
 * duel turns on.
 *
 * The heading stands above everything in every state, so the one the shell focuses after a
 * move to the page is never taken away when the board arrives. A phone reads one column: the
 * score, the rival, the read, the recap, the groups and Farklar, closed. From 1024 px the
 * rival and Farklar, open, stand in a column of their own beside the rest, in that order in
 * the document as on the screen. Every number comes scored from the page; a read's motion
 * (`liveMotion.ts`) plays on what is drawn here, once, after the read is drawn.
 */

import {
  Component,
  createRef,
  memo,
  useId,
  useLayoutEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react";

import { useLanguage } from "../../../i18n/context";
import { MODEL_POP } from "../advice/modelSwitch";
import { ClubShirt } from "../components/ClubShirt";
import { BoardArrow, DisclosureIcon } from "../components/memberIcons";
import {
  LIVE_GROUPS,
  rowPoints,
  type LiveBoard,
  type LiveGroup,
  type LiveRow,
  type RecapItem,
} from "./liveBoard";
import { duelStatus, type DuelSwing, type LiveDuel } from "./liveDuel";
import { clockTime, countedWhole, signedWhole, wholePoints } from "./liveFormat";
import type { LiveLight } from "./liveLight";
import {
  APPEAR,
  LIVE_EASE,
  ballOffset,
  claimMotion,
  countLive,
  fillScales,
  holdRow,
  laneTransform,
  lightRow,
  lookKey,
  motionTimes,
  playDuel,
  playRow,
  type MotionGate,
  type MotionPlan,
  type MotionTimes,
  type RowMotion,
} from "./liveMotion";
import { LiveNumber } from "./LiveNumber";
import { keepBy, readingAnchors, type Place } from "./livePlace";
import type { RivalChoice } from "./liveRival";
import { rowLabel, subLine } from "./liveRowText";
import styles from "./LivePage.module.css";

/** The duel of the rival chosen before, kept out of sight while the next one is read. */
export interface HeldDuel {
  duel: LiveDuel;
  rivalNet: number;
}

/** The rival side as the page has it: who, the choices, and the duel once both are scored. */
export interface LiveRivalView {
  choices: readonly RivalChoice[];
  /** The chosen rival, or null while none is chosen yet. */
  entryId: number | null;
  name: string | null;
  board: LiveBoard | null;
  duel: LiveDuel | null;
  /** The previous rival's duel while this one's is read, so nothing below it jumps. */
  pending: HeldDuel | null;
  /** The rival is the member's head-to-head opponent of the live week. */
  opponent: boolean;
  onSelect: (entryId: number) => void;
}

/**
 * LIVE's heading: the page's one h1, its light while one of the member's matches is on. The
 * light breathes three times when a newer read is drawn (`breath`), then stands still; only
 * the light is drawn again for it, never the heading the shell focuses.
 */
export function LiveHeader({
  team,
  gameweek,
  entryId,
  light,
}: {
  team: string;
  gameweek: number | null;
  entryId: number;
  light: LiveLight;
}) {
  const { messages } = useLanguage();
  const copy = messages.live;
  const lit = useSyncExternalStore(light.subscribe, light.get, light.get);
  const playing = lit !== null && lit.entryId === entryId && lit.playing;
  const breath = playing ? lit.breath : null;
  return (
    <header className={styles.header}>
      <h1 className={styles.title}>
        {copy.title}
        {playing ? (
          <span
            key={breath ?? "still"}
            className={styles.light}
            role="img"
            aria-label={copy.matchInProgress}
            data-breath={breath ?? undefined}
          />
        ) : null}
      </h1>
      {team === "" ? null : (
        <p className={styles.subtitle}>
          {gameweek === null ? team : `${team} · ${messages.suggestionHistory.gameweek(gameweek)}`}
        </p>
      )}
    </header>
  );
}

/** The page before its board: while it is read, or when there is none. */
export function LiveState({ kind }: { kind: "loading" | "empty" }) {
  const { messages } = useLanguage();
  return (
    <p className={styles.state} role="status">
      {kind === "loading" ? messages.common.loading : messages.leagueMembers.toolEmpty}
    </p>
  );
}

export interface LiveViewProps {
  /** The member's team. */
  team: string;
  board: LiveBoard;
  /** Canlı puan as shown: the board's net plus what the GOL board's landed moments brought. */
  net: number;
  recap: readonly RecapItem[];
  /** The page is the visitor's own: its side reads "Sen". */
  own: boolean;
  rival: LiveRivalView | null;
  refreshing: boolean;
  onRefresh: () => void;
  /** Two columns, from 1024 px. */
  wide: boolean;
  differentialsOpen: boolean;
  onDifferentialsToggle: (open: boolean) => void;
  /** What the read drawn moves, or null. */
  plan: MotionPlan | null;
  /** Whether the opening cover still stands: a plan waits for it to go. */
  gate: MotionGate;
}

/** The board itself, under the heading. */
export function LiveView(props: LiveViewProps) {
  const { board, rival, wide, plan, gate } = props;
  const { locale } = useLanguage();
  const score = <ScoreCard board={board} net={props.net} plan={plan} gate={gate} />;
  const fresh = (
    <Freshness board={board} refreshing={props.refreshing} onRefresh={props.onRefresh} />
  );
  const sides =
    rival === null ? null : (
      <RivalBlock
        rival={rival}
        own={props.own}
        net={board.net}
        team={props.team}
        plan={plan}
        gate={gate}
      />
    );
  const shownDuel = rival?.duel ?? rival?.pending?.duel ?? null;
  const differentials = (ref?: Ref<HTMLDetailsElement>) =>
    rival !== null && shownDuel !== null ? (
      <Differentials
        ref={ref}
        duel={shownDuel}
        pending={rival.duel === null}
        own={props.own}
        team={props.team}
        rival={rival}
        open={props.differentialsOpen}
        onToggle={props.onDifferentialsToggle}
      />
    ) : null;
  const recapKey = props.recap.map((item) => item.elementId).join(",");
  const flow = (after: boolean) => (
    <LiveFlow plan={plan} gate={gate} locale={locale} recapKey={recapKey}>
      {(refs) => (
        <>
          {props.recap.length > 0 ? <Recap ref={refs.recap} items={props.recap} /> : null}
          <Groups ref={refs.groups} board={board} />
          {after ? differentials(refs.after) : null}
        </>
      )}
    </LiveFlow>
  );
  return wide ? (
    <div className={styles.columns}>
      <div className={styles.column}>
        {score}
        {fresh}
        {flow(false)}
      </div>
      {sides || shownDuel ? (
        <div className={styles.side}>
          {sides}
          {differentials()}
        </div>
      ) : null}
    </div>
  ) : (
    <>
      {score}
      {sides}
      {fresh}
      {flow(true)}
    </>
  );
}

/**
 * The score's head, from its top to Canlı puan: the GOL board stands clear of it while it is
 * in view, and its points run into the total (`data-live-total`), which counts to each value it
 * is given. Opening the page again on a newer read, it counts from the total last seen, once
 * the opening cover has gone, as the rows count from theirs.
 */
function ScoreCardPart({
  board,
  net,
  plan,
  gate,
}: {
  board: LiveBoard;
  net: number;
  plan: MotionPlan | null;
  gate: MotionGate;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const chip = board.chip === null ? null : (messages.leagueMembers.chipNames[board.chip] ?? null);
  const start =
    plan !== null && plan.reopen
      ? { from: plan.netFrom, key: `${plan.token}:total`, ready: gate === "open" }
      : null;
  return (
    <section className={styles.score} aria-label={copy.livePoints} data-live-head>
      <dl className={styles.scoreGrid}>
        <div className={styles.total}>
          <dt>{copy.livePoints}</dt>
          <dd>
            <span className={styles.totalFigure} data-live-total>
              <LiveNumber
                key={lookKey(board)}
                follow
                value={net}
                start={start}
                format={(value) => wholePoints(value, locale)}
              />
            </span>
          </dd>
        </div>
        <div className={styles.cell}>
          <dt>{copy.matches}</dt>
          <dd>
            {wholePoints(board.matchesOver, locale)}/{wholePoints(board.matchesTotal, locale)}
          </dd>
        </div>
        <div className={styles.cell}>
          <dt>{copy.transferHit}</dt>
          <dd>{signedWhole(-board.transferCost, locale)}</dd>
        </div>
        {chip !== null ? (
          <div className={styles.cell}>
            <dt>{messages.leagueMembers.chipLabel}</dt>
            <dd>{chip}</dd>
          </div>
        ) : null}
      </dl>
      <p className={styles.counts}>
        <span className={styles.count} data-state="up">
          <BoardArrow direction="up" />
          <span>
            {wholePoints(board.doingWell, locale)} {copy.doingWell}
          </span>
        </span>
        <span className={styles.count} data-state="down">
          <BoardArrow direction="down" />
          <span>
            {wholePoints(board.struggling, locale)} {copy.struggling}
          </span>
        </span>
      </p>
    </section>
  );
}

function FreshnessPart({
  board,
  refreshing,
  onRefresh,
}: {
  board: LiveBoard;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  return (
    <div className={styles.fresh}>
      <p className={styles.bonus}>{board.final ? copy.bonusAdded : copy.bonusPending}</p>
      <div className={styles.freshEnd}>
        <p className={styles.updated}>
          {copy.updated}{" "}
          <time dateTime={board.sourceTime}>{clockTime(board.sourceTime, locale)}</time>
        </p>
        {/* Nothing is left to read once every match is finished. */}
        {board.final ? null : (
          <Refresh
            refreshing={refreshing}
            onRefresh={onRefresh}
            label={refreshing ? copy.refreshing : copy.refresh}
          />
        )}
      </div>
    </div>
  );
}

/**
 * Yenile. Kept focusable while it reads, so keyboard focus and a screen reader keep their place:
 * a press then does nothing. When it goes with focus on it (the week's last read), focus goes to
 * LIVE's heading, as the GOL board gives it back there, never to the page's body.
 */
function Refresh({
  refreshing,
  onRefresh,
  label,
}: {
  refreshing: boolean;
  onRefresh: () => void;
  label: string;
}) {
  const button = useRef<HTMLButtonElement>(null);
  useLayoutEffect(
    () => () => {
      const element = button.current;
      if (element === null || document.activeElement !== element) return;
      const heading = element.closest("[data-live-page]")?.querySelector<HTMLElement>("h1");
      if (heading === null || heading === undefined) return;
      if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
      heading.focus({ preventScroll: true });
    },
    [],
  );
  return (
    <button
      ref={button}
      type="button"
      className={styles.refresh}
      onClick={() => {
        if (!refreshing) onRefresh();
      }}
      aria-disabled={refreshing || undefined}
      data-live-refresh
    >
      {label}
    </button>
  );
}

/**
 * A ball per goal, an A per assist and a card: three drawn, then the count. A row's glyphs
 * (`marked`) carry what its motion finds them by.
 */
function Glyphs({
  goals,
  assists,
  card,
  marked = false,
}: {
  goals: number;
  assists: number;
  card: boolean;
  marked?: boolean;
}) {
  const mark = (kind: string) => (marked ? kind : undefined);
  const repeat = (count: number, kind: string, glyph: (index: number) => ReactNode) =>
    count <= 3 ? (
      Array.from({ length: count }, (_, index) => glyph(index))
    ) : (
      <>
        {glyph(0)}
        <span className={styles.times} data-live-glyph={mark(`${kind}-more`)}>
          ×{count}
        </span>
      </>
    );
  if (goals === 0 && assists === 0 && !card) return null;
  return (
    <span className={styles.glyphs}>
      {repeat(goals, "goal", (index) => (
        <BallIcon key={`g${index}`} glyph={mark("goal")} />
      ))}
      {repeat(assists, "assist", (index) => (
        <span key={`a${index}`} className={styles.assist} data-live-glyph={mark("assist")}>
          A
        </span>
      ))}
      {card ? <span className={styles.card} data-live-glyph={mark("card")} /> : null}
    </span>
  );
}

function BallIcon({ className = styles.ball, glyph }: { className?: string; glyph?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      data-live-glyph={glyph}
    >
      <circle cx="8" cy="8" r="7" />
      <path className={styles.patch} d="M8 4.6l2.6 1.9-1 3.1H6.4l-1-3.1z" />
      <path
        className={styles.seams}
        d="M8 1v3.6M10.6 6.5l3.6-1.2M9.6 9.6l2 3.1M6.4 9.6l-2 3.1M5.4 6.5L1.8 5.3"
      />
    </svg>
  );
}

function RowPart({ row }: { row: LiveRow }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  // A pick the scorer does not count brings the member nothing: its row tells no event and no
  // state, neither in words nor in its edge and arrow.
  const state = row.counted ? row.state : null;
  const arrow = state === "up" ? "up" : state === "down" ? "down" : null;
  return (
    <li
      className={styles.row}
      aria-label={rowLabel(row, messages, locale)}
      data-live-row={row.elementId}
      data-state={state ?? undefined}
      data-counted={row.counted ? "" : undefined}
    >
      <span className={styles.edge} data-live-edge="" aria-hidden="true" />
      <span className={styles.rowBody} aria-hidden="true" data-live-body="">
        <ClubShirt
          code={row.code}
          name={row.fullName}
          keeper={row.position === "GK"}
          size="large"
          className={styles.shirt}
        />
        <span className={styles.rowText}>
          <span className={styles.rowName}>
            <span className={styles.name}>{row.name}</span>
            {row.armband === "captain" ? (
              <span className={styles.armband} data-live-armband="">
                {messages.leagueMembers.captainMark}
                {row.multiplier >= 2 ? (
                  <span className={styles.times}> ×{row.multiplier}</span>
                ) : null}
              </span>
            ) : row.armband === "vice" ? (
              <span className={styles.vice}>{messages.leagueMembers.viceMark}</span>
            ) : null}
            {row.autosub !== null ? (
              <span className={styles.autosub} data-autosub={row.autosub}>
                {row.autosub === "in" ? messages.leagueMembers.in : messages.leagueMembers.out}
              </span>
            ) : null}
            {row.phase === "playing" ? <span className={styles.dot} /> : null}
            {row.counted ? (
              <Glyphs goals={row.goals} assists={row.assists} card={row.card} marked />
            ) : null}
          </span>
          <span className={styles.subLine}>{subLine(row, copy, locale)}</span>
        </span>
        <span className={styles.points} data-live-points="">
          {row.started ? (
            <LiveNumber
              className={styles.pointsValue}
              value={rowPoints(row)}
              format={(value) => wholePoints(value, locale)}
            />
          ) : (
            <span className={styles.pointsValue}>–</span>
          )}
          <span className={styles.arrow} data-live-arrow="">
            {arrow ? <BoardArrow direction={arrow} /> : null}
          </span>
        </span>
      </span>
    </li>
  );
}

function GroupsPart({ board, ref }: { board: LiveBoard; ref?: Ref<HTMLDivElement> }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const id = useId();
  return (
    <div ref={ref} className={styles.groups}>
      {LIVE_GROUPS.map((group: LiveGroup) => {
        const rows = board.groups[group];
        if (rows.length === 0) return null;
        const heading = `${id}-${group}`;
        return (
          <section key={group} className={styles.group} aria-labelledby={heading}>
            <h2 className={styles.groupTitle} id={heading} data-live-group={group}>
              {group === "playing" ? <span className={styles.dot} aria-hidden="true" /> : null}
              <span>{copy.groups[group]}</span>
              {group === "bench" ? null : (
                <span className={styles.groupCount}>{wholePoints(rows.length, locale)}</span>
              )}
            </h2>
            <ul className={styles.rows}>
              {rows.map((row) => (
                <Row key={row.elementId} row={row} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function RecapPart({ items, ref }: { items: readonly RecapItem[]; ref?: Ref<HTMLElement> }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const id = useId();
  return (
    <section ref={ref} className={styles.recap} aria-labelledby={id}>
      <h2 className={styles.sectionTitle} id={id}>
        {copy.sinceLastLook}
      </h2>
      <ul className={styles.recapList}>
        {items.map((item) => (
          <li
            key={item.elementId}
            className={styles.recapItem}
            data-live-recap-item={item.elementId}
            aria-label={[
              item.name,
              item.goals > 0 ? `${copy.goal} ${wholePoints(item.goals, locale)}` : null,
              item.assists > 0 ? `${copy.assist} ${wholePoints(item.assists, locale)}` : null,
              item.card ? copy.card : null,
              item.change !== 0 ? signedWhole(item.change, locale) : null,
            ]
              .filter((part): part is string => part !== null)
              .join(", ")}
          >
            <span className={styles.recapBody} aria-hidden="true">
              <Glyphs goals={item.goals} assists={item.assists} card={item.card} />
              <span className={styles.name}>{item.name}</span>
              {item.change !== 0 ? (
                <span className={styles.change} data-sign={item.change > 0 ? "up" : "down"}>
                  {signedWhole(item.change, locale)}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface FlowRefs {
  recap: RefObject<HTMLElement | null>;
  groups: RefObject<HTMLDivElement | null>;
  after: RefObject<HTMLDetailsElement | null>;
}

interface FlowProps {
  plan: MotionPlan | null;
  gate: MotionGate;
  locale: string;
  /** The recap's items, in order: a change in them may move what stands below. */
  recapKey: string;
  children: (refs: FlowRefs) => ReactNode;
}

interface FlowSnapshot {
  /** Where the groups' top stood on the screen before the change, and the phone bar's bottom. */
  groupsTop: number;
  barBottom: number;
  /** What the visitor may be reading, likeliest first (`readingAnchors`). */
  anchors: Place[];
  /** On a read: each row's, heading's and Farklar's top on the screen before the change. */
  places: Map<string, number> | null;
  recapKey: string;
  /** Where each of the recap's names stood in it before the change. */
  recapPlaces: Map<string, readonly [number, number]>;
}

/** A row's own changes for a plan drawn while the page waited, held at their first frame. */
interface HeldRow {
  row: HTMLElement;
  motion: RowMotion;
  animations: Animation[];
}

/** A scroll by the visitor this recently is theirs: the page keeps its hands off. */
const SCROLL_QUIET_MS = 150;
const SCROLL_INPUTS = ["pointerdown", "touchmove", "wheel", "keydown"] as const;
const SCROLL_SETTLEMENT_FRAMES = 4;

/** The groups' rows and headings, and Farklar, each by a key that outlives a change of group. */
function partsOf(groups: HTMLElement, after: HTMLElement | null): [string, HTMLElement][] {
  const parts: [string, HTMLElement][] = [];
  for (const row of groups.querySelectorAll<HTMLElement>("[data-live-row]")) {
    parts.push([`row:${row.dataset.liveRow}`, row]);
  }
  for (const heading of groups.querySelectorAll<HTMLElement>("[data-live-group]")) {
    parts.push([`group:${heading.dataset.liveGroup}`, heading]);
  }
  if (after !== null) parts.push(["after", after]);
  return parts;
}

const topOf = (element: Element) => element.getBoundingClientRect().top;

/** Where each of the recap's names stands in it: across, and down, by element id. */
function recapPlaces(recap: HTMLElement | null): Map<string, readonly [number, number]> {
  const places = new Map<string, readonly [number, number]>();
  if (recap === null) return places;
  const origin = recap.getBoundingClientRect();
  for (const item of recap.querySelectorAll<HTMLElement>("[data-live-recap-item]")) {
    const box = item.getBoundingClientRect();
    places.set(item.dataset.liveRecapItem ?? "", [box.left - origin.left, box.top - origin.top]);
  }
  return places;
}

/** The bottom of the phone's top bar, which covers the page under it; 0 without one. */
function barBottom(): number {
  return document.querySelector("[data-phone-bar]")?.getBoundingClientRect().bottom ?? 0;
}

/** Nothing covers the page: a read's motion may be seen. */
function pageClear(): boolean {
  return (
    document.visibilityState !== "hidden" &&
    document.querySelector("dialog[open], [aria-modal='true']") === null
  );
}

/** A newer read's plan, not the one drawn before (nor the same read given its duel later). */
const newPlan = (plan: MotionPlan | null, before: MotionPlan | null): plan is MotionPlan =>
  plan !== null && plan.token !== before?.token;

/**
 * The recap, the groups and, on one column, Farklar below them: the one place that sees them
 * both before and after a change.
 *
 * - Where the visitor reads past the groups' top, the part they read stays where it was on the
 *   screen, whatever changed above it (the recap, a group that came or went, a row that grew):
 *   the page scrolls by the change, under reduced motion too, unless the visitor scrolled it in
 *   the last moment.
 * - A read drawn slides every row, heading and Farklar from where it stood to its new place,
 *   the rows over the headings they cross (a new heading comes into view); where the groups'
 *   top is in sight and the recap above it changed, the groups glide from where they stood,
 *   and what the recap gained comes into view. A look's clearing of the recap jumps.
 * - It plays the rows' own changes for the read (`playRow`), once; drawn while the page waits
 *   (the opening cover, a hidden tab), they are held at their first frame until it is seen.
 */
class LiveFlow extends Component<FlowProps> {
  // Not `refs`: React keeps a field of that name on every class component.
  private readonly parts: FlowRefs = {
    recap: createRef(),
    groups: createRef(),
    after: createRef(),
  };
  /** The plan whose rows this part has taken: its own remount plays them no second time. */
  private played: string | null = null;
  private held: HeldRow[] = [];
  private heldTimes: MotionTimes | null = null;
  /** The reads whose slides run: the last to end takes off what they put on the groups. */
  private sliding = 0;
  private scrolledAt = Number.NEGATIVE_INFINITY;
  private ownScroll = false;
  private scrollSettlement: number | null = null;

  private readonly cancelScrollSettlement = () => {
    if (this.scrollSettlement === null) return;
    window.cancelAnimationFrame(this.scrollSettlement);
    this.scrollSettlement = null;
  };

  private readonly onScroll = () => {
    if (this.ownScroll) {
      this.ownScroll = false;
      return;
    }
    this.scrolledAt = performance.now();
  };

  componentDidMount() {
    window.addEventListener("scroll", this.onScroll, { passive: true });
    for (const input of SCROLL_INPUTS) {
      window.addEventListener(input, this.cancelScrollSettlement, { capture: true, passive: true });
    }
    this.decorate();
  }

  componentWillUnmount() {
    window.removeEventListener("scroll", this.onScroll);
    for (const input of SCROLL_INPUTS) {
      window.removeEventListener(input, this.cancelScrollSettlement, true);
    }
    this.cancelScrollSettlement();
    this.drop();
  }

  getSnapshotBeforeUpdate(previous: FlowProps): FlowSnapshot | null {
    const groups = this.parts.groups.current;
    if (groups === null) return null;
    const { plan, gate } = this.props;
    const read = newPlan(plan, previous.plan);
    const bar = barBottom();
    const groupsTop = topOf(groups);
    const tops = partsOf(groups, this.parts.after.current).map(
      ([part, element]) => [part, topOf(element)] as const,
    );
    // A row the read takes to another group is not what the visitor goes on reading.
    const anchors = readingAnchors(
      tops,
      bar,
      groupsTop,
      (part) =>
        read && part.startsWith("row:") && plan.rows.get(Number(part.slice(4)))?.moved === true,
    );
    return {
      groupsTop,
      barBottom: bar,
      anchors,
      places: read && gate === "open" ? new Map(tops) : null,
      recapKey: previous.recapKey,
      recapPlaces: recapPlaces(this.parts.recap.current),
    };
  }

  componentDidUpdate(previous: FlowProps, _state: unknown, snapshot: FlowSnapshot | null) {
    const { plan, gate } = this.props;
    const groups = this.parts.groups.current;
    const read = newPlan(plan, previous.plan);
    if (read) this.cancelScrollSettlement();
    if (snapshot !== null && groups !== null) {
      const parts = partsOf(groups, this.parts.after.current);
      // Where everything stands after the change, before the page moves anything.
      const now = new Map(parts.map(([part, element]) => [part, topOf(element)]));
      const groupsNow = topOf(groups);
      const scrolled = this.keep(snapshot, now);
      const times = read && gate === "open" && pageClear() ? motionTimes(groups) : null;
      let glide = 0;
      if (times !== null && scrolled === 0 && snapshot.groupsTop > snapshot.barBottom) {
        glide = snapshot.groupsTop - groupsNow;
        if (Math.abs(glide) < 1) glide = 0;
        else {
          groups.animate(
            [{ transform: `translateY(${glide}px)` }, { transform: "translateY(0px)" }],
            { duration: times.data, easing: LIVE_EASE },
          );
        }
      }
      if (times !== null && snapshot.places !== null) {
        const settledScroll = window.scrollY;
        this.slide(groups, parts, snapshot.places, now, scrolled, glide, times);
        if (scrolled !== 0) this.settleScroll(settledScroll);
      }
      if (times !== null && snapshot.recapKey !== this.props.recapKey) {
        this.reveal(snapshot.recapKey, snapshot.recapPlaces, times);
      }
    }
    if (plan?.token !== previous.plan?.token || previous.gate !== gate) this.decorate();
  }

  /**
   * The part the visitor reads stays where it was: the page scrolls by how far it moved.
   * Returns how far the page scrolled.
   */
  private keep(snapshot: FlowSnapshot, now: Map<string, number>): number {
    const by = keepBy(snapshot.anchors, now);
    // A pan or a fling scrolls every frame: the visitor moving the page keeps it.
    if (by === 0 || performance.now() - this.scrolledAt < SCROLL_QUIET_MS) return 0;
    const from = window.scrollY;
    this.ownScroll = true;
    window.scrollBy({ top: by, left: 0, behavior: "instant" });
    const moved = window.scrollY - from;
    if (moved === 0) this.ownScroll = false;
    else this.cancelScrollSettlement();
    return moved;
  }

  /**
   * WebKit can move the document again as the row transforms first change its scrollable
   * overflow. Restore the position that the browser accepted before those transforms.
   * WebKit can adjust the scroll after the first two frames, so check the first four.
   * Visitor input cancels any remaining checks.
   */
  private settleScroll(top: number) {
    let framesLeft = SCROLL_SETTLEMENT_FRAMES;
    const check = () => {
      this.scrollSettlement = null;
      if (!pageClear()) return;
      const from = window.scrollY;
      if (Math.abs(from - top) >= 1) {
        this.ownScroll = true;
        window.scrollTo({ top, left: 0, behavior: "instant" });
        if (window.scrollY === from) this.ownScroll = false;
      }
      framesLeft -= 1;
      if (framesLeft === 0) return;
      this.scrollSettlement = window.requestAnimationFrame(check);
    };
    this.scrollSettlement = window.requestAnimationFrame(check);
  }

  /**
   * Each row, heading and Farklar slides from where it stood on the screen to its new place,
   * the page's scroll and the groups' glide taken into account; a new heading comes into view.
   * While they slide, the rows pass over the headings that cross them, and a row that changes
   * group over the rows it crosses; nothing of it stays once they have all ended.
   */
  private slide(
    groups: HTMLElement,
    parts: [string, HTMLElement][],
    before: Map<string, number>,
    now: Map<string, number>,
    scrolled: number,
    glide: number,
    times: MotionTimes,
  ) {
    const plan = this.props.plan;
    const slides: Animation[] = [];
    for (const [part, element] of parts) {
      const was = before.get(part);
      if (was === undefined) {
        if (part.startsWith("group:")) {
          element.animate(APPEAR, { duration: times.data, easing: LIVE_EASE });
        }
        continue;
      }
      // Farklar stands outside the groups, so their glide does not carry it.
      const shift = was - now.get(part)! + scrolled - (part === "after" ? 0 : glide);
      if (Math.abs(shift) < 1) continue;
      slides.push(
        element.animate(
          [{ transform: `translateY(${shift}px)` }, { transform: "translateY(0px)" }],
          { duration: times.data, easing: LIVE_EASE },
        ),
      );
      if (part.startsWith("row:") && plan?.rows.get(Number(part.slice(4)))?.moved) {
        element.dataset.liveCrossing = "";
      }
    }
    if (slides.length === 0) return;
    groups.dataset.liveSliding = "";
    const run = (this.sliding += 1);
    const ended = () => {
      if (run !== this.sliding) return;
      delete groups.dataset.liveSliding;
      for (const row of groups.querySelectorAll<HTMLElement>("[data-live-crossing]")) {
        delete row.dataset.liveCrossing;
      }
    };
    void Promise.allSettled(slides.map((slide) => slide.finished)).then(ended);
  }

  /**
   * What the recap gained comes into view once what stood there has slid away: a recap that was
   * not there comes in whole, its heading with its names; one that was, the names it gained and
   * those it moved along its line together, so none stands alone in a new place meanwhile.
   */
  private reveal(
    before: string,
    places: Map<string, readonly [number, number]>,
    times: MotionTimes,
  ) {
    const recap = this.parts.recap.current;
    if (recap === null) return;
    const timing = {
      duration: times.ui,
      delay: times.ui,
      easing: LIVE_EASE,
      fill: "backwards" as const,
    };
    if (before === "") {
      recap.animate(APPEAR, timing);
      return;
    }
    const now = recapPlaces(recap);
    for (const item of recap.querySelectorAll<HTMLElement>("[data-live-recap-item]")) {
      const was = places.get(item.dataset.liveRecapItem ?? "");
      const at = now.get(item.dataset.liveRecapItem ?? "");
      const moved =
        was === undefined ||
        at === undefined ||
        Math.abs(was[0] - at[0]) >= 1 ||
        Math.abs(was[1] - at[1]) >= 1;
      if (moved) item.animate(APPEAR, timing);
    }
  }

  /**
   * The rows' own changes for the plan drawn: once, by whichever part takes the plan first, so
   * a remount after the 1024 px turn plays nothing again. While the page waits (the opening
   * cover, a hidden tab) they are held at their first frame, and play once it is seen.
   */
  private decorate() {
    const { plan, gate, locale } = this.props;
    const groups = this.parts.groups.current;
    const key = plan === null ? null : `${plan.token}:rows`;
    // Rows held for a plan no longer drawn take their end at once.
    if (this.played !== key) this.drop();
    if (plan === null || key === null || groups === null) return;
    if (this.played === key) {
      if (gate === "open") this.release(locale);
      return;
    }
    if (!claimMotion(key)) return;
    this.played = key;
    const times = motionTimes(groups);
    if (times === null || (gate === "open" && !pageClear())) return;
    for (const [id, motion] of plan.rows) {
      const row = groups.querySelector<HTMLElement>(`[data-live-row='${id}']`);
      if (row === null) continue;
      if (gate === "open") playRow(row, motion, times, locale);
      else this.held.push({ row, motion, animations: holdRow(row, motion, times, locale) });
    }
    this.heldTimes = times;
  }

  /** The rows held while the page waited play now it is seen; under a dialog they just end. */
  private release(locale: string) {
    const { held, heldTimes: times } = this;
    this.held = [];
    if (times === null) return;
    const clear = pageClear();
    for (const { row, motion, animations } of held) {
      // One its figure stopped meanwhile (written again, in another language) stays stopped.
      for (const animation of animations) {
        if (animation.playState !== "paused") continue;
        if (clear) animation.play();
        else animation.finish();
      }
      if (clear) lightRow(row, motion, times, locale);
    }
  }

  /** Held rows that will not play take their end state. */
  private drop() {
    for (const { animations } of this.held) {
      for (const animation of animations) animation.cancel();
    }
    this.held = [];
  }

  render() {
    return this.props.children(this.parts);
  }
}

/**
 * Where the duel stands, drawn: the track's middle is level, and the ball rests on the side
 * of the one ahead, further the more they lead, never at the end; each side's fill runs from
 * the middle to the ball. Decoration only; the words beside it say the same.
 */
function DuelBar({ margin, ref }: { margin: number; ref?: Ref<HTMLDivElement> }) {
  const offset = ballOffset(margin);
  const fills = fillScales(offset);
  return (
    <div ref={ref} className={styles.bar} aria-hidden="true">
      <span className={styles.track} />
      <span
        className={styles.fill}
        data-live-fill="member"
        style={{ transform: `scaleX(${fills.member})` }}
      />
      <span
        className={styles.fill}
        data-live-fill="rival"
        style={{ transform: `scaleX(${fills.rival})` }}
      />
      <span className={styles.centre} />
      <span className={styles.lane} data-live-lane="" style={{ transform: laneTransform(offset) }}>
        <span className={styles.barBall} data-live-ball="">
          <BallIcon className={styles.barBallIcon} />
        </span>
      </span>
    </div>
  );
}

function RivalBlockPart({
  rival,
  own,
  net,
  team,
  plan,
  gate,
}: {
  rival: LiveRivalView;
  own: boolean;
  /** The member's net in the read the duel comes from. */
  net: number;
  team: string;
  plan: MotionPlan | null;
  gate: MotionGate;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const id = useId();
  // The new rival's duel, or the last one kept out of sight while it is read.
  const pending = rival.duel === null ? rival.pending : null;
  const duel = rival.duel ?? pending?.duel ?? null;
  const rivalNet = rival.board?.net ?? pending?.rivalNet ?? null;
  const margin = duel?.margin ?? 0;
  const totalGap = duel?.totalGap ?? null;
  // The week's opponent is named so; any other member, in any league, is a rival.
  const label = rival.opponent ? copy.opponent : copy.rival;
  const whole = (value: number) => countedWhole(value, locale);
  const word = copy.status[duelStatus(margin)];
  const gapText = signedWhole(margin, locale);
  // The line's place: drawn only beside a duel, so it is written again each time it is drawn.
  const drawn = duel !== null && rivalNet !== null;
  const bar = useRef<HTMLDivElement>(null);
  const status = useRef<HTMLElement>(null);
  const points = useRef<HTMLSpanElement>(null);
  const ends = useRef<HTMLParagraphElement>(null);
  const gap = useRef<HTMLSpanElement>(null);
  const rolling = useRef<Animation[]>([]);
  /** The roll is held at its first frame while the page waits. */
  const held = useRef(false);
  const played = useRef<string | null>(null);
  // The line above the bar, Önde, Berabere or Geride and Fark, written here: while the figures
  // count to a read that changed the margin, it says the duel they show, the read before's,
  // until they land (`spoken.held`).
  const spoken = useRef({ word, gap: gapText, held: false, turn: 0, from: 0 });
  const motion = plan?.duel ?? null;
  const token = plan?.token ?? null;
  // The duel moves for a read drawn with the same rival it was drawn with before, once.
  const shown = rival.duel !== null && rival.board !== null ? rival.entryId : null;
  /** Writes the line: the word and Fark. */
  const say = (said: string, fark: string) => {
    if (status.current !== null) status.current.textContent = said;
    if (gap.current !== null) gap.current.textContent = fark;
  };
  useLayoutEffect(() => {
    spoken.current.word = word;
    spoken.current.gap = gapText;
    const { held, from } = spoken.current;
    // Held, it says the read before's duel, in the language shown now.
    if (held) say(copy.status[duelStatus(from)], signedWhole(from, locale));
    else say(word, gapText);
  }, [word, gapText, drawn, copy, locale]);
  useLayoutEffect(() => {
    /** The line as the duel drawn says it, held no longer. */
    const speak = () => {
      spoken.current.turn += 1;
      spoken.current.held = false;
      say(spoken.current.word, spoken.current.gap);
    };
    if (motion === null || shown !== motion.rivalId) {
      // Another rival drawn while the duel rolled: its roll stops, never to play again.
      for (const animation of rolling.current) animation.cancel();
      rolling.current = [];
      held.current = false;
      if (spoken.current.held) speak();
    }
    if (motion === null || token === null || shown !== motion.rivalId) return;
    const key = `${token}:duel`;
    if (played.current === key) {
      // Held at its first frame while the page waited: it plays now the page is seen.
      if (gate === "open" && held.current) {
        held.current = false;
        const clear = pageClear();
        for (const animation of rolling.current) {
          if (animation.playState !== "paused") continue;
          if (clear) animation.play();
          else animation.finish();
        }
      }
      return;
    }
    // Once, by whichever part takes the plan first: its own remount (React's strict check)
    // finds it rolling, and a remount after the 1024 px turn plays nothing again.
    if (!claimMotion(key)) return;
    played.current = key;
    // A roll an earlier plan still holds, never played (two reads in one wait), gives way.
    for (const animation of rolling.current) {
      if (animation.playState === "paused") animation.cancel();
    }
    held.current = false;
    const element = bar.current;
    const times = motionTimes(element);
    if (times === null || element === null || (gate === "open" && !pageClear())) return;
    if (spoken.current.held) speak();
    const running = playDuel(element, motion.marginFrom, margin, times);
    const count = (target: HTMLElement | null | undefined, from: number) => {
      if (target === null || target === undefined) return null;
      const counted = countLive(target, from, Number(target.dataset.value), whole, times.uiFast);
      if (counted !== null) running.push(counted);
      return counted;
    };
    const figure = (side: string) =>
      ends.current?.querySelector<HTMLElement>(`[data-live-end='${side}'] [data-live-number]`);
    const counts = [
      count(points.current?.querySelector<HTMLElement>("[data-live-number]"), motion.rivalNetFrom),
      count(figure("member"), motion.memberNetFrom),
      count(figure("rival"), motion.rivalNetFrom),
    ].filter((counted) => counted !== null);
    if (motion.marginFrom !== margin) {
      // The line changes as the figures land; the word pops where it changed.
      const turn = (spoken.current.turn += 1);
      spoken.current.held = true;
      spoken.current.from = motion.marginFrom;
      say(copy.status[duelStatus(motion.marginFrom)], signedWhole(motion.marginFrom, locale));
      const land = (pop: boolean) => {
        if (spoken.current.turn !== turn) return;
        speak();
        const target = status.current;
        if (!pop || !motion.statusChanged || target === null || !pageClear()) return;
        rolling.current.push(
          target.animate(MODEL_POP, { duration: times.data, easing: LIVE_EASE }),
        );
      };
      // Landed when every figure has; one stopped (another read, another rival) stops it.
      Promise.all(counts.map((counted) => counted.finished)).then(
        () => land(true),
        () => land(false),
      );
    }
    if (gate === "wait") {
      for (const animation of running) animation.pause();
      held.current = true;
    }
    rolling.current = running;
    // Played once per plan; the figures and the margin are read as they stand then.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, gate, shown]);
  // A roll held for a page that never showed it ends with the part.
  useLayoutEffect(
    () => () => {
      if (!held.current) return;
      for (const animation of rolling.current) animation.cancel();
    },
    [],
  );
  return (
    <section className={styles.rival} aria-labelledby={`${id}-label`} data-live-rival>
      <div className={styles.rivalHead}>
        <label className={styles.rivalLabel} id={`${id}-label`} htmlFor={`${id}-select`}>
          {label}
        </label>
        {rival.opponent ? <span className={styles.badge}>{copy.h2h}</span> : null}
        <select
          id={`${id}-select`}
          className={styles.select}
          value={rival.entryId ?? ""}
          onChange={(event) => rival.onSelect(Number(event.currentTarget.value))}
        >
          {rival.entryId === null ? <option value="" disabled /> : null}
          {rival.choices.map((choice) => (
            <option key={choice.entryId} value={choice.entryId}>
              {choice.name}
            </option>
          ))}
        </select>
        {/* While the next rival is read, the last one's points keep their room, out of sight. */}
        {rival.board !== null || rivalNet !== null ? (
          <span
            ref={points}
            className={styles.rivalPoints}
            data-live-rival-net
            data-pending={rival.board === null || undefined}
            aria-hidden={rival.board === null || undefined}
          >
            <LiveNumber value={rival.board?.net ?? rivalNet ?? 0} format={whole} />
          </span>
        ) : null}
      </div>
      {duel !== null && rivalNet !== null ? (
        <div
          className={styles.duel}
          data-pending={pending !== null || undefined}
          aria-hidden={pending !== null || undefined}
        >
          <p className={styles.status}>
            <strong ref={status} data-live-status="" />
            {" · "}
            {copy.margin} <span ref={gap} className={styles.figure} data-live-margin="" />
          </p>
          <DuelBar ref={bar} margin={margin} />
          <p ref={ends} className={styles.ends}>
            <span className={styles.endMember} data-live-end="member">
              {own ? copy.you : team} <LiveNumber value={net} format={whole} />
            </span>
            <span className={styles.endRival} data-live-end="rival">
              <LiveNumber value={rivalNet} format={whole} /> {rival.name}
            </span>
          </p>
          <dl className={styles.duelCells}>
            <div>
              <dt>{copy.playersLeft}</dt>
              <dd>
                {wholePoints(duel.left.member, locale)} · {wholePoints(duel.left.rival, locale)}
              </dd>
            </div>
            {totalGap !== null ? (
              <div>
                <dt>{copy.totalGap}</dt>
                <dd>{signedWhole(totalGap, locale)}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}
    </section>
  );
}

function SwingList({
  title,
  swings,
  side,
}: {
  title: string;
  swings: readonly DuelSwing[];
  side: "member" | "rival";
}) {
  const { locale, messages } = useLanguage();
  const id = useId();
  return (
    <section className={styles.swings} aria-labelledby={id}>
      <h3 className={styles.swingsTitle} id={id}>
        {title}
      </h3>
      {swings.length === 0 ? <p className={styles.none}>–</p> : null}
      <ul className={styles.swingList}>
        {swings.map((swing) => {
          const gain = side === "member" ? swing.swing : -swing.swing;
          const multiplier = side === "member" ? swing.member : swing.rival;
          return (
            <li key={swing.elementId} className={styles.swing}>
              <ClubShirt
                code={swing.row.code}
                name={swing.row.fullName}
                keeper={swing.row.position === "GK"}
                size="small"
              />
              <span className={styles.name}>{swing.row.name}</span>
              {multiplier >= 2 ? (
                <span className={styles.armband}>
                  {messages.leagueMembers.captainMark}
                  <span className={styles.times}> ×{multiplier}</span>
                </span>
              ) : null}
              <span className={styles.swingValue}>{signedWhole(gain, locale)}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * Farklar, open or closed as the member last left it (the page keeps that choice across a
 * rival's change); while the next rival is read, the last one's lists hold their place out
 * of sight.
 */
function DifferentialsPart({
  duel,
  pending,
  own,
  team,
  rival,
  open,
  onToggle,
  ref,
}: {
  duel: LiveDuel;
  pending: boolean;
  own: boolean;
  team: string;
  rival: LiveRivalView;
  open: boolean;
  onToggle: (open: boolean) => void;
  ref?: Ref<HTMLDetailsElement>;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  return (
    <details
      ref={ref}
      className={styles.differentials}
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) onToggle(event.currentTarget.open);
      }}
      data-live-differentials
    >
      <summary className={styles.summary}>
        <DisclosureIcon className={styles.disclosure} />
        {/* A heading of its own, so its two lists are not read as the last group's. */}
        <h2 className={styles.summaryTitle}>{copy.differentials}</h2>
        {pending ? null : (
          <span className={styles.groupCount}>
            {wholePoints(duel.yours.length + duel.theirs.length, locale)}
          </span>
        )}
      </summary>
      <div
        className={styles.swingBody}
        data-pending={pending || undefined}
        aria-hidden={pending || undefined}
      >
        <div className={styles.swingColumns}>
          <SwingList title={own ? copy.yours : team} swings={duel.yours} side="member" />
          <SwingList
            title={own ? copy.theirs : (rival.name ?? copy.rival)}
            swings={duel.theirs}
            side="rival"
          />
        </div>
        <p className={styles.shared}>
          {copy.shared} · {copy.players(duel.shared)}
        </p>
      </div>
    </details>
  );
}

// Each part is drawn again only when what it shows changes: a GOL board's landing changes
// Canlı puan alone, so the rows, the recap and the rival's side are not drawn again for it.
const ScoreCard = memo(ScoreCardPart);
const Freshness = memo(FreshnessPart);
const Row = memo(RowPart);
const Groups = memo(GroupsPart);
const Recap = memo(RecapPart);
const RivalBlock = memo(RivalBlockPart);
const Differentials = memo(DifferentialsPart);
