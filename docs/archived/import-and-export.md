# Development plan: worlds that travel

Status: **built**, phases 1 to 8. What each phase came to, and where it
differs from what was scoped, is under each phase in §15. Everything the
building found is marked **as built** where it changed the plan; there is a
good deal of it, and the largest is §5 -- the maker table is not the spine of
export after all.

This covers the `future-plans.md` item "world import and export", and it is
phase 7 of `docs/archived/player-building.md`, named there and deliberately left
unscoped until the maker table had proved itself against the six phases before
it. It has:

> **Phase 7 (separate plan): export and import.** A world as a document, over
> the same maker table. Named here so phases 1 to 6 build for it; scoped when
> they are done.

They are done. This is that scoping.

Three things come out of it that are worth more than the feature itself, and
they are the reason it is worth doing now rather than after the flagship
worlds:

* **A hand-built world that ships with aimud becomes a file rather than code.**
  Endless alchemy, the Taipan!-shaped one and hunt the wumpus are three
  separate `future-plans.md` items, and every one of them currently has no
  answer to "how does it get onto somebody's server". A world document is the
  answer, and it is the same answer for all three.
* **A world becomes a fixture.** `tests/fixtures/export.py` exists because the
  only generated rule data that has ever existed was about to be destroyed by
  a `worldreset`, and it takes the registers and deliberately leaves the prose.
  Once a world is a document, a test can build one, play it, and assert on
  what it became -- without a model and without a database snapshot.
* **`reset world` stops meaning "pay for a different world".** Today a reset
  regenerates from the setup, which costs model calls and gives back somewhere
  else. With a restore point it means what everybody assumed it meant.

---

## 1. The change, on one page

* **One document per world** (`world/exchange.py`). JSON, validated before
  anything is built, refused entire on any fault, and readable and editable by
  hand. Its vocabulary half *is* a ruleset document, section for section, so
  `rulesets.problems` validates it and `rulesets._apply` writes it (§3.3).
* **Nothing in it is a dbref.** Every room, thing, person and way has a local
  id that is a slug of its name, and every reference inside the document --
  an exit's destination, a coin's host, an errand's giver, a rule scoped to one
  object -- names one of those. Import builds the map once and resolves in a
  second pass (§3.2).
* **One writer per thing, and they already exist.** Import calls
  `worldgen._create_room`, `worldgen._make_exit`, `clothing.create`,
  `kinds.remember`, `rulebooks.add`, `quests.save_spec` -- the same functions
  the generators and the building forms call. A world somebody imported and a
  world a model wrote are the same world, for the same reason a world somebody
  typed already is (§7).
* **A restore point on the world root.** `import world` sets it; `export world`
  sets it too, so exporting doubles as saving the state to come back to.
  `reset world` replays it when there is one and regenerates from the setup
  when there is not (§8).
* **A shared folder**, `WORLD_DIRS`, exactly mirroring `RULESET_DIRS`: a list
  of directories, the first written to and all of them read. No player-supplied
  string ever becomes a path component (§9, §11).
* **A test that fails when export starts rotting.** An AST pass collects every
  attribute this codebase writes and asserts each is either carried by the
  document or named on a list of what is deliberately left. Without it, export
  is complete on the day it is written and quietly incomplete forever after
  (§13.2).
* **No model is called anywhere in this system.** Export and import cost
  nothing and work with no API key at all (§12).

---

## 2. What is already there

Most of this plan is a reader over machinery that exists. What is genuinely
new is the document format, the reference rewriting, and the restore point.

| Needed | Already exists as | Where |
|---|---|---|
| A validated JSON document that writes vocabulary and rules into a world | a ruleset | `world/rulesets.py` `problems`, `_apply` |
| Refusing a document naming a state/kind/trait nothing declares | `_undeclared` | `world/rulesets.py` |
| A list of everything creatable, with a listing and a writer each | the maker table | `world/making.py` |
| Making an item from a description of it | `clothing.create(spec, location)` | `world/clothing.py` |
| Making a room, placing it, zoning it, wiring its exits | `worldgen._create_room` | `world/worldgen.py` |
| Making a world root with setup, clock, rulesets, permits, owner | `worldgen.first_room_by_hand` | `world/worldgen.py` |
| Everything a world was set up with, in one dict | `lore.spec_of` | `world/lore.py` |
| Writing that dict back onto a world | `lore.store` | `world/lore.py` |
| Rebuilding the new world before destroying the old | `_reset` | `commands/world_subject.py` |
| Registers as plain JSON-able Python | `_plain` | `tests/fixtures/export.py` |
| A directory setting a server adds files to | `RULESET_DIRS` | `server/conf/settings.py` |
| `import` and `export` as verb commands | `CmdImport`, `CmdExport` | `commands/verbs.py` |

Three of those deserve a sentence each.

**`rulesets` is already half the format.** `SECTIONS` is `actions`, `verbs`,
`kinds`, `attributes`, `conditions`, `rules`, `mechanics`, and `_apply` writes
every one of them through the same functions a player's form calls. Its
docstring says the thing this plan depends on: "Everything a ruleset can say, a
world could have said for itself with `create rule`." A world document is that
sentence plus the world's contents.

