# Development plan: pronouns and ownership

Status: **phases S, P0, P1, P2, P3, M and P4 are built**; P5 onward is
proposed. P4's world reset has been completed. Where the building turned up something the plan had
wrong, the section says so rather than being quietly corrected -- §5.4 is the
one that matters.

Companion to `development-plan.md` (rulebooks) and `rules-and-rulebooks.md`.
Its ground rules (§2 there) are acceptance criteria here too, unchanged.

**`future-plans.md` is the roadmap this plan is written against.** Every
"because the roadmap wants" below refers to it. It is also where anything
uncovered during this work that is worth doing later should be written down,
rather than left in a commit message.

The build sequence is §9. Decisions already taken are recorded in §10.

---

## 1. The change, on one page

English has three things a MUD parser has to understand that this game does
not yet: **who "her" is**, **whose the sword is**, and **when to say "she"
instead of "Jessica"**. The first two are parsing, the third is narration, and
they are the same fact read in two directions -- which is why they are one
piece of work rather than two.

Underneath both is a thing the codebase has been growing by accretion: **the
noun phrase**. Six modules each know a little about what one looks like, and
each carries its own list of words to ignore:

| Module | What it knows about a noun phrase |
|---|---|
| `verbs.parse` | noise words, prepositions, leading adverbs |
| `verbs.ordinal` | "the second wrench" |
| `verbs.plain` / `_words` | noise words again, lemmatising |
| `bulk.split` | "all", "every wrench" |
| `anatomy.split_owner` | "Samuel's shoulder", "her hand" |
| `naming._NOISE` | noise words a third time |

`verbs._NOISE`, `naming._NOISE` and `anatomy.ARTICLES` are three copies of one
list and they already disagree: `verbs._NOISE` holds "my" and "your",
`anatomy` treats them as owners, `naming` drops them. Adding possessives and
pronouns to all six places would make it six copies of two lists, and the
first bug would be silent.

So the work is five things:

1. **One noun-phrase reader** (`world/nounphrase.py`). Everything above becomes
   a consumer of one structured record. The largest single change, and what
   makes a possessive or a pronoun a one-place addition rather than a
   six-place one.
2. **A pronoun register per world** (`world/pronouns.py`), shaped like the
   state and trait vocabularies that already exist.
3. **A referent table per character** (`world/referents.py`) -- what "her" last
   meant. Used by the parser to resolve and by the narrator to decide whether
   to pronominalise. The one genuinely new mechanism.
4. **An ownership relation** (`world/ownership.py`), shaped like
   `world/relations.py`, with one condition predicate and one effect.
5. **Per-recipient message rendering**, replacing the single broadcast string.
   Required by pronoun narration, and the backbone of several roadmap items
   (§8.1).

Memory turns out to need rebuilding alongside this rather than after it (§7),
for reasons that are about mnemosyne's shape rather than about pronouns.

---

## 2. Why the parser gets a grammar and not a parser generator

### 2.1 The noun phrase, not the sentence

The sentence level needs no grammar. The first word is the verb, prepositions
delimit the roles, and there are no relative clauses, no conjunction and no
attachment ambiguity. `verbs.parse` is seventy lines and is not where anything
fails.

The noun phrase does, because it is genuinely recursive and is where everything
fails:

```
Command    := Adverb* Verb NP? (Preposition NP)*
NP         := Quantifier? "of"? Determiner? Possessive? Ordinal?
              Modifier* Head
           |  Pronoun
Possessive := PossessivePronoun | NP "'s"
Head       := Noun | PronounObject
```

Written as a small recursive-descent reader -- not a parser generator -- that is
about 150 lines, and it is the only place that ever has to know what "the" is.
"all of her second-best wrenches" parses; so does "all of them"; so does
"Jessica's brother's sword", which is where the recursion earns its keep.

Three reasons not to reach for a library or a POS tagger:

* **It would make the dictionary load-bearing.** `lexicon.py`'s contract is
  that a missing WordNet makes the world clumsier and never impossible. A
  grammar needing to know whether "slate" is a noun or an adjective breaks that
  on the first line. The grammar above never asks: everything before the head
  is a modifier and the head is the last word. That rule is wrong about English
  in general and right about every object name this game generates, because
  `verbs.naming_rule()` is what wrote them.
* **The lexicon is invented at runtime.** Object names here are "Dried-Out
  Marker" and "Stained Slate Chalkboard", conjured minutes ago. A tagger
  trained on newswire has opinions about those and they are not useful.
* **Weight.** spaCy with a model is ~500MB against an 11MB WordNet this project
  already vendors reluctantly.

**The model to follow is Inform 7, not Chomsky.** This project already
reimplements Inform's rulebooks. Inform's answer to "get her sword" is not a
grammar but *scope* plus *"does the player mean"* rules -- a ranking over
candidates in reach, which `verbs.bind` already is. Its pronoun handling is a
small table holding one object each for `it`, `him`, `her` and `them`,
rewritten after every successful action. That is §4.3, and it is the right
size.

### 2.2 What the generators get out of it

`rule_gen`'s `_CONDITIONS` and `_EFFECTS` blocks are hand-written prose listing
the JSON a model may emit, and `verb_gen`'s narration prompt is hand-written
prose about `{actor}`. Both drift from the code that reads them. A written
grammar gives the command generator a statement of what a player can actually
type, the rule generator a role vocabulary that includes possession -- so a
rule can say "you may not take what is not yours", which today shows up in the
corpus as `cannot_say` -- and the narrator placeholders for every participant
rather than only the actor (§5.4).

### 2.3 No pronoun library

The content is five forms by however many sets a world has: thirty lines of
table. **Evennia's own `$pron()`** (`evennia/utils/funcparser.py:1487`) is
already installed and shows the right *decomposition*; its *model* is a fixed
four-way male/female/neutral/plural keyed off `.gender`, which is exactly what
this game wants to stop being fixed. Its machinery turned out not to be
reachable from where the rendering has to happen -- see §5.4 -- so what is
borrowed is the five-slot shape and the conjugator, not the parser. pronouns.page and pronoun.is publish data
as web resources with a neopronoun-list shape rather than a schema, and
fetching them at runtime puts a network dependency in the parser.

So: our own register, borrowing Evennia's **five-slot schema** --
subject / object / possessive adjective / possessive pronoun / reflexive --
because it is the right decomposition and because
`verb_actor_stance_components` and `$pconj` then handle agreement (§5.1) for
free.

### 2.4 SHRDLU: one idea

**Resolution ordered by semantic fit, then recency.** SHRDLU resolved "it" by
finding the most recent referent satisfying the *current* verb's constraints,
not the most recent referent full stop. Here that is nearly free:
`kinds.admits(world_root, kinds, verb)` already answers "can this sort of thing
be opened at all", so "open it" after looking at a candle and then a box
prefers the box. Written into §4.3.

Its procedural semantics this project already does better, in rulebooks. Its
clarifying questions already exist, in `naming.instead_of_creating`. Its closed
micro-domain with a hand-written lexicon is the opposite of an emergent world.

---

## 3. What is already here to build on

