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
- It asks a host for its `robots.txt` **once per run**, however many registered paths that
  host serves, and decides each path against the one file it read. One club with three pages
  is one question, not three.
- It waits a declared interval before any second request to a host it has already contacted
  this run. The debt is per host, so an unrelated club on another host does not wait.

None of that is a terms reading. A host can allow a crawler in `robots.txt` and forbid the
use in its terms, and the second is what the table below is for.

## Readings

Two real hosts are registered. Both were read on the date in their row, with our own
reader and our own identity, and both readings are of a **silence** rather than of a
permission: see the note under the table for what that means and what it does not.

| Host | Terms URL | What the terms say about automated reading | `robots.txt` verdict for our path | Read by | Date |
| --- | --- | --- | --- | --- | --- |
| `www.liverpoolfc.com` | [/legal/terms-and-conditions](https://www.liverpoolfc.com/legal/terms-and-conditions) | The page is a ticketing and membership document. Read in full, 276 lines, its only restriction of this kind is 8.5, on reselling tickets "without the prior written consent of the Club". **It says nothing about reading the website, automated access, reproduction or publication.** Silent, not permissive. | `robots.txt` read 2026-09-22 for `/news` and `squadopt/1.0`: allowed | İbrahim Ersan Özdemir | 2026-09-22 |
| `www.nufc.co.uk` | [/en/terms](https://www.nufc.co.uk/en/terms) | The page lists twenty ticketing, hospitality, membership and competition documents and publishes no website terms of use. **No document there governs reading the site.** Silent, not permissive. | `robots.txt` read 2026-09-22 for `/news` and `squadopt/1.0`: allowed | İbrahim Ersan Özdemir | 2026-09-22 |
| `club.example` | — | Placeholder. Not a real host; the fixture serves it offline and no request is ever made. | not applicable | — | — |

**What these two rows are, exactly.** Neither club said yes. Each publishes a document
called terms and conditions which, read in full, is about tickets, and neither publishes
anything that governs reading the website. Proceeding on that is a decision the reader
takes and signs, which is what the name and date in the row are for, and it can be wrong
in two ways a later reading would catch: a governing document may exist somewhere neither
search reached, and a club can publish one tomorrow. That is why a row ages.

**Seventeen clubs are not here, and for three different reasons.** Seven publish terms
that restrict this directly, and they are not registered: Spurs (2.6.3 forbids extracting,
scraping and crawling; 2.6.4 forbids use to generate prompts) and Bournemouth (no "robot,
spider, or other automatic device") forbid the read itself; Leeds (6.5) forbids mass,
automated or systematic extraction; Arsenal, Brighton, Man City and Man Utd grant a
licence limited to personal, non-commercial use. Nine could not be read at all: Aston
Villa, Coventry, Everton, Nott'm Forest, Sunderland, Brentford, Fulham, Ipswich and
Chelsea serve their terms or policy pages client-side or publish none this reader could
locate, and **unread is not silent**. Hull City's host did not resolve.

**Crystal Palace was read, considered and rejected on a different ground.** Its
`robots.txt` allows our path, it publishes an RSS feed, and no terms document could be
found anywhere on it. But its news page serves markup and no readable text, so
`fetch_club_document` refuses it. A host this lane cannot read is not a host, whatever its
terms say.

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
