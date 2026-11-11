import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { Language } from "../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../testSupport/honesty";
import { MemberLiveScoreCard } from "./MemberLiveScoreCard";
import { scoreMemberWeek, type LiveWeekScore } from "./officialScoring";
import vectors from "./officialScoring.vectors.json";
import type { PlayerActivity } from "./playerActivity";

afterEach(cleanup);
const names = new Map(Array.from({ length: 15 }, (_, index) => [index + 1, `Player ${index + 1}`]));
const result = (name = "normal-week", pending = false) => {
  const input = structuredClone(vectors.cases.find((row) => row.name === name)!.input);
  if (pending) input.fixtures[0]!.finished = false;
  return scoreMemberWeek(input, input.members[0]);
};
const show = (score: LiveWeekScore | null, language: Language = "tr", options = {}) =>
  render(
    <LanguageProvider initialLanguage={language}>
      <MemberLiveScoreCard gameweek={8} score={score} names={names} {...options} />
    </LanguageProvider>,
  );

describe.each(["tr", "en"] as const)("member live score in %s", (language) => {
  it("shows the supplied net, hit, progress and source time during play", () => {
    const score = result("transfer-hit", true);
    if (score.refused) throw new Error(score.reason);
    const { container } = show(score, language);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("8");
    expect(screen.getByText(String(score.net), { exact: true })).toBeInTheDocument();
    expect(screen.getByText(String(score.transfer_cost), { exact: true })).toBeInTheDocument();
    expect(screen.getByText("0 / 1")).toBeInTheDocument();
    expect(
      screen.getByText(language === "tr" ? "Bonus bekleniyor" : "Bonus Pending"),
    ).toBeInTheDocument();
    expect(screen.getByText(language === "tr" ? "Güncellendi" : "Updated")).toBeInTheDocument();
    expect(container.querySelector("time")).toHaveAttribute("datetime", score.source_time);
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
    expect(container.textContent).not.toMatch(AS_A_CAVEAT);
  });
  it("shows settled substitutions and the effective captain by name", () => {
    const score = result("goalkeeper-swap");
    if (score.refused) throw new Error(score.reason);
    show(score, language);
    expect(screen.getByText("Player 1")).toBeInTheDocument();
    expect(screen.getByText("Player 12")).toBeInTheDocument();
    expect(screen.getByText(names.get(score.captain!)!)).toBeInTheDocument();
    expect(
      screen.getByText(language === "tr" ? "Bonus eklendi" : "Bonus Added"),
    ).toBeInTheDocument();
  });
  it("draws the forecast before the live points, each under its own word", () => {
    const score = result("transfer-hit", true);
    if (score.refused) throw new Error(score.reason);
    const { container } = show(score, language, { forecast: 61.25 });
    const text = container.textContent ?? "";
    const forecastWord = language === "tr" ? "Tahmin" : "Forecast";
    const liveWord = language === "tr" ? "Canlı puan" : "Live Points";
    expect(text.indexOf(forecastWord)).toBeGreaterThanOrEqual(0);
    expect(text.indexOf(forecastWord)).toBeLessThan(text.indexOf(liveWord));
    expect(screen.getByText(language === "tr" ? "61,3" : "61.3")).toBeInTheDocument();
  });

  it("leaves no card for absent or refused data", () => {
    expect(show(null, language).container).toBeEmptyDOMElement();
    cleanup();
    expect(
      show({ refused: true, reason: "missing_pick" }, language).container,
    ).toBeEmptyDOMElement();
  });
});

it("refreshes only on the member's press and disables that action during a read", () => {
  const refresh = vi.fn();
  const score = result();
  const { rerender } = render(
    <MemberLiveScoreCard gameweek={8} score={score} names={names} onRefresh={refresh} />,
  );
  expect(refresh).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Yenile" }));
  expect(refresh).toHaveBeenCalledTimes(1);
  rerender(
    <MemberLiveScoreCard gameweek={8} score={score} names={names} onRefresh={refresh} refreshing />,
  );
  const button = screen.getByRole("button", { name: "Yenileniyor" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(refresh).toHaveBeenCalledTimes(1);
});

it("does not replace a missing player name with an invented label", () => {
  expect(
    show(result("goalkeeper-swap"), "tr", { names: new Map() }).container,
  ).toBeEmptyDOMElement();
});

it("keeps a real zero and a negative score visible in the net stat", () => {
  const score = result();
  if (score.refused) throw new Error(score.reason);
  // The transfer hit stat also shows "0" here, so read the value next to the net label only.
  const net = () => screen.getByText("Canlı puan", { exact: true }).nextElementSibling;
  const { rerender } = render(
    <MemberLiveScoreCard gameweek={8} score={{ ...score, net: 0 }} names={names} />,
  );
  expect(net()).toHaveTextContent(/^0$/);
  rerender(<MemberLiveScoreCard gameweek={8} score={{ ...score, net: -4 }} names={names} />);
  expect(net()).toHaveTextContent(/^-4$/);
});

describe("the live score beside the GOL board", () => {
  it("holds back what the board has still to bring, and counts in whole points", () => {
    const score = result("transfer-hit", true);
    if (score.refused) throw new Error(score.reason);
    show(score, "tr", { held: 4 });
    const figure = document.querySelector("[data-live-total]")!;
    expect(figure.textContent).toBe((score.net - 4).toLocaleString("tr-TR"));
    expect(figure.textContent).not.toMatch(/[.,]\d/);
  });

  it("keeps the read before's lists under the figures while the board brings this one's", () => {
    const before = result("normal-week");
    const now = result("goalkeeper-swap");
    if (before.refused || now.refused) throw new Error("refused");
    expect(before.autosubs).toEqual([]);
    expect(now.autosubs.length).toBeGreaterThan(0);
    show(now, "tr", { lists: { score: before, activity: null } });
    // The figures are this read's; the substitutions are still the read before's.
    expect(document.querySelector("[data-live-total]")!.textContent).toBe(
      now.net.toLocaleString("tr-TR"),
    );
    expect(screen.queryByText("Player 12")).toBeNull();
    cleanup();
    show(now, "tr");
    expect(screen.getByText("Player 12")).toBeInTheDocument();
  });
});

describe("the players' strip", () => {
  /** A starter and a reserve who both scored, the reserve's match still being played. */
  const scorers = (starter: number, reserve: number): PlayerActivity[] =>
    [starter, reserve].map((elementId) => ({
      elementId,
      matchInProgress: elementId === reserve,
      goals: 1,
      assists: 0,
      appearances: [{ element_id: elementId, fixture_id: 1, minutes: 60, goals: 1, assists: 0 }],
    }));
  const strip = () => screen.queryByRole("list", { name: "Oyuncular" });

  it("leaves out a reserve the scorer does not count, goal and all", () => {
    const score = result("normal-week");
    if (score.refused) throw new Error(score.reason);
    const reserve = 12;
    expect(score.counted).not.toContain(reserve);
    show(score, "tr", { activity: scorers(1, reserve) });
    expect(strip()).toHaveTextContent("Player 1");
    expect(strip()).not.toHaveTextContent(`Player ${reserve}`);
  });

  it("lists the bench under the bench boost, as the scorer counts it", () => {
    const score = result("bench-boost");
    if (score.refused) throw new Error(score.reason);
    const reserve = 12;
    expect(score.counted).toContain(reserve);
    show(score, "tr", { activity: scorers(1, reserve) });
    expect(strip()).toHaveTextContent("Player 1");
    expect(strip()).toHaveTextContent(`Player ${reserve}`);
  });
});
