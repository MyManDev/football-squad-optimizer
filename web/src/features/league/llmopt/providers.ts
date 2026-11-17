import {
  discardBody,
  isAbortError,
  isTimeoutError,
  withRequestDeadline,
} from "../../../data/request";
import { IntentError } from "./intent";
import type { OwnKeyProvider, ProviderCredential } from "./ownKey";

/** One model call in provider-neutral form, as `POST /api/v1/llmopt/prompt` returns it. */
export interface ProviderCall {
  system: string;
  user: string;
  schema: Record<string, unknown>;
  schema_name: string;
  max_output_tokens: number;
}

type Family = "chat" | "anthropic";

interface ProviderSpec {
  family: Family;
  /** The provider's own endpoint; null for a local server, whose base the member gives. */
  endpoint: string | null;
  /** The name the endpoint takes for the reply's token limit. */
  tokens: "max_completion_tokens" | "max_tokens";
  /** `json_schema` with strict checking, or `json_object` with the schema in the prompt. */
  output: "json_schema" | "json_object" | "tool";
  /** A model id in the provider's own format, shown as the field's placeholder. */
  modelExample: string;
}

/**
 * The providers a member can bring a key for. Every host here is in the site's `connect-src`;
 * a provider outside the list is added by a reviewed change.
 */
export const PROVIDERS: Readonly<Record<OwnKeyProvider, ProviderSpec>> = {
  openai: {
    family: "chat",
    endpoint: "https://api.openai.com/v1/chat/completions",
    tokens: "max_completion_tokens",
    output: "json_schema",
    modelExample: "gpt-5-mini",
  },
  anthropic: {
    family: "anthropic",
    endpoint: "https://api.anthropic.com/v1/messages",
    tokens: "max_tokens",
    output: "tool",
    modelExample: "claude-haiku-5-5",
  },
  gemini: {
    family: "chat",
    endpoint: "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    tokens: "max_completion_tokens",
    output: "json_schema",
    modelExample: "gemini-flash-latest",
  },
  openrouter: {
    family: "chat",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    tokens: "max_tokens",
    output: "json_schema",
    modelExample: "openai/gpt-5-mini",
  },
  mistral: {
    family: "chat",
    endpoint: "https://api.mistral.ai/v1/chat/completions",
    tokens: "max_tokens",
    output: "json_schema",
    modelExample: "mistral-small-latest",
  },
  groq: {
    family: "chat",
    endpoint: "https://api.groq.com/openai/v1/chat/completions",
    tokens: "max_completion_tokens",
    output: "json_schema",
    modelExample: "openai/gpt-oss-20b",
  },
  deepseek: {
    family: "chat",
    endpoint: "https://api.deepseek.com/chat/completions",
    tokens: "max_tokens",
    output: "json_object",
    modelExample: "deepseek-chat",
  },
  local: {
    family: "chat",
    endpoint: null,
    tokens: "max_tokens",
    output: "json_schema",
    modelExample: "llama3.1",
  },
};

export const ANTHROPIC_VERSION = "2023-06-01";
/**
 * The reply limit a chat-completions provider is given. A reasoning model counts its
 * thinking against the limit, so the answer's own size (`max_output_tokens`) would stop such
 * a model before it wrote anything. The answer stays as short; this is only room to think.
 */
export const CHAT_REPLY_TOKENS = 8192;
const PROVIDER_TIMEOUT_MS = 60_000;
const MAX_RETRY_AFTER_SECONDS = 86_400;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function refusal(code: string, status = 0, retryAfterSeconds: number | null = null) {
  return new IntentError(status, code, retryAfterSeconds);
}

/** The system text for a provider that takes only `json_object`: the schema goes in it. */
function withSchemaInText(call: ProviderCall) {
  return `${call.system}\n\nReply with one JSON object that matches this JSON schema:\n${JSON.stringify(call.schema)}`;
}

function endpointFor(credential: ProviderCredential): string {
  const spec = PROVIDERS[credential.provider];
  if (spec.endpoint) return spec.endpoint;
  if (!credential.baseUrl) throw refusal("PROVIDER_UNREACHABLE");
  return `${credential.baseUrl}/chat/completions`;
}

