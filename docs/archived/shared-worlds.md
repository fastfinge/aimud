# Development plan: shared worlds

Status: **built**, phases 0 to 4, on the `shared-worlds` branch. Where the
building changed the plan, §12 says how and why. This is the first half of the
`future-plans.md` item "shared worlds". That item has two parts. One is
letting somebody else stand in your world. The other is making a world worth
standing in when no model answers (worldmode `none`, idle NPCs picking from
what they can do, AIML-style answers). This plan builds the first part. The
second part stays in `future-plans.md`. This plan only gives it a clean place
to start: everything below makes "no model answers here right now" an ordinary
state with one source of truth.

---

## 1. The change, on one page

* **A world's creator can share it.** One switch, `shared`, in the world's
  settings beside its mode. A shared world is open to every account on the
  server. There are no invitations and no ban lists (§9).
* **Shared worlds have their own list in `enter world`.** The menu gains a
  **Public worlds** submenu. It lists every shared world somebody else made,
  with who made it and whether they are online. Every entry in it can also be
  typed: `enter world public` and `enter world public <number or title>` (§4).
* **Models are always paid for by the world's creator.** That was already
  true for nearly every call, through the sponsor. Two paths still chose a
  payer for themselves, and both are fixed: an agent's tools paid with the
  agent's own account, and memory upkeep fell back to "any account with a
  key" (§5.3).
* **No model is called while the creator is logged out.** That is one test,
  added to `Sponsor.answers`, which every generator already asks. `key()`
  refuses as well, so a path that forgot to ask still cannot spend. With the
  creator offline, a shared world plays the way a world with no key plays
  today (§5).
  * **One exception, which you chose:** memory upkeep in an *unshared* world
    keeps today's behaviour and may run after everybody has logged off. In a
    *shared* world, memories are only summarised while the creator is online
    (§5.4).
* **The world runs in its creator's mode, and only its creator can change
  it.** `normal` and `always` mean what they mean today, whoever is visiting.
  `always` used to switch itself off when *nobody* was logged in. It now
  switches off when the *creator* logs out. The settings that decide how a
  world runs (its mode, its generation permits and `shared`) are for the
  creator alone. The superuser override that `owns` grants does not reach
  them (§6).

## 2. What is already there

Most of this plan is already built. It was built ahead of time, for exactly
this case.

> 🧠 **From Hindsight memory (Key decisions and rationale)** — The sponsor
> (commit 43f6b3b, September 11, 2026) was introduced so that "somebody visiting
> a world they did not make should not spend their own key on its innkeeper". A
> world→creator back-link is written when a world is made and backfilled at
> startup. The older rule that a new room's "generation cost falls to whoever is
> in the room, else the world's creator" was replaced by it: `npcs.py`'s
> preference for any player in the room with a key is named in `sponsor.py` as
> "the exact behaviour shared worlds cannot have".

