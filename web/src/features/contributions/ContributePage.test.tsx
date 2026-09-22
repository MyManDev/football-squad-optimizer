import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { ContributePage } from "./ContributePage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount() {
  render(
    <LanguageProvider initialLanguage="tr">
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <ContributePage />
      </QueryClientProvider>
    </LanguageProvider>,
  );
}
function serve(status = 202) {
  const mock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith("/players"))
      return Response.json({
        season: "2026-27",
        captured_at_utc: "2026-09-22T12:00:00Z",
        teams: [
          { id: 10, name: "Arsenal" },
          { id: 20, name: "Chelsea" },
        ],
        players: [
          { id: 1, name: "Test Player", team_id: 10, team: "Arsenal", position: "GK" },
          { id: 2, name: "Other Player", team_id: 10, team: "Arsenal", position: "GK" },
          { id: 3, name: "Defender", team_id: 10, team: "Arsenal", position: "DEF" },
          { id: 4, name: "Midfielder", team_id: 20, team: "Chelsea", position: "MID" },
        ],
      });
    if (options?.method === "POST") return Response.json({ id: 42, status: "pending" }, { status });
    return Response.json({
      comments: [
        {
          id: 1,
          author: "Reader",
          body: "<img src=x onerror=alert(1)>",
          source: "javascript:alert(1)",
          created: 1700000000,
        },
      ],
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
it("requires consent, preserves untrusted text as text and reports pending rather than public", async () => {
  const mock = serve();
  const user = userEvent.setup();
  mount();
  await user.selectOptions(await screen.findByLabelText("Takım"), "10");
  await user.selectOptions(screen.getByLabelText("Pozisyon"), "GK");
  await user.selectOptions(await screen.findByLabelText("Oyuncu"), "1");
  expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
  expect(screen.queryByText("Paylaşılan kaynak")).toBeNull();
  await user.type(screen.getByLabelText(/Görünen ad/), "Scout");
  await user.type(screen.getByLabelText("Oyuncu hakkında yorum"), "Dakikaları ve rolü değişti.");
  expect(screen.getByRole("button", { name: "Onaya gönder" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Onaya gönder" }));
  expect(await screen.findByText(/Yorumun kaydedildi/)).toHaveTextContent(
    "Henüz herkese açık değil",
  );
  const posts = mock.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(JSON.parse(posts[0]![1]!.body as string)).toMatchObject({
    season: "2026-27",
    player_id: 1,
    consent: true,
  });
});
it("preserves a failed submission and resets it when changing players", async () => {
  serve(503);
  const user = userEvent.setup();
  mount();
  await user.selectOptions(await screen.findByLabelText("Takım"), "10");
  await user.selectOptions(screen.getByLabelText("Pozisyon"), "GK");
  await user.selectOptions(await screen.findByLabelText("Oyuncu"), "1");
  await user.type(screen.getByLabelText(/Görünen ad/), "Scout");
  await user.type(screen.getByLabelText("Oyuncu hakkında yorum"), "Dakikaları ve rolü değişti.");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Onaya gönder" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Gönderim doğrulanamadı");
  expect(screen.getByLabelText("Oyuncu hakkında yorum")).toHaveValue("Dakikaları ve rolü değişti.");
  await user.selectOptions(screen.getByLabelText("Oyuncu"), "2");
  expect(screen.getByLabelText("Oyuncu hakkında yorum")).toHaveValue("");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("filters the complete roster in order and clears drafts when upstream filters change", async () => {
  serve();
  const user = userEvent.setup();
  mount();
  const team = await screen.findByLabelText("Takım");
  expect(screen.getByLabelText("Pozisyon")).toBeDisabled();
  expect(screen.getByLabelText("Oyuncu")).toBeDisabled();
  await user.selectOptions(team, "10");
  expect(screen.getByLabelText("Oyuncu")).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Pozisyon"), "GK");
  expect(screen.queryByRole("option", { name: /Defender|Midfielder/ })).toBeNull();
  await user.selectOptions(screen.getByLabelText("Oyuncu"), "1");
  await user.type(
    screen.getByLabelText("Oyuncu hakkında yorum"),
    "This belongs to the goalkeeper.",
  );
  await user.click(screen.getByRole("checkbox"));
  await user.selectOptions(screen.getByLabelText("Pozisyon"), "DEF");
  expect(screen.getByLabelText("Oyuncu")).toHaveValue("");
  expect(screen.queryByRole("option", { name: /Test Player/ })).toBeNull();
  await user.selectOptions(screen.getByLabelText("Oyuncu"), "3");
  expect(screen.getByLabelText("Oyuncu hakkında yorum")).toHaveValue("");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await user.selectOptions(team, "20");
  expect(screen.getByLabelText("Pozisyon")).toHaveValue("");
  expect(screen.getByLabelText("Oyuncu")).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Pozisyon"), "MID");
  await user.selectOptions(screen.getByLabelText("Oyuncu"), "4");
  expect(screen.queryByRole("option", { name: /Defender/ })).toBeNull();
});
