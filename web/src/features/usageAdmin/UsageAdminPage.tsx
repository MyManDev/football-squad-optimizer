import { useQuery } from "@tanstack/react-query";
import { useId, useMemo, useState, type ReactNode } from "react";

import {
  MAX_RANGE_DAYS,
  rangeEnding,
  rangeIsReadable,
  readUsageReport,
  type UsageRange,
  type UsageReport,
  type UsageTally,
} from "../../data/usageAdmin";
import { markUsageAdmin } from "../../data/usageAdminFlag";
import { Badge, type BadgeTone } from "../../design/components/Badge";
import { Card } from "../../design/components/Card";
import { EmptyState } from "../../design/components/EmptyState";
import { PageLoading } from "../../design/components/PageLoading";
import toggle from "../../design/components/SegmentedToggle.module.css";
import { Stat, StatRow } from "../../design/components/Stat";
import { useLanguage } from "../../i18n/context";
import {
  clicksByZone,
  cumulativeDepth,
  funnel,
  pageChoices,
  reportIsEmpty,
  scrollFor,
  shareOf,
  usageTotals,
  vitalRating,
  type VitalRating,
} from "./reportFigures";
import styles from "./UsageAdminPage.module.css";
import { USAGE_ADMIN_COPY, type UsageAdminCopy } from "./usageAdminCopy";

const PRESETS = [1, 7, 28] as const;
type Preset = (typeof PRESETS)[number];

interface Formats {
  count: (value: number) => string;
  share: (value: number | null) => string;
}

const RATING_TONE: Record<VitalRating, BadgeTone> = { good: "good", needs: "neutral", poor: "bad" };

/**
 * The usage record for a range of UTC days (ADR 0016), behind Cloudflare Access at
 * `/admin/usage`. No public page links here, and the page asks search engines to leave it out.
 * A report read successfully marks this browser as an admin's, which stops it sending usage
 * events and offers the heatmap mode on the site's own pages.
 */
export function UsageAdminPage() {
  const { language, locale } = useLanguage();
  const copy = USAGE_ADMIN_COPY[language];
  const [preset, setPreset] = useState<Preset | null>(7);
  const [range, setRange] = useState<UsageRange>(() => rangeEnding(7));
  const readable = rangeIsReadable(range);

  const report = useQuery({
    queryKey: ["usage-report", range.from, range.to],
    queryFn: async () => {
      const answer = await readUsageReport(range);
      if (answer.state === "ok") markUsageAdmin();
      return answer;
    },
    enabled: readable,
    retry: false,
    staleTime: Infinity,
  });

  const formats = useMemo<Formats>(() => {
    const count = new Intl.NumberFormat(locale);
    const share = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 });
    return {
      count: (value) => count.format(value),
      share: (value) => (value === null ? copy.nothing : share.format(value)),
    };
  }, [locale, copy]);

  const choose = (days: Preset) => {
    setPreset(days);
    setRange(rangeEnding(days));
  };
  const edit = (end: keyof UsageRange, value: string) => {
    setPreset(null);
    setRange((current) => ({ ...current, [end]: value }));
  };

  let body: ReactNode;
  if (!readable) {
    body = <p className={styles.note}>{copy.rangeUnreadable(MAX_RANGE_DAYS)}</p>;
  } else if (report.isPending || report.data === undefined) {
    body = <PageLoading label={copy.loading} />;
  } else if (report.data.state === "ok") {
    body = reportIsEmpty(report.data.value) ? (
      <EmptyState title={copy.empty}>{copy.emptyBody}</EmptyState>
    ) : (
      <ReportSections report={report.data.value} copy={copy} formats={formats} />
    );
  } else {
    const state = report.data.state;
    const [title, detail] = {
      signed_out: [copy.signedOut, copy.signedOutBody],
      refused: [copy.refused, copy.refusedBody],
      not_configured: [copy.notConfigured, copy.notConfiguredBody],
      failed: [copy.failed, copy.failedBody],
    }[state];
    body = (
      <EmptyState title={title}>
        <p className={styles.stateText}>{detail}</p>
        {state === "failed" ? (
          <button type="button" className={styles.button} onClick={() => void report.refetch()}>
            {copy.retry}
          </button>
        ) : null}
      </EmptyState>
    );
  }

  return (
    <div
      className={styles.page}
      data-state={readable ? (report.data?.state ?? "loading") : "range"}
    >
      {/* React puts this in the document's head while the page is mounted. */}
      <meta name="robots" content="noindex, nofollow" />
      <header className={styles.header}>
        <h1 className={styles.title}>{copy.title}</h1>
        <p className={styles.intro}>{copy.intro}</p>
      </header>
      <fieldset className={styles.range}>
        <legend className={styles.legend}>{copy.rangeLegend}</legend>
        <div className={toggle.toggle} role="group" aria-label={copy.rangeLegend}>
          {PRESETS.map((days) => (
            <button
              key={days}
              type="button"
              aria-pressed={preset === days}
              onClick={() => choose(days)}
            >
              {days === 1 ? copy.today : copy.days(days)}
            </button>
          ))}
        </div>
        <label className={styles.dateField}>
          <span>{copy.from}</span>
          <input
            type="date"
            value={range.from}
            max={range.to}
            onChange={(event) => edit("from", event.currentTarget.value)}
          />
        </label>
        <label className={styles.dateField}>
          <span>{copy.to}</span>
          <input
            type="date"
            value={range.to}
            min={range.from}
            onChange={(event) => edit("to", event.currentTarget.value)}
          />
        </label>
        <p className={styles.rangeShown}>{copy.rangeShown(range.from, range.to)}</p>
      </fieldset>
      {body}
    </div>
  );
}

