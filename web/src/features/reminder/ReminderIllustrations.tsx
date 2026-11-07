/**
 * The three pictures of the how-to page: the browser's permission question, the share sheet
 * on an iPhone, and the notification as it arrives. Inline SVG in the page's own colours,
 * so they read by day and by night; each is decorative beside its step's words.
 */

import styles from "./ReminderPage.module.css";

export function PermissionPicture({ allow }: { allow: string }) {
  return (
    <svg className={styles.picture} viewBox="0 0 240 150" aria-hidden="true">
      <rect x="8" y="8" width="224" height="134" rx="12" className={styles.screen} />
      <rect x="8" y="8" width="224" height="22" rx="12" className={styles.bar} />
      <rect x="28" y="48" width="184" height="78" rx="10" className={styles.dialog} />
      <circle cx="52" cy="70" r="9" className={styles.bell} />
      <path d="M48 70 h8 M52 66 v8" className={styles.bellMark} />
      <rect x="70" y="63" width="120" height="7" rx="3.5" className={styles.line} />
      <rect x="70" y="76" width="84" height="7" rx="3.5" className={styles.line} />
      <rect x="44" y="96" width="70" height="20" rx="6" className={styles.ghostButton} />
      <rect x="126" y="96" width="70" height="20" rx="6" className={styles.allowButton} />
      <text x="161" y="110" textAnchor="middle" className={styles.allowText}>
        {allow}
      </text>
    </svg>
  );
}

export function HomeScreenPicture({ add }: { add: string }) {
  return (
    <svg className={styles.picture} viewBox="0 0 240 150" aria-hidden="true">
      <rect x="70" y="4" width="100" height="142" rx="16" className={styles.phone} />
      <rect x="78" y="14" width="84" height="122" rx="10" className={styles.screen} />
      <rect x="78" y="72" width="84" height="64" rx="10" className={styles.dialog} />
      <rect x="88" y="82" width="64" height="6" rx="3" className={styles.line} />
      <rect x="88" y="94" width="48" height="6" rx="3" className={styles.line} />
      <rect x="88" y="108" width="64" height="18" rx="5" className={styles.allowButton} />
      <text x="120" y="121" textAnchor="middle" className={styles.allowTextSmall}>
        {add}
      </text>
      <path d="M120 30 v22 M112 38 l8 -8 l8 8" className={styles.share} />
      <rect x="106" y="44" width="28" height="18" rx="3" className={styles.shareBox} />
    </svg>
  );
}

export function NotificationPicture({ title, body }: { title: string; body: string }) {
  return (
    <svg className={styles.picture} viewBox="0 0 240 150" aria-hidden="true">
      <rect x="70" y="4" width="100" height="142" rx="16" className={styles.phone} />
      <rect x="78" y="14" width="84" height="122" rx="10" className={styles.screen} />
      <rect x="84" y="24" width="72" height="42" rx="8" className={styles.toast} />
      <rect x="90" y="30" width="12" height="12" rx="3" className={styles.appIcon} />
      <text x="106" y="40" className={styles.toastTitle}>
        {title}
      </text>
      <text x="106" y="56" className={styles.toastBody}>
        {body}
      </text>
    </svg>
  );
}
