/** A plain plan has no price; incomplete proofs need a published ceiling. */
export function publishedPrice(plan: {
  strategy: string;
  word: boolean;
  top100: boolean;
  expected_points_cost?: number;
  expected_points_cost_ceiling?: number;
  unproven?: boolean;
}): number | undefined {
  const price = plan.unproven
    ? plan.expected_points_cost_ceiling
    : (plan.expected_points_cost_ceiling ?? plan.expected_points_cost);
  return (plan.strategy !== "saf-puan" || plan.word || plan.top100) &&
    typeof price === "number" &&
    Number.isFinite(price) &&
    price >= 0
    ? price
    : undefined;
}
