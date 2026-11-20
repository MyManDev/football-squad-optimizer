import { PlanPathGroups } from "./PlanPathGroups";
import { useComputedPlans } from "./useComputedPlans";
import {
  addHistory,
  planCatalogue,
  planContent,
  retainedPlan,
  selectHistory,
  type PlanHistory,
} from "./planHistory";
import { commandDraft } from "./planCommand";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
} from "react";
import { Link, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { PageLoading } from "../../../design/components/PageLoading";
import { useLanguage } from "../../../i18n/context";
import { money } from "../../../lib/format";
import { entryAddress, memberAddress } from "../../../lib/leagueAddresses";
import { useFixtures } from "../../fixtures/data";
import { capabilitiesForPage } from "../advice/adviceCapabilities";
import { createAdviceClient } from "../advice/adviceClient";
import { deviceAdviceClient } from "../device/adviceClient";
import { confirmationProblem, prepareConfirmedRun } from "./releaseRun";
import { gameweekDeadline, useDeadlineClock } from "../advice/deadline";
import type { ComputePhase } from "../advice/useAdviceJob";
import { checkedPreferences, preferencesKey } from "../advice/decisionPreferences";
import { LEAGUE_READ, useEntrySquad, useRestoredPlanCapabilities } from "../queries";
import type { EntryAdvice, EntrySquad } from "../types";
import { useLeague } from "../useLeague";
import { combinedCandidates, prepareCombined } from "./combinedPlan";
import { CombinedRules } from "./CombinedRules";
import { LLMOPT_COPY, ruleLabel } from "./copy";
import { InfeasibilityResult } from "./InfeasibilityResult";
import { VerifiedRuleRepairs } from "./VerifiedRuleRepairs";
import { ruleRepairChoices, type RepairChoice } from "./ruleRepairChoices";
import type { RepairRun } from "./repairComputation";
import {
  EMPTY_DRAFT,
  checkedDraft,
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
import { ownKeyIntentSource, type IntentSource } from "./intentSource";
import { OwnKeyForm } from "./OwnKeyForm";
import { clearOwnKey, useOwnKey } from "./ownKey";
import { PlanResult, type PreferencePrice } from "./PlanResult";
import { expectedNet, samePlan } from "./planComparison";
import { BANK_FLOOR, KEEP_WEEK, SCENARIO, draftChanges, type DraftChanges } from "./planChanges";
import { explainDraftConflict } from "./planConflicts";
import { planResults, preferencePrice } from "./planResults";
import { preferenceExecution, preferenceStates } from "./preferenceExecution";
import {
  referenceCaptains,
  referenceWeeks,
  summarizeRevision,
  type PlanRevision,
} from "./planRevision";
import {
  baseDraft,
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
  createPlanSessionMemory,
  createPlanSessionStore,
  writePlanSession,
  type PlanSessionContext,
  type PlanSessionMemory,
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

function Session({
  squad,
  fixtures,
  deadline,
  intentSource,
  chatReady,
  memory,
}: {
  squad: EntrySquad;
  fixtures: ReturnType<typeof useFixtures>;
  deadline: string | null;
  intentSource: IntentSource;
  chatReady: boolean;
  memory: PlanSessionMemory;
}) {
  const { messages } = useLanguage();
  const { forwarded } = useLeague();
  const publishedDeadline = gameweekDeadline(fixtures.data, squad.season, squad.gameweek);
  const roster = useQuery({
    queryKey: ["llmopt-roster", ORIGIN, squad.season, squad.source_snapshot_id],
    queryFn: ({ signal }) => readIntentCatalog(ORIGIN, squad.season, signal),
    enabled: !!ORIGIN,
    ...LEAGUE_READ,
  });
  const context: PlanSessionContext = {
    key: `squadopt.llmopt:${JSON.stringify([ORIGIN, forwarded === true, squad.league_id, squad.entry.entry_id])}`,
    basis: squadBasis(squad),
    season: squad.season,
    gameweek: squad.gameweek,
    deadline,
  };
  const saved = memory.read(context);
  if (fixtures.isPending || (saved && roster.isPending))
    return <PageLoading label={messages.common.loading} />;
  // A saved session that names a player outside the squad needs the roster to be checked.
  // While the roster read fails, the session is held untouched until a retry reads it. A
  // roster already read stays in use when a later refresh of it fails.
  if (
    saved &&
    roster.isError &&
    !roster.data &&
    !checkedPlanSession(saved, ownedPlayers(squad), squad.gameweek)
  )
    return <RosterHold squad={squad} roster={roster} />;
  return (
    <Workspace
      key={`${context.key}:${context.deadline}`}
      squad={squad}
      deadline={deadline}
      fixturesUnavailable={publishedDeadline === null}
      roster={roster}
      context={context}
      memory={memory}
      saved={saved}
      intentSource={intentSource}
      chatReady={chatReady}
    />
  );
}

function ownedPlayers(squad: EntrySquad): CatalogPlayer[] {
  return [...squad.starting_xi, ...squad.bench].map((p) => ({
    id: p.player_id,
    name: p.name,
    short_name: p.short_name,
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
  memory,
  saved,
  intentSource,
  chatReady,
}: {
  squad: EntrySquad;
  deadline: string | null;
  fixturesUnavailable: boolean;
  roster: UseQueryResult<CatalogPlayer[]>;
  context: PlanSessionContext | null;
  memory: PlanSessionMemory;
  saved: unknown;
  intentSource: IntentSource;
  /** A model is there to read the chat: the member's key is held. */
  chatReady: boolean;
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
  const client = useMemo(
    () =>
      deviceAdviceClient(createAdviceClient(tree.entryAdvice), squad, () =>
        tree.devicePlan(squad.source_snapshot_id),
      ),
    [tree, squad],
  );
  const jobs = usePlanJobs(client, squad.source_snapshot_id);
  const { controls } = jobs;
  const [restored] = useState(() => checkedPlanSession(saved, players, squad.gameweek, squad));
  const [restoredRun] = useState(() =>
    restoreRun(restored, held, (window) => requestFor(squad, forwarded, window)),
  );
  const restoreCapabilities = useRestoredPlanCapabilities(
    client,
    ORIGIN,
    forwarded === true,
    squad,
    true,
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
  // A wait belongs to the model that asked for it; another key or provider starts without one.
  const heldModel = useOwnKey();
  const waitFor = useRef(heldModel);
  // Saving a key turns the chat on; the keyboard goes there once it is.
  const focusChat = useRef(false);
  useEffect(() => {
    if (waitFor.current === heldModel) return;
    waitFor.current = heldModel;
    setLimit(null);
    if (heldModel && focusChat.current) chatInput.current?.focus();
    focusChat.current = false;
  }, [heldModel]);
  const [run, setRun] = useState<PlanRun | null>(restoredRun);
  const [changes, setChanges] = useState<DraftChanges | null>(null);
  const [session] = useState(() =>
    createPlanSessionStore(context, restored?.confirmation, memory, restored?.history),
  );
  // The saved run, read again after each save.
  const savedRun = useSyncExternalStore(session.subscribe, () => session.confirmation);
  // Keep a validated restore above the keyed workspace too. This also records a draft
  // edited before the calendar was available as soon as its deadline becomes known.
  useEffect(() => {
    if (restored) session.save(restored);
  }, [restored, session]);
  const chatInput = useRef<HTMLTextAreaElement>(null);
  const chatForm = useRef<HTMLFormElement>(null);
  const restoreChatFocus = useRef(false);
  const conversationList = useRef<HTMLOListElement>(null);
  const followConversation = useRef(true);
  const latestChatLine = conversation.at(-1)?.id;
  const previousChatLine = useRef(latestChatLine);
  const computeButton = useRef<HTMLButtonElement>(null);
  const interpret = useRef<AbortController | null>(null);
  const nextChatLine = useRef(conversation.length);
  const confirming = useRef(false);
  const mounted = useRef(true);

  // Follow new replies within the list, without moving the page or taking an older
  // question away from someone reading it. A restored conversation starts where it is.
  useLayoutEffect(() => {
    const appended = previousChatLine.current !== latestChatLine;
    previousChatLine.current = latestChatLine;
    const list = conversationList.current;
    if (appended && followConversation.current && list) list.scrollTop = list.scrollHeight;
  }, [latestChatLine]);

  // Disabling Send can leave the keyboard on the document body. Return it to the chat
  // after the answer, unless the member moved elsewhere while the model was reading.
  useEffect(() => {
    if (reading) {
      const movedElsewhere = (event: FocusEvent | PointerEvent) => {
        if (
          event.target instanceof Node &&
          !(event.type === "focusin" && event.target === document.body) &&
          !chatForm.current?.contains(event.target)
        )
          restoreChatFocus.current = false;
      };
      document.addEventListener("focusin", movedElsewhere);
      document.addEventListener("pointerdown", movedElsewhere);
      return () => {
        document.removeEventListener("focusin", movedElsewhere);
        document.removeEventListener("pointerdown", movedElsewhere);
      };
    }
    if (!restoreChatFocus.current) return;
    restoreChatFocus.current = false;
    const active = document.activeElement;
    if (chatReady && (active === document.body || chatForm.current?.contains(active)))
      chatInput.current?.focus({ preventScroll: true });
  }, [reading, chatReady, conversation, feedback, limit]);

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
  function change(next: PlanDraft, previous = selectedReference ?? reference ?? revised) {
    const abandoned = session.confirmation?.runId;
    const hadOpenWork = Object.values(jobs.states).some(({ phase }) => isWorking(phase));
    if (abandoned)
      void client.cancelRun?.(abandoned).catch(() => {
        // A terminal run has nothing left to stop. Its bookkeeping must not replace
        // the feedback for a repair or edit the member has already selected.
        if (hadOpenWork) setFeedback(copy.serviceUnavailable);
      });
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

  function askPlanQuestion(text: string) {
    setQuestion({ message: text, question: copy.planQuestion });
    setFeedback(copy.planQuestion);
    setMessage("");
  }
  async function currentGrant() {
    const read = await restoreCapabilities.refetch({ cancelRefetch: false });
    if (read.isError) return undefined;
    const caps = capabilitiesForPage(read.data, {
      leagueId: squad.league_id,
      season: squad.season,
      gameweek: squad.gameweek,
      snapshotId: squad.source_snapshot_id,
    });
    return caps?.llmoptVNext === true ? caps : undefined;
  }
  async function currentPlanData(kind: "device" | "server", serverDataId?: string) {
    try {
      return kind === "device" ? await client.readDeviceDataId?.() : serverDataId;
    } catch {
      return undefined;
    }
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (
      !text ||
      !ORIGIN ||
      !chatReady ||
      interpret.current ||
      checkingSquad ||
      roster.isPending ||
      limit
    )
      return;
    const controller = new AbortController();
    let sentCatalogue = false;
    interpret.current = controller;
    restoreChatFocus.current = event.currentTarget.contains(document.activeElement);
    setReading(true);
    setFeedback("");
    try {
      const candidate = vNext ? planCatalogue(computed.history, shownPlans) : undefined;
      const grant = candidate || selectedReference ? await currentGrant() : undefined;
      if (controller.signal.aborted) return;
      const catalogue = grant ? candidate : undefined;
      sentCatalogue = !!catalogue;
      const previous = (grant ? selectedReference : undefined) ?? reference ?? revised;
      if (
        catalogue &&
        (await currentPlanData(catalogue.kind, grant?.planDataId)) !== catalogue.data_id
      ) {
        askPlanQuestion(text);
        return;
      }
      const answer = await intentSource.interpret(
        {
          message: text,
          locale: language,
          draft,
          players,
          clarification,
          referenceWeeks: referenceWeeks(previous),
          referenceCaptains: referenceCaptains(previous),
          planContext: catalogue,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      if (answer.status === "plan") {
        if (!catalogue) throw new IntentError(422, "REPLY_REFUSED");
        const granted = await currentGrant();
        if (controller.signal.aborted) return;
        if (!granted) {
          setFeedback(copy.serviceUnavailable);
          return;
        }
        const currentCatalogue = planCatalogue(session.history, shownPlans);
        const item = session.history.items.find((p) => p.id === answer.command.plan_id);
        try {
          if (
            !currentCatalogue ||
            currentCatalogue.data_id !== catalogue?.data_id ||
            (await currentPlanData(currentCatalogue.kind, granted.planDataId)) !==
              currentCatalogue.data_id
          )
            throw new Error("Stale reply");
          const result = commandDraft(answer.command, currentCatalogue, item?.plan, draft, players);
          if (result.draft) change(checkedDraft(result.draft, players), result.reference);
          else applySelection(computed.choose(answer.command.plan_id));
        } catch {
          askPlanQuestion(text);
          return;
        }
      } else if (answer.status === "draft") {
        change(answer.draft, previous);
        setChanges(draftChanges(draft, answer.draft));
      } else {
        // A second question must keep every earlier answer in the next request's context.
        const asked = clarification ? `${clarification.message}\n${text}` : text;
        if (asked.length > MAX_MESSAGE_LENGTH) {
          setFeedback(copy.conversationTooLong);
          return;
        }
        setQuestion({
          message: asked,
          question: answer.message,
        });
      }
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
      if (error instanceof IntentError && error.code === "REPLY_REFUSED" && sentCatalogue) {
        askPlanQuestion(text);
        return;
      }
      const refusal = intentRefusal(error);
      if (
        (refusal === "limited" || refusal === "providerLimited") &&
        error instanceof IntentError &&
        error.retryAfterSeconds
      ) {
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

  const execution = useMemo(() => preferenceExecution(run), [run]);
  const states = preferenceStates(jobs.states, run, execution);
  const bundleState = jobs.states.first;
  const bundleResult =
    execution && bundleState.phase === "done"
      ? bundleState.envelope.payload.preference_bundle_result
      : undefined;
  const capacityRefused = (state: ComputePhase) =>
    (state.phase === "failed" || state.phase === "unavailable") &&
    (state.reason === "RUN_BUDGET_EXHAUSTED" || state.reason === "RUN_CANCELLED");
  const incompleteRun = Object.values(states).some(capacityRefused);
  const computing = Object.values(states).some(({ phase }) => isWorking(phase));
  const editingLocked = checkingSquad || reading || (computing && !run?.inputs.request.run);
  const busy = editingLocked || computing;
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
  const knownRequestsStarted =
    !run ||
    (execution
      ? bundleState.phase !== "idle"
      : ALTERNATIVE_SLOTS.every(
          (slot, index) =>
            (run.slots[index]?.kind !== "explicit" && !savedRun?.followups?.[index]) ||
            (run.scenario && savedReplayProof) ||
            states[slot].phase !== "idle",
        ) &&
        (!savedRun?.combined?.length || states.combined.phase !== "idle"));
  const settled =
    knownRequestsStarted &&
    !phases.includes("requesting") &&
    phases.some((phase) => phase !== "idle");
  useEffect(() => {
    if (!settled || !session.confirmation?.sending) return;
    const answered = { ...session.confirmation };
    delete answered.sending;
    session.save({ draft, reference, clarification, confirmation: answered });
  }, [settled, session, draft, reference, clarification]);
  const baseState = states.base;
  const restoreMode = capabilitiesForPage(restoreCapabilities.data, {
    leagueId: squad.league_id,
    season: squad.season,
    gameweek: squad.gameweek,
    snapshotId: squad.source_snapshot_id,
  });
  const currentCapabilities =
    restoreCapabilities.isFetchedAfterMount && !restoreCapabilities.isError ? restoreMode : null;
  const vNext = currentCapabilities?.llmoptVNext === true;
  const prioritiesEnabled =
    currentCapabilities?.llmoptVNext === true &&
    (currentCapabilities.preferenceBundles === true ||
      (plans.window === 1 && currentCapabilities.devicePreferenceBundles === true));
  const canContinue =
    (run !== restoredRun && !run?.inputs.request.run) ||
    (!!currentCapabilities &&
      (currentCapabilities.llmoptVNext === true) === !!run?.inputs.request.run &&
      (!run?.inputs.request.deviceRun || currentCapabilities.devicePreferenceBundles === true) &&
      (!run?.inputs.paths3w || currentCapabilities.transferPackages === true) &&
      (!run?.inputs.bundleMode ||
        (run.inputs.request.deviceRun
          ? currentCapabilities.devicePreferenceBundles === true
          : currentCapabilities.preferenceBundles === true)));
  const repairsEnabled = vNext && currentCapabilities?.verifiedRepairs === true;
  const oldSearch = savedRun?.repairSearch;
  const failure =
    baseState.phase === "failed" || baseState.phase === "unavailable" ? baseState : null;
  const failureCode = failure?.reason ?? oldSearch?.failureCode;
  const failureDetails = failure?.phase === "failed" ? failure.infeasibility : oldSearch?.diagnosis;
  const diagnosedRequest =
    failure?.request ??
    run?.baseRequest ??
    (oldSearch?.diagnosis && savedRun
      ? restoreRun(
          { draft, reference, confirmation: { ...savedRun, repairSearch: undefined } },
          held,
          (window) => requestFor(squad, forwarded, window),
        )?.baseRequest
      : undefined);
  const analysis =
    repairsEnabled && !draft.scenario
      ? ruleRepairChoices(draft, {
          ...conflictContext,
          language,
          heldChips: currentCapabilities.chipsByEntry?.[String(squad.entry.entry_id)] ?? null,
          freeTransfers: squad.free_transfers_known ? squad.free_transfers : null,
          heldClubs: new Map(
            [...squad.starting_xi, ...squad.bench].map((player) => [player.player_id, player.team]),
          ),
          bankTenths: squad.bank_tenths,
          request: diagnosedRequest ?? undefined,
          failureCode,
          diagnosis: failureDetails,
        })
      : null;
  async function repairData() {
    if (!deadlineOpen(deadline)) throw new Error("RUN_CONTEXT_CHANGED");
    const [fresh, grant] = await Promise.all([
      tree.entrySquad(squad.entry.entry_id),
      currentGrant(),
    ]);
    if (
      !mounted.current ||
      !grant?.verifiedRepairs ||
      squadBasis(fresh.payload) !== squadBasis(squad) ||
      !deadlineOpen(deadline)
    )
      throw new Error("RUN_CONTEXT_CHANGED");
    const dataId = plans.window === 1 ? await client.readDeviceDataId?.() : grant.planDataId;
    if (!dataId || !/^[0-9a-f]{64}$/.test(dataId)) throw new Error("INPUTS_UNAVAILABLE");
    return dataId;
  }
  async function beginRepair(signal: AbortSignal): Promise<RepairRun> {
    const dataId = await repairData();
    if (signal.aborted || !deadlineOpen(deadline)) throw new Error("RUN_CANCELLED");
    const confirmation = session.confirmation;
    if (confirmation?.repairSearch && confirmation.repairSearch.dataId !== dataId)
      throw new Error("RUN_CONTEXT_CHANGED");
    const runId = confirmation?.runId ?? crypto.randomUUID().replaceAll("-", "");
    const failedBase =
      confirmation?.repairSearch?.failedBase ??
      !!(
        confirmation?.runId &&
        run &&
        failure?.phase === "failed" &&
        ((failure.reason === "PLAN_NOT_FOUND" && failure.infeasibility) ||
          (failure.reason === "CHIP_NOT_HELD" && failure.terminalJobId))
      );
    const next = {
      draft,
      reference,
      history: session.history,
      confirmation: {
        ...confirmation,
        runId,
        wildcardNotHeld: confirmation?.wildcardNotHeld ?? false,
        repairSearch: {
          dataId,
          failedBase,
          diagnosis: failureDetails,
          ...(failureCode === "PLAN_NOT_FOUND" || failureCode === "CHIP_NOT_HELD"
            ? { failureCode: failureCode as "PLAN_NOT_FOUND" | "CHIP_NOT_HELD" }
            : {}),
        },
      },
    };
    if (!writePlanSession(context, next)) throw new Error("RUN_STORE_UNAVAILABLE");
    session.save(next);
    return { runId, dataId, failedBase };
  }
  function acceptRepair(choice: RepairChoice, plan: EntryAdvice, id: string) {
    change(choice.draft, reference);
    const history = selectHistory(
      addHistory(session.history, [{ id, plan: retainedPlan(plan) }]),
      id,
    );
    session.save({ draft: choice.draft, reference, history });
  }
  const diagnosis = (state: ComputePhase) =>
    state.phase === "failed" && state.infeasibility && !repairsEnabled ? (
      <InfeasibilityResult
        diagnosis={state.infeasibility}
        request={state.request}
        draft={draft}
        players={players}
        disabled={editingLocked}
        change={applyRepair}
      />
    ) : undefined;
  useEffect(() => {
    if (!run || run !== restoredRun || (!!ORIGIN && !restoreCapabilities.isFetchedAfterMount))
      return;
    let active = true;
    // A reload can land before a started job's id was stored, which leaves nothing to resume.
    // Such a slot asks again while the deadline is open: the service answers a computed request
    // from its cache and joins a request still running to its open job.
    const askAgain =
      canContinue && restored?.confirmation?.sending === true && deadlineOpen(deadline);
    const restore = (request: PlanRequest, job: JobControls) => {
      if (job.resume?.(request)) return;
      if (askAgain) job.compute(request);
      else job.readCached?.(request);
    };
    // React can replay mount effects. Wait until their cleanup has completed before resuming.
    queueMicrotask(() => {
      if (!active) return;
      if (run.baseRequest) restore(run.baseRequest, controls.base);
      if (!run.inputs.request.run) {
        ALTERNATIVE_SLOTS.forEach((name, index) => {
          const request = restoredSlot(run, index, restored?.confirmation?.followups?.[index]);
          if (request && !(run.scenario && savedReplayProof)) restore(request, controls[name]);
        });
        if (restored?.confirmation?.combined?.length) {
          const { request } = prepareCombined(run, restored.confirmation.combined);
          if (request) restore(request, controls.combined);
        }
      }
    });
    return () => {
      active = false;
    };
  }, [
    run,
    restoredRun,
    restored,
    savedReplayProof,
    deadline,
    controls,
    restoreCapabilities.isFetchedAfterMount,
    canContinue,
  ]);

  useEffect(() => {
    if (
      !run?.inputs.request.run ||
      execution ||
      incompleteRun ||
      baseState.phase !== "done" ||
      baseState.request !== run.baseRequest
    )
      return;
    const confirmed = session.confirmation;
    const restoring = run === restoredRun;
    const restore = (request: PlanRequest, slot: JobControls) => {
      if (slot.resume?.(request)) return;
      if (canContinue && confirmed?.sending && deadlineOpen(deadline)) slot.compute(request);
      else slot.readCached?.(request);
    };
    ALTERNATIVE_SLOTS.forEach((name, index) => {
      const slot = run.slots[index];
      if (restoring) {
        const request = restoredSlot(run, index, confirmed?.followups?.[index]);
        if (request && !(run.scenario && savedReplayProof)) restore(request, controls[name]);
      } else if (canContinue && slot?.kind === "explicit" && slot.request)
        controls[name].compute(slot.request);
    });
    if (restoring && confirmed?.combined?.length) {
      const { request } = prepareCombined(run, confirmed.combined);
      if (request) restore(request, controls.combined);
    }
  }, [
    run,
    restoredRun,
    baseState,
    session,
    savedReplayProof,
    deadline,
    controls,
    incompleteRun,
    execution,
    canContinue,
  ]);

  useEffect(() => {
    if (
      !execution ||
      !run ||
      incompleteRun ||
      baseState.phase !== "done" ||
      baseState.request !== run.baseRequest ||
      bundleState.phase !== "idle"
    )
      return;
    if (run === restoredRun) {
      if (controls.first.resume?.(execution)) return;
      if (canContinue && session.confirmation?.sending && deadlineOpen(deadline))
        controls.first.compute(execution);
      else controls.first.readCached?.(execution);
    } else if (canContinue) controls.first.compute(execution);
  }, [
    execution,
    run,
    restoredRun,
    incompleteRun,
    baseState,
    bundleState,
    controls,
    session,
    deadline,
    canContinue,
  ]);

  useEffect(() => {
    const confirmed = session.confirmation;
    if (
      !canContinue ||
      !run?.automaticBasis ||
      execution ||
      incompleteRun ||
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
  }, [
    baseState,
    run,
    deadline,
    controls,
    session,
    draft,
    reference,
    clarification,
    incompleteRun,
    execution,
    canContinue,
  ]);

  async function compute() {
    if (
      busy ||
      confirming.current ||
      clarification !== undefined ||
      !ORIGIN ||
      !squad.source_snapshot_id ||
      !deadlineOpen(deadline) ||
      !canCalculate ||
      !!analysis
    )
      return;
    confirming.current = true;
    setFeedback("");
    setChanges(null);
    setCheckingSquad(true);
    try {
      const [fresh, capabilities] = await Promise.all([
        tree.entrySquad(squad.entry.entry_id),
        restoreCapabilities
          .refetch({ cancelRefetch: false })
          .then((read) => (read.isError ? null : read.data)),
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
        // The reload the page asks for opens the new squad; the rules go with the member.
        session.save({ draft });
        return;
      }
      const runId = capabilities.llmoptVNext ? crypto.randomUUID().replaceAll("-", "") : undefined;
      const next = prepareConfirmedRun(
        { draft, held, plans, frozenWeeks: frozen, reference },
        squad,
        forwarded,
        capabilities,
        runId,
      );
      if (!next) {
        setFeedback(
          copy[confirmationProblem(draft, plans.window, capabilities) ?? "serviceUnavailable"],
        );
        return;
      }
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
      controls.combined.reset();
      const confirmed = {
        draft,
        reference,
        confirmation: {
          ...(runId ? { runId } : {}),
          wildcardNotHeld: next.inputs.wildcardNotHeld,
          ...(next.inputs.paths3w ? { paths3w: true as const } : {}),
          sending: true as const,
          compareOnly: next.inputs.compareOnly === true,
          deviceRun: next.baseRequest?.deviceRun ?? false,
          deviceAlternatives: next.baseRequest?.deviceAlternatives ?? false,
          ...(next.inputs.bundleMode ? { bundleMode: true as const } : {}),
        },
      };
      if (runId && !writePlanSession(context, confirmed)) {
        setFeedback(copy.serviceUnavailable);
        return;
      }
      setRun(next);
      session.save(confirmed);
      if (next.baseRequest) {
        controls.base.compute(next.baseRequest);
      } else controls.base.reset();
      if (!runId) {
        ALTERNATIVE_SLOTS.forEach((name, index) => {
          const slot = next.slots[index];
          if (slot?.kind === "explicit" && slot.request) controls[name].compute(slot.request);
        });
      }
    } catch {
      if (mounted.current) setFeedback(copy.squadUnavailable);
    } finally {
      confirming.current = false;
      if (mounted.current) setCheckingSquad(false);
    }
  }

  const baseAnswer = baseState.phase === "done" ? baseState.envelope.payload : undefined;
  const alternatives = alternativeStates({ ...jobs, states });
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
  // The plan with all preferences starts once the base and every single price are in, so no
  // more than three jobs run at once and a run makes at most four.
  const answered = (state: ComputePhase) =>
    state.phase === "done" || state.phase === "failed" || state.phase === "unavailable";
  const singlesIn =
    !!run &&
    !run.scenario &&
    run.prices.length > 0 &&
    baseState.phase === "done" &&
    baseState.request === run.baseRequest &&
    !computing &&
    run.slots.every((slot, index) => !slot.request || answered(alternatives[index]!));
  const combinedChoice = run && singlesIn ? combinedCandidates(run, priceReview) : null;
  useEffect(() => {
    const confirmed = session.confirmation;
    if (
      !run ||
      execution ||
      incompleteRun ||
      !canContinue ||
      !singlesIn ||
      !confirmed ||
      confirmed.followups === undefined ||
      confirmed.combined !== undefined ||
      !deadlineOpen(deadline)
    )
      return;
    const plan = combinedChoice
      ? prepareCombined(run, combinedChoice)
      : { applied: [], request: null };
    session.save({
      draft,
      reference,
      clarification,
      confirmation: {
        ...confirmed,
        combined: plan.applied,
        ...(plan.request ? { sending: true as const } : {}),
      },
    });
    if (plan.request) controls.combined.compute(plan.request);
  }, [
    run,
    singlesIn,
    combinedChoice,
    deadline,
    controls,
    session,
    draft,
    reference,
    clarification,
    incompleteRun,
    execution,
    canContinue,
  ]);
  // A rule with no slot of its own is priced in the plan with all preferences, or named as
  // left out of it.
  const combined =
    execution?.preferenceBundle?.program && states.combined.phase === "done"
      ? execution.preferenceBundle.program.preferences.flatMap((rule, index) =>
          states.combined.phase === "done" &&
          states.combined.envelope.payload.priority_preferences?.satisfied.some(
            (identity) =>
              preferencesKey(checkedPreferences(JSON.parse(identity))) ===
              preferencesKey(rule.rules),
          )
            ? [index]
            : [],
        )
      : bundleResult?.selected?.status === "done"
        ? bundleResult.applied
        : run && savedRun?.combined
          ? prepareCombined(run, savedRun.combined).applied
          : undefined;
  const combinedPending =
    !closed &&
    (isWorking(baseState.phase) ||
      (baseState.phase === "done" &&
        (computing || singlesIn || savedRun?.followups === undefined)));
  const priceRows = priceReview.map(({ outcome, price }, index): PreferencePrice => {
    if (outcome !== "skipped") return price;
    const { key, label, ceiling } = price;
    if (combined)
      return { key, label, ceiling, status: combined.includes(index) ? "combined" : "leftOut" };
    return combinedPending ? { key, label, ceiling, status: "pending" } : price;
  });
  const softRules = run?.inputs.draft.soft ?? [];
  const combinedRules = (keep: boolean) =>
    softRules.flatMap((rule, index) =>
      combined?.includes(index) === keep
        ? [{ key: String(index), label: ruleLabel(rule, players, copy) }]
        : [],
    );
  const combinedState = states.combined;
  const combinedNet =
    combinedState.phase === "done" ? expectedNet(combinedState.envelope.payload) : null;
  const baseNet = baseAnswer ? expectedNet(baseAnswer) : null;
  const combinedCost =
    combinedState.phase === "done" && combinedState.envelope.payload.priority_preferences
      ? combinedState.envelope.payload.priority_preferences.total_cost
      : combinedNet === null || baseNet === null
        ? undefined
        : samePlan(baseState, combinedState)
          ? 0
          : Math.max(0, baseNet - combinedNet);
  const showPaths = vNext && run?.inputs.paths3w === true;
  const { results, same } = run
    ? planResults({
        run,
        showPaths,
        base: baseState,
        alternatives,
        priceReview,
        copy,
        explain: explainBranchConflict,
      })
    : { results: [], same: false };
  const shownPlans = [
    ...(run?.scenario && states.first.phase === "done" ? [states.first.envelope.payload] : []),
    ...(baseAnswer ? [baseAnswer] : []),
    ...results.flatMap(({ state }) => (state.phase === "done" ? [state.envelope.payload] : [])),
    ...(combinedState.phase === "done" ? [combinedState.envelope.payload] : []),
  ];
  const computed = useComputedPlans(
    session,
    { draft, reference, clarification, confirmation: session.confirmation },
    vNext ? shownPlans : [],
    session.confirmation?.runId,
  );
  const selectedReference =
    vNext && computed.history.explicit && computed.selected
      ? summarizeRevision(computed.selected.plan)
      : undefined;
  const restoredArchive =
    !!restored?.history &&
    run === restoredRun &&
    (!restored.confirmation || !!restored.confirmation.runId);
  const historical =
    (vNext || restoredArchive) &&
    computed.selected &&
    !shownPlans.some((p) => planContent(p) === planContent(computed.selected!.plan));
  async function selectComputed(history: PlanHistory) {
    if (vNext && (await currentGrant()) && mounted.current) applySelection(history);
  }
  function applySelection(history: PlanHistory) {
    if (!history.items.some((p) => p.id === history.navigation[history.cursor])) return;
    setClarification(undefined);
    session.save({ draft, reference, confirmation: session.confirmation, history });
  }
  const planProps = (plan: EntryAdvice) => {
    const id = vNext ? computed.idFor(plan) : undefined;
    return id
      ? {
          planId: id,
          selected: computed.selected?.id === id,
          onSelect: () => selectComputed(computed.choose(id)),
        }
      : {};
  };
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
      {ORIGIN && roster.isError && !roster.data && <RosterRetry roster={roster} />}
      <section className={styles.workspace} aria-label={copy.chat}>
        {ORIGIN && (
          <OwnKeyForm
            copy={copy}
            disabled={reading}
            onSaved={() => {
              focusChat.current = true;
            }}
          />
        )}
        {conversation.length > 0 && (
          <ol
            className={styles.conversation}
            ref={conversationList}
            aria-live="polite"
            onScroll={(event) => {
              const list = event.currentTarget;
              followConversation.current =
                list.scrollHeight - list.scrollTop - list.clientHeight < 24;
            }}
          >
            {conversation.map(({ id, role, message }) => (
              <li key={id} data-role={role}>
                <strong>{role === "user" ? copy.user : copy.assistant}</strong>
                <span>{message}</span>
              </li>
            ))}
          </ol>
        )}
        <form className={styles.chat} ref={chatForm} onSubmit={(event) => void send(event)}>
          <label htmlFor="llmopt-message">{copy.chat}</label>
          <textarea
            id="llmopt-message"
            ref={chatInput}
            placeholder={copy.placeholder}
            value={message}
            maxLength={MAX_MESSAGE_LENGTH}
            rows={2}
            onChange={(event) => setMessage(event.target.value)}
            disabled={!ORIGIN || !chatReady || reading || checkingSquad}
          />
          <button
            className={styles.primary}
            type="submit"
            disabled={
              !ORIGIN ||
              !chatReady ||
              editingLocked ||
              roster.isPending ||
              limit !== null ||
              !message.trim()
            }
          >
            {reading ? copy.interpreting : copy.send}
          </button>
          {clarification && (
            <button
              className={styles.secondary}
              type="button"
              disabled={editingLocked}
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
            disabled={editingLocked}
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
          priorities={prioritiesEnabled}
          draft={draft}
          players={players}
          copy={copy}
          disabled={editingLocked}
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
                      disabled={editingLocked}
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
                    disabled={editingLocked}
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
                    disabled={editingLocked}
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
        {hardConflict && !analysis && (
          <p role="alert" className={styles.notice}>
            {hardConflict}
          </p>
        )}
        {analysis && (
          <VerifiedRuleRepairs
            key={JSON.stringify([draft, reference, squad.source_snapshot_id, language])}
            analysis={analysis}
            client={client}
            squad={squad}
            window={plans.window}
            forwarded={forwarded}
            reference={reference}
            disabled={
              editingLocked || computing || closed || basisChanged || !deadlineOpen(deadline)
            }
            begin={beginRepair}
            current={async (owner) =>
              session.confirmation?.runId === owner.runId &&
              (await repairData()) === owner.dataId &&
              session.confirmation?.runId === owner.runId
            }
            apply={acceptRepair}
          />
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
            !!analysis ||
            basisChanged
          }
          onClick={() => void compute()}
        >
          {checkingSquad ? copy.checkSquad : computing ? copy.computing : copy.compute}
        </button>
        {/* A 3-week plan is solved at the service, one plan after another: say how long. */}
        {computing && plans.window === 3 ? (
          <p className={styles.notice} role="status" data-long-wait>
            {copy.longWait}
          </p>
        ) : null}
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
      {vNext && computed.history.items.length > 0 && (
        <section className={styles.revision} aria-label={copy.planHistory}>
          <label>
            {copy.planHistory}{" "}
            <select
              value={computed.selected?.id ?? ""}
              disabled={editingLocked}
              onChange={(event) => selectComputed(computed.choose(event.target.value))}
            >
              {computed.history.items.map((item, index) => (
                <option key={item.id} value={item.id}>
                  {copy.savedPlan(index + 1)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={editingLocked || computed.history.cursor <= 0}
            onClick={() => selectComputed(computed.move(-1))}
          >
            {copy.undoPlan}
          </button>
          <button
            type="button"
            disabled={
              editingLocked || computed.history.cursor >= computed.history.navigation.length - 1
            }
            onClick={() => selectComputed(computed.move(1))}
          >
            {copy.redoPlan}
          </button>
        </section>
      )}
      {historical && computed.selected && !computing && (
        <PlanResult
          title={copy.selectedPlan}
          planId={vNext ? computed.selected.id : undefined}
          selected={vNext}
          state={{
            phase: "done",
            source: "api-cache",
            request: requestFor(squad, forwarded, computed.selected.plan.window as 1 | 3),
            envelope: {
              contract_version: "provisional_league_ui_v1",
              generated_at_utc: "2000-01-01T00:00:00Z",
              source_kind: "live",
              payload: computed.selected.plan,
            },
          }}
          squad={squad}
        />
      )}
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
                {...(states.first.phase === "done" ? planProps(states.first.envelope.payload) : {})}
                state={states.first}
                squad={squad}
                conflict={replayConflict}
                conflictMessage={copy.scenarioConflict}
              />
            )}
            <PlanResult
              title={copy.scenarioOptimized}
              {...(baseAnswer ? planProps(baseAnswer) : {})}
              state={baseState}
              squad={squad}
              conflict={run.baseConflict}
              conflictMessage={hardConflict}
              diagnosis={diagnosis(baseState)}
            />
          </div>
        </ScenarioComparison>
      )}
      {run && !run.scenario && (!historical || computing) && (
        <section
          className={styles.results}
          aria-label={copy.results}
          aria-busy={isWorking(baseState.phase)}
        >
          <h2>{copy.results}</h2>
          <PlanPathGroups
            enabled={showPaths}
            className={styles.planGrid}
            label={copy.openingDecision}
          >
            {(run.baseRequest || run.baseConflict) && !capacityRefused(baseState) && !analysis && (
              <PlanResult
                title={copy[run.baseTitle]}
                state={baseState}
                squad={squad}
                conflict={run.baseConflict}
                conflictMessage={
                  run.baseConflict ? explainBranchConflict(run.baseTitle) : undefined
                }
                diagnosis={diagnosis(baseState)}
                prices={
                  incompleteRun ? priceRows.filter(({ status }) => status === "priced") : priceRows
                }
                {...(baseAnswer ? planProps(baseAnswer) : {})}
                onRevise={baseAnswer ? () => revisePlan(baseAnswer) : undefined}
                reviseDisabled={editingLocked}
              />
            )}
            {results
              .filter(({ state }) => !capacityRefused(state))
              .map(({ title, state, conflict, conflictMessage }) => (
                <PlanResult
                  key={title}
                  title={title}
                  state={state}
                  squad={squad}
                  baseline={baseAnswer}
                  conflict={conflict}
                  conflictMessage={conflictMessage}
                  diagnosis={diagnosis(state)}
                  {...(state.phase === "done" ? planProps(state.envelope.payload) : {})}
                  onRevise={
                    state.phase === "done" ? () => revisePlan(state.envelope.payload) : undefined
                  }
                  reviseDisabled={editingLocked}
                />
              ))}
            {combined &&
              (combined.length > 0 || execution?.preferenceBundle?.program) &&
              !capacityRefused(combinedState) && (
                <PlanResult
                  title={copy.combinedPlan}
                  state={combinedState}
                  squad={squad}
                  baseline={baseAnswer}
                  diagnosis={diagnosis(combinedState)}
                  {...(combinedState.phase === "done"
                    ? planProps(combinedState.envelope.payload)
                    : {})}
                  onRevise={
                    combinedState.phase === "done"
                      ? () => revisePlan(combinedState.envelope.payload)
                      : undefined
                  }
                  reviseDisabled={editingLocked}
                >
                  <CombinedRules
                    applied={combinedRules(true)}
                    leftOut={combinedRules(false)}
                    cost={combinedCost}
                    infeasible={combinedState.phase === "failed" && !!combinedState.infeasibility}
                  />
                </PlanResult>
              )}
          </PlanPathGroups>
          {incompleteRun && !analysis && <p role="status">{copy.unfinishedPlans}</p>}
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
 * The LLMOPT page. The chat is read by the member's own model while a key is held (ADR 0017),
 * and is off until then: the site has no model of its own. The rules can always be edited by
 * hand. A test gives `intentSource` to stand in for the model.
 */
export function LLMOptPage({ intentSource }: { intentSource?: IntentSource } = {}) {
  const { messages, language } = useLanguage();
  const ownKey = useOwnKey() !== null;
  const source = useMemo(() => intentSource ?? ownKeyIntentSource(ORIGIN), [intentSource]);
  // Leaving the page deletes the key; `pagehide` covers a reload and a closed tab.
  useEffect(() => clearOwnKey, []);
  const copy = LLMOPT_COPY[language];
  const { entryId: entryParam } = useParams();
  const entryId = Number(entryParam);
  const valid = Number.isSafeInteger(entryId) && entryId > 0;
  const result = useEntrySquad(entryId, valid);
  const [memory] = useState(createPlanSessionMemory);
  const fixtures = useFixtures();
  const squad = result.data?.payload;
  const publishedDeadline = gameweekDeadline(fixtures.data, squad?.season, squad?.gameweek);
  const [knownDeadline, setKnownDeadline] = useState<{
    season: string;
    gameweek: number;
    deadline: string;
  } | null>(null);
  const sameWeek =
    squad !== undefined &&
    knownDeadline?.season === squad.season &&
    knownDeadline.gameweek === squad.gameweek;
  if (
    squad &&
    publishedDeadline !== null &&
    (!sameWeek || knownDeadline?.deadline !== publishedDeadline)
  )
    setKnownDeadline({
      season: squad.season,
      gameweek: squad.gameweek,
      deadline: publishedDeadline,
    });
  // Keep the recorded deadline across squad refreshes while the calendar is unavailable.
  // Another season or gameweek needs its own calendar, and the deadline clock still closes.
  const deadline = fixtures.data == null && sameWeek ? knownDeadline.deadline : publishedDeadline;
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (result.isPending) return <PageLoading label={messages.common.loading} />;
  // A squad already read stays on the page when a later refresh of it fails: plans may be
  // computing, and unmounting the workspace would drop them.
  if (!result.data) return <EmptyState page title={copy.squadUnavailable} />;
  return (
    <Session
      key={squadBasis(result.data.payload)}
      squad={result.data.payload}
      fixtures={fixtures}
      deadline={deadline}
      intentSource={source}
      chatReady={intentSource !== undefined || ownKey}
      memory={memory}
    />
  );
}
