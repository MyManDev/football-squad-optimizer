import { useLanguage } from "../../../i18n/context";
import { DisclosureIcon, ExternalIcon } from "./memberIcons";
import styles from "./FplIdHelp.module.css";

/** The game's own site, where the number is read from the address bar. */
const FPL_SITE = "https://fantasy.premierleague.com/";

/**
 * The address the league ID is read from, as the browser shows it on the FPL site: the host,
 * the path before the number, the number, and the rest. The number is an example, not a
 * league this site publishes, so one typed in by mistake is refused instead of opening
 * somebody else's league.
 */
const ADDRESS = ["fantasy.premierleague.com/", "leagues/", "123456", "/standings/c"] as const;

/**
 * "FPL ID'm nerede?": where the league ID the entry field asks for is found on the FPL site,
 * folded under that field until the visitor asks.
 *
 * The field is not described by it (no `aria-describedby`): the summary is the next stop
 * after the field, and describing the field by the whole help would read the example
 * address out every time the field is focused.
 */
export function FplIdHelp() {
  const copy = useLanguage().messages.fplIdHelp;
  const [host, path, number, rest] = ADDRESS;
  return (
    <details className={styles.help} data-fpl-id-help="league">
      <summary className={styles.summary}>
        <DisclosureIcon className={styles.icon} />
        {copy.title}
      </summary>
      <div className={styles.body}>
        <p>{copy.league}</p>
        {/* On a narrow column the address breaks between its parts, never inside the
            number. */}
        <code className={styles.address}>
          {host}
          <wbr />
          {path}
          <wbr />
          <strong>{number}</strong>
          <wbr />
          {rest}
        </code>
        <a className={styles.site} href={FPL_SITE} target="_blank" rel="noopener noreferrer">
          fantasy.premierleague.com <span className="visually-hidden">({copy.newTab})</span>
          <ExternalIcon />
        </a>
      </div>
    </details>
  );
}
