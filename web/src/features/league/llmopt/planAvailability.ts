import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type { AdviceClient } from "../advice/adviceClient";
import type { PlanContext } from "./planHistory";

/** Read the current data identity once for this message or selection. */
export async function readPlanAvailability(
  kind: PlanContext["kind"] | undefined,
  currentGrant: () => Promise<AdviceCapabilities | null | undefined>,
  readDeviceDataId: AdviceClient["readDeviceDataId"],
) {
  const capabilities = await currentGrant().catch(() => undefined);
  const grant = capabilities?.llmoptVNext === true ? capabilities : undefined;
  let dataId: string | undefined;
  if (grant && kind === "device") dataId = await readDeviceDataId?.().catch(() => undefined);
  else if (grant && kind === "server") dataId = grant.planDataId;
  return {
    grant,
    matches: (source: PlanContext["kind"], id: string) =>
      source === kind && dataId !== undefined && dataId === id,
  };
}