function ReportSections({
  report,
  copy,
  formats,
}: {
  report: UsageReport;
  copy: UsageAdminCopy;
  formats: Formats;
}) {
  const totals = usageTotals(report);
  const choices = useMemo(() => pageChoices(report), [report]);
  const [chosen, setChosen] = useState<{ page: string | null; device: string | null }>({
    page: null,
    device: null,
  });
  const page =
    chosen.page !== null && choices.pages.includes(chosen.page)
      ? chosen.page
      : (choices.pages[0] ?? "");
  const device =
    chosen.device !== null && choices.devices.includes(chosen.device)
      ? chosen.device
      : (choices.devices[0] ?? "");
  const place = (
    <PlaceChoice
      copy={copy}
      choices={choices}
      page={page}
      device={device}
      onChange={(next) => setChosen((current) => ({ ...current, ...next }))}
    />
  );
  const { count, share } = formats;
  const sourceName = (name: string) =>
    name in copy.sourceNames ? copy.sourceNames[name as keyof UsageAdminCopy["sourceNames"]] : name;
  const visitName = (name: string) =>
    name in copy.visitNames ? copy.visitNames[name as keyof UsageAdminCopy["visitNames"]] : name;

  return (
    <>
      {report.truncated ? <p className={styles.warning}>{copy.truncated}</p> : null}

      <Card title={copy.totals}>
        <StatRow>
          <Stat label={copy.visits} value={count(totals.visits)} tone="accent" />
          <Stat label={copy.events} value={count(totals.events)} />
          <Stat label={copy.claimShare} value={share(totals.claimShare)} />
          <Stat label={copy.returningShare} value={share(totals.returningShare)} />
          <Stat label={copy.phoneShare} value={share(totals.phoneShare)} />
          <Stat label={copy.frustrationShare} value={share(totals.frustrationShare)} />
        </StatRow>
      </Card>

      <Card title={copy.funnel}>
        <Table
          label={copy.funnel}
          head={[copy.name, copy.visits, copy.ofOpened]}
          rows={funnel(report).map((row) => [
            copy.steps[row.step],
            count(row.visits),
            <Bar key="bar" share={row.share} text={share(row.share)} />,
          ])}
          empty={copy.nothing}
        />
      </Card>

      <div className={styles.pair}>
        <Card title={copy.tools}>
          <TallyTable
            copy={copy}
            formats={formats}
            entries={report.tools}
            name={(name) => name || copy.noTool}
          />
        </Card>
        <Card title={copy.pages}>
          <TallyTable copy={copy} formats={formats} entries={report.pages} name={(name) => name} />
        </Card>
      </div>

      <div className={styles.pair}>
        <Card title={copy.sources}>
          <TallyTable
            copy={copy}
            formats={formats}
            entries={report.behaviour.arrivals.sources}
            name={sourceName}
          />
        </Card>
        <Card title={copy.returns}>
          <TallyTable
            copy={copy}
            formats={formats}
            entries={report.behaviour.arrivals.visits}
            name={visitName}
          />
        </Card>
      </div>

      <ScrollSections
        report={report}
        copy={copy}
        formats={formats}
        page={page}
        device={device}
        place={place}
      />

      <Card title={copy.vitals}>
        <Table
          label={copy.vitals}
          head={[
            copy.metric,
            copy.page,
            copy.device,
            copy.readings,
            copy.p75,
            copy.ratingNames.good,
            copy.ratingNames.needs,
            copy.ratingNames.poor,
          ]}
          rows={report.behaviour.vitals.map((vital) => {
            const rating = vitalRating(vital.metric, vital.p75);
            return [
              vital.metric.toUpperCase(),
              vital.page,
              deviceName(copy, vital.device),
              count(vital.events),
              <span key="p75" className={styles.p75}>
                {vital.p75 === null ? copy.nothing : p75Text(copy, vital.metric, vital.p75, count)}
                {rating === null ? null : (
                  <Badge tone={RATING_TONE[rating]}>{copy.ratingNames[rating]}</Badge>
                )}
              </span>,
              share(vital.ratings.good),
              share(vital.ratings.needs),
              share(vital.ratings.poor),
            ];
          })}
          empty={copy.nothing}
        />
      </Card>

      <Card title={copy.errors}>
        <Table
          label={copy.errors}
          head={[copy.error, copy.page, copy.events, copy.visits]}
          rows={report.behaviour.errors.map((error) => [
            error.error in copy.errorNames
              ? copy.errorNames[error.error as keyof UsageAdminCopy["errorNames"]]
              : error.error,
            error.page,
            count(error.events),
            count(error.visits),
          ])}
          empty={copy.nothing}
        />
      </Card>

      <Card title={copy.clicks} aside={place}>
        <Table
          label={copy.clicks}
          head={[copy.zone, copy.clickCount, copy.rage, copy.dead]}
          rows={clicksByZone(report, page, device).map((zone) => [
            zone.zone,
            count(zone.clicks),
            count(zone.rage),
            count(zone.dead),
          ])}
          empty={copy.nothing}
        />
      </Card>
    </>
  );
}

