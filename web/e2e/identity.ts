import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { Page } from "@playwright/test";

import { mockLeagueMembersEnvelope } from "../src/fixtures/league";
import { MESSAGES, type Language } from "../src/i18n/messages";
import { PUBLIC_ROOT, shippedTrees } from "../src/testSupport/shippedTrees";

/**
 * The member a visitor said they are, as the site keeps it for the tab. Every league page
 * stands behind two steps (the league number, then "Sen kimsin?"); a spec about a page
 * behind them either seeds the second step here or takes it through the picker.
 */
export interface SeededClaim {
  leagueId: number;
  entryId: number;
  managerName: string | null;
  teamName: string | null;
  leagueName: string | null;
}

const CLAIM_KEY = "squadopt.member";
/** Marks the tab as seeded once, so a claim the spec then drops stays dropped on reload. */
const SEEDED_KEY = "squadopt.e2e.claimSeeded";

const exampleHuman = mockLeagueMembersEnvelope.payload.members.find(
  (member) => member.member_kind === "human",
)!;

/** The example league's first member, Deniz Aral (35249001), as the mocked specs serve him. */
export const EXAMPLE_CLAIM: SeededClaim = {
  leagueId: mockLeagueMembersEnvelope.payload.league_id,
  entryId: exampleHuman.entry_id!,
  managerName: exampleHuman.manager_name,
  teamName: exampleHuman.team_name,
  leagueName: mockLeagueMembersEnvelope.payload.league_name,
};

/** The first member of the first league the committed site publishes, for unmocked specs. */
export function shippedClaim(): SeededClaim {
  const tree = shippedTrees()[0]!;
  const members = JSON.parse(readFileSync(join(tree.root, "members.json"), "utf-8")) as {
    payload: {
      league_id: number;
      league_name: string;
      members: {
        member_kind: string;
        entry_id: number;
        manager_name: string | null;
        team_name: string | null;
      }[];
    };
  };
  const first = members.payload.members.find((member) => member.member_kind === "human");
  if (first === undefined) throw new Error("The published league lists no human member.");
  let leagueName: string | null = members.payload.league_name;
  try {
    const directory = JSON.parse(
      readFileSync(join(PUBLIC_ROOT, "data", "leagues.json"), "utf-8"),
    ) as { payload: { leagues: { league_id: number; league_name: string }[] } };
    leagueName =
      directory.payload.leagues.find((league) => league.league_id === members.payload.league_id)
        ?.league_name ?? leagueName;
  } catch {
    // A site from before the directory names its league in its member list only.
  }
  return {
    leagueId: members.payload.league_id,
    entryId: first.entry_id,
    managerName: first.manager_name,
    teamName: first.team_name,
    leagueName,
  };
}

/**
 * Seeds the claim in the tab before the first page loads. storageState cannot carry
 * sessionStorage, so the claim is written by an init script, once per tab.
 */
export async function claimMember(page: Page, claim: SeededClaim): Promise<void> {
  await page.addInitScript(
    ({ claim, claimKey, seededKey }) => {
      try {
        if (sessionStorage.getItem(seededKey) !== null) return;
        sessionStorage.setItem(seededKey, "1");
        sessionStorage.setItem(claimKey, JSON.stringify(claim));
      } catch {
        // A page without storage keeps no claim; the spec then meets the picker.
      }
    },
    { claim, claimKey: CLAIM_KEY, seededKey: SEEDED_KEY },
  );
}

/** A member as the picker names them: the manager, then the team. */
export interface PickedMember {
  managerName: string | null;
  teamName: string | null;
}

/** The mocked example league's member with this entry number, as the picker names them. */
export function exampleMember(entryId: number): PickedMember {
  const member = mockLeagueMembersEnvelope.payload.members.find(
    (candidate) => candidate.entry_id === entryId,
  );
  if (member === undefined) throw new Error(`The example league has no member ${entryId}.`);
  return { managerName: member.manager_name, teamName: member.team_name };
}

/** A published member list's member with this entry number, as the picker names them. */
export function publishedMember(membersPath: string, entryId: number): PickedMember {
  const members = JSON.parse(readFileSync(membersPath, "utf-8")) as {
    payload: {
      members: { entry_id: number | null; manager_name: string | null; team_name: string | null }[];
    };
  };
  const member = members.payload.members.find((candidate) => candidate.entry_id === entryId);
  if (member === undefined) throw new Error(`${membersPath} lists no member ${entryId}.`);
  return { managerName: member.manager_name, teamName: member.team_name };
}

const escapeRegExp = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/**
 * Says who you are through the picker: the member's button, found by the name a screen
 * reader hears (the entry number is not in the markup), which enters at once.
 */
export async function pickMember(
  page: Page,
  member: PickedMember,
  language: Language = "tr",
): Promise<void> {
  const list = MESSAGES[language].leagueMembers;
  const manager = escapeRegExp(member.managerName ?? list.unknownMember);
  const team = escapeRegExp(member.teamName ?? list.unknownTeam);
  await page
    .locator("[data-member-picker]")
    .getByRole("button", { name: new RegExp(`^${manager}\\s*,\\s*${team}$`) })
    .click();
}
