# Kinds and affordances

A design note, written before the change it describes. Everything measured
here was measured against five live worlds holding 724 generated objects and
664 learned verb rules.

## The problem

A verb rule is cached against the *properties* of the things involved, not
against the things themselves. That is the best idea in this game: learning to
read a flyer teaches the world to read a pamphlet for nothing. `signature()`
builds its key out of an object's affordances, so two objects with the same
affordances share every rule ever learned about either.

Which means the affordance list is a cache key. And it is written fresh, by a
model, for every object that has ever existed.

Predictably, it drifts:

```
bottle    73 objects, 25 different affordance sets
cup       18 objects, 14 different affordance sets
key       10 objects,  5 sets -- four of them 'readable'
100 of 307 head nouns disagree with themselves
```

A cache key that drifts does not degrade gracefully. It silently stops
matching, and the world pays again for something it already knows:

```
664 learned rules across 151 verbs -- 4.4 rules per verb
drink learned 30 times · read 29 · open 27
77% of all rules are duplicates of an earlier rule for the same verb
```

Thirty `drink` rules, and every one of them requires exactly `container` and
`drinkable`. They forked on `breakable`, `flammable`, `readable`, `wieldable`
and six other marks that no drink rule has ever mentioned. A bottle being
flammable split the rule for drinking out of it.

## What was rejected

**Narrowing the signature to what a rule requires.** Looks like a 50% collapse
until you notice that 67% of rules require no affordance at all, so they narrow
to an empty key and become universal -- `smooth`, learned on a crumpled flyer,
would match a person, a wall, a puddle. With a floor against that, the real
saving is 15%, and it changes the behaviour of rules already learned in live
worlds. It treats the symptom.

**A per-kind prior.** Show the model what this world decided a bottle was, and
ask it to stay consistent. Advisory, so it reduces drift without ending it, and
it leaves the affordance list as per-object data written fresh every time.

Both were worth measuring and neither addresses the cause, which is that an
instance is being asked to describe its class.

## The change

### 1. Affordances are verbs, and carry a value

`brewable` is not in any dictionary. `brew` is. Nine in ten of the 64
affordances these worlds have invented decompose to a real verb by dropping
`-able`, and once they do, three things follow.

**They fold through machinery that already exists.** `VERB_SYNONYMS` is a
hand-curated table this game already maintains, and it already knows that
`consume` is `eat`, `take` is `get`, `touch` is `feel`, `listen` is `hear`,
`clean` is `wash`. Run affordances through `canonical_verb()` and
`consumable`, `takeable`, `touchable`, `listenable` and `cleanable` stop being
their own words. Today `openable` and `open` are unrelated strings in
unrelated namespaces; 27 of 54 affordance-verbs are verbs their own world has
already learned a rule for.

**Negation stops needing a vocabulary.** An affordance becomes an entry in a
map -- `{"burn": true}` -- and a map cannot hold `burn: true` and `burn: false`
at once. Nobody has to decide whether the opposite of `flammable` is
`unburnable`, `fireproof` or `nonflammable`, or write the machinery that stops
a thing being two of them. This is what `register_state()` gives states
through exclusive groups, arriving here for free, because the group is always
`{yes, no}` and never has to be declared.

**The cache key can become principled.** `rule_key("drink", bound)` can consult
what the object says about *drink* rather than everything it says about
anything. The thirty-way fork dissolves structurally rather than by heuristic,
because flammability is simply a different key.

Two conventions have to be pinned down, because the suffix was carrying them
and prose will not:

* **Voice.** `-able` is passive. `readable` means *can be read*, never *can
  read*. An affordance says what can be done **to** a thing, and "can burn"
  loses that unless it is stated.

* **`container` and `surface` are not affordances.** They say where things go,
  which is `world.relations`' question, not "what can be done to this". The
  list has been quietly holding two kinds of fact. They move out.

Ten of 64 do not decompose. `edible` and `flammable` are Latin and need a
written map to `eat` and `burn` -- small, and `consume: eat` is already
precedent. `sticky` and `resonant` are qualities, not affordances, and go.

### 2. Affordances belong to the kind, not the object

An affordance is a fact about bottles. It has been stored on each bottle.

```
724 objects · 307 kinds · 2.4 objects per kind
affordance decisions: 724 -> 307   (58% fewer, and each one reusable)
distinct affordance sets: 220 -> 129
```

The generalisation survives intact, because affordances remain the cache key
-- they are simply read through the kind rather than off the instance. 71% of
kinds share their set with another kind, so one `read` rule still covers
brochure, flyer, itinerary, magazine, map, menu, newspaper, pamphlet and
eleven more.