* **`anatomy.split_owner`** parses possessives today -- `"Samuel's shoulder"`,
  `"her hand"`, and the punctuation-free `"samuels shoulder"` -- and
  `anatomy.resolve_owner` resolves first, second and third person. It also
  implements the rule §6.7 needs: a phrase that *states* an owner is refused
  rather than conjured, while one that only *suggests* one is let through. It
  is the prototype of the whole possessive feature, built for body parts.
* **`msg_contents` already renders per recipient.** `objects.py:1147` loops the
  room's contents running the funcparser with `receiver=` set, then
  `format_map`s every `{key}` in `mapping` through
  `get_display_name(looker=receiver)`. The narration cache already stores
  `{actor}` as a literal. The plumbing for §5.4 exists.
* **`server/conf/inlinefuncs.py` is already in
  `FUNCPARSER_OUTGOING_MESSAGES_MODULES`** -- the designated place for a
  `$who()` callable, receiving `caller`, `receiver` and `mapping`.
* **World-scoped registers** are an established pattern:
  `state_vocabulary`, `trait_vocabulary`, `kind_specs`, with
  `world/vocabulary.py` refusing collisions and `help_cmds.world_topics`
  turning each into help. A pronoun register is a fifth and inherits all three
  behaviours.
* **`world/relations.py`** is the model for `ownership.py`: one module owning
  one relation, with `test`, a setter, a `describe` and a `VERBS` tuple naming
  the verbs it takes over from the learned-verb pipeline.
* **`bulk.py`** already expands "all" into ordinary single attempts and narrows
  by a named sort. "All of them" needs it to narrow by a *kind*, which is one
  branch.

---

## 4. Pronouns

### 4.1 A pronoun set

On the world, keyed by slug, in `world_root.db.pronoun_sets`:

```python
"she": {
    "subject":   "she",     # she picks it up
    "object":    "her",     # you hand her the sword
    "adjective": "her",     # her sword
    "possessive":"hers",    # the sword is hers
    "reflexive": "herself",
    "plural":    False,     # takes "picks", not "pick"
    "means":     "for a character who goes by she and her",
}
```

Seeded with `he`, `she`, `it` and `they`. `they` is seeded rather than left to
be invented for the same reason `life_status` is seeded in `verbs.py`: it is
the one set whose `plural` is True, no model reliably works that out, and
getting it wrong makes every sentence about that character ungrammatical.

`pronouns.register()` is the one door -- shaped like `verbs.register_state`,
with the same two behaviours that keep a register from sprawling:

* **The slug is the subject form.** A set is identified in English by how it
  starts, so a declared set whose subject form the world already keeps **folds
  onto the existing one** and returns it. Sharper than `register_state`'s
  `_similar` prefix test, because pronoun forms are a small closed set of
  strings rather than open vocabulary.
* **Two sets may share a non-subject form.** "she/her" and a declared "ze/her"
  both answer to "her", which is how neopronoun sets genuinely work, so it is
  allowed rather than refused -- §4.3 step 5 asks which was meant.

A declaration must be **complete**: five forms, `plural`, `means`. An
incomplete one is dropped rather than patched, because a half-set produces
ungrammatical sentences for as long as that character exists and there is no
later moment at which the missing form gets filled in.

`plural` is validated rather than trusted, the way `DEFAULT_STATE_GROUP`
overrides a declared group: a set whose subject form is "they" is plural
whatever the declaration said.

`vocabulary.claim` still runs. Pronoun against state or kind is allowed and
reported, the way kind-against-affordance already is.

### 4.2 Who has one

Every person: `character.db.pronouns = "she"`, a slug into the world register.
Absent means `they`.

**Players** get a `pronouns` command, a sibling of `name`
(`commands/name_cmds.py`), stored the same way -- per world, through `lore`.
`pronouns` lists the world's sets, `pronouns she` picks one, `pronouns new`
walks through making one.

**NPCs** get one from `npc_gen`'s JSON and **may declare a new set**, the way
`rule_gen` and `verb_gen` declare `new_states`:

```json
"pronouns": "she",
"new_pronoun_set": { ...five forms, plural, means... }
```

`new_pronoun_set` is filled only when the slug is not one the prompt listed,
and goes through the same `pronouns.register()` the player command uses.
`pronouns.vocabulary_block(world_root)` lists the existing sets with the
"reuse an existing one whenever it fits" instruction `rule_gen` already gives
for states, and slots in beside the `traits.vocabulary_block(...)` call
`npc_gen` makes today.

The traits discipline -- drop anything unregistered -- is deliberately *not*
followed here. A trait is a shared scale, and one character measured on a scale
nobody else uses is a scale that will never be compared against anything. A
pronoun set is a fact about one person, and a world that generates a hive-mind,
a ship's computer or a creature nobody has met before must be able to say how
to refer to it. What makes that safe is the declaration channel rather than the
constraint: a word merely *used* still does nothing, a word *declared* arrives
with its meaning, and near-duplicates fold.

**Objects** have no set. They have a *number* -- one thing is "it", a pile of
coins is "them" -- read off the kind, defaulting to singular.

### 4.3 The referent table

`world/referents.py`. Per character, in `ndb` -- deliberately not persistent,
because after a reload "get it" should mean nothing rather than something from
last week.

```python
{
  "it":   <obj>,        # last non-person referred to
  "her":  <obj>,        # last person whose set uses "her"
  "him":  <obj>,
  "them": <obj>,        # last plural-set person OR last plural object
  "kind": "wrench.n.01" # what the last bound object was, for "all of them"
}
```

Keyed by **surface form, not set slug**, because that is what the player types
and because two sets can share an object form.

Written after every successful bind, by `verbs.bind_all` -- one place, so
nothing can forget -- and by the narrator when it names somebody to a viewer
(§5.3), which is why this is one module and not two.

**Resolving a pronoun, in `bind`:**

1. Candidates in reach whose pronoun set has this surface form (people) or
   whose number matches (objects).
2. Filter to those the verb could apply to at all -- `kinds.admits(...) is not
   False`. Only a definite refusal filters; silence is not a refusal, exactly
   as `bulk.matching` already has it.
3. Exactly one survives: that.
4. More than one: the referent table's entry, if still in reach and still
   surviving step 2.
5. Otherwise ambiguous. Say so, and say which -- "Which her? Jessica or
   Britney?" -- rather than picking.

Step 5 deliberately breaks `bind`'s existing contract, which resolves ambiguity
by taking the oldest because for a typed noun the alternative was a room
filling with chalkboards. A pronoun has no such failure mode -- nothing is
conjured for "her" -- so asking is strictly better.

Step 4 is what makes "greet Jessica" then "hug her" work, and it degrades
correctly: if Jessica has left, the entry fails the in-reach test and the
player is asked.

### 4.4 What this replaces

`anatomy.SPEAKER` and `anatomy.THIRD_PERSON` are the naive version of this and
must be **removed**, not left alongside. `anatomy.resolve_owner`'s third-person
branch answers only when exactly one other person is present; the real resolver
answers more often and better. Two answers to one question is what
`vocabulary.py` exists to prevent.

---

## 5. Narration

### 5.1 Agreement

"Jessica picks up the sword" and "they pick up the sword" -- the verb changes.
`verb_actor_stance_components(verb, plural=...)` already conjugates and
`$pconj()` already reads a `plural` flag, so the narration template carries the
verb as `$pconj(pick)` rather than as literal "picks", and the generator is
told to write it that way. A prompt change and a cache invalidation, and the
main reason a world reset is wanted.

