# Rulebooks, taken from Inform 7 and made generatable

The companion to [rules-and-rulebooks.md](rules-and-rulebooks.md), which argues
that rules must stop belonging to verbs. This one says exactly what to build,
on the grounds that Inform 7 has already solved this problem and the answer is
worth copying rather than reinventing.

Everything here is a template: a record with a fixed set of slots, every slot
filled either from a closed menu or from a closed condition language. Nothing a
model writes here is prose, except one sentence per rule that exists to be read
by a person.

---

## 1. Why Inform, and the one place the analogy breaks

Inform 7 has thirty years of parser-IF behind it and its action machinery is the
most thoroughly tested answer in existence to "a world where anything can be
tried on anything". It is worth being precise about *why* it works, because one
of its reasons cannot transfer.

It works because:

* an **action** is declared once, separately from what it does;
* what it does lives in **rulebooks**, not in the action;
* a rule is attached to **what it is about** -- a thing, a kind, a room, a
  region -- and says so in its preamble;
* rules are sorted **most specific first**, mechanically;
* every rule has a **name**, so it can be listed, unlisted, reordered, and
  printed as it fires;
* an action can be **replaced by another action** mid-flight.

It also works because **rule bodies are arbitrary code.** `Instead of opening
the safe: now the safe is open; increase the score by 5; move the player to the
Vault;` is a program. That is the half that cannot transfer: a model writing
code is the one thing this project has refused from the start.

So the honest statement of what we are doing: **we take Inform's architecture
whole, and replace its body language with a closed effect vocabulary.** The
architecture is what makes rules composable, orderable, addable and printable,
and none of that depends on the bodies being Turing-complete. What we lose is
reach -- there will be things a world wants to do that the effect vocabulary
cannot say -- and section 11 is about measuring that rather than guessing at it.

The claim "Inform can express anything a MUD needs" is true of Inform. It will
not be true of us on the day we start. The architecture is what lets it become
true incrementally, because every gap is a new entry in one closed list rather
than a redesign.

---

## 2. What Inform actually does

Stated accurately, because the mapping in section 3 depends on it.

**Actions are declared.** `Powering is an action applying to one thing.` The
declaration fixes the arity and the accessibility each noun needs -- `one
visible thing`, `one touchable thing`, `one carried thing`, `two things`,
`nothing`. `applying to one carried thing` is why Inform can silently pick
something up before using it.

**Six rulebooks run per action, in order.**

| Rulebook | What it is for | If a rule fires |
|---|---|---|
| before | intervene before anything is decided | may stop or continue |
| instead | this action means something else here | replaces the action, processing ends |
| check | reasons it cannot happen | may stop the action with a refusal |
| carry out | what actually changes | all of them run |
| after | consequences, once it has worked | stops processing unless it continues |
| report | what everyone is told | prints |

The Standard Rules ship dozens of named check rules -- "can't take what's
fixed in place rule", "can't insert into closed containers rule", "can't wear
what's not clothing rule". They are exactly cumulative refusals in a shared
rulebook, written once, applying to every object in every game.

**A rule's preamble is an action pattern plus a condition.**
`Instead of taking the crown when the player is not wearing the robe:` The
pattern can name a specific thing, a kind, a room, a region, or any action at
all (`Instead of doing something to the safe`).

**Rules are sorted most specific first**, by a documented comparison: a named
action beats "doing something"; a specific noun beats a kind beats anything; a
rule with a `when` clause beats one without; a rule confined to a room beats one
confined to a region beats one confined to nothing. Ties fall back to the order
they were declared in.

**Every rule has a name**, and a name is a handle:

```
The can't take people rule is not listed in the check taking rulebook.
The new rule is listed before the can't take people rule.
```

**An action can be replaced.** `Instead of powering the console: try powering
the ship;` Inform calls this trying another action, and it is how one typed
command becomes a different one.

**Other machinery** we will come back to: relations (declared, named, typed,
fixed arity), every turn rules (a tick), scenes (begin/end conditions),
activities (before/for/after around non-action processes like printing a name),
"does the player mean" rules (disambiguation scoring), and the `RULES` and
`ACTIONS` debug commands that print each rule as it fires.

---

## 3. What we take, template, or drop

| Inform | Us | Why |
|---|---|---|
| Action declaration | **Take, templated** | The thing we are missing most. Fixes `power` vs `power datapad` at the root, and gives implicit taking for free. §5.1 |
| before rulebook | **Drop** | Inform's own documentation warns against it; everything it does, `instead` does more clearly. Fewer phases is fewer ways for a model to choose wrong. |
| instead rulebook | **Take** | How a verb means different things in different company, and how redirection happens. §4 |
| check rulebook | **Take** | Cumulative refusals. Where most generated rules will live, and the phase that is safe by construction. §4 |
| carry out rulebook | **Take** | Effects. §4 |
| after rulebook | **Take** | Consequences of success. This is the trigger layer, bounded by the action, with no tick needed. §4 |
| report rulebook | **Take as-is** | Already built: per-object, per-outcome narration. Not touched by any of this. |
| Action patterns (thing / kind / room / region / any) | **Take, templated** | Becomes `scope`, over closed identifiers. §5.3 |
| `when` conditions | **Take, templated** | The unified condition language. §5.4 |
| Specificity sort | **Take, made explicit** | Inform's is a documented comparison; ours is a tuple, so it can be printed beside every rule. §6 |
| Named rules, listing / unlisting | **Take** | This is the repair mechanism, and it means a bad rule never requires revising a good one. §10 |
| `try <other action>` | **Take, templated** | `power` in a ship becomes `power the ship`. §5.5 |
| Implicit taking | **Take** | Falls out of `applies_to: carried`. Removes a whole class of refusals. §5.1 |
| Accessibility (visible / touchable / carried) | **Take** | `relations.reachable` already computes it; it becomes two world-scope check rules. §8 |
| `RULES` / `ACTIONS` | **Take** | The `rules` command. Non-negotiable: see §10. |
| Rule bodies as code | **Replace** | Closed effect vocabulary. §5.5 |
| Relations | **Later, templated** | Declared, named, typed, fixed arity -- the disciplined form of the triple store rejected in the previous note. §11 |
| Every turn rules | **Drop** | A tick. This project's best property is that an unwatched world costs nothing. `after` rules cover consequence; checkpoints cover delay. §11 |
| Scenes | **Drop** | Quests and goals are this, with rewards attached. |
| Activities | **Drop** | Narration is this. |
| "Does the player mean" | **Drop for now** | `naming.py` and `verbs.similarity` already score candidates. |

---

## 4. The four rulebooks we run, precisely

```
declare -> gather -> instead -> check -> carry out -> after -> report
```

**Gather.** Every rule whose action pattern matches this action and whose scope
matches a participant, the room, an enclosing zone, or the world; then drop
those whose `when` fails. Dict lookups against an index, bounded by the number
of scopes in play. Free.

**Instead.** The most specific gathered `instead` rule wins outright. Its
effects run, or it redirects to another action, and processing ends. One winner
only -- the specificity order decides which, and the order is printable.

**Check.** *Every* gathered check rule must pass. All of them, cumulatively, in
specificity order; the first failure supplies the refusal sentence and stops the
attempt.

This phase is the heart of it, and it is safe by construction: a check rule can
only ever make an action stricter. A world can accumulate five hundred of them
and none can change what a verb means. That is what makes "add a rule later"
safe, and it is why a model is steered to write check rules by default.

**Carry out.** Every gathered carry-out rule runs, in specificity order, as in
Inform. In practice there is one, because of a generation rule rather than an
engine rule: **a carry-out rule may only be written for an action-and-scope pair
that has none.** A model that wants different behaviour for spacecraft writes an
`instead` rule. Inform's own idiom, and it makes contradictory effects
structurally unlikely without forbidding anything.

The winning rule -- instead, or the most specific carry-out -- also supplies the
contest, so there is exactly one roll per attempt.

**After.** Gathered after-rules for what actually changed. They run once. No
recursion, no second pass, no depth counter needed: an after rule cannot trigger
another after rule, because after-rules are gathered before any effects land.
This is deliberately less powerful than Inform, and it is what lets "the ship
launches and everyone aboard is weightless" be a rule on `spacecraft` rather
than a clause in `launch`.

**Report.** Unchanged. `verb_gen.narrate`, cached per object per outcome.

---

## 5. The templates

Everything below is the complete slot list. A model is never asked for anything
that is not one of these slots, and every slot is either a closed identifier, a
number, a boolean, a condition from §5.4, or an effect from §5.5. Two fields
hold prose, and both exist to be read by a person rather than acted on: a rule's
`name`, and an action's `means` -- which is itself a dictionary gloss unless a
model improves on it.

### 5.1 Action declaration

One per verb per world, written the first time the verb is seen, before any
rule.

```json
{
  "action": "power",
  "sense": "power.v.01",
  "means": "supply the force or power for the functioning of",
  "applies_to": [
    {"role": "direct", "access": "touchable", "optional": true}
  ]
}
```

| Slot | Values | Notes |
|---|---|---|
| `action` | a canonical verb | after `canonical_verb`, so `examine` never arrives |
| `sense` | a WordNet verb synset, or `""` | **chosen from a menu**, not written. See below |
| `means` | one sentence | defaults to the sense's gloss; the model may replace it |
| `applies_to` | list of `{role, access, optional}` | roles from the closed six: `direct`, `instrument`, `target`, `container`, `source`, and `actor` is implicit |
| `access` | `visible` / `touchable` / `carried` | `carried` buys implicit taking; `touchable` is `relations.reachable` |
| `optional` | bool | a role that may be left unsaid |

#### The sense is picked, not written

`means` started as free text and should not be. A verb has a dictionary entry,
and asking a model to paraphrase one when it could point at one throws away the
identifier and keeps only the prose. So the declaration asks for both, in the
shape nouns already use (`lexicon.sense_prompt`): here are the senses, pick the
one you mean; write your own sentence only if none of them fits.

