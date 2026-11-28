/** Measured device admission, separate from the published input contract.
 *
 * The real 674-player pool exceeds the unchanged 60-second horizon ceiling
 * at both H3 and H5 in nominal CDP4 Chromium. Keep these windows on the
 * service until a complete measurement admits them. The numeric solver and
 * published windows remain available for reference checks.
 * Evidence: benchmark/evidence/real-pool-20261128.json.
 */
import { deviceHorizonWindows, type DevicePlanEntry } from "./types";

const admittedWindows: readonly (3 | 5)[] = [];

export function admittedHorizonWindows(entry: DevicePlanEntry): Array<3 | 5> {
  return deviceHorizonWindows(entry).filter((window) => admittedWindows.includes(window));
}