### 5.2 How many pronouns, and where

**The budget is one pronoun per surface form**, not one per sentence. The
danger is a reader unable to tell two referents apart, and that lives entirely
*within* a surface form: "She hands her the sword" is unreadable, "She examines
it" is not. The rule generalises correctly to invented sets, and the common
person-plus-thing sentence reads naturally rather than stiffly.

**Which participant gets it: the one the reader is already thinking about.**
This is centering theory (Grosz, Joshi and Weinstein), whose Rule 1 is exactly
the question asked: *if anything in an utterance is pronominalised, the
backward-looking centre must be.*

The backward-looking centre (Cb) is the highest-ranked entity from the previous
utterance that also appears in this one, ranked by grammatical role -- which
maps onto the roles this game already has:

```
actor > direct > target > container > source > instrument
```

Worked through, all three about Jessica handing Britney a sword:

| What this viewer was last told | Cb | What they are told now |
|---|---|---|
| "Jessica picks up the sword." | Jessica (actor) | "**She** hands Britney the sword." |
| "Britney examines the sword." | Britney | "Jessica hands **her** the sword." |
| "The lamp gutters." | none | "Jessica hands Britney the sword." |

The third row is easy to forget and is why the theory is worth having: when
nothing carries over, **no person-pronoun is used at all**. A pronoun with no
antecedent in the reader's attention is worse than a name, and a
most-recently-mentioned heuristic produces one constantly.

The second row is what centering calls a *retain*: the Cb is still Britney but
is no longer the subject, and English signals precisely that with a pronoun in
the non-subject slot. The two sentences say different things about what the
reader has been following, and both are right in context.

This **subsumes** the ambiguity rule rather than competing with it: "use 'her'
if only one her is present, but 'her' anyway if she was the last one named" is
the Cb rule from the other end, because attention rather than headcount is what
makes a pronoun resolvable.

**Second person is free and does not spend the budget.** "You" is never
ambiguous, so a viewer who is a participant is always "you" whatever slot they
fill. "She hands you the sword" is one third-person pronoun and one second
person, and it is the best reading of that event available.

### 5.3 The algorithm, and the state it needs

Per viewer, at delivery:

```
  participants := the message's roles, ranked actor > direct > target > ...
  cb           := the highest-ranked entity of the viewer's PREVIOUS
                  participants that also appears in this one,
                  excluding the viewer themselves
  for each participant:
      viewer          -> second person
      is the cb       -> pronoun, if no earlier slot already spent
                         that surface form
      otherwise       -> name
  record participants as the viewer's new previous
```

The state is one slot per viewer: the ranked participant list of the last
message they were shown. It lives in the `referents` table on the viewer, in
`ndb`, written as a side effect of rendering. Message delivery having a side
effect is new; it is contained to the one funcparser callable below, and is
per-viewer by construction because that callable runs once per recipient.

Two guards fall out of writing it this way:

* **The actor's own line does not touch the table.** It is second person
  throughout and establishes no third-person centre, so a player acting alone
  has no narration centre at all.
* **A possessive counts against the surface form.** "She hands Britney her
  sword" spends "her" twice and must not happen; since the possessor is itself
  a participant, it is ranked and budgeted like any other.

### 5.4 The mechanism

Today `attempt._for_room` does `template.replace("{actor}", name)`, producing
one string that `unknown_cmd.deliver` broadcasts.

Instead, the template keeps `{actor}` and gains `{direct}`, `{target}` and so
on -- one per role -- and an **event** carries it, with the per-recipient loop
in `world/events.py`.

**An earlier draft of this section said to use `msg_contents` with a mapping
and hook a `$who()` callable into it. That does not work, and the reason is
worth recording so nobody tries it again.** `objects.py` builds its parser as
`funcparser.FuncParser(funcparser.ACTOR_STANCE_CALLABLES)` -- a fixed dict --
so a callable of ours is never consulted however
`FUNCPARSER_OUTGOING_MESSAGES_MODULES` is set; that setting governs a
different path. And `msg_contents`' own `{key}` substitution resolves through
`get_display_name`, which is the same call that names things in an inventory
listing and in a room's contents, so teaching *it* to answer "she" would put a
pronoun in both.

What is needed is a substitution that knows it is rendering a narration, knows
which role each name fills, and knows who is reading. That is twenty lines and
they live in `events.render`, with every name chosen by one function,
`events.name_for`. P4 changes that function and nothing else moves.
`msg_contents` stays exactly right for everything that is not an action.

`{direct}`/`{target}` buy the second-person case for free: "She hands you the
sword" to Britney and "She hands Britney the sword" to everyone else, from one
cached template, with no extra model call.

**Every delivery site moves**, and they are enumerable: `attempt._for_room` and
`_finish`, `clothing`, `gear`, `relations.handle` / `_take_from` / `_set_down`,
`drop_cmds`, `quests`, `worldgen`, and `npcs.py`'s `get` and `give` tool
handlers. About a dozen, each currently building a string with
`get_display_name(caller)` in an f-string, each becoming a template plus a
mapping.

---

## 6. Ownership

### 6.1 What it is, and what it is not

Three relations that must not be confused, two of which exist:

| Relation | Where it lives | Question |
|---|---|---|
| containment | Evennia `location` | where is it |
| placement | `relations.py`, `obj.db.relation` | how is it there -- in, on, under, behind |
| **ownership** | **new** | **whose is it** |

Ownership is orthogonal to both. A sword you own can be in a chest you do not,
in a room neither of you is in.

### 6.2 Storage, and who may own

```python
obj.db.owner = {"id": 42, "name": "Jessica", "since": <turn or time>}
```

**The name is stored beside the id deliberately.** An Evennia attribute holding
an object reference reads back as `None` once that object is deleted, and the
default rules need to tell "owned by nobody" from "owned by somebody who no
longer exists" -- the second is what makes a dead NPC's sword claimable and the
first is what makes a rock on the floor not somebody's rock. With only a
reference those two are the same value. This matters more given the typing
below, not less: owners are now always the things most likely to die or walk
out of the world.

**An owner is a character.** `quests.is_person` is the test -- it answers true
for NPCs, which are not `DefaultCharacter` subclasses here, so a robot or a
ship's computer owns things like anybody else.

Objects may not own. Every case that seems to want it is one of three other
things:

* **An institution** -- a guild, a company, the Crown. Not an object, and
  modelling it as one puts a physical thing in a room that *is* the
  corporation.
* **Fit, not property** -- "the key belongs to the chest", "the lamp's oil".
  Functional pairings; calling them ownership means "the chest's key" and
  "Jessica's key" look identical and mean different things.
* **A place** -- a ship, a house, a room. Already excluded, and `zones.py` is
  where places with identity and state live.

The stronger argument is that **ownership only means anything through the four
things that read it**, and all four are about a person's claim: the `owned_by`
condition, whose refusals are addressed to somebody; the possessive parser,
where "my" and "her" resolve to people; NPC goals such as "recover what is
mine"; and the transfer cascade. An object owner resolves to nothing useful in
three of the four.

Typing to characters also makes the parser *more* correct: "the chest's key"
falls through to the containment reading `anatomy.instead_of_a_part` already
implements -- the key inside the chest -- which is what a player means almost
every time.