**`first_room_by_hand` is the import's front door.** It already makes a world
root, writes the title, description, guidance, clock, rulesets and permits
through `lore.store`, claims the world for an account, and adds it to
`created_worlds` -- with no model call. An import is that, and then the document
replayed on top of it.

**`CmdImport` and `CmdExport` already exist** with no subject answering them
but `import commonsense`. `VERBS` in `commands/subjects.py` has held `import`
and `export` since the verb commands were written. Nothing new is added to the
command surface; `world_subject.py` gains two `Use` entries.

---

## 3. The document

### 3.1 Shape

```json
{
  "aimud": 1,
  "kind": "world",
  "title": "Netherfield Hall",
  "exported": "2026-09-25",
  "rooms": 34,

  "requires": {
    "rulesets": {"default": 3, "clothing": 1, "crafting": 2},
    "plugins": []
  },

  "setup":      { "...": "lore.spec_of, less the player's own name and look" },
  "vocabulary": { "...": "a ruleset document, plus `decided`: see 3.3" },
  "map":        { "plan": {}, "zones": {}, "rooms": [], "ways": [] },
  "things":     [],
  "people":     [],
  "errands":    [],
  "learned":    { "...": "what this world has already worked out" }
}
```

*As built*, `vocabulary` holds these sections: `kinds`, `attributes`,
`conditions`, `actions`, `verbs`, `token_lists`, `pronouns`, `rules`, and
`decided` -- which rules of its rulesets this world had switched off. The
first eight are a ruleset document exactly; `decided` is the one thing a
ruleset has no need of and is taken out before the rest is judged as one.

`aimud` is the document version and the first thing read. A document from a
later version than this server knows is refused by number rather than by the
first field that fails to parse.

`rooms` at the top is there so that `view exports` can list what is in the
folder without parsing every document whole.

### 3.2 Local ids, not dbrefs

Nothing in a document is a dbref. A dbref is this server's row number; it means
nothing on another one, and it means something *different and wrong* -- some
other object -- which is worse than meaning nothing.

Every room, thing and person carries an `id` that is a slug of its name:
`the_gym`, `brass_key`, `mrs_hallow`, `brass_key_2`. Every reference names one.

**As built: one namespace for all three, not one per section.** A thing's `at`
may name a room, a person or another thing, and a reference that has to be read
twice to know what sort of thing it points at is a reference that will one day
be read wrongly. A collision takes a number across the whole world. Ways carry
no id at all, because nothing refers to one.

| Reference | Lives on | Names |
|---|---|---|
| where a way goes | a way | a room id |
| where a way is | a way | a room id |
| where a thing is | a thing | a room, person or thing id |
| what a thing is in/on/under/behind | a thing (`relation_to`) | a thing id |
| who owns a thing | a thing (`owner`) | a person id, or nothing |
| who hands out an errand | an errand (`givers[].npc`) | a person id |
| what one rule is about | a rule (`scope.object`, `scope.room`) | a thing or room id |
| who somebody is following | a person | a person id |

Slugs rather than indices for two reasons. A document somebody opens in an
editor reads -- `"destination": "the_gym"` says where the door goes, `"to": 17`
does not. And a re-export of an imported world produces the same ids, which is
what makes the round-trip test in §13.1 an equality assertion rather than a
structural one.

`scope.kind` is a synset and `scope.zone` is a zone id. Both are already stable
identifiers that mean the same thing on every server, and neither is rewritten.

### 3.3 The vocabulary half is a ruleset

`vocabulary` is a ruleset document. Same sections, same validator, same writer.
A world that invented `smoulder`, a `scorched` condition and four rules about
them exports them as a ruleset would have declared them, and imports through
`rulesets._apply`.

That is worth the constraint it imposes, because it buys the check that matters
most: `_undeclared` already refuses a document whose rule names a kind, trait,
state or action that neither the document nor anything it requires declares.
Its docstring says why -- such a rule "will never gather, which fails by doing
nothing, the worst way there is". An imported world is precisely where that
failure would otherwise land, because it is the one case where the rules and
the vocabulary crossed a machine together and could have been separated on the
way.

Two consequences:

**Ruleset-sourced rules do not export.** A rule whose `source` starts with
`ruleset:`, or is `standard`, belongs to a ruleset the document already names
in `requires`, and exporting it would mean importing it twice. What *does*
export is the world's decisions about them -- a rule suspended with
`rules suspend` stays suspended, which `rulesets._decisions` already carries
across a version bump for exactly this reason.

**`SECTIONS` grows by two** -- `token_lists` and `pronouns`. Both are world
vocabulary, both are written through a register's own writer
(`token_lists.register_many`, `pronouns.register`), and a ruleset could ship
neither. Adding them makes rulesets strictly more useful and makes the world
document one format rather than one-and-a-bit. It is done honestly, because
`rulesets.py` is explicit that "a section nobody reads is a promise nobody
keeps" and the `affordances` section that sat in a shipped ruleset doing
nothing is the scar: each gets a reader in `_apply` in the same commit.

**As built: noun folds needed no section.** The plan said three. `verbs` has
always carried both halves -- `rulesets._fold` passes `noun` straight to
`folds.fold`, which writes to `noun_folds` instead of `verb_synonyms` -- so a
noun fold exports as a `verbs` entry with `"noun": true` and nothing was added
for it. Worth recording because it is the shape of most of this work: the
register that looked like it needed a new door already had one.

