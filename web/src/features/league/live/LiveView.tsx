/**
 * The LIVE page as it is drawn (the synthesis of 2026-11-11, section 3.2): the member's live
 * score and counts, one rival beside it, when the week was read, what the newest read
 * changed, the fifteen grouped by their match, and the players the duel turns on.
 *
 * A phone reads one column: the header, the score, the rival, the read, the recap, the
 * groups and Farklar, closed. From 1024 px the rival and Farklar, open, stand in a column of
 * their own beside the rest, in that order in the document as on the screen. Display only:
 * every number comes scored from the page.
 */

import { useId, useState, type ReactNode } from "react";

import { useShellLayout } from "../../../design/shell/layout";
import { useLanguage } from "../../../i18n/context";
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
import type { DuelSwing, LiveDuel } from "./liveDuel";
import { clockTime, kickoffShort, signedWhole, wholePoints } from "./liveFormat";
import type { RivalChoice } from "./liveRival";
import styles from "./LivePage.module.css";

type Copy = ReturnType<typeof useLanguage>["messages"];

/** The rival side as the page has it: who, the choices, and the duel once both are scored. */
export interface LiveRivalView {
  choices: readonly RivalChoice[];
  /** The chosen rival, or null while none is chosen yet. */
  entryId: number | null;
  name: string | null;
  board: LiveBoard | null;
  duel: LiveDuel | null;
  /** The league is head-to-head: the rival is named the opponent there. */
  headToHead: boolean;
  /** The rival is the member's opponent of the live week. */
  opponent: boolean;
  onSelect: (entryId: number) => void;
}

export interface LiveViewProps {
  /** The member's team, named under the heading. */
  team: string;
  /** The gameweek the board is for, once known. */
  gameweek: number | null;
  /** One of the member's matches is being played: the heading's light is on. */
  playing: boolean;
  state: "loading" | "empty" | "board";
  board: LiveBoard | null;
  recap: readonly RecapItem[];
  /** The page is the visitor's own: its side reads "Sen". */
  own: boolean;
  rival: LiveRivalView | null;
  refreshing: boolean;
  onRefresh: () => void;
  /** Two columns, from 1024 px. */
  wide: boolean;
}

export function LiveView(props: LiveViewProps) {
  const { messages } = useLanguage();
  const copy = messages.live;
  const { board, rival, wide, state } = props;
  const header = (
    <header className={styles.header}>
      <h1 className={styles.title}>
        {copy.title}
        {props.playing ? (
          <span className={styles.light} role="img" aria-label={copy.matchInProgress} />
        ) : null}
      </h1>
      {props.team === "" ? null : (
        <p className={styles.subtitle}>
          {props.gameweek === null
            ? props.team
            : `${props.team} · ${messages.suggestionHistory.gameweek(props.gameweek)}`}
        </p>
      )}
    </header>
  );
  if (state !== "board" || board === null) {
    return (
      <div className={styles.page}>
        {header}
        <p className={styles.state} role="status">
          {state === "loading" ? messages.common.loading : messages.leagueMembers.toolEmpty}
        </p>
      </div>
    );
  }
  const score = <ScoreCard board={board} />;
  const fresh = (
    <Freshness board={board} refreshing={props.refreshing} onRefresh={props.onRefresh} />
  );
  const recap = props.recap.length > 0 ? <Recap items={props.recap} /> : null;
  const groups = <Groups board={board} />;
  const sides =
    rival === null ? null : (
      <RivalBlock rival={rival} own={props.own} board={board} team={props.team} />
    );
  const differentials =
    rival?.duel != null ? (
      <Differentials
        duel={rival.duel}
        own={props.own}
        team={props.team}
        rival={rival}
        wide={wide}
      />
    ) : null;
  return (
    <div className={styles.page} data-live-page data-wide={wide || undefined}>
      {wide ? (
        <div className={styles.columns}>
          <div className={styles.column}>
            {header}
            {score}
            {fresh}
            {recap}
            {groups}
          </div>
          {sides || differentials ? (
            <div className={styles.side}>
              {sides}
              {differentials}
            </div>
          ) : null}
        </div>
      ) : (
        <>
          {header}
          {score}
          {sides}
          {fresh}
          {recap}
          {groups}
          {differentials}
        </>
      )}
    </div>
  );
}