Co-ownership and institutional owners are one deferred feature, not two; see
§12.

### 6.3 Transfer cascades; asking does not

Two questions that read like one.

**Transfer is transitive.** Handing somebody a box of things hands them the
things; anything else makes giving a container a trap. So `set_owner` cascades
into contents by default.

**Asking is not.** If I own a chest and you put your sword in it, the sword is
still yours. `owned_by` reads the object's own owner and does not walk up the
container chain.

They do not conflict because they happen at different moments. The cascade
fires once, when ownership changes, and writes an owner onto each thing it
reaches; afterwards everything has its own answer and nothing is inferred from
where it is sitting. That also makes it a recorded fact rather than a standing
inference, so it can be read back, disputed, and overridden by a later
`set_owner` on one item.

**The cascade claims only what the giver actually owned:**

> For each thing inside, to `relations.MAX_DEPTH`: if it is owned by the
> *previous* owner, it becomes owned by the new one. Anything owned by somebody
> else, or by nobody, is untouched.

So giving you a chest containing Britney's sword does not give you her sword,
and giving you a chest of unowned pebbles leaves them unowned until somebody
takes one -- at which point rule 1 of §6.5 claims it with no special case.

A world may still want the standing inference -- a landlord, a ship's captain
-- so the condition keeps a way to ask:

```json
{"subject": "direct", "owned_by": "actor"}
{"subject": "direct", "owned_by": {"role": "actor", "through": "containers"}}
```

The first is the default and what every seeded rule uses. The second ships as
syntax so no rule has to be rewritten later, and may be honestly unimplemented
at first.

### 6.4 The condition and the effect

* `conditions._PREDICATES["owned_by"]`, with the three moods `WANT`, `UNMET`,
  `ABSTRACT` like every other predicate. Unmet reads "The sword is not yours.",
  want reads "own the sword".
* `effects.VOCABULARY["set_owner"]`, taking `name_role`, `to` (a role,
  `"actor"` or `"nobody"`) and `cascade` (default true), `backwards: True` so
  `conditions.achieves` can read it -- ground rule 4 -- and `answers: False`.

  `achieves` reads it backwards against `owned_by` for the named thing only.
  It cannot read the cascade backwards: "give her the box" as a way to satisfy
  "own the sword" is not a plan step any planner should invent. A decision on
  the record rather than a gap.

Both get a line in `rule_gen._CONDITIONS` and `_EFFECTS`, which is where a
model learns they exist.

### 6.5 The default rules

Seeded in `standard_rules.py`, not hard-coded guards -- that is what lets a
world override them. `standard_rules.VERSION` is raised, which re-seeds
existing worlds' standard rules without touching what they learned.

1. **Taking an unowned thing claims it.** An `after` rule on `get`: if the
   direct object is owned by nobody, or by something that no longer exists,
   `set_owner` to the actor.
2. **Giving transfers.** An `after` rule on `give` (§6.6).
3. **Making claims.** `effects.create_object` sets the owner to the actor when
   an actor caused it. A room generating its own furniture has no actor, so
   that stays unowned.
4. **Born with it.** `dress_npc` and starting inventory set the owner to the
   wearer.

Rule 1 is an `after` rule rather than `carry_out`, so a world can add a check
rule in front of it -- "you may not take what is not yours" -- without either
rule knowing about the other. That composition is the reason to write these as
rules.

### 6.6 `give` has to become a mechanic

There is no `give` command. NPCs have a `give` *tool* (`npcs.py:1064`) that
calls `move_to` and prints a line; a player typing "give the sword to Jessica"
falls through to the learned-verb pipeline and buys a model call to invent what
giving means.

Giving is a mechanic in the sense `put`, `wear` and `wield` are: it means one
thing, the game knows what, and no world invents a private meaning. So it joins
them -- handled in the attempt pipeline before a model is reached, sharing one
implementation with the NPC tool, carrying the ownership transfer in one place.

Not optional: without it, "giving transfers ownership" has nowhere to live.

### 6.7 Matching a possessive

Once `nounphrase` returns a `possessor` and `referents` can resolve a pronoun
to a person, this is one filter in `bind`:

* Resolve the possessor. First and second person are the speaker and the
  addressee; third person goes through §4.3; a name goes through
  `naming.best_match` over people in reach, as `anatomy.resolve_owner` does.
* If it does not resolve: refuse, and **do not conjure**. A stated possessive
  is a claim about the world, and inventing a ball to satisfy it is the worst
  available answer. `anatomy` already draws this line with its `stated` flag.
* If it does: filter to things owned by them, **then** fall back to things
  merely carried by them -- "her sword" said of a sword she is holding and has
  not been given is still the sword she means. Ownership first because it is
  the stronger claim.
* If nothing survives: "You see no sword of hers here." Name the owner, because
  "you see no sword here" is a lie when there are three on the floor.

`"get all of her machines"` falls out: `bulk.expand` already takes the direct
role's phrase, which now carries a possessor that `bulk.matching` adds to its
filters beside `sort` and `kinds.admits`.

---

## 7. Memory

Memory needs rebuilding at the same time, for reasons that are about
mnemosyne's shape rather than about pronouns. Everything below was read out of
the installed package (3.15.1).

### 7.1 Text shape is index shape

`recall` is **hybrid** -- it takes `vec_weight` *and* `fts_weight`, so
retrieval is embedding similarity plus full-text search over the stored
sentence. A memory written as "hug her" is therefore not merely ambiguous when
read back; it is **unfindable**, because it will not FTS-match a cue of
"Jessica" and its embedding is weaker besides. The failure is retrieval, and it
is silent.

**It is already happening.** `attempt._remember` stores `f"I did: {raw}"`,
where `raw` is the player's literal typing. Type "hug her" today and the bank
receives `I did: hug her (involving Jessica)`, the name surviving only in a
parenthetical. P2 makes this worse by making "hug her" succeed far more often.

A memory bank is an index: change the text template and old rows are shaped
differently from new ones, and retrieval degrades across the boundary for as
long as the bank lives. There is one clean moment to settle the shape, and P4's
reset is it.

**The shape:** generated from the event record (§8.1) rather than reassembled
from `raw` plus prose. Names always, no command echo, and without the constant
`"I did: "` prefix, which appears on every row and so discriminates nothing
while diluting both halves of a hybrid search. `metadata` -- never passed today
-- carries the event record's ids, so a recalled memory can be **re-rendered**
with current names rather than replayed as frozen text.

### 7.2 One bank per world, one session per character

Today: one bank per character (`aimud-char-{id}`), `session_id` left at
`'default'`, `scope` left at `'session'`. The session machinery is unused and
isolation is done with files.

* `core/banks.py` -- "Each bank gets its own SQLite file under
  `banks/<bank_name>/mnemosyne.db`", with `create_bank`, `list_banks`,
  `delete_bank`, `bank_exists`.
* `core/beam.py:421` -- recall's session filter is literally
  `(session_id = ? OR scope = 'global')`.

Four things follow:

1. **`worldreset` and `worldremove` clean up memory**, via `delete_bank`. No
   scheduled sweep of orphaned banks.
2. **World-global memories cost one keyword.** `scope="global"` makes a memory
   visible to every character in that world.
