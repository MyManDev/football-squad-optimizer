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
- It refuses a host whose reading below is more than 90 days old, or undated, before any
  request to it, `robots.txt` included. See [When a reading ages](#when-a-reading-ages).
- It reads the host's `robots.txt` through the same reader as the document and refuses a
  disallowed path, recording that club as **not covered** rather than reading it anyway.
- It asks that question of the origin the registry names, so it **refuses a redirect that is
  answered by a different origin** rather than following it. One host's `robots.txt` is not
  the other's, and neither is the reading signed in the table below. The request has already
  gone by the time the serving host is known, so what the refusal buys is that the bytes are
  not read and the club is recorded as not covered; the fix is to register the origin that
  answers and sign its reading, after which there is no redirect left.
- It treats a `robots.txt` that cannot be read as an unanswered question, not as consent.
  "We could not ask" is not "they said yes".
- It sends one identity (`squadopt/1.0`) and reads registered paths, in the order the
  registry declares them; a club may have more than one.
- From a registered HTML page it follows **article links, and no others**: a link on the same
  origin, under the registered page's own path (`/news` leads to `/news/...`), in the order
  the page lists them, at most ten per host per run. Each article is asked of the same
  `robots.txt`, waits the same interval and meets the same refusals as a registered page,
  and is stored as its own document with its own readable text. A link to another host is
  never requested, an article's own links are not followed, and a feed's item links are not
  followed because the feed already carries the items' words. An article that fails costs
  that article: the club's coverage rests on its registered page.
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
| `www.newcastleunited.com` | [/en/terms](https://www.newcastleunited.com/en/terms) | The page lists twenty ticketing, hospitality, membership and competition documents and publishes no website terms of use. **No document there governs reading the site.** Silent, not permissive. | `robots.txt` read 2026-09-23 for `/en/news` and `squadopt/1.0`: allowed | İbrahim Ersan Özdemir | 2026-09-23 |
| `club.example` | — | Placeholder. Not a real host; the fixture serves it offline and no request is ever made. | not applicable | — | — |

**Newcastle is registered at the host that serves the bytes, and it was not at first.**
The first registration named `www.nufc.co.uk/news`, which **redirects** to
`www.newcastleunited.com/en/news`; `/en/terms` redirects the same way to the same document.
The first real run surfaced it, because the model cited the final URL and the capture's
`final_url` confirmed the redirect was the source rather than an invention.

That mattered for two reasons and only one of them is tidiness. A reading is a judgement
about a named host, and a row naming one host while another serves the content is a reading
of something nobody read. And the lane asks `robots.txt` of the **requested** origin, so a
cross-host redirect was being followed without the serving host's preference ever being
consulted. Both origins allow our path, so nothing was read against a refusal; the row now
names the origin that answers, and the robots gap is fixed separately.

**What these two rows are, exactly.** Neither club said yes. Each publishes a document
called terms and conditions which, read in full, is about tickets, and neither publishes
anything that governs reading the website. Proceeding on that is a decision the reader
takes and signs, which is what the name and date in the row are for, and it can be wrong
in two ways a later reading would catch: a governing document may exist somewhere neither
search reached, and a club can publish one tomorrow. That is why a row ages.

**Seventeen clubs are not here, and for three different reasons.** Eight publish terms
that restrict this directly, and they are not registered: Spurs (2.6.3 forbids extracting,
scraping and crawling; 2.6.4 forbids use to generate prompts) and Bournemouth (no "robot,
spider, or other automatic device") forbid the read itself; Leeds (6.5) forbids mass,
automated or systematic extraction; Arsenal, Brighton, Brentford, Man City and Man Utd
grant a licence limited to personal, non-commercial use. Eight could not be read at all:
Aston Villa, Coventry, Everton, Nott'm Forest, Sunderland, Fulham, Ipswich and
Chelsea serve their terms or policy pages client-side or publish none this reader could
locate, and **unread is not silent**. Hull City serves nothing this reader can reach.

**Brentford and Hull City were the two the survey left open, and both are now closed.**
Read 2026-09-24, with our own reader and our own identity.

Brentford moved from the second group to the first. Its `robots.txt` allows `/news` for
`squadopt/1.0`, and `/news` redirects within the same origin to `/en/news`, so the lane
would have been able to ask. The document the earlier survey could not locate is at
[`/en/terms-of-use`](https://www.brentfordfc.com/en/terms-of-use), and clause 8.2 settles
it before readability is reached:

> Permission is granted to You to view the Site Materials on a single personal computer or
> other device and to print a single hard copy of such Site Materials solely for personal,
> non-commercial use. [...] Any other use of materials on this Site [...]

That is the same licence Arsenal, Brighton, Man City and Man Utd grant, and it is the
reason those four are not registered either. Separately, and not the operative reason: its
news page yields 223 words and all of them are navigation, so it is a Crystal Palace case
underneath a Man City case.

Hull City is unreadable rather than absent, which is a different sentence from the one
this file used to carry. `hullcity.co.uk` does not resolve, which is what the earlier
survey met. Two hosts that do resolve do not answer: `www.hulltigers.com` returns HTTP 530
and `www.hullcityafc.com` times out. **We could not ask**, and that is not consent.

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
  Copy the date into the registry entry's `terms_read_on` for every page of that host.

## When a reading ages

**A reading is relied on for 90 days after the date in its row, and not after.** On day 91
the reader refuses the host before any request, `robots.txt` included, and records its club
as not covered with a refusal that names the reading's date and says what to do. The number
is `TERMS_READING_VALID_DAYS` in `src/squadopt/platform/club_news_fetch.py`; it is the
owner's to change and it is declared, not measured. It is short enough that a season sees
each host read three or four times, which is the point: the failure it guards against is a
club publishing website terms after our reading, and nothing tells us when that happens.

The rule reads a date, so the registry carries one. Every entry in
`data/sources/club_news_sources.json` names `terms_read_on`, the Date from the host's row
above, and `tests/unit/test_club_news_fetch.py` holds the two equal, so a row re-signed
here without the registry moving (or the other way round) fails before it reaches a run.
Every page of one host carries the same date, because a reading is of a host. The
placeholder carries `null`, because nobody read it, and an undated host is refused exactly
as a stale one is. A date more than a day after the fetch is refused too: it is a typo or a
wrong clock, and a typo in the year would stretch a permission by a year.

The reading covers the host, so it covers the article pages the reader follows there. The
`robots.txt` column above records the verdict for the registered path; each article's path
is asked of `robots.txt` again at run time, and a disallowed one is not requested.

**To renew a reading**, read the host's terms and `robots.txt` again as the row describes,
update the row's "What the terms say", verdict, "Read by" and "Date", and set the same date
as `terms_read_on` on every registry entry for that host, in one pull request. If the terms
now restrict automated reading, remove the entries instead. As of the rows above, Liverpool's
reading is relied on through 2026-12-21 and Newcastle's through 2026-12-22.

## What is deliberately not automated

Nobody's terms are parsed, scored or classified by this project. There is no attempt to
detect a licence from a page, and no default that treats an unreadable or missing terms
document as permissive. A host that has not been read is a host that is not fetched, and
that is the whole mechanism.
