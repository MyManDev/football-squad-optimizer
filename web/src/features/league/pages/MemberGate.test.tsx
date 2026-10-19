/**
 * "Sen kimsin?": the member step in front of every league page. Until the visitor says who
 * they are, the page is not drawn and the picker stands in its place; the picker shows
 * names only; Onayla opens the page asked for, or the visitor's own page when they came to
 * find themselves.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PageShell } from "../../../design/components/PageShell";
import { MOTION_MS } from "../../../design/motion";
import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import {
  FIND_YOURSELF,
  memberAddress,
  membersAddress,
  PICK_HERE,
} from "../../../lib/leagueAddresses";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import {
  claimIn,
  EXAMPLE_LEAGUE,
  EXAMPLE_MEMBER,
  forgetIdentity,
  stubTree,
  withLeague,
} from "../../../testSupport/league";
import { LeagueDataError, LeagueDataMissing, type LeagueTree } from "../data";
import type { PublishedLeague } from "../directory";
import { readMemberClaim, writeMemberClaim } from "../identity/memberClaim";
import type { EntryView, LeagueMembers, LeagueViewEnvelope } from "../types";
import { MemberGate } from "./MemberGate";

const LEAGUE = EXAMPLE_LEAGUE.leagueId;
const LEAGUE_NAME = "SquadOpt Classic League";
const clients: QueryClient[] = [];
const members = vi.fn<LeagueTree["members"]>();

beforeEach(() => {
  forgetIdentity();
  members.mockReset();
  members.mockResolvedValue(mockLeagueMembersEnvelope);
  stubTree({ members });
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

/** Where the router is, and how it got there. */
function LocationProbe() {
  const location = useLocation();
  const type = useNavigationType();
  return (
    <output data-testid="location" data-key={location.key} data-type={type}>
      {`${location.pathname}${location.search}${location.hash}|${JSON.stringify(location.state)}`}
    </output>
  );
}
const probe = () => screen.getByTestId("location");
const where = () => probe().textContent!.split("|")[0];

type Entry = string | { pathname: string; hash?: string; search?: string; state?: unknown };

function client() {
  const made = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(made);
  return made;
}

function open({
  entry = membersAddress(LEAGUE),
  language = "tr",
  page = <h1>League page</h1>,
  league = EXAMPLE_LEAGUE,
  shell = false,
}: {
  entry?: Entry;
  language?: Language;
  page?: ReactNode;
  league?: PublishedLeague;
  shell?: boolean;
} = {}) {
  const gated = withLeague(<MemberGate>{page}</MemberGate>, league);
  const routes = (
    <Routes>
      <Route path="/league/:leagueId/members" element={gated} />
      <Route path="/league/:leagueId/members/:entryId" element={gated} />
    </Routes>
  );
  return render(
    <QueryClientProvider client={client()}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[entry]}>
          {shell ? <PageShell>{routes}</PageShell> : routes}
          <LocationProbe />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

const humans = mockLeagueMembersEnvelope.payload.members.filter(
  (member) => member.member_kind === "human",
);

function picker(language: Language) {
  const copy = MESSAGES[language].memberPicker;
  return screen.findByRole("group", { name: copy.legend });
}

function envelopeWith(rows: EntryView[]): LeagueViewEnvelope<LeagueMembers> {
  return {
    ...mockLeagueMembersEnvelope,
    payload: { ...mockLeagueMembersEnvelope.payload, members: rows },
  };
}

describe.each(["tr", "en"] as const)("the member step in %s", (language) => {
  const copy = MESSAGES[language].memberPicker;
  const list = MESSAGES[language].leagueMembers;

  it("asks who you are in place of the page, listing the members by name", async () => {
    open({ language });
    const group = await picker(language);
    expect(screen.getByRole("heading", { level: 1, name: copy.title })).toBeInTheDocument();
    expect(screen.getByText(copy.league(LEAGUE_NAME))).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "League page" })).toBeNull();

    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(humans.length);
    // Sorted by name, never in the file's order (the standings): Arda Demir first, the
    // member without a published name last.
    const names = radios.map((radio) => radio.closest("label")!.textContent);
    expect(names[0]).toBe("Arda Demir, Expected Threat");
    expect(names.at(-1)).toBe(`${list.unknownMember}, Awaiting Picks`);
    expect(within(group).queryByRole("radio", { name: /SquadOpt/ })).toBeNull();
    expect(group).not.toHaveTextContent("SquadOpt");
  });

  it("enables Onayla only once a name is picked", async () => {
    const user = userEvent.setup();
    open({ language });
    const group = await picker(language);
    const confirm = screen.getByRole("button", { name: copy.confirm });
    expect(confirm).toBeDisabled();
    await user.click(within(group).getByRole("radio", { name: /Mert Işık/ }));
    expect(confirm).toBeEnabled();
  });

  it("offers a different league number in every state", async () => {
    open({ language });
    await picker(language);
    expect(screen.getByRole("link", { name: copy.otherLeague })).toHaveAttribute("href", "/");
  });

  it("says a missing member list plainly, with nothing to retry", async () => {
    members.mockRejectedValue(new LeagueDataMissing("members.json"));
    open({ language });
    expect(await screen.findByText(list.notAvailable)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: MESSAGES[language].leagueEntry.retry })).toBeNull();
    expect(screen.getByRole("link", { name: copy.otherLeague })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("heading", { name: "League page" })).toBeNull();
  });

  it("reads an unreadable member list again on request, and stays closed until it can", async () => {
    const user = userEvent.setup();
    members.mockRejectedValueOnce(new LeagueDataError("503"));
    open({ language });
    expect(await screen.findByText(list.membersUnreadable)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "League page" })).toBeNull();
    expect(screen.getByRole("link", { name: copy.otherLeague })).toHaveAttribute("href", "/");
    await user.click(screen.getByRole("button", { name: MESSAGES[language].leagueEntry.retry }));
    expect(await picker(language)).toBeInTheDocument();
    expect(members).toHaveBeenCalledTimes(2);
  });

  it("says when the league has no member to pick", async () => {
    members.mockResolvedValue(
      envelopeWith(
        mockLeagueMembersEnvelope.payload.members.filter((m) => m.member_kind !== "human"),
      ),
    );
    open({ language });
    expect(await screen.findByText(copy.empty)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.otherLeague })).toHaveAttribute("href", "/");
  });
});

