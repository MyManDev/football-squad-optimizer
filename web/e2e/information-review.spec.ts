import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../src/fixtures/league";
import { mockInformationReview } from "../src/fixtures/information";
import type { AdviceLineup, AdviceLineupExpectation } from "../src/features/league/types";
import { isAdvicePayload } from "../src/features/league/advice/adviceShape";
import { installLeagueMocks } from "./leagueMocks";

/** Hypothetical arithmetic fixture, not a captured forecast or a measured gain.
 * Only the starting keeper is uncertain: q=.5, conditional points=6. His reserve
 * always plays for 2 points; all outfield players always play for 4 points. Thus
 * 43 starting +1 autosub +3 captain +2 vice =49. Later news gives 52 or 46,
 * whose equal-weight mean remains 49. Same-position swaps preserve a legal XI.
 */
function expectedAnswer(window: 3 | 5) {
  const answer = mockEntryAdviceEnvelope(35249001, "saf-puan", window);
  const roles = (index: number): AdviceLineup => {
    const starting_xi = answer.payload.starting_xi!.map((player) => ({
      ...player,
      expected_points: 4,
    }));
    const bench = answer.payload.bench!.map((player) => ({ ...player, expected_points: 4 }));
    if (index % 2) {
      const reserve = bench.findIndex((player) => player.position !== "GK");
      const starter = starting_xi.findIndex(
        (player) => player.position === bench[reserve]!.position,
      );
      [starting_xi[starter], bench[reserve]] = [bench[reserve]!, starting_xi[starter]!];
    }
    const captain = starting_xi.find((player) => player.position === "GK")!;
    captain.expected_points = 3;
    const keeper = bench.find((player) => player.position === "GK")!;
    keeper.expected_points = 2;
    const outfield = bench.filter((player) => player.position !== "GK");
    const offset = index % outfield.length;
    return {
      starting_xi,
      captain,
      vice_captain: starting_xi.filter((player) => player.position !== "GK")[index % 10]!,
      bench: [keeper, ...outfield.slice(offset), ...outfield.slice(0, offset)],
    };
  };
  const names = (lineup: AdviceLineup): AdviceLineup<string> => ({
    starting_xi: lineup.starting_xi.map((player) => player.name),
    captain: lineup.captain.name,
    vice_captain: lineup.vice_captain.name,
    bench: lineup.bench.map((player) => player.name),
  });
  const expectation: AdviceLineupExpectation = {
    version: "expected_lineup_v1",
    expected_net_points: 49,
    starting_points: 43,
    autosub_points: 1,
    captain_bonus_points: 3,
    vice_bonus_points: 2,
    bench_boost_points: 0,
    assumptions: [
      "independent_player_week_appearances",
      "unconditional_weekly_points_already_include_appearance",
      "any_positive_gameweek_minutes_including_cameos_block_autosubs",
      "double_gameweek_appearance_probability_is_supplied_by_the_caller",
    ],
  };
  const first = roles(0);
  const review = mockInformationReview(window);
  review.player_name = first.captain.name;
  review.source_playing_chance_percent = 50;
  const candidate = review.candidates[0]!;
  candidate.first_lineup = names(first);
  candidate.expected_net_points = 49 * window;
  candidate.branches.forEach((branch, stateIndex) => {
    branch.expected_net_points = 49 + (window - 1) * (branch.state === "eligible" ? 52 : 46);
    branch.weeks = branch.weeks.map((week, index) => ({
      ...week,
      transfers_in: [],
      transfers_out: [],
      chip: null,
      bank_tenths: 5,
      free_transfers: Math.min(3 + index, 5),
      lineup: names(roles(index + 1 + stateIndex)),
    }));
  });
  // Two legal captain choices, with identical resources and future continuations.
  // The certain outfield captain adds 4 instead of 3 captain + 2 vice points.
  // Its first-week score is one lower in both synthetic news branches.
  const alternative = structuredClone(candidate);
  alternative.selected = false;
  alternative.baseline = false;
  alternative.first_lineup = {
    ...names(first),
    captain: first.vice_captain.name,
    vice_captain: first.captain.name,
  };
  alternative.expected_net_points = candidate.expected_net_points - 1;
  alternative.branches.forEach((branch) => {
    branch.expected_net_points = branch.expected_net_points! - 1;
  });
  review.candidates.push(alternative);
  review.comparison = {
    version: "completed_policy_comparison_v1",
    basis: "expected_own_points",
    baseline_index: 0,
    scenario_ids: ["eligible", "unavailable"],
    news_arrival_probability: null,
    scope: "supplied_conditional_scenarios_only",
    terminal_resource_value_added: false,
    candidates: review.candidates.map((policy, index) => ({
      index,
      action_kind: "hold",
      first_state: { bank_tenths: 5, free_transfers: 2 },
      scenario_min: Math.min(...policy.branches.map((branch) => branch.expected_net_points!)),
      scenario_max: Math.max(...policy.branches.map((branch) => branch.expected_net_points!)),
      branch_gaps_vs_baseline: { eligible: -index, unavailable: -index },
      minimum_gap_vs_baseline: -index,
      maximum_gap_vs_baseline: -index,
      dominates_baseline: index === 0,
      dominated_by: index === 0 ? [] : [0],
    })),
  };
  answer.payload = {
    ...answer.payload,
    ...first,
    moves: [],
    chip: null,
    transfer_hit_points: 0,
    expected_own_points: 49,
    expected_gain_vs_hold: null,
    optimality_gap: null,
    lineup_expectation: expectation,
    plan_weeks: answer.payload.plan_weeks!.map((week, index) => ({
      ...week,
      transfers_in: [],
      transfers_out: [],
      transfer_hit_points: 0,
      chip: null,
      free_transfers_before: Math.min(1 + index, 5),
      free_transfers_after: Math.min(2 + index, 5),
      expected_points: 49,
      lineup_expectation: expectation,
      lineup: roles(index),
    })),
    prediction_model: {
      id: "football",
      version: "football_joint_role_minutes_v1",
      experimental: true,
      fingerprint: "a".repeat(64),
    },
    role_forecast: {
      version: "football_role_forecast_v1",
      model_version: "football_joint_role_minutes_v1",
      calibration: "not_independently_verified",
      scope: "current_gameweek_fixtures",
      rows: [
        {
          player_id: first.captain.player_id,
          name: first.captain.name,
          fixture_id: 101,
          gameweek: answer.payload.gameweek,
          kickoff: "2026-09-05T14:00:00Z",
          status: "fitted_known_start_labels",
          expected_minutes: 34,
          captured_eligibility_multiplier: 0.5,
          news_applied: false,
          point_components: {
            appearance: 0.9,
            goals: 0,
            assists: 0,
            clean_sheet: 1.2,
            defcon: 0,
            other: 0.9,
            clipping: 0,
            total: 3,
          },
        },
        {
          player_id: first.vice_captain.player_id,
          name: first.vice_captain.name,
          fixture_id: 102,
          gameweek: answer.payload.gameweek,
          kickoff: "2026-09-05T16:30:00Z",
          status: "unavailable_no_known_start_labels",
          expected_minutes: 60,
          captured_eligibility_multiplier: 1,
          news_applied: false,
        },
      ],
    },
    selection_top100_weight: 20,
    information_review: review,
    participation_evidence: {
      version: "football_participation_evidence_v1",
      as_of: review.captured_at_utc,
      gameweek: answer.payload.gameweek,
      applied_player_count: 1,
      unapplied_statement_count: 1,
      captured_percentage_count: 2,
      manager_statement_count: 2,
      assumptions: [
        "source_eligibility_only",
        "no_start_or_minutes_reestimate",
        "no_external_calibration",
      ],
    },
    stated_limits: [
      "Complete plans are compared using expected automatic substitutions and vice-captain recovery. The limited search does not prove the best possible plan or future performance.",
    ],
  };
  delete answer.payload.expected_points_cost;
  // No permission to redistribute central PL injury rows: absent in this release fixture.
  delete answer.payload.official_injuries;
  return answer;
}

