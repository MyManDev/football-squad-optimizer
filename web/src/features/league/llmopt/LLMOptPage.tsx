import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { PageLoading } from "../../../design/components/PageLoading";
import { useLanguage } from "../../../i18n/context";
import { money } from "../../../lib/format";
import { entryAddress, memberAddress } from "../../../lib/leagueAddresses";
import { useFixtures } from "../../fixtures/data";
import { capabilitiesForPage } from "../advice/adviceCapabilities";
import { createAdviceClient } from "../advice/adviceClient";
import { gameweekDeadline, useDeadlineClock } from "../advice/deadline";
import type { ComputePhase } from "../advice/useAdviceJob";
import { LEAGUE_READ, useEntrySquad } from "../queries";
import type { EntryAdvice, EntrySquad } from "../types";
import { useLeague } from "../useLeague";
import { LLMOPT_COPY, ruleLabel } from "./copy";
import { InfeasibilityResult } from "./InfeasibilityResult";
import {
  EMPTY_DRAFT,
  IntentError,
  MAX_MESSAGE_LENGTH,
  intentRefusal,
  needsThreeWeeks,
  preparePlans,
  readIntentCatalog,
  type CatalogPlayer,
  type Clarification,
  type Constraint,
  type PlanDraft,
} from "./intent";
import { serverIntentSource, type IntentSource } from "./intentSource";
import { PlanResult } from "./PlanResult";
import { BANK_FLOOR, KEEP_WEEK, SCENARIO, draftChanges, type DraftChanges } from "./planChanges";
import { explainDraftConflict } from "./planConflicts";
import { planResults, preferencePrice } from "./planResults";
import {
  referenceCaptains,
  referenceWeeks,
  summarizeRevision,
  type PlanRevision,
} from "./planRevision";
import {
  baseDraft,
  prepareRun,
  requestFor,
  restoreRun,
  type BaseTitle,
  type ExplicitTitle,
  type PlanRequest,
  type PlanRun,
} from "./planRun";
import { frozenForDraft, matchingScenarioReference, scenarioLabel } from "./planScenario";
import {
  checkedPlanSession,
  createPlanSessionStore,
  readPlanSession,
  type PlanSessionContext,
} from "./planSession";
import {
  ALTERNATIVE_SLOTS,
  alternativeStates,
  followupRequests,
  isWorking,
  restoredSlot,
  usePlanJobs,
  type JobControls,
} from "./planSlots";
import { RevisionComparison } from "./RevisionComparison";
import { ChangeMark, RemovedRule, RuleEditor } from "./RuleEditor";
import { ScenarioComparison } from "./ScenarioComparison";
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

function deadlineOpen(deadline: string | null) {
  return deadline !== null && Date.now() < Date.parse(deadline);
}

interface ChatLine {
  id: number;
  role: "user" | "assistant";
  message: string;
}

function Session({ squad, intentSource }: { squad: EntrySquad; intentSource: IntentSource }) {
  const { messages } = useLanguage();
  const { forwarded } = useLeague();
  const fixtures = useFixtures();
  const deadline = gameweekDeadline(fixtures.data, squad.season, squad.gameweek);
  const roster = useQuery({
    queryKey: ["llmopt-roster", ORIGIN, squad.season, squad.source_snapshot_id],
    queryFn: ({ signal }) => readIntentCatalog(ORIGIN, squad.season, signal),
    enabled: !!ORIGIN,
    ...LEAGUE_READ,
  });
  const context =
    ORIGIN && deadline && squad.source_snapshot_id
      ? {
          key: `squadopt.llmopt:${JSON.stringify([ORIGIN, forwarded === true, squad.league_id, squad.entry.entry_id])}`,
          basis: squadBasis(squad),
          deadline,
        }
      : null;
  const saved = context ? readPlanSession(context) : null;
  if (fixtures.isPending || (saved && roster.isPending))
    return <PageLoading label={messages.common.loading} />;
  // A saved session that names a player outside the squad needs the roster to be checked.
  // While the roster read fails, the session is held untouched until a retry reads it.
  if (saved && roster.isError && !checkedPlanSession(saved, ownedPlayers(squad), squad.gameweek))
    return <RosterHold squad={squad} roster={roster} />;
  return (
    <Workspace
      key={context ? `${context.key}:${context.deadline}` : undefined}
      squad={squad}
      deadline={deadline}
      fixturesUnavailable={fixtures.isError}
      roster={roster}
      context={context}
      saved={saved}
      intentSource={intentSource}
    />
  );
}

