import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { PageLoading } from "../../../design/components/PageLoading";
import { useLanguage } from "../../../i18n/context";
import { entryAddress, memberAddress } from "../../../lib/leagueAddresses";
import { useFixtures } from "../../fixtures/data";
import { capabilitiesForPage } from "../advice/adviceCapabilities";
import { createAdviceClient, type AdviceRequest } from "../advice/adviceClient";
import { gameweekDeadline, useMinuteClock } from "../advice/deadline";
import { useAdviceJob } from "../advice/useAdviceJob";
import { LEAGUE_READ, useEntrySquad } from "../queries";
import type { EntrySquad } from "../types";
import { useLeague } from "../useLeague";
import { LLMOPT_COPY } from "./copy";
import {
  EMPTY_DRAFT,
  IntentError,
  MAX_MESSAGE_LENGTH,
  preparePlans,
  readIntent,
  readIntentCatalog,
  type Clarification,
  type PlanDraft,
} from "./intent";
import { PlanResult } from "./PlanResult";
import { samePlan } from "./planComparison";
import { RuleEditor } from "./RuleEditor";
import styles from "./LLMOptPage.module.css";

const ORIGIN = (import.meta.env.VITE_ADVICE_API_ORIGIN ?? "").replace(/\/$/, "");

function squadBasis(squad: EntrySquad) {
  return JSON.stringify([
    squad.source_snapshot_id,
    squad.season,
    squad.gameweek,
    squad.league_id,
    squad.entry.entry_id,
    squad.squad_basis,
    squad.free_transfers,
    squad.free_transfers_known,
    squad.bank_tenths,
    squad.squad_sell_value_tenths,
    squad.purchase_prices_known,
    [...squad.starting_xi, ...squad.bench].map(({ player_id }) => player_id).sort((a, b) => a - b),
  ]);
}

function isWorking(phase: string) {
  return phase === "requesting" || phase === "waiting";
}

interface ChatLine {
  id: number;
  role: "user" | "assistant";
  message: string;
}

