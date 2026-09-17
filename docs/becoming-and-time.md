# Development plan: what follows from what, and when

A plan, written before the change it describes, and checked against the code as
it stood at `834fcea`. It answers three wants that turn out to be one gap:

* when somebody's health reaches nought they should be dead, without every rule
  that can hurt them having to say so;
* hunger and exhaustion should mean something everywhere, without every rule
  restating the figure at which they start to;
* a world with a clock should be able to have things that are true at night and
  things that happen at dawn.

The short answer is **no new trigger system**. Conditions learn "or" and every
predicate declares its opposite, the rulebook gains one phase, the state register
gains states that are worked out rather than written, a world gains a clock that
is read rather than ticked, and one small piece of machinery decides when to
look. Everything else is already here.

---

## 1. What is wrong

### 1.1 A consequence has to be restated by every cause

Nothing in the game fires because a fact changed. A rule fires because a verb was
attempted, and only then. So "health at nought means dead" has nowhere to live
except inside every rule whose effects can lower health -- `attack`, `stab`,
`drink poison`, `fall` -- and a world that writes it in nine of them and forgets
the tenth has a character walking about on no health at all.

It is worse than restatement, because two of the ways a figure falls cannot say
it at all.

* **Drift.** `set_trait` with a `rate` makes a figure move on its own (see
  `traits.adjust`). A poison drains health for a minute and nobody's rule is
  running when it reaches nought. `traits.notice_changes` reports the new figure
  at the next checkpoint, and that is all that happens.

* **An after rule cannot ask how things came out.** The obvious workaround is an
  `after` rule on `attack` guarded "when the target's health is at most 0". It
  does not work, and not because of anything a world got wrong: `_with_rule` in
  `world/attempt.py` gathers the whole book, `when` guards included, *before* the
  carry-out phase runs. The guard is tested against the health the target had
  before the blow landed. So the workaround fails silently on exactly the blow
  that matters. That is a fault on its own, and 6.8 fixes it.

### 1.2 A threshold is restated by every reader

The game already has the tools for "exhausted affects everything", and each one
stops short.

* **A rule with no action applies to every verb.** That is how the standard rule
  "you must be able to act" is written, and a world can write "you cannot do that
  while starving" once. But it must spell the threshold out -- `hunger max 10` --
  and so must every other rule, goal, quest and check that cares whether somebody
  is starving. They drift apart the first time one of them says 12.

* **A state group can gate acting, moving or speaking** (`prevents_acting` and
  its siblings in `verbs.STATE_GROUPS`). But a state is only true when a verb
  writes it, and nothing writes `starving` when hunger falls, which is 1.1 again.
  And `verbs.blocked` reads `states`, the written ones, not `implied_states`.

* **Gear sums bonuses from sources** (`gear.total`): what you carry, the room, and
  what lies in the room. The character's own condition is not a source, so
  "exhausted means -2 to strength" cannot be said anywhere.

### 1.3 There is no clock

Every time in the game is real time. Quest deadlines (`QuestDeadlineScript`) and
memory ages count real seconds. `tokens-and-phrases.md` §12 deferred a `period`
scope and in-game memory ages explicitly "until a world clock exists". A rule
cannot ask whether it is night, and nothing can happen at dawn.

### 1.4 A condition can only say "and"

Every list of conditions is a conjunction, and nothing else can be said. A check
rule cannot be satisfied by a key *or* a lockpick. Most predicates have no
opposite, so a rule cannot ask that somebody is *not* holding something. The
three cases above all run into this sooner or later: "in danger" is burning or
drowning, and "stops being tired and starving" is a negation. §4 has the details.

---

## 2. What was decided before, and what this changes

This ground has been refused twice, and the refusals were right about the thing
they refused.

* `rulebooks-from-inform.md` §3 dropped Inform's **every turn rules** ("a tick")
  and **scenes**.
* §11 of the same note refused a clock: "We have no tick and should keep not
  having one -- an unwatched world costing nothing is this project's best
  property." A delayed consequence was to become "a condition on a checkpoint".
* `kinds-and-affordances.md`, on ambient warmth: "Nothing ticks. It runs when a
  thing changes, not while it stays changed."

Read closely, the principle underneath is narrower than "no timers". The same
note says it outright: "A timer is not the thing this project refuses ... What it
refuses is a timer that spends money." The game already runs timers: memory
consolidation and quest deadlines, and each NPC's idle script, which fires every
second and does nothing unless `world.activity` lets it.

So this plan keeps every property those decisions protected:

* **Nothing ticks.** No rule is evaluated on an interval.
* **Nothing scans.** No rule is tested against every object in a world. A rule
  is tested against a thing because that thing just changed.
* **A world nobody is watching costs nothing**, not even free work.
* **Nothing here calls a model.** Firing a rule is conditions and effects.

And it amends one position on the record. §11's "checkpoint only" is kept for
everything a checkpoint can catch. What a checkpoint cannot catch is a crossing
somebody is present for and nobody triggers: a player standing beside a poisoned
character, watching. For that one case this plan arms **one timer per predicted
crossing, only while the world is awake** (§7). A crossing time can be worked out
in advance, because rates are linear and a clock is periodic. So the timer fires
once, at the moment something becomes true. It is not a poll.

---

## 3. The change, on one page

**Combining and negating conditions** (§4). `all` and `any` join conditions,
anywhere a condition is written. There is no `not`. Instead every predicate
declares its exact opposite once (`is` and `lacks`, `holds` and `not_holds`, and
so on), or declares that it cannot be negated, and `negate` works out the mirror
of any condition when something needs it. Nothing mirrored is ever stored.

**Derived states** (§5). A state in the register may carry a `when`, the
conditions under which it holds. It is never written onto anything.
`implied_states`, which already answers "what is true of this", works it out.
`hungry`, `starving` and `night` are derived. `dead` is not, because death is
sticky: healing a corpse to 1 health should not raise it.

> A state persists until something changes it. A derived state holds exactly
> while its conditions do. A trait modifier persists only while its source does.

**States that carry bonuses** (§5.6). A state entry may carry `bonuses`, and
`gear.total` counts a character's own states as a source. "Starving costs 3
strength" lives on `starving`.

**Becomes rules** (§6). A fifth phase, `becomes`: a rule with no action, whose
`when` is tested against a thing that just changed. It fires when that goes from
false to true. "When a person's health becomes at most 0: they are dead" is one
rule, filed at world scope, found by `rulebooks.gather`, listed by `view rules`
and suspended by `edit rules`.

**Settling** (§6.3). The doors that change things -- `verbs.apply_states`,
`traits.adjust`, drift noticed by `traits.notice_changes`, moving -- mark what
they touched, and note what the rules that care said about it just before. At
the end of the operation, `settle` asks those rules again and fires the ones
that went from false to true. "Stops being" is the same thing, written as a
negation.

**Predicted crossings** (§7). While a world is awake, one reactor timer per
character is armed for the earliest moment a draining figure will cross a
threshold some rule cares about, and one per world for the next clock boundary.
When it fires, it settles.

**A world clock** (§8). An epoch and a speed on the world root, read on demand
the way a trait's rate is. A new `clock` predicate for conditions, and
time-of-day periods as derived states of the world.

---

## 4. Combining and negating conditions

This comes first because everything after it uses it:

* a derived state defined as "burning or drowning";
* a check rule satisfied by a key or a lockpick;
* a becomes rule for "stops being tired and starving".

It belongs in `conditions.py` and not on the rule, for the reason `conditions.py`
exists at all. Two places once grew their own ways of saying what must be true,
and they drifted. A combinator on the rule would give rules something goals,
quests, derived states and refusals cannot say, and would split them again. It
would also be weaker: a rule-level "match any" is one level of OR, and cannot
say "(A or B) and C" without copying C into each branch.

### 4.1 What a condition cannot say today

* **Only "and".** Every list of conditions is a conjunction: `satisfied`,
  `complaints`, the `when` guards `rulebooks.gather` tests, a goal's conditions.
* **No "or", anywhere.** Check rules accumulate, so every one of them must pass.
  "Must be holding a key or a lockpick" cannot be written, not even as two rules.
* **Negation only by luck.** Some predicates come in pairs: `is` and `lacks`,
  `exists` and `gone`, `unbound` true and false, `owned_by` nobody and somebody.
  The docstring on `SOMEBODY` says why that last pair exists: "the condition
  language has no 'not' to write that with". The others have no opposite at all:
  `holds`, `wears`, `placed`, `in_room`, `kind`, `leads_to`, and `owned_by` a
  particular person. `min` and `max` both include their bound, so "not at least
  10" has no exact form.