* **`world/sponsor.py`.** `of(caller)` and `of_world(root)` already pay with
  `creator_of(root)`, never with the actor. `Sponsor.answers` describes itself
  as "the place worldmode `none` will be added when it exists -- one line here
  rather than a branch in each of the callers". `_no_key` already words its
  refusal differently for a visitor ("This world belongs to X, who has no API
  key set").
* **Every NPC wake-up and every generator asks the sponsor.** `npcs.py` asks
  `answers` before each of its four kinds of call. Ten modules ask `will`, and
  `tests/test_permits.py` fails if a generator has no gate. `services.allowed`
  reads `answers` too, so an outside call made by a character, or any
  acts-outward call, follows the same rule with no change.
* **`world/activity.py`.** `mode`, `set_mode`, `always_on` and
  `normalise_unwatched`, plus `npc_may_act`, the single gate every NPC
  wake-up passes.
* **`commands/subjects.py`.** `owns(account, root)` decides who may change
  what a world is made of. It is true for the creator *or the superuser*.
  Only one maker (pronoun sets, `world/makers/vocabulary.py`) is open to
  anybody standing in the world, and it is meant to be.
* **`commands/world_subject.py`.** `ENTER_WHICH`, `_world_entries` and
  `_pick_world` list and pick from `resolve_worlds(account)`, which is
  `account.db.created_worlds`. `enter_world` already remembers where each
  account last stood in each world (`world_last_locations`, keyed by world),
  so a visitor gets their own return point with no change.
* **Keyless worlds already play.** Written narration, fixed words for verb
  rules and `_said_plainly` exist because a hand-built world with no key has
  to read properly. A shared world whose creator is away is that case again,
  so nothing new is needed for it to play.

## 3. Sharing a world

### 3.1 The switch

A `Field` called `shared` on `THIS_WORLD` in `world/preferences.py`, beside
`MODE` and the five permit fields. It is a yes/no choice, written through
one function, `sharing.share(root, on)`, in a new module `world/sharing.py`.
That module is the one place that says what shared means, the way
`activity.py` holds the mode and `permits.py` holds what a world may
generate.

* Stored as `world_root.db.shared = True`. Unshared means the attribute is
  absent or false, so every existing world is unshared with no backfill.
* Turning it on asks first, with a new `CONFIRMATIONS` entry
  (`world_share`), because it is the one setting that lets somebody else
  spend your key: *"Share this world? Anybody on this server can enter it,
  and what happens to them here is paid for with your key while you are
  logged in."* Turning it off asks only when somebody is visiting (§3.2).
* `view worlds` marks a shared world, so a creator can see at a glance what
  they have opened.

### 3.2 Unsharing, deleting, resetting

* **Unsharing sends visitors out.** Anybody in the world who is not its
  creator is moved to the start room and told *"X has closed this world to
  visitors."* That is the same move `clear_world` already makes before it
  deletes rooms. A world that stops being shared and keeps strangers inside
  would only be half closed. Their `world_last_locations` entry is kept, so
  they return to the same spot if it is shared again.
* **Deleting and resetting** already move every character out of a world
  (`clear_world`), visitors included. They now tell visitors which world went
  and why, using the message argument `clear_world` already takes.

### 3.3 Export and import

`shared` is `exchange.LEFT`: *"whether this server's other accounts may enter
is a choice about this server, not about the world"*. An imported world
arrives unshared, the same way it arrives with a new owner. The AST test
`AttributesAreAccountedFor` enforces this.

## 4. Entering a shared world

### 4.1 The menu

`ENTER_WHICH` gains a `Submenu("public", "Public worlds", PUBLIC_WORLDS)`
after the creator's own worlds and before `Back to Limbo`. It is offered only
when at least one shared world was made by somebody else, so a server with
one player never sees it.

`PUBLIC_WORLDS` lists `sharing.public_worlds(account)`: every root with
`shared` set whose creator is not this account. Each line reads:

> **The Drowned Library**, by fastfinge, online -- 14 rooms

When the creator is offline, the line says so and what it means:

> **The Drowned Library**, by fastfinge, away (nothing new happens there until
> they are back) -- 14 rooms

The world the visitor is standing in is marked, as `_world_line` already
does.

### 4.2 Typed

Every point in a menu must also be reachable by typing a command:

* `enter world public` opens the submenu.
* `enter world public <n>` enters by the number shown.
* `enter world public <title>` enters by title, matched the way
  `names_for` matches titles everywhere else.

**Numbers are a convenience here, not an identity.** A creator's own worlds
keep their numbers because `delete world 2` has to mean the same world
everywhere. Nothing destructive is ever typed against a public world, and
the list changes whenever somebody shares or unshares one. So public worlds
are numbered in a stable order (creator name, then when the world was made),
and the title is the dependable way to name one.

### 4.3 Arriving

`enter_world` already refuses nothing. It gains one check and one note:

* **Refused** if the world is neither yours nor shared. The test is
  `sharing.may_enter(account, root)`. Nothing can reach that today, but an
  agent or an old menu entry could once sharing exists.
* **Told** on arrival when the creator is offline: *"fastfinge is away, so
  nothing new happens here until they are back: the people here keep to
  themselves, and unexplored ways stay closed."* This is said once, on entry,
  so it isn't discovered by trying a door.

## 5. Who pays, and when nobody does

### 5.1 The one test

```python
@property
def answers(self):
    return bool(self.account
                and self.account.db.openrouter_api_key
                and present(self.account))
```

`present(account)` is `bool(account.sessions.count())`: logged in at all,
whatever they are doing and wherever they are standing. An owner who is idle,
or playing in another world, is still present. Paying is a matter of being
logged in, and how attentive a player is already belongs to `activity.py`.

`key()` gains the same test and raises a new `_away` error: *"This world
belongs to X, who is not logged in, so nothing new can happen here until they
are back."* `key()` is what `world.llm` reads, so a call site that skipped
`answers` still fails closed, with a sentence a player can read.

### 5.2 What this changes for a creator alone

Nothing a player can see. While a creator is logged in, `present` is true. When
they log out, nobody is left in an unshared world to see the difference, and
`always` was already switched off by `normalise_unwatched`. The two things that
did run after logout were memory upkeep, which keeps today's behaviour for
unshared worlds (§5.4), and an agent account playing in its owner's world while
the owner was offline. That agent is no longer paid for (§5.3). This is what
the rule asks for.

### 5.3 The two paths that chose their own payer

* **`world/agents.py` `_context`** builds the sponsor with
  `of_account(account)`, so an agent's tools spend the *agent's* account even
  inside somebody else's world. When the agent is in a world, the sponsor
  becomes `of_world(world_root, actor=character)`. Outside any world,
  `of_account` stays, because there is no world there to pay.
* **`world/fact_gen.py` `_account_for` and `world/summaries.py` `payer_for`**
  fall back to "any account with a key" when a world's creator has none. On
  a server with one player that was harmless. On a shared server it spends a
  stranger's key on somebody else's world. The fallback is removed: a bank
  whose creator cannot pay is skipped and tried again on the next pass.
  `_anybody_with_a_key` and the `spare` argument go with it.

### 5.4 Memory upkeep

Memory sleep runs once the game has been quiet for `QUIET_FOR_HEAVY_WORK`, and
that is usually after everybody has logged off. As you chose:

* **An unshared world** is summarised as today, whenever the game is quiet,
  creator online or not.
* **A shared world** is summarised only while its creator is present. A pass
  that reaches a shared world's bank while the creator is away skips it, and
  a later pass picks it up.

`summaries.payer_for` and `fact_gen._account_for` decide this, by asking
`sharing.is_shared(root)` and building the sponsor with `present` checked
only for shared worlds. This is the one place that bypasses
`Sponsor.answers`. It is named there with the reason, and it gets a test of
its own.

## 6. The mode, and who may change it

### 6.1 Creator only

`subjects.owns` stays as it is for building, because an admin repairing what a
world is made of is a real need. A new `subjects.created(account, root)` is
true for the creator alone, and gates:

* the whole `THIS_WORLD` settings group (`preferences.owns_world`): the mode,
  the five generation permits, and `shared`
* `sharing.share`, checked again inside the function, so a typed `settings`
  line cannot get round the menu

The permits go with the mode, because they are the other half of how a world
runs. A visitor who could turn `rooms` from `asked` to `always` would be
choosing how the creator's money is spent.

### 6.2 `always`, with visitors

`always` follows the creator, not whoever is logged in:

* `activity.always_on(root)` asks whether the *creator* is present, where it
  used to ask `anybody_logged_in()`. If the creator is away, this world goes
  back to `normal`. Only this world changes, not every world at once.
* `normalise_unwatched` at server start is unchanged.
* `_leaving_note` (*"still running always"*) still speaks only to the
  creator.

`normal` needs no change. NPCs act near any active player, so a visitor
counts as an audience. They are paid for by the creator while the creator is
present, and by nobody otherwise, because `npcs.py` asks `answers` after
`npc_may_act`.

### 6.3 When the creator logs out

`Account.at_post_logout` (or `at_disconnect` for the last session) tells
everybody in the creator's shared worlds once: *"fastfinge has logged out.
Nothing new will happen here until they are back."* When the creator logs back
in, the visitors are told that too. Nothing else has to happen at that
moment, because `answers` is asked fresh on every call.

## 7. What a visitor may do

Nothing about this changes. It is listed here so it is decided rather than
inherited by accident:

* **Play:** every verb, every NPC, every quest, paid for by the creator
  while the creator is present.
* **Read:** every `view` that reading already allows.
* **Make:** pronoun sets, the one maker open to anybody in a world (meant
  for players describing themselves).
* **`~` on a form:** a form's sponsor comes from where the player is standing,
  so `~` on the "You in this world" form spends the creator's key. This
  follows the rule. The `spend` confirmation already asks before any call made
  on purpose. Its wording changes for a visitor, to say whose key it is.
* **Generation permits set to `asked`** count any player, visitors included,
  as "a player went looking". A creator who wants only themselves to grow the
  world should use `never` and build by hand. Recorded in §10, not changed.
* **Outside services:** a visitor's own contained or looks-outward tool
  calls are not model calls, and use the server's credentials, as an
  admin decided when adding the service. Acts-outward calls and every call a
  character makes already require `answers`, so they stop with the creator.

## 8. Testing

New tests, each watched failing before the code that passes it:

* **`tests/test_sponsor.py`**: `answers` is false and `key()` raises `_away`
  when the creator has no session. Both are true again once the creator has
  one. A visitor's own key is never read, even when the creator has none.
* **`tests/test_sharing.py`**: sharing and unsharing. Unsharing moves
  visitors out and leaves the creator. `may_enter`. `public_worlds` excludes
  your own and unshared worlds. A typed `settings shared on` by a
  non-creator is refused, and so is one by the superuser (§6.1).
* **The public submenu and the typed forms** (`enter world public 2`,
  `... <title>`), driven through the form's typed keys as every other menu
  test is.
* **`always` with visitors**: a visitor logged in while the creator is away
  does not keep the world in `always`.
* **Agents** (`tests/test_agents.py`): an agent in another account's world
  has that creator as payer.
* **Memory** (`tests/test_summaries.py`, and `test_memory_tools.py` where it
  already covers `fact_gen._account_for`): no fallback payer. An unshared world is summarised with its creator offline, and a
  shared one is not.
* **Exchange**: `shared` is in `LEFT`, and an imported world is unshared.

Fixtures: `characters = 2` with `accounts = True` (a creator and a
visitor), which is the costly dial and is right here. A session is needed
only where being *logged in* is the thing tested. Elsewhere, `present` is
patched, the way `tests/support.py` stands in for other services.

## 9. Not in this plan

* **Worldmode `none`, idle NPCs, AIML answers**: the second half of the
  `future-plans.md` item. That item stays there, rewritten to say this half
  is built.
* **Invitations, ban lists, per-visitor permissions.** Shared means shared
  with this server. A server is a small number of people who know each
  other, and the first time that stops being true, this is the next plan.
* **A spending cap or a ledger report for creators.** `world/ledger.py`
  counts calls, but nothing reports them yet. A creator who shares a world
  will want to see what visitors cost, and that is the obvious next piece.
  It isn't needed to share safely, because a creator who logs out stops all
  spending.
* **Sharing across servers.** That is federation, and a different item in
  `future-plans.md`.

## 10. Decisions

* **Logged in means any session, idle or not.** Attentiveness already
  belongs to `activity.py`. Paying is a separate question with a simpler
  answer.
* **Memory upkeep is exempt for unshared worlds only** (your call,
  2026-10-05).
* **Mode, permits and sharing are for the creator, not the superuser**
  (your call, 2026-10-05). Building stays open to the superuser through
  `owns`.
* **Unsharing evicts visitors** rather than letting them stay until they
  leave.
* **`asked` counts visitors as players.** Changing that would need a fourth
  permit setting ("only when the creator asks"). That can be added later if
  it turns out to be wanted.

## 11. Phases

Each phase ends with the free suite green, and one full run on settled code
before the PR.

* **Phase 0: the creator must be present.** `present`, `answers`, `key()`
  and `_away`. The agent sponsor (§5.3). Memory payers without the fallback,
  with the shared-world rule (§5.4). Note: until phase 2 lands, no world is
  shared, so §5.4 is not visible yet.
* **Phase 1: creator-only world settings.** `subjects.created`.
  `owns_world` uses it. `always_on` follows the creator.
* **Phase 2: sharing.** `world/sharing.py`, the `shared` field and its
  confirmation, unsharing evicts, `view worlds` marks shared worlds,
  `exchange.LEFT`.
* **Phase 3: entering.** The Public worlds submenu, `enter world public`,
  the `may_enter` check, the arrival note.
* **Phase 4: telling people.** The creator's logout and login notices to
  visitors. The `spend` confirmation's wording for a visitor. The
  delete/reset message to visitors. README: "Sharing a world". Help entries.
  `future-plans.md` rewritten.

## 12. As built

Where the building departed from the plan above, and what it found.

* **The upkeep exemption is a sponsor, not a branch (§5.4).** `payer_for` and
  `_account_for` could not "check `present` only for shared worlds" by
  themselves: they hand a `Sponsor` to `world.llm`, and `key()` refuses an
  absent creator. So `Sponsor` has an `unattended` field, set only by
  `sponsor.for_upkeep(root)`, and only for an unshared world. Every other path
  still needs the creator logged in, and the exemption is named in one place.
* **`sponsor.is_creator`, not `subjects.created` (§6.1).** The check is needed
  in `world/preferences.py` and `world/sharing.py`, and `world/` does not
  import from `commands/`. It sits beside `creator_of`.
* **Fact distilling had never run live since commit 2196ecc.**
  `fact_gen._account_for` returned the creator's *account*, and `distil` used
  it as a sponsor: `sponsor.key()` on an account calls its name. Every test
  replaced `_account_for` with a fake sponsor, so nothing saw it. It now returns
  a real sponsor, and `WhoPaysForDistilling` tests the real function. A bank
  nobody can pay for is also now skipped rather than ending the pass, or one
  creator logging out would stop distilling for everybody.
* **The agent's own account is not the sponsor's (§5.3).** `import_world` and
  `_world_for` read `ctx.sponsor.account` to mean "the agent's account". Once
  the sponsor inside a world is its creator, that named the wrong account. They
  now read the actor's account (`agents._account_of`).
* **A reset keeps a world shared (§3.2, not in the plan).** A reset builds a
  new root, and `shared` is in `exchange.LEFT`, so a rebuilt world came back
  unshared with its visitors already moved into it. `sharing.carry` copies the
  switch across in both reset paths, before the old root is cleared.
* **The superuser may enter any world (§4.3).** The plan refused anything
  neither yours nor shared. The superuser may already repair what any world is
  made of through `owns`, and has to be able to stand in one to do it. Mode,
  permits and sharing stay the creator's alone.
* **`always` goes back to normal for that world only (§6.2).**
  `anybody_logged_in` had no other caller, so it is gone.
* **No `spend` wording to change (§7).** The one `spend` confirmation, judging
  suggestions, is offered only to the creator and already says "paid for by
  this world".
* **Tests.** `tests/support.logged_in(test, *accounts)` counts accounts as
  logged in for `sponsor.present`. Eleven existing tests needed it: each had a
  fixture account paying for something it asked for, which no real player can
  do without being logged in. `PresentMeansLoggedIn` checks `present` against a
  real session. Every new guard was watched failing with the fault planted.
* **Not watched live yet**: two real accounts on the live server, one
  visiting the other's shared world, with the creator logging out partway.

