# Rules, and where they live

A design note, written before the change it describes. Everything measured here
was measured against the seven worlds in the development database, holding 326
learned verb rules across 100 verbs and 99 generated rooms.

Those worlds straddle the kinds change, so some numbers below describe a
problem that is already fixed and are marked as such. They are kept because the
problem this note is about is the *shadow* of that fix.

> **This note makes the case; the design was settled in
> [rulebooks-from-inform.md](rulebooks-from-inform.md), which follows Inform 7's
> action machinery rather than the sketch below.** Sections 1, 2 and 9 -- what is
> wrong, what the examples demand, and what was rejected -- stand as written. Two
> things in section 4 do not: an action is *declared* with its arity rather than
> inferred from what was typed, and a rule reaches a participant nobody named by
> **redirecting to another action** rather than by binding a subject implicitly.
> Both are Inform's answers and both are better. The build order in section 12 is
> superseded too.

---

## 1. What is wrong

A verb rule today is one JSON object per verb per world: preconditions,
effects, an optional contest, a repeatable flag. It is written by a model the
first time anybody types the verb, stored under `verb#roleshape`, and never
revised. It may not mention a room -- the prompt says so twice -- because a rule
is cached for the whole world and a room-specific rule would be wrong
everywhere else.

That design has four failures, and they are not independent: they are four
views of one mistake.

### 1.1 A verb means one thing per world, and verbs do not

Take the example that prompted this note.

```
power                 (standing in a spaceship)   -> power the ship
power                 (standing in a VR pod)      -> power the pod
power datapad                                     -> power the datapad
launch                (in a powered, sound ship,
                       on a planet that allows it) -> launch
```

Not one of these four is expressible today.

`power` resolves to a single rule keyed `power` (nothing was named) or
`power#direct` (the datapad was). Two rules for four meanings, and the two that
matter most -- the ship and the pod -- share a key, so whichever was typed
first wins for the life of the world. Nothing in the rule can ask what the
player is standing in, because a rule may not mention the room.

`launch` is worse: the thing being launched is the room, and the room is not a
participant. So `launch` can only be a rule about `actor`, and its three real
conditions -- powered, undamaged, permitted -- are about a thing the rule is
forbidden to name.

This is not a gap at the edge of the design. It is the ordinary case for any
world with vehicles, machines, buildings, institutions or weather in it.

### 1.2 The refusals say so out loud

85 of 326 rules are refusals -- `valid: false`, the verb declined for the life
of that world. Sorted by the reason the model gave:

```
60   the engine already does this        get, give, set, pull, take
18   genuinely implausible               smooth a lamppost, "lightly" is an adverb
 7   needs a place or a context          fill, order, search
```

The first 60 are an old wound, mostly closed: verbs the command set answers are
now handed back to it instead of being learned. The 18 are the system working.

The 7 are this note:

> **fill** — "Filling a container requires a source of liquid, meaning this
> action only makes sense in specific locations like a fountain or river."
>
> **order** — "Ordering a drink is a transaction with a vendor or
> establishment, not a universal property of the drink itself, and only makes
> sense in specific locations."
>
> **search** — "Searching without specifying a target implies searching the
> surrounding room, and these rules cannot reference or interact with
> locations."

The model is not failing. It is correctly reporting that the representation it
was handed cannot hold the answer. And the refusal is permanent: one attempt at
`fill` anywhere in a world refuses `fill` everywhere in it, forever.

Seven is also a floor rather than a measurement. A verb refused once is never
asked again, and players stop typing verbs that do not work.

### 1.3 Write once, be right forever

A rule is learned from whatever the world happened to know at that moment. It
cannot be revised, and nothing revises it.

Of the 241 rules that were accepted:

```
32%  change nothing at all -- no effects, success or failure
16%  require nothing at all
12%  have a contest
```

A third of the rules in these worlds are inert. Some of that is honest -- a
verb that produces only a sensation should change nothing -- but `search`
setting `searched` on a role nobody bound is not honest, it is a silent no-op,
and there are rules like it in every world here.

The deeper version of the problem is that a rule written on day one cannot
require a state that is invented on day three. A world that learns `launch`
before it has ever heard of `fuelled` has a `launch` that will never want fuel.
The only repair is `worldreset`.

### 1.4 Nothing composes, so everything is restated