### 4.2 `all` and `any`

```json
{"any": [
  {"subject": "actor", "holds": ["key"]},
  {"subject": "actor", "holds": ["lockpick"]}
]}
```

* **A node has no subject.** Its members are conditions, or other nodes.
* **A list is already `all`.** The explicit node exists only for use inside
  `any`: "a key, or a lockpick and a steady hand".
* **Normalised on the way in.** A node of one member is unwrapped, a node inside
  a node of the same kind is flattened, and an empty node is refused. Stored
  conditions nest at most three deep, with at most eight members to a node.
* **Evaluating** is recursion over `_judge`, and is the easy part.
* **Saying it**, in each of the three moods:
  * *Want*: members that share a subject and a predicate are merged first, so
    the want reads "be carrying the key or the lockpick". Otherwise the members'
    wants are joined with "or", which Evennia's `iter_to_str` already does with
    `endsep`.
  * *Unmet*: one complaint for the whole node, built from its members' wants:
    "You need to be carrying the key or the lockpick." Not one complaint per
    branch, which would read as though both were required.
  * *Abstract*: the same, in the abstract words `view rules` uses.
* **A quest listing** shows a node as one line, ticked when it holds.
* **Ranking.** `rulebooks.rank` counts a rule's guards, and a node counts as one.

**Combinators are for "or", not for packing.** `from_verb_rule` gives each
requirement its own check rule on purpose, so that a refusal names exactly what
is missing and `view rules` shows one line per requirement. Folding a check
rule's conditions into one `all` loses both. `rule_gen`'s prompt says so, and
`validate` complains about a check rule whose only condition is an `all`.

### 4.3 Opposites, declared once per predicate

There is **no `not` node**, stored or read. Instead every predicate declares, in
a closed table beside `_PREDICATES`, exactly one of:

* **its opposite**: another predicate, or the same one with its value flipped.
  It comes with its own sentences in all three moods and its own backwards
  reading in `achieves`, so nothing ever reads aloud as "it is not the case
  that";
* **a refusal**, with the reason it cannot be negated.

This is the arrangement `effects.VOCABULARY` already uses for `backwards`, and
for the same reason. A predicate nobody can negate is a hole in whatever reads
it, and it should be on the record as a decision rather than found by accident.

An opposite is only an opposite if it is exact, and the existing pairs set two
rules every new one has to keep:

* **Lists flip from "all of these" to "none of these".** `is: [wet, cold]` means
  both. `lacks: [wet, cold]` means neither.
* **A missing subject flips too.** `is` answers false about a thing that is not
  there, and `lacks` answers true. Each new opposite must answer the other way
  from its twin, or negation goes wrong exactly where the thing is absent.

The table, with new names provisional until they are written:

* **Pairs that exist**: `is` and `lacks`; `exists` and `gone`; `unbound: true`
  and `unbound: false`. `owned_by: nobody` and `owned_by: somebody` look like a
  pair and are not one: the complement test found that both say no about a
  thing that is not there. So their mirror is `not_owned_by`, like any other
  `owned_by`.
* **Value flips.** Where a predicate already takes a closed word or a boolean,
  its opposite is a flipped value rather than a new field.
* **Trait bounds.** `min` and a new exclusive `below` are opposites, as are
  `max` and a new exclusive `above`. A figure somebody does not have meets
  neither `min` nor `max`, so it meets both `below` and `above`. A stone golem
  with no hunger is not starving, and "not starving" has to be true of it.
* **New opposites**: `not_holds`, `not_wears`, `not_placed`, `not_in_room`,
  `not_kind`, `not_leads_to`, and `not_owned_by` for a particular person, which
  means nobody's or somebody else's.