**Coverage is the reason this works for verbs and did not for nouns.** Of the 100
verbs these worlds have learned, **98 have a WordNet verb sense.** The two
failures are not invented words: `lightly` is an adverb the old parser mistook
for a verb, and `weild` is a misspelling of `wield`. Against the noun picture in
§7 -- `datapad` and `holodeck` with nothing at all -- that is a different world,
and the reason is structural: **worlds invent nouns constantly and verbs almost
never, because a player types verbs and players type English.** (Measured on five
worlds that are schools, hotels and resorts rather than high fantasy, so a world
full of scrying and hexing may yet disagree.)

**Ambiguity is the cost, and it is why the menu is capped.** Verbs are far more
polysemous than nouns: median 6 senses among those learned, mean 9.5, and a third
of them have ten or more -- `break` has 59, `make` 49, `give` 44. So the noun
trick of asking only when senses straddle a bucket, which fires for one noun in
sixteen, does not transfer; nearly every verb would qualify. Show the first five
instead. WordNet orders senses by corpus frequency, so the answer is almost always
among them, and five short glosses once per verb per world is a rounding error
against the call it rides on -- unlike the per-object priors in §7.1.

**The model picks, and that is not a formality.** WordNet's frequency order is a
1990s newspaper corpus, which `lexicon.py` already warns about for nouns. For
verbs it is worse, and `launch` is the example that matters:

```
launch:
  establish.v.01   set up or found                          <- first, and wrong here
  launch.v.02      propel with force
  launch.v.03      launch for the first time; maiden voyage  <- the spaceship
  plunge.v.04      begin with vigor
```

A generator that can see the bridge of a ship picks the third. Nothing in code
could.

**Glosses are lexicographer's prose, which is why `means` stays overridable.**
Most are serviceable -- `burn.v.01` "destroy by fire", `read.v.01` "interpret
something that is written or printed". A real fraction are not: `open.v.01` is
"cause to open or to become open" and `search.v.02` is "search or seek", which
are circular and useless as help text, and some carry editorial debris --
`pry.v.01` ends in a stray "; :" and `wash.v.02` reads "cleanse (one's body) with
soap and water". So the gloss is the default and the sense id is the valuable
part. A model that can say it better should.

#### What recording the sense buys

**Every lexical lookup stops guessing.** `lexicon.verb_ancestors` takes the bare
word and uses `synsets(verb)[:2]`, and that guess is wrong in exactly the way the
menu above predicts:

```
verb_ancestors("launch") -> ['open', 'propel']
```

`open`, because sense one is `establish.v.01` whose hypernym is `open.v.02`. So
the kindred block hands a model the world's **`open` rule** as the starting point
for writing `launch` -- for a spacecraft. `pry` comes back `['open', 'ask']`, half
right and half noise from "be nosey". The causative and entailment lookups added
in §7.1 read the same guessed senses and inherit the same defect. One recorded
identifier fixes all of it, exactly, for nothing.

**What it must not do is key the action.** The tempting next step is to make the
sense part of the action's identity, the way a kind is part of an object's -- so
that drawing a curtain and drawing a sword are two actions. That does not work
here, and the reason is worth stating so nobody tries it: an object carries its
kind, so a noun arrives pre-disambiguated, while **a verb arrives as a bare word
every single time**. Keying actions by sense would mean disambiguating every
attempt, which is a model call per command. So the sense is recorded for lookups
and for help, and the action stays keyed by the canonical verb. A world that needs
`draw` to mean two things says so with `instead` rules scoped to kinds, which is
what §4 is for.

**And synonym folding stays hand-written.** The obvious hope is that
`VERB_SYNONYMS` could be computed from shared synsets. It cannot:
`examine`/`look`, `study`/`look` and `sniff`/`smell` share no synset at all, and
only `consume`/`eat` does. WordNet
does not think examining and looking are the same verb, and the curated table
encodes a decision about this game rather than a fact about English. It stays.

Three looser signals were tried in its place, and all three are worse. They are
written down here because each is the obvious next idea, and because folding
wrongly is now a more expensive mistake than it used to be: two words that share
a rulebook cannot be told apart by an `instead` rule, since the distinction lives
in the verb rather than in what it acts on.

*Shared consequence -- "verbs that cause the same thing are the same verb".*
Tested on WordNet's `causes`, which is the strongest form of the idea because it
is sense-disambiguated. It fails in both directions at once. **Too sparse:** only
17 of 199 cause targets are shared by more than one verb, so for nine in ten
verbs the test fires not at all -- `die.v.01` is caused by exactly one word,
`kill`, not by murder, drown, poison or behead. **And too loose where it does
fire:**

```
everything that causes descend.v.01 : bring_down, cut_down, drop, fell,
                                      lower, strike_down, take_down
everything that causes move.v.03    : circulate, displace, mobilize, move,
                                      move_out, remove, take_out
everything that causes break.v.46   : break, disclose, divulge, expose, leak,
                                      reveal, unwrap
everything that causes act.v.01     : coerce, compel, direct, force, incite,
                                      instigate, obligate, pressure, squeeze
```

Three of those four groups would fold an **engine verb** into something else:
`drop` with `fell`, `remove` with `move`, and `break` with `reveal` -- the last
because `break.v.46` is news breaking. `force` would fold with `incite`.

The reason is not a data problem and no corpus will fix it: **causation is
many-to-one by nature.** Many different actions produce the same outcome, which
is what makes a world worth playing and what the planner exploits. "Achieves the
same end" is not "is the same verb": poisoning and beheading both cause death and
want different instruments, different preconditions and different narration.

*Shared hypernyms -- "verbs that are ways of doing the same thing".* Worse. It
does not recover the hand table at all (`examine`/`look` and `sniff`/`smell`
share no hypernym either), and what it does group is exactly what must stay
apart:

```
everything whose hypernym is open.v.01 : breach, break_open, jimmy, lance,
    lever, prise, pry, unbar, unbolt, uncork, unlock, unseal
```

`_kindred_block` already explains why that list is a set of *relatives* and not
of synonyms: "troponymy says prying is a kind of opening; it does not say that
prying wants something to lever with, and a rule that inherited `open` wholesale
would quietly lose the crowbar."

*ConceptNet, for any of the above.* It would be worse than WordNet here, not
better, for three reasons that need no download to see. Its nodes are words, not
senses, so a `Causes` edge cannot be attributed to the sense that earned it --
and the sense-disambiguated version already failed. Its commonsense edges are
crowdsourced, so two genuine synonyms share an edge only when a contributor
happened to enter both, and the test would measure who typed what rather than
what words mean. And if synonyms are the goal, `/r/Synonym` exists already, so
inferring them from causation is the long way round to a worse answer -- while
that relation is itself word-level and loose, which is the precise property that
makes a cache key drift and the reason `affordances.py` exists.

So: automation may **propose** additions to the table for a person to accept, and
may never fold on its own.

What a bare `power` *does* is deliberately not a slot here. Inform says it with
a rule -- `Instead of powering when the player is aboard a ship: try powering the
ship;` -- and so do we, because a declaration is one per verb while the answer
differs per place. The declaration's job is only to say that the role may be
left unsaid; §8 shows the rule that fills it.

Two things this fixes immediately.

**Arity stops being inferred from what was typed.** Today a rule is keyed
`power#direct` or `power`, and those are two rules that must each be right.
Declared once, `power` applies to one touchable thing, and an attempt that named
nothing is either redirected or refused with "power what?".

**Implicit taking.** `throw` applies to one carried thing, so an attempt to
throw something on the floor picks it up first instead of refusing. Today that
is 54 `holds` clauses across the rule corpus, each separately invented, and a
planner step that has to work out `get` for itself.

### 5.2 Rule

```json
{
  "id": "r47",
  "name": "a ship only launches under power",
  "phase": "check",
  "action": "launch",
  "scope": {"kind": "spacecraft.n.01"},
  "about": "direct",
  "when": [],
  "conditions": [{"subject": "direct", "is": ["powered"]}],
  "effects": [],
  "contest": null,
  "outcome": "stop",
  "listed": true,
  "source": "generated",
  "born": 1757462400
}
```

| Slot | Values |
|---|---|
| `id` | assigned by the engine |
| `name` | one sentence, the only free text; printed by `rules` and by `help` |
| `phase` | `instead` / `check` / `carry_out` / `after` |
| `action` | a verb, or `null` for every action |
| `scope` | see §5.3 |
| `about` | which role this rule's scope is matched against: a role name, `here`, `zone`, or `world` |
| `when` | conditions that decide whether the rule is in play at all |
| `conditions` | for `check`: what must hold. Empty for other phases |
| `effects` | for `instead` / `carry_out` / `after`: what changes |
| `contest` | a check, as today, on the rule that supplies effects |
| `outcome` | `stop` or `continue` -- whether a firing rule ends processing |
| `listed` | false means suspended; see §10 |
| `source` | `generated` / `standard` / `player` -- where it came from |

Rules are stored with their scope: `kind_specs[kind]["rules"]`, `room.db.rules`,
the zone record, `world_root.db.rules`. An index on the world root,
`{action: [(scope, id)]}`, is written alongside so gathering never scans.

### 5.3 Scope

```json
{"object": 4712}            // this one thing
{"kind": "spacecraft.n.01"} // everything of that sort, and of sorts beneath it
{"room": 3920}              // this one place
{"zone": "kepler-9"}        // this area and everything in it
{"world": true}             // everywhere
```

Five forms, every one a closed identifier. There is no free text in a scope, so
a scope cannot drift the way an affordance list drifted. A model choosing a
scope is choosing from a menu of identifiers the world already holds.

`{"kind": ...}` matches a thing whose kinds include that synset **or any
descendant of it**, which is the reuse axis: one rule on `vehicle.n.01` covers
every ship, pod and cart a world will ever generate, because
`lexicon.ancestors` answers that for nothing.

#### The other axis, and why it is not a scope

The taxonomy carves the world one way -- by what a thing *is* -- and a rule
sometimes wants the other: by what a thing is *for*. "Everything readable",
"all machines". WordNet will not give that, and it is not wrong to refuse:
`spacecraft.n.01` descends through `vehicle`, not through `machine`, and an
`inscription` is `written_communication` rather than a `publication`. Each of
those reads as an error and is not one; a carved inscription is genuinely not
published. Three assumptions to the contrary were made and corrected while
building phase 2, and they are tests now.