3. **A live bug disappears by construction.** Banks are per character, one
   player character plays many worlds, and `recall_sync` passes no world filter
   -- so a player's memories of the haunted school appear to be recallable
   aboard the freighter. Read from the code, not reproduced.
4. **It is probably faster.** Five NPCs writing memories currently touch five
   separate SQLite databases in one turn, all serialised behind `memory._lock`.
   One bank per world makes that one database and one warm connection. The
   "roughly a fifth of a second each" in `remember`'s docstring and the
   `MAX_PENDING` backlog that drops memories on a busy turn may both be partly
   this. Measure before claiming it.

It also unblocks shared worlds, which the present layout prevents: two players
in one world *should* share a bank, or an NPC cannot hold one memory about both
and a world-global memory has nowhere to live. `recall` additionally takes
`author_id` / `author_type` / `channel_id` for telling two players'
contributions apart inside one world.

**The tradeoff, stated plainly:** session isolation is a `WHERE` clause where
bank isolation is a separate file. It is weaker, and two things follow:

* `beam.py:409` has a `cross_session` runtime toggle that replaces the filter
  with `(1=1)`. Flipped on, every character reads every other's memories.
  `memory._configure_backend` is where it should be pinned off explicitly.
* A test that writes to two sessions in one bank and asserts neither recalls
  the other's -- the invariant the file boundary used to give for free.

**One implementation consequence.** `bank` and `session_id` are both
constructor arguments; neither the module functions nor the instance methods
take `session_id` per call. So `memory.py`'s single global instance becomes a
cache keyed by (world, character), and its one-connection-one-lock docstring
has to be re-read: still one connection per bank, no longer one in total.

### 7.3 Write the entities ourselves

`core/entities.py` says so in its own docstring: "Uses regex patterns for
entity extraction and pure Python Levenshtein distance for fuzzy matching. No
spaCy, no PyTorch." `_extract_and_store_entities` (beam.py:1559) files the
result as annotations:

```python
beam.annotations.add_many(memory_id=..., kind="mentions",
                          values=entities, source="regex", confidence=0.8)
```

`AnnotationStore.add_many` and the module-level `add_annotation` are public,
`remember()` returns the `memory_id` that `_remember_sync` currently throws
away, and `_find_memories_by_entity` (beam.py:1670) fuzzy-matches recall
queries against `get_distinct_values("mentions")`. Write path open, read path
already built.

**We have better entities than any scan could produce, and exactly.** The event
record holds the bound roles as real objects: the regex sees a sentence and
guesses, we know the actor is Jessica and the direct object is the Brass
Lantern because binding resolved them.

**And the regex cannot see the case this document is about.** Its stop list
(`entities.py:19`) includes `"he", "she", "it", "they", "him", "her", "them",
"his", "its", "their"`, so a memory reading "hug her" contributes *no entity at
all*. Writing entities ourselves turns the pronoun problem into a non-issue
independently of the text shape.

Two annotation kinds, not one:

* `kind="mentions"` with the object's **key** -- what the existing fuzzy path
  matches against.
* `kind="dbref"` with the id -- exact lookup for every memory involving *this*
  lantern, surviving renames, and still findable after the object is deleted,
  when there is no name left to match.

`extract_entities=True` stays off: it would add a worse guess beside a better
fact.

**The same argument extends to the whole gist.** `episodic_graph.Gist` carries
`participants`, `location`, `emotion` and `time_scope`, and `extract_gist`
derives all four by keyword matching over prose -- `_extract_emotion`
(episodic_graph.py:254) is a list of eight positive words, seven negative and
five neutral, scanned for substrings. `store_gist(gist, memory_id)` is public,
so the gist can be built rather than guessed:

* **participants** -- the bound roles. Exact.
* **location** -- the room. Exact.
* **time_scope** -- turn ordering. Exact.
* **emotion** -- the one we genuinely do not have. This is the hook the
  roadmap's NPC emotion system lands on: if characters acquire emotional state,
  this field is where it belongs, and until then leaving it None is more honest
  than a substring match for "great".

### 7.4 What already writes facts, and what should

`_post_store_pipeline` (beam.py ~3690) runs on **every** `remember()`, with
zero LLM:

1. `episodic_graph.extract_gist(...)` -- rule-based participants, temporal
   anchor, location, emotion, summary.
2. `episodic_graph.extract_facts(...)` -- **regex** SPO extraction on the
   pattern "X is/has/uses Y".
3. `add_edge(gist -> fact, edge_type="ctx")` -- this fills `graph_edges`, which
   polyphonic recall's **graph voice** traverses.
4. `veracity_consolidator.consolidate_fact(...)` for each regex fact.
5. `_proactively_link(...)` -- more edges by recall similarity and entity
   overlap.

So a knowledge graph and a fact store are **already being built out of our
memory prose**, silently. The text shape is not only deciding retrieval
quality; it is deciding the contents of an SPO graph that recall reasons over.

**A fourth confirmation of the pronoun problem, and the sharpest.**
`episodic_graph.py:35` carries `_LOW_QUALITY_SUBJECT_LEADERS`, a stop list of
pronoun and demonstrative subjects, because

> every such triple shares the same (subject, predicate) so the veracity
> consolidator flags each new object as a "contradiction", producing a conflict
> explosion from pure noise.

`"i"` is on that list, and every memory this game writes begins `"I did: ..."`.
Our memories are either rejected at the source or contributing pronoun-subject
noise; either way the graph built from them is close to worthless.

**Where our facts should go: `consolidated_facts`.**

* `veracity_consolidation.py:326` -- real SPO, indexed on subject, predicate
  and object, with `confidence`, `mention_count`, `veracity`, `superseded_by`.
  Not the flattened `facts` table, whose rows from the `extract=True` path are
  `(source, "stated", <whole sentence>)`.
* `VeracityConsolidator.consolidate_fact(subject, predicate, object,
  veracity=..., source=...)` is **public** (line 445).
* It is what polyphonic recall's **fact voice** reads.

The veracity vocabulary is already the distinction needed:
`['imported', 'inferred', 'stated', 'tool', 'unknown']`. Engine-derived facts
-- ownership, placement, state -- are **`tool`**, true by construction. The
distillation's output is **`inferred`**.

Phase 4 above passes `veracity` straight through from `remember()`, and
`memory.py` never passes one, so every regex fact in the bank today is filed
`unknown`. Writing engine facts as `tool` gives the consolidator's Bayesian
weighting a reason to prefer ours, and turns disagreements into **recorded
conflicts** (`_record_conflict`, `get_conflicts`, `resolve_conflict`) rather
than silent averaging. A distillation that hallucinates "the sword is
Britney's" against an engine fact saying Jessica becomes a conflict at
differing veracity tiers instead of pollution nobody notices.

**Polyphonic recall: turn it on, but the toggle is not the win.** The fact and
graph voices are already reading something, and it is presently junk derived
from prose we did not write for them. Fixing the prose and writing `tool`-tier
facts fixes what those voices see; the toggle only decides whether anybody
listens.

### 7.5 Temporal history: `TripleStore`

`TripleStore` is public, as are `add_triple`, `end_triple` and `query_triples`.
Its docstring: *"Time-aware knowledge graph on top of SQLite. Tracks when facts
were true, enabling contradiction detection and historical queries."*
`add()` takes a real subject, predicate and object, plus `supersede=True`
(closes any open triple sharing subject and predicate), `supersede=False`
(multi-valued), `end()` (expire without replacing) and `query(as_of=...)`.

