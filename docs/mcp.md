# Development plan: agents on equal footing

Status: **scoped**, nothing built.

This covers the first half of the `future-plans.md` item "mcp servers: let
other AI's play? Give generators and npcs new tools?" — the half where an
agent reaches *in*. The half where the world reaches *out* is a separate item
in `future-plans.md` now ("an mcp client") and wants its own plan; §14 says
why they were split.

`basic-principles.md` has already decided that this is allowed, and it is the
only place in that document where network access is named as a thing the game
may have:

> Network access may only be provided to in-game entities via strictly scoped
> surfaces, like MCP servers added to the world, API's offered by AI
> providers, federation with other AIMud servers, or on-demand in-game
> resource downloads and update checks.

and this one, which is the whole design in a sentence:

> an open sandbox: players should be able to examine and understand the state
> of the world and its systems. NPC characters, player characters, and AI
> assistants should all have equal access to the world.

Three things come out of this that are worth more than the feature, and they
are the reason to do it now rather than after the flagship worlds:

* **A test can build its own fixture and then play it.** `docs/archived/import-and-export.md`
  made a world into a document so a test could "build one, play it, and assert
  on what it became". Nothing can currently *drive* that world except a person
  typing at it or a test calling `.call()`. An agent with a session can play
  a world the way a player does, which is the only way some bugs are ever
  going to be found.
* **The hand-built worlds get an author who is not a person.** Hunt the
  wumpus, endless alchemy and the Taipan!-shaped one are three
  `future-plans.md` items, each of which is a long sitting at a menu. A world
  is a document and a document can be written.
* **The structured seam gets built once.** GMCP and MSDP are on
  `future-plans.md` and want exactly what a tool call wants: something other
  than a line of prose going in, and something other than a line of prose
  coming back. §3.4.

---

## 1. The change, on one page

* **An MCP session *is* an Evennia session.** Not a Django view, not a
  side-channel: a connection served Portal-side, authenticated, handed to the
  session handler, and thereafter indistinguishable from a telnet client as
  far as the rest of the game is concerned. `who` lists it, `@boot` removes
  it, the idle timer applies to it, and — the one that decides the whole
  architecture — a menu will open for it (§3.2).
* **Four tools, not two hundred.** `send` (a line of input), `poll` (what the
  mud has said since last time), the lookups already registered in
  `world/lookups.py`, and the world document through `world/exchange.py`.
  Nothing else. §5.
* **`send` is a complete building surface, and stays complete for free.**
  CLAUDE.md already promises that every point in a menu is reachable by typing
  a command. That promise is held level for players; an agent inherits it and
  the tool list cannot fall behind the game. §5.1.
* **A token minted in game**, a `SECRET` field beside `apikey` in
  `world/preferences.py`, masked the same way and revocable the same way. Not
  a password, not OAuth. §4.
* **Off unless switched on, and bound to localhost when it is.** Three
  settings, defaulting to nothing listening. §8.
* **A test that fails when the tool list starts drifting.** Every tool this
  codebase defines is either offered over MCP or named on a list of what is
  deliberately not, with the reason — the arrangement `exchange.CARRIED` and
  `exchange.LEFT` already use. §10.
* **No model is called anywhere in this system.** The server needs no API key
  and costs nothing to run. §9.

---

## 2. What is already there

Most of this plan is wiring, because nearly every piece exists.

**`world/toolbox.py`** is already a tool definition that is not tied to a
provider: `Tool` with a name, a description, parameters and a handler; a
`schema(ctx)` that renders the provider shape; `portable()` which strips what
one provider or another will refuse; `problems_with()` which checks a call
against the schema's own promises; `MOST_RESULT` and `MOST_CALLS_PER_ROUND`.
An MCP server is a third consumer of the same objects — after a generator and
after an NPC — and needs no fourth definition of what a tool is.

**`world/lookups.py`** is already the central registry people ask for. Its
`MODULES` tuple names seventeen modules, `all_tools()` collects every
`lookup_tools()` among them, and `named(...)` picks some out in order. A
lookup is defined beside the register it reads, which is what keeps the shape
asked for and the shape read from drifting apart. MCP offers whatever
`all_tools()` returns and adds nothing.

