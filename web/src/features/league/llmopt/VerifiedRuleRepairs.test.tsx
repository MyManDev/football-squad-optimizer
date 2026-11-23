import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { AdviceClient } from "../advice/adviceClient";
import { LLMOPT_COPY } from "./copy";
import { VerifiedRuleRepairs } from "./VerifiedRuleRepairs";

afterEach(cleanup);

it("recovers a failed first candidate without changing its run or offering an unverified edit", async () => {
  const copy = LLMOPT_COPY.en.repairs;
  const owner = { runId: "a".repeat(32), dataId: "b".repeat(64), failedBase: true };
  const begin = vi.fn().mockResolvedValue(owner);
  const client: AdviceClient = {
    requestAdvice: vi
      .fn()
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue({ kind: "unavailable", reason: "PLAN_NOT_FOUND" }),
    readJob: vi.fn(),
    readAdvice: vi.fn(),
    readPublished: vi.fn(),
  };
  const apply = vi.fn();
  render(
    <LanguageProvider initialLanguage="en">
      <VerifiedRuleRepairs
        analysis={{
          status: "conflict",
          sentence: copy.conflict,
          choices: [
            {
              label: "Remove the club count",
              draft: { hard: [{ kind: "no_hits" }], soft: [], window: 3 },
            },
          ],
        }}
        client={client}
        squad={mockEntrySquadEnvelopes[35249001]!.payload}
        window={3}
        disabled={false}
        begin={begin}
        current={async () => true}
        apply={apply}
      />
    </LanguageProvider>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: copy.check }));
  expect(await screen.findByText(copy.unconfirmed)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Remove the club count" })).toBeNull();
  expect(client.requestAdvice).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: copy.check }));
  await waitFor(() => expect(screen.queryByRole("button", { name: copy.check })).toBeNull());
  expect(screen.getByText(copy.conflict)).toBeVisible();
  const requests = vi.mocked(client.requestAdvice).mock.calls.map(([request]) => request);
  expect(requests).toHaveLength(2);
  expect(requests[0]?.run).toMatchObject({ run_id: owner.runId, stage: "repair" });
  expect(requests[1]).toEqual(requests[0]);
  expect(apply).not.toHaveBeenCalled();
});
