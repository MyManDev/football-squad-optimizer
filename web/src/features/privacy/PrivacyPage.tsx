import { useLanguage } from "../../i18n/context";
import { PRIVACY_COPY } from "./privacyCopy";
import styles from "./PrivacyPage.module.css";

/** The site's privacy page: what is sent where, one short section per flow. */
export function PrivacyPage() {
  const { language } = useLanguage();
  const copy = PRIVACY_COPY[language];
  return (
    <section className={styles.page} data-zone="privacy">
      <h1>{copy.title}</h1>
      {copy.sections.map((section) => (
        <section key={section.title} className={styles.section}>
          <h2>{section.title}</h2>
          <p>{section.body}</p>
        </section>
      ))}
    </section>
  );
}