Every rule restates what every other rule already said. "You must be holding
it" appears in 54 `holds` clauses. "It must not already be burning" appears in
121 `lacks` clauses. `wash` in one world has five accepted rules between which
`clean`, `dirty`, `dry`, `wet`, `sweaty` and `sticky` are shuffled five
different ways.

(That last number is the old cache key, which forked on affordances: 45 verbs
held more than one accepted rule in a single world and 26 of those disagreed
about what the verb changes. Keying on the verb alone fixed it. Read on.)

There are already two hand-built exceptions to "nothing composes", and both are
evidence for what this note proposes:

* **`prevents_acting`, `prevents_moving`, `prevents_speaking`** on a state
  group. These are universal preconditions, attached to a *state* rather than
  to a verb, applying to every verb including ones not yet invented. The
  docstring explains why they cannot be a list of forbidden verbs: "a state is
  settled once while new verbs go on being invented, so any list would be stale
  within a week." That is exactly the argument for composition, made once, for
  three flags.
* **`kinds.admits`** -- one bit per kind and verb, consulted before the rule
  runs, introduced because 86% of learned rules existed only to answer a
  yes-or-no question about one sort of thing. A bit is a rule with no effects.

Both are scoped rules in everything but name. Neither is reusable, neither
appears in help, and each needed its own machinery.

### 1.5 And the shadow of the last fix

The kinds change made the rule key the verb alone, on good evidence: 73 bottles
had reached 25 different answers about what a bottle is, and `drink` had been
learned 30 separate times. One rule per verb per world is what ended that.

It is also precisely what makes `power` unexpressible. The old key had too many
rules that disagreed; the new key has exactly one rule that must be right
everywhere. Both are the same error in opposite directions: **the verb was
treated as the thing a rule belongs to.**

The fix is not to fork the key again. It is to stop asking one rule to be right
everywhere, and to let several small rules, each filed against something
closed, compose into the answer.

---

## 2. What the examples demand

Five things, read straight off the four lines of the spaceship example.

1. **A rule must be able to be about a place.** Not "about the room it was
   learned in" -- that is the thing the ban was right to forbid -- but about a
   *sort* of place: any spacecraft, any tavern, this planet.
2. **A verb must be able to mean different things in different company**, and
   which meaning applies must be decided without a model and without ambiguity.
3. **Conditions must be able to name things nobody typed.** "The ship I am in"
   is not a word in `power`, and `launch` names nothing at all.
4. **A world must be able to add a condition later** without rewriting what it
   already decided, because on the day `launch` is learned nobody has invented
   fuel, traffic control or hull breaches yet.
5. **All of it must stay readable backwards**, or the planner, the hints and the
   quests stop working -- and readable *forwards* by a person, or nobody can
   debug a world.

And the existing constraints do not move: decide everything free before paying
for anything; pay once for the part that generalises; closed vocabularies
wherever drift is fatal; no model ever writes code.

---

## 3. The change: a rule is a thing, and it lives where it is true

The same move kinds made.

> An affordance is a fact about bottles. It was being stored on each bottle.

A precondition is a fact about spacecraft. It is being stored on the verb.

So:

**A rule stops being part of a verb and becomes a small named object, filed
against whatever it is a fact about.** A verb attempt gathers the rules that
apply to it, in a defined order, and runs them in phases.

```json
{
  "id": "r47",
  "means": "a ship only launches under power",
  "verb": "launch",
  "scope": {"kind": "spacecraft.n.01"},
  "subject": {"enclosure": "spacecraft.n.01"},
  "when":     [],
  "requires": [{"subject": "direct", "is": ["powered"]},
               {"subject": "direct", "lacks": ["damaged"]}],
  "effects":  [{"type": "set_state", "role": "direct", "add": ["in_flight"]}]
}
```

Rules live with their scope, not in one pile:

| Scope | Where it is stored | What it is a fact about |
|---|---|---|
| `{"object": <dbref>}` | `obj.db.rules` | this one thing |
| `{"kind": "<synset>"}` | `kind_specs[kind]["rules"]` | everything of that sort |
| `{"room": <dbref>}` | `room.db.rules` | this one place |
| `{"zone": "<id>"}` | the zone record | this area and everything in it |
| `{"world": true}` | `world_root.db.rules` | the world |

