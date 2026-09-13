# Club news sources: the terms reading

A page is registered in `data/sources/club_news_sources.json` only after somebody has read
that host's terms of use and its `robots.txt` and written down what they said, here. The
registry's `terms_record` field points at this file and the reader **refuses an entry
without it** — the registry is the record of what this project may read, so an entry with
no reading behind it would be a permission nobody granted.

This is a judgement, not a computation. The reading below is a person's, dated and signed,
and nothing in the code decides it. What the code does is narrower and worth stating so the
two are not confused:

- It refuses a URL that is not in the registry.
- It reads the host's `robots.txt` through the same reader as the document and refuses a
  disallowed path, recording that club as **not covered** rather than reading it anyway.
- It treats a `robots.txt` that cannot be read as an unanswered question, not as consent.
  "We could not ask" is not "they said yes".
- It sends one identity (`squadopt/1.0`), reads only registered paths — a club may have more
  than one, in the order the registry declares them — and follows no links.

None of that is a terms reading. A host can allow a crawler in `robots.txt` and forbid the
use in its terms, and the second is what the table below is for.

## Readings

No real host is registered yet. The row below is the shape.

| Host | Terms URL | What the terms say about automated reading | `robots.txt` verdict for our path | Read by | Date |
| --- | --- | --- | --- | --- | --- |
| `club.example` | — | Placeholder. Not a real host; the fixture serves it offline and no request is ever made. | not applicable | — | — |

### How to fill a row

- **What the terms say** — in the host's own terms, quoted or closely paraphrased, not
  summarised into "fine". If they are silent about automated access, write that they are
  silent; silence is not permission and it is not refusal either, and the decision to
  proceed on silence is the reader's to make and to sign.
- **`robots.txt` verdict** — for the exact path being registered, and for our user-agent.
  A host that allows `*` but disallows a path we want is a refusal for that path.
- **Read by / Date** — a name and a date, because a reading ages. A host can change its
  terms without telling anyone, and a row from last season is evidence about last season.

## What is deliberately not automated

Nobody's terms are parsed, scored or classified by this project. There is no attempt to
detect a licence from a page, and no default that treats an unreadable or missing terms
document as permissive. A host that has not been read is a host that is not fetched, and
that is the whole mechanism.