The temptation is to reach for a corpus. ConceptNet's `UsedFor`, `CapableOf`
and `ReceivesAction` are precisely the functional axis, and they would work.
They must still not be a scope, for a reason that is structural rather than
fastidious: **a scope has to be a closed identifier, stable, printable in
`rules`, and the same whether or not a corpus is installed.** A grouping
computed from edges is none of those. Membership would shift with the corpus,
and a world without ConceptNet would have different scopes from one with it,
which breaks the neutral-degradation rule this whole design rests on.

It is also unnecessary, because the functional axis is already expressible --
as a **condition** rather than as a scope:

```json
{"phase": "check", "action": "read", "scope": {"world": true},
 "conditions": [{"subject": "direct", "affords": ["read"]}]}
```

That reaches every readable thing in the world, out of the world's own settled
affordances (§5.4). And where a world wants to say that in *this* world a
spacecraft is a machine, the mechanism is a **secondary kind** -- the union of
§5.3, declared once per kind, closed and world-local.

So two ways to group by function already exist and neither needs a corpus.
ConceptNet's job stays where §7.1 puts it: proposing what a kind affords, and
proposing an anchor for an invented noun. Both are suggestions into a prompt,
and neither grounds a scope.

### 5.4 Conditions

One language, replacing both `verbs.check`'s role-keyed form and `goals`'
type-tagged form. Every condition is `{subject, predicate, value}` flattened for
readability.

**Subjects** -- the closed list, and the part that is new:

| Subject | Means |
|---|---|
| `"actor"` `"direct"` `"instrument"` `"target"` `"container"` `"source"` | the participants, as now |
| `"here"` | the room |
| `{"enclosure": "<synset>"}` | the nearest enclosing room or zone of that kind |
| `{"zone": true}` | the innermost zone |
| `"world"` | the world |

**Predicates** -- the closed list, every one evaluated in Python, every one
printable in English, every one reversible by the planner:

| Predicate | Example | Replaces |
|---|---|---|
| `is` | `{"subject": "direct", "is": ["powered"]}` | `requires.is`, goal `state` |
| `lacks` | `{"subject": "direct", "lacks": ["damaged"]}` | `requires.lacks` |
| `affords` | `{"subject": "direct", "affords": ["read"]}` | `requires.has` |
| `kind` | `{"subject": "direct", "kind": "vehicle.n.01"}` | nothing -- new |
| `holds` | `{"subject": "actor", "holds": "direct"}` | `requires.holds`, goal `holds` |
| `wears` | `{"subject": "actor", "wears": "direct"}` | goal `worn` |
| `placed` | `{"subject": "direct", "placed": {"in": "container"}}` | goal `placed` |
| `trait` | `{"subject": "actor", "trait": "piloting", "min": 10}` | `requires.trait`, goal `trait` |
| `in_room` | `{"subject": "actor", "in_room": "Bridge"}` | goal `in_room` |
| `exists` / `gone` | `{"exists": {"kind": "key.n.01"}}` | goal `exists`, `gone` |
| `count` | `{"subject": "here", "count": {"kind": "person.n.01"}, "min": 2}` | nothing -- new |

Three operations over them, and three is the whole point:

```python
conditions.evaluate(c, bound, actor, world_root)  -> bool
conditions.describe(c, ...)                        -> "the ship is not powered"
conditions.achieves(effect, c)                     -> would this effect satisfy it?
```

`evaluate` serves check rules, `when` clauses, quest testing and goal testing.
`describe` serves refusals, `help`, quest listings and `rules`. `achieves`
serves the planner. Today these are three partial implementations that have to
guess at each other.

### 5.5 Effects

The existing vocabulary, unchanged, plus four additions. This list is the
ceiling on what any world can do, and it is meant to be extended by hand as
worlds demand -- never by a model.

Existing: `set_state`, `set_trait`, `create_object`, `destroy_object`,
`move_object`, `modify_object`, `modify_room`, `move_actor`.

New:

```json
{"type": "try", "action": "power", "roles": {"direct": {"enclosure": "spacecraft.n.01"}}}
{"type": "stop"}
{"type": "set_exit", "from": "here", "direction": "out", "to": {"zone_room": "docking bay"}}
{"type": "set_relation", "relation": "owes", "from": "target", "to": "actor", "value": true}
```

| Effect | What it is for |
|---|---|
| `try` | Inform's redirection: replace this action with another, with roles filled from scope references. This is what makes `power` and `launch` work. |
| `stop` | An `instead` rule that only blocks, printing its own name. |
| `set_exit` | **The gap that binds first.** Launching a ship should change where its airlock leads, and nothing in the effect vocabulary can touch an exit. |
| `set_relation` | Later, with §11's declared relations. |

### 5.6 Outcomes

`stop` ends processing; `continue` lets later rules run. Defaults, so a model
need not choose: `instead` stops, `check` stops on failure, `carry_out`
continues, `after` continues. Inform's defaults exactly, including the one that
catches authors out -- except that we make `after` default to `continue`, so a
rule about weightlessness cannot accidentally silence the narration.

---

## 6. Specificity, as a sort key

Inform compares rules pairwise by a documented set of criteria. We do the same
thing with an explicit tuple, because a tuple can be printed next to every rule
in the `rules` command, and "why did that rule win" must never be a mystery.

```python
def order(rule, attempt):
    return (
        0 if rule["action"] else 1,            # a named action beats any action
        scope_rank(rule["scope"]),             # below
        0 if rule["when"] else 1,              # a guarded rule beats an open one
        -len(rule["when"]),                    # more guards first
        rule["born"],                          # older first
        rule["id"],                            # total order, always
    )
```

```python
def tier(rule, attempt):
    """Not the scope alone: what the scope was matched against."""
    scope, about = rule["scope"], rule["about"]
    if "object" in scope:                     return 0
    if "kind" in scope and about in ROLES:    return 1   # a thing named
    if "kind" in scope:                       return 2   # the enclosure
    if "room" in scope:                       return 3
    if "zone" in scope:                       return 4
    return 5                                             # world


def depth(rule, root):
    """Deeper in the taxonomy, or deeper in the zone tree, first."""
    scope = rule["scope"]
    if "kind" in scope:  return -len(kinds.ancestors(root, scope["kind"]))
    if "zone" in scope:  return -zones.depth(root, scope["zone"])
    return 0
```

**The tier is not read off the scope alone**, and writing this out is what
found it: §4 orders "the kind of an object named" above "the kind of the
enclosure", and both of those are a `{"kind": ...}` scope. Nothing in the
scope distinguishes them. `about` does, which is why it is a slot rather than
a note -- a rule filed against `spacecraft.n.01` may mean the ship you are
standing in or a model spaceship on the shelf, and the two want different
precedence and different matching. If the tier were guessed from the scope,
the enclosure rule would fire because somebody was carrying a toy.

Two consequences worth stating, because they are the examples that prompted all
this:

**A kind beats a room.** `power datapad` is decided by the datapad's rule, not
by the rule on the spaceship you happen to be standing in, because tier 1 beats
tier 2. The thing the player named wins.

**Deeper beats shallower, in both taxonomies.** `spacecraft.n.01` beats
`vehicle.n.01`; the engine room's zone beats the ship's zone beats the planet's.
Both depths are already computed -- `lexicon.ancestors` and `zones.depth`.

Every tie is broken, down to the id. A world behaves the same way twice.

---

## 7. The prerequisite: a scope is only as good as the kind

Everything above rests on kinds being right, because a scope is a kind and a
rule is only as correct as the thing it is filed against. Measured against the
lexicon as it stands, for exactly the vocabulary a space game uses:

```
word        senses  sense chosen                         asked?
datapad        0    -- kept as the bare word             no
holodeck       0    -- kept as the bare word             no
pod            4    pod.n.01  "the vessel that contains  no
                     the seeds of a plant"
blaster        1    blaster.n.01  "a workman employed    no
                     to blast with explosives"
airlock        1    airlock.n.01  correct                 no
console        4    asked, correctly                      yes
```

Three distinct failures, and none of them is hypothetical.

**An invented noun anchors nowhere.** `kinds.canonical("datapad")` returns
`datapad`, and `lexicon.ancestors("datapad")` returns the empty set. So it has no
taxonomic floor, no hypernym, and **no rule scoped to any kind can ever reach
it**. For a space game that is most of the vocabulary. The docstring in
`kinds.py` says these "are anchored under the nearest real synset, so a
greatsword still lands somewhere closed" -- that is the intention and it is not
implemented; `clothing.create` falls through to `lexicon.head_noun` and stores
the bare word.

**A sense can be confidently wrong.** A blaster is a workman and a VR pod is a
seed case. Both have few enough senses that `needs_sense_choice` returns False,
so the generator is never asked, and the wrong answer is settled for the life of
the world. Unanchored is a gap; this is worse, because a rule scoped to a
hypernym of `pod.n.01` would apply to husks and fruit.

**A compound reduces to the wrong head.** `head_noun("data pad")` is `pad`,
which is a real word, so nothing looks wrong anywhere.

Today this costs a floor of a few affordances -- `implied_affordances` returns
nothing and the model's own list stands, which is survivable. Under this design
it costs much more, because the taxonomy stops being a hint and becomes the index
every rule is filed under. **So anchoring comes before rulebooks.**

The fix is one slot and one cheap test.

```json
// kind_specs["datapad"]
{"under": "device.n.01", "affordances": {...}, "holds": [], "states": []}
```

`lexicon.ancestors` consults it, so `ancestors("datapad")` becomes
`{device.n.01, instrumentality.n.03, ...}` and a rule scoped to `device.n.01`
reaches every datapad in the world. One menu question, asked once per new kind,
and only when it is needed -- which is a free test:

* **no senses at all** -> ask for the anchor. `datapad`, `holodeck`.
* **senses straddle a bucket** -> the existing `needs_sense_choice`. `console`,
  `chest`.
* **the best sense's bucket contradicts what the generator said** -> ask. This
  is the one to add, and it catches `blaster`: the sense is under
  `person.n.01`, the generator said the thing is takeable and wieldable, and a
  person is neither. A contradiction between bucket and declared affordances is
  computable with no model call, and it is exactly the signal that the free
  sense choice was wrong.