A flat `world_root.db.rule_index` of `{verb: [(scope, id)]}` is written
alongside, so gathering is a dict lookup per scope rather than a scan. A rule
with `"verb": null` applies to every verb in its scope, which is how "nothing
works while you are dead" becomes one rule instead of three flags.

Two properties of this are worth stating plainly, because they are the whole
argument.

**Scopes are closed.** A kind is a synset, a zone is a zone id, a room and an
object are dbrefs, the world is the world. There is no free text anywhere in a
scope, so a scope cannot drift the way an affordance list drifted. A model
choosing a scope is choosing from a menu, which is the one kind of question this
project has found models reliably good at.

**Rules attach to hypernyms.** `{"kind": "vehicle.n.01"}` covers ships, pods,
carts and anything else a world later files under vehicle, because
`lexicon.ancestors` already answers that question for nothing. This is the reuse
axis the current design has none of: one rule about containers, written once,
applying to every container any world ever generates.

---

## 4. How an attempt runs

Four phases, in this order. The order is the design, the way the order in
`attempt.py` is the design today.

```
gather -> refuse -> carry out -> react -> report
```

**Gather.** Every rule for this verb whose scope matches a participant, the
room, an enclosing zone, or the world -- plus every `verb: null` rule in the
same scopes. Then drop any whose `when` does not hold. Dict lookups and set
tests: free, bounded, no inference.

**Refuse.** *Every* gathered rule's `requires` must hold. All of them,
cumulatively. The first unmet condition in specificity order supplies the
refusal sentence.

This phase is why the design composes, and it is safe by construction: adding a
rule can only ever make an action *stricter*, never change what it means. The
launch example falls out with nobody having written it in one place --

```
world   : you must be able to act                    (a verb: null rule)
zone    : Kepler-9 forbids unscheduled launches      (written the day traffic
                                                      control was invented)
kind    : a ship only launches under power
kind    : a damaged ship does not launch             (written later still)
```

-- and the refusal a player reads is the first one that bites, with its `means`
available to explain itself.

**Carry out.** Exactly *one* rule supplies the effects and the contest: the most
specific gathered rule that has any. Not a merge. Merging effects from several
rules is how a system becomes impossible to predict, and one winner is what
makes `power` work: a rule on `datapad` and a rule on `spacecraft`, neither
aware of the other, each winning when it is the more specific.

The order, most specific first:

```
1. the object named                     (a rule on this very thing)
2. the kind of an object named          (deepest synset first)
3. the kind of the enclosure            (the ship or pod you are standing in)
4. the room
5. the zone, innermost first
6. the world
```

Within a tier: more `when` conditions wins; then the older rule wins. Every tie
is broken deterministically, so a world behaves the same way twice.

Tier 2 above tier 3 is the whole of `power datapad` versus `power`: a thing the
player actually named outranks the room they happen to be standing in.

**React** -- later, and section 10 argues for doing it second. Rules whose
trigger is a change rather than a verb, run once over what just changed, depth
capped.

**Report.** Narration, per object, per outcome, exactly as today. Nothing in
this note touches it.

---

## 5. One condition language

There are two condition languages today and there should be one.

```python
# verbs.check -- keyed by role
{"direct": {"has": ["read"], "is": ["open"], "lacks": ["burning"],
            "holds": ["direct"], "trait": {"stamina": {"min": 10}}}}

# goals._test -- tagged by type
{"type": "state", "object": "lantern", "is": ["lit"]}
{"type": "trait", "trait": "stamina", "min": 10}
{"type": "in_room", "room": "library"}
```

They already describe the same facts -- `goals.py` says so in its docstring,
"the condition vocabulary deliberately mirrors verb preconditions" -- and they
have drifted anyway, because mirroring by hand is not a mechanism.

Merge them into `world/conditions.py`, with one form and three operations:

```python
evaluate(condition, bound, actor, world_root)   -> True / False
describe(condition, ...)                        -> "the ship is not powered"
achieves(effect, condition)                     -> would this effect satisfy it?
```

`evaluate` serves verb preconditions, rule guards, quest testing and goal
testing. `describe` serves refusals, `help`, quest listings and the `rules`
command. `achieves` serves the planner. Today those are three separate partial
implementations, and `planner._effect_achieves` has to guess the correspondence
between the two languages as it goes.