* **Refused**:
  * `affords`, which also asks about placement, and whose negative ("cannot be
    done to it") is `affordances.refused`, a different question from "nobody
    said it can";
  * `reachable_by` and `visible_to`, which answer whether *this action* may touch
    or see a thing, and excuse a role the action declared `visible`. The
    complement of an excuse is not "out of reach". A world that means "in the
    dark" asks the `light` trait;
  * `able`, which is waived per action in the same way. The negation of being
    free to act is being in a state that gates it, and that is `is` on the state;
  * `never`, whose opposite is no condition at all.

**Names.** The new opposites are `not_` plus the predicate's own word, because a
model that knows `holds` can guess `not_holds`. In a field list a model chooses
from, being predictable matters more than being elegant. The spelling is not
what makes these different from a `not` node. Each is written by hand, with its
own sentences and its own planner reading, and wraps only its own predicate.

### 4.4 `negate`

`conditions.negate(condition)` returns a condition, or None when it cannot be
negated. Nothing is stored by it, and nothing it returns contains a `not`.

* A leaf becomes its opposite. A list of several values becomes an `any` of
  single-value opposites: not (wet and cold) is not-wet or not-cold.
* `all` becomes `any` of the negated members, and `any` becomes `all` of them
  (De Morgan's laws). The result is flattened into the list around it.
* If any member refuses, the whole negation refuses.
* `negate(negate(c))` evaluates the same as `c`, though it need not be spelled
  the same.

What uses it:

* **Becomes rules**, for "stops being" over several conditions (6.4).
* **Derived states.** `lacks: ["starving"]` is `negate` of the definition, which
  is what the planner plans towards (5.8).
* **Menus**, when menu building exists. A player picks a condition and toggles
  "not", and the result is run through `negate` before it is stored. `view rules`
  then shows "must not be holding the key", from the opposite's own sentence.
* **`rulecheck`**, which can report a rule that requires a condition and its
  negation at once, since that rule can never pass.

### 4.5 What reads a condition, and has to learn trees

* **`describe`, `complaints`, `unmet`, `progress` and `achieves`**, as in 4.2.
  `achieves` of an `any` is true when an effect achieves any member, and of an
  `all` when it achieves some member. That is the same "that would help" the
  function already means.
* **The planner still plans in the older goal shape**, `type` and `object`,
  through `as_goal` and `from_goal`. Goals gain `{"type": "any", "of": [...]}`,
  and `_for_condition` takes the first branch that offers a step. `all`
  flattens into the goal list. The new opposites convert where a character can
  act on them, each with a mechanic as its step:
  * `not_holds`: drop it;
  * `not_wears`: take it off;
  * `not_placed`: take it back;
  * `not_in_room`: leave by any way out.

  `achieves` reads `move_object`, `destroy_object`, `set_owner` and `move_actor`
  backwards for them, so a learned verb that does the same is found too.
  `not_owned_by` is read backwards through `set_owner` but has no step of its
  own: giving a thing away needs somebody to give it to, and the planner has no
  business choosing who. `not_kind` and `not_leads_to` are evaluated but never
  planned, which `as_goal` already answers by returning None.
* **`rulecheck`, `suggest` and `rule_gen`** read `is` and `lacks` directly, in
  about a dozen places. They walk trees now. A state inside an `any` is only one
  way to pass, so "required and settable by nothing" makes a rule dead only when
  every branch is dead. `edit rules dead` must use the same test, or it will
  suspend a rule that could still fire. Because there is no `not`, none of them
  has to track polarity: `lacks` and every `not_` predicate already mean
  "forbidden".
* **`conditions.schema`**, the tool parameters a model writes to, offers the
  opposites as ordinary fields and `any` one level deep over plain conditions.
  That needs no recursive schema. The toolbox builds schemas inline with no
  `$ref`, and support for recursive schemas varies by provider. Stored conditions
  may still nest three deep, for when menus can build them.
* **`view rules`** prints a node as a group, one member to a line. That reads
  better aloud than one long sentence joined by "or".

### 4.6 Staying short of a language

`basic-principles.md` says that if a small language is ever needed it must be
scoped, buildable from menus, and guarded. This stays deliberately below that:

* two combinators, over a closed set of predicates whose opposites are written
  by hand;
* no variables, no "for every thing" or "for some thing", no arithmetic;
* a depth cap and a member cap;
* every node buildable as one menu group, when menu building arrives.

Three tests hold it to that:

* every predicate in `_PREDICATES` declares an opposite or a refusal, and the
  test fails for one that declares neither;
* for every opposite, over fixtures that include a missing subject, a missing
  trait and a list of several values, `evaluate(c)` and `evaluate(negate(c))`
  always differ;
* `negate(negate(c))` evaluates the same as `c`.

---

## 5. Derived states

### 5.1 Shape

A derived state is an ordinary entry in `world_root.db.state_vocabulary`, with
one more field:

```json
"starving": {
  "means": "so hungry it is hard to do anything",
  "group": "hunger_level",
  "when": [{"subject": "direct", "trait": "hunger", "max": 10}]
}
```

In a definition, `direct` is the thing whose state is being asked about. If that
thing is a person it is `actor` as well, so a definition written either way
reads the same.

The `when` list is in the one condition language (`world/conditions.py`), so
everything that can already be asked of a thing can define a state: traits,
other states, what is held or worn, where it is, and (after §8) the time.

### 5.2 Reading

`verbs.implied_states` is already the function that answers "what is true of
this, including what nobody wrote down". It exists so that `alive` holds without
being stored. Derived states are the same idea with a condition instead of a
group default. After the group defaults it evaluates each derived entry for the
object and adds the ones that hold.

It needs to stay cheap, because it is read constantly.

* **A per-world index of derived slugs**, rebuilt when the register changes.
  A world with none pays one empty lookup.
* **A depth guard.** A definition may mention another derived state, as in
  "exhausted" meaning "tired and starving". Evaluation carries a depth, and
  anything past three is not true. `register_state` refuses a definition that
  makes a cycle, so the guard is a belt rather than the brace.

### 5.3 The hot path that has to move

`verbs.blocked` reads `states(character)`, the written ones, and says in its
docstring why: "Nothing here reads the world unless a state is actually held." A
derived state with `prevents_acting` on its group would be ignored there.

`blocked` moves to `implied_states`, and keeps its promise through the index in
5.2. It only evaluates derived definitions whose group has a gate set. In a
world where no derived state's group gates anything, it is the old set
intersection.

### 5.4 Never written

A derived state set by an effect would be true twice over for different reasons,
and could not be cleared, because clearing it leaves the definition still
holding. So it is refused at every door:

* `verbs.apply_states` skips a derived slug and logs it.
* `rule_gen.validate` complains about a `set_state` that adds or removes one.
* `rulecheck` reports any stored rule that does, as a fault.
* The state tools shown to a model mark derived states as "worked out, not set".

A group may hold derived members or written members, never both.
Exclusivity is enforced when a state is written (`apply_states` clears the rest
of the group), and a derived member is never written. A mixed group could
therefore be `fed` and `starving` at once. `register_state` refuses the mix, in
both directions but not in the same way. A derived state is refused outright,
since nothing in play depends on it yet. A written state is still registered,
only outside that group, because refusing it would leave a verb that is
already running with a word it cannot set.
Keeping derived members apart is the job of their conditions, and `rulecheck`
can check that for the common case of bands over one trait (§10).

### 5.5 Showing them

`verbs.condition` prints `states`, deliberately, so that "It is alive" is not
printed under everybody. Derived states are not like `alive`. "You are starving"
is exactly what a player needs to be shown, and it is the same open-sandbox
argument `apply_states` makes for announcing. So `condition` prints written
states and derived states, and still leaves out group defaults.

State aliases (`refresh_state_aliases`, which lets "get empty bottle" find the
bottle) are written when states are written, and a derived state is never
written. Leave that gap for now. Nobody picks up a thing by how hungry it is,
and `night` belongs to the world rather than to an object.

### 5.6 States that carry bonuses

A state entry may carry `bonuses: {slug: amount}`, the same shape as an item's
`trait_bonuses`. `gear.total` adds, for a character, the bonuses of every state
in `implied_states(character)`. `gear.sources` lists them beside the gear, so
that `score` can say where the missing strength went.

Recomputing works the way the rest of gear does, from scratch, so there is no
accounting.

* A written state changes: `apply_states` on a person calls `gear.recompute`.
* A derived state changes: `settle` notices (§6.3) and calls `gear.recompute`.

One loop to rule out. A bonus changes a trait, the trait may define a derived
state, and that state may carry a bonus. `recompute` runs once per settle pass
and cannot trigger itself. A pair of states that flip each other is caught by
the pass limit in 6.6 and reported.

### 5.7 A trait's own bands, as an on-ramp

The trait register already accepts `descs`, Evennia's map from a lower bound to a
word, such as `{0: "starving", 10: "hungry", 30: "fed"}`. Today it only colours
`traits.describe`. When a trait is registered with `descs`, the bands can be
registered as derived states in an exclusive group named after the trait. That
gives a world "hungry" for the price of writing the words it already writes.

Optional, and last in its phase. It is the easy way in, not the design.

### 5.8 What the planner needs

`conditions.achieves(effect, condition)` is handed no world, on purpose, so it
cannot look a derived state up. `planner._for_condition` has the world. When a
goal condition is `is` a derived state, it replaces the state with the state's
`when` conditions before asking anything. For `lacks`, it uses `negate` of them
(4.4). "Stop being starving" (`hunger max 10`) becomes "get hunger above 10", and
that is already plannable through `_trait_step`. A definition that cannot be
negated makes `lacks` of it unplannable, and the goal waits. That is the honest
answer.

---

## 6. Becomes rules

### 6.1 Shape

```json
{
  "name": "somebody with no health left is dead",
  "phase": "becomes",
  "action": null,
  "scope": {"world": true},
  "about": "direct",
  "when": [{"subject": "direct", "trait": "health", "max": 0}],
  "effects": [
    {"type": "set_state", "role": "direct", "add": ["dead"]},
    {"type": "move_contents", "name_role": "direct", "to": "room"}
  ],
  "report": "{direct} $pconj(collapse) to the ground."
}
```

`when` is the edge being watched. It already means "applies only if", and for
this phase that is the whole rule. `conditions` is unused, and `rule_gen.validate`
complains if it is filled.

`rulebooks.PHASES` stays the attempt's four phases, because `rule_gen` offers
`PHASES` to a model asked about a verb, and `becomes` is never an answer to that
question. A separate `BECOMES` constant and `STORED_PHASES` for `blank` and
`add`, which today coerce any unknown phase to `check`.

### 6.2 Who is who

A becomes rule has no attempt, so roles are bound from what changed:

* **`direct`** is the thing it happened to, always.
* **`actor`** is the same thing if it is a person, because every effect that
  acts on a person (`set_trait` with no role, `move_actor`) defaults to the
  actor, and it is their state that changed. Otherwise there is no actor.
* **`cause`** is whoever acted to make the change: the actor of the attempt, or
  of the mechanic behind `attempt.consequences`. It is a new role, and
  a reserved one.
* **The room** is where the thing is. For something carried, it is the holder's
  room. For a place, it is the place.

**`cause` is bound only when somebody acted, at the time they acted.**

* **Chains keep it.** A chain settles within the same operation, so the attacker
  whose blow killed the phoenix is still the cause of its rebirth.
* **The first mark wins.** If writes from two actors land in one settle, which
  only the `callLater(0)` backstop can arrange, the cause is whoever marked the
  thing first.
* **Drift has no cause. That is a decision, not a gap.** A poisoner gets their
  credit when they poison somebody, through the rules on the poisoning verb.
  Whether the victim dies an hour later does not change what the poisoner did.
  If a trait remembered who set its rate, a character would be credited with
  a death days after the act, and an NPC's memory would record a consequence
  as something it did at a time it was doing something else.
* **The clock has no cause either**, and nor do place rules.

A rule that means "killed by somebody" says so with the condition that already
exists for this: `{"subject": "cause", "unbound": false}`. `rule_gen.validate`
complains about a becomes rule whose effects or report name `cause` without that
guard. Without it, a death by poison would leave a report reading "{cause}" and
effects that skip.

`cause` goes in `conditions.ROLES`, and in `tokens.ROLES`, which is also
`events.RANK`. It ranks last there, because a cause is oblique in a sentence:
"collapses, struck down by {cause}". It does not go in `actions.ROLES`, because
nobody names a cause in a command. Being in `tokens.ROLES` reserves it through
`tokens.RESERVED_SLOTS`, so no world can declare a word list called `cause`.
Reports then get `{cause}`, `{cause's}` and `{cause.trait.renown}` for nothing,
and conditions and effects reach it the way they reach every role, by name in
`bound`. Token syntax is not put inside conditions or effects:

* it would be a second way to name a participant;
* a token renders text, and a condition needs the object;
* `$pick` and world lists choose at random, and a condition whose answer can
  change between two evaluations breaks the before and after in 6.4.

`about` decides what a rule is tested against, just as it does for an attempt:

* `about: direct` rules are tested against things and people.
* `about` in `rulebooks.PLACES` (`here`, `zone`, `enclosure`) rules are tested
  against rooms. That is how the clock reaches a place (§8.4).

`rulebooks.Attempt` takes an explicit room, because today it only works one out
from the actor, and a lamp or a room has no actor. `conditions.Context` gains the
same field, so that `here` resolves for a rule with nobody in it.

Some effects need an actor and have none here. `effects._apply_one` is audited
so each one skips cleanly: `move_actor` with no actor does nothing, and
`create_object` with `location: actor` lands in the room. `try` and
`describe` are refused in this phase by `rule_gen.validate`: there is no attempt
to redirect and nobody asked to look.

### 6.3 When they are tested: settling

Every change to a state or trait already passes through a door that says so.
Each door adds what it touched to a **dirty set** held in memory, with the
before taken as 6.4 describes:

* `verbs.apply_states`: the object;
* `traits.adjust`: the character;
* `traits.notice_changes`: the character, when anything had drifted;
* `at_pre_move`: the mover, and `at_post_move`: the room they arrived in;
* `ownership` and `relations` moves: the thing moved, since `holds`, `wears`,
  `placed` and `in_room` are conditions too.

`settle(world_root)` drains the set. For each thing, it gathers becomes rules
about it with `rulebooks.gather`, which already evaluates `when` and orders by
specificity. It compares the result with the before and fires what became
true.

**Every rule that became true fires, and none stops another.** A becomes rule
adds to the rules above it, as a check condition adds to the checks and an effect
to the effects. A more specific rule refines what a general one did instead of
preventing it. The phoenix in §9 dies by the world's rule and is reborn by its
own, one straight after the other.

**Within a pass they fire most general first**, the reverse of the order
everywhere else. Elsewhere rank picks a winner, so the most specific rule has to
come first. Here nothing wins, and order only decides whose effects land last.
The specific rule should have the last word: if the world's rule sets health to
nought and the phoenix's sets it to full, the phoenix ends at full. `view rules`
lists becomes rules in the order they fire, so the listing still shows exactly
what will happen.

The clearer way to write a refinement is to watch the general rule's result,
not its cause. A phoenix rule on `becomes dead` fires on the pass after death,
so its order is visible in the rule itself rather than in the sort.

**Where settle is called** is the one decision here that players will see,
because it decides the order in which things are said:

* **At the end of an attempt, after the narration is released** (`_release`).
  The blow is described, and then the character collapses. Settling earlier
  would put the collapse before the blow whenever the narration waited on a
  model.
* At the end of `attempt.consequences`, for the mechanics.
* After `notice_changes`, in `at_post_move` and in an NPC's turn.
* When a predicted-crossing timer fires (§7).
* **As a backstop**, a `callLater(0)` is armed by the first mark on an empty
  set. Writers outside the pipeline (`npc_gen`, `token_lists`) are still
  settled, without each having to remember to.

### 6.4 Before and after

An edge needs a before.

**Why not remember it.** The first draft of this plan kept a memo on the world
root: which rules were true of which subjects, with a missing entry read as
false. That breaks on exactly the rules a falling edge needs. "When the kettle
stops boiling" is `lacks: boiling` becoming true, and `lacks: boiling` is true of
nearly everything. With a missing entry read as false, every lamp and chair in a
world would "stop boiling" the first time anything happened to it. `becomes
alive` fails the same way, because `alive` is a group default and true of every
character. A memo can only be right about common conditions if it has seen every
thing, and seeing every thing is the scan this design refuses.

**Take it at the door instead.** The door that makes a change can see what things
were like before it:

* **Before a write**, the first time a subject is marked in a settle, the door
  evaluates the `when` of the becomes rules about that subject, against the
  subject as it still is. It keeps the answers in the dirty set. This is not a
  scan: it is the rules about one thing, for the one thing changing.

  The first draft narrowed this further with a per-world index from what a
  condition reads (a state's group, a trait, where something is) to the rules
  that read it. Phase 5 left the index out, on purpose. Becomes rules are few,
  and an index that missed a predicate would make a rule silently never fire,
  which is a worse failure than asking a handful of extra questions. If
  measuring ever shows the cost, the index can be added then, with a test that
  every predicate declares what it reads.
* **After**, `settle` evaluates the same rules again. A rule fires where the
  answer went from false to true.
* **Drift** has already happened by the time anyone notices it, so its before
  comes from `trait_last_seen`. `notice_changes` already keeps that for exactly
  this comparison, and it is laid over the live figures while the rules are
  asked. Drift only ever moves traits, so that is the only overlay needed.
* **Moves** take their before in `at_pre_move`, Evennia's hook that runs while
  the thing is still where it was.
* **Chains** need nothing extra. A subject marked again in a later pass takes its
  before then, which is the after of the pass before.

What follows from taking it this way:

* **Falling edges need no new syntax.** "Stops being" is a rule on the negation:
  the predicate's opposite for one condition (4.3), and `negate` for several
  (4.4). "Stops being tired and starving" is one rule. It fires exactly when the
  thing stops, and never for something that never was.
* **Mutually exclusive states make this read naturally.** A kettle's `heat` group
  might hold freezing, cold, warm, hot and boiling. "Stops boiling" is
  `lacks: ["boiling"]`. "Becomes hot" is `is: ["hot"]`, and it fires on warming
  up as well as cooling down. The two differ, which is why both are wanted. In a
  group of two, or a group with a default, they are the same thing: stopping
  being dead is becoming alive. Bands over one trait (5.7) are such a group
  already.
* **Nothing is stored for things.** There is nothing to prune, and nothing to
  stash per world when a character crosses between worlds.
* **A new rule waits for a change.** Adding "no health means dead" to a world
  holding a character on 0 health does not kill them, because nothing crossed.
  So as not to hide that, `view faults` lists what already matches a becomes
  rule when it is added, and `edit rules` offers to apply the rule once to them.

**Places are the exception**, because their changes (the clock) happen with
nobody there and no door. They keep a small memo. See §8.4.

### 6.5 What is said

An attempt is narrated by a model, or from a cached narration. A becomes rule
must never call a model when it fires, because a world's clock would otherwise
be a paid tick. So a becomes rule carries its own `report`, a template in the
grammar `world/events.py` already renders per viewer. `{direct}` becomes "you" or
a name, and `$pconj` agrees. `events.repair` checks it when the rule is stored.

Whoever writes the rule writes the report: a person, or a model once, when the
rule is written. That is the same bargain cached narrations already strike.
A rule with no report changes things silently. What changed about a person
reaches them anyway, through `apply_states` and `adjust` announcing it.

### 6.6 Chains

Death drops the inventory. Dropping moves things. A moved thing is dirty. A
becomes rule may fire about it. Chains are the point here, unlike `after` rules,
which are gathered before any of them lands so that none can set another off.
But a chain must end:

* **A rule fires at most once per subject per settle.**
* **Settling makes at most four passes.** What is still dirty after the fourth
  is dropped, logged, and counted against the rules that fired last, so that
  `view faults` can name the rules that keep setting each other off. Dropped
  rather than left for the next checkpoint, because the backstop would make the
  next checkpoint the next turn of the reactor, and a loop would spin for ever. Four, because the longest
  honest chain anybody has described is three: a blow, a death, a dropped
  lantern that sets the straw alight.

### 6.7 What it costs

Nothing a becomes rule does calls a model. What it *causes* can: a report
delivered to a room is an event, and events wake NPCs. That goes through
`world.activity`, like every other event, so a becomes rule in a world nobody is
watching wakes nobody. It is still the one path from this design to spending
money, and §13 lists it.

### 6.8 After rules see what happened

1.1 found that an `after` rule's `when` is tested before carry-out runs,
because `_with_rule` gathers the whole book, guards included, at the start. A
guard about how things came out is tested against how they were. That changes:
**an after rule's guards are tested after carry-out.**

* **Scope is still matched where the action happened.** The book is gathered at
  the start, as now, but `rulebooks.gather` can leave guards untested
  (`guarded=False`), and the after phase is gathered that way. A carry-out that
  moves the actor with `move_actor` does not change which after rules are about
  the action: the ship's rule stays the ship's.
* **Guards are tested once, all together.** After carry-out and before any after
  rule's effects land, every after rule's `when` is tested against the world as
  carry-out left it. Then the effects of those that passed are applied, in
  order. That keeps the property the comment on that loop protects: nothing an
  after rule does can set another one going. Chains are what becomes rules are
  for.
* **`here` means the room the action happened in**, through the `room` field
  `conditions.Context` gains in 6.2, not wherever carry-out left the actor.
* **A participant that carry-out destroyed is missing.** `conditions.resolve`
  treats a role bound to a deleted object (its `pk` is None) as not found. After
  burning a note, `{"subject": "direct", "gone": true}` holds, and every other
  predicate answers as it does for anything absent. Nothing checks for this
  today, because nothing asked about a participant after destroying it.
* **Mechanics are unchanged.** `attempt.consequences` already runs after the
  mechanic has happened, so its guards, including the two standard after rules
  for taking and giving, were always tested against the after. Now both paths
  agree.
* A failed contest still skips after rules, and an answer from a cached
  narration still changes nothing.

**Which to write, an after rule or a becomes rule:**

* **An after rule is about the act**: "after stabbing somebody who ends up dead,
  the dagger is bloodied". It runs for that verb only, and sees what carry-out
  did directly.
* **A becomes rule is about the fact**: "anybody who dies drops what they carry",
  whatever killed them. "Whoever kills somebody gains renown" is a becomes rule
  too, through `cause`, and covers every verb that can kill.
* **After rules run before settling** (6.3). So an after rule sees `health max 0`
  but not `dead`, which a becomes rule sets later. A guard about a consequence of
  a consequence belongs in a becomes rule.

**What stops working.** An after rule written against the old order, such as
"after lighting it, when it is not lit", now never fires. `rulecheck.self_defeating`
already finds check rules that demand the state their own carry-out adds. Its
twin for after rules finds a guard that forbids the state its own carry-out
adds, and reports it the same way.

---

## 7. Predicted crossings

### 7.1 Why they are needed

Every checkpoint in §6.3 is somebody doing something. A poison draining a
character while a player stands and watches involves nobody doing anything, and
§11's position ("a consequence nobody will ever look at does not matter by
definition") does not cover it, because somebody *is* looking.

### 7.2 Rates

A trait with a rate moves linearly. The Traits contrib works the value out on
read (`_update_current`: `current += rate * elapsed`, stopping at bounds and at
`ratetarget`). So the moment it will reach a figure can be worked out:

```
seconds = (threshold - (current + mod)) / rate
```

That only counts if the sign is right, and if the figure lies inside the bounds
and short of `ratetarget`.

The thresholds that matter are the trait bounds in the `when` of becomes rules
that could apply to this character. That includes rules that watch a derived
state, whose definition is expanded (5.2), and derived states that are worth
something to a figure (5.6), since gear has to follow those as well. They are
worked out when a timer is armed rather than kept in an index, for the reason
6.4 gives.

For each character with a moving trait, **one** timer (`ndb`, never persistent)
is armed for the earliest crossing. It is re-armed whenever that character
settles or has a rate set. When it fires, it calls `notice_changes` and then
settles. Float error is handled by firing a fraction of a second late and letting
evaluation decide.

### 7.3 Awake and asleep

Timers are armed only while `activity.world_has_active_player` holds for the
character's world.

* **When a timer fires into an asleep world**, it does not re-arm. The crossing is
  still true, because the value is worked out on read, and it is found at the
  next checkpoint, as it is today.
* **Waking** has no hook today. A world wakes when a player puppets into it or
  arrives in it (`at_post_puppet`, which `Character` does not override yet, and
  `at_post_move` across `crossing.cross`). Waking settles the arriving player and
  the room, and arms timers for the characters there.
* **Reloads** clear every `ndb` timer. `at_server_start` arms them again for the
  worlds of connected puppets, which a reload keeps.

`world.busy` already takes an injectable clock (`busy.CLOCK`,
`tests.support.clock`). The same pattern goes here, so every timing test runs
without waiting.

### 7.4 Not yet: how the planner waits

A goal can depend on something that will come true with nobody doing anything.

* **An NPC wants bread, and the shop refuses at night.** The check rule's
  condition is `{"subject": "world", "lacks": ["night"]}`.
* **An NPC wants to cast a spell that needs 10 mana**, and its mana is
  recovering at a rate.

Today the planner finds no step for either. `as_goal` returns None for a
condition about the world, and nothing achieves a figure that is already moving
on its own. So `_pursue_goal` counts a stall, and after `GOAL_STALL_LIMIT`
(ten) the NPC gives up a goal that only needed patience. Meanwhile every idle
turn falls through to the dialogue model.

**The planner can tell when something will come true on its own**, because the
two things that change with nobody acting are the two things this plan already
predicts:

* the clock, which is periodic (§8);
* a trait with a rate, which is linear (7.2).

`conditions.eventually(condition, ctx)` answers in seconds, or None when the
condition will not come true on its own. It is closed per predicate, like
opposites:

* `clock`: the time until the range next starts.
* `trait` bounds, including `below` and `above`: the crossing time from 7.2, if
  the rate is heading that way and the bounds and `ratetarget` let it arrive.
* A derived state: `eventually` of its definition. For `lacks`, of `negate` of
  it (4.4).
* `any`: the soonest of its members.
* `all`: the latest of its members that are not yet true. This is an estimate,
  because a member true now may stop being true by then, such as night ending.
  Being checked again on waking (below) makes that harmless.
* Everything else: None. A written state, what somebody holds, and where
  something is change only when somebody acts, and nobody can say when that
  will be.

**A step can be "not yet".** `_for_condition` and `_towards` ask `eventually`
before giving up on a condition, and they ask it of the condition-language form,
before `as_goal` drops a condition about the world. A condition that will come
true on its own is answered "not yet, in N seconds" instead of "no step".
`plan_for` already moves on to the goal's next unmet condition when one has no
step, and it goes on doing so. So an NPC that wants bread, a coin and the shop
open fetches the coin while it waits. Only when every unmet condition is "no
step" or "not yet", and at least one is "not yet", does `plan_for` return
**waiting**, with the soonest time.

**While waiting, the NPC does other things.**

* `_pursue_goal` records the wait in `db.goal_waiting`: the condition and when
  it is due. It does not count a stall, and it returns False, so the turn goes
  on to whatever the character would do with no goal at all. A waiting NPC costs
  what a goal-less one does, and no more than a stalled one costs today.
* The idle prompt is told what it is waiting for ("waiting for morning, to buy
  bread"), so the dialogue model does not have it go and try the step anyway, or
  forget it wanted anything.
* It may wander while it waits. The planner takes one step at a time, so it
  walks back when the wait is over.

**When the time comes, it is told, and the plan resumes.**

* The due time goes into the one per-character timer from 7.2, which is armed
  for the earliest crossing *or* wait, and only while the world is awake (7.3).
  When it fires, the NPC's `idle_probability` is set to 100. It acts on its next
  tick, still through `npc_may_act` and `ndb.reacting`, like any other turn.
* **The turn checks again rather than trusting the timer.**
  * If the condition holds, the wait is cleared, one line goes into the NPC's
    history ("it is morning; the shop will be open"), and the planner takes its
    step.
  * If it does not hold, `eventually` is asked again. A new time means the NPC
    waits again, for example when night came and went while the world was
    asleep. None means it is back to ordinary stall counting, for example when
    the rate was stopped.
* The backstop is the same as everywhere else in this plan. Each NPC turn
  compares `goal_waiting` with the time, so a lost timer costs precision and
  nothing else.

**A wait has limits.**

* A wait due further off than `MAX_WAIT` counts as no step. That is a real hour
  to start with, and a soak should tune it. An NPC should not keep a want alive
  for a week of real time because its mana regenerates at a crawl.
* A quest deadline still lapses a goal while it waits. `QuestDeadlineScript` does
  not care why the goal is unfinished.
* A wait belongs to the goal it was for. A character that reaches the goal, or
  takes up another, is not still waiting on the old one.
* Waiting for the same thing more than `REWAITS_ALLOWED` times in a row (three)
  counts as being stuck, so a goal whose conditions never line up is given up
  in the ordinary way.

**Waiting is not guessing.** When the only thing blocking a verb this world
already knows is a wait, the planner does not fall back on a verb nobody has
tried. That would answer "not yet" with "try something else".

**Players get the same answer.** `advise`, behind the goal command, says "Nothing
to do until morning, in about twenty minutes" rather than "you cannot see how".
`blocker` gains a `waiting` reason for the same sentence. Players and NPCs read
one planner, as the open sandbox wants.

---

## 8. The world clock

### 8.1 Shape

**Every world has a clock, and until it is told otherwise it is the real one**:
the server's local date and time, running at real speed. A world never has to
turn a clock on, and "what time is it" always has an answer. A world that never
mentions time pays nothing for it, because the clock is only read, and its
timers are armed only for boundaries some rule or derived state mentions (8.4).

```json
"clock": {"epoch": 1789300000.0, "began": "1852-06-14T06:00:00", "speed": 1.0}
```

All three fields are optional, and a world with none of them is on real time.

* **The date is a Python `datetime`**, in the real Gregorian calendar: `began`
  plus `(now - epoch) * speed`. Weekdays, month lengths and leap years all come
  from the standard library, with nothing of ours to get wrong.
* **Nothing is stored as it advances.**
* **Setting the year keeps the day and the hour**, and it is the change most
  worlds will make: a Victorian London is real time in 1852, and a starship is
  real time in 2253. `began` becomes the current date with the year replaced (29
  February becomes the 28th in a year that has none), and `epoch` becomes now.
* **Changing the speed** moves the epoch the same way, so the hour does not jump.
* **The limit is the standard library's**: years 1 to 9999. A world set in 3000
  BC, or a hundred thousand years on, says so in its description, not its clock.

### 8.2 Why not Evennia's game time

`evennia.utils.gametime` is one clock for the server, set by `TIME_FACTOR` in
settings, and its `schedule` creates a persistent Script per event. Worlds on one
server differ, since a space station and a village keep different days. And a
Script per event is the kind of store this project keeps choosing not to grow. So
the arithmetic is ours, and it is ten lines over `datetime`. The custom game time
contrib's invented calendars, with days, months and years of other lengths, are
not taken (§15).

### 8.3 The condition

```json
{"subject": "world", "clock": {"from": 20, "to": 6}}
```

Hours on a 24-hour dial, and a range may wrap past midnight. `describe` gives
"it must be between eight at night and six in the morning", and the abstract
mood reads the same. `achieves` answers false for every effect, because nothing
makes it night. What the planner does instead is wait (7.4).

A range includes its start and excludes its end, so its opposite is the same
predicate with `from` and `to` swapped (4.3). "Not between eight and six" is
"between six and eight", exactly, with no hour counted twice or missed.

### 8.4 Periods, and places

Time of day is **derived states of the world**, in an exclusive group named
`time_of_day`. It is seeded into every world lazily, the way `standard_rules.seed`
seeds the standard rules, with hours from the real world:

```json
"night": {"group": "time_of_day",
          "when": [{"subject": "world", "clock": {"from": 20, "to": 5}}]}
```

It is seeded with dawn, day, dusk and night, and every one can be edited or
renamed, since a station may keep shifts. Rules then say
`{"subject": "world", "is": ["night"]}` and never mention an hour, which is
§1.2's lesson applied to time.

**Most of what people want from time needs no event at all.** "The shop is shut at
night" is a check rule on `buy` scoped to the shop, guarded on `night`. "The gate
is closed at night" is a derived state of the gate. Only things that *happen*
need a becomes rule. The bell rings at dawn, the lamps are lit at dusk, and the
stock is replaced at midnight.

Those are place rules (`about: here`, scoped to a room, a zone or the world), and
their subjects are rooms. A room changes with nobody in it and no door to take a
before, so place rules keep a memo on the world root:

```
world_root.db.becomes_seen = {rule_id: {room_id: [was_true, evaluated_at]}}
```

It holds only rooms somebody has been in since the rule was written, so it
stays small. Rule ids are only unique inside a world, which is why it lives on
the world root. `rulebooks.orphans` prunes rooms and rules that are gone.

* **Occupied rooms are settled live.** When the world's clock timer fires (one
  timer per awake world, armed for the next boundary any rule or derived state
  mentions), every occupied room is settled, and a rule that became true fires
  and reports. **A room is occupied if a person is in it, player or NPC**
  (`quests.is_person`, since an NPC is not a `DefaultCharacter`). That is the
  equality `basic-principles.md` asks for: the bell rings for the baker whether
  or not a player is standing beside her. It costs nothing extra, because what an
  NPC does about the bell goes through `NPC._trigger_reaction`, and every reaction
  and idle turn is gated by `activity.npc_may_act`.
* **Everywhere else catches up on arrival, once and silently.** Each place entry
  stores when it was last evaluated. When a room is settled after being empty,
  a clock condition that had a rising edge since then fires **once**. Its effects
  are applied, and its report is dropped, because nobody was there to hear it.
  The stock was replaced at midnight. Nobody arriving at noon hears a bell.

For a clock condition, "had a rising edge since" can be worked out, because the
dial is periodic. For anything else in a place rule's `when`, catch-up does the
plain comparison.

### 8.5 Setting it, and reading it

* **`edit world`** gains clock fields through `world/menus.py`, in order of how
  often they will be wanted:
  * the year;
  * the date and hour it is now;
  * how long a day lasts in real time, a real day unless changed.

  Every one can be typed as well, and every one can be put back to the real
  world.
* **`view world`** says the date, the time and the period. `view rules` lists becomes
  rules under their own heading, "when things change", in firing order, with
  the report beside each.
* A `{time}` token and in-game memory ages are §15, not this plan.

**The clock runs on real time while the world sleeps.** It costs nothing, since
it is only read, and quest deadlines already do the same. There is no setting to
stop it while nobody is there (§12).

### 8.6 What world generation may choose, and who is told

**World generation may set the clock, and does not have to.** The world wizard's
spec (`lore.store` and `lore.spec_of`) gains an optional `clock`, so that `edit
world` shows it and `reset world` keeps it. The generator is asked about it with
the defaults stated: "Leave this empty for the real date and time. Set a year if
the setting has one. Change the length of a day only if this world's days truly
differ." A setting that names an era gets its year. Everything else stays real.

**NPCs are told the date**, because roleplay is what a year is for. The prompts
`npc_gen` builds already carry the world's description and guidance. They gain
one line from `clock.said(world_root)`, such as "It is a Tuesday evening in June,
1852." A barman who knows it is 1852 does not mention the telephone. It is one
line and costs one lookup, and the model is never asked to keep track of time
itself.

---

## 9. The three cases, worked

**Hunger.**

1. Register a gauge `hunger` with a `rate` of -0.01. Every character who gains
   it drains, which `traits.ensure` already does from the register.
2. Register the derived states `hungry` (`hunger max 30`) and `starving`
   (`hunger max 10`) in group `hunger_level`. Give `starving` the bonuses
   `{"strength": -3}`.
3. Write the eat rule: a carry-out `set_trait hunger change 40`.

No other rule anywhere mentions a number. A check rule that wants people fed
asks `lacks: ["starving"]`. When hunger falls past 10 with a player in the room,
the character's crossing timer fires, `starving` becomes true, strength drops,
and the character is told. Eating raises hunger, `starving` stops holding, the
bonus goes, and the timer is re-armed for the next crossing.

**Death.** Write one becomes rule at world scope, `when health max 0`, which adds
`dead` and drops what they carry, with a report. A sword blow that takes health
to 0 is narrated, then settled, then the collapse is reported. A poison draining
health reaches 0 on its timer if anyone is watching, or at the next checkpoint
if nobody is. `dead` is in `life_status`, so `prevents_acting` already stops the
body getting up. Starvation can reuse the rule: a becomes rule "when hunger max
0, set health rate -0.05" hands over to it.

**The phoenix.** Write a becomes rule scoped to the kind `phoenix`, `when` it
`is: ["dead"]`. It removes `dead`, sets health to full, and reports "{direct}
$pconj(burst) into flame, and $pconj(rise) from the ashes." Nothing about the
world's death rule changes. A killing blow runs like this:

1. The first pass fires the world's rule. The phoenix is dead, drops what it
   carried, and collapses.
2. `set_state` marked it changed, so the second pass finds `dead` newly true and
   fires the phoenix rule. It rises.
3. Rebirth marked it changed again, and the third pass finds neither
   `health max 0` nor `is: dead` newly true. Both rules are ready for the next
   death.

It dies first and is reborn straight after, which is what a phoenix does. It
also drops its things, because it really did die. A world that wants a phoenix
to keep them splits the dropping into its own rule on `becomes dead`, and guards
that rule, not the death.

**The town at night.**

* Nothing to set up. Every world has `night`, by the real clock unless it says
  otherwise.
* The shop: a check rule on `buy`, scoped to the shop room, with the condition
  `{"subject": "world", "lacks": ["night"]}`.
* The bell: a becomes rule, `about: here`, scoped to the town zone, `when` the
  world `is: ["dawn"]`, with the report "Somewhere across the town, a bell
  rings."

It rings in every occupied room of the town at dawn, and in no empty one.

---

## 10. Where this meets what is already here

* **`world/rulebooks.py`**: `BECOMES` and `STORED_PHASES`. `blank` and `add`
  accept them. `blank` gains `report`. `gather` skips becomes rules unless asked
  for that phase, and returns them most general first (6.3). `Attempt` takes an
  explicit room. `orphans` covers the place memo, `becomes_seen`. `gather` can
  leave guards untested (`guarded=False`), for the after phase (6.8).
* **`world/conditions.py`**:
  * `all` and `any` in `_judge`, the three moods, `progress`, `complaints`,
    `unmet` and `achieves`, normalised and capped;
  * the table of opposites and refusals, the new `not_` predicates, the `below`
    and `above` trait bounds, and `negate`;
  * `as_goal` and `from_goal` for `any` and the plannable opposites;
  * the `clock` predicate in `predicate_of`, `_judge`, `describe` and the tool
    schema;
  * `Context` gains `room`, and `resolve("here")` falls back to it;
  * `resolve` treats a role bound to a deleted object as not found;
  * `eventually`, closed per predicate (7.4);
  * `cause` joins `ROLES`.
* **`world/tokens.py`**: `cause` joins `ROLES`, last, which reserves it and puts
  it in `events.RANK`.
* **`world/verbs.py`**: `register_state` accepts `when` and `bonuses`, and
  refuses cycles and mixed groups. `implied_states` evaluates derived states.
  `blocked` reads implied states through the gate index. `apply_states` refuses
  derived slugs, marks dirty, and calls `gear.recompute` for people. `condition`
  prints derived states.
* **`world/traits.py`**: `adjust` and `notice_changes` mark dirty. Crossing
  arithmetic. `descs` promoted to derived states (5.7).
* **`world/gear.py`**: states as a source in `total` and `sources`.
* **`world/effects.py`**: every effect tolerates a missing actor.
* **`world/attempt.py`**: in `_with_rule`, after rules are gathered unguarded,
  and their guards are tested together after carry-out, against the attempt's
  room (6.8). `settle` runs after `_release` and at the end of `consequences`.
* **A new `world/becoming.py`**: the dirty set with its befores, who caused
  what, `settle`, the place memo,
  the pass limit, the crossing timers and the clock timer. It is one module
  because it is one question: "has anything become true".
* **A new `world/clock.py`**: the date over `datetime`, setting the year and the
  speed without a jump, boundaries and the next boundary, seeding the periods,
  and `said` for prompts and `view world`.
* **`world/lore.py`**: an optional `clock` in `store` and `spec_of`.
* **`world/worldgen.py`**: the clock question, with the real world as the stated
  default (8.6).
* **`world/npc_gen.py`**: one line of date and time in NPC prompts.
* **`typeclasses/characters.py`, `npcs.py` and `objects.py`**: the before in
  `at_pre_move`, settling in `at_post_move`; `at_post_puppet` wakes the world.
  In `npcs.py`, `_pursue_goal` records `goal_waiting` without counting a stall,
  checks it on each turn, and resumes. The idle prompt is told what the NPC is
  waiting for.
* **`server/conf/at_server_startstop.py`**: arming timers after a reload.
* **`world/planner.py`**: `any` goals take the first branch with a step, and the
  plannable opposites are planned (4.5). Derived states are expanded in
  `_for_condition`, through `negate` for `lacks`. A goal about a state a becomes
  rule adds (`is: dead`) takes that rule's `when` as a subgoal, one step deep.
  `_for_condition` and `_towards` answer "not yet" through `eventually`, and
  `plan_for` returns waiting. `advise` and `blocker` say so (7.4).
* **`world/rulecheck.py`, `suggest.py` and `commands/rules_subject.py`**: every
  reader of `is` and `lacks` walks trees. A rule is dead only when every branch
  of an `any` is dead, and `edit rules dead` uses the same test.
* **`world/rulecheck.py`**: states set only by becomes rules count as settable.
  New faults:
  * an after rule guarded against the state its own carry-out adds, the twin of
    `self_defeating` for check rules (6.8);
  * a rule that requires a condition and its negation at once;
  * a becomes rule whose `when` nothing can bring about, such as a trait no
    effect lowers and no rate drains;
  * a derived state some effect writes;
  * overlapping bands over one trait in one exclusive group;
  * rules that exceed the pass limit;
  * what already matches a becomes rule when it is added (6.4).
* **`world/suggest.py`**: the plan had it propose a becomes rule for a gauge seen
  at its bound with nothing to say what that means. Phase 9 does not, on
  purpose. A proposal is a rule, and nothing but a model can say what running
  out of a figure means here -- dead, fainted, or nothing at all -- so a
  proposal would be a guess dressed as evidence. Instead the first time a gauge
  actually runs out is the evidence, and it asks `rule_gen` the question
  directly (below).
* **`world/rule_gen.py`**: `any` one level deep and the opposites in the schema.
  The prompt says combinators are for "or", and `validate` complains about a
  check rule packed into one `all`. The becomes phase and `report` go in the
  schema, prompt and `validate` too, and `validate` refuses a becomes rule that
  names `cause` without guarding on it being bound. That question ("what
  happens when this runs out?") is never asked when a verb is attempted. It is
  asked the first time somebody's gauge in this world really runs out, rather
  than when the gauge is registered: once per figure, only where somebody pays,
  and not for a figure a becomes rule already watches. Many gauges never run
  out, and a question nobody needed answering is a call nobody should pay for.
* **`commands/rules_subject.py` and `world_subject.py`**: the listing in 8.5 and
  the clock fields.
* **`world/crossing.py`**: nothing. Things keep no memo, and the place memo is
  on the world root.

---

## 11. Phases

Each phase ships on its own, is useful on its own, and is tested with `unit`
tests and a hand-moved clock. None needs a model.

**Phase 1: combining and negating conditions.** `all` and `any` through every
reader in 4.5, the table of opposites and refusals, the new predicates and trait
bounds, `negate`, the goal shape for `any`, and the three tests in 4.6. It is
useful on its own: a check rule can take a key or a lockpick, and a rule can ask
that somebody is not holding something. Everything later is built on it.

**Phase 2: after rules see what happened.** Unguarded gathering for the after
phase, guards tested together after carry-out, `Context.room`, destroyed
participants read as missing, and the self-defeating after-rule fault. It is
small, needs nothing else in this plan, and fixes a fault that fails silently
today. Afterwards "after stabbing somebody, when their health is at most 0" works.

**Phase 3: derived states.** Register `when`, `implied_states`, the gate index
and `blocked`, refusal at every write door, `condition` output, cycle and
mixed-group refusal, and planner expansion. Afterwards "starving" is defined
once and read everywhere, and the band is always correct when read, even with no
events.

**Phase 4: states that carry bonuses.** `gear.total` and `gear.sources`, and
recompute on state change. Afterwards "starving costs strength" works.

**Phase 5: becomes rules, from direct changes.** The phase, `report`,
marking and befores at the doors, `settle` at the call sites in 6.3, the pass
limit, effects without an actor, the `cause` role and its guard, and the
`view rules` listing. The listing is in
this phase and not a later one, because the open sandbox means a rule that fires
has to be readable the day it can fire. Afterwards a blow that takes health to 0
kills.

**Phase 6: predicted crossings.** Rate arithmetic, the thresholds,
per-character timers, waking at puppet and at arrival, and re-arming after a
reload. Afterwards a poison kills while somebody watches.

**Phase 7: the clock.** `world/clock.py`, the `clock` predicate, the seeded
periods, the per-world boundary timer, place subjects with silent catch-up, the
`edit world` and `view world` fields, the clock in the world spec and the world
generator's question, and the date in NPC prompts. Afterwards the town, the shop
and the bell work, and a world set in 1852 has NPCs who know it. The place memo arrives in this phase, because nothing before it
changes a place with nobody there.

**Phase 8: not yet.** `conditions.eventually`, "not yet" and waiting in the
planner, `goal_waiting` and resuming in `_pursue_goal`, the wait in the
per-character timer, `MAX_WAIT`, the idle prompt line, and `advise` and
`blocker`. It comes after the clock and predicted crossings because it predicts
with both. Afterwards an NPC that wants bread at midnight does something else
until morning, then goes and buys it.

**Phase 9: authoring and diagnosis.** `rule_gen` writing becomes rules and
reports when a gauge first runs out, the new `rulecheck` faults, bands from
`descs`, and the planner following a becomes rule. Afterwards a generated world
works out what running out of health means, and says when it got it wrong.

---

## 12. Decisions on the record

* **Rules, not a trigger system.** Conditions, effects, scope, specificity,
  listing, suspending, the scan and the suggester already exist once. A second
  system would grow its own copy of each, which `basic-principles.md` rules out.
* **"And" and "or" belong to conditions, not to rules**, so that rules, goals,
  quests, derived states and refusals all get them at once.
* **No `not`.** Every predicate declares its exact opposite once, or declares
  that it cannot be negated. `negate` works out mirrors when they are needed, and
  no mirror is ever stored.
* **Combinators are for "or".** A check rule keeps one requirement per rule, so a
  refusal names what is missing.
* **No tick, no scan.** A rule is tested against a thing because that thing
  changed, or because a worked-out moment arrived in an awake world.
* **Becomes rules add, never override.** Every rule that became true fires, most
  general first, so a specific rule refines a general one by coming after it.
  There is no `instead` for this phase. Rules chain as conditions and effects
  do, and nothing stops anything.
* **A rule fires when its `when` goes from false to true, and nothing else.**
  "Stops being" is the same edge on a negated `when`, so it needs no syntax of
  its own. Mutually exclusive states make the negation read as what it means.
* **No `was` clause.** A rule cannot name where a thing came from, and nothing
  found needs it to:
  * **Bands over a trait already have direction.** "Cools from boiling to hot"
    is `below 100` becoming true, which only happens on the way down. "Warms
    into hot" is a different edge.
  * **"Stops being" covers written state groups.** Almost every consequence
    cares about one end: unlocked is no longer locked, shut is no longer open,
    and risen is no longer dead.
  * **Where both ends matter, the cause already knows them.** A written state
    changes only through some rule's effect, and that rule's guards saw the
    before. If rain turning to snow means something clear turning to snow does
    not, the consequence belongs with whatever turned the rain to snow.

  Derived states are never written by a rule, but they change only because a
  trait, the clock or another state did, so the first two points cover them.
* **The before is taken at the door, not remembered.** A thing's changes all
  come through a door that can see the before. Only places, which change with
  nobody there, keep a memo.
* **A new rule waits for a change**, and says what it already matches rather
  than silently applying to it.
* **Places catch up once, silently.** Effects happen and reports are dropped.
* **Derived states are never written**, and groups do not mix derived and
  written members.
* **Death stays a written state.** Being dead is sticky, and hunger is not.
* **After rules test their guards after carry-out**, all together and before any
  after rule's effects land, against the room the action happened in. Scope is
  still matched where the action happened.
* **Reports are templates.** Nothing that fires calls a model.
* **`cause` is a reserved role, bound only at the time somebody acts.** Chains
  in the same settle keep it. Drift, the clock and place rules have none. Credit
  belongs to the act, when it happened, and a trait never remembers who set its
  rate.
* **The clock runs on real time**, per world, and is read rather than kept.
* **Every world has a clock, and its defaults are the real world's**: today's
  date, the local time, a real day. A world changes only what it needs, most
  often the year. World generation may set it and does not have to. NPCs are told
  the date.
* **A room with only NPCs in it is occupied.** Place rules fire and report there
  as they would for a player. NPCs are equal to players here, and what they do
  about it is already gated by `activity.npc_may_act`.
* **A clock never stops while nobody is there**, and no world can ask it to. A
  clock that runs only while somebody is watching makes the time depend on who
  has been logged in. That is confusing to a player, to somebody building a
  world by hand, and to a model reasoning about when morning comes. A world that
  wants slower days sets a longer day.
* **The planner waits for what will come true on its own.** Only the clock and
  traits with a rate qualify. Anything that needs somebody to act is not worth
  waiting for, because nobody can say when that will be. A waiting NPC does other
  things, is woken when the wait is due, checks, and resumes.

---

## 13. Risks

* **The order things are said in.** Settling after `_release` is the fix, and
  the backstop `callLater(0)` could still beat a narration that is waiting on a
  model when the write came from outside the pipeline. The ordering needs a test
  with a delayed fake sponsor, not just a synchronous one.
* **`implied_states` gets slower**, and `blocked` is on the path of every step and
  every line of dialogue. Mitigated by the index in 5.2. Measure it on the largest
  exported world before and after phase 3.
* **Stored after rules change meaning.** Any after rule whose guard was written
  against the before now answers against the after. The ones that stop firing
  altogether are the self-defeating kind, which `view faults` names. The ones
  that fire differently cannot be found mechanically. Soak a world with learned
  after rules before and after phase 2, and compare the counts.
* **Chains.** The pass limit stops loops, and it cannot tell a loop from a long
  honest chain. The fault report is how a world finds out which it had.
* **Model misuse.** The commonest check-rule mistake is an inverted condition, and
  here it inverts the edge. A death rule written `when health min 1` fires when
  somebody is *healed*. `validate` should reject a becomes rule that already
  holds for the subject it was written about, since a consequence that is
  already true is not waiting to happen. The prompt should name "stops being" as
  the negation, so a model does not reach for a field that does not exist.
* **A longer list of predicates for a model to choose from.** About eight
  opposites and two bounds are added, and an inverted condition is already the
  commonest mistake a model makes. Value flips keep the growth down where they
  read naturally. The soak should count how often a model picks a `not_`
  predicate where the plain one was meant.
* **An opposite that is not quite exact** is a silent bug in everything that
  negates, and it hides at the edges: a missing subject, a missing figure, a list
  of several values. The complement test in 4.6 is the guard, and its fixtures
  have to cover those edges.
* **Asking every becomes rule about a changing thing.** Phase 5 has no index
  (6.4), so every door asks every becomes rule that applies to the thing. That
  is cheap while becomes rules are few. A world with hundreds of them would want
  the index, and a soak should say when.
* **Money, indirectly.** A report is an event, and events wake NPCs. Every
  reaction passes `activity.npc_may_act`, so an NPC with no player nearby spends
  nothing. `worldmode always` lifts that brake, though, and then place rules
  firing across a whole zone at dawn, in NPC-only rooms included, are a burst of
  reactions at one moment. Watch it in a soak with `always`.
* **A report must reach NPCs through the gated path.** The first point only holds
  if a becomes rule's report reaches NPCs the way every other event does, through
  `witness` and `_trigger_reaction`. A delivery path of its own that wakes NPCs
  directly would skip the gate. A test should hold that.
* **Waiting NPCs still think.** A waiting NPC takes ordinary idle turns, and
  those are model calls. That is what an NPC with no goal costs, and today's
  stalled NPC costs the same, but a world full of NPCs waiting for morning is a
  world of idle chatter until then. `MAX_WAIT` bounds it, and so does
  `activity`.
* **The estimate for `all` can be wrong.** A member true now may be false when
  the others arrive. Checking again on waking makes it self-correcting, but a
  goal whose conditions never line up would wait, wake and wait again. Count
  re-waits for one condition, and treat too many as a stall.
* **Timers after a reload.** `ndb` timers vanish on a reload, and the start hook
  arms them again. If it is missed, nothing is lost, only precision, because
  every crossing is still found at the next checkpoint.

---

## 14. Open questions


---

## 15. Out of scope, deliberately

* **Every turn rules and scenes.** Still refused, for the reasons in
  `rulebooks-from-inform.md` §3.
* **Invented calendars**, with days, months or years of other lengths. The real
  calendar and a settable year cover the change most worlds will want.
* **Conditions on the date**, such as a weekday or a month ("the market is open
  on Saturdays"). The date is already there to read, so a later predicate costs
  little, but nothing here needs one yet.
* **Seasons, moons and weather.** `future-plans.md` has "templated features ...
  weather and climate and moons with phases". These are periods over a longer
  dial, and belong there, built on this.
* **Per-zone clocks**, for planets with their own days. The shape allows an
  offset per zone later.
* **A `{time}` token, in-game memory ages, and the `period` scope** deferred by
  `tokens-and-phrases.md` §12.
* **Writing becomes rules by hand through menus.** That belongs to the "full
  menu-based building" item in `future-plans.md`. Until then, becomes rules come
  from the generator, from suggestions, and from the standard rules.
* **Which effects an NPC's after rules may use.** In `_with_rule`, carry-out
  effects are filtered by `allow_effects` and `_hits_everyone`, so an NPC acting
  on its own cannot use `move_actor`, `modify_room` or an effect on everyone
  present. After-rule effects are applied unfiltered, so an NPC's action can
  still reach those through an after rule. That was believed to be deliberate
  when it was noticed, but the reason was not remembered, and the commits that
  wrote the after phase (`663dc64`) and the filter (`79ee51a`) do not say.
  Phase 2 leaves this exactly as it is. Settle it separately, once the reason is
  found or ruled out. The same question will apply to becomes rules an NPC's
  action sets off.
