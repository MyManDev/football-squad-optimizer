// What an event may say. Every field but the session is a word from a closed list, and every
// number an integer in a fixed range, so these tests are also the privacy rule: an address, an
// entry number or a name is refused.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BLOB_COLUMNS,
  DEVICES,
  DWELLS,
  ERRORS,
  KINDS,
  KIND_LAYOUT,
  LANGUAGES,
  MARKS,
  MAX_BODY_BYTES,
  METRICS,
  PAGES,
  RATINGS,
  RefusedError,
  SOURCES,
  STEPS,
  TARGETS,
  TOOLS,
  VISITS,
  ZONES,
  dataPoint,
  eventFrom,
} from "../src/rules.js";
import { KIND_FIELDS, SESSION, goodBehaviour, goodEvent } from "./support.mjs";

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
    for (const v of [0, 3, "1", "2", 1.5, null, true]) refused(goodEvent({ v }), "wrong_version");
    const { v: _v, ...unversioned } = goodEvent();
    refused(unversioned, "wrong_version");
  });

  it("is refused under version 2's rules when it says version 2", () => {
    refused(goodEvent({ v: 2 }), "wrong_fields");
  });

  it("comes out with the same fields as before version 2", () => {
    assert.deepEqual(eventFrom(goodEvent()), {
      page: "member",
      tool: "what-if",
      step: "tool",
      lang: "tr",
      device: "phone",
      session: SESSION,
      v: 1,
    });
  });

  it("counts the constrained planner's page and tool", () => {
    assert.equal(eventFrom(goodEvent({ page: "llmopt", tool: "llmopt" })).page, "llmopt");
  });
});

// The fields of each version 2 kind that hold a word, and the list each word comes from.
const KIND_WORDS = {
  click: { zone: ZONES, target: TARGETS, mark: MARKS },
  scroll: { dwell: DWELLS },
  vital: { metric: METRICS, rating: RATINGS },
  error: { error: ERRORS },
  arrival: { source: SOURCES, visit: VISITS },
};

// The field of each version 2 kind that holds a number, with values it takes and refuses.
const KIND_NUMBERS = {
  click: {
    field: "cell",
    accepted: [0, 1, 20, 399],
    refused: [-1, 400, 1000, 1.5, 47.25, "47", null, true, [47], { cell: 47 }],
  },
  scroll: {
    field: "depth",
    accepted: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
    refused: [-10, 5, 55, 99, 110, 1000, 50.5, "60", null, false],
  },
  vital: {
    field: "value",
    accepted: [0, 1, 1840, 60000],
    refused: [-1, 60001, 1e9, 0.1, 2.5, "1840", null, true],
  },
};

// What a page must never manage to store, in any text field.
const PERSONAL = [
  "/league/352490/members/35249001",
  "https://squadopt.mymandev.com/league/352490",
  "35249001",
  "Ertuğrul",
  "Ertuğrul's XI",
  "utm_source=newsletter",
  "TypeError: x is undefined",
  "DECISION",
  " decision",
  35249001,
  null,
  true,
  ["decision"],
];