The one genuinely new thing the merged language needs is a **subject** that can
name something nobody typed:

| Subject | Means |
|---|---|
| `"actor"`, `"direct"`, `"instrument"`, `"target"`, `"container"`, `"source"` | as now |
| `"here"` | the room |
| `{"enclosure": "<kind>"}` | the nearest enclosing room or zone of that kind |
| `{"zone": true}` | the innermost zone |
| `"world"` | the world |

`enclosure` is four lookups up the room-and-zone chain, and it is the single
reference that makes "the ship I am in" sayable. A rule may also declare a
`subject` of its own, which **binds a participant nobody named** -- that is how
`launch`, typed alone, comes to have the ship as its direct object.

### What this buys the planner, for nothing

The planner reads effects backwards today. With one condition language it can
read *preconditions* backwards too, and that is a real capability rather than
tidiness:

```
launch              -> refused: the ship is not powered
                       which is a condition, in the language goals are written in
                    -> subgoal: {"subject": {"enclosure": "spacecraft"}, "is": ["powered"]}
                    -> which rule has an effect that adds "powered"? the power rule
                    -> step: "power"
```

An NPC that wants to leave the planet works out that it has to power the ship
first, with no model call, because the rule that refused it said why in a
language the planner already understands. Depth-capped at two or three, for the
same reason the planner is shallow now: effects are model-written and
incomplete, and a long plan on a wrong effect fails silently.

---

## 6. The enabling change: rooms and zones get kinds and states

None of the above works unless a place can be a *sort* of place and can be in a
condition. Both are small, and the groundwork is done.

**Kinds.** Every one of the 99 generated rooms already carries a `room_type`,
and all 64 distinct values have a head noun WordNet knows --
`carousel_boutique_showroom` reduces to `showroom`, `spore_hollow` to `hollow`.
So a room gets a kind by the
same path an object does: `lexicon.head_noun`, a sense chosen by the generator
that can see the place, `kinds.remember` to settle it. A zone gets one from its
own name. A spaceship with one room is a room of kind `spacecraft.n.01`; a
spaceship with a bridge and an engine room is a *zone* of that kind. Both
answer `{"enclosure": "spacecraft.n.01"}`.

**States.** Zero rooms carry states today. `register_state` already gives a
state a `means`, a group, exclusivity and a help entry, and none of that
machinery cares whether it is applied to a bottle or a planet. A room that is
`depressurised` and a zone that is `under_curfew` cost one attribute and no new
vocabulary.

This is also the answer to "where do facts about non-objects live". A planet
forbidding launches is a state on a zone. A guild owing you a favour is a state
on you. There is no need for a parallel fact store; see section 9.

---

## 7. What a model is asked, and why it is an easier question

Today, once, forever:

> You are defining the verb for EVERY object of this kind, not for one object in
> one place. Never refer to a room, a location, or anything you were not told is
> part of the objects themselves. If the action only makes sense somewhere
> specific, it is not a rule -- mark it invalid.

That prompt demands a universal answer and refuses the verb when no universal
answer exists. It is the direct cause of every failure in section 1.

Proposed, and the change is in what is *shown* as much as what is asked:

> Here is what is already true of this attempt, in the order it is decided:
>
> ```
> world   : you must be able to act
> zone    : Kepler-9 forbids unscheduled launches
> kind spacecraft.n.01 : (no rule for launch)
> ```
>
> Write **one** rule that is missing. File it against exactly one of:
>
> ```
> spacecraft.n.01   the sort of thing you are standing in
> vehicle.n.01      ... and what that is a sort of
> kepler-9          this area
> the world         everything, everywhere
> ```
>
> Require only what is not required above. Do not restate it.

Four things follow.

**The scope is a menu.** The hardest judgement -- how general is this? -- becomes
a multiple choice between closed identifiers, rather than an invitation to write
prose that will drift.

**The rule is small.** One or two conditions, one or two effects. The median
rule today is a large object with several branches; a model asked for a small
one writes a better one, and a person reading a world's rulebook can actually
audit it.