function ScoreCard({ board }: { board: LiveBoard }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const chip = board.chip === null ? null : (messages.leagueMembers.chipNames[board.chip] ?? null);
  return (
    <section className={styles.score} aria-label={copy.livePoints}>
      <dl className={styles.scoreGrid}>
        <div className={styles.total}>
          <dt>{copy.livePoints}</dt>
          <dd data-live-net>{wholePoints(board.net, locale)}</dd>
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

function Freshness({
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
            onClick={onRefresh}
            disabled={refreshing}
            data-live-refresh
          >
            {refreshing ? copy.refreshing : copy.refresh}
          </button>
        )}
      </div>
    </div>
  );
}

/** A ball per goal, an A per assist and a card: three drawn, then the count. */
function Glyphs({ goals, assists, card }: { goals: number; assists: number; card: boolean }) {
  const repeat = (count: number, glyph: (index: number) => ReactNode) =>
    count <= 3 ? (
      Array.from({ length: count }, (_, index) => glyph(index))
    ) : (
      <>
        {glyph(0)}
        <span className={styles.times}>×{count}</span>
      </>
    );
  if (goals === 0 && assists === 0 && !card) return null;
  return (
    <span className={styles.glyphs}>
      {repeat(goals, (index) => (
        <BallIcon key={`g${index}`} />
      ))}
      {repeat(assists, (index) => (
        <span key={`a${index}`} className={styles.assist}>
          A
        </span>
      ))}
      {card ? <span className={styles.card} /> : null}
    </span>
  );
}

function BallIcon({ className = styles.ball }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="7" />
      <path className={styles.patch} d="M8 4.6l2.6 1.9-1 3.1H6.4l-1-3.1z" />
      <path
        className={styles.seams}
        d="M8 1v3.6M10.6 6.5l3.6-1.2M9.6 9.6l2 3.1M6.4 9.6l-2 3.1M5.4 6.5L1.8 5.3"
      />
    </svg>
  );
}

/** What a pick's row says to a screen reader: name, role, group, points, events and state. */
function rowLabel(row: LiveRow, copy: Copy, locale: string): string {
  const live = copy.live;
  const roles: string[] = [];
  if (row.armband === "captain") {
    roles.push(
      row.multiplier >= 2
        ? `${copy.leagueMembers.captainLabel} ×${row.multiplier}`
        : copy.leagueMembers.captainLabel,
    );
  } else if (row.armband === "vice") {
    roles.push(copy.leagueMembers.viceCaptainLabel);
  }
  if (row.autosub !== null) {
    roles.push(row.autosub === "in" ? copy.leagueMembers.in : copy.leagueMembers.out);
  }
  const events = [
    row.goals > 0 ? `${live.goal} ${wholePoints(row.goals, locale)}` : null,
    row.assists > 0 ? `${live.assist} ${wholePoints(row.assists, locale)}` : null,
    row.card ? live.card : null,
  ];
  const state =
    row.fact === "noMatch"
      ? live.noMatch
      : row.fact === "didNotPlay"
        ? live.didNotPlay
        : row.state === "up"
          ? live.doingWell
          : row.state === "down"
            ? live.struggling
            : null;
  return [
    row.name,
    ...roles,
    live.groups[row.group],
    row.started ? live.points(wholePoints(rowPoints(row), locale)) : null,
    ...events,
    state,
  ]
    .filter((part): part is string => part !== null)
    .join(", ");
}

/** The opponent, then the kickoff before the match or the minutes once it has started. */
function subLine(row: LiveRow, copy: Copy["live"], locale: string): string {
  if (row.fact === "noMatch" || row.fixture === null) return copy.noMatch;
  const fixture = row.fixture;
  const minutes = fixture.minutes ?? row.minutes;
  const when =
    row.fact === "didNotPlay"
      ? copy.didNotPlay
      : fixture.phase === "upcoming" && minutes === 0
        ? fixture.kickoff === null
          ? null
          : kickoffShort(fixture.kickoff, locale)
        : copy.minutes(wholePoints(minutes, locale));
  return [fixture.opponent, when].filter((part): part is string => part !== null).join(" · ");
}

function Row({ row }: { row: LiveRow }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const arrow = row.state === "up" ? "up" : row.state === "down" ? "down" : null;
  return (
    <li
      className={styles.row}
      aria-label={rowLabel(row, messages, locale)}
      data-live-row={row.elementId}
      data-state={row.state ?? undefined}
      data-counted={row.counted ? "" : undefined}
    >
      <span className={styles.rowBody} aria-hidden="true">
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
              <span className={styles.armband}>
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
            <Glyphs goals={row.goals} assists={row.assists} card={row.card} />
          </span>
          <span className={styles.subLine}>{subLine(row, copy, locale)}</span>
        </span>
        <span className={styles.points}>
          <span className={styles.pointsValue}>
            {row.started ? wholePoints(rowPoints(row), locale) : "–"}
          </span>
          <span className={styles.arrow}>{arrow ? <BoardArrow direction={arrow} /> : null}</span>
        </span>
      </span>
    </li>
  );
}

