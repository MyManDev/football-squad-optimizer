import type { ReactNode } from "react";

import styles from "./FixtureChoice.module.css";

export interface FixtureOption<T> {
  value: T;
  label: ReactNode;
  /** The whole name of a label that prints a code. */
  title?: string;
}

/**
 * One of the fixture page's choices, as radios: joined segments for the two views, and a grid
 * of separate cells for the clubs. The group's name is for assistive technology; what the
 * options say is enough to see.
 */
export function FixtureChoice<T extends string>({
  legend,
  name,
  options,
  value,
  onChange,
  clubs = false,
}: {
  legend: string;
  name: string;
  options: readonly FixtureOption<T>[];
  value: T;
  onChange: (value: T) => void;
  clubs?: boolean;
}) {
  return (
    <fieldset className={styles.choice}>
      <legend className="visually-hidden">{legend}</legend>
      <div className={clubs ? styles.clubs : styles.segments}>
        {options.map((option) => (
          <label
            className={clubs ? styles.club : styles.segment}
            key={option.value}
            title={option.title}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={option.value === value}
              onChange={() => onChange(option.value)}
            />
            <span className={styles.label}>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
