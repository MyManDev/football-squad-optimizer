import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { Language } from "../../i18n/messages";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../testSupport/honesty";
import { MemberLiveScoreCard } from "./MemberLiveScoreCard";
import { scoreMemberWeek, type LiveWeekScore } from "./officialScoring";
import vectors from "./officialScoring.vectors.json";

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
      screen.getByText(language === "tr" ? "Bonus bekleniyor" : "Bonus pending"),
    ).toBeInTheDocument();
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
      screen.getByText(language === "tr" ? "Bonus eklendi" : "Bonus added"),
    ).toBeInTheDocument();
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
  const net = () => screen.getByText("Net puan", { exact: true }).nextElementSibling;
  const { rerender } = render(
    <MemberLiveScoreCard gameweek={8} score={{ ...score, net: 0 }} names={names} />,
  );
  expect(net()).toHaveTextContent(/^0$/);
  rerender(<MemberLiveScoreCard gameweek={8} score={{ ...score, net: -4 }} names={names} />);
  expect(net()).toHaveTextContent(/^-4$/);
});
