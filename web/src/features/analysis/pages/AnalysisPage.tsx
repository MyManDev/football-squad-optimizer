import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { EmptyState } from "../../../design/components/EmptyState";
import {
  analysisAsset,
  fetchAnalysisIndex,
  fetchMarkdown,
  type MeasurementEntry,
  type MeasurementType,
} from "../data";
import styles from "./AnalysisPage.module.css";

const TYPE_LABELS: Record<MeasurementType, string> = {
  passed: "kapı geçti",
  negative: "temiz negatif",
  descriptive: "betimleyici",
  prereg: "prereg",
};

const TYPE_TONES: Record<MeasurementType, "good" | "bad" | "neutral" | "accent"> = {
  passed: "good",
  negative: "bad",
  descriptive: "neutral",
  prereg: "accent",
};

const EMPTY_ENTRIES: MeasurementEntry[] = [];

function shortDate(value: string | null): string {
  if (!value) return "tarih kaydı yok";
  return new Intl.DateTimeFormat("tr-TR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function MeasurementCard({ entry }: { entry: MeasurementEntry }) {
  return (
    <article className={styles.card}>
      <div className={styles.cardMeta}>
        <Badge tone={TYPE_TONES[entry.type]}>{TYPE_LABELS[entry.type]}</Badge>
        <span>{entry.phase}</span>
        <time dateTime={entry.date ?? undefined}>{shortDate(entry.date)}</time>
      </div>
      <h2 className={styles.cardTitle}>
        <Link to={`/analysis/${entry.slug}`}>{entry.title}</Link>
      </h2>
      <p>{entry.finding}</p>
    </article>
  );
}

function MeasurementDocument({ entries, slug }: { entries: MeasurementEntry[]; slug: string }) {
  const entry = entries.find((candidate) => candidate.slug === slug);
  const documentQuery = useQuery({
    queryKey: ["analysis-document", entry?.markdown_path],
    queryFn: () => fetchMarkdown(entry!.markdown_path),
    enabled: Boolean(entry),
  });

  if (!entry) {
    return (
      <EmptyState title="Ölçüm bulunamadı.">İndekste bu kimlikle bir artefakt yok.</EmptyState>
    );
  }
  if (documentQuery.isPending) return <EmptyState title="Ölçüm yükleniyor…" />;
  if (documentQuery.isError) {
    return <EmptyState title="Ölçüm açılamadı.">{String(documentQuery.error)}</EmptyState>;
  }

  const rendered = DOMPurify.sanitize(marked.parse(documentQuery.data, { async: false }) as string);
  return (
    <div className={styles.documentPage}>
      <div className={styles.documentActions}>
        <Link to="/analysis">← Analiz Merkezi</Link>
        {entry.json_path ? (
          <a href={analysisAsset(entry.json_path)} target="_blank" rel="noreferrer">
            Ham JSON
          </a>
        ) : null}
      </div>
      <div className={styles.cardMeta}>
        <Badge tone={TYPE_TONES[entry.type]}>{TYPE_LABELS[entry.type]}</Badge>
        <span>{entry.phase}</span>
        <time dateTime={entry.date ?? undefined}>{shortDate(entry.date)}</time>
      </div>
      <article className={styles.markdown} dangerouslySetInnerHTML={{ __html: rendered }} />
    </div>
  );
}

export function AnalysisPage() {
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

  if (indexQuery.isPending) return <EmptyState title="Ölçüm indeksi yükleniyor…" />;
  if (indexQuery.isError) {
    return <EmptyState title="Analiz Merkezi açılamadı.">{String(indexQuery.error)}</EmptyState>;
  }
  if (slug) return <MeasurementDocument entries={entries} slug={slug} />;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.kicker}>kanıt, kararın yanında</div>
        <h1>Analiz Merkezi</h1>
        <p>
          Geçen kapılar kadar temiz negatifler de burada kalır. İçerikler İngilizce kaynak
          belgelerin değişmeden sunulan kopyalarıdır.
        </p>
      </header>

      <div className={styles.tabs} aria-label="Ölçüm görünümü">
        <button type="button" aria-pressed={tab === "all"} onClick={() => setTab("all")}>
          Tüm ölçümler
        </button>
        <button type="button" aria-pressed={tab === "negative"} onClick={() => setTab("negative")}>
          Negatifler
        </button>
      </div>

      <section className={styles.filters} aria-label="Ölçüm filtreleri">
        <label>
          Tür
          <select value={type} onChange={(event) => setType(event.target.value as typeof type)}>
            <option value="all">Tümü</option>
            {Object.entries(TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Faz
          <select value={phase} onChange={(event) => setPhase(event.target.value)}>
            <option value="all">Tümü</option>
            {phases.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Başlangıç tarihi
          <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
        </label>
        <label>
          Bitiş tarihi
          <input type="date" value={to} onChange={(event) => setTo(event.target.value)} />
        </label>
      </section>

      <p className={styles.count} aria-live="polite">
        {filtered.length} / {entries.length} ölçüm gösteriliyor
      </p>
      {filtered.length ? (
        <div className={styles.grid}>
          {filtered.map((entry) => (
            <MeasurementCard entry={entry} key={entry.slug} />
          ))}
        </div>
      ) : (
        <EmptyState title="Bu filtrelerle ölçüm yok." />
      )}
    </div>
  );
}