**`world/exchange.py`** already turns a world into a validated document and
back: `document(root)`, `problems(doc)`, `build(...)`, `Refused` carrying
every complaint rather than the first, and caps (`MOST_BYTES`, `MOST_ROOMS`,
`LONGEST_TEXT` and the rest) that are exactly the caps a network surface
wants.

**`world/menus.py`** says "Nobody without a session is shown a menu" (its line
57) and means it. This is not an obstacle; it is the reason §3.2 is shaped the
way it is.

**`world/preferences.py`** already holds a secret on an account and handles it
carefully: `API_KEY` is a `m.SECRET` field, shown through `mask()`, with a
`clear_apikey` entry in `CONFIRMATIONS` and help text that says plainly what
it is and who can see it. A token is the same shape at the same trust level.

**`server/conf/web_plugins.py`** already has the hook, and upstream's own
docstring for it says what it is for:

> `at_webproxy_root_creation(web_root)` — the Evennia `Website` application.
> Use `.putChild()` to add new subdomains that are Portal-accessible over TCP;
> **primarily for new protocol development**, but suitable for other
> shenanigans.

**`server/conf/inputfuncs.py`** is the Server-side dispatch for anything
arriving on a session that is not a command line, and `session.msg(oob=(...))`
is how structured data goes back. This is the pair §3.4 uses.

**`world/permits.py` and `Sponsor.will`** already gate what a model may bring
into being, three ways (whenever asked / only for a player / never), and
`tests/test_permits.py` walks the generator modules and fails if one forgot to
ask. An agent typing `create item` goes through that gate like everything
else, and this plan adds no way around it.

---

## 3. Where it runs, and why that is the hard part

### 3.1 The two processes

Evennia runs a Portal and a Server. Django views — the website, the admin, the
`web/api/` directory that is currently an empty stub — run in the Webserver
and have the ORM. They do **not** have the live game: not the session handler,
not a character's cmdset, not `ndb`, not a menu halfway through being
answered.

So the obvious shape, "add some URLs to `web/urls.py`", buys a `export_world`
tool and nothing else. It cannot `send("north")`, because there is nobody to
send it as.

This is the first thing to settle and everything else depends on it, which is
why it is phase 0 and not phase 3.

### 3.2 An MCP session is an Evennia session

The shape this plan proposes: the MCP endpoint is served Portal-side, through
`at_webproxy_root_creation` in `server/conf/web_plugins.py`, and a client that
authenticates gets a session — a real one, created the way a webclient
connection creates one, handed to the session handler, logged in to the
account the token belongs to.

What that buys, none of which has to be built:

* **Menus work at all.** Without a session there is no menu, and without menus
  there is no building.
* **Unsolicited output routes itself.** An NPC speaking, another player
  arriving, a rule firing, a quest deadline — all of it reaches the session
  because that is what sessions are for. §5.2 is then only a buffer, not a
  notification system.
* **The agent is visible and stoppable.** `who` lists it. `@boot` removes it.
  An idle agent times out. A player can see that something is in the room with
  them and what it is.
* **Permissions are the account's own**, including `@quell`, including the
  lock system, including not being an admin if the account is not one.
* **"AI assistants should all have equal access" stops being an aspiration.**
  Not a parallel API that happens to resemble the game, but the game.

### 3.3 Text in, text out

`send` is `session.data_in(text=...)` and the reply is whatever
`session.data_out(text=...)` produced, collected. Prompt included: a menu
sends one, and an agent that cannot see the prompt cannot answer the menu.

Colour codes are stripped, or rather never generated: the session declares
itself as taking no ANSI and no MXP, the way a dumb client does, and the
existing screen-reader-shaped rendering is then already the right rendering.
This is worth stating because it is the one place a "just like telnet" session
should *not* be just like telnet.

### 3.4 Structured in, structured out

A lookup does not want a line of prose. It wants arguments in and JSON back.

That is an OOB message: in through a custom inputfunc in
`server/conf/inputfuncs.py`, back through `session.msg(oob=("tool", ...))`.
The Portal side holds the request until the matching reply arrives or the
timeout does.

This is the piece worth building carefully, because it is the piece GMCP and
MSDP need too. A mapper asking for the room as data and a model asking
`kinds.lookup_tools()` a question are the same request travelling the same
way; the difference is who is asking and what shape the answer takes.

### 3.5 The spike that decides this

