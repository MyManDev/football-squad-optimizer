import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { CHIP_HALVES, CHIP_NAMES, isKnownWindow, knownChips } from "../chipShape";
import type { EntrySquad } from "../types";
import styles from "./MemberResourceCards.module.css";

/**
 * What the member can still use: the free transfers held before the deadline and every
 * chip by half. The member page shows both under its closed "Chips and free transfers"
 * section, so the cards themselves never collapse. A count or a window the document does
 * not state draws nothing, a card with nothing in it is left out, and with neither card
 * the section says it is empty, as an empty tool does.
 */
export function MemberResourceCards({ squad }: { squad: EntrySquad }) {
  const { messages, locale } = useLanguage();
  const copy = messages.memberResources;
  const chips = knownChips(squad);
  const rows = chips
    ? CHIP_NAMES.flatMap((chip) => {
        const windows = CHIP_HALVES.flatMap((half) => {
          const window = chips.states[chip]?.[half];
          return isKnownWindow(window) ? [{ half, window }] : [];
        });
        return windows.length > 0 ? [{ chip, windows }] : [];
      })
    : [];
  const knownTransfers =
    squad.free_transfers_known === true &&
    Number.isSafeInteger(squad.free_transfers) &&
    squad.free_transfers >= 0;
  if (!knownTransfers && rows.length === 0)
    return <EmptyState title={messages.leagueMembers.toolEmpty} />;
  return (
    <>
      {knownTransfers ? (
        <Card title={copy.transfersTitle}>
          <p className={styles.count}>
            {new Intl.NumberFormat(locale).format(squad.free_transfers)}
          </p>
        </Card>
      ) : null}
      {rows.length > 0 ? (
        <Card title={copy.chipsTitle}>
          <div className={styles.chips}>
            {rows.map(({ chip, windows }) => (
              <section key={chip}>
                <h3 className={styles.name}>{messages.leagueMembers.chipNames[chip]}</h3>
                <dl className={styles.windows}>
                  {windows.map(({ half, window }) => (
                    <div key={half}>
                      <dt>{copy.halves[half]}</dt>
                      <dd>
                        <strong>
                          {window.state === "used"
                            ? copy.used(window.gameweek!)
                            : copy.states[window.state]}
                        </strong>
                        <span>{copy.window(window.start_event, window.stop_event)}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        </Card>
      ) : null}
    </>
  );
}
