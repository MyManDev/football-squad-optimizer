import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router";

import { deviceClass, usagePlace } from "../../data/usage";
import toggle from "../../design/components/SegmentedToggle.module.css";
import { useLanguage } from "../../i18n/context";
import {
  adminOnce,
  measureCells,
  reportOnce,
  selectCells,
  type CellSelection,
  type HeatCell,
  type HeatDays,
  type HeatDevice,
  type HeatMark,
} from "./heatmap";
import styles from "./HeatmapMode.module.css";
import { USAGE_ADMIN_COPY } from "./usageAdminCopy";

const DEVICES: readonly HeatDevice[] = ["phone", "tablet", "desktop"];
const MARKS: readonly HeatMark[] = ["all", "rage", "dead"];
const RANGES: readonly HeatDays[] = [7, 28];

type Read =
  { days: HeatDays; state: "ok"; selection: CellSelection } | { days: HeatDays; state: "failed" };

/**
 * The heatmap mode (ADR 0016): for a browser marked as an admin's, a small button that draws
 * the record's clicks over the page being looked at, cell by cell over each zone's live box,
 * for a chosen device class, mark and range. Only the clicks of the page and tool the address
 * names are drawn; clicks in no zone are counted in the panel instead. It asks whether the
 * person may read the record once a page load and shows nothing unless the answer is yes.
 * Nothing it draws takes a pointer, so the page under it works as usual.
 */
export function HeatmapMode() {
  const { language, locale } = useLanguage();
  const copy = USAGE_ADMIN_COPY[language];
  const { pathname } = useLocation();
  const { page, tool } = usagePlace(pathname);

  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    let live = true;
    void adminOnce().then((answer) => {
      if (live && answer.state === "ok") setAdmin(true);
    });
    return () => {
      live = false;
    };
  }, []);

  const [open, setOpen] = useState(false);
  const [device, setDevice] = useState<HeatDevice>(() => {
    const own = deviceClass();
    return own === "unknown" ? "desktop" : own;
  });
  const [mark, setMark] = useState<HeatMark>("all");
  const [days, setDays] = useState<HeatDays>(7);
  const [read, setRead] = useState<{
    days: HeatDays;
    answer: Awaited<ReturnType<typeof reportOnce>>;
  } | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    void reportOnce(days).then((answer) => {
      if (live) setRead({ days, answer });
    });
    return () => {
      live = false;
    };
  }, [open, days]);

  const current = useMemo<Read | null>(() => {
    if (read === null || read.days !== days) return null;
    if (read.answer.state !== "ok") return { days, state: "failed" };
    return {
      days,
      state: "ok",
      selection: selectCells(read.answer.value.behaviour.clicks, { page, tool }, device, mark),
    };
  }, [read, days, page, tool, device, mark]);
  const selection = current?.state === "ok" ? current.selection : null;

  const rootRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const [cells, setCells] = useState<HeatCell[]>([]);

  // Redraw on scroll, resize, a new address and any change to the document, at most once a
  // frame. The mode's own nodes changing is not a change to the page.
  useEffect(() => {
    if (!open || selection === null) return;
    let frame = 0;
    const draw = () => {
      frame = 0;
      setCells(measureCells(selection, layerRef.current));
    };
    const schedule = () => {
      if (frame === 0) frame = window.requestAnimationFrame(draw);
    };
    schedule();
    const observer = new MutationObserver((records) => {
      const root = rootRef.current;
      if (records.some((record) => root === null || !root.contains(record.target))) schedule();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
    });
    window.addEventListener("scroll", schedule, { capture: true, passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
    };
  }, [open, selection, pathname]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  function close() {
    setOpen(false);
    setCells([]);
    window.requestAnimationFrame(() => openRef.current?.focus({ preventScroll: true }));
  }

  if (!admin || pathname.startsWith("/admin")) return null;

  const count = new Intl.NumberFormat(locale);
  const status =
    current === null
      ? copy.heatLoading
      : current.state === "failed"
        ? copy.heatFailed
        : current.selection.total === 0 && current.selection.outside === 0
          ? copy.heatEmpty
          : copy.heatTotal(count.format(current.selection.total));

  return createPortal(
    <div ref={rootRef} className={styles.root} data-heatmap="">
      {open && selection !== null ? (
        <div ref={layerRef} className={styles.layer} aria-hidden="true">
          {cells.map((cell) => (
            <div
              key={cell.key}
              className={styles.cell}
              style={{
                left: cell.left,
                top: cell.top,
                width: cell.width,
                height: cell.height,
                background: cell.colour,
              }}
            />
          ))}
        </div>
      ) : null}
      {open ? (
        <section className={styles.panel} aria-labelledby="heatmap-title">
          <header className={styles.panelHeader}>
            <h2 id="heatmap-title" className={styles.panelTitle}>
              {copy.heatmapTitle}
            </h2>
            <button ref={closeRef} type="button" className={styles.close} onClick={close}>
              {copy.close}
            </button>
          </header>
          <p className={styles.line}>{copy.heatPage(page, tool)}</p>
          <Choice
            label={copy.device}
            options={DEVICES.map((value) => ({ value, text: copy.deviceNames[value] }))}
            value={device}
            onChange={setDevice}
          />
          <Choice
            label={copy.mark}
            options={MARKS.map((value) => ({ value, text: copy.markNames[value] }))}
            value={mark}
            onChange={setMark}
          />
          <Choice
            label={copy.heatRange}
            options={RANGES.map((value) => ({ value, text: copy.days(value) }))}
            value={days}
            onChange={setDays}
          />
          <p className={styles.line} role="status">
            {status}
          </p>
          {selection !== null && selection.outside > 0 ? (
            <p className={styles.line}>{copy.heatOutside(count.format(selection.outside))}</p>
          ) : null}
          {selection !== null && selection.untooled ? (
            <p className={styles.line}>{copy.heatUntooled}</p>
          ) : null}
          <div className={styles.legend} aria-hidden="true">
            <span>{copy.legendFew}</span>
            <span className={styles.ramp} />
            <span>{copy.legendMany}</span>
          </div>
        </section>
      ) : (
        <button ref={openRef} type="button" className={styles.open} onClick={() => setOpen(true)}>
          {copy.heatmapOpen}
        </button>
      )}
    </div>,
    document.body,
  );
}

function Choice<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; text: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className={styles.choice}>
      <span className={styles.choiceLabel}>{label}</span>
      <div className={toggle.toggle} role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={option.value === value}
            onClick={() => onChange(option.value)}
          >
            {option.text}
          </button>
        ))}
      </div>
    </div>
  );
}