Phase 0 is one afternoon and answers one question: can a Portal-side resource
get a session made, logged in, driven and torn down, with output collected —
and can a structured call reach the Server and come back?

If it can, the rest of this plan is right. If it cannot, the fallback is a
Server-side Twisted service on its own port (`server/conf/server_services_plugins.py`,
which is also a stub waiting), which trades "the webserver is already
reachable" for "the game objects are right there". The tools, the token and
the tests in this plan are unchanged either way; only §3.2 and §3.4 are.

Do not write the token, the tools or the tests until phase 0 has answered.

---

## 4. Who is asking

### 4.1 Not a password, not OAuth

**Not username and password.** MCP clients carry headers, not login flows. A
password in a header is the account credential sitting in a config file on
disk, and revoking it means changing the thing the human logs in with.

**Not OAuth.** It is the right answer for a public multi-tenant server and an
absurd amount of machinery for a mud somebody hosts for themselves and some
friends, which is what `basic-principles.md` says this is:

> low population, distributed servers: AIMud is a mud to be hosted for
> yourself, and perhaps some friends.

Worth revisiting if the ActivityPub item in `future-plans.md` ever happens,
because then the account system is somebody else's and so is this question.

**A bearer token, minted in game.** Revocable on its own without touching the
password, storable in a client config, and readable by the account that owns
it and nobody else.

### 4.2 The field

A `SECRET` field in `world/preferences.py`, in its own small form, beside the
API key because it is the same kind of thing:

```
settings agenttoken
```

* Generated by the game, not typed by the player — the one difference from
  `apikey`, and the reason is that a token a person chooses is a password
  again.
* Shown through `mask()` once at generation and masked forever after.
* Cleared through a `clear_agenttoken` entry in `CONFIRMATIONS`, worded like
  `clear_apikey`: "Any agent using it is disconnected and cannot come back
  until you make another."
* Help text that says the true thing plainly: **this token is the account**.
  It is not a lesser credential, it does everything the account can do
  including spending the API key, and it should be treated the way the API key
  is treated.

It is an account attribute, so it needs a line in `exchange.LEFT` with its
reason, exactly as the five account settings found by the AST test in the
import/export work did. A world document holds no accounts and no secrets, and
this is both.

### 4.3 One account, one character, and displacement

An agent connecting with a token is that account, and puppets the one
character that account has. There is nothing to decide about what it puppets,
because there is nothing else for it to puppet.

**Connecting displaces, and this is not a rule this plan invents.** One
character per account means a second connection already takes the body from
the first, exactly as logging in from a second terminal does. An agent
connecting on your token while you are playing drops you, and that is the
correct behaviour: two sessions on one body interleave output and neither of
you can follow a menu through it.

The one thing to build is honesty about it. A session displaced by an agent is
told so — *"An agent connected with your token"* — rather than being dropped
into silence, because a person thrown out of a half-answered menu by their own
tooling should not have to guess. Nothing else is needed; the session handler
already does the rest.

**To play beside your agent, give it its own account.** Not a second
character, and the reason is permissions rather than tidiness. A token cannot
be scoped down — §4.2 says plainly that it is the account — so an agent on
your account can do everything you can, including spending your key. An agent
on its own account can be given less: not a superuser, quelled, locked out of
what it has no business touching, and with no API key at all if it does not
need one. A second character of yours could be none of those things.

This is also the shape `future-plans.md` already wants for shared worlds: two
accounts, one world, the creator's key. An agent with an account of its own is
not a special case of anything. It is a player, which is what
`basic-principles.md` asked for.

### 4.4 What a token cannot do

It cannot make an account — including the one §4.3 recommends giving an agent
of its own. A person makes that account the way accounts are made here, and
mints a token on it. An agent that could make accounts could make itself more
of them. §5.5.

---

## 5. The tools

### 5.1 `send`

One line of input, as a player would type it. The reply is everything the mud
said in response, including the prompt.

This is the whole of playing and the whole of building, and the reason it is
the whole of building is a promise CLAUDE.md already makes and tests already
hold:

> Every point in a menu must also be reachable by typing a command.

So there is no `create_item` tool, no `edit_rules` tool, no menu-walking API.
There is the command line, which is what a player has, and the parser — noun
phrases, referents, `which one`, disambiguation, the lot — comes with it. A
schema cannot do the English as well as the parser does, and a schema per
command would have to be rebuilt every turn anyway, because a world's verbs
are generated per world and a cmdset depends on the room you are standing in.