/** The provider request for a neutral call: where it goes, its headers and its body. */
export function providerRequest(
  credential: ProviderCredential,
  call: ProviderCall,
): { url: string; headers: Record<string, string>; body: Record<string, unknown> } {
  const spec = PROVIDERS[credential.provider];
  const url = endpointFor(credential);
  if (spec.family === "anthropic")
    return {
      url,
      headers: {
        "Content-Type": "application/json",
        "x-api-key": credential.key,
        "anthropic-version": ANTHROPIC_VERSION,
        "anthropic-dangerous-direct-browser-access": "true",
      },
      body: {
        model: credential.model,
        max_tokens: call.max_output_tokens,
        system: call.system,
        messages: [{ role: "user", content: call.user }],
        tools: [{ name: call.schema_name, input_schema: call.schema }],
        tool_choice: { type: "tool", name: call.schema_name },
      },
    };
  const jsonObject = spec.output === "json_object";
  return {
    url,
    headers: {
      "Content-Type": "application/json",
      // A local server may run without a key.
      ...(credential.key ? { Authorization: `Bearer ${credential.key}` } : {}),
    },
    body: {
      model: credential.model,
      [spec.tokens]: Math.max(call.max_output_tokens, CHAT_REPLY_TOKENS),
      ...(credential.provider === "openai" ? { store: false } : {}),
      ...(credential.provider === "openrouter" ? { provider: { require_parameters: true } } : {}),
      messages: [
        { role: "system", content: jsonObject ? withSchemaInText(call) : call.system },
        { role: "user", content: call.user },
      ],
      response_format: jsonObject
        ? { type: "json_object" }
        : {
            type: "json_schema",
            json_schema: { name: call.schema_name, strict: true, schema: call.schema },
          },
    },
  };
}

/**
 * The model's answer in a provider's reply: the JSON text of a chat completion, or the input
 * of Anthropic's forced tool. A reply without one rejects as an invalid reply.
 */
export function providerReply(provider: OwnKeyProvider, call: ProviderCall, value: unknown) {
  if (!record(value)) throw refusal("PROVIDER_REPLY_INVALID");
  if (PROVIDERS[provider].family === "anthropic") {
    const content = value.content;
    const tool = Array.isArray(content)
      ? content.find(
          (block: unknown) =>
            record(block) && block.type === "tool_use" && block.name === call.schema_name,
        )
      : undefined;
    if (value.stop_reason === "max_tokens") throw refusal("PROVIDER_REPLY_CUT");
    if (!record(tool) || !record(tool.input)) throw refusal("PROVIDER_REPLY_INVALID");
    return tool.input;
  }
  const choices = value.choices;
  const choice: unknown = Array.isArray(choices) ? choices[0] : undefined;
  if (!record(choice) || !record(choice.message)) throw refusal("PROVIDER_REPLY_INVALID");
  const finish = choice.finish_reason;
  const { content, refusal: declined } = choice.message;
  // The model ran into the reply limit, usually while still thinking.
  if (finish === "length") throw refusal("PROVIDER_REPLY_CUT");
  if (
    (finish !== undefined && finish !== null && finish !== "stop") ||
    (declined !== undefined && declined !== null) ||
    typeof content !== "string" ||
    !content.trim()
  )
    throw refusal("PROVIDER_REPLY_INVALID");
  return content;
}

/** `Retry-After` in whole seconds, from a count or an HTTP date; null when absent. */
export function retryAfterSeconds(header: string | null, now = Date.now()): number | null {
  const value = header?.trim() ?? "";
  if (!value) return null;
  const seconds = /^\d{1,10}$/.test(value)
    ? Number(value)
    : Math.ceil((Date.parse(value) - now) / 1000);
  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  return Math.min(seconds, MAX_RETRY_AFTER_SECONDS);
}

/**
 * The words of a provider's error: its code, type, status, reason and message. Nothing of
 * the body is kept, since a provider can repeat part of a key in it.
 */
async function errorWords(response: Response): Promise<(pattern: RegExp) => boolean> {
  let fields: unknown[] = [];
  try {
    const parsed: unknown = await response.json();
    // Gemini wraps its error in a one-item list; Mistral puts the fields at the top.
    const value: unknown = Array.isArray(parsed) ? parsed[0] : parsed;
    const error = record(value) ? value.error : undefined;
    const details = record(error) && Array.isArray(error.details) ? error.details : [];
    fields = [value, error, ...details]
      .filter(record)
      .flatMap((item) => [item.code, item.type, item.status, item.reason, item.message]);
  } catch {
    fields = [];
  }
  return (pattern: RegExp) =>
    fields.some((field) => typeof field === "string" && pattern.test(field));
}

