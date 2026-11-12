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
import { clockTime, signedWhole, wholePoints } from "./liveFormat";
import type { LiveLight } from "./liveLight";
import {
  APPEAR,
  LIVE_EASE,
  ballOffset,
  claimMotion,
  countLive,
  fillScales,
  laneTransform,
  lookKey,
  motionTimes,
  playDuel,
  playRow,
  releaseMotion,
  type MotionGate,
  type MotionPlan,
} from "./liveMotion";
import { LiveNumber } from "./LiveNumber";
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
 * is given. Opening the page again on a newer read, it holds the total last seen until the
 * opening cover has gone, then counts on from it.
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
  const total = plan !== null && plan.reopen && gate === "wait" ? plan.netFrom : net;
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
                value={total}
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
          <button
            type="button"
            className={styles.refresh}
            // Kept focusable while it reads, so keyboard focus and a screen reader keep their
            // place: a press then does nothing.
            onClick={() => {
              if (!refreshing) onRefresh();
            }}
            aria-disabled={refreshing || undefined}
            data-live-refresh
          >
            {refreshing ? copy.refreshing : copy.refresh}
          </button>
        )}
      </div>
    </div>
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
  /** Where the groups' top stood on the screen, and the phone bar's bottom, before the change. */
  groupsTop: number;
  barBottom: number;
  /** Each row and group heading's place in the groups, before a read's change. */
  places: Map<string, number> | null;
  recapKey: string;
}

/** A scroll by the visitor this recently is theirs: the page keeps its hands off. */
const SCROLL_QUIET_MS = 150;

/** Each row's and group heading's top, from the groups' own. */
function placesIn(groups: HTMLElement): Map<string, number> {
  const top = groups.getBoundingClientRect().top;
  const places = new Map<string, number>();
  for (const row of groups.querySelectorAll<HTMLElement>("[data-live-row]")) {
    places.set(`row:${row.dataset.liveRow}`, row.getBoundingClientRect().top - top);
  }
  for (const heading of groups.querySelectorAll<HTMLElement>("[data-live-group]")) {
    places.set(`group:${heading.dataset.liveGroup}`, heading.getBoundingClientRect().top - top);
  }
  return places;
}

/** The bottom of the phone's top bar, which covers the page under it; 0 without one. */
function barBottom(): number {
  return document.querySelector("[data-phone-bar]")?.getBoundingClientRect().bottom ?? 0;
}

/** Nothing covers the page and it is in view: a read's motion may be seen. */
function pageClear(): boolean {
  return (
    document.visibilityState !== "hidden" &&
    document.querySelector("dialog[open], [aria-modal='true']") === null
  );
}

/**
 * The recap, the groups and, on one column, Farklar below them: the one place that sees them
 * both before and after a change. A read drawn slides each row that changed group to its new
 * place from where it stood, and plays the rows' own changes; the recap's growing or clearing
 * keeps the rows where the visitor reads them when the recap is out of sight above, or, on a
 * read, glides what stands below it into place. Under reduced motion nothing slides or glides;
 * the place is still kept.
 */
class LiveFlow extends Component<FlowProps> {
  // Not `refs`: React keeps a field of that name on every class component.
  private readonly parts: FlowRefs = {
    recap: createRef(),
    groups: createRef(),
    after: createRef(),
  };
  private running: Animation[] = [];
  private claim: string | null = null;
  private touching = false;
  private scrolledAt = Number.NEGATIVE_INFINITY;
  private ownScroll = false;

  private readonly onTouchStart = () => {
    this.touching = true;
  };
  private readonly onTouchEnd = () => {
    this.touching = false;
  };
  private readonly onScroll = () => {
    if (this.ownScroll) {
      this.ownScroll = false;
      return;
    }
    this.scrolledAt = performance.now();
  };

  componentDidMount() {
    window.addEventListener("touchstart", this.onTouchStart, { passive: true });
    window.addEventListener("touchend", this.onTouchEnd, { passive: true });
    window.addEventListener("touchcancel", this.onTouchEnd, { passive: true });
    window.addEventListener("scroll", this.onScroll, { passive: true });
    this.decorate();
  }