**As built: a condition is written out whole.** A ruleset names a state inside
its group, which is enough when the ruleset is introducing the word. A world's
states already have meanings, conflicts, bonuses and sometimes a definition
(`when` makes a state worked out rather than set), so a `conditions` entry may
now be a group *or* a state written out in full, and `_apply` reads both. A
document carrying only the spelling would have imported a world in which
`starving` meant nothing.

They are shown under `lists` in §3.1 for readability; in the file they are two
more sections of `vocabulary`.

### 3.4 The map half

```json
"map": {
  "zones": { "...": "world_root.db.zones, verbatim -- ids are slugs already" },
  "rooms": [
    {
      "id": "the_gym",
      "title": "The Gym Block",
      "description": "A high hall smelling of {smell} and floor polish.",
      "choices": {"smell": "rubber"},
      "at": [2, -1, 0],
      "zone": "gym_block",
      "type": "gymnasium",
      "category": "destination",
      "kinds": ["gymnasium.n.01"],
      "states": [],
      "styles": {},
      "trait_bonuses": {},
      "bonus_when": ""
    }
  ],
  "ways": [
    {"name": "north", "from": "the_corridor", "to": "the_gym",
     "aliases": ["n"]},
    {"name": "east", "from": "the_gym", "pending": true,
     "hint": "changing rooms", "aliases": ["e"]}
  ]
}
```

*As built*, a way carries no id of its own -- nothing refers to a way -- and it
carries its aliases, because `n` for north is put on by `direction_aliases`
where a room is built and an import builds no room from anywhere.

Four things in there are not obvious.

**`at` is the coordinate, and it is why import does not walk.** `_create_room`
places a room either at the origin or one step from where the player came,
because that is how a world grows. An import is not growing a world, it is
laying one out, and a world that closed back on itself would not survive being
rebuilt by walking it. So import places by coordinate directly through
`coords.place`, and §7.3 says how.

**`choices` is what the word lists already chose.** A description keeps its
tokens in storage -- `token_lists` settles a choice once and records it under
`token_choices` on the holder -- and the seed is `world_root.id` among other
things. An imported world has a different root id, so re-settling would produce
a different smell. Carrying the choices is what makes "the world as it stands"
true of its prose and not only of its objects.

**A pending way exports as pending.** `_make_ai_exit` leaves a way that
promises a room nobody has built, and `ensure_frontier` exists because a world
whose frontier reaches zero is a world that has stopped growing. An import that
resolved pending ways into nothing would hand somebody a sealed world; one that
generated them would spend their money before they had walked anywhere.

**Zones export verbatim**, except for the room ids inside them. Zone ids are
already slugs of zone names, which `zones.py` chose so that older worlds
carried over without a migration; the same property makes them portable, and
the room records name their zone by the same id. A zone record's `rooms` list
holds dbrefs, and those become local ids like every other reference.

**As built: the document is sorted, not walked.** Things, people and ways come
out ordered by id rather than in the order the world was walked. A walk follows
creation order, and an imported world creates its people before its things and
its things holder-first, so the same world exported twice listed the same
objects in two orders -- and the round-trip test would have been comparing
arrangements rather than worlds. A sorted document also diffs.

**As built: a kind exports `accepts`, not `holds`.** `kinds.remember` takes
`accepts` and answers `holds`, which is the declared placements plus whatever
the taxonomy already knew. Writing the answer back in as the question is exact
rather than lossy: the floor is re-added on the way in, so a second pass
changes nothing.

### 3.5 Things, people and errands

A thing exports as the spec that would have made it -- which is close to
literally true, because `clothing.create` takes exactly this dict from the item
generator today:

```json
{
  "id": "brass_key",
  "name": "a small brass key",
  "description": "...",
  "kind": "key.n.01", "kinds": ["key.n.01"], "qualifiers": ["brass"],
  "affordances": {"get": true, "unlock": true},
  "states": ["clean"],
  "takeable": true,
  "at": "the_gym",
  "relation": {"to": "oak_table", "how": "on"},
  "owner": {"name": "Mrs Hallow", "of": "mrs_hallow"},
  "choices": {},
  "trait_bonuses": {}, "bonus_when": "", "bonus_while": "",
  "clothing_type": "", "styles": {}
}
```

`rulebooks.CREATED_FIELDS` already names what a filled-in `create_object`
effect keeps from the item generator's answer, for exactly this purpose: it is
very nearly this list.

**As built: the relation is read from `relations.relation_of`, not from the
`relation_to` attribute.** Only the pointer relations -- under, behind -- ever
set that attribute. A lamp *on* a table is inside it as far as the database is
concerned, and its preposition lives on `db.relation` with nothing pointing
anywhere, so reading the attribute exported the lamp as merely being in the
table and it came back in it. Found by the world-to-world half of the round
trip in §13.1, which is exactly the failure that half exists for: both
documents agreed, and both were wrong.

**As built: `styles` rather than `wearstyle`.** How a thing is in a condition
-- "tied loosely around her waist" -- is `verbs.styles`, a map over every
condition, and being worn is only the one `clothing.create` takes an argument
for. The map travels whole.

A person is the same idea over the NPC writer in `world/makers/things.py`:
name, description, manner, pronoun set, kinds, states, styles, their figures
and what each stands at, what they want, what they are wearing and carrying
(things whose `at` is their id), and who they are following.

