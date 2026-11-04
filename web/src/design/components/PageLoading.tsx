import styles from "./PageLoading.module.css";

export function PageLoading({ label }: { label: string }) {
  return (
    <div className={styles.page} role="status" aria-busy="true">
      <span className="visually-hidden">{label}</span>
      <div className={styles.heading} aria-hidden="true" />
      <div className={styles.rows} aria-hidden="true">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} />
        ))}
      </div>
    </div>
  );
}