  componentWillUnmount() {
    window.removeEventListener("touchstart", this.onTouchStart);
    window.removeEventListener("touchend", this.onTouchEnd);
    window.removeEventListener("touchcancel", this.onTouchEnd);
    window.removeEventListener("scroll", this.onScroll);
    this.stop();
  }

  getSnapshotBeforeUpdate(previous: FlowProps): FlowSnapshot | null {
    const groups = this.parts.groups.current;
    if (groups === null) return null;
    const read = this.props.plan !== null && this.props.plan !== previous.plan;
    return {
      groupsTop: groups.getBoundingClientRect().top,
      barBottom: barBottom(),
      places: read && this.props.gate === "open" ? placesIn(groups) : null,
      recapKey: previous.recapKey,
    };
  }

  componentDidUpdate(previous: FlowProps, _state: unknown, snapshot: FlowSnapshot | null) {
    const groups = this.parts.groups.current;
    const read = this.props.plan !== null && this.props.plan !== previous.plan;
    if (snapshot !== null && groups !== null) {
      const moved = groups.getBoundingClientRect().top - snapshot.groupsTop;
      if (Math.abs(moved) >= 1) this.keep(groups, moved, snapshot, read);
      const times = read && pageClear() ? motionTimes(groups) : null;
      if (times !== null && snapshot.places !== null) this.slide(groups, snapshot.places, times);
      if (times !== null && snapshot.recapKey !== this.props.recapKey) {
        this.reveal(snapshot.recapKey, times);
      }
    }
    if (read || previous.gate !== this.props.gate) this.decorate();
  }

  /** The groups moved on the screen by `moved` px because what stands above them changed. */
  private keep(groups: HTMLElement, moved: number, snapshot: FlowSnapshot, read: boolean) {
    if (snapshot.groupsTop <= snapshot.barBottom) {
      // The change is out of sight above: the rows stay where the visitor reads them, unless
      // the visitor is moving the page themselves.
      if (this.touching || performance.now() - this.scrolledAt < SCROLL_QUIET_MS) return;
      this.ownScroll = true;
      window.scrollBy({ top: moved, left: 0, behavior: "instant" });
      return;
    }
    // In sight, only a read glides what stands below the change into place; a look jumps.
    const times = read && pageClear() ? motionTimes(groups) : null;
    if (times === null) return;
    for (const part of [groups, this.parts.after.current]) {
      if (part === null) continue;
      this.running.push(
        part.animate([{ transform: `translateY(${-moved}px)` }, { transform: "translateY(0px)" }], {
          duration: times.data,
          easing: LIVE_EASE,
        }),
      );
    }
  }

  /** Each row and heading slides from where it stood to its new place; a new heading appears. */
  private slide(
    groups: HTMLElement,
    before: Map<string, number>,
    times: NonNullable<ReturnType<typeof motionTimes>>,
  ) {
    const plan = this.props.plan;
    const top = groups.getBoundingClientRect().top;
    const parts = [
      ...groups.querySelectorAll<HTMLElement>("[data-live-row]"),
      ...groups.querySelectorAll<HTMLElement>("[data-live-group]"),
    ];
    for (const part of parts) {
      const row = part.dataset.liveRow;
      const key = row !== undefined ? `row:${row}` : `group:${part.dataset.liveGroup}`;
      const was = before.get(key);
      if (was === undefined) {
        if (row === undefined) {
          this.running.push(part.animate(APPEAR, { duration: times.data, easing: LIVE_EASE }));
        }
        continue;
      }
      const shift = was - (part.getBoundingClientRect().top - top);
      if (Math.abs(shift) < 1) continue;
      const slide = part.animate(
        [{ transform: `translateY(${shift}px)` }, { transform: "translateY(0px)" }],
        { duration: times.data, easing: LIVE_EASE },
      );
      this.running.push(slide);
      // A row that changes group passes over the rows it crosses.
      if (row !== undefined && plan?.rows.get(Number(row))?.moved) {
        part.style.zIndex = "1";
        const lower = () => {
          part.style.removeProperty("z-index");
        };
        slide.finished.then(lower, lower);
      }
    }
  }