function deviceName(copy: UsageAdminCopy, device: string): string {
  return device in copy.deviceNames
    ? copy.deviceNames[device as keyof UsageAdminCopy["deviceNames"]]
    : device;
}

/** A 75th percentile in its unit: milliseconds, or layout shift as the browser writes it. */
function p75Text(
  copy: UsageAdminCopy,
  metric: string,
  value: number,
  count: (value: number) => string,
): string {
  return metric === "cls" ? (value / 1000).toFixed(2) : copy.milliseconds(count(value));
}

function ScrollSections({
  report,
  copy,
  formats,
  page,
  device,
  place,
}: {
  report: UsageReport;
  copy: UsageAdminCopy;
  formats: Formats;
  page: string;
  device: string;
  place: ReactNode;
}) {
  const { count, share } = formats;
  const scroll = scrollFor(report, page, device);
  const dwellTotal = scroll === null ? 0 : Object.values(scroll.dwell).reduce((a, b) => a + b, 0);
  return (
    <>
      <Card title={copy.scroll} aside={place}>
        <Table
          label={copy.scroll}
          head={[copy.depth, copy.views, copy.share]}
          rows={
            scroll === null
              ? []
              : cumulativeDepth(scroll.depth).map((row) => [
                  copy.atLeast(share(row.depth / 100)),
                  count(row.views),
                  <Bar key="bar" share={row.share} text={share(row.share)} />,
                ])
          }
          empty={copy.nothing}
        />
      </Card>
      <Card title={copy.dwell}>
        <Table
          label={copy.dwell}
          head={[copy.dwell, copy.views, copy.share]}
          rows={
            scroll === null
              ? []
              : (Object.keys(copy.dwellNames) as (keyof UsageAdminCopy["dwellNames"])[]).map(
                  (bucket) => {
                    const views = scroll.dwell[bucket] ?? 0;
                    const part = shareOf(views, dwellTotal);
                    return [
                      copy.dwellNames[bucket],
                      count(views),
                      <Bar key="bar" share={part} text={share(part)} />,
                    ];
                  },
                )
          }
          empty={copy.nothing}
        />
      </Card>
    </>
  );
}

function PlaceChoice({
  copy,
  choices,
  page,
  device,
  onChange,
}: {
  copy: UsageAdminCopy;
  choices: { pages: string[]; devices: string[] };
  page: string;
  device: string;
  onChange: (next: { page?: string; device?: string }) => void;
}) {
  const id = useId();
  if (choices.pages.length === 0) return null;
  return (
    <span className={styles.place}>
      <label htmlFor={`${id}-page`}>{copy.page}</label>
      <select
        id={`${id}-page`}
        value={page}
        onChange={(event) => onChange({ page: event.currentTarget.value })}
      >
        {choices.pages.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      <label htmlFor={`${id}-device`}>{copy.device}</label>
      <select
        id={`${id}-device`}
        value={device}
        onChange={(event) => onChange({ device: event.currentTarget.value })}
      >
        {choices.devices.map((name) => (
          <option key={name} value={name}>
            {deviceName(copy, name)}
          </option>
        ))}
      </select>
    </span>
  );
}

function TallyTable({
  copy,
  formats,
  entries,
  name,
}: {
  copy: UsageAdminCopy;
  formats: Formats;
  entries: readonly UsageTally[];
  name: (word: string) => string;
}) {
  const sorted = [...entries].sort((a, b) => b.visits - a.visits || b.events - a.events);
  return (
    <Table
      head={[copy.name, copy.visits, copy.events]}
      rows={sorted.map((entry) => [
        name(entry.name),
        formats.count(entry.visits),
        formats.count(entry.events),
      ])}
      empty={copy.nothing}
    />
  );
}

/** A share drawn as a bar under its figure. */
function Bar({ share, text }: { share: number | null; text: string }) {
  return (
    <span className={styles.barCell}>
      <span className={styles.barText}>{text}</span>
      <span className={styles.bar} aria-hidden="true">
        <span className={styles.barFill} style={{ transform: `scaleX(${share ?? 0})` }} />
      </span>
    </span>
  );
}

/** A table whose first column names a row and whose others are figures. */
function Table({
  label,
  head,
  rows,
  empty,
}: {
  label?: string;
  head: string[];
  rows: ReactNode[][];
  empty: string;
}) {
  if (rows.length === 0) return <p className={styles.note}>{empty}</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table} aria-label={label}>
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th key={index} scope="col">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, column) =>
                column === 0 ? (
                  <th key={column} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={column}>{cell}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