**As built: what somebody wants is `goal`, and the form that wrote it was
wrong.** `create person` wrote it to `goal_conditions`, which nothing anywhere
reads, while `npc_gen` writes `goal` through `goals.sanitise` -- which is what
the planner, `view score` and every goal condition ask. So a character
somebody typed wanted something no system in the game knew about. Fixed in
`makers/things.py` rather than carried in both, which is how it was found:
this document had to say which of the two a person's want *is*, and there was
only one honest answer.

An errand is `quests.blank_spec` verbatim, with `givers[].npc` rewritten to a
person id and its id moved to `key` so that a rebuilt world's errands are the
same errands. Errands already live on the world root rather than on the
character who offers them -- `player-building.md` §10 settled that -- which is
what makes them exportable at all.

### 3.6 What a world has learned

`learned` carries the registers that are neither vocabulary nor contents:
`attempt_counts`, `verbs_without_rules`, `verbs_that_cannot_be_said`,
`declined_suggestions`, `rule_failures`, `standard_rules_version`,
`rule_counter`, the quest counter, and -- **as built** -- `verb_rules`, the
per-verb cache from before the rulebooks, which `verb_gen.store_rule` still
writes and which is still worth exactly what it cost. It was found by the
attribute test in §13.2 rather than by anybody remembering it, which is the
whole of why that test exists.

These are carried rather than left, and the reason is money. `attempt_counts`
is what has been tried and how it went; `verbs_without_rules` is the list of
verbs a model was already asked about and had nothing to say; and
`declined_suggestions` is a decision somebody made. An import that dropped them
would re-ask every one of those questions on somebody else's key, which is the
opposite of what "pay once, for the part that generalises" means.

The counters are carried for a duller reason: `rulebooks.add` names rules `r1`,
`r2`, `r3` from `rule_counter`, and a world whose counter restarted would issue
an id that a suspension decision or a suggestion's `overrides` already names.

---

## 4. What does not travel, and why

Said out loud, because every one of these is something somebody will expect and
the honest place to disappoint them is here.

**Memories.** A world's memories are a mnemosyne bank -- a SQLite file keyed by
the world's dbref -- and they are not a description of the world, they are a
record of what happened to whoever was in it. They also contain player speech,
which is the one thing in this game that is unambiguously somebody's own. An
imported world arrives with nobody remembering anything, which is the right
thing for a world you have never played.

There is one part of memory that could travel later and should not now: `memory.py`
notes that one bank per world made it possible to remember something "about a
world rather than about one person in it", and those world-scope memories are
about the place. If a later plan wants them, they are a section; they are not
this plan.

**Spend, rounds and the ledger.** Per account, and the importer's own.

**Player characters.** Their per-world names and descriptions, their traits,
their quests in progress, their inventory. A world document describes a place,
not the people who visited it. `lore.spec_of` carries `player_name` and
`player_description` for `reset world`; export drops both, because they are
what *you* looked like there.

**Ownership by a player.** A thing owned by a player character exports its
owner's *name* and not their id, and imports as a thing somebody who is gone
once owned. That is not a fudge: `ownership.orphaned` is an existing, named
state with a comment explaining that the distinction from never-owned is kept
"only so that the *record* can still tell them apart afterwards". This is the
case it was kept for.

**Worldmode.** How hard a world thinks is how much its owner spends, and the
importer is the one paying. The importer's default applies. `generation` --
what a world is *allowed* to grow by itself -- does travel, because that is
what its author meant the world to be rather than what they were willing to pay.

**Who made it.** The importer becomes the creator, the payer and the owner.
There is nowhere in a document for an account on another server, and
`sponsor.claim` is the one write.

### 4.1 Things in a player's hands at export

The one case with no clean answer. A player who exports a world while holding
its crowbar exports a world with no crowbar in it.

**Recommendation: carried things come back loose in the room that character was
standing in, and the export says so in the line it prints.** A world missing its
crowbar is broken; a world with a crowbar on the floor is not. The alternative
-- dropping them -- silently breaks a puzzle, and the other alternative --
exporting the player's inventory as an inventory -- puts a player character in
a document that has no player characters in it.

---

## 5. Reading a world out

`world/exchange.document(root)` returns the dict. It is the only reader, and
everything else -- writing the file, setting the restore point, `view world` --
calls it.

It walks in the order §3.1 lists, because that is the order import needs and a
document whose sections are in build order can be read straight down.

**As built: the maker table is not the spine, and this is where the plan was
wrong.** It said each maker would gain a `record(root, ident)` and export
would be the table walked. It is not. A maker's `listing` adapter exists so a
*menu* can offer what a world holds, one prose line each; a document wants the
register, and every register already answers with the whole of itself --
`kinds.spec`, `traits.vocabulary`, `rulebooks.all_rules`, `quests.specs`,
`token_lists.vocabulary`. Fourteen `record()` methods would each have
forwarded to the reader beside it.

