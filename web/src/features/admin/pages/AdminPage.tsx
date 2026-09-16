import { Link } from "react-router";

import { useLanguage } from "../../../i18n/context";
import styles from "./AdminPage.module.css";

export function AdminPage() {
  const { messages } = useLanguage();
  const copy = messages.admin;

  return (
    <div className={styles.page}>
      <h1>{copy.title}</h1>
      <p>{copy.notice}</p>
      <ul className={styles.links}>
        <li>
          <Link to="/analysis">{copy.analysis}</Link>
        </li>
        <li>
          <Link to="/status">{copy.status}</Link>
        </li>
        <li>
          <a href="https://github.com/MyManDev/football-squad-optimizer/blob/develop/docs/decisions.md">
            {copy.decisions}
          </a>
        </li>
      </ul>
    </div>
  );
}
