/**
 * The compute panel's states. With no service it is the panel it always was; with one it
 * offers what the capabilities allow, says when a selection was not computed ahead of time
 * and about how long it takes, tells a waiting member the page can be left open, turns a
 * coded failure into a sentence, and stays calm when the service is down.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AdviceRequestPanel, type ComputeService } from "./AdviceRequestPanel";
import type { AdviceRequest } from "./adviceClient";
import { COMPUTE_COPY } from "./computeCopy";
import type { AdviceJob, ComputePhase } from "./useAdviceJob";

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
    deadlinePassed?: boolean;
    selectionAvailable?: boolean;
    request?: AdviceRequest;
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
        deadlinePassed={props.deadlinePassed}
      />
    </LanguageProvider>,
  );
  return { ...view, compute, button: screen.getByRole("button", { name: /Hesapla|Compute/ }) };
}

const tr = COMPUTE_COPY.tr;
const messages = MESSAGES.tr.leagueMembers;

describe("with no compute service", () => {
  it("keeps the old sentence back while a configured service has not answered yet", () => {
    // The service computes a rival strategy over three weeks; saying it does not, for the
    // half second before its capabilities arrive, is a sentence the page takes back.
    const { container, button } = renderPanel({ pending: true });
    expect(button).toBeDisabled();
    expect(container).not.toHaveTextContent(messages.computeUnsupportedSelection);
  });

  it("says nothing new and keeps the old rule for what can be computed", () => {
    const { container, button } = renderPanel();
    expect(button).toBeDisabled(); // a rival strategy over three weeks, as before
    expect(container).toHaveTextContent(messages.computeUnsupportedSelection);
    for (const text of [tr.notPrecomputed, tr.duration[3], tr.serviceUnreachable, tr.leaveOpen]) {
      expect(container).not.toHaveTextContent(text);
    }
  });

  it("still says unavailable and failed in the words it always used", () => {
    expect(
      renderPanel({ state: { phase: "unavailable", request: REQUEST } }).container,
    ).toHaveTextContent(messages.computeUnavailable);
    cleanup();
    expect(
      renderPanel({ state: { phase: "failed", request: REQUEST } }).container,
    ).toHaveTextContent(messages.computeFailed);
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
    expect(container).toHaveTextContent(tr.durationNote);
    expect(container).not.toHaveTextContent(messages.computeUnsupportedSelection);
    button.click();
    expect(compute).toHaveBeenCalledWith(REQUEST);
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
    expect(chip.container).toHaveTextContent(tr.chipUnavailable);
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

describe("with a service that cannot help right now", () => {
  it("leaves a short notice and the static rule when it is down", () => {
    const { container, button } = renderPanel({
      service: "unreachable",
      selectionAvailable: true,
      request: { ...REQUEST, strategy: "saf-puan", window: 1, rivalEntryId: null },
    });
    expect(container).toHaveTextContent(tr.serviceUnreachable);
    expect(button).toBeEnabled(); // the click lands on the published answer
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("switches Compute off when the service works from another capture", () => {
    const { container, button } = renderPanel({
      service: "other-capture",
      selectionAvailable: true,
      request: { ...REQUEST, strategy: "saf-puan", window: 1, rivalEntryId: null },
    });
    expect(container).toHaveTextContent(tr.otherCapture);
    expect(container).not.toHaveTextContent(messages.computeUnsupportedSelection);
    expect(button).toBeDisabled();
  });
});

describe("a gameweek whose deadline has passed", () => {
  it("asks nothing of a ready service and says why, in both languages", () => {
    for (const language of ["tr", "en"] as const) {
      const { button, compute } = renderPanel(
        { service: "ready", computable: true, deadlinePassed: true },
        language,
      );
      expect(button).toBeDisabled();
      button.click();
      expect(compute).not.toHaveBeenCalled();
      expect(screen.getByText(COMPUTE_COPY[language].deadlinePassedCompute)).toBeInTheDocument();
      // The duration sentence belongs to a computation that can still be asked for.
      expect(screen.queryByText(COMPUTE_COPY[language].durationNote, { exact: false })).toBeNull();
      cleanup();
    }
  });

  it("does not stack the unreachable or other-capture notes on top of it", () => {
    renderPanel({ service: "unreachable", deadlinePassed: true });
    expect(screen.queryByText(COMPUTE_COPY.tr.serviceUnreachable)).toBeNull();
    cleanup();
    renderPanel({ service: "other-capture", deadlinePassed: true });
    expect(screen.queryByText(COMPUTE_COPY.tr.otherCapture)).toBeNull();
    expect(screen.getAllByRole("note")).toHaveLength(1);
  });
});
