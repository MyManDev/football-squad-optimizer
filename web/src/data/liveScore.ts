import { ContractMismatchError, type Loaded, type ViewEnvelope } from "./client";

export interface LiveScoreView {
  season: string;
  gameweek: number;
  decision_snapshot_id: string;
  prediction_fingerprint: string;
  status: "available" | "unavailable";
  reason: string | null;
  source_snapshot_id: string | null;
  captured_at_utc: string | null;
  named_score: number | null;
  transfer_hit_points: number | null;
  net_score: number | null;
  fixtures_finished: number | null;
  fixtures_total: number | null;
  bonus_confirmed: boolean | null;
}

export function readLiveScore(
  raw: unknown,
  season: string,
  gameweek: number,
): Loaded<LiveScoreView> {
  const envelope = raw as ViewEnvelope<LiveScoreView> | null;
  if (envelope?.contract_version !== "live_score_v1") {
    throw new ContractMismatchError(String(envelope?.contract_version), "live_score_v1");
  }
  const p = envelope.payload;
  const validTime = (value: unknown): value is string =>
    typeof value === "string" && /(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
  const finite = (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value);
  if (
    !p ||
    p.season !== season ||
    p.gameweek !== gameweek ||
    !validTime(envelope.generated_at_utc) ||
    typeof p.decision_snapshot_id !== "string" ||
    typeof p.prediction_fingerprint !== "string" ||
    (p.captured_at_utc !== null &&
      (!validTime(p.captured_at_utc) ||
        Date.parse(p.captured_at_utc) > Date.parse(envelope.generated_at_utc))) ||
    (p.source_snapshot_id !== null && typeof p.source_snapshot_id !== "string") ||
    (p.status !== "available" && p.status !== "unavailable")
  )
    throw new Error("Invalid live score identity.");
  const scores = [p.named_score, p.net_score, p.transfer_hit_points];
  if (p.status === "available") {
    if (
      !scores.every(finite) ||
      !p.source_snapshot_id ||
      !validTime(p.captured_at_utc) ||
      p.reason !== null ||
      typeof p.bonus_confirmed !== "boolean" ||
      !Number.isInteger(p.fixtures_finished) ||
      !Number.isInteger(p.fixtures_total) ||
      p.fixtures_total! < 1 ||
      p.fixtures_finished! < 0 ||
      p.fixtures_finished! > p.fixtures_total! ||
      (p.bonus_confirmed && p.fixtures_finished !== p.fixtures_total) ||
      p.transfer_hit_points! < 0 ||
      p.net_score !== p.named_score! - p.transfer_hit_points!
    )
      throw new Error("Invalid live score values.");
  } else if (
    typeof p.reason !== "string" ||
    !scores.every((v) => v === null) ||
    p.fixtures_finished !== null ||
    p.fixtures_total !== null ||
    p.bonus_confirmed !== null
  )
    throw new Error("Unavailable live score carries values.");
  return { payload: p, generatedAtUtc: envelope.generated_at_utc };
}
