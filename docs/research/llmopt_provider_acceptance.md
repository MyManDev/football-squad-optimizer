# LLMOPT provider acceptance checklist

**Owner check.** Use an existing LLMOPT acceptance session where plan conversation
is available and two distinct, current plans are already displayed. Identify each
plan by a visible transfer or captain and note its displayed points. Missing setup,
credentials or model access leaves that row **not run**.

1. Under **Your model**, choose the provider and enter an eligible model ID. Enter
   your existing key only in the **API key** field and choose **Save**. The saved
   form shows the provider and model. For **Local**, use your existing
   OpenAI-compatible HTTP endpoint on `localhost` or `127.0.0.1` with an explicit
   port and its API base path. The key is optional if that server accepts anonymous calls.
2. Use the plan card buttons to select the opposite plan as a starting point for
   each row. Type the row's message and press **Send** once. Check which card is
   selected, its distinguishing decision and its original points. Selection should
   take effect without another calculation. Use **Delete** to clear the held
   credential before changing providers and after the final row.
3. Record only the provider, model ID, pass/fail/not run and a short description
   of any page error. Keep keys, request headers, request or response bodies and
   logs out of the record.

| Provider | Send once | Expected selected card | Failure to watch for |
| --- | --- | --- | --- |
| OpenAI | Use the second plan. | Second, `P2` | Request or model refused on the strict JSON schema. |
| Anthropic | Use the first plan. | First, `P1` | An unreadable answer if the model omits the requested tool or returns invalid tool input. |
| Google Gemini | Use the second plan. | Second, `P2` | Key or model refused by the chat-completions endpoint. |
| OpenRouter | Use the first plan. | First, `P1` | Model or request refused if a route cannot honor the required structured-output parameters. |
| Mistral | Use the second plan. | Second, `P2` | The model refuses the schema or the page rejects the returned selection. |
| Groq | Use the first plan. | First, `P1` | A rate-limit message or a reply that stops before the selection is complete. |
| DeepSeek | Use the second plan. | Second, `P2` | Unreadable answer if JSON-object mode returns an invalid command or an unknown plan label. |
| Local | Use the first plan. | First, `P1` | Unreachable endpoint, unsupported strict schema or unreadable completion. |

The browser obtains the schema from `/api/v1/llmopt/prompt`, calls the chosen
provider once, then submits the reply to `/api/v1/llmopt/check`. The two app
routes are keyless. The provider returns the displayed plan's short label. The
page checks the resolved identity against the current catalogue before selecting
the card. A wrong card, a changed score or an invented label counts as a failure
even if the chat acknowledges the instruction.
[Provider adapters](../../web/src/features/league/llmopt/providers.ts) ·
[Chat request flow](../../web/src/features/league/llmopt/intentSource.ts) ·
[Plan-label contract](../contracts/llmopt_plans_v1.md)
