import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import type { LLMOptCopy } from "./copy";
import {
  OWN_KEY_PROVIDERS,
  clearOwnKey,
  isOwnKeyProvider,
  localBaseUrl,
  setOwnKey,
  useOwnKey,
  type OwnKeyProvider,
} from "./ownKey";
import { PROVIDERS } from "./providers";
import styles from "./LLMOptPage.module.css";

/**
 * The member's provider, model and key. The key field is uncontrolled: its text is read once
 * on Save, handed to the key holder and wiped from the field, so no component state holds it.
 *
 * The field is a text field drawn as dots, not a password field. A browser offers to save
 * what a password field held once the field leaves the page, whatever `autocomplete` says,
 * and a saved key would outlive the tab. A text field with autocomplete off is not offered.
 *
 * `onSaved` runs once the key is held, so the page can move focus to the chat. `disabled`
 * is true while a message is being read: the call under way keeps its key, so neither Save
 * nor Delete is offered until it ends.
 */
export function OwnKeyForm({
  copy,
  disabled,
  onSaved,
}: {
  copy: LLMOptCopy;
  disabled: boolean;
  onSaved?: () => void;
}) {
  const words = copy.ownKey;
  const held = useOwnKey();
  const id = useId();
  const keyField = useRef<HTMLInputElement>(null);
  const providerField = useRef<HTMLSelectElement>(null);
  // Delete replaces the held view, and with it the focused button: focus goes to the form.
  const focusForm = useRef(false);
  useEffect(() => {
    if (held || !focusForm.current) return;
    focusForm.current = false;
    providerField.current?.focus();
  }, [held]);
  const [provider, setProvider] = useState<OwnKeyProvider>("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [keyTyped, setKeyTyped] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const local = provider === "local";
  const ready =
    model.trim() !== "" && (local ? localBaseUrl(baseUrl) !== null : keyTyped) && !disabled;

  useEffect(() => {
    // An unsaved key is still in the DOM when the browser caches the departing document.
    function wipeOnPageHide() {
      if (keyField.current) keyField.current.value = "";
      setKeyTyped(false);
    }
    window.addEventListener("pagehide", wipeOnPageHide);
    return () => window.removeEventListener("pagehide", wipeOnPageHide);
  }, []);

  function wipeKeyField() {
    if (keyField.current) keyField.current.value = "";
    setKeyTyped(false);
  }

  function save() {
    if (!ready) return;
    const saved = setOwnKey({
      provider,
      model,
      key: keyField.current?.value ?? "",
      ...(local ? { baseUrl } : {}),
    });
    wipeKeyField();
    if (saved) setBaseUrl("");
    setInvalid(!saved);
    if (saved) onSaved?.();
  }

  function remove() {
    focusForm.current = held !== null;
    clearOwnKey();
    wipeKeyField();
    setInvalid(false);
  }

  function saveOnEnter(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter") return;
    event.preventDefault();
    save();
  }

  if (held)
    return (
      <div className={styles.ownKey} role="group" aria-labelledby={`${id}-title`}>
        <h2 id={`${id}-title`}>{words.title}</h2>
        <p className={styles.ownKeyHeld} role="status">
          <span>{words.providers[held.provider]}</span>
          <span>{held.model}</span>
        </p>
        <button className={styles.secondary} type="button" disabled={disabled} onClick={remove}>
          {words.delete}
        </button>
      </div>
    );

  return (
    <div className={styles.ownKey} role="group" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{words.title}</h2>
      <p className={styles.ownKeyNeeded}>{words.needed}</p>
      <label htmlFor={`${id}-provider`}>{words.provider}</label>
      <select
        id={`${id}-provider`}
        ref={providerField}
        value={provider}
        onChange={(event) => {
          setInvalid(false);
          if (isOwnKeyProvider(event.target.value)) setProvider(event.target.value);
        }}
      >
        {OWN_KEY_PROVIDERS.map((name) => (
          <option key={name} value={name}>
            {words.providers[name]}
          </option>
        ))}
      </select>
      <label htmlFor={`${id}-model`}>{words.model}</label>
      <input
        id={`${id}-model`}
        type="text"
        required
        value={model}
        placeholder={PROVIDERS[provider].modelExample}
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        maxLength={256}
        onChange={(event) => {
          setInvalid(false);
          setModel(event.target.value);
        }}
        onKeyDown={saveOnEnter}
      />
      <label htmlFor={`${id}-key`}>{words.key}</label>
      <input
        id={`${id}-key`}
        ref={keyField}
        className={styles.ownKeySecret}
        type="text"
        autoComplete="off"
        data-1p-ignore
        data-lpignore="true"
        data-bwignore="true"
        data-form-type="other"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        maxLength={1024}
        required={!local}
        onInput={(event) => {
          setInvalid(false);
          setKeyTyped(event.currentTarget.value.trim() !== "");
        }}
        onKeyDown={saveOnEnter}
      />
      {local && (
        <>
          <label htmlFor={`${id}-base`}>{words.baseUrl}</label>
          <input
            id={`${id}-base`}
            type="url"
            required
            value={baseUrl}
            placeholder="http://localhost:11434/v1"
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setInvalid(false);
              setBaseUrl(event.target.value);
            }}
            onKeyDown={saveOnEnter}
          />
        </>
      )}
      {invalid && (
        <p className={styles.ownKeyInvalid} role="status">
          {words.invalid}
        </p>
      )}
      <div className={styles.ownKeyActions}>
        <button className={styles.primary} type="button" disabled={!ready} onClick={save}>
          {words.save}
        </button>
        <button className={styles.secondary} type="button" disabled={!keyTyped} onClick={remove}>
          {words.delete}
        </button>
      </div>
    </div>
  );
}