The `supersede` flag turns out to encode a distinction aimud already makes:

| aimud | triple | supersede |
|---|---|---|
| ownership | `(sword, owned_by, Jessica)` | **True** -- a transfer closes the old owner by itself |
| placement | `(mug, on, table)` | **True** |
| exclusive state group | `(lantern, fire, lit)` | **True** -- `lit` closes `unlit` |
| ordinary state | `(rag, state, wet)` | False -- wet *and* torn |
| kind | `(chest, is_a, chest.n.01)` | False |
| pronoun set | `(Jessica, pronouns, she)` | True |

Row three is the striking one: `supersede=True` is exactly the semantics of an
exclusive state group as `verbs.STATE_GROUPS` defines it.

Two constraints:

* **Nothing reads triples into `recall()`.** They are queried structurally --
  `query_triples(subject=..., predicate=...)` -- which suits "what does Jessica
  own", a structured question rather than a fuzzy-retrieval one. But a caller
  asks for them and puts them in a prompt deliberately; nothing is automatic.
* **The `triples` table has no `session_id`** (triples.py:92), so it is
  bank-scoped: **world history, not per-character belief.** Prefixing subjects
  with a character id to fake per-character scoping would be inventing a
  scoping mechanism inside a column. Do not.

`add_facts()` is deprecated and routes to `AnnotationStore`. Do not use it.

### 7.6 A memory is never retired because its subject is gone

* **An event is true for ever.** "I watched Jessica light the lantern" does not
  stop having happened when the lantern is smashed. Somebody may mourn a dead
  husband or a broken sword, and deleting the memories that make that possible
  destroys the only thing that made the loss mean anything. Episodic memory is
  **append-only**.
* **A fact can stop being true.** "The lantern is in the drawer" is false the
  moment it moves. That is what `invalidate` / `update` / `superseded_by` /
  `valid_until` and `end_triple` are for -- a different table and a different
  question.
* **So destruction is written, not erased:** a new event, and a closed fact.
  `end_triple(sword, owned_by)` closes it while `query(subject=sword,
  as_of=<then>)` still answers "it was Jessica's". The loss becomes something
  the character knows, which is what lets an NPC grieve or ask after a thing
  that no longer exists.

`effects.forget_narrations` is not a precedent for the opposite: it clears the
*narration cache*, prose describing what a verb does to this object, and
clearing that is right precisely because it describes the object's present
state. A memory describes the past, and the past does not change.

### 7.7 Our own distillation stays

It is tempting to conclude that triples make `world/fact_gen.py` redundant.
Read what it asks for:

> "Bram owes me a favour", "the ledger went missing last winter", "the
> archivist does not trust the steward"

None is derivable from an event record. They are inference, social obligation
and disposition, and the second came out of **dialogue**, which the game never
modelled. Its exclusion list is decisive: leave out "anything that was only
true for a moment (where somebody was standing, what they were holding at the
time)" and "the character's own passing actions" -- precisely the ground
triples cover. **The two are near-disjoint by construction.**

What changes is what it is *given*. Handed the current triples as ground truth,
it stops spending its `MAX_FACTS = 8` budget re-deriving who owns what from
prose and spends it all on the inferential half. Feed it, do not retire it. Its
output goes to `consolidate_fact(..., veracity="inferred")` rather than back in
as plain text with `source="distilled"`.

### 7.8 Division of labour

Three stores is already more than this game needs, so it has to be deliberate:

* `obj.db.*` -- **authoritative.** Who owns the sword. Unchanged.
* `consolidated_facts` -- what **surfaces in recall**, with veracity and
  conflict detection. Both engine and distilled facts. **Build this first**;
  being read is the entire point.
* `TripleStore` -- **temporal history**, for what `as_of` answers: ownership
  provenance, and §7.6. Not worth mirroring every state change into.

A mirror of `obj.db.owner` in a triple would be the two-answers-to-one-question
failure `world/vocabulary.py` exists to prevent. A dated record of each
transfer is not, and is the thing no Evennia attribute can hold.

### 7.9 Unused capabilities, noted once

