import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { coachNewsFixture, NEWS_ENTRY } from "../../../testSupport/coachNews";
import { withLeague } from "../../../testSupport/league";
import { LeagueMemberView } from "./LeagueMemberView";

afterEach(cleanup);

function show(language: Language, options: { outgoing?: boolean; failed?: boolean } = {}) {
  const { squad, document, item } = coachNewsFixture();
  const plan = structuredClone(document);
  delete plan.payload.evidence;
  if (options.outgoing) {
    plan.payload.starting_xi = plan.payload.starting_xi?.filter(
      (p) => p.player_id !== item.player_id,
    );
    plan.payload.bench = plan.payload.bench?.filter((p) => p.player_id !== item.player_id);
  }
  const index = mockEntryAdviceIndex(NEWS_ENTRY).payload;
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter
        initialEntries={[`/league/352490/members/${NEWS_ENTRY}?mode=saf-puan&window=1&llm=off`]}
      >
        {withLeague(
          <LeagueMemberView
            squad={squad}
            advice={plan}
            coachNews={options.failed ? null : document}
            index={index}
            members={mockLeagueMembersEnvelope.payload.members}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
  return { squad, item };
}

describe("the manager's source beside the player", () => {
  it.each(["tr", "en"] as const)(
    "shows the quotation and source with the planning switch off (%s)",
    (language) => {
      const { item } = show(language);
      const region = screen.getByRole("region", {
        name: language === "tr" ? "Hocanın açıklaması" : "Manager's statement",
      });
      expect(within(region).getByText(item.words!)).toBeVisible();
      expect(within(region).getByText(item.name!)).toBeVisible();
      const link = within(region).getByRole("link", {
        name: language === "tr" ? "Haberi oku" : "Read the news",
      });
      expect(link).toHaveAttribute("href", item.source_url);
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(region.querySelector("time")).toHaveAttribute("datetime", item.published_at_utc);
      expect(screen.getByRole("link", { name: new RegExp(`${item.name}:`) })).toHaveAttribute(
        "href",
        item.source_url,
      );
    },
  );

  it("retains the held player's source after a plan transfers him out", () => {
    const { item } = show("en", { outgoing: true });
    const region = screen.getByRole("region", { name: "Manager's statement" });
    expect(within(region).getByText(item.name!)).toBeVisible();
    expect(within(region).getByText(item.words!)).toBeVisible();
  });

  it("keeps the squad available without inventing news after a failed read", () => {
    show("en", { failed: true });
    expect(screen.queryByRole("region", { name: "Manager's statement" })).not.toBeInTheDocument();
    expect(document.querySelector("#kadro")).not.toBeNull();
    expect(document.querySelector("[data-coach-absence]")).toBeNull();
  });
});
