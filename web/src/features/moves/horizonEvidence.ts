export const HORIZON_EVIDENCE_CONTRACT_VERSION = "public_horizon_evidence_v1";

export interface HorizonEvidenceRow {
  horizon: number;
  decision_role: "live_control" | "research_shadow";
  solver_status: string;
  solver_proof_status: string;
  publication_status: "decision_eligible" | "shadow_only";
}

export interface HorizonEvidence {
  contract_version: typeof HORIZON_EVIDENCE_CONTRACT_VERSION;
  ledger_control_verified: true;
  horizons: HorizonEvidenceRow[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function readHorizonEvidence(value: unknown): HorizonEvidence | null {
  if (!isRecord(value)) return null;
  if (value.contract_version !== HORIZON_EVIDENCE_CONTRACT_VERSION) return null;
  if (value.ledger_control_verified !== true || !Array.isArray(value.horizons)) return null;
  const rows: HorizonEvidenceRow[] = [];
  const seen = new Set<number>();
  for (const item of value.horizons) {
    if (!isRecord(item)) return null;
    const horizon = Number(item.horizon);
    if (![1, 3, 5].includes(horizon) || seen.has(horizon)) return null;
    seen.add(horizon);
    if (!["live_control", "research_shadow"].includes(String(item.decision_role))) return null;
    if (!["decision_eligible", "shadow_only"].includes(String(item.publication_status)))
      return null;
    if (typeof item.solver_status !== "string" || typeof item.solver_proof_status !== "string") {
      return null;
    }
    const expectedRole = horizon === 1 ? "live_control" : "research_shadow";
    const expectedPublication = horizon === 1 ? "decision_eligible" : "shadow_only";
    if (item.decision_role !== expectedRole || item.publication_status !== expectedPublication) {
      return null;
    }
    if (
      horizon === 1 &&
      (item.solver_status !== "OPTIMAL" || item.solver_proof_status !== "proven")
    ) {
      return null;
    }
    rows.push(item as unknown as HorizonEvidenceRow);
  }
  return value as unknown as HorizonEvidence;
}
