import { useId, useRef, useState, type KeyboardEvent } from "react";

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
 * There is no form element, so a browser has no submission to offer to save as a password.
 */
export function OwnKeyForm({ copy, disabled }: { copy: LLMOptCopy; disabled: boolean }) {
  const words = copy.ownKey;
  const held = useOwnKey();
  const id = useId();
  const keyField = useRef<HTMLInputElement>(null);
  const [provider, setProvider] = useState<OwnKeyProvider>("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [keyTyped, setKeyTyped] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const local = provider === "local";
  const ready =
    model.trim() !== "" && (local ? localBaseUrl(baseUrl) !== null : keyTyped) && !disabled;

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
  }

  function remove() {
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
      <div className={styles.ownKey} role="group" aria-label={words.title}>
        <p className={styles.ownKeyHeld}>
          <span>{words.providers[held.provider]}</span>
          <span>{held.model}</span>
        </p>
        <button className={styles.secondary} type="button" onClick={remove}>
          {words.delete}
        </button>
      </div>
    );

  return (
    <div className={styles.ownKey} role="group" aria-label={words.title}>
      <label htmlFor={`${id}-provider`}>{words.provider}</label>
      <select
        id={`${id}-provider`}
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
        type="password"
        autoComplete="off"
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
        <button className={styles.secondary} type="button" onClick={remove}>
          {words.delete}
        </button>
      </div>
    </div>
  );
}
