import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { CHIP_HALVES, CHIP_NAMES, isEntryChips } from "../chipShape";
import type { EntrySquad } from "../types";
import styles from "./MemberResourceCards.module.css";

export function MemberResourceCards({ squad }: { squad: EntrySquad }) {
  const { messages, locale } = useLanguage();
  const copy = messages.memberResources;
  const chips = isEntryChips(squad.chips, squad.gameweek) ? squad.chips : undefined;
  const knownTransfers =
    squad.free_transfers_known === true &&
    Number.isSafeInteger(squad.free_transfers) &&
    squad.free_transfers >= 0;
  return (
    <>
      <Card title={copy.transfersTitle} aside={copy.asOf(squad.gameweek)}>
        <p className={styles.count}>
          {knownTransfers
            ? new Intl.NumberFormat(locale).format(squad.free_transfers)
            : copy.unknown}
        </p>
      </Card>
      <Card title={copy.chipsTitle} aside={copy.asOf(squad.gameweek)}>
        {!chips?.known ? (
          <p>{copy.chipsMissing}</p>
        ) : (
          <div className={styles.chips}>
            {CHIP_NAMES.map((chip) => (
              <section key={chip}>
                <h3 className={styles.name}>{messages.leagueMembers.chipNames[chip]}</h3>
                <dl className={styles.windows}>
                  {CHIP_HALVES.map((half) => {
                    const window = chips.states[chip]![half];
                    return (
                      <div key={half}>
                        <dt>{copy.halves[half]}</dt>
                        <dd>
                          {window ? (
                            <>
                              <strong>
                                {window.state === "used"
                                  ? copy.used(window.gameweek!)
                                  : copy.states[window.state]}
                              </strong>
                              <span>{copy.window(window.start_event, window.stop_event)}</span>
                            </>
                          ) : (
                            copy.noWindow
                          )}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </section>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