function ownedPlayers(squad: EntrySquad): CatalogPlayer[] {
  return [...squad.starting_xi, ...squad.bench].map((p) => ({
    id: p.player_id,
    name: p.name,
    team: p.team,
  }));
}

function PageHeader({ squad }: { squad: EntrySquad }) {
  const { language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const team = squad.entry.team_name ?? squad.entry.manager_name;
  const teamPath =
    squad.league_id === 0
      ? entryAddress(squad.entry.entry_id)
      : memberAddress(squad.league_id, squad.entry.entry_id);
  return (
    <header className={styles.header}>
      <Link to={teamPath}>{copy.back}</Link>
      <h1>{copy.title}</h1>
      <p>
        {team ? `${team} · ` : ""}
        {copy.week} {squad.gameweek}
      </p>
    </header>
  );
}

function RosterRetry({ roster }: { roster: UseQueryResult<CatalogPlayer[]> }) {
  const { language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  return (
    <p className={styles.notice} role="status">
      {copy.rosterUnavailable}{" "}
      <button
        className={styles.textButton}
        disabled={roster.isFetching}
        onClick={() => void roster.refetch()}
        type="button"
      >
        {copy.retry}
      </button>
    </p>
  );
}

function RosterHold({
  squad,
  roster,
}: {
  squad: EntrySquad;
  roster: UseQueryResult<CatalogPlayer[]>;
}) {
  return (
    <div className={styles.page} data-zone="llmopt">
      <PageHeader squad={squad} />
      <RosterRetry roster={roster} />
    </div>
  );
}

function Workspace({
  squad,
  deadline,
  fixturesUnavailable,
  roster,
  context,
  saved,
  intentSource,
}: {
  squad: EntrySquad;
  deadline: string | null;
  fixturesUnavailable: boolean;
  roster: UseQueryResult<CatalogPlayer[]>;
  context: PlanSessionContext | null;
  saved: unknown;
  intentSource: IntentSource;
}) {
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const { tree, forwarded } = useLeague();
  const now = useDeadlineClock(deadline);
  const closed = deadline !== null && now >= Date.parse(deadline);
  const owned = [...squad.starting_xi, ...squad.bench];
  const held = new Set(owned.map(({ player_id }) => player_id));
  const players = (roster.data ?? ownedPlayers(squad)).map((p) => ({
    ...p,
    held: held.has(p.id),
  }));
  const client = useMemo(() => createAdviceClient(tree.entryAdvice), [tree]);
  const jobs = usePlanJobs(client, squad.source_snapshot_id);
  const { controls } = jobs;
  const [restored] = useState(() => checkedPlanSession(saved, players, squad.gameweek));
  const [restoredRun] = useState(() =>
    restoreRun(restored, held, (window) => requestFor(squad, forwarded, window)),
  );
  const [draft, setDraft] = useState<PlanDraft>(restored?.draft ?? EMPTY_DRAFT);
  const [reference, setReference] = useState<PlanRevision | undefined>(restored?.reference);
  const [message, setMessage] = useState("");
  const [conversation, setConversation] = useState<ChatLine[]>(() =>
    restored?.clarification
      ? [
          { id: 0, role: "user", message: restored.clarification.message },
          { id: 1, role: "assistant", message: restored.clarification.question },
        ]
      : [],
  );
  const [clarification, setClarification] = useState<Clarification | undefined>(
    restored?.clarification,
  );
  const [feedback, setFeedback] = useState(
    restoredRun?.wildcardUnavailable ? copy.wildcardUnavailable : "",
  );
  const [checkingSquad, setCheckingSquad] = useState(false);
  const [basisChanged, setBasisChanged] = useState(false);
  const [reading, setReading] = useState(false);
  // While a rate limit's Retry-After runs, Send stays off and the wait is shown.
  const [limit, setLimit] = useState<{ seconds: number } | null>(null);
  const [waitLeft, setWaitLeft] = useState(0);
  const [run, setRun] = useState<PlanRun | null>(restoredRun);
  const [changes, setChanges] = useState<DraftChanges | null>(null);
  const [session] = useState(() => createPlanSessionStore(context, restored?.confirmation));
  const chatInput = useRef<HTMLTextAreaElement>(null);
  const computeButton = useRef<HTMLButtonElement>(null);
  const interpret = useRef<AbortController | null>(null);
  const nextChatLine = useRef(conversation.length);
  const confirming = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      interpret.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!limit) return;
    const end = Date.now() + limit.seconds * 1000;
    const timer = window.setInterval(() => {
      const left = Math.ceil((end - Date.now()) / 1000);
      if (left <= 0) setLimit(null);
      else setWaitLeft(left);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [limit]);

  // An edit keeps the plan the member compares against; only Revise picks another. Before any
  // plan was picked, the first edit after a result compares against the plan shown.
  function change(next: PlanDraft, previous = reference ?? revised) {
    for (const job of Object.values(controls)) job.reset();
    setRun(null);
    setFeedback("");
    setClarification(undefined);
    setChanges(null);
    setDraft(next);
    setReference(previous);
    session.save({ draft: next, reference: previous });
  }

  function revisePlan(plan: EntryAdvice) {
    const selected = summarizeRevision(plan);
    if (!selected) return;
    change(draft, selected);
    chatInput.current?.focus();
  }

  function applyRepair(next: PlanDraft) {
    change(next, reference);
    setFeedback(copy.repairApplied);
    computeButton.current?.focus();
  }

  function setQuestion(next?: Clarification) {
    setClarification(next);
    session.save({ draft, reference, clarification: next, confirmation: session.confirmation });
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (!text || !ORIGIN || interpret.current || checkingSquad || roster.isPending || limit) return;
    const controller = new AbortController();
    const previous = reference ?? revised;
    interpret.current = controller;
    setReading(true);
    setFeedback("");
    try {
      const answer = await intentSource.interpret(
        {
          message: text,
          locale: language,
          draft,
          players,
          clarification,
          referenceWeeks: referenceWeeks(previous),
          referenceCaptains: referenceCaptains(previous),
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if (answer.status === "draft") {
        change(answer.draft, previous);
        setChanges(draftChanges(draft, answer.draft));
      } else setQuestion({ message: clarification?.message ?? text, question: answer.message });
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
      if (controller.signal.aborted) return;
      const refusal = intentRefusal(error);
      if (refusal === "limited" && error instanceof IntentError && error.retryAfterSeconds) {
        setWaitLeft(error.retryAfterSeconds);
        setLimit({ seconds: error.retryAfterSeconds });
      } else setFeedback(copy.refusals[refusal]);
    } finally {
      if (interpret.current === controller) interpret.current = null;
      if (!controller.signal.aborted) setReading(false);
    }
  }

  const frozen = frozenForDraft(draft, reference);
  const plans = preparePlans(baseDraft(draft), held, frozen);
  const scenarioReferenceMissing =
    draft.scenario && !matchingScenarioReference(reference, plans.window);
  const canCalculate =
    !scenarioReferenceMissing &&
    !plans.hardConflict &&
    (draft.soft.length > 0 || plans.base || plans.alternative);
  const conflictContext = {
    gameweek: squad.gameweek,
    window: plans.window,
    held,
    frozen,
    players,
    copy,
  };
  const hardConflict = plans.hardConflict
    ? (explainDraftConflict(draft, conflictContext) ?? copy.hardConflict)
    : undefined;

  function explainBranchConflict(title: BaseTitle | ExplicitTitle) {
    if (title === "scenarioOriginal") return copy.scenarioConflict;
    if (title === "scenarioOptimized") return hardConflict;
    const comparison = draft.comparison;
    if (title === "base" || !comparison) return hardConflict;
    const rule: Constraint =
      title === "without" && comparison.kind === "include_player"
        ? { kind: "avoid_player", player_id: comparison.player_id, week: comparison.week }
        : comparison;
    return explainDraftConflict({ ...draft, hard: [...draft.hard, rule] }, conflictContext);
  }

  const { states } = jobs;
  const computing = Object.values(states).some(({ phase }) => isWorking(phase));
  const busy = checkingSquad || reading || computing;
  const replayProof =
    run?.scenario && states.first.phase === "failed" && states.first.infeasibility !== undefined;
  const savedReplayProof =
    run?.scenario && run === restoredRun && restored?.confirmation?.scenarioReplayInfeasible;
  useEffect(() => {
    const confirmed = session.confirmation;
    if (!replayProof || !confirmed || confirmed.scenarioReplayInfeasible) return;
    session.save({
      draft,
      reference,
      clarification,
      confirmation: { ...confirmed, scenarioReplayInfeasible: true },
    });
  }, [replayProof, session, draft, reference, clarification]);
  // Once every request of the run has a job or an answer, a reload resumes or reads it.
  // Before a restored run has started its jobs, every slot is idle and nothing is settled.
  const phases = Object.values(states).map(({ phase }) => phase);
  const settled = !phases.includes("requesting") && phases.some((phase) => phase !== "idle");
  useEffect(() => {
    if (!settled || !session.confirmation?.sending) return;
    const answered = { ...session.confirmation };
    delete answered.sending;
    session.save({ draft, reference, clarification, confirmation: answered });
  }, [settled, session, draft, reference, clarification]);
  const diagnosis = (state: ComputePhase) =>
    state.phase === "failed" && state.infeasibility ? (
      <InfeasibilityResult
        diagnosis={state.infeasibility}
        request={state.request}
        draft={draft}
        players={players}
        disabled={busy}
        change={applyRepair}
      />
    ) : undefined;
  const baseState = states.base;
  useEffect(() => {
    if (!run || run !== restoredRun) return;
    let active = true;
    // A reload can land before a started job's id was stored, which leaves nothing to resume.
    // Such a slot asks again while the deadline is open: the service answers a computed request
    // from its cache and joins a request still running to its open job.
    const askAgain = restored?.confirmation?.sending === true && deadlineOpen(deadline);
    const restore = (request: PlanRequest, job: JobControls) => {
      if (job.resume?.(request)) return;
      if (askAgain) job.compute(request);
      else job.readCached?.(request);
    };
    // React can replay mount effects. Wait until their cleanup has completed before resuming.
    queueMicrotask(() => {
      if (!active) return;
      if (run.baseRequest) restore(run.baseRequest, controls.base);
      const followups = restored?.confirmation?.followups;
      ALTERNATIVE_SLOTS.forEach((slot, index) => {
        const request = restoredSlot(run, index, followups?.[index]);
        // A replay the saved run proved infeasible is shown from that proof, not asked again.
        if (request && !(run.scenario && savedReplayProof)) restore(request, controls[slot]);
      });
    });
    return () => {
      active = false;
    };
  }, [run, restoredRun, restored, savedReplayProof, deadline, controls]);

  useEffect(() => {
    const confirmed = session.confirmation;
    if (
      !run?.automaticBasis ||
      baseState.phase !== "done" ||
      baseState.request !== run.baseRequest ||
      !confirmed ||
      confirmed.followups !== undefined
    )
      return;
    if (!deadlineOpen(deadline)) return;
    const followups = followupRequests(run, baseState.envelope.payload);
    session.save({
      draft,
      reference,
      clarification,
      confirmation: {
        ...confirmed,
        followups: followups.map((followup) => followup?.alternative ?? null),
        ...(followups.some(Boolean) ? { sending: true as const } : {}),
      },
    });
    ALTERNATIVE_SLOTS.forEach((slot, index) => {
      const followup = followups[index];
      if (followup) controls[slot].compute(followup.request);
    });
  }, [baseState, run, deadline, controls, session, draft, reference, clarification]);

  async function compute() {
    if (
      busy ||
      confirming.current ||
      clarification !== undefined ||
      !ORIGIN ||
      !squad.source_snapshot_id ||
      !deadlineOpen(deadline) ||
      !canCalculate
    )
      return;
    confirming.current = true;
    setFeedback("");
    setChanges(null);
    setCheckingSquad(true);
    try {
      const [fresh, capabilities] = await Promise.all([
        tree.entrySquad(squad.entry.entry_id),
        forwarded
          ? client.readPublicCapabilities?.(squad.league_id, squad.entry.entry_id)
          : client.readCapabilities?.(squad.league_id),
      ]);
      if (!mounted.current) return;
      if (!capabilities?.preferences) {
        setFeedback(copy.serviceUnavailable);
        return;
      }
      if (!capabilities.strategies["saf-puan"]?.windows.includes(plans.window)) {
        setFeedback(copy.windowUnavailable);
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
        !deadlineOpen(deadline)
      ) {
        setBasisChanged(true);
        setRun(null);
        setReference(undefined);
        session.save({ draft });
        return;
      }
      const request = requestFor(squad, forwarded, plans.window);
      // A public team may have no chip list until its FPL inputs are pinned.
      const heldChips = capabilities.chipsByEntry?.[String(squad.entry.entry_id)];
      const wildcardNotHeld = heldChips !== undefined && !heldChips.includes("wildcard");
      const next = prepareRun({
        draft,
        held,
        request,
        plans,
        wildcardNotHeld,
        frozenWeeks: frozen,
        reference,
      });
      if (next.wildcardUnavailable) setFeedback(copy.wildcardUnavailable);
      if (
        !next.baseRequest &&
        !next.slots.some((slot) => slot.kind === "explicit" && slot.request)
      ) {
        setRun(null);
        session.save({ draft, reference });
        return;
      }
      for (const slot of ALTERNATIVE_SLOTS) controls[slot].reset();
      setRun(next);
      session.save({ draft, reference, confirmation: { wildcardNotHeld, sending: true } });
      if (next.baseRequest) {
        controls.base.compute(next.baseRequest);
      } else controls.base.reset();
      ALTERNATIVE_SLOTS.forEach((name, index) => {
        const slot = next.slots[index];
        if (slot?.kind === "explicit" && slot.request) controls[name].compute(slot.request);
      });
    } catch {
      if (mounted.current) setFeedback(copy.squadUnavailable);
    } finally {
      confirming.current = false;
      if (mounted.current) setCheckingSquad(false);
    }
  }

  const baseAnswer = baseState.phase === "done" ? baseState.envelope.payload : undefined;
  const alternatives = alternativeStates(jobs);
  const priceReview =
    run?.prices.map((target) => {
      const price = preferencePrice(
        target,
        ruleLabel(target.rule, players, copy),
        baseState,
        alternatives,
        !closed && (run !== restoredRun || restored?.confirmation?.followups === undefined),
      );
      if (target.outcome === "conflict")
        price.detail = explainDraftConflict(
          { ...draft, hard: [...draft.hard, target.rule] },
          conflictContext,
        );
      return { outcome: target.outcome, price };
    }) ?? [];
  const { results, same } = run
    ? planResults({
        run,
        base: baseState,
        alternatives,
        priceReview,
        copy,
        explain: explainBranchConflict,
      })
    : { results: [], same: false };
  const alternative = results.find(({ state }) => state.phase === "done")?.state;
  const revisionAnswer =
    baseAnswer ?? (alternative?.phase === "done" ? alternative.envelope.payload : undefined);
  const revised = !draft.scenario && revisionAnswer ? summarizeRevision(revisionAnswer) : undefined;
  const scenarioDescription =
    draft.scenario && scenarioLabel(draft.scenario, players, squad.gameweek, locale, copy);
  const replaySlot = run?.scenario ? run.slots[0] : undefined;
  const replayConflict = replaySlot?.kind === "explicit" && replaySlot.conflict;
  const bankLabel = (floor: NonNullable<PlanDraft["min_bank"]>) =>
    floor.week === undefined
      ? copy.minimumBank(money(floor.tenths, locale))
      : copy.minimumWeekBank(money(floor.tenths, locale), squad.gameweek + floor.week - 1);
  const bankRule = draft.min_bank && bankLabel(draft.min_bank);
  const removedRevision = (changes?.removed ?? []).flatMap((item) =>
    item.group !== "revision"
      ? []
      : "keepWeek" in item
        ? [copy.frozenWeek(squad.gameweek + item.keepWeek - 1)]
        : [bankLabel(item.bank)],
  );
  const removedScenario = (changes?.removed ?? []).flatMap((item) =>
    item.group === "scenario"
      ? [scenarioLabel(item.scenario, players, squad.gameweek, locale, copy)]
      : [],
  );
  const mark = (identity: string) => {
    const kind = changes?.marks.get(identity);
    return kind ? (
      <>
        {" "}
        <ChangeMark mark={kind} copy={copy} />
      </>
    ) : null;
  };

  return (
    <div className={styles.page} data-zone="llmopt">
      <PageHeader squad={squad} />
      {!ORIGIN && (
        <p className={styles.notice} role="status">
          {copy.serviceUnavailable}
        </p>
      )}
      {ORIGIN && roster.isError && <RosterRetry roster={roster} />}
      <section className={styles.workspace} aria-label={copy.chat}>
        {conversation.length > 0 && (
          <ol className={styles.conversation} aria-live="polite">
            {conversation.map(({ id, role, message }) => (
              <li key={id} data-role={role}>
                <strong>{role === "user" ? copy.user : copy.assistant}</strong>
                <span>{message}</span>
              </li>
            ))}
          </ol>
        )}
        <form className={styles.chat} onSubmit={(event) => void send(event)}>
          <label htmlFor="llmopt-message">{copy.chat}</label>
          <textarea
            id="llmopt-message"
            ref={chatInput}
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
            disabled={!ORIGIN || busy || roster.isPending || limit !== null || !message.trim()}
          >
            {reading ? copy.interpreting : copy.send}
          </button>
          {clarification && (
            <button
              className={styles.secondary}
              type="button"
              disabled={busy}
              onClick={() => setQuestion()}
            >
              {copy.dismissQuestion}
            </button>
          )}
        </form>
        <label className={styles.windowChoice}>
          {copy.window}
          <select
            value={plans.window}
            disabled={busy}
            onChange={(event) => change({ ...draft, window: event.target.value === "3" ? 3 : 1 })}
          >
            <option value={1} disabled={needsThreeWeeks(draft)}>
              {copy.oneWeek}
            </option>
            <option value={3}>{copy.threeWeeks}</option>
          </select>
        </label>
        {limit && (
          <p role="status" className={styles.notice}>
            {copy.limitedFor(waitLeft)}
          </p>
        )}
        {feedback && (
          <p role="status" className={styles.notice}>
            {feedback}
          </p>
        )}
        <RuleEditor
          draft={draft}
          players={players}
          copy={copy}
          disabled={busy}
          change={change}
          changes={changes}
        />
        {(Boolean(draft.keep_weeks?.length) || bankRule || removedRevision.length > 0) && (
          <div className={styles.ruleGroup}>
            <h3>{copy.revisionRules}</h3>
            <ul>
              {draft.keep_weeks?.map((week) => {
                const label = copy.frozenWeek(squad.gameweek + week - 1);
                return (
                  <li key={week} data-change={changes?.marks.get(KEEP_WEEK(week))}>
                    <span>
                      {label}
                      {mark(KEEP_WEEK(week))}
                    </span>
                    <button
                      className={styles.remove}
                      type="button"
                      disabled={busy}
                      aria-label={`${copy.remove} · ${label}`}
                      onClick={() => {
                        const keep = draft.keep_weeks?.filter((item) => item !== week);
                        change({ ...draft, keep_weeks: keep?.length ? keep : undefined });
                      }}
                    >
                      ×
                    </button>
                  </li>
                );
              })}
              {bankRule && (
                <li data-change={changes?.marks.get(BANK_FLOOR)}>
                  <span>
                    {bankRule}
                    {mark(BANK_FLOOR)}
                  </span>
                  <button
                    className={styles.remove}
                    type="button"
                    disabled={busy}
                    aria-label={`${copy.remove} · ${bankRule}`}
                    onClick={() => change({ ...draft, min_bank: undefined })}
                  >
                    ×
                  </button>
                </li>
              )}
              {removedRevision.map((label) => (
                <RemovedRule key={`removed:${label}`} label={label} copy={copy} />
              ))}
            </ul>
          </div>
        )}
        {(scenarioDescription || removedScenario.length > 0) && (
          <div className={styles.ruleGroup}>
            <h3>{copy.scenarioRule}</h3>
            <ul>
              {scenarioDescription && (
                <li data-change={changes?.marks.get(SCENARIO)}>
                  <span>
                    {scenarioDescription}
                    {mark(SCENARIO)}
                  </span>
                  <button
                    className={styles.remove}
                    type="button"
                    disabled={busy}
                    aria-label={`${copy.remove} · ${scenarioDescription}`}
                    onClick={() => change({ ...draft, scenario: undefined })}
                  >
                    ×
                  </button>
                </li>
              )}
              {removedScenario.map((label) => (
                <RemovedRule key={`removed:${label}`} label={label} copy={copy} />
              ))}
            </ul>
          </div>
        )}
        {scenarioReferenceMissing && (
          <p className={styles.notice} role="alert">
            {copy.scenarioReferenceRequired}
          </p>
        )}
        {hardConflict && (
          <p role="alert" className={styles.notice}>
            {hardConflict}
          </p>
        )}
        {closed && (
          <p role="status" className={styles.notice}>
            {copy.deadline}
          </p>
        )}
        {fixturesUnavailable && deadline === null && (
          <p role="status" className={styles.notice}>
            {copy.deadlineUnknown}
          </p>
        )}
        <button
          className={styles.primary}
          ref={computeButton}
          type="button"
          disabled={
            busy ||
            clarification !== undefined ||
            !ORIGIN ||
            !squad.source_snapshot_id ||
            closed ||
            deadline === null ||
            !canCalculate ||
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
      {reference && !draft.scenario && (
        <RevisionComparison previous={reference} revised={revised} />
      )}
      {reference && run?.scenario && scenarioDescription && (
        <ScenarioComparison
          reference={reference}
          replay={states.first}
          optimized={baseState}
          description={scenarioDescription}
          proven={!!(replayProof || savedReplayProof)}
          conflict={replayConflict}
        >
          <div className={styles.planGrid}>
            {!savedReplayProof && (
              <PlanResult
                title={copy.scenarioOriginal}
                state={states.first}
                squad={squad}
                conflict={replayConflict}
                conflictMessage={copy.scenarioConflict}
              />
            )}
            <PlanResult
              title={copy.scenarioOptimized}
              state={baseState}
              squad={squad}
              conflict={run.baseConflict}
              conflictMessage={hardConflict}
              diagnosis={diagnosis(baseState)}
            />
          </div>
        </ScenarioComparison>
      )}
      {run && !run.scenario && (
        <section
          className={styles.results}
          aria-label={copy.results}
          aria-busy={isWorking(baseState.phase)}
        >
          <h2>{copy.results}</h2>
          <div className={styles.planGrid}>
            {(run.baseRequest || run.baseConflict) && (
              <PlanResult
                title={copy[run.baseTitle]}
                state={baseState}
                squad={squad}
                conflict={run.baseConflict}
                conflictMessage={
                  run.baseConflict ? explainBranchConflict(run.baseTitle) : undefined
                }
                diagnosis={diagnosis(baseState)}
                prices={priceReview.map(({ price }) => price)}
                onRevise={baseAnswer ? () => revisePlan(baseAnswer) : undefined}
                reviseDisabled={busy}
              />
            )}
            {results.map(({ title, state, conflict, conflictMessage }) => (
              <PlanResult
                key={title}
                title={title}
                state={state}
                squad={squad}
                baseline={baseAnswer}
                conflict={conflict}
                conflictMessage={conflictMessage}
                diagnosis={diagnosis(state)}
                onRevise={
                  state.phase === "done" ? () => revisePlan(state.envelope.payload) : undefined
                }
                reviseDisabled={busy}
              />
            ))}
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

/**
 * The LLMOPT page. The chat is read by `intentSource`, the site's intent service unless
 * another source is given.
 */
export function LLMOptPage({ intentSource }: { intentSource?: IntentSource } = {}) {
  const { messages, language } = useLanguage();
  const source = useMemo(() => intentSource ?? serverIntentSource(ORIGIN), [intentSource]);
  const copy = LLMOPT_COPY[language];
  const { entryId: entryParam } = useParams();
  const entryId = Number(entryParam);
  const valid = Number.isSafeInteger(entryId) && entryId > 0;
  const result = useEntrySquad(entryId, valid);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (result.isPending) return <PageLoading label={messages.common.loading} />;
  if (result.isError) return <EmptyState page title={copy.squadUnavailable} />;
  return (
    <Session
      key={squadBasis(result.data.payload)}
      squad={result.data.payload}
      intentSource={source}
    />
  );
}