`pod` escapes all three, and pretending otherwise would be dishonest: its chosen
sense sits in no bucket at all, so there is nothing for a declared affordance to
contradict. The way to find that class is to instrument rather than to guess --
log every kind as it is settled, with its sense, its gloss and what the generator
said it affords, and read the log of a generated space world. That is how the
kinds change was settled and it is how this should be.

### 7.1 A second lexicon: what ConceptNet adds

WordNet answers what a word **can be**. ConceptNet answers what people **think
is true of it**. Those are different questions with different reliability, and
the difference decides where a second lexicon may be used and where it may not.

**The alignment is exact, and worth seeing verbatim.** ConceptNet's own
definitions, against this codebase's own prose:

| ConceptNet says | aimud says |
|---|---|
| `/r/ReceivesAction` -- "B can be done to A" | "affordances say what can be DONE to this thing" (`affordances.py`) |
| `/r/MannerOf` -- "A is a specific way to do B. Similar to IsA, but for verbs" | "the verbs a verb is a way of performing [...] prying is a way of opening" (`lexicon.verb_ancestors`) |
| `/r/DistinctFrom` -- "something that is A is not B" | "a group IS a set of states only one of which can hold at once" (`verbs.NEW_GROUP`) |
| `/r/HasPrerequisite` -- "in order for A to happen, B needs to happen" | a check rule, section 5.2 |

Four relations that are, definitionally, four things this game has had to invent
for itself. `affordances.py` was written from scratch because "WordNet has an
opinion about six of the sixty-odd affordances these worlds invented"; a corpus
whose whole purpose is the seventh through sixtieth is worth having.

**And there is one property that disqualifies it from everything load-bearing:
its nodes are words, not senses.** `/c/en/pod` is one node for the seed case and
for the thing you climb into. The edges that *are* sense-labelled are the ones
imported from WordNet, which we already have; the valuable commonsense edges --
`ReceivesAction`, `AtLocation`, `HasPrerequisite` -- are exactly the unlabelled
ones. So ConceptNet can never ground a kind, name a scope or enter a cache key.
It is advisory, everywhere, always. `lexicon.py` already states the test it
fails: a lexicon "is never asked what a word MEANS HERE", and "WordNet is a
controlled vocabulary the world selects from, not an oracle it queries."
ConceptNet is an oracle. It gets used the way an oracle should be.

**Two classes of use, and they cost completely different amounts.**

| Use | Relations | Where it lands | Cost |
|---|---|---|---|
| Exclusive state groups -- knowing that open/closed, wet/dry, lit/unlit answer one question | `DistinctFrom`, `Antonym` | `register_state`, `register_group` | **free** |
| Body parts beyond the hand-written list -- a world with beetles in it | `PartOf`, `HasA` | `anatomy.PARTS` | **free** |
| Verb kindred, wider than troponymy and including multiword verbs | `MannerOf` | `lexicon.verb_ancestors` | **free** |
| A proposed anchor for an invented noun, to pre-fill section 7's menu | `IsA` | the anchor question | **free** |
| A third signal that a free sense choice was wrong | `IsA` + `ReceivesAction` against what the generator declared | the contradiction test above | **free** |
| Affordance prior for a kind nobody has settled | `ReceivesAction`, `UsedFor`, `CapableOf` | item, npc and clothing generation | tokens, per object |
| What is plausibly lying about in a galley | `AtLocation`, inverted | `_CONTENTS_SYSTEM_PROMPT` | tokens, per room |
| The state a verb leaves behind -- that opening leaves a thing open | WordNet `causes`, `entailments` | rule generation, group seeding, the planner | **free** |
| Suggestions for a missing condition | `HasPrerequisite` | section 9's Q3 | tokens, per ask |
| Suggestions for a missing consequence | `Causes`, `HasSubevent`, `ObstructedBy` | rule generation, the effects half | tokens, per ask |

The free rows run in Python and cost nothing per call. The last three are prompt
text, and prompt text is paid for every object, every room, for the life of every
world -- which is the arithmetic the README's cost section exists for.
**Disk is cheap and tokens are not, so the free column is where the value is**,
and it is the column nobody would have thought to look in while the corpus was
still a download to be avoided.

`anatomy.PARTS` and the state groups are the clearest cases. `PARTS` is a
hand-written set of about 120 nouns whose own comment admits the problem -- "a
world with beetles and birds in it has mandibles and wings" -- and every creature
a generator invents tests it. Exclusive groups are currently seeded by hand in
`DEFAULT_STATE_GROUP`, folded by a prefix-and-one-edit test, and otherwise
declared by whichever model happened to coin the state; `DistinctFrom` is that
fact, already written down, for every ordinary pair in English.

**The best single result is in WordNet rather than ConceptNet, and it is not
where anybody would look for it.** WordNet carries two verb-to-verb relations
this game has never consulted: `entailments` (408 pairs) and `causes` (220
pairs). Tiny, and *sense-disambiguated*, which is exactly what ConceptNet is not.
Measured against the 100 verbs these worlds have actually learned: 17% have an
entailment and 10% have a cause. And the causes are all one thing --

```
open   causes open.v.03      "the door opened"
close  causes close.v.02     dry  causes dry.v.02
fill   causes fill.v.02      lay  causes lie.v.02
kill   causes die.v.01       ring causes sound.v.02
```

-- the causative/inchoative pair: the transitive verb a player types, linked to
the intransitive change it produces. Which is the link this game has needed and
never had. `affordances.py` already observes that "`burn` and `burning` are one
idea correctly split across two registers", and `world.vocabulary` permits the
overlap deliberately; nothing anywhere *computes* it. WordNet computes it, for a
tenth of every verb a world learns, for nothing, with the senses attached.

Three things want it:

* **Rule generation.** A model writing what `open` does should be shown that
  opening leaves a thing `open`, so it does not coin `unlocked` or `ajar` beside
  an existing word.
* **Group seeding.** A causative pair plus `DistinctFrom` is an exclusive group
  with no model involved: open/closed, wet/dry, lit/unlit.
* **The planner, and this one is a capability rather than a tidying.**
  `_verb_for` currently searches the rules a world has *already learned* for one
  whose effects add the state a goal wants. With causative pairs it can propose a
  verb the world has never learned -- nothing here knows how to make a thing
  open, but `open` is by definition the verb whose cause is being open, so try
  it. A goal that is currently unreachable becomes a verb attempt, which becomes
  a learned rule. The planner stops being limited to what the world already
  knows.

And there is a fourth use, which is where the *many*-to-one shape of causation
earns its keep instead of getting in the way. Inverted, `causes` answers "which
verbs would bring this about" with a set rather than a single word:

```
to make something descend : drop, lower, fell, take_down, bring_down
to make something move    : move, displace, remove, take_out, circulate
```

As a test of whether two verbs are the same word that grouping is useless, and
§5.1 measures how badly. As a list of candidates for a planner that tries one
step and looks again, it is exactly right: more ways to attempt a goal, ranked by
whatever the world has already learned, with the unlearned ones still available
to try. The same property that disqualifies it from folding qualifies it here, and
the distinction worth keeping in mind is that this is an **index, not an
identity**.

**The contract, which is `lexicon.py`'s and stricter.** That module is explicit:
"Nothing here is load-bearing [...] every function below answers neutrally when
the corpus is missing [...] A missing dictionary makes the world slightly
clumsier. It must never make the world impossible." ConceptNet inherits that
whole paragraph, and two clauses of its own:

* **Never a floor.** `kinds.remember` applies the taxonomic floor last "so that
  it wins: a model may add to what a chest can do and may not talk it out of
  being a container." Crowdsourced, weighted, sense-free data must never hold
  that position. It goes in as a prior a generator can disagree with.
* **Never against the world's own guidance.** ConceptNet encodes consensus
  reality. These worlds are allowed not to be: "this is a world of technology;
  magic does not exist" is a guidance line somebody may have written, and a
  corpus asserting otherwise into a prompt is working against the one field that
  exists to overrule it. Advisory, overridable, and behind the guidance rather
  than in front of it.

**Getting it, and why nothing has to be filtered.** The whole corpus is fetched
at first run, not vendored -- and that single decision removes the licence
question rather than managing it. ConceptNet's licence "varies by source",
recorded per edge in the metadata, and the share-alike obligation attaches to
*distributing* the data or a derivative of it. A repository that ships only the
code to fetch it distributes neither, so no edge has to be dropped for its
licence and no part of the corpus is lost to caution. Attribution still belongs
in the README and in the download notice, because it is owed and costs nothing.
The README's "What is safe to publish" section is where this reasoning already
lives, for the database and the API key.

**Storage.** A gzipped TSV of edges is not queryable, and the official loader
wants PostgreSQL, which is far too heavy a dependency for this project. So:
stream the download, keep `/c/en/` nodes, write them into SQLite with indexes on
`(start, relation)` and `(end, relation)`, once, at first run, with a progress
bar, resumable. SQLite is in the standard library, the result is one file beside
`data/nltk_data`, and every lookup is the same shape as a WordNet lookup. Gate
everything behind `commonsense.available()`, exactly as `lexicon.available()` is
gated today.

**What is not known yet.** The downloads page states neither the compressed size
nor the edge count, so the builder should report what it actually built rather
than this note guessing. The decisive measurement is a replay: take the 64
affordance words and every settled kind in the exported corpus, and ask what
fraction of each kind's settled affordance map `ReceivesAction`, `UsedFor` and
`CapableOf` between them would have proposed, after folding through
`affordances.known_verb()` -- its values are participles, "eaten" and "burned",
which that function already handles. Three numbers decide it: coverage,
precision, and novelty against the twelve-bucket `_BUCKET_AFFORDANCES` table.

The expected shape of that result is worth writing down in advance, so that it
can be wrong on the record: **good on ordinary nouns -- bread, door, rope, paper
-- and poor on exactly the invented genre vocabulary that section 7 is about**,
because crowdsourced commonsense has never heard of a datapad either. Which would
mean it improves the easy case and not the hard one. Worth having; not worth
reordering anything for.

**Numberbatch**, the embedding download, is a separate question with one good
answer in it: `verbs.similarity` is word-overlap and deliberately strict, because
"a player typing a noun means it, so only an exact or contained match will do --
guessing at their words is worse than saying 'you see no such thing'." That
reasoning holds for players and is explicitly relaxed for characters, which
"would rather find the blackboard already on the wall than hang another beside
it". So embeddings belong on the NPC side of that threshold and nowhere near the
player's.