**Nothing has to be right first time, only not wrong.** A rule that says too
little is repaired by *adding* a rule, which is exactly what the refuse phase
composes. When a world invents `fuelled` on day three, the day-three rule
requiring it sits beside the day-one rule requiring power, and the day-one rule
is untouched. This is the same decision kinds made -- union only, never
subtraction -- and it is made for the same reason: revision invalidates
everything that depended on the old answer, while addition cannot.

**Wrong rules are removable.** Additive growth handles incompleteness; it does
not handle a rule that is simply wrong. Two answers, both cheap because a rule
is now small and named and carries a sentence about itself: the planner's
existing `note_failure` suspends a rule that repeatedly promises and does not
deliver, and `rule forget <id>` lets a person remove one. Neither is possible
today, when a rule is an anonymous blob of JSON under a verb.

---

## 8. The examples, worked

**`power` in a spaceship.** Gather for `power`: no world or zone rule; the room
is a `spacecraft.n.01`, whose rulebook has a `power` rule with
`subject: {"enclosure": "spacecraft.n.01"}`. Tier 3 wins because nothing higher
applies. The subject binds to the ship, `requires` asks it `lacks powered`,
effects add `powered`. One call, the first time anybody powers a ship.

**`power` in a VR pod.** The same, from the pod's rulebook. The two rules never
meet and cannot disagree; each was written when the first of its sort was
powered.

**`power datapad`.** The datapad is a named participant, so its kind's rule is
tier 2 and outranks the ship's tier 3. The ship stays unpowered.

**`launch`.** Nothing is named. The `spacecraft` rule binds `direct` to the
enclosure, so the verb acquires a subject. Refuse phase runs four rules from
three scopes written on three different days: able to act, planet permits,
powered, undamaged. Carry out runs the one rule with effects. A failure names
the first condition that bit, in the world's own words. The planner, handed the
same refusal, works out `power` as the step before.

**And what it costs to say all that:** four small rules, against three closed
scopes, learned over the life of the world -- against one rule today that is
forbidden from expressing any of it.

---

## 9. What was rejected

**A triple store with a logical resolver.** The appeal is real: uniform
representation, composition for free. Three objections, in increasing order of
seriousness.

The object graph is already the fact store. `relations.py` settled this for
containment -- "Evennia's own containment does the work [...] there is no second
notion of location to keep in step with the first" -- and the argument
generalises. States, traits, kinds and placement are all already facts about
objects, queryable in constant time. A triple store would be a second copy of
the world, and the two would diverge.

Resolution has no cost ceiling. This whole project is built on deciding
everything free before paying for anything; an inference engine has no
equivalent guarantee, and "the world thought for four seconds about whether you
may open a door" is a worse failure than any this note describes. Scoped rules
are a bounded number of dict lookups and a sort.

And a model writing logic is a model writing code. Every lesson in this
codebase points the other way: closed vocabularies, menus, one small decision at
a time. A rule language a model can get wrong in interesting ways is a rule
language that will be wrong in interesting ways, 300 rules deep into a world,
with no way to tell which clause did it.

What *is* worth taking from the idea is the condition language of section 5 --
one or two hops, named predicates, no recursion -- which is the useful ten
percent of a resolver with none of the cost.

**Triggers on objects as the primary mechanism.** Invisible to the planner: a
trigger cannot be read backwards, so an NPC cannot work out that powering the
ship makes launching possible. Unorderable: two triggers on one object have no
defined precedence. And they are code in disguise -- the moment a trigger needs
a condition, it wants a language, and the language is section 5 again. Triggers
have a place, and it is second: section 10.

**Forking the cache key again.** `power#direct:powerable` was the old design and
the measurements that killed it are in `kinds.py`. The key is not the problem.

**Rules only on rooms.** Tempting, since the spaceship example is about places.
But a rule on a room is a rule that cannot generalise, which loses the property
the whole project is built on -- pay once for the part that generalises. A rule
on `spacecraft.n.01` covers every ship a world will ever build.

**Letting rules merge their effects.** One winner, stated in section 4. Merging
is how a rule system stops being predictable, and predictability is what makes
the refuse phase safe to extend.

---

## 10. Triggers, deliberately second

There is a class of behaviour this design does not reach: consequences that are
nobody's action. The ship launches and everyone aboard is weightless. The
reactor breaches and the compartment fills with smoke. Today that has to be
written into the launching verb's own effects, by a model that cannot know what
a future world will consider a consequence of launching.