### 5.2 `poll`

The mud talks when it wants to. Between one `send` and the next, an NPC says
something, a quest expires, somebody walks in.

`poll` returns what has arrived since it was last called, and blocks for up to
a short timeout so an agent waiting on an NPC does not have to spin. The
buffer is capped in the shape `toolbox.MOST_RESULT` already uses: cut, and
saying it was cut.

### 5.3 The lookups

`lookups.all_tools()`, whole, as MCP tools. They are already `toolbox.Tool`
objects with descriptions and schemas, they are already read-only, and they
are already what an NPC gets. Offering an agent less than an NPC has would be
a strange reading of "equal access"; offering it something different would be
a second registry.

Each is offered only where it can answer, through the `available(ctx)` the
tool already carries — a character's memory needs a character — and the
context is built from the session the way a generator builds one.

### 5.4 `export_world` and `import_world`

`export_world` returns the document. `import_world` takes one, validates it
through `exchange.problems`, and builds it or refuses it entire with every
complaint.

These are not a convenience. They are the reason to build this at all (§6).

Both go through the same confirmations a player's `export world` and
`import world` go through, which for an agent means the confirmation arrives
as text and is answered with `send` — a menu, in other words, which works
because §3.2.

### 5.5 What is deliberately not a tool

* **One tool per command.** §5.1.
* **Account registration.** Nothing is gained — the human has an account and
  the token is minted from it — and it would be an unauthenticated write
  endpoint on a project whose own `future-plans.md` says "massive security
  audit: before hosting this for other people".
* **Anything that writes an attribute directly.** The import/export work
  settled this for documents and it holds here: everything goes in through the
  writer a maker's form already calls. An agent that can set `db.desc` is an
  agent that can build a world no player could have typed.
* **Anything Python.** `basic-principles.md`, and it is not close.

---

## 6. The document is the building surface

The highest-value tool here is not a building tool. It is `import_world`.

A world is one self-contained validated JSON document with no dbrefs, no
paths, no accounts and no code in it, and building one is a single call that
either works or comes back with every reason it did not. For an agent writing
a test fixture that is the difference between four hundred menu answers and
one document — and the document is reviewable, diffable, and can be checked
into `tests/fixtures/` afterwards.

So the expected shape of agent-driven work is:

1. `import_world` a document, or `export_world` one that exists to start from.
2. `send` to play it, and `poll` to hear what happened.
3. The lookups to ask what the world thinks is true.
4. `export_world` at the end to assert on what it became.

Steps 1 and 4 are the ones that do not exist today in any form. Step 2 is what
a session buys. This is the same argument `docs/archived/import-and-export.md`
made for a world being a fixture, finished.

---

## 7. Limits, and refusing

Everything here is a cap that already exists somewhere, reused:

* **A tool result** is capped at `toolbox.MOST_RESULT`, cut with
  `toolbox.CUT_SHORT`, because every list tool takes a query, a limit and an
  offset and can always be asked again more precisely.
* **A document** is capped by `exchange.MOST_BYTES` and the rest of the caps
  in that module, checked before anything is built.
* **Arguments** are checked by `toolbox.problems_with` against the schema's
  own promises before a handler sees them.
* **A rate on `send`**, because a runaway loop typing at the mud is the
  in-game equivalent of the runaway recursion `basic-principles.md` asks for
  guards against.

There is deliberately **no cap on sessions per token**, because there is
nothing to cap: one character per account means a second connection displaces
the first rather than joining it (§4.3). Somebody who genuinely wants two
agents wants two accounts.

A refusal says what was wrong and does not guess, which is the house rule
everywhere else in this codebase.

---

## 8. Safety

**Off unless switched on.** Three settings in `server/conf/settings.py`,
written in the shape `RULESET_DIRS` and `WORLD_DIRS` are written — a comment
saying what putting something here buys and what the bar is:

```python
MCP_ENABLED = False
MCP_INTERFACE = "127.0.0.1"
MCP_PORT = 4005
```

The default is nothing listening. Turning it on and reaching it from another
machine are two separate decisions, and the second one should be made by
somebody who has read the line in `future-plans.md` about SSL and the one
about the security audit.