describe("a version 2 event", () => {
  it("names exactly the kinds and words ADR 0015 lists", () => {
    const sorted = (set) => [...set].sort();
    assert.deepEqual(sorted(KINDS), ["arrival", "click", "error", "scroll", "vital"]);
    assert.equal(ZONES.size, 44);
    for (const zone of ["nav", "decision", "pitch", "member-picker", "llmopt", "contribute", "page"]) assert.ok(ZONES.has(zone));
    // Added on 2026-11-23 for smaller boxes; the words they replaced stay readable above.
    for (const zone of [
      "nav-brand", "nav-member", "nav-links", "nav-settings", "phone-bar",
      "llmopt-model", "llmopt-instructions", "llmopt-rule-list", "llmopt-rules", "llmopt-plan", "llmopt-compute", "llmopt-results",
    ]) assert.ok(ZONES.has(zone), zone);
    assert.deepEqual(sorted(TARGETS), ["control", "plain"]);
    assert.deepEqual(sorted(MARKS), ["dead", "none", "rage"]);
    assert.deepEqual(sorted(DWELLS), ["long", "s15", "s180", "s30", "s5", "s60", "s600"]);
    assert.deepEqual(sorted(METRICS), ["cls", "fcp", "inp", "lcp", "ttfb"]);
    assert.deepEqual(sorted(RATINGS), ["good", "needs", "poor"]);
    assert.deepEqual(sorted(ERRORS), ["chunk", "promise", "script"]);
    assert.deepEqual(sorted(SOURCES), [
      "bing", "direct", "facebook", "fpl", "google", "instagram", "internal", "other", "reddit", "telegram", "whatsapp", "x",
    ]);
    assert.deepEqual(sorted(VISITS), ["last_week", "new", "older", "same_week", "unknown", "weeks_2_4"]);
    assert.deepEqual(Object.keys(KIND_LAYOUT).sort(), sorted(KINDS));
  });

  it("is accepted for every kind with every word of every common list", () => {
    const lists = { page: PAGES, tool: TOOLS, lang: LANGUAGES, device: DEVICES };
    for (const kind of KINDS) {
      for (const [field, words] of Object.entries(lists)) {
        for (const value of words) {
          assert.equal(eventFrom(goodBehaviour(kind, { [field]: value }))[field], value, `${kind} ${field}`);
        }
      }
    }
  });

  it("is accepted with every word of its kind's lists", () => {
    for (const [kind, fields] of Object.entries(KIND_WORDS)) {
      for (const [field, words] of Object.entries(fields)) {
        for (const value of words) {
          assert.equal(eventFrom(goodBehaviour(kind, { [field]: value }))[field], value, `${kind} ${field}`);
        }
      }
    }
  });

  it("comes out as the common fields and its kind's, and nothing else", () => {
    for (const kind of KINDS) {
      const event = eventFrom(goodBehaviour(kind));
      assert.deepEqual(event, {
        page: "member",
        tool: "what-if",
        kind,
        lang: "tr",
        device: "phone",
        session: SESSION,
        v: 2,
        ...KIND_FIELDS[kind],
      });
      assert.equal("step" in event, false);
    }
  });

  it("refuses a kind it does not know, and a body with no kind", () => {
    for (const kind of ["", "pageview", "Click", "heatmap", 1, null, true]) {
      refused(goodBehaviour("click", { kind }), "kind_refused");
    }
    const { kind: _kind, ...kindless } = goodBehaviour("click");
    refused(kindless, "wrong_fields");
  });

  it("refuses a missing field, an extra one and another kind's, for every kind", () => {
    const common = ["page", "tool", "lang", "device", "session"];
    for (const kind of KINDS) {
      for (const field of [...common, ...Object.keys(KIND_FIELDS[kind])]) {
        const { [field]: _gone, ...missing } = goodBehaviour(kind);
        refused(missing, "wrong_fields");
      }
      const extras = [{ step: "tool" }, { x: 120, y: 340 }, { message: "boom" }, { referrer: "https://t.co/" }, { entry_id: 35249001 }];
      for (const extra of extras) refused(goodBehaviour(kind, extra), "wrong_fields");
      for (const other of KINDS) {
        if (other === kind) continue;
        refused(goodBehaviour(kind, KIND_FIELDS[other]), "wrong_fields");
        // A kind's name over another kind's fields is wrong too.
        refused({ ...goodBehaviour(other), kind }, "wrong_fields");
      }
    }
  });

  it("refuses an address, an entry number and a name in every text field of every kind", () => {
    for (const kind of KINDS) {
      const fields = ["page", "tool", "lang", "device", ...Object.keys(KIND_WORDS[kind])];
      for (const field of fields) {
        for (const value of PERSONAL) refused(goodBehaviour(kind, { [field]: value }), `${field}_refused`);
      }
      for (const value of PERSONAL) refused(goodBehaviour(kind, { kind: value }), "kind_refused");
      for (const session of ["", "352490", `${SESSION}00`, "ABCDEF0123456789", 7]) {
        refused(goodBehaviour(kind, { session }), "session_refused");
      }
    }
  });

  it("refuses a word from another field's list", () => {
    refused(goodBehaviour("click", { zone: "rage" }), "zone_refused");
    refused(goodBehaviour("click", { target: "button" }), "target_refused");
    refused(goodBehaviour("click", { mark: "control" }), "mark_refused");
    refused(goodBehaviour("scroll", { dwell: "s10" }), "dwell_refused");
    refused(goodBehaviour("vital", { metric: "fid" }), "metric_refused");
    refused(goodBehaviour("vital", { rating: "lcp" }), "rating_refused");
    refused(goodBehaviour("error", { error: "network" }), "error_refused");
    refused(goodBehaviour("arrival", { source: "new" }), "source_refused");
    refused(goodBehaviour("arrival", { visit: "google" }), "visit_refused");
  });

  it("takes only integers in range, on their step, as numbers", () => {
    for (const [kind, { field, accepted, refused: wrong }] of Object.entries(KIND_NUMBERS)) {
      for (const value of accepted) assert.equal(eventFrom(goodBehaviour(kind, { [field]: value }))[field], value);
      for (const value of wrong) refused(goodBehaviour(kind, { [field]: value }), `${field}_refused`);
    }
  });

  it("fits the largest event of every kind under the size cap", () => {
    const longest = (set) => [...set].sort((a, b) => b.length - a.length)[0];
    const big = {
      click: { zone: longest(ZONES), cell: 399, target: longest(TARGETS), mark: longest(MARKS) },
      scroll: { depth: 100, dwell: longest(DWELLS) },
      vital: { metric: longest(METRICS), rating: longest(RATINGS), value: 60000 },
      error: { error: longest(ERRORS) },
      arrival: { source: longest(SOURCES), visit: longest(VISITS) },
    };
    for (const kind of KINDS) {
      const body = goodBehaviour(kind, { page: longest(PAGES), tool: longest(TOOLS), device: longest(DEVICES), ...big[kind] });
      eventFrom(body);
      assert.ok(new TextEncoder().encode(JSON.stringify(body)).length < MAX_BODY_BYTES, kind);
    }
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

  it("keeps version 1's six text columns and one number, with no padding", () => {
    const point = dataPoint(eventFrom(goodEvent({ page: "llmopt", tool: "llmopt", step: "open" })));
    assert.equal(
      JSON.stringify(point),
      `{"indexes":["${SESSION}"],"blobs":["llmopt","llmopt","open","tr","phone","${SESSION}"],"doubles":[1]}`,
    );
  });

  it("puts each version 2 kind's fields in the columns ADR 0015 names", () => {
    const head = ["member", "what-if"];
    const tail = ["tr", "phone", SESSION];
    const expected = {
      click: { blobs: [...head, "click", ...tail, "decision", "control", "none"], doubles: [2, 47] },
      scroll: { blobs: [...head, "scroll", ...tail, "s30", "", ""], doubles: [2, 60] },
      vital: { blobs: [...head, "vital", ...tail, "lcp", "good", ""], doubles: [2, 1840] },
      error: { blobs: [...head, "error", ...tail, "chunk", "", ""], doubles: [2, 0] },
      arrival: { blobs: [...head, "arrival", ...tail, "whatsapp", "last_week", ""], doubles: [2, 0] },
    };
    for (const kind of KINDS) {
      assert.deepEqual(dataPoint(eventFrom(goodBehaviour(kind))), { indexes: [SESSION], ...expected[kind] }, kind);
    }
  });

  it("keeps a click in the first cell and a burst's mark", () => {
    const point = dataPoint(eventFrom(goodBehaviour("click", { cell: 0, mark: "rage", zone: "page", target: "plain" })));
    assert.deepEqual(point.doubles, [2, 0]);
    assert.deepEqual(point.blobs.slice(6), ["page", "plain", "rage"]);
  });
});