---

## 8. The space game, as data

The complete set of records a world would accumulate, in the order it would
learn them. This is the test of whether the templates are sufficient.

**Standard rules, seeded into every world** -- Inform's Standard Rules, written
once by hand, never generated. These are what the current design has to reinvent
inside every rule it learns.

```json
{"name": "you must be able to act", "phase": "check", "action": null,
 "scope": {"world": true},
 "conditions": [{"subject": "actor", "lacks": ["dead", "unconscious"]}]}

{"name": "you must be able to reach it", "phase": "check", "action": null,
 "scope": {"world": true}, "about": "direct",
 "conditions": [{"subject": "direct", "reachable_by": "actor"}]}

{"name": "you cannot move while bound", "phase": "check", "action": "go",
 "scope": {"world": true},
 "conditions": [{"subject": "actor", "lacks": ["bound", "pinned"]}]}
```

**Reach looks upwards as well as downwards.** `relations.reachable` searches
from the actor outwards -- their inventory, the room's floor, inside anything
open -- and stops there, because until a rule could be about a place there was
nothing above to find. A redirect makes the place the direct object: aboard a
ship, `power` means powering the ship, and the ship is not something in the
room, it *is* the room. So `reachable_by` also answers yes for whatever
encloses the actor, and for whatever encloses that -- a pod inside a ship can
still reach the ship. Implemented as `relations.enclosing`, kept separate from
`reachable` so that what a player may *name* is unchanged: "ship" still does
not resolve to the room you are standing in.

Those three replace `prevents_acting`, `prevents_moving` and the accessibility
guesswork now scattered through 121 `lacks` clauses.

**Day one: somebody types `power datapad`.** The datapad is an invented noun, so
§7's anchor question was asked when the first one was made and the kind is
`datapad` under `device.n.01`.

```json
// action declaration, generated once
{"action": "power", "means": "to bring a machine to life",
 "applies_to": [{"role": "direct", "access": "touchable", "optional": true}]}

// carry-out rule, filed at the scope the model chose from the menu
{"name": "powering a device brings it to life", "phase": "carry_out",
 "action": "power", "scope": {"kind": "device.n.01"}, "about": "direct",
 "conditions": [],
 "effects": [{"type": "set_state", "role": "direct", "add": ["powered"]}]}

// check rule, same call
{"name": "a device already running cannot be started", "phase": "check",
 "action": "power", "scope": {"kind": "device.n.01"}, "about": "direct",
 "conditions": [{"subject": "direct", "lacks": ["powered"]}]}
```

Note the scope: `device.n.01`, not `datapad`. The model was offered the kind and
its ancestors and chose the general one, which is the whole reason scopes are a
menu -- every device in the world now powers up, including ones nobody has
invented yet.

**Day two: somebody types `power` on the bridge of a ship.**

The ship is a zone of kind `spacecraft.n.01`. `power` is declared and its
`direct` is optional, so the attempt arrives with nothing bound. Two rules, and
the reason it is two rather than one is worth dwelling on:

```json
{"name": "powering aboard a ship means powering the ship", "phase": "instead",
 "action": "power", "scope": {"kind": "spacecraft.n.01"}, "about": "zone",
 "when": [{"subject": "direct", "unbound": true}],
 "effects": [{"type": "try", "action": "power",
              "roles": {"direct": {"enclosure": "spacecraft.n.01"}}}]}

{"name": "powering a ship wakes its reactor", "phase": "carry_out",
 "action": "power", "scope": {"kind": "spacecraft.n.01"}, "about": "direct",
 "conditions": [],
 "effects": [{"type": "set_state", "role": "direct", "add": ["powered"]}]}
```

The redirect re-enters with the ship bound as `direct`. **But the day-one rule
does not fire**, because WordNet does not put a spacecraft under `device.n.01` --
`spacecraft.n.01` descends through `vehicle.n.01` to `instrumentality.n.03`, and
so does a device, but only at a height where the scope would cover nearly every
object in the world. So the ship needs its own carry-out rule.

That is the honest shape of taxonomic reuse and it is worth not overselling: the
taxonomy gives reuse where English agrees things are alike, and English does not
think a starship is a kind of gadget. What composes regardless is everything in
the check phase -- reach, being able to act, and the ship's own conditions -- and
that is where the volume is.

It is also the concrete form of the open question about scope ceilings. A model
offered `instrumentality.n.03` could have written one `power` rule covering both,
and it would have been a worse world: powering a chair and powering a reactor are
not one rule. Some ceiling on how general a scope may be chosen is needed, and
the taxonomy's own depth is the natural one.

**Day two, ten minutes later: `power` in a VR pod.** The same pair of rules,
scoped to the pod's kind. They cannot collide with the ship's: each is gathered
only when its own enclosure is present, and if somebody builds a pod inside a
ship, the deeper zone wins by `zones.depth`.

**Day three: `launch`.**

```json
{"action": "launch", "means": "to take a craft up and away",
 "applies_to": [{"role": "direct", "access": "visible", "optional": true}]}

{"name": "launching aboard a ship means launching the ship", "phase": "instead",
 "action": "launch", "scope": {"kind": "spacecraft.n.01"}, "about": "zone",
 "when": [{"subject": "direct", "unbound": true}],
 "effects": [{"type": "try", "action": "launch",
              "roles": {"direct": {"enclosure": "spacecraft.n.01"}}}]}

{"name": "a ship only launches under power", "phase": "check",
 "action": "launch", "scope": {"kind": "spacecraft.n.01"}, "about": "direct",
 "conditions": [{"subject": "direct", "is": ["powered"]}]}

{"name": "a launching ship must be sound", "phase": "check",
 "action": "launch", "scope": {"kind": "spacecraft.n.01"}, "about": "direct",
 "conditions": [{"subject": "direct", "lacks": ["damaged", "breached"]}]}

{"name": "a ship underway cannot launch again", "phase": "check",
 "action": "launch", "scope": {"kind": "spacecraft.n.01"}, "about": "direct",
 "conditions": [{"subject": "direct", "lacks": ["in_flight"]}]}

{"name": "launching takes the ship up", "phase": "carry_out",
 "action": "launch", "scope": {"kind": "spacecraft.n.01"}, "about": "direct",
 "contest": {"trait": "piloting", "difficulty": 12},
 "effects": [{"type": "set_state", "role": "direct", "add": ["in_flight"]},
             {"type": "set_exit", "from": "here", "direction": "out", "to": null}]}

{"name": "everyone aboard a launching ship is thrown about", "phase": "after",
 "action": "launch", "scope": {"kind": "spacecraft.n.01"}, "about": "direct",
 "effects": [{"type": "set_state", "role": "everyone", "add": ["weightless"]}]}
```

**Day nine: a world invents traffic control.** Somebody tries to launch from
Kepler-9 while the port is shut. One rule, at a scope nothing else uses:

```json
{"name": "Kepler-9 forbids unscheduled launches", "phase": "check",
 "action": "launch", "scope": {"zone": "kepler-9"}, "about": "zone",
 "conditions": [{"subject": {"zone": true}, "lacks": ["port_closed"]}]}
```

Nothing written on day three is revised. The refusal a player reads is whichever
condition bites first, in specificity order, in the world's own words. And the
planner, handed the same refusal, reads it as a goal condition and works out
`power` as the step before launching -- with no model call, because the refusal
and the goal are now the same language.

**Day nine: a world invents fuel.** Another check rule. Again nothing is
revised. This is the property the previous design could not have at any price.

---

## 8.1 Looking, as the action it should always have been

Everything above is about changing the world. This is about reading it, and the
design has been treating that as a different kind of thing for no reason that
survives inspection.

`look` is a command. It never reaches the pipeline: `verbs.VERB_SYNONYMS` folds
`examine`, `inspect`, `study`, `view`, `x` and `l` onto it, `engine_verbs`
reports it as one the game answers for itself, and `_with_bindings` hands it
straight back to the command set. So no world can hold an opinion about seeing
-- which is the one sense the game offers no rules about, and the sense every
other rule quietly assumes. A world cannot say that its cave is dark, that its
ghost needs the right spectacles, or that its moon is there to be looked at and
not to be touched.

### Three questions wearing one verb

What `look` is asked to do is three different things, and only two of them are
an action:

1. **`look`** -- describe the room. Inform calls this *looking*.
2. **`look at X`** -- describe one thing. Inform calls this *examining*, and
   makes it a separate action.
3. **How X appears inside a room description** -- Inform's *writing a paragraph
   about* and *printing the name of*. This is not an action at all: nobody is
   doing it, it runs while somebody else's action reports.

(1) and (2) fit the four rulebooks exactly. (3) does not, and this section
deliberately does not bend the action shape to fit it -- see **The listing**
below for the part of it that cannot wait.

### One action, not two -- and why this diverges from Inform

Inform splits LOOK and EXAMINE because it must: its rulebooks key on the action
name, so `Instead of examining the painting` needs *examining* to be a thing.

Here they stay one action, because the machinery that separates them already
exists and was built for the spaceship. Declare `look` with `direct` **optional**,
and the two cases are told apart by the predicate §8 already needed:

```json
{"name": "looking about you means looking at the room", "phase": "instead",
 "action": "look", "scope": {"world": true}, "about": "enclosure",
 "when": [{"subject": "direct", "unbound": true}],
 "effects": [{"type": "try", "action": "look",
              "roles": {"direct": {"enclosure": "room"}}}]}
```

That is the `power` redirect with the nouns changed, and it is a **standard**
rule rather than a per-world one. `relations.enclosing` already makes the room a
legal direct object, so after the redirect there is exactly one case to write
rules about: looking at a thing. A rule that means to be about rooms scopes to a
room kind; a rule about a painting scopes to the painting.

The cost is one `unbound` guard on the handful of rules that really are about
looking-about-you rather than looking-at. The saving is a new action, an
unfolding of five synonyms, and a second set of scopes for every world to learn.

### The bug this exposes

The standard rule seeded into every world is:

```json
{"name": "you must be able to reach what you act on", "phase": "check",
 "action": null, "scope": {"world": true}, "about": "direct",
 "conditions": [{"subject": "direct", "reachable_by": "actor"}]}
```

