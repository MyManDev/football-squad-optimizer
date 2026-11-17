import { intentAnswer, intentError, type CatalogPlayer } from "../features/league/llmopt/intent";

/**
 * What the page makes of a response from the site's keyless LLMOPT routes: the checked
 * answer, or the named refusal.
 */
export async function readReply(response: Response, players: readonly CatalogPlayer[]) {
  if (!response.ok) throw await intentError(response);
  return intentAnswer(await response.json(), players);
}
