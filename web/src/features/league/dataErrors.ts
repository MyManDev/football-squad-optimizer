export class LeagueDataError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LeagueDataError";
  }
}

/**
 * Raised when the document exists nowhere: the site publishes only the mode and window it
 * actually computed, so asking for another one is a normal outcome rather than a fault.
 */
export class LeagueDataMissing extends LeagueDataError {
  constructor(relative: string) {
    super(`No published league document at ${relative}.`);
    this.name = "LeagueDataMissing";
  }
}