`action: null` means **every** action, including looking. Meanwhile §5.1 gives
every role one of three access levels -- `visible`, `touchable`, `carried` --
`actions.access_for` reads the declared level, and **nothing enforces it**. The
`visible` level has never been connected to anything.

So today the moon is not merely undescribed, it is unlookable, and so is a
notice across the room. Two changes fix it, and both are small:

* The standard reach rule consults `actions.access_for(world_root, action,
  role)` instead of assuming `touchable`.
* A `visible_to` predicate joins `reachable_by`. Reach is already a strict
  subset of sight, so the first implementation is honest and cheap: everything
  reachable is visible, plus whatever a world's own rules add.

`look` then declares `direct` as `visible`, and the moon works.

### The standard rules for looking

The defaults are **exactly the current behaviour**, written down as rules so
that a world can add to them. Nothing about an ordinary room changes.

```json
{"name": "you must be able to see what you look at", "phase": "check",
 "action": "look", "scope": {"world": true}, "about": "direct",
 "conditions": [{"subject": "direct", "visible_to": "actor"}]}

{"name": "what looking at a thing shows", "phase": "carry_out",
 "action": "look", "scope": {"world": true}, "about": "direct",
 "effects": [{"type": "describe", "role": "direct"}]}
```

`describe` is a new effect, and it is the one effect in the vocabulary that is
deliberately **output-only**: it returns the appearance text that
`return_appearance` returns today and changes nothing. Effects already hand back
text -- `effects.apply` returns the lines an attempt says -- so this needs no new
plumbing, and a carry-out that produces prose without a model call is what keeps
looking free.

**On §11.1's invertibility rule.** `conditions.achieves` cannot read `describe`
backwards, and that is correct rather than a hole: no goal is ever "to have been
told something". An NPC that wants to look at the painting wants what *follows*
from looking, and that is an `after` rule with `set_trait` or `set_state` --
both of which `achieves` already reads. The planner reaches looking through the
consequence, never through the description.

### Light, with no light subsystem

Light needs no new code, and the first draft of this plan was wrong to budget a
subsystem for it. `world/gear.py` already has every part:

* An item carries `trait_bonuses` -- `{"light": 2}`.
* `bonus_when` says when they count: `worn`, `wielded`, `carried`, or
  **`present`**, which means lying in the same room and doing it for everybody
  there. The module docstring names the case: *"a room may carry bonuses of its
  own: a forge is warm whether or not anything in it is."*
* `bonus_while` names a state that must hold first. Its docstring names the
  other case: *"An unlit lantern lights nobody."*
* The total is **derived, never accumulated** -- `gear.recompute` rebuilds it
  from scratch, so a lamp put down or carried away needs no bookkeeping and
  nothing drifts.

So the check is one condition on the actor, and the room, a held lamp and a lamp
on the floor all feed the same figure:

```json
{"name": "you cannot see in the dark", "phase": "check", "action": "look",
 "scope": {"world": true}, "about": "actor",
 "conditions": [{"subject": "actor", "trait": "light", "min": 1}]}
```

**Invert the default and darkness is free.** Let `light` be 0 everywhere, and
let lit places and lit things grant it. A cave is then not a room carrying
negative light against a trait floor -- it is a room that grants none, and
needs nothing declared at all. Only brightness is ever stated, which is also
the shorter list.

Two schema fields are missing, and they are the whole of the work:

* Room generation never declares room-level `trait_bonuses`. `worldgen`'s
  contents prompt offers them for the *items in* a room, not for the room.
* That item schema offers `trait_bonuses` and `bonus_when` but not
  `bonus_while`, so a model cannot say "lights you only while lit" even though
  `gear._gate_open` implements precisely that.

The same two fields buy warmth, stench, noise and radiation, none of which is
light-specific. That is the test a capability should pass before it earns code.

### Descriptions written when somebody looks -- measured, and not built

The argument was that a world generates hundreds of objects, a player examines a
dozen, and describing all of them at creation spends money on prose nobody
reads. The pipeline already has the shape for the alternative: the narration
cache writes the words for a verb on an object the first time anybody does it and
replays them afterwards, which is how `read` works.

**The saving is not there.** Every path that makes a describable thing already
carries its description in a call that was happening regardless:

* `worldgen`'s contents pass asks for `{"name", "description", ...}` for 0-3
  items in one call per room -- the call that decides what is in the room at all.
* `item_gen.generate_item` describes the one thing it was asked to conjure.
* the `create_object` effect carries a `description` written by the rule.

So descriptions cost a few dozen extra tokens inside a reply already paid for.
Making them lazy would replace that with **one call per examined object**, which
is more calls and not fewer for any player who examines more than a fraction of
what they walk past. Room descriptions, which *are* a separate call each, are
already lazy in the way that matters: a room is generated when somebody first
walks into it.

What this does cost is the other direction: looking now skips narration
entirely, so a look can never be richer than `db.desc`. A world cannot yet say
"describe the painting vividly, once, and keep it". The fallback that would buy
both -- if a thing has no description, narrate one and store it -- is about
fifteen lines and is **deferred until something actually creates a describable
thing without a description**, because until then it is code that cannot run.

`CmdAILook` already *materialises* objects that do not exist when you look for
them, and that is untouched: a thing conjured by a look is described by the call
that conjures it, then looked at through the pipeline like anything else.

### The listing

Rule-driven paragraphs -- a world deciding how its thing reads in a list -- are
deferred. What cannot be deferred is the **filter**: if darkness stops you
examining the lamp but the room description still lists it, the rule is
decoration. So `get_display_things` consults the same `visible_to` predicate,
and nothing else about the listing changes.

That is not Inform's *writing a paragraph about*, and the gap is recorded rather
than closed. Closing it wants a rulebook that runs inside another action's
report, which is a fifth rulebook, and no evidence yet says it is worth one.

### What comes free

Once looking is an action, three of its uses need nothing built:

* **NPCs can want to look at things.** `goals` and `planner` see `look` like any
  other action the moment it has a declaration and rules.
* **Looking can change somebody.** An `after` rule with `set_trait` -- knowledge
  for reading a map, fear for looking down the well -- and `achieves` already
  reads it, so wanting the knowledge makes looking a plan step.
* **A world can hide things.** Invisibility is a check rule on a kind or a
  state, written by the same question that writes every other rule, with no
  notion of invisibility anywhere in the engine.

---

## 9. Generation: five questions, each a menu

A model is asked for one record at a time, and never for a universal answer.

**Q1 -- declare the action** (once per verb). Its arity, from a menu: which of
the six roles it takes, each `visible` / `touchable` / `carried`, each optional
or not. Plus one sentence of `means`. This is the easiest question in the set
and it is the one the current design never asks.

**Q2 -- what does it mean here?** Asked when an action has no carry-out rule in
scope. The prompt shows the rules already gathered, in firing order, and the
menu of scopes available:

```
Already decided, in this order:
  world : you must be able to act
  world : you must be able to reach it
  kind device.n.01 : powering a device brings it to life
  kind device.n.01 : a device already running cannot be started

File your rule against exactly one of:
  datapad             the thing named
  device.n.01         ... and what that is a sort of
  spacecraft.n.01     the sort of place you are standing in
  vehicle.n.01        ... and what that is a sort of
  kepler-9            this area
  the world           everywhere

Require only what is not required above.
```

**Q3 -- is anything missing?** Asked when an attempt *succeeded* but the
narration or the world suggests it should not have. This is where day-nine rules
come from, and it is the mechanism the current design has no equivalent of.
Cheap, because the answer is a check rule: a scope, a condition, a sentence.

**Q4 -- does this thing differ?** The existing per-object specifics call,
unchanged, folded in as an `instead` rule scoped to the object when it differs
in more than amount.

**Q5 -- narrate.** Unchanged.

Three properties make these answerable:

* **Every scope is an identifier from a list.** The hardest judgement -- how
  general is this? -- is multiple choice.
* **Every rule is small.** One scope, one or two conditions, one or two
  effects. Models write small records well.
* **Nothing must be right, only not wrong.** An incomplete answer is repaired by
  adding, never by revising, because the check phase is cumulative.

### 9.1 What needs no model at all

Three of the five questions above can be partly answered before anybody is asked,
and one class of finding can be produced for nothing at all. **The line between
what may be derived and applied, and what may only be derived and proposed, is
the one §4 already draws:** a check rule is monotone -- it can only ever make an
action stricter, never change what it means -- so a derived check rule is safe to
install. An effect changes the world, so a derived carry-out rule is a
suggestion and must be marked as one.

| Mechanism | Needs | When | May it apply itself? |
|---|---|---|---|
| Consistency scan | nothing -- the world's own rules | a timer, and server start | no: it reports |
| Inverse rules from antonyms | WordNet antonyms | the scan, or rule generation | proposed, suspended |
| Inherited checks from related verbs | WordNet troponymy, entailment | rule generation | **yes** -- monotone |

#### The consistency scan, which needs no corpus whatsoever

The most valuable thing here turns out to need neither WordNet nor ConceptNet: it
is inference over the rule index, and it finds real, invisible, world-breaking
faults. Run against the seven worlds in the development database as they stand:

```
states a rule can add                : 62
states a rule can remove             : 33
one-way states -- set, never unset   : 45   (72% of every state ever set)
required but never settable          :  7
```

**Seventy-two percent of the states these worlds can produce, they cannot
undo.** `lit`, `open`, `wet`, `burning`, `broken`, `cracked`, `folded`, `clean`
and `smooth` are all one-way: a lamp that can be lit and never put out, a door
that opens and never closes. And seven states are required by some rule and
settable by none, so those rules can never fire however long anybody plays.

Those two lists are not separate faults. They are the same missing rule, seen
from both ends -- here is one world:

```
world 3117
  set, never unset          : clean folded harvested lit open parted
                              searched smooth wet
  required, never settable  : closed crumpled growing unlit
  complementary pairs       : (open, closed)  (lit, unlit)  (smooth, crumpled)
```

Something can be opened and nothing can close it; something lit and nothing
unlit; something smoothed and nothing crumpled -- and the rules that wanted
`closed`, `unlit` and `crumpled` are dead on arrival. Three missing rules,
each one showing up twice in the scan, none of them visible to anybody today.

