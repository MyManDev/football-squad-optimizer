/**
 * The players of the page's background scene, drawn from joint angles rather than stored as
 * outlines, so a pose is a line of numbers and every player keeps the same proportions.
 *
 * An angle of 0 points straight down and a positive angle turns toward the way the player
 * faces, so 90 is forward, -90 is back and 180 is up. A figure is built around its hip, at
 * the origin. Each limb is a chain of tapered capsules whose subpaths all wind the same way,
 * so a nonzero fill draws their overlaps as one shape.
 */

export type Point = readonly [number, number];

/** [upper arm, forearm] */
type Arm = readonly [number, number];
/** [thigh, calf, foot] */
type Leg = readonly [number, number, number];

export type Pose = {
  /** How far the body leans: forward is positive. */
  readonly torso: number;
  readonly head: number;
  readonly arm: Arm;
  readonly armFar: Arm;
  readonly leg: Leg;
  readonly legFar: Leg;
  /** A goalkeeper's hands are gloves. */
  readonly gloves?: boolean;
};

export type FigurePaths = {
  /** The body and the limbs nearer the viewer. */
  readonly near: string;
  /** The limbs on the far side. */
  readonly far: string;
  /** The waist and the tops of the socks, cut across the body in the page's colour. */
  readonly seams: string;
  /** The near foot's toe and the near hand, where a ball can meet the player. */
  readonly toe: Point;
  readonly hand: Point;
};

export const POSES = {
  sprint: {
    torso: 20,
    head: 10,
    arm: [-58, 28],
    armFar: [46, 138],
    leg: [58, -8, 72],
    legFar: [-38, -104, -34],
  },
  strike: {
    torso: -20,
    head: -2,
    arm: [-74, -30],
    armFar: [66, 108],
    leg: [84, 72, 132],
    legFar: [8, -8, 80],
  },
  tackle: {
    torso: -64,
    head: 6,
    arm: [-24, -34],
    armFar: [104, 122],
    leg: [86, 90, 150],
    legFar: [58, -62, 22],
  },
  overhead: {
    torso: -118,
    head: -96,
    arm: [-30, -10],
    armFar: [-158, -120],
    leg: [166, 172, -112],
    legFar: [66, 16, 92],
  },
  dive: {
    gloves: true,
    torso: 72,
    head: 66,
    arm: [104, 98],
    armFar: [122, 114],
    leg: [-76, -86, -28],
    legFar: [-52, -112, -52],
  },
  header: {
    torso: -14,
    head: 24,
    arm: [-72, -38],
    armFar: [62, 104],
    leg: [18, -74, -14],
    legFar: [-14, -52, 12],
  },
  cheer: {
    torso: -6,
    head: -10,
    arm: [150, 168],
    armFar: [-150, -168],
    leg: [24, -22, 62],
    legFar: [-20, -48, 30],
  },
} as const satisfies Record<string, Pose>;

const LENGTH = { torso: 88, neck: 10, upper: 44, fore: 42, thigh: 68, calf: 66, foot: 27 };

const round = (value: number) => Math.round(value * 10) / 10;

function step(from: Point, angle: number, length: number): Point {
  const radians = (angle * Math.PI) / 180;
  return [from[0] + length * Math.sin(radians), from[1] + length * Math.cos(radians)];
}

const between = (a: Point, b: Point, share: number): Point => [
  a[0] + (b[0] - a[0]) * share,
  a[1] + (b[1] - a[1]) * share,
];

function circle(centre: Point, radius: number): string {
  const r = round(radius);
  const across = round(2 * radius);
  return `M${round(centre[0] - radius)} ${round(centre[1])}a${r} ${r} 0 1 1 ${across} 0a${r} ${r} 0 1 1 ${-across} 0Z`;
}