**The token is the account, and the help text says so.** §4.2.

**The agent adds no authority.** Everything it does goes through the command
line, the locks, the permits gate and the confirmations a player goes through.
There is no path in this plan by which an agent can do something a player
sitting at that account could not.

**The agent is visible.** A player can see what is in the room with them,
`who` lists it, and an admin can `@boot` it. A mud where something is playing
and nobody can tell would be a worse mud.

**`LOCKDOWN_MODE` must switch this off too**, for the same reason it switches
off everything else.

---

## 9. What it costs: nothing

No part of this calls a model. The server runs with no API key; `send`,
`poll`, the lookups and the document all work on a world in worldmode `none`,
which — with an imported hand-built world — is a complete game that costs
nothing, exactly as the import/export plan left it.

The one honest caveat, and it belongs in the README: an agent can *type*
things that spend, because a player can. `create item` in a world whose
creator permitted it costs what it costs. That goes through
`Sponsor.will(making)` like everything else, and an account that does not want
it says so the way it already says so.

---

## 10. Drift: the tool list is data a test can walk

There is no need for a new central registry. `lookups.py` is one, and
`toolbox.Tool` is the single currency already.

The two gaps are the ones MCP would otherwise widen:

* **`npc_gen.NPC_TOOLS`** is a hand-written list of raw provider dicts, not
  `Tool` objects. It converts — `toolbox.from_schema` exists for exactly this
  — and should be converted at its source rather than at its use.
* **Generator finish tools** are defined per module (`item_gen.item_tool`, and
  its siblings), which is right, but nothing anywhere can enumerate them.

So: a `tools()` accessor per tool-defining module, the way `lookup_tools()`
already works, and then the guard:

**A test walks every tool-defining module and fails if a tool is on none of
three lists** — `OFFERED` (an agent gets it), `NOT_OFFERED` (it deliberately
does not, with the reason), or internal to a generator's own loop. Same
arrangement as `exchange.CARRIED` and `exchange.LEFT`, same bite as
`AttributesAreAccountedFor`, and the same reason: a new tool must not quietly
become an agent capability, and must not quietly fail to become one either.

This is the codebase's own idiom applied to tools. A register is data a test
can walk, not prose; a gap left on purpose is a decision somebody wrote down.

---

## 11. Testing

**A session without a socket.** The tests need to make a session, log it in,
drive it and read what it said, with nothing listening on a port. That harness
is the first test asset and everything else uses it; `tests/base.py` already
knows how to make a logged-in session (`session = True`), and this is that
plus a collector.

**The round trip is the test, again.** `import_world` a document, `send` a few
lines that change the world, `export_world`, and assert on the difference.
This exercises the document, the session and the command line in one, and it
needs no model.

**The walk test.** §10, and it must be verified to bite by planting a tool
that is on neither list.

**Refusals.** A bad token, no token, a token whose account is gone, a second
session on one token, a document that fails `problems`, arguments that fail
`problems_with`, a result that has to be cut. Each asserting the complaint and
that nothing changed.

**Tags.** All of this is `world`-tier: the database, no network, no model.
Nothing here belongs in the `llm` tier, which is the point of §9.

---

## 12. Phases

**Phase 0 — the spike.** §3.5. Ends with a written answer to where this runs,
and this document updated if the answer is the fallback.

**Phase 1 — the transport and the session.** A Portal-side resource, MCP's
handshake and tool listing, a session made and torn down. No auth yet, nothing
but a `send` that echoes. Ends when a client can connect and see a tool list.

**Phase 2 — the token.** The preferences field, generation, masking, the
confirmation, the `exchange.LEFT` line, and the displaced-session message
(§4.3). Ends when phase 1 refuses everybody without a token.

**Phase 3 — `send` and `poll`.** The real ones: input in, output collected,
prompt included, ANSI off, the buffer and its cap, the rate limit. Ends with
an agent that can play a world.

**Phase 4 — the document.** `export_world` and `import_world` over
`exchange.py`, with the confirmations. Ends with a fixture built by an agent
and checked in.

**Phase 5 — the lookups.** `lookups.all_tools()` offered, the context built
from the session, `available` honoured. Small, because the tools exist.

