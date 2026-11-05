# Player details and pitch movement

Tap a player's plate or bench row to open their points, this week's fixtures and, for an
incoming transfer, the reason carried by the plan. A football forecast adds its minutes
estimate to the matching fixture. The fixture calendar must match the plan's capture and
season; an absent estimate is left out. A verified manager absence includes the exact
source words and a link to the club page.

A player gets the **Out** mark on their pitch plate or bench row, and the manager's
statement with its words, link and publication time, only when every check below holds.
The statement shows in the player's details and in the **Manager's statement** list below
the squad. That list covers the players of the squad on show and of the squad the member
holds. The rule is `coachAbsences` in `web/src/features/league/advice/coachAbsences.ts`. A
player who fails any check gets neither, and nothing stands in their place.

- The news document is from the squad's own publication. It has the same generation time,
  which is a full instant with its offset. The squad names its capture, and the document
  has the same capture, league, entry, season and gameweek. Its window is 1.
- Its evidence is a club news read (`club_news_capture`) under `managers_word_rule_v3`.
- The player has exactly one applied statement in it. Its speaker is `manager`, its role
  `not_starting` and its disposition `stated_expected_absent`.
- Its words are shown, not blank, and carry none of the figures the site withholds, such
  as a percentage, a chance or odds.
- Its publication time has `instant` precision. Publication is at or before the fetch,
  and the fetch at or before the document's generation, each a full instant with its
  offset.
- Its source is an HTTPS address with a host, and no whitespace, backslash, user name or
  password.

The page reads this news from the manager's word document that the member's advice index
names. It reads it only when the index marks that document available and its source is a
club news read (`club_news_capture`). It does so even when the member has the manager's
word switched off for planning, and reading it never submits a computation. Until that
document is read, and whenever the index names none or it cannot be read, the check runs
on the advice the page shows.

Each plate has a named button with a touch target at least 44 px high. Enter opens it,
Escape or Close dismisses it, and focus returns to the button. The source link remains a
separate control. A plan that no longer draws the player, or another member or capture, closes
the details, and they stay closed until the player is chosen again.

When another plan arrives, retained players move from their actual previous screen positions
for 400 ms. The existing shared motion tokens and Web Animations API handle this without
an additional animation package. A first load, another member/capture, a resize or reopening
the pitch does not animate; reduced motion changes positions immediately. Interrupted
animations are cancelled, leaving the final layout in control.

The following screenshots use synthetic test data, taken by `e2e/player-details.spec.ts`.
That test also checks keyboard focus, Escape, mobile overflow, accessibility, and the same
final positions with motion enabled and disabled.

![Player details in Turkish at 360 px](screenshots/player-details-tr.png)

![Player details in English at 1280 px](screenshots/player-details-en.png)