So the audit is not redone from scratch: `export_to_file` / `import_from_file`
(which serves the roadmap's world import/export directly), `get_context`,
`detect_patterns` / `summarize_patterns`, and `scope`, which defaults to
`'session'` and is being taken silently -- worth finding out what it means
before assuming memories are permanent.

---

## 8. Infrastructure to settle now

Items the roadmap makes cheap now and expensive later.

**8.1 P3 delivers an event, not a string.** The largest item here. Every
delivery site melts structured facts into prose at the moment it has them, then
discards them:

```python
on_message(f"You put {label} {preposition} {where}.",
           f"{name} puts {label} {preposition} {where}.")
```

Verb, roles, preposition, host, outcome and the effects that fired are all
present on that line and none survives it. Six things want exactly those facts:
MSP (which sound is this?), GMCP and MSDP, the web interface, shared worlds,
the `$who()` renderer (§5.4) and memory (§7). If P3 converts a string into a
template plus a mapping and stops there, each of those touches the same dozen
sites again.

So P3 lands an event record -- verb, bound roles, outcome, effects applied,
narration template -- of which the prose is *one rendering*. Sinks subscribe.

**It pays immediately**, because two sinks already exist and are both handed
English: `npc_gen.notify_npcs` tells characters what happened by giving them
the room's prose, which a model then reads back to work out what occurred; and
`attempt._remember` reassembles a sentence out of `bound` and `actor_text`, the
same information arriving twice and agreeing by hand.

**Evennia's side is already built.** `evennia/server/portal/` ships `mccp.py`,
`telnet_oob.py` (MSDP and GMCP), `gmcp_utils.py`, `mssp.py`, `irc.py` and
`discord.py`. MCCP is on already; GMCP and MSDP have transport and want only
something to carry. Four roadmap items are this one change plus a mapping.

**8.2 `account` is the wrong thing to pass, and it is passed 57 times.** Every
generator takes an `account` and asks it two questions: `get_openrouter_key()`
and `model_for(job)`. Correct for one player in their own world, wrong for
three roadmap items: **shared worlds** must spend the creator's key, not the
acting player's; **worldmode none** must answer "there is no model", which
today would be 57 branches or a `ValueError` shown to a player who did nothing
wrong; and a **configurable API URL** is a third question to the same object,
while `llm.BASE_URL` is a module constant.

One object answers all three: a **sponsor**, resolved from the world rather
than the caller, carrying key, base URL, model choice and a "will you answer at
all" flag. A rename across 57 sites and one resolver.

**8.3 Nothing counts what is spent.** `llm.py` makes every call in the game and
records none of them; OpenRouter returns a `usage` block in every reply and it
is discarded. The roadmap's security audit names this outright and there is no
data an audit could examine. Attribution gets *harder* after shared worlds,
because the question becomes "whose action caused this call on whose key",
answerable only if the sponsor and the acting character were both known at call
time. A ledger behind `llm.fetch` recording job, model, tokens, sponsor and
actor -- about thirty lines, and it must ship with 8.2 or it cannot record the
field that matters.

**8.4 Make the new tables world-overridable from the start.** Pronoun sets are
per-world by design, but `PREPOSITION_ROLES`, `VERB_SYNONYMS`, `ORDINALS` and
`bulk.QUANTIFIERS` are module constants, and the roadmap wants plugins to
extend "all the hardcoded lists and vocabularies". When `nounphrase.py` is
written, give it a `tables(world_root)` accessor merging module defaults with
`world_root.db` overrides, even if nothing overrides anything yet.

**8.5 Every generated artifact needs one declared schema.** An NPC, an item, a
room, a rule, a quest and a kind each have their shape described as prose
inside a prompt and parsed ad-hoc. Four things must produce the same shapes:
the model path, **menu-based building**, **affect plugins**, and **world
import**. Three do not exist yet and all three will reimplement the shape
unless it is declared once. The prompts in P4 and P5 are being rewritten
anyway, which is the cheapest moment to lift each shape out and have the prompt
render *from* it.

**8.6 Add the new registers to `tests/fixtures/export.py`.** Its `REGISTERS`
tuple is explicit, and a register missing from it is invisible to the corpus
and to every measurement. `pronoun_sets` goes in at P1. Ownership lives on
objects rather than the world, so it is out of scope for that file -- but world
import/export will need object-level state, and P5 should decide whether
ownership is part of a world's shape or of its contents.

**8.7 Database ids are already load-bearing identity, and none of it travels.**
Ownership is not the first cross-object reference. Already stored:
`quests.py:155` (`giver_id`, `world_root` as bare ids), `memory.py:149` (a bank
keyed `aimud-char-{id}`), `goals.py:78` (rooms found by a tag that is
`str(world_root.id)`). None survives export into another instance, and
federation needs character identity to survive leaving the instance entirely.
The invariant to adopt while ownership adds one more: **a stored cross-object
reference carries a stable name or slug beside the id**, with a test asserting
nothing new stores a bare one.

**8.8 Asking the player a question is one mechanism wanted in three places.**
The roadmap asks for it three times over: a rule effect that shows a menu and
returns the choice, disambiguation by menu rather than by prompt, and MXP
clickable menus built from a world's kinds and verbs. They are one thing.

Two consequences land inside this plan:

* **P2's ambiguity question is the first instance.** "Which her? Jessica or
  Britney?" should be issued through a `choose(caller, question, options)` seam
  from the start -- answering by typing the name in its first version, with
  Evennia's `EvMenu` behind the same seam later -- rather than as a bare
  `caller.msg()` that a menu would have to be retrofitted around.
* **An effect that asks a question suspends the action**, and the effect
  vocabulary has no such shape: `effects.apply()` is fire-and-forget, running
  a list and returning lines. P5 extends that vocabulary, so it is the moment
  to make sure `set_owner` and its neighbours do not quietly assume every
  effect completes within the call. Not to build suspension -- only to avoid
  foreclosing it.

**8.9 Worldmode "none" must stay reachable.** Pronouns and ownership are
entirely deterministic -- no phase below needs a model call except the two
prompt updates. This work makes the no-model world richer rather than poorer,
and nothing here should be allowed to acquire a model dependency.

---

## 9. Phases

Each lands something playable, and nothing is half-migrated across a boundary.
Every phase carries tests in the existing tiers.

**Phase S -- the sponsor and the ledger** (§8.2, §8.3). First, because it is a
mechanical rename that conflicts with everything if it lands after P3 has
rewritten the same functions' insides. `account` becomes `sponsor` across 57
call sites, `llm.BASE_URL` becomes a field on it, and every call is recorded.
Uninteresting and best got out of the way.

**Phase P0 -- `world/nounphrase.py`.** The reader and the record, with
`tables(world_root)` per §8.4. No behaviour change: `verbs.parse`,
`verbs.ordinal`, `verbs.plain`, `bulk.split` and `anatomy.split_owner` become
thin callers and their private word lists are deleted. Acceptance: every
existing parser test passes unchanged, plus the grammar's own table of phrases.
*The risky phase, and early on purpose -- everything downstream assumes it.*

**Phase P1 -- the pronoun register.** `world/pronouns.py` with one `register()`
that both `pronouns new` and `npc_gen`'s `new_pronoun_set` go through; seeded
sets; subject-form folding; `vocabulary.claim`; `vocabulary_block`;
`help_cmds` category; `pronoun_sets` added to `export.py` (§8.6). No parsing or
narration yet. The test that matters is the fold: a generator declaring she/her
in a world that already has it returns the existing slug and leaves the
register one entry long.

**Phase P2 -- the referent table and pronoun binding.** `world/referents.py`;
`bind` resolving "her"/"him"/"it"/"them"; the ambiguity question behind the
`choose()` seam (§8.8); the `kinds.admits` filter; "all of them" by kind;
`anatomy`'s pronoun sets deleted. This is where "greet Jessica" then "hug her"
works.

**Phase P3 -- the event record and per-recipient rendering** (§8.1). The dozen
delivery sites move to templates plus mapping; `$who()` lands in
`inlinefuncs.py` returning the name. A pure refactor, verifiable by the
existing narration tests, which is what makes it reviewable alone.

**Phase M -- memory** (§7). Rides on P3's event record.

*Shape*: `_remember` and `notify_npcs` become consumers of the record; stored
text generated from structure; `metadata` carries the ids; the `memory_id`
`remember()` already returns is used to write `mentions` and `dbref`
annotations.

*Banks*: one bank per world, one `session_id` per character, `cross_session`
pinned off, `delete_bank` wired into `worldreset` and `worldremove`, an
instance cache replacing the single global one.

*Facts*: the `note_fact` channel, the distillation re-pointed at
`veracity="inferred"`, and polyphonic recall on. **Engine facts and
`TripleStore` moved to P5**, where ownership gives them something to record --
writing a fact channel with nothing to put through it would be a costume.

Sequenced between P3 and P4 because it needs the record P3 builds and the reset
P4 brings. The bank change is the reason to do it here: the old per-character
banks are abandoned wholesale rather than migrated, and this is the one moment
where abandoning everybody's memories is already the agreed price.

**Phase P4 -- pronouns in narration.** `events.render` starts deciding: the
centering rule (§5.2), the per-viewer ranked-participant slot (§5.3), the
per-surface-form budget, `$pconj` for agreement. Narration prompt rewritten for
`{direct}`/`{target}` placeholders and `$pconj` verbs. **World reset here**, and
`export.py` re-run *before* it.

The centering rule tests without a model: the input is two ranked participant
lists, the output is which slot pronominalises. The three rows of §5.2's table
are three cases, and the third -- no carry-over, therefore no pronoun -- is the
one a naive implementation fails.

*As built* (`tests/test_centering.py`). Three things the section above did not
say, settled in the building:

* **`$pconj` is ours, not funcparser's.** The template never reaches Evennia's
  parser (§5.4), so `events.conjugate` reads `$pconj(verb[, role])` itself and
  hands the English to `verb_actor_stance_components`. The spelling is kept so
  a template written for one reads correctly in the other. Only the first
  word is conjugated -- `$pconj(pick) up` and `$pconj(pick up)` both work --
  and the reader as subject gets second person, so one template also yields
  "You pick up the sword."
* **A possessive is a slot form, `{target's}`** (or `{target}'s`, which a
  model writes as readily). It takes the set's adjective form, spends it
  against the budget, and the thing that follows it in the clause is rendered
  bare -- "her sword", not "her the sword". Things are otherwise rendered
  definite ("the sword"), which is what every hand-written site had before
  the event carried the object instead of its label.
* **Rendering writes the parser's half of the table too.** Having watched
  Jessica hand Britney the sword, a viewer's "her" means Jessica and "it" the
  sword -- noted lowest rank first so the direct object wins, and the actor
  is not made "the last thing referred to", because "get all of them" after
  watching somebody pick up a wrench means wrenches. Rendering for nobody
  (`viewer=None`, what `notify_npcs` and the memory record get) chooses no
  pronoun and writes nothing.

The mechanics' hand-written templates (`clothing`, `gear`, `relations`,
`drop_cmds`, `follow`) carry `$pconj` now, and an NPC's action is rendered per
watcher like a player's rather than broadcast once. Two P3 defects turned up
under pyflakes on the way -- `clothing._event` was called and never written,
so wearing anything failed with "Something went wrong", and `recall` raised
`NameError` before reaching the thread pool -- and are fixed.

