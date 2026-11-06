import { useEffect, useState } from "react";

import { useLanguage } from "../../../i18n/context";
import styles from "./LeagueMemberPage.module.css";

type SectionKey = "move" | "squad";

const KEYS: readonly SectionKey[] = ["move", "squad"];

/**
 * Where each link lands: the decision's heading (the plan settings' 'Planı gör' lands there
 * too) and the squad the sidebar's 'Kadro' opens. The tools are pages of their own in the
 * sidebar.
 */
const TARGETS: Record<SectionKey, string> = {
  move: "entry-advice-title",
  squad: "kadro",
};

/** The height of the shell's phone bar (PageShell.module.css) and of the strip, in px. */
const PHONE_BAR = 56;
const STRIP = 40;

/**
 * A section is the current one once its top has gone up past this line, a little under the
 * strip: a link lands its section at the strip's lower edge, above the line.
 */
const READING_LINE = PHONE_BAR + STRIP + 16;

/** Far enough below any page that a band reaching it has no end on this page. */
const BEYOND = 100_000;

/**
 * The phone's section strip, 'Hamle · Kadro', pinned under the phone bar as
 * FotMob and Sofascore pin a long page's sections under a slim header: one tap lands each
 * part of the page under both bars, and the part being read is marked as the current
 * location. LeagueMemberView draws it on a phone only, right under the top bar.
 *
 * It takes no room in the page: the decision leads the first screen, and after 'Planı gör'
 * the boards and the captain line still fit it (member-pitch.spec.ts), which a strip 40 px
 * tall in the flow would not leave room for. So it is drawn only once the decision's heading
 * has gone up behind the phone bar, and it stands aside again whenever the heading comes
 * back into view, as it does after its own 'Hamle'.
 *
 * Every reading is an IntersectionObserver's, made as a line is crossed; nothing reads the
 * layout while the page scrolls. A section is linked once its observer has reported it, so
 * a section the page does not draw has no link, and where the browser has no observer
 * (jsdom) the strip has no links and stays away.
 */
export function MemberSections() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const [found, setFound] = useState<readonly SectionKey[]>([]);
  const [shown, setShown] = useState(false);
  const [current, setCurrent] = useState<SectionKey>("move");

  // The page draws its sections around the strip, each as one element for as long as the
  // strip is drawn (a new member or week draws the page and the strip anew), so they are
  // looked up once, after the page is in the document.
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return undefined;
    const elements = KEYS.map((key) => document.getElementById(TARGETS[key]));
    const [move, squad] = elements;
    // One array for the strip's lifetime, so a report that finds nothing new renders nothing.
    const present = KEYS.filter((_, index) => elements[index] !== null);
    const observers: IntersectionObserver[] = [];

    // The decision's heading has gone up behind the phone bar once it no longer meets the
    // band from the bar's lower edge down, and lies above it.
    if (move) {
      const passed = new IntersectionObserver(
        (entries) => {
          const entry = entries[entries.length - 1]!;
          const edge = entry.rootBounds?.top ?? PHONE_BAR;
          setFound(present);
          setShown(!entry.isIntersecting && entry.boundingClientRect.top < edge);
        },
        { rootMargin: `-${PHONE_BAR}px 0px ${BEYOND}px 0px` },
      );
      passed.observe(move);
      observers.push(passed);
    }

    // Whether the squad's top is above the reading line, from a band that starts at the line
    // and has no lower end: the squad is wholly inside it until its top goes up past the
    // line, so even a jump over the whole screen changes what the band holds and is reported.
    if (squad) {
      const reached = new IntersectionObserver(
        (entries) => {
          const entry = entries[entries.length - 1]!;
          const line = entry.rootBounds?.top ?? READING_LINE;
          setFound(present);
          setCurrent(entry.boundingClientRect.top < line ? "squad" : "move");
        },
        { rootMargin: `-${READING_LINE}px 0px ${BEYOND}px 0px`, threshold: [0, 1] },
      );
      reached.observe(squad);
      observers.push(reached);
    }
    return () => observers.forEach((observer) => observer.disconnect());
  }, []);

  const names: Record<SectionKey, string> = {
    move: copy.sectionMove,
    squad: copy.sectionSquad,
  };
  // The holder stays when nothing is linked: the page's scroll padding counts the strip.
  return (
    <div className={styles.sections} data-shown={shown || undefined}>
      {found.length > 0 ? (
        <nav className={styles.sectionsBar} aria-label={copy.sectionsLabel}>
          {found.map((key) => (
            <a
              key={key}
              href={`#${TARGETS[key]}`}
              className={styles.sectionLink}
              aria-current={current === key ? "location" : undefined}
            >
              <span className={styles.sectionName}>{names[key]}</span>
            </a>
          ))}
        </nav>
      ) : null}
    </div>
  );
}
