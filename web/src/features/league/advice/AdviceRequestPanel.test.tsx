/**
 * The compute panel's states. With no service it is the panel it always was; with one it
 * offers what the capabilities allow, says that a selection can be computed now and about
 * how long it takes, tells a waiting member the page can be left open, turns a coded failure
 * into a sentence, and stays calm when the service is down.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import type { DevicePlan } from "../device/useDevicePlan";
import { AdviceRequestPanel, type ComputeService } from "./AdviceRequestPanel";
import type { AdviceRequest } from "./adviceClient";
import { COMPUTE_COPY } from "./computeCopy";
import type { AdviceJob, ComputePhase, EarlierAnswer, WaitingPhase } from "./useAdviceJob";

afterEach(cleanup);

const REQUEST: AdviceRequest = {
  leagueId: 352490,
  entryId: 35249001,
  strategy: "ortak-koru",
  window: 3,
  rivalEntryId: 35249002,
};

function renderPanel(
  props: {
    state?: ComputePhase;
    service?: ComputeService;
    computable?: boolean;
    published?: boolean;
    chipChosen?: boolean;
    pending?: boolean;
    selectionAvailable?: boolean;
    request?: AdviceRequest;
    device?: DevicePlan;
  } = {},
  language: Language = "tr",
) {
  const compute = vi.fn();
  const job: AdviceJob = { state: props.state ?? { phase: "idle" }, compute, reset: vi.fn() };
  const view = render(
    <LanguageProvider initialLanguage={language}>
      <AdviceRequestPanel
        request={props.request ?? REQUEST}
        job={job}
        selectionAvailable={props.selectionAvailable}
        service={props.service}
        computable={props.computable}
        published={props.published}
        chipChosen={props.chipChosen}
        pending={props.pending}
        device={props.device}
      />
    </LanguageProvider>,
  );
  return { ...view, compute, button: screen.getByRole("button", { name: /^(Hesapla|Compute)$/ }) };
}

const device = (state: DevicePlan["state"]): DevicePlan => ({
  available: true,
  state,
  run: vi.fn(),
  reset: vi.fn(),
});

const tr = COMPUTE_COPY.tr;
const messages = MESSAGES.tr.leagueMembers;

describe("with a solve on the member's device", () => {
  const panel = (state: DevicePlan["state"]) => (
    <LanguageProvider initialLanguage="tr">
      <AdviceRequestPanel
        request={REQUEST}
        job={{ state: { phase: "idle" }, compute: vi.fn(), reset: vi.fn() }}
        device={{ available: true, state, run: vi.fn(), reset: vi.fn() }}
      />
    </LanguageProvider>
  );

  it("gives focus back to its button when the cover goes, and the button says how it ended", () => {
    const view = render(panel({ phase: "idle" }));
    const button = screen.getByRole("button", { name: messages.deviceButton });
    expect(button).not.toHaveAttribute("aria-describedby");

    view.rerender(panel({ phase: "loading", progress: { step: "inputs", done: 0, total: null } }));
    expect(screen.getByRole("region", { name: messages.deviceSolving })).toHaveFocus();

    view.rerender(panel({ phase: "failed" }));
    expect(button).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent(messages.deviceFailed);
    expect(button).toHaveAccessibleDescription(messages.deviceFailed);
  });
});

describe("a job at the service", () => {
  const waiting = (said: Partial<WaitingPhase>): ComputePhase => ({
    phase: "waiting",
    request: REQUEST,
    jobId: "job-1",
    status: "queued",
    fallback: null,
    ...said,
  });
  const show = (said: Partial<WaitingPhase>, language: Language = "tr") =>
    renderPanel({ service: "ready", computable: true, state: waiting(said) }, language);
  const bar = () => screen.getByRole("progressbar", { name: messages.computeRunning });
  const workersLabel = tr.workersBusy(0, 0).split(":")[0]!;
  const stateLine = (container: HTMLElement) => container.querySelector("[data-compute-dock] p");
  const stageInHand = (container: HTMLElement) => container.querySelector("[data-stage-now]");

  it("says its place in line and the workers at work, with no bar, while queued", () => {
    const { container } = show({ queuePosition: 2, workers: { busy: 3, total: 3 } });
    expect(container).toHaveTextContent(messages.computeQueued);
    expect(container).toHaveTextContent(tr.queueAhead(2));
    expect(container).toHaveTextContent(tr.workersBusy(3, 3));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("says when it is next", () => {
    const { container } = show({ queuePosition: 0 });
    expect(container).toHaveTextContent(tr.queueNext);
    expect(container).not.toHaveTextContent(tr.queueAhead(0));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("says how much is solved and who is at work while it runs", () => {
    const { container } = show({
      status: "running",
      progress: { done: 1, total: 3 },
      workers: { busy: 1, total: 1 },
    });
    expect(container).toHaveTextContent(messages.computeRunning);
    expect(container).toHaveTextContent("%33");
    expect(container).toHaveTextContent(tr.workersBusy(1, 1));
    expect(container).not.toHaveTextContent(messages.computeQueued);
    expect(bar()).toHaveAttribute("aria-valuemin", "0");
    expect(bar()).toHaveAttribute("aria-valuenow", "33");
    expect(bar()).toHaveAttribute("aria-valuemax", "100");
    expect(bar()).toHaveAttribute("aria-valuetext", "%33");
    expect(stageInHand(container)).not.toBeNull();
  });

  it("has no stage in hand once every stage is solved", () => {
    const { container } = show({ status: "running", progress: { done: 3, total: 3 } });
    expect(container).toHaveTextContent("%100");
    expect(bar()).toHaveAttribute("aria-valuenow", "100");
    expect(stageInHand(container)).toBeNull();
  });

  it("shows a job of one stage as the bar alone, with no percentage and no value", () => {
    const { container } = show({ status: "running", progress: { done: 0, total: 1 } });
    expect(container).not.toHaveTextContent("%");
    expect(bar()).not.toHaveAttribute("aria-valuenow");
    expect(bar()).not.toHaveAttribute("aria-valuemax");
    expect(bar()).not.toHaveAttribute("aria-valuetext");
    expect(stageInHand(container)).not.toBeNull();
  });

  it("leaves the word alone with a service that says nothing, and the bar while it runs", () => {
    const queued = show({});
    expect(queued.container).toHaveTextContent(messages.computeQueued);
    expect(queued.container).not.toHaveTextContent(workersLabel);
    expect(screen.queryByRole("progressbar")).toBeNull();
    queued.unmount();

    const { container } = show({ status: "running" });
    expect(container).toHaveTextContent(messages.computeRunning);
    expect(container).not.toHaveTextContent(workersLabel);
    expect(container).not.toHaveTextContent("%");
    expect(bar()).not.toHaveAttribute("aria-valuenow");
    expect(stageInHand(container)).not.toBeNull();
  });

  it.each([
    ["none alive", { status: "running", workers: { busy: 0, total: 0 } }],
    ["none alive while queued", { status: "queued", workers: { busy: 0, total: 0 } }],
    ["none busy on a running job", { status: "running", workers: { busy: 0, total: 1 } }],
  ] as const)("leaves out the workers with %s", (_name, said) => {
    const { container } = show(said);
    expect(container).not.toHaveTextContent(workersLabel);
  });

  it("names no word and draws no bar until the service has said where the job stands", () => {
    const { container, button } = show({ status: null });
    expect(container).not.toHaveTextContent(messages.computeQueued);
    expect(container).not.toHaveTextContent(messages.computeRunning);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(button).toBeDisabled();
    expect(container).toHaveTextContent(tr.leaveOpen);
  });

  it("has the bar say the share to a screen reader, and the line say a place in line", () => {
    const running = show({ status: "running", progress: { done: 1, total: 3 } });
    expect(screen.getByText("%33")).toHaveAttribute("aria-hidden", "true");
    running.unmount();
    show({ queuePosition: 2 });
    expect(screen.getByText(tr.queueAhead(2))).not.toHaveAttribute("aria-hidden");
  });

  it("starts the stage in hand over at each answer from the service, and only then", () => {
    const panel = (answers: number) => (
      <LanguageProvider initialLanguage="tr">
        <AdviceRequestPanel
          request={REQUEST}
          job={{
            state: waiting({ status: "running", progress: { done: 1, total: 3 }, answers }),
            compute: vi.fn(),
            reset: vi.fn(),
          }}
          service="ready"
          computable
        />
      </LanguageProvider>
    );
    const view = render(panel(1));
    const first = stageInHand(view.container);
    view.rerender(panel(1));
    expect(stageInHand(view.container)).toBe(first);
    view.rerender(panel(2));
    expect(stageInHand(view.container)).not.toBeNull();
    expect(stageInHand(view.container)).not.toBe(first);
  });

  it("says only its word and its share on the state line", () => {
    const { container } = show({
      status: "running",
      progress: { done: 2, total: 3 },
      workers: { busy: 2, total: 3 },
    });
    expect(stateLine(container)).toHaveTextContent(new RegExp(`^${messages.computeRunning} %67$`));
    expect(container).toHaveTextContent(tr.leaveOpen);
  });

  it("speaks the member's language", () => {
    const english = COMPUTE_COPY.en;
    const view = show({ queuePosition: 1, workers: { busy: 2, total: 3 } }, "en");
    const { container } = view;
    expect(container).toHaveTextContent(MESSAGES.en.leagueMembers.computeQueued);
    expect(container).toHaveTextContent(english.queueAhead(1));
    expect(container).toHaveTextContent(english.workersBusy(2, 3));
    view.unmount();
    const running = show({ status: "running", progress: { done: 1, total: 3 } }, "en");
    expect(running.container).toHaveTextContent("33%");
  });
});

describe("with no compute service", () => {
  it("says nothing while a configured service has not answered yet", () => {
    const { button } = renderPanel({ pending: true });
    expect(button).toBeDisabled();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("says nothing new and keeps the old rule for what can be computed", () => {
    const { container, button } = renderPanel();
    expect(button).toBeDisabled(); // a rival strategy over three weeks, as before
    expect(screen.queryByRole("note")).toBeNull();
    for (const text of [tr.notPrecomputed, tr.duration[3], tr.leaveOpen]) {
      expect(container).not.toHaveTextContent(text);
    }
  });

  it("says a failure did not finish, and nothing for an unavailable answer with no reason", () => {
    const unavailable = renderPanel({ state: { phase: "unavailable", request: REQUEST } });
    expect(unavailable.container.querySelector("p")).toBeNull();
    cleanup();
    expect(
      renderPanel({ state: { phase: "failed", request: REQUEST } }).container,
    ).toHaveTextContent(messages.computeFailed);
  });
});

describe("the finished answer", () => {
  const envelope = mockEntryAdviceEnvelope(REQUEST.entryId, REQUEST.strategy, REQUEST.window);

  it("is marked ready when computed, with no capture identity or date beside it", () => {
    const { container } = renderPanel({
      state: { phase: "done", request: REQUEST, envelope, source: "api-cache" },
    });
    expect(container).toHaveTextContent(messages.computeDone);
    expect(container).not.toHaveTextContent(String(envelope.payload.source_snapshot_id));
  });

  it("is marked ready when the press lands on the published tree", () => {
    const { container, button } = renderPanel({
      state: { phase: "done", request: REQUEST, envelope, source: "static" },
      request: { ...REQUEST, strategy: "saf-puan", window: 1, rivalEntryId: null },
    });
    expect(container).toHaveTextContent(messages.computeDone);
    expect(container).not.toHaveTextContent(messages.computeStaticFallback);
    expect(button).toBeEnabled();
  });

  it("says the service could not be reached when it fell back", () => {
    const { container } = renderPanel({
      state: { phase: "done", request: REQUEST, envelope, source: "static-fallback" },
    });
    expect(container).toHaveTextContent(messages.computeStaticFallback);
    expect(container).not.toHaveTextContent(messages.computeDone);
  });
});

describe("with the selection's earlier answer kept on the page", () => {
  const earlier: EarlierAnswer = {
    envelope: mockEntryAdviceEnvelope(REQUEST.entryId, REQUEST.strategy, REQUEST.window),
    source: "api-cache",
  };
  const published = mockEntryAdviceEnvelope(REQUEST.entryId, "saf-puan", 1);

  it("says only that the plan will come while this computes", () => {
    const { container } = renderPanel({
      service: "ready",
      computable: true,
      state: {
        phase: "waiting",
        request: REQUEST,
        jobId: "job-1",
        status: "running",
        fallback: published,
        earlier,
      },
    });
    expect(container).toHaveTextContent(tr.leaveOpen);
    expect(container.querySelector("[data-compute-dock] p")).toHaveTextContent(
      new RegExp(`^${messages.computeRunning}$`),
    );
  });

  it.each(["SERVICE_UNREACHABLE", "CHIP_NOT_HELD", null] as const)(
    "says only what happened after a failure (%s)",
    (reason) => {
      const { container } = renderPanel({
        service: "ready",
        computable: true,
        state: { phase: "failed", request: REQUEST, reason, earlier },
      });
      const sentence = reason ? tr.failures[reason]! : messages.computeFailed;
      expect(container.querySelector("p")).toHaveTextContent(new RegExp(`^${sentence}$`));
    },
  );

  it("names the wait a rate limit asked for", () => {
    const { container } = renderPanel({
      service: "ready",
      computable: true,
      state: {
        phase: "failed",
        request: REQUEST,
        reason: "RATE_LIMITED",
        retryAfterSeconds: 45,
        earlier,
      },
    });
    expect(container).toHaveTextContent(tr.rateLimitedFor(45));
  });

  it("says why the service is unavailable when it gave a reason, and nothing when not", () => {
    const { container } = renderPanel({
      state: { phase: "unavailable", request: REQUEST, earlier },
    });
    expect(container.querySelector("p")).toBeNull();
    cleanup();
    const second = renderPanel({
      state: { phase: "unavailable", request: REQUEST, reason: "ADVICE_BACKEND_DISABLED", earlier },
    });
    expect(second.container).toHaveTextContent(tr.failures.unknown);
  });
});

describe("with the service answering", () => {
  it("offers a selection nobody published, with about how long it takes", () => {
    const { container, button, compute } = renderPanel({
      service: "ready",
      computable: true,
      published: false,
    });
    expect(button).toBeEnabled();
    expect(container).toHaveTextContent(tr.notPrecomputed);
    expect(container).toHaveTextContent(tr.duration[3]);
    button.click();
    expect(compute).toHaveBeenCalledWith(REQUEST);
  });

  it("invites a press only while one can still be made", () => {
    const envelope = mockEntryAdviceEnvelope(REQUEST.entryId, REQUEST.strategy, REQUEST.window);
    const invites = (state: ComputePhase) => {
      const { container } = renderPanel({
        service: "ready",
        computable: true,
        published: false,
        state,
      });
      const shown = container.textContent?.includes(tr.notPrecomputed);
      cleanup();
      return shown;
    };
    expect(invites({ phase: "idle" })).toBe(true);
    expect(invites({ phase: "failed", request: REQUEST, reason: "NOT_READY" })).toBe(true);
    expect(invites({ phase: "requesting", request: REQUEST })).toBe(false);
    expect(
      invites({ phase: "waiting", request: REQUEST, jobId: "j", status: "queued", fallback: null }),
    ).toBe(false);
    expect(
      invites({
        phase: "waiting",
        request: REQUEST,
        jobId: "j",
        status: "running",
        fallback: null,
      }),
    ).toBe(false);
    expect(invites({ phase: "done", request: REQUEST, envelope, source: "api-cache" })).toBe(false);
    expect(invites({ phase: "unavailable", request: REQUEST, reason: "NOT_READY" })).toBe(false);
  });

  it.each([
    [1, tr.duration[1]],
    [5, tr.duration[5]],
  ] as const)(
    "names the %i-week duration for a published plan without calling it new",
    (window, text) => {
      const { container } = renderPanel({
        service: "ready",
        computable: true,
        published: true,
        request: { ...REQUEST, strategy: "saf-puan", window, rivalEntryId: null },
      });
      expect(container).toHaveTextContent(text);
      expect(container).not.toHaveTextContent(tr.notPrecomputed);
    },
  );

  it("is off, and says which way out, for what the service does not compute", () => {
    const plain = renderPanel({ service: "ready", computable: false });
    expect(plain.button).toBeDisabled();
    expect(plain.container).toHaveTextContent(tr.notComputable);
    expect(plain.container).not.toHaveTextContent(tr.duration[3]);
    cleanup();
    const chip = renderPanel({ service: "ready", computable: false, chipChosen: true });
    expect(chip.button).toBeDisabled();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("tells a waiting member the page can be left open", () => {
    const { container, button } = renderPanel({
      service: "ready",
      computable: true,
      state: { phase: "waiting", request: REQUEST, jobId: "j", status: "running", fallback: null },
    });
    expect(button).toBeDisabled();
    expect(container).toHaveTextContent(messages.computeRunning);
    expect(container).toHaveTextContent(tr.leaveOpen);
  });

  it.each([
    ["tr", "TOP100_INPUTS_UNAVAILABLE"],
    ["en", "TOP100_INPUTS_UNAVAILABLE"],
    ["tr", "OPEN_JOB_LIMITED"],
    ["en", "OPEN_JOB_LIMITED"],
    ["tr", "DEADLINE_PASSED"],
    ["en", "DEADLINE_PASSED"],
  ] as const)("says a coded failure in %s: %s", (language, reason) => {
    const copy = COMPUTE_COPY[language];
    const { container } = renderPanel(
      {
        service: "ready",
        computable: true,
        state: { phase: "failed", request: REQUEST, reason },
      },
      language,
    );
    expect(container).toHaveTextContent(copy.failures[reason]!);
    expect(container).not.toHaveTextContent(reason);
  });

  it("names the rate limit's wait, and an unknown code only generally", () => {
    const limited = renderPanel({
      service: "ready",
      computable: true,
      state: { phase: "failed", request: REQUEST, reason: "RATE_LIMITED", retryAfterSeconds: 60 },
    });
    expect(limited.container).toHaveTextContent(tr.rateLimitedFor(60));
    cleanup();
    const unknown = renderPanel({
      service: "ready",
      computable: true,
      state: { phase: "failed", request: REQUEST, reason: "BRAND_NEW_CODE" },
    });
    expect(unknown.container).toHaveTextContent(tr.failures.unknown);
    expect(unknown.container).not.toHaveTextContent("BRAND_NEW_CODE");
  });

  it("says why the service could not help when nothing published stands in", () => {
    const { container } = renderPanel({
      service: "ready",
      computable: true,
      state: { phase: "unavailable", request: REQUEST, reason: "SERVICE_UNREACHABLE" },
    });
    expect(container).toHaveTextContent(tr.failures.SERVICE_UNREACHABLE!);
  });
});

describe.each([
  ["tr", "Bu cihazda hesaplanıyor…"],
  ["en", "Computing on this device…"],
] as const)("the device's run in %s", (language, sentence) => {
  it.each(["loading", "solving"] as const)("says it is computing while %s", (phase) => {
    const { container } = renderPanel({ device: device({ phase }) }, language);
    expect(container.querySelector(`[data-device-state='${phase}']`)?.textContent).toBe(sentence);
  });
});

describe("with a service that cannot help right now", () => {
  it.each(["tr", "en"] as const)("says nothing about what was published in %s", (language) => {
    for (const published of [true, false, undefined]) {
      renderPanel({ service: "unreachable", published }, language);
      expect(screen.queryByRole("note")).toBeNull();
      cleanup();
    }
  });

  it("offers the device while it can still answer a selection nobody published", () => {
    const note = () => screen.queryByRole("note");
    renderPanel({ service: "unreachable", published: false, device: device({ phase: "idle" }) });
    expect(note()).toHaveTextContent(tr.serviceUnreachableDevice);
    cleanup();
    renderPanel({ service: "unreachable", published: true, device: device({ phase: "idle" }) });
    expect(note()).toBeNull();
    cleanup();
    renderPanel({ service: "unreachable", published: false, device: device({ phase: "failed" }) });
    expect(note()).toBeNull();
  });

  it("keeps the ready-service duration while the publication is unconfirmed", () => {
    const { container } = renderPanel({ service: "ready", computable: true });
    expect(container).not.toHaveTextContent(tr.notPrecomputed);
    expect(container).toHaveTextContent(tr.duration[3]);
  });

  it("keeps the static rule, and raises no alert, when it is down", () => {
    const { button } = renderPanel({
      service: "unreachable",
      selectionAvailable: true,
      request: { ...REQUEST, strategy: "saf-puan", window: 1, rivalEntryId: null },
    });
    expect(button).toBeEnabled(); // the click lands on the published answer
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("switches Compute off when the service works from another capture", () => {
    const { button } = renderPanel({
      service: "other-capture",
      selectionAvailable: true,
      request: { ...REQUEST, strategy: "saf-puan", window: 1, rivalEntryId: null },
    });
    expect(screen.queryByRole("note")).toBeNull();
    expect(button).toBeDisabled();
  });
});
