import { describe, expect, it } from "vitest";

import { readHorizonEvidence } from "./horizonEvidence";

describe("readHorizonEvidence", () => {
  it("accepts the sanitized public contract", () => {
    expect(
      readHorizonEvidence({
        contract_version: "public_horizon_evidence_v1",
        ledger_control_verified: true,
        horizons: [
          {
            horizon: 3,
            decision_role: "research_shadow",
            solver_status: "FEASIBLE",
            solver_proof_status: "unproven",
            publication_status: "shadow_only",
          },
        ],
      }),
    ).not.toBeNull();
  });

  it("refuses unknown or malformed evidence", () => {
    expect(readHorizonEvidence({ contract_version: "other" })).toBeNull();
    expect(
      readHorizonEvidence({
        contract_version: "public_horizon_evidence_v1",
        ledger_control_verified: true,
        horizons: [{ horizon: 7 }],
      }),
    ).toBeNull();
    expect(
      readHorizonEvidence({
        contract_version: "public_horizon_evidence_v1",
        ledger_control_verified: true,
        horizons: [
          {
            horizon: 3,
            decision_role: "live_control",
            solver_status: "OPTIMAL",
            solver_proof_status: "proven",
            publication_status: "decision_eligible",
          },
        ],
      }),
    ).toBeNull();
  });
});
