// What an event may say. Every field but the session is a word from a closed list, so these
// tests are also the privacy rule: an address, an entry number or a name is refused.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BLOB_COLUMNS,
  DEVICES,
  LANGUAGES,
  PAGES,
  RefusedError,
  STEPS,
  TOOLS,
  dataPoint,
  eventFrom,
} from "../src/rules.js";
import { SESSION, goodEvent } from "./support.mjs";

const refused = (body, reason) =>
  assert.throws(
    () => eventFrom(body),
    (error) => error instanceof RefusedError && error.reason === reason,
  );

describe("an event", () => {
  it("is accepted with every word of every list", () => {
    const lists = { page: PAGES, tool: TOOLS, step: STEPS, lang: LANGUAGES, device: DEVICES };
    for (const [field, words] of Object.entries(lists)) {
      for (const value of words) {
        assert.equal(eventFrom(goodEvent({ [field]: value }))[field], value);
      }
    }
  });

  it("names the questions the record has to answer", () => {
    for (const tool of ["what-if", "duel", "chips", "card", "history", "live", "fixtures"]) assert.ok(TOOLS.has(tool));
    for (const step of ["open", "tool", "picker_shown", "picker_claimed", "device_solve"]) assert.ok(STEPS.has(step));
    assert.deepEqual([...DEVICES].sort(), ["desktop", "phone", "tablet", "unknown"]);
  });

  it("refuses anything that is not a plain object", () => {
    for (const body of [null, [], "text", 7]) refused(body, "body_not_object");
  });

  it("refuses a missing field and an extra one", () => {
    const { tool: _tool, ...missing } = goodEvent();
    refused(missing, "wrong_fields");
    refused(goodEvent({ entry_id: 35249001 }), "wrong_fields");
  });

  it("refuses an address, an entry number and a name in place of a word", () => {
    refused(goodEvent({ page: "/league/352490/members/35249001" }), "page_refused");
    refused(goodEvent({ tool: "35249001" }), "tool_refused");
    refused(goodEvent({ step: "Ertuğrul" }), "step_refused");
    refused(goodEvent({ lang: "de" }), "lang_refused");
    refused(goodEvent({ device: "iPhone 15" }), "device_refused");
    refused(goodEvent({ page: 7 }), "page_refused");
  });

  it("refuses a session that is not the random token's shape, and another version", () => {
    for (const session of ["", "short", "352490", `${SESSION}00`, "ABCDEF0123456789", 7]) {
      refused(goodEvent({ session }), "session_refused");
    }
    for (const v of [0, 2, "1", null]) refused(goodEvent({ v }), "wrong_version");
  });
});

describe("the data point", () => {
  it("holds the session as the index and the fields in the columns the report reads", () => {
    const event = eventFrom(goodEvent());
    assert.deepEqual(dataPoint(event), {
      indexes: [SESSION],
      blobs: ["member", "what-if", "tool", "tr", "phone", SESSION],
      doubles: [1],
    });
    assert.deepEqual(BLOB_COLUMNS, ["page", "tool", "step", "lang", "device", "session"]);
  });
});