**Phase 6 — the guard.** `tools()` per module, `NPC_TOOLS` converted,
`OFFERED` / `NOT_OFFERED`, and the walk test verified to bite.

**Phase 7 — documentation.** The README's command reference and architecture
table; a section under "Before you host this anywhere" about what a token is
and what an agent connected with one can spend; and the agent-readable note
that the ACP item in `future-plans.md` really wanted — what the surfaces are,
in a form something can read.

Each phase ends with the suite green.

---

## 13. Decisions

**An MCP session is an Evennia session, not an API beside one.** Every other
shape has to reimplement menus, output routing, visibility and permissions,
and would drift from all four. This one gets them by not being different.
§3.2.

**`send`, not a tool per command.** The invariant that makes it complete is
already written down and already tested, so a complete building surface costs
one tool and stays complete without anybody maintaining it. §5.1.

**A token minted in game, and it is the account.** Not a password in a header,
not OAuth for a mud with four players. Said plainly rather than dressed up as
a scoped credential, because it is not one. §4.

**No multiple characters per account, and none added for this.** The
indirection that would justify them is already here: every piece of per-world
character state is keyed by world id on whichever object owns it —
`created_worlds` and `world_last_locations` on the account,
`ledger.forget_world(account, root_id)` per account and world,
`quests.forget_world(character, root_id, givers)` per character and world,
memory per world root — and `enter world` moves the one body between worlds
rather than making a new one. Characters per world would replace a keyed map
with an object graph and arrive at the same behaviour, at the cost of a
character-select screen at login, `MULTISESSION_MODE` changing what reconnect
means for everybody, and the out-of-character layer becoming something a
player has to think about. What it would *not* buy is the thing anybody
actually wants from it — an agent that can be given fewer permissions than
you, which needs an account and not a body — and it would not let an agent
into your world either, which is shared worlds. §4.3.

**The document is the building surface.** The reason to do this now. §6.

**No new registry; a walk test instead.** `lookups.py` already collects what
can be collected, and what stops the rest from drifting is the arrangement
that already stops export from rotting. §10.

**Off by default, localhost by default.** §8.

**No account registration over MCP.** §5.5.

**No ACP.** ACP's client is an editor and its agent is a coding agent; for
aimud to speak it, aimud would have to become a host for coding-agent
sessions, which is a different program. Nothing in "help me build a world with
Claude Code" needs it that MCP does not already give. The half of that
`future-plans.md` item worth keeping is the documentation — surfaces written
down in a form an agent can read — and that is phase 7, not a protocol.

---

## 14. Open questions

**Whether `poll` is enough, or whether the client needs pushing.** MCP is
request-shaped and a mud is not. A blocking `poll` with a short timeout is the
simple answer and is probably right for a low-population game; if it is not,
the answer is a notification and phase 3 will find out.

**An agent on its own account has no way into your world yet.**
`resolve_worlds` lists the worlds an account created and `enter world` picks
from that list, so today an agent with its own account can only enter worlds
it made itself. That is the whole of the testing case and none of the playing
case, and it bounds what phase 4 can be tested against.

It is less of a wall than it looks, because **a world already travels between
accounts without either of them sharing anything**: the agent exports to
`WORLD_DIRS` and the player imports, or the other way round. A world built by
an agent can be played by a person the same day, and a world a person is stuck
in can be handed to an agent to look at. The document is the bridge, which is
what it was for.

What it is not is two of you in one room at once, and that is **shared
worlds** — `future-plans.md`, next after this — not multiple characters
(§13). The two things this plan owes it: an agent connected to somebody else's
world spends somebody else's money, and `Sponsor` already has opinions about
that; and nothing here should make entering a world you did not create any
harder than it already is.

**Whether the structured seam should be GMCP from the start.** §3.4 says the
plumbing is the same. It may be cheaper to build MSDP or GMCP properly in
phase 1 and have MCP be its first consumer, rather than build a private OOB
message and generalise it later. Phase 0 is the right place to look at this,
because it is the same afternoon.

**The client half.** A world calling out — weather, a web search, real data —
is in `future-plans.md` as its own item and is deliberately not here. It is a
different set of questions (where a server is declared, who may use one, and
what happens to text that arrives from outside a world that insists its text
be grounded) and it should not hold this up. The one thing this plan owes it:
nothing here should assume an MCP tool is something only a *client* of aimud
holds.