/** Two circles and the outer tangents between them. */
function capsule(a: Point, radiusA: number, b: Point, radiusB: number): string {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const distance = Math.hypot(dx, dy);
  if (distance <= Math.abs(radiusA - radiusB))
    return radiusA > radiusB ? circle(a, radiusA) : circle(b, radiusB);
  const base = Math.atan2(dy, dx);
  const spread = Math.acos((radiusA - radiusB) / distance);
  const on = (centre: Point, radius: number, angle: number) =>
    `${round(centre[0] + radius * Math.cos(angle))} ${round(centre[1] + radius * Math.sin(angle))}`;
  const startA = on(a, radiusA, base - spread);
  return (
    `M${startA}L${on(b, radiusB, base - spread)}` +
    `A${round(radiusB)} ${round(radiusB)} 0 0 1 ${on(b, radiusB, base + spread)}` +
    `L${on(a, radiusA, base + spread)}` +
    `A${round(radiusA)} ${round(radiusA)} 0 ${radiusA > radiusB ? 1 : 0} 1 ${startA}Z`
  );
}

/** A thin bar across a limb, as wide as the limb is there. */
function seam(a: Point, b: Point, share: number, halfWidth: number): string {
  const centre = between(a, b, share);
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const across: Point = [(a[1] - b[1]) / length, (b[0] - a[0]) / length];
  return capsule(
    [centre[0] + across[0] * halfWidth, centre[1] + across[1] * halfWidth],
    1.5,
    [centre[0] - across[0] * halfWidth, centre[1] - across[1] * halfWidth],
    1.5,
  );
}

function legPaths(hip: Point, [thigh, calf, foot]: Leg) {
  const knee = step(hip, thigh, LENGTH.thigh);
  const ankle = step(knee, calf, LENGTH.calf);
  const toe = step(ankle, foot, LENGTH.foot);
  const muscle = between(knee, ankle, 0.32);
  return {
    toe,
    body:
      capsule(hip, 20, knee, 12) +
      capsule(knee, 12, muscle, 13.5) +
      capsule(muscle, 13.5, ankle, 7) +
      capsule(ankle, 8, toe, 5.5),
    seam: seam(knee, ankle, 0.16, 15),
  };
}

function armPaths(shoulder: Point, [upper, fore]: Arm, gloves: boolean) {
  const elbow = step(shoulder, upper, LENGTH.upper);
  const wrist = step(elbow, fore, LENGTH.fore);
  const hand = step(wrist, fore, gloves ? 10 : 7);
  return {
    hand,
    body:
      capsule(shoulder, 12.5, elbow, 9) +
      capsule(elbow, 9, wrist, 6.5) +
      circle(hand, gloves ? 10.5 : 7),
  };
}

export function figurePaths(pose: Pose): FigurePaths {
  const hip: Point = [0, 0];
  const up = 180 - pose.torso;
  const headUp = 180 - pose.head;
  const waist = step(hip, up, LENGTH.torso * 0.34);
  const chest = step(hip, up, LENGTH.torso * 0.74);
  const shoulder = step(hip, up, LENGTH.torso * 0.86);
  const neck = step(hip, up, LENGTH.torso);
  const head = step(neck, headUp, LENGTH.neck + 13);
  const gloves = pose.gloves ?? false;
  const leg = legPaths(hip, pose.leg);
  const legFar = legPaths(hip, pose.legFar);
  const arm = armPaths(shoulder, pose.arm, gloves);
  const armFar = armPaths(shoulder, pose.armFar, gloves);
  return {
    near:
      capsule(hip, 19, waist, 17) +
      capsule(waist, 17, chest, 23) +
      capsule(chest, 23, neck, 11) +
      capsule(neck, 8, step(neck, headUp, LENGTH.neck), 8) +
      circle(head, 14.5) +
      leg.body +
      arm.body,
    far: legFar.body + armFar.body,
    seams: seam(hip, waist, 0.3, 21) + leg.seam + legFar.seam,
    toe: leg.toe,
    hand: arm.hand,
  };
}