The scan is O(rules), needs no model, and produces a **report** rather than
rules. `memcheck` is the shape to copy: it reports by default, acts when asked,
runs on a clock and at server start. A timer is not the thing this project
refuses -- memory consolidation already runs on one, and `traits.rate` plays out
on another. What it refuses is a timer that spends money, and this one cannot.

**It can also be built today**, against the current monolithic rules, before any
of §12 happens -- the numbers above were produced by a sixty-line script. It
would start reporting on existing worlds immediately.

#### Its findings are free content for the one expensive question

§9's Q3 -- "is anything missing?" -- currently depends on somebody noticing that
an attempt succeeded when it should not have. The scan replaces that luck with a
queue:

> Nothing in this world can make anything `closed`, and two rules require it.
> Should something?

That is a concrete, cheap, high-value question, generated for nothing, about a
fault that is definitely real. It is the best argument for the scan: not the
report a person reads, but the prompt it writes.

#### Inverse rules, which are template-fillable

Of the 51 states these worlds have invented, **28 have a WordNet antonym** (54%),
and the quality is good where it exists:

```
closed->open   clean->dirty   dry->wet      empty->full    bound->free
dead->alive    broken->unbroken   charged->uncharged   dormant->active
```

So when the scan finds `open` settable and `closed` required-but-unsettable, and
the antonym says those two are a pair, the missing rule can be written with no
model at all: **swap `add` and `remove`**, take the verb from the antonym, take
`means` from its gloss, keep the scope of the rule it inverts. That is every slot
in §5.2 filled from data.

It is still a carry-out rule, so by the line above it arrives `listed: false` with
`source: "derived"`, visible in `rules` with a mark, waiting for a person or one
cheap confirmation. Closing is usually un-opening and is not always: a closed
wound is not an unopened one, and the 46% of states with no antonym are mostly the
invented ones -- `harvested`, `piggybacking`, `shimmering` -- where nothing should
be guessed.

#### Inherited checks, which are sound and rarer than hoped

If `pry` is a way of `open`, then whatever `open` requires, `pry` requires. If
`soap` entails `wash`, whatever `wash` requires, `soap` requires. Both are
monotone, so both can be installed rather than proposed, and both directly reduce
what a model has to write -- §9's prompt already says "require only what is not
required above", and this puts more above the line for free.

The honest measurement is that the opportunity is small: of 113 verb-and-world
pairs, **only 4 (3%) have a troponymy parent whose rule the same world has already
learned.** `_kindred_block`'s own docstring says as much -- "nothing is found for
most verbs". Two caveats in opposite directions: that figure is computed through
`verb_ancestors`, which §5.1 shows is guessing senses and guessing some of them
wrongly, so it must be re-measured once senses are recorded; and it can only rise
as a world matures, since it depends on how much the world already knows.

Depth one only. Propagating preconditions up a troponymy chain -- pry to open to
move to act -- ends with everything requiring everything, which is how a monotone
mechanism turns into a world where nothing is permitted.

#### What still needs a model

Worth naming, so the boundary is not tested by accident:

* **Effects for a verb nobody has defined.** Derivation can invert a known rule;
  it cannot invent the first one.
* **ConceptNet `HasPrerequisite` into actual conditions.** The edges are
  phrase-shaped ("start car HasPrerequisite have key") and need interpreting
  against this world's vocabulary, which is a model's job. They stay prompt
  material, as §7.1 has them.
* **Anything that changes what a verb means, without somebody agreeing to it.**
  Every mechanism above either restricts an action or inverts one, and none of
  them may *install* an `instead` rule, because that is the phase where meaning
  lives. Proposing one is a different matter, and §10.1 is how.


---

## 10. Repair without revision

Three mechanisms, in increasing severity, all of them Inform's.

**Unlisting.** `listed: false` takes a rule out of its rulebook without deleting
it, exactly as `The can't take people rule is not listed in the check taking
rulebook.` The rule stays visible in `rules` with a mark, so a world's history is
legible and a mistake is reversible.

**Suspension.** `planner.note_failure` already counts rules that promise
something and do not deliver. Generalised to rule ids, a rule that fails twice
is unlisted automatically and logged.

**The `rules` command**, and this is not a convenience:

```
> rules launch
launch -- to take a craft up and away
  applies to one visible thing (optional)

check
  world              you must be able to act
  zone kepler-9      Kepler-9 forbids unscheduled launches
  kind spacecraft    a ship only launches under power          [not met]
  kind spacecraft    a launching ship must be sound
carry out
  kind spacecraft    launching takes the ship up               (piloting vs 12)
after
  kind spacecraft    everyone aboard a launching ship is thrown about
```

Inform's hardest bug class is rule ordering, and its answer is `RULES ON`. Ours
has to ship in the first version, not the third. A world nobody can debug is
worse than a world that cannot launch a spaceship -- and `help launch` is the
same listing with the scopes left off, so self-documentation costs nothing extra.

### 10.1 Suggesting rules, and who judges them

§9.1 derives what is safe to install by itself. The interesting rules are the
unsafe ones -- a carry-out rule that does something, an `instead` rule that
changes what a verb means -- and those can still be *derived*, as long as nothing
installs them unasked. So: a queue of proposals, filled for free, emptied by a
person or by one cheap call.

**A suggestion is a suspended rule, and needs no new storage.** §10's `listed:
false` already means "in the book, not in force"; a proposal is that plus
provenance.

```json
{
  "id": "d12", "listed": false, "source": "derived",
  "phase": "carry_out", "action": "close",
  "scope": {"kind": "door.n.01"}, "about": "direct",
  "effects": [{"type": "set_state", "role": "direct",
               "add": ["closed"], "remove": ["open"]}],
  "name": "closing a door shuts it",
  "why": "nothing in this world can make anything closed, and 2 rules require it",
  "overrides": null,
  "evidence": {"one_way_state": "open", "unreachable_state": "closed",
               "antonym": "open->closed", "attempts_refused": 7}
}
```

`rules` shows it with a mark, `rules suggest` lists only these, and nothing
anywhere consults a rule whose `listed` is false. The queue is therefore
inspectable, suspendable and deletable by machinery that already exists.

#### Where proposals come from

Every generator is free, and every one must cite **evidence from this world**. A
lexical resource may *name* a candidate; only the world's own behaviour may
justify one. That rule is what stops a queue of plausible nonsense.

| Source | Proposes | Evidence | Have the data today? |
|---|---|---|---|
| A complementary pair from the scan, plus an antonym | `carry_out` inverse | the scan: 45 one-way states, 7 unreachable | **yes** |
| An optional role left unbound and refused, N times, inside an enclosure of kind K | **`instead` redirect** -- the `power` case | attempt counters | **no: needs §10.1's counter** |
| Objects of one kind repeatedly verbed where the winning rule is scoped higher | **`instead`** at the narrower scope | counters, plus kind/verb counts | partly |
| Sibling kinds with identical affordances where only one has a rule | scope **widening** -- fewer rules, not more | kind specs | yes |
| Per-object specifics that agree across a kind | `instead` promotion | `verb_specifics` | **no: measured empty** |

That last row is worth recording as a negative result. The per-object specifics
store holds 65 (kind, verb) entries across these worlds -- `flyer`/read on five
objects, `bottle`/drink on three -- and **every stored body is `{}`**. The
mechanism has been paid for in every narration prompt and has never once found a
thing that differs from its sort. Either the question is not reaching the model
or these objects really are ordinary; either way it cannot be the foundation of a
suggester, and finding that out cost one query rather than a sprint.

The redirect row is the one that matters most, because it is the `power`-aboard-a
-ship case arising by itself rather than being anticipated -- and it needs
something the game does not collect. **Attempt counters are a prerequisite**: per
`(action, scope, outcome)`, a count and a last-seen, incremented in `attempt.py`.
Not a transcript and not a log to be read back; six integers per pair. Without
them every instead-suggestion is a guess, and with them the commonest refusal in a
world becomes the best-evidenced proposal in the queue.

#### Who judges, and why judging is the cheap question

Three routes, and the first is free:

* **A person.** `rules suggest` lists the queue, each rendered in English through
  `conditions.describe`, with its evidence and what it would override. `rules
  accept <id>` sets `listed: true`; `rules reject <id>` records a refusal.
* **A model, in one batched call.** The whole queue goes in at once and comes
  back as accept / reject / amend per entry. The economy here is the point:
  **the model is never asked to write a rule, only to judge one**, which is a
  smaller question with the answer visible in a screen of context -- the proposed
  rule, the rule it would override, and the counts that prompted it. Writing a
  rule means inventing a scope, conditions and effects from nothing; judging one
  means saying yes or no to a filled-in form with evidence attached. Several
  proposals ride in one call, so the cost is per batch rather than per rule.
* **Nothing, ever, automatically.** Generation runs on a timer if it likes, since
  it costs nothing. Evaluation runs when somebody asks.

That split is the whole answer to "can this tick": the free half ticks, the paid
half is a command.

#### Rails

Six, and each of them exists because of a specific way this goes wrong.

1. **No evidence, no proposal.** A count from this world, or it is not offered.
2. **Rejections are remembered.** A declined proposal is recorded as declined, or
   the queue offers it again every time it runs, forever.
3. **No chains.** A proposal may not be derived from a derived rule, accepted or
   not, or a world bootstraps its way into fiction.
4. **An `instead` proposal must be strictly more specific than what it would
   override**, and must name that rule in its `why`. An instead rule at equal or
   wider scope would shadow the thing it was meant to refine, and a wrong one is
   the worst bug this design allows -- it silently makes a verb mean something
   else.
5. **The queue is capped**, and evicts the weakest evidence first. A suggester
   that can grow without bound is a second drift problem.
6. **`source: "derived"` is permanent.** An accepted proposal keeps the mark, so
   an audit years later can ask what this world decided for itself and what was
   suggested to it.

#### What it looks like in the space game

The scan finds that nothing can make a ship `landed`, while `launch` requires
`lacks in_flight`, and the counters find `land` attempted eleven times and
refused. Three proposals, in evidence order:

```
> rules suggest
d3  carry_out  kind spacecraft.n.01   "landing a ship sets it down"
    would add: landed, remove: in_flight
    because  : in_flight is set and never unset; land refused 11 times
