import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { ModelComparison } from "./ModelComparison";
import type { AdviceClient, AdviceRequest } from "./adviceClient";
import { adviceRequestKey } from "./adviceJobStore";

afterEach(cleanup);

it("only computes on click, keeping the same five-week Top100 question under the other model", async () => {
  const request: AdviceRequest = {
    leagueId: 352490,
    entryId: 101,
    strategy: "saf-puan",
    window: 5,
    top100Weight: 20,
    model: "football",
  };
  const readAdvice = vi.fn<AdviceClient["readAdvice"]>(async () => ({
    kind: "not-computed" as const,
  }));
  const requestAdvice = vi.fn<AdviceClient["requestAdvice"]>(async () => ({
    kind: "unavailable" as const,
  }));
  const client: AdviceClient = { readAdvice, requestAdvice, readJob: vi.fn() };
  const renderCard = (chosen: AdviceRequest) => (
    <LanguageProvider initialLanguage="tr">
      <ModelComparison
        request={chosen}
        selected={mockEntryAdviceEnvelope(101, "saf-puan", 5)}
        client={client}
      />
    </LanguageProvider>
  );
  const view = render(renderCard(request));
  await waitFor(() => expect(readAdvice).toHaveBeenCalled());
  expect(requestAdvice).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Diğer modeli de hesapla" }));
  await waitFor(() => expect(requestAdvice).toHaveBeenCalled());
  expect(requestAdvice.mock.calls[0]![0]).toEqual({ ...request, model: "current" });
  expect(adviceRequestKey(request)).not.toBe(adviceRequestKey({ ...request, model: "current" }));
  view.rerender(renderCard({ ...request, window: 3 }));
  await waitFor(() =>
    expect(readAdvice.mock.calls.at(-1)?.[0]).toMatchObject({
      window: 3,
      model: "current",
      top100Weight: 20,
    }),
  );
  expect(requestAdvice).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/yüksek sayı daha başarılı model demek değildir/)).toBeVisible();
  // The Top 100 setting is named as the weight it is, never as a share.
  expect(screen.getByText(/Top 100 ağırlığı 20/)).toBeInTheDocument();
  expect(view.container.textContent).not.toContain("%");
});

it("does not compare an old baseline or submit after the deadline", async () => {
  const request: AdviceRequest = {
    leagueId: 352490,
    entryId: 101,
    strategy: "saf-puan",
    window: 5,
    top100Weight: 20,
  };
  const baseline = mockEntryAdviceEnvelope(101, "saf-puan", 1);
  baseline.payload.expected_own_points = 777.77;
  const client: AdviceClient = {
    readAdvice: vi.fn(async () => ({ kind: "not-computed" as const })),
    requestAdvice: vi.fn(),
    readJob: vi.fn(),
  };
  render(
    <LanguageProvider initialLanguage="tr">
      <ModelComparison request={request} selected={baseline} client={client} deadlinePassed />
    </LanguageProvider>,
  );
  expect(screen.queryByText("777.77")).not.toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Diğer modeli de hesapla" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(client.requestAdvice).not.toHaveBeenCalled();
  await waitFor(() => expect(client.readAdvice).toHaveBeenCalled());
});