The promise `making.py` made in its docstring -- "`export world` and `import
world`, later, are this table serialised" -- is kept, but by the **writers**
rather than by the readers. Nothing in §7 writes an attribute that a maker's
form does not write through the same function; that is the half that had to be
true, and it is. What guards the arrangement against drift is not a method on
the table but §13.2, which catches an attribute nobody has decided about
whether a maker exists for it or not.

The four room-local makers -- `item`, `room`, `way`, `person` -- therefore
gained no `listing_everywhere` either. `exchange.rooms_of` and
`exchange.contents_of` walk the world once, from the rooms, which is the same
walk `clear_world` does and the only walk anything here needs.

**As built: `tests/fixtures/export.py` reads `exchange.plain` and keeps
everything else.** It has a different job -- registers only, prose
deliberately excluded, one file per world, generations in subdirectories --
and the plan was right that its `_plain` was a second copy and wrong that its
`REGISTERS` tuple was. That tuple is a deliberately narrower selection than a
world document, and saying so is the point of the module.

---

## 6. Refusing a document

`exchange.problems(doc)` returns a list of short sentences, `[]` when there is
nothing wrong, and is run to completion before a single object is made.

Nothing is imported by halves, for the reason `rulesets._refuse` gives: half a
ruleset is a world whose rules mention states nothing registers, which is worse
than not having it. Half a world is worse still.

What it checks:

1. **Version.** `aimud` is a number this server knows.
2. **Structure.** Every section is the type it should be; no section it does not
   know (the same refusal `rulesets.problems` makes, and for the same reason).
3. **The vocabulary half**, by handing it to `rulesets.problems` with the
   requirements resolved -- which gets `_undeclared` for free.
4. **References resolve.** Every room, thing, person and way id named anywhere
   exists in its own section. A door onto a room that is not in the document is
   a fault, not a pending way.
5. **The map is a map.** No two rooms at one coordinate (`coords` guarantees
   this and an edited document could break it), every way's `from` and `to` in
   the room list, every room in a zone the `zones` section declares.
6. **Requirements are here.** Every ruleset named in `requires` exists on this
   server at a version at least as high (§14).
7. **Caps.** §11.

A fault names the section and the id: `"the way 'east' in 'the_gym' goes to
'changing_rooms', which is not in this document"`. A document that fails is not
imported and the file is not touched.

---

## 7. Building a world from a document

*As built:* `exchange.build(doc, account, character)`, and it answers with the
world's first room rather than taking callbacks. There is no model call in it,
so there is nothing to wait for and nothing to be called back about; the
callback pair in the plan was copied from `generate_first_room`, which has a
network request in the middle and needs them.

It raises `Refused`, carrying every complaint rather than the first, and
`problems` runs to completion before anything is made. **As built**, there is
a second guard behind that: an unexpected failure part-way through the
building -- a fault in this code rather than in the document -- tears down
what it had made and raises `Refused` as well. Somebody left owning half a
world with no first room has no way to say so, and `clear_world` is the one
that knows how to take a world away.

### 7.1 The world, first

`worldgen.first_room_by_hand(sponsor, doc["setup"], ...)`, which is exactly
what it is for: a world root with no model call, with the title, description,
guidance, clock, rulesets and permits written by `lore.store`, claimed for the
account and added to `created_worlds`. The room it makes becomes the document's
first room, renamed and described in pass three.

The rulesets named in `setup` are applied here, by `lore.store`, which is why
they must be checked in §6 before anything is built.

### 7.2 Vocabulary, before anything that could name it

`rulesets._apply`-shaped, in `SECTIONS` order, rules last. Word lists before
descriptions, because a description's `choices` names a list; conditions before
things, because a thing's `states` names one; kinds before rules, because a
rule's scope names one.

### 7.3 The map

Rooms are created through `worldgen._create_room` with `source_room=None` and
`arrival_exit=None`, which places them at the origin -- and then moved to their
recorded coordinate with `coords.place`. That is one line of correction rather
than a new creation path, and it keeps every other thing `_create_room` does:
the zone attach, the type record, the kind settling, the token declaration.

The first room of the document is the one `first_room_by_hand` already made,
so it is written rather than created.

Ways are made with `worldgen._make_exit`, with `pending=True` and the hint for
the ones that promise a room nobody built. Both directions are in the document,
so nothing is inferred: `_create_room`'s automatic back-exit is not wanted here
and is skipped by passing no `source_room`.

Then `zones` is written onto the root verbatim, after the rooms exist, so that
the registry is not rebuilt from a half-built world on first read.

### 7.4 Contents, and then the pointers

Things through `clothing.create(spec, location)` and people through the same
sequence `world/makers/things.py` `keep_npc` uses. Both in two passes: make
everything, holding the local id → object map, then resolve. Resolution is
`relations.place` for hosts, `ownership` for owners, `quests.save_spec` for
errands with their givers rewritten, and `rulebooks.add` for the rules whose
scope names an object or a room.

A thing whose `at` is a person is created in that person's inventory; a thing
worn is worn through `clothing`, which is what makes a guard's breastplate
protect exactly as well as one found in a chest.

### 7.5 What import must not do

It must not call a model, must not call `ensure_frontier` (a document's pending
ways are its frontier, and a world whose author closed it deliberately must
stay closed -- `ensure_frontier` already refuses when `permits` says rooms are
`never`, and this is the second case), and must not run the contents pass.

---

## 8. The restore point

One new attribute on the world root: `restore`, holding a world document.

* `import world <name>` sets it to the document imported.
* `export world <n>` sets it to the document just written, so exporting is also
  "save this as what a reset comes back to".