Deciding once per kind also means the decision can be made properly. It
happens 58% less often, and that gap widens as a world matures.

### 3. A thing may be more than one kind, and kinds only ever add

A sword with runes on the blade is a sword and an inscription. Rather than let
an object patch its own affordances -- which would put the hole straight back
in the closed vocabulary -- it may name a second kind, and its affordances are
the union.

Union only. There is no way to say a thing lacks what its kind has. That looks
like a limitation until you look at what subtraction is actually being used
for today:

```
Broken School Chalk   is a chalk, but lacks ['throwable']
event flyer           is a flyer, but lacks ['flammable']
lump of white chalk   is a chalk, but lacks ['crushable','throwable','writable']
```

Chalk is throwable. A flyer is flammable. These are not exceptions, they are a
model forgetting, one object at a time -- 17% of objects, and almost all of it
the very drift this change exists to end. Once a kind decides once, nobody
gets a second chance to forget, and there is nothing to subtract.

So subtraction is deliberately inexpressible. When a thing cannot do what its
kind does, one of two things is true and both are already handled:

* **it is a state** -- sealed, blunted, broken, waterlogged; changeable, which
  is the whole point of states;
* **it is the wrong kind** -- a decorative sword that cannot be wielded is an
  ornament.

This is the affordance version of the rule names already follow: the test is
whether anything anybody could do here would make the word wrong.

**Kinds are closed, or none of this holds.** A kind is a WordNet synset --
`chest.n.02`, which cannot drift the way "chest", "storage chest" and "coffer"
drift. A noun WordNet has never heard of, and generated worlds are full of
them, is anchored under the nearest real synset instead, so `greatsword` still
lands somewhere closed.

**One primary kind, mandatory and singular.** It names the thing, keys the
spec, and answers "which cup?". Asking a model for a *set* of anything is what
produced 25 bottles in the first place, so secondaries have to earn their
place -- and one already implied by the primary's hypernym chain is dropped
mechanically:

```
sword + weapon    -> dropped, implied      sword + inscription -> kept
chest + container -> dropped, implied      book  + sword       -> kept
```

### 4. What the taxonomy can and cannot ground

WordNet stops **kind** drift. It does not stop **affordance** drift, and
should not be asked to: of 64 affordances in use it has an opinion on six
(`container`, `edible`, `readable`, `surface`, `wearable`, `wieldable`) and
none at all on `flammable`, `crushable`, `brewable`, `danceable`, `flushable`
or the other 52, which are invented per world and are meant to be.

So the two mechanisms are separate and both are needed. A closed vocabulary
stops kinds drifting. Single ownership stops affordances drifting. The
taxonomy supplies a floor beneath a kind's affordances -- a chest is a
container whoever generated it -- so that the first object of a kind cannot
decide something the taxonomy already contradicts.

## What was built

1. `world/affordances.py` -- the vocabulary: decompose, canonicalise, the
   Latinate map, normalise to a `{verb: bool}` map. `verbs.affordances()`
   still answers with a set of words, so the twelve other modules that ask
   what a thing affords did not have to change.
2. `world/kinds.py` -- `kind_specs` on the world root, union across kinds, the
   redundancy guard, the taxonomic floor, and placement (`in`/`on`) as a
   property of the kind rather than an entry in the affordance list.
3. `clothing.create` stores kinds and reads affordances through them.
   `item_gen`, `npc_gen` and `worldgen` share one affordance rule.
4. `signature()` keys on what the object says about the verb being attempted.

### One thing changed during the build

`relations.accepts()` gated placement on `container` and `surface` being in
the affordance list, so moving them out would have stopped anything being put
in or on anything. They became `holds` on the kind spec, which is where they
should have been -- being in the affordance list made them part of the verb
cache key, so a table and a shelf could fail to share a rule over which of
them had been called a surface that day.

### One exception, arrived at deliberately

An object naming **two or more** kinds keeps its declared affordances as its
own, and teaches neither kind. A sword with runes is readable because of the
runes, and filing that under `sword` would make every sword in the world
readable; filing it under `inscription` would be settling what every
inscription can do on the strength of a passing mention.

So there is a per-object exception after all, confined to the case that needs
one. Single-kind objects -- which is every object the drift was measured in --
cannot reach it, and for them what the generator says is ignored once the kind
is settled.

`effects.py` is the other way an object's affordances can diverge from its
kind, and it stays: a rule that chars a book is a deliberate act on one book,
not drift, and it does not stop books being readable.

Worlds are reset for this. There is no migration.