for (const [window, width] of [
  [3, 390],
  [3, 320],
  [5, 390],
  [5, 320],
] as const) {
  test(`conditional football plan preserves ${window} weeks and Top100 at ${width}px`, async ({
    page,
  }, info) => {
    test.skip(!process.env.VITE_ADVICE_API_ORIGIN, "API build required");
    await page.setViewportSize({ width, height: 844 });
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await installLeagueMocks(page);
    const squad = mockEntrySquadEnvelopes[35249001]!.payload;
    const answer = expectedAnswer(window);
    expect(isAdvicePayload(answer.payload)).toBe(true);
    const reads: string[] = [];
    const writes: string[] = [];
    await page.route("**/api/v1/**", async (route) => {
      const url = route.request().url();
      const headers = {
        "access-control-allow-origin": new URL(page.url()).origin,
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type, idempotency-key",
      };
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers });
        return;
      }
      if (url.includes("/advice?")) reads.push(url);
      if (route.request().method() === "POST") writes.push(url);
      const body = url.endsWith("/capabilities")
        ? {
            contract_version: "league_capabilities_v1",
            league_id: squad.league_id,
            season: squad.season,
            gameweek: squad.gameweek,
            capture_snapshot_id: squad.source_snapshot_id,
            strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
            models: ["current", "football"],
            top100: { available: true, weights: [0, 20] },
            managers_word: { available: false },
          }
        : answer;
      await route.fulfill({
        status: 200,
        headers,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });
    await page.goto(
      `/league/members/35249001?mode=saf-puan&window=${window}&top100=20&model=football`,
    );
    const region = page.getByTestId("information-review");
    await expect(region).toBeVisible();
    await expect(region).toContainText("kesin gelecek transfer tahmini değildir");
    await expect(region).toContainText("Top100 ağırlığı puan kazancı değildir");
    const selected = region.locator(":scope > details[open]");
    const comparison = selected.getByTestId("policy-comparison");
    const format = (value: number) => value.toFixed(1).replace(".", ",");
    const expectedComparison = answer.payload.information_review!.comparison!.candidates[0]!;
    await expect(region).toContainText("Kaynakta belirtilen oynama ihtimali: 50%");
    await expect(comparison).toContainText(
      `Hesaplanan haber senaryolarındaki puan aralığı: ${format(expectedComparison.scenario_min)} – ${format(expectedComparison.scenario_max)}`,
    );
    await expect(comparison).toContainText("Başlangıç planına göre senaryo farkı: 0,0 – 0,0");
    await expect(comparison).toContainText("maç sonucu için bir güven aralığı değildir");
    await expect(comparison).toContainText("Haberin ne zaman geleceğine olasılık atanmadı");
    await expect(comparison).toContainText("banka ve kalan transfere ek puan yazılmadı");
    await expect(page.getByTestId("official-injuries")).toHaveCount(0);
    const selectedUrl = page.url();
    const breakdown = page.getByTestId("lineup-expectation");
    await expect(breakdown).toContainText("İlk 11: 43,0");
    await expect(breakdown).toContainText("Otomatik değişikliklerden gelen puan: 1,0");
    await expect(breakdown).toContainText("Kaptanın ek puanı: 3,0");
    await expect(breakdown).toContainText("yardımcısının ek puanı: 2,0");
    await expect(breakdown).toContainText("Ceza sonrası beklenen puan: 49,0");
    await breakdown.locator("summary").click();
    await expect(breakdown).toContainText("ikinci kez uygulanmaz");
    const participation = page.getByTestId("participation-evidence");
    await participation.locator(":scope > summary").click();
    await expect(participation).toContainText("Kontrol edilen FPL oynayabilirlik kaydı: 2");
    await expect(participation).toContainText("Değerlendirilen hoca açıklaması: 2");
    await expect(participation).toContainText("Doğrulanmış haberin uygulandığı oyuncu: 1");
    await expect(participation.locator("time")).toHaveAttribute(
      "datetime",
      answer.payload.participation_evidence!.as_of!,
    );
    await expect(participation).toContainText("Uygulanamayan açıklama: 1");
    const role = participation.getByTestId("role-forecast");
    await role.locator(":scope > summary").click();
    await expect(role).toContainText("Beklenen dakika: 34,0");
    await expect(role).toContainText("kesinleşmiş bir ilk 11 değildir");
    await expect(role).not.toContainText("%");
    await expect(role).toContainText("FPL oynayabilirliği bir kez uygulanır");
    await expect(role).toContainText("Bağımsız doğruluk ölçümü henüz tamamlanmış değildir");
    await expect(role).toContainText("İlk 11 bilgisi için yeterli kayıt yok");
    await expect(role).toContainText("Beklenen dakika: 60,0");
    const rolePoints = role.getByTestId("role-point-components");
    await expect(rolePoints).not.toHaveAttribute("open");
    await rolePoints.locator(":scope > summary").focus();
    await page.keyboard.press("Enter");
    await expect(rolePoints).toHaveAttribute("open", "");
    await expect(rolePoints).toContainText("Toplam oyuncu puanı: 3,00");
    await expect(rolePoints).toContainText("kaptan çarpanı ve Top100 seçim ağırlığı öncesidir");
    await expect(rolePoints).toContainText("Oynayabilirlik zaten bir kez uygulanmıştır");
    const nominal = page.getByRole("region", { name: `${window} haftalık pencere`, exact: true });
    const weeks = answer.payload.plan_weeks!;
    for (const [index, week] of weeks.entries()) {
      const detail = nominal.getByTestId(`week-lineup-${week.gameweek}`);
      const summary = detail.locator(":scope > summary");
      if (index === 0) {
        await summary.focus();
        await page.keyboard.press("Enter");
      } else await summary.click();
      await expect(detail).toHaveAttribute("open", "");
      await expect(detail).toContainText(
        week.lineup!.starting_xi.map((player) => player.name).join(", "),
      );
      await expect(detail).toContainText(`Yardımcı kaptan: ${week.lineup!.vice_captain.name}`);
      await expect(detail).toContainText(
        week.lineup!.bench.map((player) => player.name).join(" → "),
      );
    }
    const candidate = answer.payload.information_review!.candidates[0]!;
    for (const branch of candidate.branches) {
      const summary = selected.getByText(
        branch.state === "eligible" ? "Oynayabilir bilgisi gelirse" : "Oynayamaz bilgisi gelirse",
        { exact: true },
      );
      await summary.click();
      const branchRegion = summary.locator("..");
      await expect(branchRegion).toContainText(
        `Pencere beklenen net puanı: ${branch.expected_net_points!.toFixed(1).replace(".", ",")}`,
      );
      for (const week of branch.weeks) {
        const detail = branchRegion.getByTestId(`week-lineup-${week.gameweek}`);
        await detail.locator(":scope > summary").click();
        await expect(detail).toHaveAttribute("open", "");
        await expect(detail).toContainText(week.lineup!.starting_xi.join(", "));
        await expect(detail).toContainText(`Yardımcı kaptan: ${week.lineup!.vice_captain}`);
        await expect(detail).toContainText(week.lineup!.bench.join(" → "));
      }
    }
    await expect(page.getByRole("radio", { name: "20", exact: true })).toBeChecked();
    await expect(page.getByRole("radio", { name: new RegExp(`^${window} `) })).toBeChecked();
    await expect(page).toHaveURL(/top100=20/);
    expect(page.url()).toBe(selectedUrl);
    expect(writes).toEqual([]);
    await expect(selected.locator(":scope > summary")).toContainText("Başlangıç planı");
    await expect(selected).toContainText(`Kaptan: ${answer.payload.captain!.name}`);
    await expect(region.locator(":scope > details").nth(1)).not.toHaveAttribute("open");
    expect(
      reads.some((url) => {
        const query = new URL(url).searchParams;
        return (
          query.get("window") === String(window) &&
          query.get("top100_weight") === "20" &&
          query.get("model") === "football"
        );
      }),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    ).toBe(true);
    const expandedLineups = page.locator('details[data-testid^="week-lineup-"][open]');
    await expect(expandedLineups).toHaveCount(window + 2 * (window - 1));
    expect(
      await expandedLineups.evaluateAll((details) =>
        details.every(
          (detail) =>
            detail.scrollWidth <= detail.clientWidth + 1 &&
            detail.getBoundingClientRect().right <= innerWidth + 1,
        ),
      ),
    ).toBe(true);
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(
      accessibility.violations
        .filter((violation) => ["critical", "serious"].includes(violation.impact ?? ""))
        .map((violation) => ({
          id: violation.id,
          targets: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
        })),
    ).toEqual([]);
    expect(pageErrors).toEqual([]);
    await nominal.screenshot({ path: info.outputPath(`lineups-window${window}-${width}.png`) });
    await region.screenshot({ path: info.outputPath(`information-window${window}-${width}.png`) });
  });
}
