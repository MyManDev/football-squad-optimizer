/** Measured device admission, separate from the published input contract.
 *
 * The reduced real 674-player pool fails the unchanged 60-second ceiling
 * for FT0/H3, FT0/H5 and FT1/H3 across five members and three nominal CDP4
 * repeats. Other groups remain unmeasured. Keep all horizon groups on the
 * service until a complete measurement admits them. The numeric solver and
 * published windows remain available for reference checks.
 * Evidence: benchmark/evidence/pool-reduction-20261128.json.
 */
import { deviceHorizonWindows, type DevicePlanEntry } from "./types";

const admittedWindows: readonly (3 | 5)[] = [];

export function admittedHorizonWindows(entry: DevicePlanEntry): Array<3 | 5> {
  return deviceHorizonWindows(entry).filter((window) => admittedWindows.includes(window));
}
