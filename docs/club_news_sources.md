# Club news sources: the terms reading

A page is registered in `data/sources/club_news_sources.json` only after somebody has read
that host's terms of use and its `robots.txt` and written down what they said, here. The
registry's `terms_record` field points at this file and the reader **refuses an entry
without it** — the registry is the record of what this project may read, so an entry with
no reading behind it would be a permission nobody granted.

Source activation is an owner decision, not a computation. Each reading has a dated
review record below. The Palace follow-up records the inspected evidence separately from
the owner's approval to activate it; it does not claim that the owner personally read the
terms. What the code does is narrower:

- It never contacts a host that is not in the registry, by a link or by a redirect. On a
  registered host it requests the host's `robots.txt`, the registered pages, the article
  links described below and the same-origin addresses those redirect to, and nothing else.
- It refuses a host whose reading below is more than 90 days old, or undated, before any
  request to it, `robots.txt` included. See [When a reading ages](#when-a-reading-ages).
- It reads the host's `robots.txt` through the same reader as the document and refuses a
  disallowed path, recording that club as **not covered** rather than reading it anyway.
- It asks that question of the origin the registry names, so it **refuses a redirect to a
  different origin before following it**: the other host is sent no request, and the page is
  recorded as not read (for a registered page, its club as not covered). One host's
  `robots.txt` is not the other's, and neither is the reading signed in the table below. A
  redirect within the same scheme, host and port is followed. A `robots.txt` that redirects to
  another origin counts as one that could not be read, so that host is refused. The fix is to
  register the origin that answers and sign its reading, after which there is no redirect left.
- It treats a `robots.txt` that cannot be read as an unanswered question, not as consent.
  "We could not ask" is not "they said yes".
- It sends one identity (`squadopt/1.0`) and reads registered paths, in the order the
  registry declares them; a club may have more than one.
- From a registered HTML page it follows **article links, and no others**: a link on the same
  origin, under the registered page's own path (`/news` leads to `/news/...`), in the order
  the page lists them, at most ten per host per run. The path is the registered one even when
  a same-origin redirect served the page somewhere else, so a page that is served at another
  path should be registered where it is served. A link whose printed or resolved path has a
  `.` or `..` segment, written out or percent-encoded, is skipped rather than resolved. Each
  article is asked of the same `robots.txt`, waits the same interval and meets the same
  refusals as a registered page, and is stored as its own document with its own readable
  text. A link to another host is never requested, an article's own links are not followed,
  and a feed's item links are not followed because the feed already carries the items'
  words. An article that fails costs that article: the club's coverage rests on its
  registered page.
- It asks a host for its `robots.txt` **once per run**, however many registered paths that
  host serves, and decides each path against the one file it read. One club with three pages
  is one question, not three.
- It waits a declared interval before any second request to a host it has already contacted
  this run. The debt is per host, so an unrelated club on another host does not wait.

None of that is a terms reading. A host can allow a crawler in `robots.txt` and forbid the
use in its terms, and the second is what the table below is for.

## Readings

Three real hosts are registered. Each was read on the date in its row, with our own
reader and identity. The Liverpool and Newcastle readings are of a **silence** rather
than permission. Palace has a specific written-article provision requiring source credit
and a link; it is not permission for unrestricted use of other site material.

| Host | Terms URL | What the terms say about automated reading | `robots.txt` verdict for our path | Review record | Date |
| --- | --- | --- | --- | --- | --- |
| `www.liverpoolfc.com` | [/legal/terms-and-conditions](https://www.liverpoolfc.com/legal/terms-and-conditions) | The page is a ticketing and membership document. Read in full, 276 lines, its only restriction of this kind is 8.5, on reselling tickets "without the prior written consent of the Club". **It says nothing about reading the website, automated access, reproduction or publication.** Silent, not permissive. | `robots.txt` read 2026-09-22 for `/news` and `squadopt/1.0`: allowed | İbrahim Ersan Özdemir | 2026-09-22 |
| `www.newcastleunited.com` | [/en/terms](https://www.newcastleunited.com/en/terms) | The page lists twenty ticketing, hospitality, membership and competition documents and publishes no website terms of use. **No document there governs reading the site.** Silent, not permissive. | `robots.txt` read 2026-09-23 for `/en/news` and `squadopt/1.0`: allowed | İbrahim Ersan Özdemir | 2026-09-23 |
| `www.cpfc.co.uk` | [/terms-of-use/](https://www.cpfc.co.uk/terms-of-use/) | Section 8.2 contains general restrictions on extraction and reuse. **Section 8.7 specifically permits quotations and full written articles with appropriate source credit and a hyperlink to the club website.** Registration is limited to this written-article scope, retaining attribution and source links. | `robots.txt` read 2026-10-01 for `/news/first-team/`, its sampled article and `squadopt/1.0`: allowed | Dated direct-reader evidence below; source activation approved by repository owner | 2026-10-01 |
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

**What the Liverpool and Newcastle readings mean.** Neither club said yes. Each publishes a document
called terms and conditions which, read in full, is about tickets, and neither publishes
anything that governs reading the website. Proceeding on that is a decision the reader
takes and signs, which is what the name and date in the row are for, and it can be wrong
in two ways a later reading would catch: a governing document may exist somewhere neither
search reached, and a club can publish one tomorrow. That is why a row ages.

**The September 2026 survey left seventeen other clubs unregistered for three reasons.**
The paragraphs below preserve that survey; the October follow-up updates the technical
findings for Hull, Brentford and Palace. Eight publish terms
that restrict this directly, and they are not registered: Spurs (2.6.3 forbids extracting,
scraping and crawling; 2.6.4 forbids use to generate prompts) and Bournemouth (no "robot,
spider, or other automatic device") forbid the read itself; Leeds (6.5) forbids mass,
automated or systematic extraction; Arsenal, Brighton, Brentford, Man City and Man Utd
grant a licence limited to personal, non-commercial use. Eight could not be read at all:
Aston Villa, Coventry, Everton, Nott'm Forest, Sunderland, Fulham, Ipswich and
Chelsea serve their terms or policy pages client-side or publish none this reader could
locate, and **unread is not silent**. Hull City's then-tested hosts served nothing this
reader could reach.

**Historical Brentford and Hull City readings, 2026-09-24.**
These resolved the survey's two open checks at that time, with our own reader and identity.

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

**Historical Crystal Palace reading, September 2026, superseded on 2026-10-01.**
The earlier reader found that `robots.txt` allowed our path and an RSS feed existed, but
could not locate website terms. Its news response exposed markup without readable text,
so `fetch_club_document` refused it. The direct-reader check below subsequently located
the terms and verified readable article paragraphs; the signed Palace row records that
new reading rather than repeating the earlier limitations as current findings.

### How to fill a row

- **What the terms say** — in the host's own terms, quoted or closely paraphrased, not
  summarised into "fine". If they are silent about automated access, write that they are
  silent; silence is not permission and it is not refusal either, and the decision to
  proceed on silence is the reader's to make and to sign.
- **`robots.txt` verdict** — for the exact path being registered, and for our user-agent.
  A host that allows `*` but disallows a path we want is a refusal for that path.
- **Review record / Date** — identify the reviewer or link the dated evidence and owner
  activation decision separately, without attributing a reading to someone who did not
  perform it. A host can change its terms without notice; an old row describes that date.
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
update the row's "What the terms say", verdict, "Review record" and "Date", and set the same date
as `terms_read_on` on every registry entry for that host, in one pull request. If the terms
now restrict automated reading, remove the entries instead. As of the rows above, Liverpool's
reading is relied on through 2026-12-21, Newcastle's through 2026-12-22 and Palace's
through 2026-12-30.

## What is deliberately not automated

Nobody's terms are parsed, scored or classified by this project. There is no attempt to
detect a licence from a page, and no default that treats an unreadable or missing terms
document as permissive. A host that has not been read is a host that is not fetched, and
that is the whole mechanism.

## Source discovery follow-up, 2026-10-01

This dated follow-up does not renew the Liverpool or Newcastle readings. The first
pass records what official pages exposed to a web research reader on 2026-10-01. A subsequent
bounded Palace check, detailed below, used the application's exact HTTP identity and
existing readable-text/link extraction functions. The first pass alone cannot establish
what that reader receives. Following explicit approval, Palace was added with the signed
2026-10-01 reading above; the previous three registry entries and their dates were preserved.
No acquisition command or model call was run for this survey or configuration activation.

The league is not a hard-coded list of twenty names. `short_name_roster` derives club names
from the selected bootstrap capture, and source names must match those names exactly. The
twenty clubs below are the earlier survey's set, not a replacement for the captured roster.
A promoted or relegated club must be handled by that roster comparison, without guessing
aliases or reusing a previous season's denominator.

### Discovery and reading evidence

Technical confidence describes only the observed index/article path. High means that a
sample index-to-article path exposed article text; medium means partial discovery or an
incomplete chain; low means no usable discovery was verified. It is not confidence that
collection is permitted or that every relevant article can be discovered. An index may
show a featured story while omitting newer articles loaded by JavaScript.

| Captured-name candidate | Official discovery URL | Observed technical status | Technical confidence | Terms evidence and remaining condition |
| --- | --- | --- | --- | --- |
| Arsenal | [News](https://www.arsenal.com/news) | The research reader received HTTP 403. | Low | [Website terms](https://www.arsenal.com/terms-of-use) grant a limited personal, non-commercial licence and restrict other reuse. Not cleared for this lane. |
| Aston Villa | [News](https://www.avfc.co.uk/news/) | Only a heading and footer were exposed; no article links. | Low | The footer links [acceptable-use policy](https://www.avfc.co.uk/club/legal/acceptable-use-policy/), whose text was not exposed. Unread, not permission. |
| Bournemouth | [News](https://www.afcb.co.uk/news/) | Only the page shell and footer were exposed. | Low | The footer links [Foley Entertainment Group terms](https://www.foleyentertainmentgroup.com/terms-of-use/), which prohibit automated access and monitoring/copying without the stated authorisation. |
| Brentford | [News](https://www.brentfordfc.com/en/news) | A featured article link and its full text were exposed. Other list entries were not verified. | Medium | The [website terms URL](https://www.brentfordfc.com/en/terms-of-use) did not return readable text in this follow-up. The signed 2026-09-24 restriction recorded above remains the existing evidence. |
| Brighton | [Latest news](https://www.brightonandhovealbion.com/all-latest-news) | Headlines were exposed, but article anchors usable by the current link reader were not verified. | Low | [Terms of use](https://www.brightonandhovealbion.com/terms-of-use), section 8.2, restrict extraction and reuse beyond the limited personal licence. |
| Chelsea | [Latest news](https://www.chelseafc.com/en/news/latest-news) | The index exposed only a page shell. Individual indexed articles are not evidence of working discovery. | Low | [Terms and conditions](https://www.chelseafc.com/en/terms-and-conditions) did not expose readable terms. Subscription conditions found elsewhere do not establish the public-news rules. |
| Coventry | [News](https://www.ccfc.co.uk/news/) | Only the page shell and footer were exposed. | Low | The footer links [terms of use](https://www.ccfc.co.uk/terms-of-use), whose text was not exposed. |
| Crystal Palace | [First-team news](https://www.cpfc.co.uk/news/first-team/) | The direct-reader follow-up verified same-path links and real article paragraphs within existing limits; the initial web-tool response had omitted that body. | High | [Terms of use](https://www.cpfc.co.uk/terms-of-use/) are now located: section 8.2 restricts extraction; section 8.7 separately permits credited, linked written articles. The direct robots check allows these paths. Registered on 2026-10-01 within that written-article scope, with attribution and source links retained. |
| Everton | [News](https://www.evertonfc.com/news/) | Only a heading and footer were exposed. | Low | The footer links [terms and conditions](https://www.evertonfc.com/content/terms-and-conditions), whose text was not exposed. |
| Fulham | [News](https://www.fulhamfc.com/news/) | Four featured article links were exposed; the sampled article exposed title/date/author but no body. | Medium | The linked [policies page](https://www.fulhamfc.com/more/policies/) did not expose governing website terms. |
| Hull | [News](https://www.wearehullcity.co.uk/news/) | A reachable club-branded host was found; its news response was still a page shell. | Low | The footer links [policies](https://www.wearehullcity.co.uk/club/policies), whose text was not exposed. |
| Ipswich | [News](https://www.itfc.co.uk/news/) | Four featured links were exposed; the sampled interview exposed title/date/author but no body. | Medium | The linked [policies page](https://www.itfc.co.uk/club/policies/) did not expose governing website terms. |
| Leeds | [News](https://www.leedsunited.com/en/news) | The index was readable; the full index-to-article chain was not verified. | Medium | [Terms and conditions](https://www.leedsunited.com/en/terms-and-conditions), section 6.5, prohibit mass, automated or systematic extraction. |
| Liverpool | [News](https://www.liverpoolfc.com/news) | Article links and a sampled article body were exposed. Already registered. | High | Existing [terms reading](https://www.liverpoolfc.com/legal/terms-and-conditions) above; not renewed by this research. |
| Man City | [Men's news](https://www.mancity.com/news/mens) | Same-path article links and a sampled article body were exposed. | High | [Terms of use](https://www.mancity.com/terms-of-use) grant a limited personal, non-commercial licence and restrict other reuse. Not cleared for this lane. |
| Man Utd | [News](https://www.manutd.com/en/news) | The index was readable; the full index-to-article chain was not verified. | Medium | [Website terms](https://www.manutd.com/en/help/website-terms-of-use), section 2, provide a limited personal, non-commercial licence. Not cleared for this lane. |
| Newcastle | [News](https://www.newcastleunited.com/en/news) | Article links and a sampled article body were exposed. Already registered. | High | Existing [terms reading](https://www.newcastleunited.com/en/terms) above; not renewed by this research. |
| Nott'm Forest | [News](https://www.nottinghamforest.co.uk/news/) | Only the page shell and footer were exposed. | Low | The footer links [terms of use](https://www.nottinghamforest.co.uk/terms-of-use), whose text was not exposed. |
| Sunderland | [News](https://www.safc.com/news/) | Only the page shell and footer were exposed. | Low | The footer links [terms](https://www.safc.com/terms), whose text was not exposed. |
| Spurs | [News](https://www.tottenhamhotspur.com/news/) | The index was readable; no full collection chain was verified. | Medium | [Terms](https://www.tottenhamhotspur.com/information/terms-and-conditions/), sections 2.6.3 and 2.6.4, restrict automated collection and use in AI prompts/content generation. |

These findings refine the historical notes rather than changing what the earlier reader
observed. In particular, Hull's currently reachable host is `www.wearehullcity.co.uk`;
the failed hosts in the September note are not an exhaustive statement about today's
website. Palace's website terms have now been located, so the earlier failure to find them
must not be repeated as a present conclusion. Their written-article provision warrants a
specific reading alongside the general restrictions; it is not a blanket permission for
all site material. The direct follow-up below identified Palace's RSS URL and distinguished its excerpts from
article bodies.

Brentford also exposed more than the navigation-only response recorded in September. The
[sampled match report](https://www.brentfordfc.com/en/news/match-reports-brentford-3-chelsea-0-premier-league-jaidon-anthony-igor-thiago-fabio-carvalho)
contained a body and manager remarks. Man City's
[sampled match preview](https://www.mancity.com/news/mens/liverpool-v-city-premier-league-match-preview-october-2026-63926279)
also contained a body. In contrast, the sampled
[Fulham article](https://www.fulhamfc.com/news/2026/september/30/internationals-jedi-captains-united-states-in-big-win/),
[Ipswich interview](https://www.itfc.co.uk/news/2026/september/29/Christian-Walton-on-new-deal-at-Ipswich-Town/)
and [Palace article](https://www.cpfc.co.uk/news/first-team/international-eagles-gozo-makes-usa-debut-as-kamada-helps-japan-to-back-to-back-wins/)
initially exposed their headings and dates without their story bodies in the web research
tool. Palace's direct-reader check below supersedes that technical limitation for the
sampled article. These are observations of particular responses, not permanent claims that
those sites cannot be read.

### What a coverage report can establish

The operator report compares the entire captured league with the full registry and the
selected source subset. It distinguishes clubs that are not registered, registered but
not selected, selected with no received document, read without a coded response, and read
with a coded response. Unknown registry names are reported separately; selecting an
unmatched name is refused. `Example FC` is an offline placeholder and contributes no real
club coverage.

A club can have a received index, a successful empty model response and no usable article
body. That is still an acquisition result, not proof that no relevant news was published.
A refusal of an optional linked article is shown separately; the existing partial-coverage
contract concerns unread selected registered pages. Neither measure claims an exhaustive
search of the website. The current reader follows at most ten same-origin links per host,
under the registered path, and performs no JavaScript discovery. Its RSS/Atom support reads
item text; it does not follow item links, so a headline-only feed is not a full article feed.

Palace is now registered after the direct-reader check below, a recorded terms reading
and explicit approval of the configuration change. Its existing discovery and size limits
remain in force. Man City and Brentford remain technical candidates with the restrictions
recorded above. Updating a registry alone cannot establish source permissions or readability.

### Palace direct-reader check, 2026-10-01

The [robots file](https://www.cpfc.co.uk/robots.txt) returned HTTP 200 and `Allow: /` for the
application identity `squadopt/1.0 (private research; contact via repository owner)`.
The exact terms, news index and sampled article paths were allowed. Requests remained on
`https://www.cpfc.co.uk`, used the existing 2 MiB document ceiling, and were spaced by at
least the reader's one-second interval. No scripts were executed and no capture was written.

The [first-team index](https://www.cpfc.co.uk/news/first-team/) returned 2,020,865 bytes, below
the existing 2,097,152-byte ceiling. The unchanged `article_links` function found 25 links.
The sampled international-news article was second in that list, within the existing
maximum of ten followed articles per host. This verifies a bounded discovery path; it
does not cover every article on the club's website. The index is close to the size ceiling,
so a future larger response will be refused by the existing rule.

The [sampled article](https://www.cpfc.co.uk/news/first-team/international-eagles-gozo-makes-usa-debut-as-kamada-helps-japan-to-back-to-back-wins/)
returned 1,475,379 bytes. Its served HTML contained actual paragraphs about Richards, Gozo
and Kamada. Seven such paragraphs, totalling 192 words, were all present in the unchanged
`extract_readable_text` output. The page's `NewsArticle` metadata declares publication at
`2026-09-30T11:00:00.000Z`, consistent with the displayed 30 September dateline. That is
publication evidence, not proof of eligibility for an earlier decision capture or an
upcoming league fixture. In particular, an international-match load-management remark is
not automatically a restriction on a later league match.

There was no `articleBody` field in the HTML or JSON-LD. The JSON-LD description was only
29 words. The official page also declares [RSS](https://www.cpfc.co.uk/rss.xml), which
returned a 278,625-byte XML feed with 200 dated items. Its sampled descriptions contained
47 to 53 words, with no full-body field. Neither a new JSON-LD parser nor treating that RSS
as a full-article feed is warranted: the served article HTML already works with the reader.

The direct terms response was also readable. Section 8.2 contains the general restrictions;
section 8.7 specifically permits use of quotations and full written articles with
appropriate source credit and a hyperlink to the club website. The new Palace row records
that specific written-article scope, retaining source attribution and links, rather than
describing all site material as unrestricted. The existing Liverpool and Newcastle rows
are not re-signed here.

No source-registry writer was found in the application or operator scripts. There is a
validated reader, `load_club_sources`, and the acquisition command accepts an explicit
`--registry` path. The documented existing maintenance process changes the registry and
its signed reading together. The reviewed proposal was validated with that loader and
explicitly approved for activation. Only the Palace entry was appended; the prior three
entries were preserved. This approval is specific to that configuration change and does
not create a general exception to the project's restriction on manual data edits.