describe("what the picker shows of a member", () => {
  it("shows the names and nothing else: no rank, points, value or number", async () => {
    const template = humans[0]!;
    const rows: EntryView[] = [
      {
        ...template,
        entry_id: 41001,
        rank: 3,
        total_points: 517,
        gameweek_points: 63,
        transfer_cost: 8,
        manager_name: "Zeynep Ok",
        team_name: "Clubv2 99",
      },
      {
        ...template,
        entry_id: 41002,
        rank: 1,
        total_points: 604,
        gameweek_points: 71,
        transfer_cost: 4,
        manager_name: "Ali Can",
        team_name: "Pressing Trap",
      },
    ];
    members.mockResolvedValue(envelopeWith(rows));
    open();
    const group = await picker("tr");
    const labels = within(group)
      .getAllByRole("radio")
      .map((radio) => radio.closest("label")!.textContent);
    expect(labels).toEqual(["Ali Can, Pressing Trap", "Zeynep Ok, Clubv2 99"]);
    const text = group.textContent ?? "";
    const tokens = text.split(/[^\p{L}\p{N}]+/u);
    expect(tokens).toContain("99");
    for (const row of rows) {
      for (const value of [
        row.rank,
        row.total_points,
        row.gameweek_points,
        row.transfer_cost,
        row.entry_id,
      ]) {
        expect(tokens).not.toContain(String(value));
      }
    }
    // Nor in the markup: no attribute (a radio's value among them) carries an entry number.
    const markup = group.closest("[data-member-picker]")!.outerHTML;
    for (const row of rows) expect(markup).not.toContain(String(row.entry_id));
  });

  it("starts a new league's list with nothing picked", async () => {
    const user = userEvent.setup();
    const view = open();
    const group = await picker("tr");
    await user.click(within(group).getByRole("radio", { name: /Mert Işık/ }));
    expect(screen.getByRole("button", { name: "Onayla" })).toBeEnabled();

    const other: PublishedLeague = { ...EXAMPLE_LEAGUE, leagueId: 352491 };
    view.rerender(
      <QueryClientProvider client={client()}>
        <LanguageProvider initialLanguage="tr">
          <MemoryRouter initialEntries={[membersAddress(other.leagueId)]}>
            <Routes>
              <Route
                path="/league/:leagueId/members"
                element={withLeague(
                  <MemberGate>
                    <h1>League page</h1>
                  </MemberGate>,
                  other,
                )}
              />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    const next = await picker("tr");
    expect(
      within(next)
        .getAllByRole("radio")
        .some((radio) => (radio as HTMLInputElement).checked),
    ).toBe(false);
    expect(screen.getByRole("button", { name: "Onayla" })).toBeDisabled();
  });
});

describe("after Onayla", () => {
  it("opens the page asked for at the same address, with a new history key", async () => {
    const user = userEvent.setup();
    open({
      entry: { pathname: memberAddress(LEAGUE, 35249003), search: "?mode=agresif", hash: "#kadro" },
    });
    const group = await picker("tr");
    const before = probe().dataset.key;
    await user.click(within(group).getByRole("radio", { name: /Mert Işık/ }));
    await user.click(screen.getByRole("button", { name: "Onayla" }));

    expect(await screen.findByRole("heading", { name: "League page" })).toBeInTheDocument();
    expect(where()).toBe(`${memberAddress(LEAGUE, 35249003)}?mode=agresif#kadro`);
    expect(probe().dataset.type).toBe("REPLACE");
    expect(probe().dataset.key).not.toBe(before);
    expect(readMemberClaim()).toEqual({
      leagueId: LEAGUE,
      entryId: 35249002,
      managerName: "Mert Işık",
      teamName: "Half Space",
      leagueName: LEAGUE_NAME,
    });
  });

  it("opens the visitor's own page, never drawing the table first, when they came to find themselves", async () => {
    const user = userEvent.setup();
    let tableMounts = 0;
    function TableProbe() {
      useEffect(() => {
        tableMounts += 1;
      }, []);
      return <h1>Members table</h1>;
    }
    const OwnProbe = lazy(async () => ({ default: () => <h1>Own page</h1> }));
    render(
      <QueryClientProvider client={client()}>
        <LanguageProvider initialLanguage="tr">
          <MemoryRouter
            initialEntries={[{ pathname: membersAddress(LEAGUE), state: FIND_YOURSELF }]}
          >
            <Suspense fallback={<p>outer fallback</p>}>
              {withLeague(
                <Routes>
                  <Route
                    path="/league/:leagueId/members"
                    element={
                      <MemberGate>
                        <TableProbe />
                      </MemberGate>
                    }
                  />
                  <Route
                    path="/league/:leagueId/members/:entryId"
                    element={
                      <MemberGate>
                        <OwnProbe />
                      </MemberGate>
                    }
                  />
                </Routes>,
              )}
            </Suspense>
            <LocationProbe />
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    const group = await picker("tr");
    await user.click(within(group).getByRole("radio", { name: /Seda Kaya/ }));
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    expect(screen.queryByRole("heading", { name: "Members table" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "Own page" })).toBeInTheDocument();
    expect(tableMounts).toBe(0);
    expect(where()).toBe(memberAddress(LEAGUE, 35249003));
    expect(probe().dataset.type).toBe("REPLACE");
  });

  it("shows a placeholder, not the table, while the own page is on its way", async () => {
    const user = userEvent.setup();
    let release!: () => void;
    const loaded = new Promise<void>((resolve) => {
      release = resolve;
    });
    const OwnProbe = lazy(async () => {
      await loaded;
      return { default: () => <h1>Own page</h1> };
    });
    render(
      <QueryClientProvider client={client()}>
        <LanguageProvider initialLanguage="tr">
          <MemoryRouter
            initialEntries={[{ pathname: membersAddress(LEAGUE), state: FIND_YOURSELF }]}
          >
            <Suspense fallback={<p>outer fallback</p>}>
              {withLeague(
                <Routes>
                  <Route
                    path="/league/:leagueId/members"
                    element={
                      <MemberGate>
                        <h1>Members table</h1>
                      </MemberGate>
                    }
                  />
                  <Route
                    path="/league/:leagueId/members/:entryId"
                    element={
                      <MemberGate>
                        <OwnProbe />
                      </MemberGate>
                    }
                  />
                </Routes>,
              )}
            </Suspense>
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    const group = await picker("tr");
    await user.click(within(group).getByRole("radio", { name: /Seda Kaya/ }));
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    expect(screen.getByText(MESSAGES.tr.common.loading)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Members table" })).toBeNull();
    await act(async () => {
      release();
      await loaded;
    });
    expect(await screen.findByRole("heading", { name: "Own page" })).toBeInTheDocument();
  });

  it("takes a visitor already claimed in the league, who came to find themselves, to their page", async () => {
    claimIn();
    open({ entry: { pathname: membersAddress(LEAGUE), state: FIND_YOURSELF } });
    await waitFor(() => expect(where()).toBe(memberAddress(LEAGUE, EXAMPLE_MEMBER.entry_id)));
    expect(probe().dataset.type).toBe("REPLACE");
  });
});

describe("a visitor who has already said who they are", () => {
  it("sees the page and no picker", async () => {
    claimIn();
    open();
    expect(await screen.findByRole("heading", { name: "League page" })).toBeInTheDocument();
    expect(document.querySelector("[data-member-picker]")).toBeNull();
  });

  it("sees the page at once while the member list is still being read", () => {
    members.mockReturnValue(new Promise(() => {}));
    claimIn();
    open();
    expect(screen.getByRole("heading", { name: "League page" })).toBeInTheDocument();
    expect(document.querySelector("[data-member-picker]")).toBeNull();
  });

  it("is asked again when the claimed member is not in the league's list", async () => {
    claimIn(99999999);
    open();
    expect(await picker("tr")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "League page" })).toBeNull();
    expect(readMemberClaim()).toBeNull();
  });

  it("has the published names written back over outdated ones", async () => {
    claimIn(EXAMPLE_MEMBER.entry_id, LEAGUE, {
      managerName: "Old name",
      teamName: "Old team",
      leagueName: "Old league",
    });
    open();
    await waitFor(() =>
      expect(readMemberClaim()).toMatchObject({
        managerName: EXAMPLE_MEMBER.manager_name,
        teamName: EXAMPLE_MEMBER.team_name,
        leagueName: LEAGUE_NAME,
      }),
    );
  });
});

describe("the picker with a keyboard and a screen reader", () => {
  it("is used with Tab, the arrow keys, Space and Enter", async () => {
    const user = userEvent.setup();
    open();
    const group = await picker("tr");
    await user.tab();
    const radios = within(group).getAllByRole("radio");
    expect(radios[0]).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(radios[1]).toHaveFocus();
    await user.keyboard(" ");
    expect(radios[1]).toBeChecked();
    await user.tab();
    expect(screen.getByRole("button", { name: "Onayla" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "League page" })).toBeInTheDocument();
    const picked = humans
      .map((member) => member.manager_name)
      .filter((name): name is string => name !== null)
      .sort(new Intl.Collator("tr", { sensitivity: "base" }).compare)[1];
    expect(readMemberClaim()?.managerName).toBe(picked);
  });

  it.each([
    ["the league number", FIND_YOURSELF],
    ["a step asked for in place", PICK_HERE],
  ])("puts focus on the question when the visitor arrives from %s", async (_, state) => {
    open({ entry: { pathname: membersAddress(LEAGUE), state } });
    await picker("tr");
    expect(screen.getByRole("heading", { level: 1, name: "Sen kimsin?" })).toHaveFocus();
  });

  it("leaves focus alone when the address was opened directly", async () => {
    open();
    await picker("tr");
    expect(screen.getByRole("heading", { level: 1, name: "Sen kimsin?" })).not.toHaveFocus();
  });

  it("moves focus to main, then to the page's heading once it is drawn", async () => {
    const user = userEvent.setup();
    // The page draws its heading only when the test says its documents have arrived.
    let arrive: () => void = () => undefined;
    function LatePage() {
      const [ready, setReady] = useState(false);
      useEffect(() => {
        arrive = () => setReady(true);
      }, []);
      return ready ? <h1>Members table</h1> : <p>reading</p>;
    }
    open({ shell: true, page: <LatePage /> });
    const group = await picker("tr");
    await user.click(within(group).getByRole("radio", { name: /Mert Işık/ }));
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    expect(screen.getByRole("main")).toHaveFocus();
    act(() => arrive());
    const heading = await screen.findByRole("heading", { level: 1, name: "Members table" });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("scrolls to the squad in the address once the page under the picker is drawn", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const scrolled: string[] = [];
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value(this: HTMLElement) {
        scrolled.push(this.id);
      },
    });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    open({
      shell: true,
      entry: { pathname: memberAddress(LEAGUE, 35249003), hash: "#kadro" },
      page: (
        <>
          <h1>Member page</h1>
          <div id="kadro">squad</div>
        </>
      ),
    });
    const group = await picker("tr");
    // The shell's own wait for #kadro runs out while the picker is up.
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(scrolled).toEqual([]);
    await user.click(within(group).getByRole("radio", { name: /Deniz Aral/ }));
    await user.click(screen.getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(scrolled).toContain("kadro"));
  });
});

describe("the step's words", () => {
  it.each(["tr", "en"] as const)(
    "carry no dash, percentage or chance wording in %s",
    (language) => {
      const copy = MESSAGES[language];
      const words = [
        ...Object.values(copy.memberPicker).map((value) =>
          typeof value === "function" ? value(LEAGUE_NAME) : value,
        ),
        copy.shell.findLeague,
        copy.shell.changeMember,
      ];
      for (const word of words) {
        for (const banned of [String.fromCharCode(0x2013), String.fromCharCode(0x2014), "%"]) {
          expect(word).not.toContain(banned);
        }
        expect(word).not.toMatch(AS_A_CHANCE);
      }
    },
  );
});

describe("the step from the picker to the page (#1131)", () => {
  let started: Array<Promise<void> | void> = [];
  let startedAt: number[] = [];
  beforeEach(() => {
    started = [];
    startedAt = [];
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      writable: true,
      value: vi.fn((update: () => Promise<void> | void) => {
        startedAt.push(performance.now());
        started.push(update());
        return {};
      }),
    });
  });
  afterEach(() => {
    delete (document as { startViewTransition?: unknown }).startViewTransition;
    delete (window as { matchMedia?: unknown }).matchMedia;
  });

  async function pickAndConfirm(name = /Seda Kaya/) {
    const user = userEvent.setup();
    const group = await picker("tr");
    await user.click(within(group).getByRole("radio", { name }));
    await user.click(screen.getByRole("button", { name: "Onayla" }));
  }

  function reduceMotion() {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      writable: true,
      value: (query: string) => ({ matches: query === "(prefers-reduced-motion: reduce)" }),
    });
  }

  it("crossfades into the page asked for, the claim made inside the transition", async () => {
    open();
    await pickAndConfirm();
    expect(document.startViewTransition).toHaveBeenCalledOnce();
    await started[0];
    expect(readMemberClaim()?.entryId).toBe(35249003);
    expect(screen.getByRole("heading", { name: "League page" })).toBeInTheDocument();
  });

  it("crossfades into the visitor's own page once it is drawn, not into a placeholder", async () => {
    open({
      entry: { pathname: membersAddress(LEAGUE), state: FIND_YOURSELF },
      page: <h1>Own page</h1>,
    });
    await pickAndConfirm();
    expect(document.startViewTransition).toHaveBeenCalledOnce();
    let settledAt = Number.POSITIVE_INFINITY;
    await act(async () => {
      await started[0];
      settledAt = performance.now();
    });
    // When the new picture is taken, the router is already on the visitor's page.
    expect(where()).toBe(memberAddress(LEAGUE, 35249003));
    expect(screen.getByRole("heading", { name: "Own page" })).toBeInTheDocument();
    // The page's arrival ends the wait, not the data time that caps it.
    expect(settledAt - startedAt[0]).toBeLessThan(MOTION_MS.data);
  });

  it("takes one step for two confirms made before the first one's update runs", async () => {
    const waiting: Array<() => Promise<void> | void> = [];
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      writable: true,
      value: vi.fn((update: () => Promise<void> | void) => {
        waiting.push(update);
        return {};
      }),
    });
    const writes = vi.spyOn(Storage.prototype, "setItem");
    const keys: string[] = [];
    function Page() {
      const { key } = useLocation();
      useEffect(() => {
        keys.push(key);
      }, [key]);
      return <h1>League page</h1>;
    }
    open({ page: <Page /> });
    const user = userEvent.setup();
    const group = await picker("tr");
    const before = probe().dataset.key;
    await user.click(within(group).getByRole("radio", { name: /Seda Kaya/ }));
    const button = screen.getByRole("button", { name: "Onayla" });
    await user.click(button);
    await user.click(button);
    expect(document.startViewTransition).toHaveBeenCalledOnce();
    await act(async () => {
      for (const update of waiting) await update();
    });
    expect(writes.mock.calls.filter(([name]) => name === "squadopt.member")).toHaveLength(1);
    // The page is drawn under the address's first key, then under the one key the step
    // replaces it with.
    expect(keys.filter((key) => key !== before)).toHaveLength(1);
    expect(probe().dataset.type).toBe("REPLACE");
    expect(screen.getByRole("heading", { name: "League page" })).toBeInTheDocument();
  });

  it("changes at once under reduced motion", async () => {
    reduceMotion();
    open();
    await pickAndConfirm();
    expect(document.startViewTransition).not.toHaveBeenCalled();
    expect(await screen.findByRole("heading", { name: "League page" })).toBeInTheDocument();
  });

  it.each(["with a transition", "without the API", "under reduced motion"] as const)(
    "takes the step again once the member is dropped, %s",
    async (path) => {
      if (path === "without the API") {
        delete (document as { startViewTransition?: unknown }).startViewTransition;
      }
      if (path === "under reduced motion") reduceMotion();
      open();
      await pickAndConfirm();
      await act(async () => {
        await Promise.all(started);
      });
      expect(readMemberClaim()?.entryId).toBe(35249003);
      // The first step's update has run, so the second Onayla is not taken for a repeat.
      act(() => writeMemberClaim(null));
      await pickAndConfirm(/Mert Işık/);
      await act(async () => {
        await Promise.all(started);
      });
      expect(readMemberClaim()?.entryId).toBe(35249002);
    },
  );
});