*Wiring the narrator* (`tests/test_verb_gen.py`,
`tests/test_centering.py`). The prompt asks for a template, and a narrator
does not always give one. What it gets wrong is not a one-off blemish: the
template is what is stored, so it is replayed to every later viewer and to
everybody who does the same thing afterwards. `events.repair` is therefore
the one place to fix it, and `attempt._finish` runs it *before storage* so
the repair is paid once rather than on every read -- the `repair` calls left
at the delivery sites now only cover templates cached before P4.

Three things it fixes:

* **No subject** -- "lights the candle." -- which P3 already repaired.
* **An article before a placeholder** -- "the {direct}", which renders "the
  the sword", because the slot supplies its own determiner and must (the same
  slot may come back "her" or "you"). The prompt forbids it and a model
  writes it anyway; every sentence it has ever read has the article there.
* **The actor's verb conjugated** -- "{actor} hands", which can never agree
  with anybody: "hands" for a they/them character who should get "hand", and
  "hands" for the reader themselves, who should get "you hand". Wrapping it
  in `$pconj` is the difference between a template that works for one pronoun
  set and one that works for all of them. The base form is recovered by
  asking Evennia's conjugator which candidate produces the word -- so "tries"
  comes back "try" and "watches" "watch" with no exception table here -- and
  anything it cannot be certain of is left exactly as written.

**Phase P5 -- ownership.** `world/ownership.py`; the `owned_by` condition; the
`set_owner` effect and its cascade; `rule_gen` prompt lines; `standard_rules`
seeds and a raised `VERSION`; the `give` mechanic; `create_object` and
`dress_npc` claiming.

Also the half of Phase M that had nothing to record until now: engine facts
through `memory.note_fact(..., veracity="tool")`, and `TripleStore` for
ownership provenance -- `(sword, owned_by, Jessica)` with `supersede=True`, so
a transfer closes the old owner by itself and `query(as_of=...)` still answers
who it belonged to before. That is what §7.6 needs to let somebody mourn a
sword that no longer exists.

**Phase P6 -- possessive matching.** `bind` filtering on possessor; the refusal
wording; `bulk` narrowing; `anatomy`'s carried-object fallback folded in.

**Phase P7 -- what it is for.** One optional standard rule ("you may not take
what is not yours", off by default), one NPC goal template ("recover what is
mine"), and theft carried on the witnessing path so `notify_npcs` can say whose
it was. Without this phase nothing in play changes, and it is the phase most
likely to be cut under time pressure.

---

## 10. Decisions on the record

1. **One pronoun per surface form**, placed on the backward-looking centre.
   §5.2.
2. **Second person for non-actor participants**, and it does not spend the
   pronoun budget. §5.2.
3. **Ownership transfer cascades; `owned_by` does not walk containers**, and
   the cascade claims only what the previous owner owned. §6.3.
4. **An owner is a character.** Objects may not own; co-ownership and
   institutions are one deferred feature. §6.2, §12.
5. **NPCs may declare new pronoun sets**, through the `new_states` channel
   rather than being constrained to the seeded four. §4.2.
6. **P0 is a standalone no-behaviour-change refactor**, and Phase S goes first.
   §9.
7. **Memory is rebuilt in Phase M**, not merely protected from pronouns. §7.

Three things the brief did not cover, now folded in: **verb agreement**
(§4.1, §5.1) -- without a `plural` flag every they/them sentence reads "they
picks up the sword"; **`give` does not exist** (§6.6); and **ownership with no
consequence is bookkeeping** (P7).

Two smaller notes: "it" for objects collides with "it" as a personal pronoun,
handled in practice by §4.3 step 2 but worth stating as a rule rather than
leaving to kind data; and objects have number rather than gender, so
`referents["them"]` holds either a plural-set person or a plural object and the
parser copes with both.

---

## 11. Risks

1. **P0 rewrites the parser's foundations under a working game.** Mitigated by
   its being a pure refactor with no behaviour change, with the existing parser
   tests as acceptance criteria. If it cannot land without changing behaviour,
   it is not done.
2. **P3 touches a dozen delivery sites** and a missed one shows a raw
   `{actor}` in somebody's face. Mitigation: a test that greps for
   `get_display_name` inside an f-string, in the style of the AST test in
   `test_people.py:263`.
3. **Ambiguity questions are a new class of interaction.** "Which her?" is a
   prompt the game has never issued and there is no machinery for answering it
   -- the player types the name and starts over. That remains the first
   version, but the roadmap wants disambiguation by menu, so it goes behind the
   `choose()` seam of §8.8 rather than being written as a bare message. The
   risk is not the prompt; it is issuing it somewhere a menu cannot later
   replace.
4. **Phase M abandons every existing memory bank.** Deliberate and covered by
   the reset, but it is the one irreversible step in this plan.

---

## 12. Out of scope, deliberately

* Possessive chains deeper than one -- "Jessica's brother's sword" parses by
  the grammar in §2.1 and need not *resolve*; refuse the second level.
* Reflexives as objects ("she cut herself"). The form is in the set for
  narration; binding it is not worth it yet.
* Plural objects as a single bound thing ("get the coins" as one object). The
  game has no mass nouns and adding them is its own work.
* Relative clauses. "the box that's on the table" is a phrase Inform supports
  and this grammar does not; `put` and `from` already cover it.
* Ownership by a room, and ownership by an object. §6.2.
* **Co-ownership and institutional owners** -- one feature, not two: a **legal
  person**, a record in the world with identity but no body, which characters
  can own and which can own things. It would be a fifth `conditions.Subject`
  kind and is genuinely wanted by any world with a guild or a Crown. Left out
  because it multiplies cases in the possessive parser, the refusal wording,
  the cascade and `owned_by` at once, for something no world in the corpus has
  asked for; because it is much cheaper after §8.5's declared schemas exist;
  and because nothing shipped here has to be rewritten to add it -- `owned_by`
  already takes a subject, and a legal person is one more kind of subject.
  Worlds that want one now say the guildmaster owns it.
* Per-character belief as distinct from world fact. `TripleStore` is
  bank-scoped (§7.5) and faking scoping inside a column is not worth it.