d7  instead    kind spacecraft.n.01   "landing aboard a ship lands the ship"
    would redirect: land -> land the enclosing ship
    overrides: nothing
    because  : land typed with no object 11 times aboard a spacecraft
d9  carry_out  kind door.n.01         "closing a door shuts it"
    because  : open set and never unset; 2 rules require closed; antonym open/closed
```

Every one of those was produced without a model, out of the world's own faults
and its own refusals. Accepting d3 and d7 is two keystrokes, or one batched call
that has the counts in front of it.

---

## 11. Where this binds, and the clock we are still refusing

The architecture transfers. The body language does not, and these are the places
a world will notice.

**Exits.** Nothing in the effect vocabulary can create, retarget or remove an
exit. Launching a ship should change where its airlock leads; opening a trapdoor
should make `down` mean something. `set_exit` is in §5.5 for this reason and it
is the first gap to close -- `worldgen._make_exit` and `ensure_return_exit`
already do the work, and no rule can reach them.

**Delay.** Inform has timed events: "the ship arrives in three turns from now".
We have no tick and should keep not having one -- an unwatched world costing
nothing is this project's best property. So a delayed consequence must become a
**condition on a checkpoint** rather than a timer: a ship in flight arrives when
somebody does something about it, or when the next person walks onto the bridge.
`traits.rate` is the existing precedent -- a figure that moves on its own,
evaluated when read rather than on a clock -- and the same trick covers most of
what timers are wanted for. What it does not cover is a consequence nobody will
ever look at, and that consequence does not matter by definition.

**Arithmetic.** Inform can say `increase the score by the weight of the cargo`.
We can say `change: -5`. Properties as values in effects is a real gap, and the
cheapest honest version of it is a small closed set of value references --
`{"from_trait": "..."}`, `{"count": {...}}` -- rather than an expression
language.

**Relations.** Inform's relations are declared, named, typed and of fixed arity:
`Owing relates various people to various people.` That is the disciplined form of
the triple store the previous note rejected, and the objection to the triple
store was never arity -- it was free predicates and unbounded resolution. A
*declared* relation has neither. This is the right way to say "the guild owes
you a favour" or "the brass key unlocks the vault door", and it is a later phase
with its own note.

**How to know which of these matters.** Instrument the generator: when a model
is asked for a rule, let it answer `{"cannot_say": "<one sentence>"}` and log it.
That turns "what is the effect vocabulary missing" from a design argument into a
measurement, which is how the kinds change was settled and how this one should
be.

### 11.1 How the effect vocabulary grows

Effects are the one part of this design that cannot grow by itself. A condition,
a scope, a kind, a state and a trait are all data a world invents as it runs; an
effect is a branch in `effects._apply_one`, and a model may never write one. So
the list grows by hand, and the question is what governs the order.

**The governing rule is invertibility, not frequency.** Every effect type must be
readable backwards by `conditions.achieves`, or the planner and the hint system
silently stop working for every goal that depends on it. `set_state` is perfectly
invertible -- the planner can ask which rule adds `powered`. A hypothetical
`run_script` effect would be uninvertible, and the first goal needing it would
make an NPC look stuck rather than thoughtful. **An effect nobody can read
backwards is not a cheap effect, it is a hole in the planner**, and that is a
harder test than how often a world wants one.

**Three sources, in descending order of usefulness.**

*First: Inform's own world model.* Having taken its rule architecture, the
obvious place to look for the missing effects is the rest of what it ships --
which is the distilled thirty-year answer to "what can change in a parser world",
already closed and already minimal. Set against what `effects.py` can do today:

| Inform has | aimud has | Worth taking |
|---|---|---|
| doors, two-sided, connecting two rooms | exits, built only by `worldgen` | **yes** -- `set_exit`; §11 already has this binding first |
| lockable things with a matching key | a `locked` state that now really shuts an exit; still no key behind it | **partly done** -- refusing and unlocking by rule works; matching *this* key to *that* lock still wants declared relations |
| devices, switched on/off | a state, which is the right answer | no |
| light and darkness, and actions that require light | `gear.py`: `trait_bonuses` with `bonus_when: present` and `bonus_while` | **no code** -- it is a trait, and the mechanism is already built. §8.1 |
| backdrops: one thing present in many rooms | nothing; a sky would have to be a separate object per room | **probably** -- the hum of an engine, a river, a storm overhead |
| pushing things from room to room | `move_object` reaches the actor, this room, or a role -- never another room | **yes** |
| containers, supporters, carried, worn | `relations.py`, `clothing.py`, `gear.py` | already done |
| scenery and fixed-in-place | `kinds.admits("get")` | already done |
| every turn rules, timed events | refused on purpose, §11 | no |

*Second: the measured gap.* The `cannot_say` log above, plus the refusals already
in the database -- 18 of the 85 were classed "genuinely implausible" and some of
those are a model declining because the vocabulary had no room for the answer.
This source is better than any corpus because it is this game's own worlds asking.

*Third, and weakest: mining causal corpora.* ConceptNet's `Causes` and
`HasSubevent` look like a list of effects and are not one. "Dropping a glass
causes the glass to break" has to be classified before it is useful -- is breaking
a `set_state`, or a `destroy_object`, or a `create_object` of fragments? -- and
that classification *is* the design work, which the corpus does not do. What a
causal corpus is genuinely good at is the per-verb suggestion in §7.1's table:
not "which effect types should exist", but "given that these effect types exist,
what should this verb do with them". Those are different questions and only the
second is a lookup.

**So the effect list is not a late step.** Writing it last would leave
`launch` unable to change where an airlock leads until the very end, when §11
establishes that exits bind first. It is a standing item, ordered by what the
rulebooks actually need: `set_exit` with the first real vehicle, cross-room
`move_object` beside it, relations when the first key meets the first lock.

Light is **not** on that list, and the first draft of it was wrong twice. It
needs no effect type, because it is a trait and `gear.py` already sums traits
granted by a room and by what is lying in it. And a bespoke light effect would
have needed new `achieves` support to avoid being exactly the hole this section
exists to prevent, where `set_trait` is invertible already. §8.1 has the
worked example; what remains is two generation schema fields.

That is the test worth applying to every candidate below: a capability earns
code when it cannot be said with the vocabulary already there. The same two
fields that buy light buy warmth, stench, noise and radiation.

---

## 12. Build order

Revised from the previous note, now that actions are declared separately.

1. **Kinds get anchors, then rooms and zones get kinds and states.** §7 before
   anything: an invented noun that anchors nowhere cannot be a scope, and for a
   space game that is most of the vocabulary. Rooms come with it -- all 99
   already carry a `room_type` whose head noun WordNet knows. Both are useful on
   their own, before a single rule exists.
2. **`world/conditions.py`.** One condition language, §5.4, with the new
   subjects. Replaces `verbs.check` and `goals._test`; `planner._effect_achieves`
   becomes `conditions.achieves`.
3. **Action declarations.** `world/actions.py`, §5.1. Worth doing before
   rulebooks, because implicit taking and "power what?" pay for themselves on
   their own, and arity is what the rule index is keyed by.
4. **`world/rulebooks.py`: storage, index, gather, order.** Pure functions over
   data. Testable with no model: hand it a world and an attempt, get back an
   ordered list. §6's sort key is the part to get exactly right.
5. **The standard rules**, §8, written by hand. This is where the composition
   win shows up as deleted code: `prevents_acting`, the `holds` clauses, the
   reach checks.
6. **`attempt.py` runs the phases.** The old `verb_rules` path goes: there is
   one player and one tester, worlds are reset for this as they were for kinds,
   and a fresh world is a better test bed than a converted one. The old corpus
   is kept as test fixtures rather than as a migration target -- see
   development-plan.md §2.
7. **`rules` and `help <action>`.** Same sitting as step 6. Not later.
8. **The generation prompts**, §9. Last, when there is an engine to write into.
9. **Effect vocabulary, as the rulebooks demand it**, §11.1: `set_exit` and
   cross-room `move_object` first, then planner subgoals, then declared
   relations. Not one step and not a late one -- each entry is small, each must
   be invertible, and the order is set by what the first real world needs rather
   than by how common it is in a corpus. Light was on this list and has been
   taken off it: §8.1.
10. **Looking as an action**, §8.1. After step 8, and it needs nothing from
    step 9. The one sense no world can currently hold an opinion about, and the
    step that connects the `visible` access level declared in §5.1 to something
    that enforces it.
11. **The consistency scan**, §9.1. Orderable anywhere, including before step 1:
    it needs no corpus, no rulebooks and no model, and it already reports real
    faults in existing worlds. Do it early precisely because it is cheap --
    72% one-way states is a thing worth knowing before redesigning around them.
    Inverse rules and inherited checks follow it, once §5.4 and §5.1 exist.
12. **Attempt counters, then the suggestion queue**, §10.1. The counters come
    first and are worth having on their own -- the commonest refusal in a world
    is worth knowing whatever is done about it. The queue reuses suspension from
    §10, so it is mostly the generators and one command.
13. **`world/commonsense.py`**, §7.1. Deliberately last, and deliberately
    independent of everything above: it improves the quality of what gets
    generated and changes no capability, so nothing in steps 1-10 may come to
    depend on it. Within it, the free column of §7.1's table first -- state
    groups, body parts, verb kindred, anchor proposals -- because those cost
    nothing per call and can be judged by reading a log. The prompt priors
    after the replay measurement says whether they earn their tokens.

---

## 13. What this has that neither earlier design did

| | Verb rules (today) | Scoped rules (previous note) | Inform's way (this note) |
|---|---|---|---|
| A verb means different things | no | yes | yes |
| A rule can be about a place | no | yes | yes |
| Conditions can name the unnamed | no | via implicit binding | **via redirection, which is also how the planner reads it** |
| Arity is known | inferred from input | inferred from input | **declared once** |
| Holding something is a precondition | 54 hand-written clauses | the same clauses | **`access: carried`, and it picks it up** |
| A rule can be added later | no | yes | yes |
| A bad rule can be removed | no | delete | **unlist, reversibly, with the history kept** |
| Rules are printable | no | yes | yes, and **the order they fire in is printable** |
| Universal rules | 3 hard-coded flags | `verb: null` rules | **a Standard Rules set, written once by hand** |
