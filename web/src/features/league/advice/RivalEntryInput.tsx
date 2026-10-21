import { useState } from "react";
import { useLanguage } from "../../../i18n/context";
import type { EntryView } from "../types";
import styles from "./MemberDecisionControls.module.css";

/** Read one listed member on demand, without preloading the rest of the league. */
export function RivalEntryInput({
  members,
  entryId,
  onSelect,
}: {
  members: readonly EntryView[];
  entryId: number;
  onSelect: (entryId: number) => void;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const [value, setValue] = useState("");
  const [invalid, setInvalid] = useState(false);
  return (
    <form
      className={styles.rivalField}
      onSubmit={(event) => {
        event.preventDefault();
        const id = Number(value.trim());
        const valid =
          /^\d+$/.test(value.trim()) &&
          Number.isSafeInteger(id) &&
          id !== entryId &&
          members.some((member) => member.member_kind === "human" && member.entry_id === id);
        setInvalid(!valid);
        if (valid) onSelect(id);
      }}
    >
      <label>
        <span className={styles.label}>{copy.rivalEntryLabel}</span>
        <input
          inputMode="numeric"
          value={value}
          aria-invalid={invalid || undefined}
          onChange={(event) => {
            setValue(event.target.value);
            setInvalid(false);
          }}
        />
      </label>
      <button type="submit">{copy.rivalEntryChoose}</button>
      {invalid ? <p role="alert">{copy.rivalEntryNotListed}</p> : null}
    </form>
  );
}
