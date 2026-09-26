/**
 * The envelope every published view arrives in, and the error for one this build does not
 * read. The site client and the live score reader both check it, so it lives beside them
 * rather than in either: neither has to import the other.
 */

export interface ViewEnvelope<T> {
  contract_version: string;
  generated_at_utc: string;
  payload: T;
}

export interface Loaded<T> {
  payload: T;
  generatedAtUtc: string;
}

export class ContractMismatchError extends Error {
  readonly found: string;
  readonly expected: string;
  constructor(found: string, expected: string) {
    super(`This page was built for ${expected}; the data says ${found}.`);
    this.name = "ContractMismatchError";
    this.found = found;
    this.expected = expected;
  }
}