/** An account with no credit or plan left: waiting does not help, so it is no rate limit. */
const NO_CREDIT = /insufficient[ _-]?(quota|balance)|credit balance/i;

/**
 * What a 400 or 422 refused: the key (Gemini answers a bad key with 400), the account
 * (Anthropic answers an empty balance with 400), the model, or the request.
 */
async function badRequestCode(response: Response): Promise<string> {
  const said = await errorWords(response);
  if (said(/api[ _-]?key/i)) return "PROVIDER_KEY_REFUSED";
  if (said(NO_CREDIT)) return "PROVIDER_ACCOUNT_REFUSED";
  if (said(/model/i)) return "PROVIDER_MODEL_REFUSED";
  return "PROVIDER_REFUSED";
}

/** The refusal a provider's failed response is read as. */
export async function providerError(response: Response): Promise<IntentError> {
  const { status } = response;
  if (status === 401 || status === 403) {
    await discardBody(response);
    return refusal("PROVIDER_KEY_REFUSED", status);
  }
  if (status === 402) {
    await discardBody(response);
    return refusal("PROVIDER_ACCOUNT_REFUSED", status);
  }
  if (status === 429) {
    // OpenAI answers a key with no credit with 429 too; only a real limit has a wait.
    if ((await errorWords(response))(NO_CREDIT)) return refusal("PROVIDER_ACCOUNT_REFUSED", status);
    return refusal(
      "PROVIDER_RATE_LIMITED",
      status,
      retryAfterSeconds(response.headers.get("Retry-After")),
    );
  }
  if (status === 404) {
    await discardBody(response);
    return refusal("PROVIDER_MODEL_REFUSED", status);
  }
  if (status === 400 || status === 422) return refusal(await badRequestCode(response), status);
  await discardBody(response);
  return refusal("PROVIDER_UNAVAILABLE", status);
}

/**
 * Sends the call to the member's provider, straight from this browser, and returns the
 * model's answer. Cancellation rejects as it came; a network or CORS failure rejects as the
 * provider being unreachable.
 */
export function callProvider(
  credential: ProviderCredential,
  call: ProviderCall,
  signal: AbortSignal,
): Promise<unknown> {
  return withRequestDeadline(
    async (signal) => {
      const { url, headers, body } = providerRequest(credential, call);
      let response: Response;
      try {
        response = await fetch(url, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
          credentials: "omit",
          referrerPolicy: "no-referrer",
          cache: "no-store",
          signal,
        });
      } catch (error) {
        if (isAbortError(error) || isTimeoutError(error) || signal.aborted) throw error;
        throw refusal("PROVIDER_UNREACHABLE");
      }
      if (!response.ok) throw await providerError(response);
      let value: unknown;
      try {
        value = await response.json();
      } catch (error) {
        if (signal.aborted) throw error;
        throw refusal("PROVIDER_REPLY_INVALID");
      }
      return providerReply(credential.provider, call, value);
    },
    { signal, timeoutMs: PROVIDER_TIMEOUT_MS },
  ).catch((error: unknown) => {
    // The provider's own deadline passed, not the page's.
    if (isTimeoutError(error) && !signal.aborted) throw refusal("PROVIDER_UNAVAILABLE");
    throw error;
  });
}

/** The neutral call `/prompt` returned, checked before any of it goes to a provider. */
export function checkedProviderCall(value: unknown): ProviderCall {
  if (
    !record(value) ||
    typeof value.system !== "string" ||
    typeof value.user !== "string" ||
    !record(value.schema) ||
    typeof value.schema_name !== "string" ||
    !/^[A-Za-z0-9_-]{1,64}$/.test(value.schema_name) ||
    typeof value.max_output_tokens !== "number" ||
    !Number.isInteger(value.max_output_tokens) ||
    value.max_output_tokens < 1 ||
    value.max_output_tokens > 65_536
  )
    throw new Error("Invalid prompt");
  return {
    system: value.system,
    user: value.user,
    schema: value.schema,
    schema_name: value.schema_name,
    max_output_tokens: value.max_output_tokens,
  };
}
