import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import {
  analysisAsset,
  fetchAnalysisIndex,
  fetchMarkdown,
  type MeasurementEntry,
  type MeasurementType,
} from "../data";
import styles from "./AnalysisPage.module.css";

const TYPE_TONES: Record<MeasurementType, "good" | "bad" | "neutral" | "accent"> = {
  passed: "good",
  negative: "bad",
  descriptive: "neutral",
  prereg: "accent",
};

const EMPTY_ENTRIES: MeasurementEntry[] = [];

function shortDate(value: string | null, locale: string, noDate: string): string {
  if (!value) return noDate;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function MeasurementCard({ entry }: { entry: MeasurementEntry }) {
  const { locale, messages } = useLanguage();
  return (
    <article className={styles.card}>
      <div className={styles.cardMeta}>
        <Badge tone={TYPE_TONES[entry.type]}>{messages.analysis.types[entry.type]}</Badge>
        <span>{entry.phase}</span>
        <time dateTime={entry.date ?? undefined}>
          {shortDate(entry.date, locale, messages.analysis.noDate)}
        </time>
      </div>
      <h2 className={styles.cardTitle}>
        <Link to={`/analysis/${entry.slug}`}>{entry.title}</Link>
      </h2>
      <p>{entry.finding}</p>
    </article>
  );
}

function MeasurementDocument({ entries, slug }: { entries: MeasurementEntry[]; slug: string }) {
  const { locale, messages } = useLanguage();
  const copy = messages.analysis;
  const entry = entries.find((candidate) => candidate.slug === slug);
  const documentQuery = useQuery({
    queryKey: ["analysis-document", entry?.markdown_path],
    queryFn: () => fetchMarkdown(entry!.markdown_path),
    enabled: Boolean(entry),
  });

  if (!entry) {
    return <EmptyState title={copy.notFoundTitle}>{copy.notFoundBody}</EmptyState>;
  }
  if (documentQuery.isPending) return <EmptyState title={copy.loadingDocument} />;
  if (documentQuery.isError) {
    return <EmptyState title={copy.documentError}>{String(documentQuery.error)}</EmptyState>;
  }

  const rendered = DOMPurify.sanitize(marked.parse(documentQuery.data, { async: false }) as string);
  return (
    <div className={styles.documentPage}>
      <div className={styles.documentActions}>
        <Link to="/analysis">{copy.back}</Link>
        {entry.json_path ? (
          <a href={analysisAsset(entry.json_path)} target="_blank" rel="noreferrer">
            {messages.common.rawJson}
          </a>
        ) : null}
      </div>
      <div className={styles.cardMeta}>
        <Badge tone={TYPE_TONES[entry.type]}>{copy.types[entry.type]}</Badge>
        <span>{entry.phase}</span>
        <time dateTime={entry.date ?? undefined}>{shortDate(entry.date, locale, copy.noDate)}</time>
      </div>
      <article className={styles.markdown} dangerouslySetInnerHTML={{ __html: rendered }} />
    </div>
  );
}

export function AnalysisPage() {
  const { messages } = useLanguage();
  const copy = messages.analysis;
  const { slug } = useParams();
  const indexQuery = useQuery({ queryKey: ["analysis-index"], queryFn: fetchAnalysisIndex });
  const [tab, setTab] = useState<"all" | "negative">("all");
  const [type, setType] = useState<"all" | MeasurementType>("all");
  const [phase, setPhase] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const entries = indexQuery.data?.entries ?? EMPTY_ENTRIES;
  const phases = useMemo(() => [...new Set(entries.map((entry) => entry.phase))].sort(), [entries]);
  const filtered = useMemo(
    () =>
      entries.filter((entry) => {
        if (tab === "negative" && entry.type !== "negative") return false;
        if (type !== "all" && entry.type !== type) return false;
        if (phase !== "all" && entry.phase !== phase) return false;
        const date = entry.date?.slice(0, 10);
        if (from && (!date || date < from)) return false;
        if (to && (!date || date > to)) return false;
        return true;
      }),
    [entries, from, phase, tab, to, type],
  );

  if (indexQuery.isPending) return <EmptyState title={copy.loadingIndex} />;
  if (indexQuery.isError) {
    return <EmptyState title={copy.indexError}>{String(indexQuery.error)}</EmptyState>;
  }
  if (slug) return <MeasurementDocument entries={entries} slug={slug} />;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.kicker}>{copy.kicker}</div>
        <h1>{copy.title}</h1>
        <p>{copy.lede}</p>
      </header>

      <div className={styles.tabs} aria-label={copy.viewLabel}>
        <button type="button" aria-pressed={tab === "all"} onClick={() => setTab("all")}>
          {copy.all}
        </button>
        <button type="button" aria-pressed={tab === "negative"} onClick={() => setTab("negative")}>
          {copy.negatives}
        </button>
      </div>

      <section className={styles.filters} aria-label={copy.filters}>
        <label>
          {copy.type}
          <select value={type} onChange={(event) => setType(event.target.value as typeof type)}>
            <option value="all">{copy.allOption}</option>
            {Object.entries(copy.types).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          {copy.phase}
          <select value={phase} onChange={(event) => setPhase(event.target.value)}>
            <option value="all">{copy.allOption}</option>
            {phases.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          {copy.from}
          <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
        </label>
        <label>
          {copy.to}
          <input type="date" value={to} onChange={(event) => setTo(event.target.value)} />
        </label>
      </section>

      <p className={styles.count} aria-live="polite">
        {copy.count(filtered.length, entries.length)}
      </p>
      {filtered.length ? (
        <div className={styles.grid}>
          {filtered.map((entry) => (
            <MeasurementCard entry={entry} key={entry.slug} />
          ))}
        </div>
      ) : (
        <EmptyState title={copy.empty} />
      )}
    </div>
  );
}