The answer is the same object with a different trigger --
`"on": {"state": "in_flight"}` rather than `"verb": "launch"` -- gathered after
effects land, over the things
that actually changed. Which makes it one mechanism rather than two: the same
conditions, the same effects, the same scopes, the same help, the same `rules`
listing.

Two reasons it is second rather than first. It is the only part of this design
that can fail to terminate, so it needs a depth cap and a visible log, and
neither is worth building while the dispatch half is still being proven. And
nothing in the example that prompted this note needs it.

---

## 11. What it costs, and what it cannot do

**Calls.** More rules over the life of a world, each much smaller, each reused
more widely. A world rule about holding applies to every verb ever invented; a
rule on `container.n.01` applies to every container ever generated. The steady
state is unchanged: a gathered, cached rulebook costs nothing, and the common
case is and remains zero calls.

**Time.** Gathering is bounded by the number of scopes in play -- a handful of
participants, their kinds and ancestors, the room, the zone chain, the world --
which is tens of dict lookups. No inference, no fixpoint, no recursion in the
dispatch half.

**Storage.** Rules are small and live beside what they are about. A world's
whole rulebook is enumerable, which is what makes help and auditing possible.

**The real loss, stated plainly.** Today a verb's meaning is one object you can
read. Tomorrow it is four rules from three scopes, and understanding why an
attempt was refused means knowing which rules applied and in what order. That is
the known failure mode of every system of this shape, and the known mitigation
is to make the order visible -- so `rules` (every rule in scope here, in firing
order) and `rules <verb>` (what this verb means here, and where each part of it
came from) are part of the first version, not a later convenience. A world
nobody can debug is worse than a world that cannot launch a spaceship.

**What it still cannot do.** A vehicle you can be *inside* as an object rather
than as a room: `relations._is_thing` excludes characters deliberately, so a
character cannot be placed in a thing. Ships, pods and lifts are rooms or zones
here, and that is a separate change with its own consequences.

---

## 12. How it would be built, in order

Each step is useful on its own, which is the test of whether the order is right.

1. **Rooms and zones get kinds and states.** Smallest change, and it already
   improves generation: a room that knows it is a `galley` generates better
   contents. Nothing depends on the rest of this.
2. **`world/conditions.py`: one condition language.** Mechanical, touches
   `verbs.check`, `goals._test`, `planner._effect_achieves` and `quest_gen`, and
   pays for itself three times over in things that stop being written twice. Add
   `here`, `enclosure`, `zone` and `world` as subjects.
3. **`world/rules.py`: storage, index, gather, order.** Pure functions over data
   that already exists. Testable without a model: hand it a world and an
   attempt, get back an ordered list of rules.
4. **`attempt.py` runs phases** instead of one rule. Old rules read as
   world-scoped rules for their verb, which is a ten-line adapter and means
   existing worlds keep working rather than needing a reset.
5. **The prompt asks for one small scoped rule**, showing what is already in
   scope. This is where the quality of the whole thing is decided, and it should
   be done last, when there is a working engine to write rules into.
6. **`help <verb>`, `help <kind>` and `rules`.** Self-documentation, from the
   same store.
7. **Planner subgoals from unmet preconditions.** The capability win, once the
   condition language makes it nearly free.
8. **Reaction rules.** Section 10. Later.

---

## 13. Open questions

* **How many rules per verb per scope before a world is asked to amend rather
  than add?** Unbounded addition is how a rulebook becomes unreadable. A cap
  with "amend the closest existing rule instead" as the alternative is probably
  right, but the number is a guess until a world has been played.
* **Who chooses the scope when the model chooses badly?** A rule filed against
  `physical_entity.n.01` would apply to everything in the world. Some ceiling on
  how general a scope a model may pick is needed; the taxonomy depth is a
  natural one.
* **Should `when` and `requires` really be separate?** `when` decides whether a
  rule is in play, `requires` decides whether the attempt succeeds. The
  distinction matters -- it is the difference between "this rule is not about
  you" and "you may not" -- but it is also exactly the kind of distinction a
  model gets wrong, and collapsing them is worth considering.
* **Contests from constraint rules.** Forbidden above, to keep one roll per
  attempt. But "launching from a damaged pad is a piloting check" is a real
  thing a zone might want to say, and it has nowhere to go.