function Groups({ board }: { board: LiveBoard }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const id = useId();
  return (
    <div className={styles.groups}>
      {LIVE_GROUPS.map((group: LiveGroup) => {
        const rows = board.groups[group];
        if (rows.length === 0) return null;
        const heading = `${id}-${group}`;
        return (
          <section key={group} className={styles.group} aria-labelledby={heading}>
            <h2 className={styles.groupTitle} id={heading}>
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

function Recap({ items }: { items: readonly RecapItem[] }) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const id = useId();
  return (
    <section className={styles.recap} aria-labelledby={id}>
      <h2 className={styles.sectionTitle} id={id}>
        {copy.sinceLastLook}
      </h2>
      <ul className={styles.recapList}>
        {items.map((item) => (
          <li
            key={item.elementId}
            className={styles.recapItem}
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

/**
 * Where the duel stands, drawn: the track's middle is level, and the ball rests on the side
 * of the one ahead, further the more they lead, never at the end. Decoration only; the words
 * beside it say the same.
 */
function DuelBar({ margin }: { margin: number }) {
  const share = margin / (Math.abs(margin) + 20);
  const ball = 50 - share * 44;
  return (
    <div
      className={styles.bar}
      aria-hidden="true"
      data-lead={margin > 0 ? "member" : margin < 0 ? "rival" : undefined}
    >
      <span className={styles.track} />
      <span
        className={styles.lead}
        style={{ left: `${Math.min(ball, 50)}%`, width: `${Math.abs(50 - ball)}%` }}
      />
      <span className={styles.centre} />
      <span className={styles.barBall} style={{ left: `${ball}%` }}>
        <BallIcon className={styles.barBallIcon} />
      </span>
    </div>
  );
}

function RivalBlock({
  rival,
  own,
  board,
  team,
}: {
  rival: LiveRivalView;
  own: boolean;
  board: LiveBoard;
  team: string;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  const id = useId();
  const duel = rival.duel;
  const label = rival.headToHead ? copy.opponent : copy.rival;
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
        {rival.board !== null ? (
          <span className={styles.rivalPoints} data-live-rival-net>
            {wholePoints(rival.board.net, locale)}
          </span>
        ) : null}
      </div>
      {duel !== null ? (
        <>
          <p className={styles.status}>
            <strong>{copy.status[duel.status]}</strong>
            {" · "}
            {copy.margin} <span className={styles.figure}>{signedWhole(duel.margin, locale)}</span>
          </p>
          <DuelBar margin={duel.margin} />
          <p className={styles.ends}>
            <span className={styles.endMember}>
              {own ? copy.you : team} {wholePoints(board.net, locale)}
            </span>
            <span className={styles.endRival}>
              {wholePoints(rival.board!.net, locale)} {rival.name}
            </span>
          </p>
          <dl className={styles.duelCells}>
            <div>
              <dt>{copy.playersLeft}</dt>
              <dd>
                {wholePoints(duel.left.member, locale)} · {wholePoints(duel.left.rival, locale)}
              </dd>
            </div>
            {duel.totalGap !== null ? (
              <div>
                <dt>{copy.totalGap}</dt>
                <dd>{signedWhole(duel.totalGap, locale)}</dd>
              </div>
            ) : null}
          </dl>
        </>
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

function Differentials({
  duel,
  own,
  team,
  rival,
  wide,
}: {
  duel: LiveDuel;
  own: boolean;
  team: string;
  rival: LiveRivalView;
  wide: boolean;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.live;
  // Closed on a phone, open on a tablet and beside the page; the member's own choice then stands.
  const layout = useShellLayout();
  const [open, setOpen] = useState(wide || layout !== "phone");
  return (
    <details
      className={styles.differentials}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      data-live-differentials
    >
      <summary className={styles.summary}>
        <DisclosureIcon className={styles.disclosure} />
        <span>{copy.differentials}</span>
        <span className={styles.groupCount}>
          {wholePoints(duel.yours.length + duel.theirs.length, locale)}
        </span>
      </summary>
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
    </details>
  );
}