function Session({ squad }: { squad: EntrySquad }) {
  const { language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const { tree, forwarded } = useLeague();
  const now = useMinuteClock();
  const fixtures = useFixtures();
  const deadline = gameweekDeadline(fixtures.data, squad.season, squad.gameweek);
  const closed = deadline !== null && now >= Date.parse(deadline);
  const roster = useQuery({
    queryKey: ["llmopt-roster", ORIGIN, squad.season, squad.source_snapshot_id],
    queryFn: ({ signal }) => readIntentCatalog(ORIGIN, squad.season, signal),
    enabled: !!ORIGIN,
    ...LEAGUE_READ,
  });
  const owned = [...squad.starting_xi, ...squad.bench];
  const held = new Set(owned.map(({ player_id }) => player_id));
  const players = (
    roster.data ?? owned.map((p) => ({ id: p.player_id, name: p.name, team: p.team }))
  ).map((p) => ({ ...p, held: held.has(p.id) }));
  const client = useMemo(() => createAdviceClient(tree.entryAdvice), [tree]);
  const base = useAdviceJob(client, false, squad.source_snapshot_id, true);
  const alternative = useAdviceJob(client, false, squad.source_snapshot_id, true);
  const [draft, setDraft] = useState<PlanDraft>(EMPTY_DRAFT);
  const [message, setMessage] = useState("");
  const [conversation, setConversation] = useState<ChatLine[]>([]);
  const [clarification, setClarification] = useState<Clarification>();
  const [feedback, setFeedback] = useState("");
  const [checkingSquad, setCheckingSquad] = useState(false);
  const [basisChanged, setBasisChanged] = useState(false);
  const [reading, setReading] = useState(false);
  const [calculated, setCalculated] = useState(false);
  const interpret = useRef<AbortController | null>(null);
  const nextChatLine = useRef(0);
  const confirming = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      interpret.current?.abort();
    };
  }, []);

  function change(next: PlanDraft) {
    base.reset();
    alternative.reset();
    setCalculated(false);
    setFeedback("");
    setClarification(undefined);
    setDraft(next);
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (!text || !ORIGIN || interpret.current || checkingSquad || roster.isPending) return;
    const controller = new AbortController();
    interpret.current = controller;
    setReading(true);
    setFeedback("");
    try {
      const answer = await readIntent(
        ORIGIN,
        text,
        language,
        draft,
        players,
        controller.signal,
        clarification,
      );
      if (controller.signal.aborted) return;
      if (answer.status === "draft") change(answer.draft);
      else setClarification({ message: clarification?.message ?? text, question: answer.message });
      const reply = answer.status === "clarification" ? answer.message : copy.understood;
      const userLine = nextChatLine.current++;
      const replyLine = nextChatLine.current++;
      setConversation((before) => [
        ...before.slice(-18),
        { id: userLine, role: "user", message: text },
        { id: replyLine, role: "assistant", message: reply },
      ]);
      setMessage("");
    } catch (error) {
      if (!controller.signal.aborted)
        setFeedback(
          error instanceof IntentError && error.status === 429
            ? copy.limited
            : copy.intentUnavailable,
        );
    } finally {
      if (interpret.current === controller) interpret.current = null;
      if (!controller.signal.aborted) setReading(false);
    }
  }

  const plans = preparePlans(draft, held);
  const computing = isWorking(base.state.phase) || isWorking(alternative.state.phase);
  const busy = checkingSquad || reading || computing;
  const compareBoth = draft.comparison?.both === true;
  const baseTitle = compareBoth ? copy.without : copy.base;
  const alternativeTitle = compareBoth
    ? copy.with
    : draft.comparison
      ? copy.alternative
      : copy.preferred;

  async function compute() {
    if (
      busy ||
      confirming.current ||
      clarification !== undefined ||
      !ORIGIN ||
      !squad.source_snapshot_id ||
      deadline === null ||
      Date.now() >= Date.parse(deadline) ||
      plans.hardConflict ||
      (!plans.base && !plans.alternative)
    )
      return;
    confirming.current = true;
    setFeedback("");
    setCheckingSquad(true);
    try {
      const [fresh, capabilities] = await Promise.all([
        tree.entrySquad(squad.entry.entry_id),
        forwarded
          ? client.readPublicCapabilities?.(squad.league_id, squad.entry.entry_id)
          : client.readCapabilities?.(squad.league_id),
      ]);
      if (!mounted.current) return;
      if (!capabilities?.preferences || !capabilities.strategies["saf-puan"]?.windows.includes(1)) {
        setFeedback(copy.serviceUnavailable);
        return;
      }
      if (
        squadBasis(fresh.payload) !== squadBasis(squad) ||
        !capabilitiesForPage(capabilities, {
          leagueId: squad.league_id,
          season: squad.season,
          gameweek: squad.gameweek,
          snapshotId: squad.source_snapshot_id,
        }) ||
        Date.now() >= Date.parse(deadline)
      ) {
        setBasisChanged(true);
        setCalculated(false);
        return;
      }
      const request: AdviceRequest = {
        publicEntry: forwarded,
        leagueId: squad.league_id,
        entryId: squad.entry.entry_id,
        strategy: "saf-puan",
        window: 1,
        season: squad.season,
        gameweek: squad.gameweek,
      };
      setCalculated(true);
      if (plans.base) {
        base.compute({ ...request, preferences: plans.base });
      }
      if (plans.alternative) alternative.compute({ ...request, preferences: plans.alternative });
    } catch {
      if (mounted.current) setFeedback(copy.squadUnavailable);
    } finally {
      confirming.current = false;
      if (mounted.current) setCheckingSquad(false);
    }
  }

  const same = samePlan(base.state, alternative.state);
  const baseAnswer = base.state.phase === "done" ? base.state.envelope.payload : undefined;
  const hasAlternative = plans.alternative !== null || plans.alternativeConflict;
  const team = squad.entry.team_name ?? squad.entry.manager_name;
  const teamPath =
    squad.league_id === 0
      ? entryAddress(squad.entry.entry_id)
      : memberAddress(squad.league_id, squad.entry.entry_id);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link to={teamPath}>{copy.back}</Link>
        <h1>LLMOPT</h1>
        <p>
          {team ? `${team} · ` : ""}
          {copy.week} {squad.gameweek}
        </p>
      </header>
      <p className={styles.muted}>{copy.chipScope}</p>
      {!ORIGIN && (
        <p className={styles.notice} role="status">
          {copy.serviceUnavailable}
        </p>
      )}
      {ORIGIN && roster.isError && (
        <p className={styles.notice} role="status">
          {copy.rosterUnavailable}{" "}
          <button className={styles.textButton} onClick={() => void roster.refetch()} type="button">
            {copy.retry}
          </button>
        </p>
      )}
      <section className={styles.workspace} aria-label={copy.chat}>
        {conversation.length > 0 && (
          <ol className={styles.conversation} aria-live="polite">
            {conversation.map(({ id, role, message }) => (
              <li key={id} data-role={role}>
                <strong>{role === "user" ? copy.user : "LLMOPT"}</strong>
                <span>{message}</span>
              </li>
            ))}
          </ol>
        )}
        <form className={styles.chat} onSubmit={(event) => void send(event)}>
          <label htmlFor="llmopt-message">{copy.chat}</label>
          <textarea
            id="llmopt-message"
            placeholder={copy.placeholder}
            value={message}
            maxLength={MAX_MESSAGE_LENGTH}
            rows={2}
            onChange={(event) => setMessage(event.target.value)}
            disabled={!ORIGIN || reading || checkingSquad}
          />
          <button
            className={styles.primary}
            type="submit"
            disabled={!ORIGIN || busy || roster.isPending || !message.trim()}
          >
            {reading ? copy.interpreting : copy.send}
          </button>
          {clarification && (
            <button
              className={styles.secondary}
              type="button"
              disabled={busy}
              onClick={() => setClarification(undefined)}
            >
              {copy.dismissQuestion}
            </button>
          )}
        </form>
        {feedback && (
          <p role="status" className={styles.notice}>
            {feedback}
          </p>
        )}
        <RuleEditor draft={draft} players={players} copy={copy} disabled={busy} change={change} />
        {draft.comparison && draft.soft.length > 0 && (
          <p className={styles.muted}>{copy.comparisonScope}</p>
        )}
        {plans.hardConflict && (
          <p role="alert" className={styles.notice}>
            {copy.hardConflict}
          </p>
        )}
        {closed && (
          <p role="status" className={styles.notice}>
            {copy.deadline}
          </p>
        )}
        {fixtures.isError && deadline === null && (
          <p role="status" className={styles.notice}>
            {copy.deadlineUnknown}
          </p>
        )}
        <button
          className={styles.primary}
          type="button"
          disabled={
            busy ||
            clarification !== undefined ||
            !ORIGIN ||
            !squad.source_snapshot_id ||
            closed ||
            deadline === null ||
            plans.hardConflict ||
            (!plans.base && !plans.alternative) ||
            basisChanged
          }
          onClick={() => void compute()}
        >
          {checkingSquad ? copy.checkSquad : computing ? copy.computing : copy.compute}
        </button>
        {basisChanged && (
          <p className={styles.notice} role="status">
            {copy.newSquad}{" "}
            <button
              type="button"
              className={styles.textButton}
              onClick={() => window.location.reload()}
            >
              {copy.reload}
            </button>
          </p>
        )}
      </section>
      {calculated && (
        <section className={styles.results} aria-label={copy.results} aria-busy={computing}>
          <h2>{copy.results}</h2>
          <div className={styles.planGrid}>
            <PlanResult title={baseTitle} state={base.state} conflict={plans.baseConflict} />
            {hasAlternative && !same && (
              <PlanResult
                title={alternativeTitle}
                state={alternative.state}
                baseline={baseAnswer}
                conflict={plans.alternativeConflict}
              />
            )}
          </div>
          {same && (
            <p role="status" className={styles.muted}>
              {copy.same}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

export function LLMOptPage() {
  const { messages, language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const { entryId: entryParam } = useParams();
  const entryId = Number(entryParam);
  const valid = Number.isSafeInteger(entryId) && entryId > 0;
  const result = useEntrySquad(entryId, valid);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (result.isPending) return <PageLoading label={messages.common.loading} />;
  if (result.isError) return <EmptyState page title={copy.squadUnavailable} />;
  return <Session key={squadBasis(result.data.payload)} squad={result.data.payload} />;
}