* `reset world <n>` replays it when there is one, and regenerates from the
  setup exactly as it does today when there is not.

**Why the document and not the file's path.** A path can be deleted, moved, or
replaced with a different world by somebody else with write access to the shared
folder, and a reset that silently rebuilt a different world would be the worst
bug this feature could have. The cost is storage: a world document is a few
hundred KB for a large world, held twice. `basic-principles.md` is explicit that
disk is an acceptable thing to spend.

**The reset flow is unchanged in shape.** `_reset` already builds the new world
before removing the old one, moves characters into it, and leaves the old world
untouched if the build fails. A replay is faster and cannot fail for lack of a
key, but it fails the same way.

**The question it asks has to say which reset this is**, because the two are
genuinely different promises:

* with a restore point: *"Put Netherfield Hall back as it was when it was
  imported on 25 September, destroying all 34 rooms as they are now?"*
* without one: *"Destroy all 34 rooms of Netherfield Hall, with everything in
  them, and generate the world again from its setup?"* -- which is what it says
  today.

`view world <n>` gains a line saying whether there is a restore point and when
it was taken, so that nobody has to reach the confirmation to find out.

`reset world` on an imported world needs no API key, which is a real change:
`_key_problem` is asked of the spec today and must not be asked when there is a
document to replay.

---

## 9. The shared folder

```python
# Directories holding world documents this server can import, the first of
# which is where `export world` writes. A world document is validated JSON and
# never code, exactly as a ruleset is. See world/exchange.py.
WORLD_DIRS = [os.path.join(GAME_DIR, "worlds")]
```

Read the way `rulesets.directories()` reads its own: the first is the writable
one, all of them are searched, a later directory wins a name collision. It is
gitignored, alongside `server/`.

**A file is named from the world, never by the player.** `slug(title).json`,
uniqued with a number. The player types `export world 2`; they never type a
filename, and no string a player controls reaches a path component without
going through the slug. That is the whole of the path-traversal defence and it
is worth being able to state in one sentence.

**`view exports`** lists what is in the folder: title, room count, when it was
taken, what it requires, and whether this server can take it -- the last read
from `requires` without parsing the document whole.

**`delete export`** removes one. Whoever wrote it may delete it, tracked on the
account (`exported_worlds`) rather than in the file, because a shared file
should not name an account. A builder may delete any.

---

## 10. The commands

Two `Use` entries on the existing world subject in `commands/world_subject.py`,
and one new subject for the folder.

```
export world [<number or title>]     # writes the file, sets the restore point
import world [<name>]                # builds a world from one
view exports                         # what is in the shared folder
delete export <name>                 # remove one you wrote
```

Each answers bare, with a menu of what it could act on, exactly as
`delete world` and `reset world` do -- `_which_world_form` is the existing
helper and `export` is another verb through it. Import's menu is a list of the
folder's documents.

Both confirm. Export's confirmation is about the restore point moving, not
about the file:

> *Write Netherfield Hall to the shared folder, and make this the state
> `reset world` comes back to?*

Import's says the thing that actually matters, and §11.4 is why:

> *Build a world from 'the-school', 34 rooms, made by somebody else? Its
> descriptions and its characters' words will be sent to your model on your
> key when you play it.*

---

## 11. Safety

`README.md` is direct about what this codebase has and has not been audited
for, and importing another person's world is the first feature in it where data
somebody else wrote is executed -- in the loose sense -- by your server on your
key. So this section is not boilerplate.

**11.1 A document is data and never code.** The same bar `rulesets.py` holds:
validated JSON with no executable part. Nothing in a document can be a Python
path, a callable, a module name, or a lock string. Everything it says goes in
through a writer that already validates its own input, and anything a writer
refuses is refused here.

**11.2 Nothing is written raw.** Import never sets an attribute from a document
directly. Every value goes through the function the game already uses, so
folding, normalisation and the caps in `conditions.normalise_all`,
`token_lists.register_many` and `traits.register` all run. This is the
difference between an import and a database restore, and it is the reason the
format is a document rather than an attribute dump: a raw dump would put a rule
naming a state nothing registers into a live world with nothing to catch it.

**11.3 Caps, checked before parsing where possible.** Proposed, and all of them
are "larger than a world anybody plays, smaller than a denial of service":

| | cap | why |
|---|---|---|
| file | 8 MiB | the largest exported register set today is 88 KiB; a 100-room world with prose is single-digit MB |
| rooms | 2000 | a world nobody could walk |
| things | 20000 | |
| people | 2000 | |
| rules | 5000 | the seven development worlds hold 326 between them |
| any one text | 8000 chars | a description, not a novel |
| ids | 64 chars, `[a-z0-9_]` | slugs |

The file size is checked before the file is read, because a document is parsed
whole into memory.

**11.4 Prose from a document reaches a model.** Room descriptions, a world's
description, its guidance and a character's words all go into prompts, and an
imported world's were written by somebody else. That is a real surface and it
has not been explored -- `README.md` says so about a player's own text already.
The mitigations here are: say so in the confirmation (§10), keep the token
grammar closed, and nothing else. It is not solvable by this plan and should
not be claimed as solved.

