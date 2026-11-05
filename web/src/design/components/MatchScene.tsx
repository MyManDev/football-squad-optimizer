import { figurePaths, POSES, type Point } from "../scene/matchFigures";
import styles from "./MatchScene.module.css";

type Player = {
  readonly pose: keyof typeof POSES;
  /** Where the hip stands in the scene. */
  readonly at: Point;
  readonly scale: number;
  /** Faces left rather than right. */
  readonly mirrored?: boolean;
  /** The height of the shadow under a player with a foot on the ground. */
  readonly ground?: number;
  /** Copies drawn behind the player, for speed. */
  readonly echoes?: number;
};

/** A player on the ball: it meets their `touch`, coming round `via` from the last touch. */
type Touch = Player & {
  readonly touch: "toe" | "hand";
  readonly via?: Point;
};

type Scene = {
  readonly width: number;
  readonly height: number;
  /** The move, in the order the ball plays it. */
  readonly move: readonly Touch[];
  /** Players further off, away from the ball, in the far colour only. */
  readonly distant: readonly Player[];
};

/** One move across the page: a tackle, a run, a cross, an overhead kick, the keeper's dive. */
const WIDE: Scene = {
  width: 1600,
  height: 1000,
  move: [
    { pose: "tackle", at: [500, 800], scale: 1.5, ground: 930, touch: "toe" },
    {
      pose: "sprint",
      at: [800, 560],
      scale: 1,
      ground: 712,
      echoes: 2,
      touch: "toe",
      via: [780, 730],
    },
    { pose: "strike", at: [1060, 740], scale: 1.65, ground: 960, touch: "toe", via: [1040, 960] },
    {
      pose: "overhead",
      at: [1180, 380],
      scale: 1.4,
      mirrored: true,
      touch: "toe",
      via: [1290, 480],
    },
    { pose: "dive", at: [1500, 200], scale: 1.15, mirrored: true, touch: "hand", via: [1110, 60] },
  ],
  distant: [
    { pose: "header", at: [900, 250], scale: 0.62 },
    { pose: "header", at: [985, 262], scale: 0.62, mirrored: true },
    { pose: "cheer", at: [640, 310], scale: 0.55 },
    { pose: "sprint", at: [1420, 700], scale: 0.62, mirrored: true },
  ],
};

/** The same move up a phone's page, without the run. */
const TALL: Scene = {
  width: 600,
  height: 1200,
  move: [
    { pose: "tackle", at: [170, 1050], scale: 1, ground: 1135, touch: "toe" },
    { pose: "strike", at: [330, 760], scale: 1.1, ground: 905, touch: "toe", via: [240, 960] },
    { pose: "overhead", at: [240, 400], scale: 1, mirrored: true, touch: "toe", via: [560, 520] },
    { pose: "dive", at: [520, 130], scale: 0.85, mirrored: true, touch: "hand", via: [200, 80] },
  ],
  distant: [{ pose: "header", at: [90, 620], scale: 0.5 }],
};

const round = (value: number) => Math.round(value * 10) / 10;

/** The ball's way through the scene: an arc to each player's touch in turn. */
function ballPath({ move }: Scene): string {
  return move
    .map((player) => {
      const local = figurePaths(POSES[player.pose])[player.touch];
      const x = round(player.at[0] + local[0] * player.scale * (player.mirrored ? -1 : 1));
      const y = round(player.at[1] + local[1] * player.scale);
      return player.via ? `Q${player.via[0]} ${player.via[1]} ${x} ${y}` : `M${x} ${y}`;
    })
    .join("");
}

function ScenePlayer({ player, distant = false }: { player: Player; distant?: boolean }) {
  const paths = figurePaths(POSES[player.pose]);
  const { at, scale, ground } = player;
  const flip = player.mirrored ? -1 : 1;
  const echoes = Array.from({ length: player.echoes ?? 0 }, (_, index) => index + 1).reverse();
  const place = (x: number) => `translate(${x} ${at[1]}) scale(${flip * scale} ${scale})`;
  if (distant)
    return <path className={styles.far} d={paths.near + paths.far} transform={place(at[0])} />;
  return (
    <>
      {ground === undefined ? null : (
        <ellipse className={styles.far} cx={at[0]} cy={ground} rx={95 * scale} ry={7 * scale} />
      )}
      {echoes.map((echo) => (
        <path
          key={echo}
          className={styles.echo}
          d={paths.near}
          transform={place(at[0] - echo * 34 * flip * scale)}
        />
      ))}
      <g transform={place(at[0])}>
        <path className={styles.far} d={paths.far} />
        <path className={styles.near} d={paths.near} />
        <path className={styles.seam} d={paths.seams} />
      </g>
    </>
  );
}

/**
 * The page's background: one passing move played across the bare page, in two colours close
 * to the page's own (tokens.css), so every text colour that sits on the page still reads over
 * a player. It stays where it is while the page scrolls over it. The ball runs the move once
 * each time a page arrives (`arrival` changes) and rests in the keeper's gloves. A page
 * that is one question opts out with `data-no-match-scene` (MatchScene.module.css).
 */
export function MatchScene({ tall, arrival }: { tall: boolean; arrival: string }) {
  const scene = tall ? TALL : WIDE;
  const path = ballPath(scene);
  return (
    <div className={styles.scene} aria-hidden="true" data-match-scene="">
      <svg
        className={styles.picture}
        viewBox={`0 0 ${scene.width} ${scene.height}`}
        preserveAspectRatio="xMaxYMid slice"
        focusable="false"
      >
        {scene.distant.map((player) => (
          <ScenePlayer key={player.at.join()} player={player} distant />
        ))}
        <path className={styles.flight} d={path} />
        {scene.move.map((player) => (
          <ScenePlayer key={player.pose} player={player} />
        ))}
        <g key={arrival} className={styles.ball} style={{ offsetPath: `path("${path}")` }}>
          <circle className={styles.near} r={15} />
          <path
            className={styles.ballPanels}
            d="M0-6 5.7-1.9 3.5 4.9H-3.5L-5.7-1.9ZM0-14V-7M13.3-4.3 6.7-2.2M8.2 11.3 4.1 5.7M-8.2 11.3-4.1 5.7M-13.3-4.3-6.7-2.2"
          />
        </g>
      </svg>
    </div>
  );
}