  /** The recap's new names come into view once what stands below has started to move. */
  private reveal(before: string, times: NonNullable<ReturnType<typeof motionTimes>>) {
    const recap = this.parts.recap.current;
    if (recap === null) return;
    const had = new Set(before.split(","));
    for (const item of recap.querySelectorAll<HTMLElement>("[data-live-recap-item]")) {
      if (had.has(item.dataset.liveRecapItem ?? "")) continue;
      this.running.push(
        item.animate(APPEAR, {
          duration: times.ui,
          delay: times.ui,
          easing: LIVE_EASE,
          fill: "backwards",
        }),
      );
    }
  }

  /** The rows' own changes for the plan drawn, once the cover has gone; once per plan. */
  private decorate() {
    const { plan, gate, locale } = this.props;
    const groups = this.parts.groups.current;
    if (plan === null || gate === "wait" || groups === null) return;
    const key = `${plan.token}:rows`;
    if (!claimMotion(key)) return;
    this.claim = key;
    const times = pageClear() ? motionTimes(groups) : null;
    if (times === null) return;
    for (const [id, motion] of plan.rows) {
      const row = groups.querySelector<HTMLElement>(`[data-live-row='${id}']`);
      if (row !== null) this.running.push(...playRow(row, motion, times, locale));
    }
  }

  /** Stops what is running; a plan stopped before it ended may play again on the next mount. */
  private stop() {
    const unfinished = this.running.some((animation) => animation.playState !== "finished");
    for (const animation of this.running) animation.cancel();
    this.running = [];
    if (unfinished && this.claim !== null) releaseMotion(this.claim);
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
  const whole = (value: number) => wholePoints(value, locale);
  const bar = useRef<HTMLDivElement>(null);
  const status = useRef<HTMLElement>(null);
  const points = useRef<HTMLSpanElement>(null);
  const ends = useRef<HTMLParagraphElement>(null);
  const motion = plan?.duel ?? null;
  const token = plan?.token ?? null;
  // The duel moves for a read drawn with the same rival it was drawn with before, once.
  const shown = rival.duel !== null && rival.board !== null ? rival.entryId : null;
  useLayoutEffect(() => {
    if (motion === null || token === null || gate === "wait" || shown !== motion.rivalId) {
      return undefined;
    }
    const key = `${token}:duel`;
    if (!claimMotion(key)) return undefined;
    const element = bar.current;
    const times = pageClear() ? motionTimes(element) : null;
    if (times === null || element === null) return undefined;
    const running = playDuel(element, motion.marginFrom, margin, times);
    const later = times.uiFast;
    const figure = (selector: string, from: number) => {
      const target = ends.current?.querySelector<HTMLElement>(selector) ?? null;
      if (target !== null) countLive(target, from, Number(target.dataset.value), whole, later);
    };
    const rivalFigure = points.current?.querySelector<HTMLElement>("[data-live-number]");
    if (rivalFigure) {
      countLive(rivalFigure, motion.rivalNetFrom, Number(rivalFigure.dataset.value), whole, later);
    }
    figure("[data-live-end='member'] [data-live-number]", motion.memberNetFrom);
    figure("[data-live-end='rival'] [data-live-number]", motion.rivalNetFrom);
    if (motion.statusChanged && status.current !== null) {
      running.push(
        status.current.animate(MODEL_POP, {
          duration: times.data,
          delay: times.data,
          easing: LIVE_EASE,
        }),
      );
    }
    return () => {
      const unfinished = running.some((animation) => animation.playState !== "finished");
      for (const animation of running) animation.cancel();
      if (unfinished) releaseMotion(key);
    };
    // Played once per plan; the figures and the margin are read as they stand then.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, gate, shown]);
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
            <strong ref={status} data-live-status="">
              {copy.status[duelStatus(margin)]}
            </strong>
            {" · "}
            {copy.margin} <span className={styles.figure}>{signedWhole(margin, locale)}</span>
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