**11.5 Tokens cannot read attributes.** `world/tokens.py` already refuses this
-- its comment notes that "a world that could write `{direct.db.api_key}` would
be" the problem it is preventing -- and a world document is another way for
such a string to arrive. A test should assert it from the import side, because
the check existing is not the same as the check being reached by this path.

**11.6 An import is not a builder command.** Any player may import; what they
get is a world of their own, owned by them, paid for by them, in their own
`created_worlds`. Nothing in a document can reach another account's world, and
nothing in it can name an account at all.

---

## 12. What it costs: nothing

No model call in export, in validation, in import, or in a reset that replays a
document. A server with no API key can import a world, walk it, and reset it.

That is the same hard constraint `player-building.md` §12 set, and it matters
for the same reason: it is what makes a world somebody shares playable by
somebody who has not paid for anything. Combined with worldmode `none` --
`future-plans.md`'s shared-worlds item -- an imported hand-built world is a
complete game that costs nothing to run.

---

## 13. Testing

### 13.1 The round trip is the test

Build a world, export it, import it, export the result: the two documents are
equal. Not equivalent, equal -- which is what the slug ids in §3.2 are for.

It is the only test that can catch a field that export forgets, because a field
nothing writes out is a field the second document also lacks -- unless the
comparison is against the *world*, which is why there is a second half:

Build a world, export it, import it, and compare the two worlds: same room
count, same coordinates, same kinds, same states, same rules by name, same
errands, same things in the same places. A helper (`tests/support.py`) does the
comparison once and both halves use it.

The worlds to run it against:

* a hand-built world in the test itself, which phases 1 to 6 of
  `player-building.md` made possible and which needs no model;
* the flagship worlds from `future-plans.md` once they exist, which is the
  acceptance test for both plans at once;
* a generated world, in `tests/live.py`, where a model is available.

### 13.2 The test that stops export rotting

Export is complete on the day it is written and silently incomplete forever
after, unless something says so. A new attribute on a room is added by somebody
working on rooms, and no test they run fails.

So: an AST pass over `world/`, `typeclasses/` and `commands/` collecting every
`.db.<name> = ` assignment and every `attributes.add("<name>"` call, asserted
against two lists in `world/exchange.py` -- `CARRIED` and `LEFT`. A name in
neither fails the test with "the attribute `foo` is written in
`world/bar.py:91` and the world document neither carries it nor says it is left
behind."

This is the arrangement `effects.VOCABULARY` already has with `_apply_one`,
where the module notes that "adding an effect without an entry here is caught
by a test", and the AST approach is the one `tests/base.py` already used to
categorise the suite. `LEFT` is not a denylist to be filled in silently: each
entry carries the one-line reason, and §4 is that list in prose.

### 13.3 Refusals

One test per fault in §6, each asserting that nothing was built. A document
that fails validation must leave no room, no object and no world root behind --
which means validation runs to completion before `first_room_by_hand`, and a
test asserts the object count is unchanged.

---

## 14. What a world requires

`requires.rulesets` is a map of name to version. Import refuses a document
naming a ruleset this server does not have, or has at a lower version, and says
which -- because the alternative is a world whose rules gather nothing and
whose failure is silence.

A *higher* version on this server is accepted. `rulesets` already handles this
case properly: `_retire` removes the old edition's rules by their `source` mark
and seeds the new one, carrying suspensions across by name. An imported world
simply arrives having had that done to it.

`requires.plugins` is in the format and empty, and that is deliberate.
`future-plans.md` says worlds "need to say what plugins they require if any",
and the affect-plugin item is a separate plan that does not exist yet. A field
that is always empty is a promise nobody keeps, so the rule for now is: export
writes it empty, validation refuses any document with anything in it, naming
the plugin and saying this server cannot take it. That is honest, it is two
lines, and it means a document written after plugins exist is refused clearly
by a server from before them rather than imported wrongly.

---

## 15. Phases

Each ended with the suite green. What each came to is under it.

**Phase 1 -- the document, and reading one out.** `world/exchange.py` with
`document(root)`, and `token_lists` and `pronouns` added to
`rulesets.SECTIONS` with their readers in `_apply`.

*As built:* the makers gained no `record()` and no `listing_everywhere()`, and
that is the one place this plan was wrong about its own architecture. A
maker's `listing` adapter exists so a *menu* can offer what a world holds, in
prose, one line each. A document wants the register, and every register
already answers with the whole of itself -- `kinds.spec`, `traits.vocabulary`,
`rulebooks.all_rules`, `quests.specs`. A `record()` per maker would have been
fourteen functions each forwarding to the reader beside it, and the table's
real promise ("export world and import world, later, are this table
serialised") is kept by the *writers*: nothing here writes an attribute that a
maker's form does not write through the same function. What guards the table
against drift is not a method on it but §13.2, which catches an attribute
nobody decided about whether a maker exists for it or not.

**Phase 2 -- refusing one.** `problems(doc)`: the version and kind, the shapes,
the caps, `requires`, `rulesets.problems` over the vocabulary half, the map,
and every reference. Sixteen refusal tests, each asserting the object count is
unchanged as well as the complaint.

**Phase 3 -- building one.** `build(...)`, the passes, the reference
resolution, and `Refused` carrying every complaint rather than the first.

**Phase 4 -- the round trip.** Both halves, and it found four things phases 1
to 3 had wrong: a lamp on a table came back in it (§3.5), the document was
ordered by creation rather than by id (§3.4), a kind exported its answer
instead of its question (§3.4), and an import settled word lists the original
world had not settled yet. That last is the one worth keeping in mind: an
import must write what the document says **and nothing else**, even where the
thing it would otherwise do looks harmless.

The AST test found two more: `verb_rules`, still written and never listed, and
five account settings -- an API key among them -- that nothing had said a world
does not carry.

**Phase 5 -- the restore point.** `restore` on the root, `_replay` beside
`_reset` in `world_subject`, the two confirmation questions, and the `view
world` line saying which reset yours will do. `_key_problem` is not asked when
there is a document to replay, which is the change that makes a reset free.

**Phase 6 -- the shared folder and the commands.** `WORLD_DIRS`, `export world`
and `import world` as uses on the world subject, `commands/exchange_subject.py`
for `view exports` and `delete export`, three confirmations, `exported_worlds`
on the account, and the gitignore line.

**Phase 7 -- requirements.** `requires.rulesets` checked by name and version,
with a higher version here accepted; `requires.plugins` refused by name.

**Phase 8 -- documentation.** The README's command reference, its architecture
table, and two honest paragraphs: one under "Before you host this anywhere"
about an imported world's text reaching your model on your key, and one under
"What is safe to publish" about what a world document does and does not hold.

Two things this changed outside its own files, both tests that were right until
they were not. `test_verbs` asserted `import world` was claimed by nothing,
which stopped being true the moment a world could be imported.
`test_token_lists` forbids any module in `world/` reading `db.desc` raw, and
`exchange.py` is the second module allowed to -- it is writing the text down
rather than showing it, and expanding a token here would bake one world's
choices into every copy of it.

A ninth is not a phase of this plan but is the point of it: **ship a world**.
Hunt the wumpus is the small one and is the right first test of whether a
document can carry a whole game.

---

## 16. Decisions

**The world as it stands, not the world as authored.** An export is a
photograph: a door left open exports open, a thing moved exports where it was
moved to. "Export the entire world" is what was asked for, and it is what makes
a restore point mean a place rather than a recipe.

**A document replayed through the writers, not a snapshot of the database.**
Every value goes in through the function the generators and the forms already
call, so an imported world cannot hold a rule that names nothing, and nothing
is written that a player could not have typed. The cost is that a field no
writer takes cannot be carried -- which is what §13.2 exists to make loud
instead of silent. §11.2.

**Importing sets the restore point, and so does exporting.** A world you built
and exported resets to what you exported; a world you imported resets to what
you imported; a world that has done neither regenerates from its setup, as
today. One rule, three cases, no new gesture to learn. §8.

**The vocabulary half is a ruleset, and `SECTIONS` grows to make it true.**
Reusing `problems` and `_apply` is worth adding two readers for, and a ruleset
that can ship a word list and a pronoun set is better than one that cannot.
§3.3.

**Slugs, not indices, not dbrefs.** A document that reads, and a round trip
that can assert equality. §3.2.

**Carried things come back to the floor.** §4.1.

**Memories do not travel.** §4.

**The makers gained no `record()`.** The one architectural expectation this
plan got wrong, kept here rather than quietly dropped: a maker's `listing` is
for a menu and a document wants the register, which every register already
answers with whole. The table's promise is kept by its writers, and the guard
against drift is the attribute test rather than a method. §15, phase 1.

**An import writes what the document says and nothing else.** Not what the
writers would otherwise have worked out: not a re-settled word list, not the
affordances a kind has since gained. Found by the round trip, and it is the
sentence the whole of "the world as it stands" rests on. §15, phase 4.

---

## 17. Open questions

**How a player gets a file to the server, and gets one off it.** This plan
takes the shared folder as given, which answers "player to player on one
server" and nothing else. Getting a document from one aimud to another means
somebody with shell access moving a file. That is the same bar
`basic-principles.md` sets for plugins and rulesets and it is not a bad answer,
but it is not the answer for MSP sounds, resource packs, or a world downloaded
from somebody's website -- which are one problem and not three, and which
`future-plans.md` raises without settling.

Two shapes worth investigating when it is scoped, neither in this plan:

* **A fetch, not an upload.** `import commonsense` already downloads a large
  file over a confirmation, and `basic-principles.md` permits "on-demand
  in-game resource downloads" as one of the strictly scoped network surfaces.
  `import world from <url>` is the same gesture, and it inverts the hard part:
  the server pulls from somewhere the player names rather than accepting bytes
  from a connection. MSP already works this way -- a sound is a URL.
* **Federation.** `future-plans.md` names I3, IMC, ActivityPub, XMPP and Matrix
  for chat, and a world document is a file another aimud could offer. That is a
  much bigger plan and should not be pulled into this one.

The thing this plan does that matters for either: a world is one self-contained,
validated, human-readable document with no dbrefs, no paths, no accounts and no
code in it. Whatever eventually carries files, that is what it carries.

**Should a document be signed, or carry who made it?** Not in this plan --
there is nothing to verify a signature against, and a name in a shared file is
an account reference in a document that deliberately has none. Worth revisiting
with federation, where there would be a server to attribute to.

**Do world-scope memories travel later?** §4 says not now and says why. The
question is whether an innkeeper who has met people is part of the world or
part of what happened in it.
