# Rulesets, and the counting we have been avoiding

A design note, written before the change it describes, and checked against the
code as it stood at `30de529`. It answers two questions from
`docs/future-plans.md` and one that follows from both:

* **Could our rules express everything Evennia's crafting contrib does?**
  Almost. Four things are missing, and three of them are the same thing.
* **Do we still need the clothing contrib, or can wearing be built out of
  rules?** We barely use it now, and the same four gaps are what stand between
  us and dropping it.
* **If both answers are "yes, once X exists", what is X, and how does a world
  choose which of these it wants?** X is quantity. The choosing is rulesets.

The short answer: **no new engine.** The condition language learns to count and
to match by sort, effects learn to name what a condition found, and the seeding
machinery `standard_rules.py` already has is generalised so that a bundle of
rules, kinds, verbs, traits and states can be declared as data and chosen at
world creation. Everything else is already here.

---

## 1. Crafting, feature by feature

`evennia/contrib/game_systems/crafting` is a recipe engine: a class per recipe,
inputs matched by tag, outputs spawned from prototypes, a `craft` command
reading `craft <recipe> from <consumables> with <tools>`.

| What the contrib does | What we have | Verdict |
|---|---|---|
| A named recipe, looked up by name | A rule scoped to a kind, gathered by `rulebooks.gather` | **Better.** A recipe is one rule among many, ordered by specificity, readable in `rules`, replaceable per room or per zone. |
| Consumables matched by `crafting_material` tag | `{"subject": "actor", "holds": [...]}` | **Gap.** `conditions._held` matches on a *substring of the object's key*. It cannot say "something of kind `iron.n.01`". |
| Two of the same consumable (`["coal", "coal"]`) | — | **Gap.** Nothing anywhere counts. |
| Consumables destroyed on success | `destroy_object` with `name_role` | **Gap.** It destroys one thing, named by a role somebody typed. The condition found the coal; the effect cannot refer to what the condition found. |
| Tools required, in inventory *or* room, not consumed | `instrument` role, `reachable_by`, `actions.ACCESS` | **Have it.** `{"role": "instrument", "access": "touchable"}` is exactly this, and better: `carried` makes the game pick the hammer up for you. |
| `exact_tools`, `exact_tool_order`, `consume_on_fail` | — | **Don't want it.** Flags on a Python class, answering questions a rule answers by existing or not. |
| Outputs spawned from prototypes | `create_object`, through `clothing.create` | **Have it.** |
| Per-failure error messages (`error_tool_missing_message`, ...) | `conditions.complaints` | **Better.** Ours are generated from the condition, in the right mood, and do not have to be written per recipe. |
| Skill checks (override `pre_craft`) | `{"trait": "smithing", "min": 4}`, plus `contest`/`outcome` | **Have it.** |
| `craft` with no matching recipe | `counters.NOT_ADMITTED` and the suggester | **Better.** A world that is asked for a thing it cannot make *remembers being asked*, which is how a recipe becomes the best-evidenced proposal in `suggest`. |

So: seven of eleven rows are already ours, two are ours and better, and the
remaining three are one hole with three edges.

### 1.1 The fourth gap, which is a parser one

The contrib's syntax names the *result* first: `craft spiked club from club,
nails`. Ours cannot. `verbs.PREPOSITION_ROLES` maps `from` to `source` and
`with` to `instrument` correctly, but `direct` would bind to "spiked club" —
and `verbs.bind` binds nouns to things that exist. A spiked club does not
exist yet; that is the point of making one. What the binder does with a noun
naming nothing is offer to conjure it, so `craft a spiked club` would build the
club and *then* run the rule that is supposed to build it.

The honest conclusion is not that we need a "topic" role. It is that **the
contrib's syntax is the wrong one for this game.** Ours should be
inputs-first — `combine the iron with the wood`, `forge a blade from the
ingot` — where every noun is a real thing and the result is what the rule
says it is. That is also exactly the shape the "endless alchemy" world in
`future-plans.md` asks for, and it is more generative: a world can have a rule
that knows what iron and wood make, or it can have a model decide, and neither
needs the player to know the recipe's name in advance.

A recipe-name syntax stays available to any world that wants one, as a rule
whose `direct` is unbound and whose name is a verb: `smelt`, `brew`, `bake`.

---

## 2. Clothing: what the contrib is actually still doing for us

`world/clothing.py` is 710 lines and almost all of it is ours. From the contrib
we import exactly seven names:

```
CLOTHING_OVERALL_LIMIT, CLOTHING_TYPE_LIMIT, CLOTHING_TYPE_ORDER,
WEARSTYLE_MAXLENGTH, ContribClothing, get_worn_clothes, single_type_count
```

Three constants, one typeclass, and two helpers of a dozen lines each. Against
that, `as_garment` performs a `swap_typeclass` on a live object the first time
anybody tries to wear it, because an item the generators called wearable is not
necessarily an instance of the contrib's class. We are carrying a typeclass
hierarchy in order to store one boolean.

What wearing actually needs, and whether we have it:

| What the contrib supplies | Built out of what we have | Verdict |
|---|---|---|
| `db.worn` flag | A state. `verbs.register_group("wornness", exclusive=True, default="")` | **Have it**, and it wins: a worn state is visible in `show_state`, testable by `{"is": "worn"}`, settable by `set_state`, and needs no typeclass at all. |
| `db.covered_by` | `relations.place(garment, covering, "under")` | **Nearly.** `under` is already a preposition and `_AWAY` already renders taking a thing out from under another. The friction is that `relations` uses real containment, so a covered garment would sit inside the covering one rather than in the wearer's contents — see 2.1. |
| `CLOTHING_TYPE_LIMIT` (one hat per head) | — | **Gap.** Counting again. |
| `CLOTHING_OVERALL_LIMIT` | — | **Gap.** Counting again. |
| `CLOTHING_TYPE_ORDER` (hat before shirt before shoes) | Kind ancestry, `kinds.ancestors` | **Have it**, if garment kinds are anchored. Ordering by taxonomy depth is at least as good as a hand-written list, and works for a world that invents a garment the list never heard of. |
| Wear styles ("tied at the waist") | A qualifier on the object, as `item_gen` already produces | **Have it.** |
| Appearance assembly | `clothing.appearance`, ours already | **Ours.** |
| Bonuses while worn | `gear.CONDITIONS` `worn` | **Ours.** |

So clothing needs exactly what crafting needs: **counting**, plus one decision
about covering.

### 2.1 Covering, decided

Two ways to say "the shirt is under the coat":

1. **Placement.** `relations.place(shirt, coat, "under")`. Costs: the shirt
   leaves the wearer's `contents` and enters the coat's, so `worn_by`,
   inventory, bulk and every `holds` clause see a different shape. Taking the
   coat off would carry the shirt with it, which is wrong.
2. **A state plus a role.** The shirt is `covered`; what covers it is a
   relation stored the way `gear` stores what a thing is worth.

Take (2) for the shirt-and-coat case and leave (1) alone. Covering is not
placement: both garments are on the same person, and containment is the wrong
model for two things occupying one body. The state is enough for everything
`clothing.py` does with `covered_by` today, and it composes: a rule can say
"you may not take off what is covered" once, at world scope, instead of that
refusal living inside `take_off`.

### 2.2 The recommendation

**Drop the contrib.** Not first, and not as its own piece of work: it falls out
of §3 and §5. `typeclasses/clothing.Garment` goes, `as_garment` and its
typeclass swap go, `is_garment` becomes "has the `wear` affordance", and the
three limit constants become rules a ruleset ships and a world can change.
`world/clothing.py` keeps the parts that are genuinely ours — appearance,
`item_name`, `create`, the event templates — and loses the mechanic.

---

## 3. What is actually missing: quantity

Three of the four gaps above are one sentence: **a rule cannot say how many of
what sort, and cannot tell an effect what it found.**

That is not a crafting problem or a clothing problem. It is missing from:

* crafting — "two iron ore and a coal"
* clothing — "no more than one hat"
* quests — "bring me three apples" is unsayable today; `quests.py` has no
  counting and `goals.py` has none either
* the planner — an NPC that wants three apples cannot plan for three
* trade and economy — the Taipan-shaped world in `future-plans.md` is made of
  quantities from end to end
* `bulk.py` — "get all but the blue ball", also in `future-plans.md`, is a
  quantified selection over the same vocabulary
* `gear.py` — "a thing that works from inside a pack lets somebody carry six
  of them", says its own comment, with nothing to stop them

Six systems growing the same subsystem is the case `basic-principles.md` says
to pull out and make generic.

### 3.1 The shape

Three additions to the condition language, which are one idea.

**Quantity.** `holds`, `in_room` and `wears` take a count:

```json
{"subject": "actor", "holds": {"of_kind": "coal.n.01", "count": 2}}
```

Rendered by `conditions.describe` as "be carrying two pieces of coal", in every
mood the renderer already has, so quests, goals, `rules` listings and refusals
all read correctly with no further work.

**Matching by sort.** `of_kind` inside a `holds` clause searches by
`kinds.is_a` rather than by substring of the key. This is the fix to
`conditions._held`, which today matches `"iron"` against `str(obj.key)` and so
counts an iron *key* as iron. `of_name` keeps the old behaviour for a rule that
really does mean a particular thing.

**Binding what was found.** A clause may file its matches under a name:

```json
{"subject": "actor", "holds": {"of_kind": "coal.n.01", "count": 2,
                               "as": "fuel"}}
```

and an effect may then name it:

```json
{"type": "destroy_object", "name_role": "fuel"}
```

`effects.PLURAL_ROLES` already exists for `everyone` and `others`, with a
deliberate note that destroying or moving everybody present is not something a
verb should say in one line. A *bound* plural role is the other case: it is not
"everybody here", it is "the two lumps of coal this rule just checked for", and
the rule that checked is the one destroying them. Extend `_resolve_many` to
bound sets, and let `destroy_object`, `move_object` and `set_state` take them.
Leave `create_object` and `move_actor` alone.

### 3.2 Where it goes

* `world/conditions.py` — `_held`, `_p_holds`, `_p_not_holds`, `_p_wears`,
  `_p_in_room`; `describe` for the new phrasings; `OPPOSITES` for the
  negations (a count flips to "fewer than", which needs a decision recorded in
  `UNNEGATABLE` if we decline it)
* `world/effects.py` — `_resolve_many` and the three effects named above
* `world/rule_gen.py` — the prompt block, so a model can write one
* `world/planner.py` — `achieves` reads a counted want backwards into "get one
  more"; this is the piece with the most room to go wrong and wants its own
  tests
* `world/bulk.py` — unchanged. Bulk stays an expansion into single attempts;
  it is a different question ("do this to everything") from a quantified
  requirement ("you need two of these"), and its docstring's three reasons
  still hold.

### 3.3 The guard rails

`conditions.MAX_DEPTH` and `MAX_MEMBERS` exist so a condition cannot become a
program. A count needs the same: a ceiling on `count` (the same order as
`bulk`'s ceiling), and a refusal to bind a set larger than it. A rule that
wants a hundred of something has stopped being a fact about the world.

---

## 4. So: rulesets

Now the second half. Once crafting is a bundle of rules, and clothing is a
bundle of rules, and death is a bundle of rules, the question is which bundles
a world gets — and the answer today is "all of them, always, hardcoded".

Some of this is already wrong in ways we can point at:

* `verbs.STATE_GROUPS` seeds `life_status` with `dead`, `prevents_acting` and a
  default of `alive` into **every** world. A world about a dinner party has it.
* `clothing.VERBS` intercepts `wear`, `remove`, `cover` and `uncover` before
  any rule is consulted, in every world, whether or not that world has clothes.
* `gear.VERBS` does the same for `wield` and `hold`.
* `standard_rules.STANDARD` ships one rule suspended — "you may not take what
  is not yours" — with a comment saying a heist and a monastery answer it
  differently. That comment is a ruleset asking to exist.

### 4.1 What a ruleset is

**A ruleset is data, not code.** `basic-principles.md` is explicit: no player,
character, model or rule writes Python, and Python arrives only by a server
administrator putting a file on the machine. A ruleset is lighter than a plugin
and must not be a way around that rule, so it is a validated document with no
executable part. Anything a ruleset can express, a world could have written for
itself with `create rule`.

A ruleset is a JSON document with seven sections, every one optional, matching
the seven stores a world already keeps:

| Section | Goes to | Store |
|---|---|---|
| `actions` | `actions.declare` | `db.action_specs` |
| `verbs` | `verbs.VERB_SYNONYMS`, per world | `db.verb_synonyms` (new) |
| `kinds` | `kinds.remember` | `db.kind_specs` |
| `affordances` | `affordances.normalise`, and the generator prompts | — |
| `attributes` | `traits.register` | the traits contrib's store |
| `conditions` | `verbs.register_group` | `db.state_groups` |
| `rules` | `rulebooks.add` | `db.rules` |

Plus a header:

```json
{
  "name": "crafting",
  "title": "Crafting",
  "version": 1,
  "means": "Things can be made out of other things.",
  "requires": [],
  "conflicts": [],
  "default": false
}
```

`means` is one sentence, shown in the menu and by `view rulesets`. It is the
same discipline as `effects.VOCABULARY` and `actions.prompt_block`: the
sentence and the thing it describes live in one file so they can only drift
together.

### 4.2 Where they live

* **Built in:** `aimud/world/rulesets/*.json`, shipped with the game.
* **Local:** every directory in a new `RULESET_DIRS` setting, defaulting to
  `server/conf/rulesets/`. Nothing scans it but the loader, and putting a file
  there requires access to the machine — which is the bar `basic-principles.md`
  sets for extending the game.

A local ruleset whose `name` collides with a built-in one **replaces** it, and
says so in `view rulesets`. That is how a server runs its own idea of death
without patching the game.

### 4.3 Validation, and what a bad ruleset costs

Loaded once at server start, validated hard, and a ruleset that fails
validation is logged and skipped rather than half-applied. The validator is the
existing one in each case — `rulebooks.add` already cleans a scope,
`actions.clean_roles` already cleans roles, `conditions.normalise` already
refuses a condition that is too deep — so this is mostly a matter of running
them at load time instead of at write time, and refusing the document rather
than quietly repairing it.

The one new check: a rule in a ruleset may not name a kind, trait, state or
action that neither the same ruleset nor its `requires` declares. A ruleset
whose rules never gather is the worst failure there is, because it fails by
doing nothing — which is precisely the argument `standard_rules.LOOK` makes
for naming a constant rather than spelling it out.

### 4.4 Choosing them

**At creation.** A `Submenu` in `WIZARD` (`commands/world_subject.py`), listing
every ruleset with its `means`, the default ones pre-selected. This is a form
like any other, so it gets the screen-reader layout, `?` help and a text
fallback for free, and every point in it is reachable by typing — `create world
... rulesets crafting, clothing`.

**Stored in the spec.** `lore.store` gains `rulesets`, `lore.spec_of` returns
it. That is the whole of what makes it survive `reset world`: a reset rebuilds
from `spec_of`, so the rulesets come back and come back at their defaults,
which is what was asked for.

**Changeable after.** `edit world` shows the same menu. Adding a ruleset to a
live world seeds it. Removing one **unlists** its rules rather than deleting
them, for the reason `standard_rules._decisions` exists: a world may have built
on top of what it is now removing, and a rule that vanishes takes a player's
work with it. `view rulesets` shows what is on, what is off, and what a world
has changed.

**A new subject, not a new command.** `rulesets` joins `SUBJECT_MODULES` with
`create`/`edit`/`view` uses, per the rule in `CLAUDE.md`.

### 4.5 Versioning

`standard_rules.py` has already solved this and the solution generalises
unchanged. Each ruleset carries a `version`; a world records which version of
each it holds; `_retire` drops what the old edition seeded, matched on
`source`, and reseeds. Today's mark `source: "standard"` becomes
`source: "ruleset:default"`, and `is_standard` becomes
`from_ruleset(rule, name)`.

`_decisions` carries across untouched, and matters more than before: it is what
lets a world suspend a ruleset's rule and keep that decision through the next
edition. That is the mechanism by which "you may not take what is not yours"
ships suspended in one ruleset and restored in another.

---

## 5. The four we bundle, and the fifth we do not

### 5.1 `default`

Everything `standard_rules.seed` does now, moved to data, plus what is
currently seeded from elsewhere and belongs here: `clock.seed_periods`, the
non-death entries of `verbs.STATE_GROUPS` (`posture`, `wetness`, `fire`,
`bonds`, `gagged`) and `traits.BUILTIN`.

Marked `"default": true`. A world that takes the defaults and nothing else
behaves exactly as a world does today, which is the acceptance test for this
whole section.

**New machinery needed:** none. This is a move.

### 5.2 `crafting`

*Requires:* `default`.

* **actions** — `combine` (`direct` and `instrument`, both `carried`),
  `make` (`direct` optional, `source` carried), each with a `means`.
* **verbs** — `craft`, `forge`, `brew`, `assemble`, `build` folding onto
  `make`; `mix`, `join` onto `combine`.
* **affordances** — `combine`, so the generators can say a thing is a material.
  `affordances.to_verb` already folds `combinable` onto it.
* **rules** — a check rule "you must have what it is made from"; an after rule
  "making something uses up what it was made from"; a world-scope instead rule
  that hands an unrecognised combination to the model, which is where "endless
  alchemy" gets its behaviour for free.

Recipes themselves are **not** in the ruleset. A recipe is a rule scoped to a
kind, written by a world or proposed by `suggest` from what players kept trying.
The ruleset ships the frame; the world ships the content. That is the
difference between this and the contrib, and it is the whole argument.

**New machinery needed:** §3, all of it.

### 5.3 `clothing`

*Requires:* `default`.

* **actions** — `wear`, `remove`, `cover`, `uncover`, with the roles
  `clothing.handle` currently reads off `bound` by hand.
* **affordances** — `wear`, as now.
* **kinds** — the garment kinds, anchored, replacing `GARMENT_TYPES`.
* **conditions** — a `wornness` group (`worn`, exclusive) and a `covering`
  group (`covered`).
* **rules** — wearing sets `worn`; removing clears it; "you must be holding it
  to put it on"; "you may not take off what is covered"; "you may wear only one
  hat" and "you may not wear more than N things", both counted.

`world/clothing.py` keeps `appearance`, `describe_outfit`, `item_name`,
`create` and the event templates, and loses `put_on`, `take_off`, `cover_with`,
`uncover`, `handle`, `as_garment`, `is_garment` and `typeclass_for`.
`typeclasses/clothing.py` goes. The contrib import goes.

**New machinery needed:** §3's counting; §2.1's decision; and a way for a
ruleset to *remove* a mechanic interception, since `attempt.py` line 327 calls
`clothing.handle` unconditionally. See §6.

### 5.4 `death`

*Requires:* `default`.

* **attributes** — `health`, a gauge.
* **conditions** — the `life_status` group, moved out of `verbs.STATE_GROUPS`,
  with `prevents_acting`, `prevents_moving`, `prevents_speaking` and a default
  of `alive`; and `verbs.DEFAULT_STATE_GROUP`'s death slugs with it.
* **actions** — `revive`, `wake`, `heal`, declared `despite: ["acting"]`, which
  is the case `actions.GATES` was built for and currently has no shipped user.
* **rules** — a `becomes` rule, "when a person's health becomes at most 0 they
  are dead", which is the example `becoming.py`'s own docstring opens with and
  which no world is actually given; and an after rule on reviving that puts
  health back above nought so the becoming rule does not immediately undo it.

This one is nearly free, and it is the clearest evidence that rulesets are the
right shape: the engine already has everything, three separate modules already
name death in their comments, and no world has ever been given the rule.

**New machinery needed:** none beyond the loader.

### 5.5 `permadeath` — not building this

*Requires:* `death`. *Conflicts:* nothing yet; a future `respawn` ruleset would.

**Decided against, for now.** What follows is the scoping that led there, kept
because the reasons are the interesting part and because a world that wants
permadeath will want them answered eventually.

* **rules** — a `becomes` rule on `dead` that ends the character and starts a
  new one.

And here is an honest gap. `effects._protected` refuses to destroy a
`DefaultCharacter`, deliberately, and there is no effect that ends a character
or makes a new one. Permadeath needs one, and it is not a small addition: a
character is puppeted by an account, holds quests, owns things, and is
remembered by `world/memory.py`. What happens to a dead player's sword, their
half-finished quest, and what an NPC remembers of them are three separate
decisions, and this document does not settle them.

There is a second reason to leave it, and it is the stronger one: **what
permadeath means differs per world.** One world ends the character and hands
the player a new one with nothing. One keeps the name and the memories and
takes the levels. One lets the corpse be looted by whoever finds it. These are
not settings on a shared mechanic, they are four different games, and a bundled
ruleset would have to pick one and be wrong for the other three.

So the right shape is probably not a ruleset at all. It is the `death` ruleset
plus whatever `becomes` rules a world writes on top of `dead` — which is what
rulesets are *for*, and which needs only an effect that can end a character.
When somebody wants it, that effect is the piece to build, and the three
questions above are theirs to answer rather than ours.

**Not in scope.** The other four are worth more than all five together.

---

## 6. The mechanic problem

Four modules take verbs before any rule is consulted
(`attempt.py:327-330`): `clothing`, `gear`, `ownership`, `relations`. Each has a
good reason — the game already knows what "put the key in the box" means, and
buying a model call to find out would be absurd — and each is a decision made
for every world at once.

Two of them should stay hardcoded. `relations` and `ownership` answer questions
about where things are and whose they are, and those are true of every world
there could be.

The other two should become rulesets, which means the interception has to
become conditional. The cheapest honest version:

```python
for mechanic in mechanics.enabled(world_root):
    if mechanic.handle(caller, verb, parsed, bound, on_message):
        return
```

where `mechanics.enabled` reads the world's rulesets. A ruleset may name a
mechanic module it switches on; only modules shipped with the game may be
named, and the name is matched against a fixed table — so this stays a switch
over game code rather than a way for a data file to reach Python.

That table is the seam between "ruleset as data" and "plugin as code", and it
is worth being strict about now: a ruleset names a mechanic, it never supplies
one. When the affordance-plugin work in `future-plans.md` happens, plugins
register into that same table, and a ruleset that names a plugin's mechanic
simply fails validation on a server where the plugin is not installed — which
is the right failure, at load time, in the log.

---

## 7. Build order

Each step leaves the game working and is worth having alone.

1. **Counting in conditions.** `of_kind` and `count` on `holds`, `wears`,
   `in_room`. Fixes `_held`'s substring bug on its own. Tests only.
2. **Bound sets.** `as` on a quantified clause; `destroy_object`,
   `move_object`, `set_state` accept a bound plural role. Tests only.
3. **The generator prompt and the planner.** `rule_gen` can write one, `suggest`
   can render one, `planner.achieves` can read one backwards. This is where the
   risk is; it wants a soak, not only unit tests.
4. **The loader.** `world/rulesets.py`: read, validate, seed, retire, version.
   Generalised from `standard_rules.py`, which becomes the `default` ruleset
   and a thin shim.
5. **`default`, `death`.** The two that need no new mechanics. `death` is the
   proof the loader works, because it exercises attributes, conditions, actions
   and a `becomes` rule, and a world without it must behave as before.
6. **The menu and the subject.** `rulesets` in `SUBJECT_MODULES`; the wizard
   submenu; `lore.store`/`spec_of`; reset keeps them.
7. **Conditional mechanics.** §6's table.
8. **`clothing`.** Drop the contrib, drop `typeclasses/clothing.py`, move the
   limits into rules.
9. **`crafting`.** The frame, plus a hand-written recipe or two in a test world
   to prove a world can write its own.

Nine steps, and that is the whole of it. Steps 1–3 are worth doing even if
rulesets are never built: they close a hole six systems are working around.
Steps 4–6 are worth doing even if clothing and crafting never move, because
`death` alone justifies them.

Permadeath was a tenth and is not being built — see §5.5.

---

## 8. What this deliberately does not do

* **No recipe classes, no prototypes, no tag categories.** The contrib's
  vocabulary does not enter the game. A recipe is a rule.
* **No plural roles a player can type.** "Get the blue ball and the yellow
  ball" is the grammar work in `future-plans.md` and stays there. A bound set
  is something a *rule* found, never something a player named.
* **No ruleset that supplies code.** §4.1 and §6.
* **No ordering between rulesets.** Rules are already ordered by specificity,
  and a second ordering — by which ruleset a rule came from — would be a
  second answer to a question `rulebooks.rank` already answers. If two
  rulesets genuinely cannot coexist they say so in `conflicts`.
* **No per-ruleset storage.** Rules go in `db.rules` with the rest, marked by
  `source`, for the reason `rulebooks.py` gives for one store rather than five.
* **No count in `bulk`.** §3.2.

---

## 9. What was actually built, and where it differs

Written after the fact, against `3f99cfb` and what follows it. Steps 1–9 are
done; step 10 was a soak, and permadeath was declined in §5.5 before any of it
started. Everything below is a place where building it taught us something the
plan had wrong.

### The counting work found three bugs the plan did not predict

All three fail by doing nothing, which is why none of them had been noticed.

* **`conditions.as_goal` put a clause's value through `str()`.** A check rule
  refusing for want of two lumps of coal handed the planner a goal for an
  object called `"{'of_kind': 'coal.n.01', 'count': 2}"`. It would never find
  one, blame the rule for not delivering, and after `FAILURES_ALLOWED` tries
  stop planning with that rule at all.
* **`conditions.from_goal` put a goal's *kind* into `holds` as a name**, where
  it was matched as a substring of what things are called. `"cake.n.01"`
  appears in nothing anybody calls a cake, so a goal for *a* cake could never
  be met by any cake. This predates counting entirely; nobody saw it because a
  quest that names the cake works, and that is what quests mostly do.
* **`model_json.listed` tested for a mapping by type.** An Evennia attribute
  hands a stored mapping back as a `_SaverDict`, which is not a `dict`, so a
  spec read from the database fell through to the sequence case and came apart
  into its keys — the same failure that function exists to stop, one level up.
  It could not happen while every listed value was a word.

The trap §7 predicted — a counted goal looping — was real and worse than
predicted: `goals._world_objects` looks in the actor's own hands first, so
somebody wanting three apples and holding one was handed back the apple they
were already holding, found no step that would get it, and gave the want up.
`find_of_kind` takes a `skip` now. `tests/test_counted_goals.py` was checked
by reverting the fix and watching it fail, rather than assumed.

### `in_room` does not take a count, and `MAX_COUNT` is not `bulk.LIMIT`

§3.2 listed `in_room` among the predicates to give counting. It is about the
*room's title*, not its contents, so there is nothing to count; `holds`,
`not_holds`, `wears` and `not_wears` are the four.

§3.3 said the ceiling should be `bulk`'s. That borrowed `bulk.LIMIT`'s number
*and* its argument, and the argument does not transfer: `bulk`'s twelve is
about how many model calls `eat all` may cost in a storeroom, while counting
runs against a pool already in hand. It refused to store "no more than twenty
things at once", which is an ordinary rule. Fifty now, as a guard against
nonsense rather than a claim about play.

### A becomes rule's trigger is its `when`

`world.becoming` reads `when` and nothing else. The death ruleset's first
draft used `conditions`, was filed, was gathered, and never fired. The
validator refuses that now — the symptom is a rule that works in the wrong way
rather than not at all, which is the hardest sort to see.

### `life_status` stays in `verbs.STATE_GROUPS`

§5.4 said the death ruleset should own it. It does not. An unused state group
is inert and costs nothing; removing it from the seeds would mean a world that
invents `dead` *without* the ruleset gets a state that looks like death and
stops nobody acting. The genuinely optional part of death is the health
figure, the rule joining it to dying, and the way back — and that is what the
ruleset holds. `death.json` declares the group as well, so the dependency is
written down; registering it again is a fold and a no-op.

### `worn` and `covered` are states

Done, after an argument worth recording because the first attempt got the
reasoning wrong.

The case for leaving `db.worn` alone was that the conversion buys visibility
and settability and costs eighteen call sites plus a migration, while `wears`
and `not_wears` read the attribute directly — so the counted wardrobe limits
work either way. That weighed the wrong thing. **`db.worn` was storage no other
ruleset could have had.** Nothing could write a rule against it, `condition`
did not print it, `set_state` could not reach it, and a ruleset wanting its own
idea of being dressed had no way in. Every other fact about a thing in this
game is a state — lit, open, burning, dead — and clothes had a private slot.
That is a reason on its own, and it does not depend on any particular use for
it.

So `worn` and `covered` are states, registered by `clothing.json` like any
ruleset's vocabulary, which means a world without clothing has neither word.
`clothing.is_worn` / `is_covered` are the readers, and the eighteen call sites
now go through them.

Three things fell out of it:

* **"You cannot take off what is covered" is a rule**, not a line inside
  `take_off`, because `covered` is now testable. A world where a cloak slips
  off over everything suspends it.
* **The wear style is not a state** -- "tied loosely around her waist" is text
  about one garment, not a condition anything could test, and a register
  filling up with a phrase per scarf would have lost what the register is for.
  It became its own general thing instead; see §10. `db.covered_by` stays a
  pointer, because `covered` is the fact and *which garment* is the detail,
  and both are written in `_cover` and `_uncover` and nowhere else.
* **A ruleset's `conditions` section gained `states`.** `apply_states`
  registers a slug it has never seen, which is the right default and the wrong
  thing to rely on here: with nobody having said which group `worn` belongs to,
  `register_state` folds it onto whatever looks similar and may hand back a
  different word. A ruleset that means one particular word says so when it is
  seeded.

`examine coat` now reads "It is worn", as it reads "It is lit" for a lamp. That
is the treatment every other state gets and it was not there before.

### Clothing and wielding ship switched **on**

§5.3 and §6 read as though clothing becomes opt-in. It is opt-*out*:
`clothing.json` and `wielding.json` are `default: true`. On is the status quo —
a world made before rulesets existed had them, and `reset world` must not take
them away. What rulesets buy here is the ability to say no, not a change of
default.

### Two things `seed` needed that the plan did not mention

* A world's `rules suspend` decisions are carried across an **edition** and not
  across a fresh install. Without that, putting back a ruleset that had been
  taken away brought it back switched off, because `forget` unlists everything
  it seeded and `_decisions` read that as a decision.
* Validation runs in two passes. A document is checked for naming things
  nothing declares, and what a ruleset's `requires` declares lives in another
  document — so the cross-document half cannot run until every document is
  parsed. Written as one pass, it recursed until the stack gave out.

### The limits are a pre-check, so "only one hat" is a count of **one**

A check rule runs before the thing it guards. "You may wear only one hat" is
`not_wears` with a count of 1 — *be wearing fewer than one before putting one
on*. Written with 2, as the obvious reading suggests, it lets the second hat
through and refuses the third. Worth knowing for every limit written this way.

### §1.1 was right, and the test walked into it anyway

The plan argued that `craft <recipe> from <stuff>` is the wrong syntax here,
because `verbs.bind` binds nouns to things that exist and the thing being made
does not. The first draft of `tests/test_crafting.py` typed `forge a blade` and
every recipe test reached for a model to invent a blade. `forge`, naming the
result not at all and reading what is in hand, is the idiom — and it is the one
the endless-alchemy world in `future-plans.md` wants.

### What the rulesets actually ship

| | rules | what else |
|---|---|---|
| `default` | 8 | 5 action declarations |
| `clothing` | 4 limits | the `clothing` mechanic, `wear`/`remove` |
| `wielding` | — | the `wielding` mechanic |
| `death` | 4 | `health`, `life_status`, `revive`/`heal`, 3 synonyms |
| `crafting` | 2 | `combine`/`make`, 7 synonyms, the `combine` affordance |

`crafting` ships **no recipes**, which is the whole argument against copying
the contrib: a recipe is a fact about one world, and belongs with that world's
other rules where it can be read, replaced, scoped to a room, and proposed by
`suggest` from what players kept trying. It ships no rules at all, for a
reason the soak found; see §12.

---

## 10. Styles: how a thing is in the state it is in

The wear style was the last piece of storage clothes had that no other ruleset
could have had, and generalising it turned out to be the same argument as
`worn` one level down.

**A state is a word from a closed vocabulary**, and that is what makes it worth
having: it can be grouped, made exclusive, tested by a condition, answered to
as an alias, and counted. What it cannot be is *particular*. A coat is `worn`
the way every coat is worn, and "slung over one arm" has nowhere to go. A sword
held point-down, a lantern raised high, a fire burning low and a body lying
where it fell all want the same thing, and none of them could have it.

So **a state may carry a phrase saying how**. One per state per thing, open
text, in `verbs.styles`. `world.clothing` reads its wear style out of it and
`world.gear` is the second user rather than a hypothetical one.

Three rules keep it from becoming a second vocabulary nobody can test:

* **It rides on a state and dies with it.** `apply_states` drops the style of
  anything it removes — including what an exclusive group removes on its own —
  so there is no way to be "slung over one arm" while not being worn. That is
  why it is keyed by slug rather than being a free attribute, and it is the
  whole of what keeps the two from drifting.
* **It may not name a state.** The line `name_contradicts_states` already
  draws, for the same reason: a phrase saying "burning" has said something no
  rule can read and nothing can undo. `style_complaints` refuses it, and a
  refused style leaves the plain state behind — less said, never something
  false said.
* **Nothing tests it.** There is deliberately no `style` predicate. A substring
  match against open text is the bug `world.quantity` exists to have fixed, and
  re-inventing it here would be worse for being on purpose. **If it matters,
  it is a state; if it only has to read well, it is a style.**

It stays inside `basic-principles.md`'s rule against decorative text, and not
by a technicality: a style is written into the events `world.memory` records,
it is part of what a character reads of themselves in `own_appearance` and so
is something they can act on, and it hangs off a state every system reads.

A rule can set one — `set_state` takes `styles: {slug: how}` — which is what
makes this a ruleset's to use rather than a mechanic's private convenience.

### And `db.wielded` went the same way

Converting it was not scope creep but the proof: `world.gear` had exactly the
private slot `world.clothing` had, for exactly as long, and a generalisation
with one user is a rename. `wielded` is a state registered by `wielding.json`,
and `gear.wield` takes a style.

That leaves the four mechanics with no bespoke storage between them except
`db.covered_by`, which is a pointer to an object rather than a fact about one —
a different kind of thing, and the one shape a state cannot hold.

---

## 11. Under is not inside

`db.covered_by` survived §10 because a state cannot point at an object. The
question that finished it was somebody else's: *if I put the table on the rug,
the rug is now under the table — and the rug cannot be on the table while the
table is on the rug.*

Both halves turned out to be about something larger. `world.relations` stored
**every** preposition as containment — `obj.move_to(host)` — and that is right
for two of the four and plainly wrong for the other two:

```
put coin under rug   ->  coin.location is rug
take rug             ->  the coin goes into your inventory, inside the rug
                         the floor has neither
```

A coin under a rug is not in the rug. Neither is a key behind a painting in
the painting. `in` and `on` earn containment — a thing in a box or on a tray
travels with it, is hidden when the box is shut, and needs no bookkeeping
because Evennia's containment does all of it — but `under` and `behind` say
where a thing is in a room rather than what holds it.

So `relations.BESIDE` is a pointer: both things stay where they are, one
pointing at the other. Three things follow.

**Covering is placement.** "The shirt is under the coat" is the same word, said
of two things that share a wearer rather than a floor. That was impossible
while `under` meant containment — §2.1 was right that the shirt must not sit
inside the coat, and wrong to conclude that covering therefore was not
placement. `db.covered_by` and the `covered` state are both gone; `relations`
keeps the one fact, and "you cannot take off what is covered" is
`{"not_placed": {"under": true}}` — which needed `placed` to learn a wildcard
host, since the rule is about being under *something* and naming the garment
would make it a rule about that garment.

**Cleanup is a lapse, not a hook.** A thing is under another because they are
in the same place, so `host_of` answers None the moment they part — burn the
rug, pocket it, shut it in a chest, and the coin is a coin on the floor again.
No door needs unpicking because there is no door this misses. Nothing is
narrated: what to say when a coin comes to light is a rule's business.

**The other side can be spoken.** Only the guest ever carried the word, so
`relation_of(rug)` said the rug was nowhere in particular while a table stood
on it. `INVERSE` and `relations.standing` give it the sentence.

The cycle was already refused, by `_holds` — but in the only words it had:
"that would have to go inside itself", which names containment to somebody who
said "on". It now says which way round things already are.

One consequence worth watching in play: a coin under a rug is in the room's
own contents now, so it would read twice — loosely among what you see, and
again under the rug. `Room.filter_visible` drops what another thing already
accounts for. That hook rather than the listing, because "is this one of the
things shown" is exactly what it answers, and everything that lists a room
asks it.

---

## 12. What the soak found: a frame that outranked its world

The first hour of play in a space-crash world, verbatim:

```
> combine strut with shield tile
You cannot combine a titanium strut. You can salvage and wield it.
```

The world had written its own recipes — *combining a strut and a heat shield
tile makes an improvised shovel* — and the crafting ruleset refused them.

`crafting.json` shipped two check rules requiring both things to afford
`combine`. Three things were wrong, in increasing order of importance.

**Nothing ever puts `combine` in an affordance map.** Affordances are written
per object by the generators, which were never told the word existed. The
world's struts afford `salvage` and `wield`, because that is what a strut is
for.

**The `affordances` section was dead config.** `crafting.json` said
`"affordances": ["combine"]` and `clothing.json` said `["wear"]`, and `_apply`
read neither — the section was in `SECTIONS` and handled nowhere. It had been
doing nothing since the day it was written. `SECTIONS` is now exactly what is
read, and a document naming anything else is refused at load: *a section nobody
reads is a promise nobody keeps.*

**And the real one: a world-scope check rule cannot be overruled.** Check rules
accumulate — that is what makes the phase safe to extend — so a specific
carry-out rule can never get past a general check. The frame's guess about what
is combinable therefore outranked the world's own knowledge of what combining
*does*, permanently. That is exactly backwards: the frame is the thing that
should yield.

Worse, the question it asked was the wrong one. "Did some generator happen to
write this word down?" is not "does combining this make sense", and the engine
already asks the second: `kinds.admits` settles it once per kind per verb,
model-answered and cached, and runs in the pipeline already. The check rules
duplicated an existing gate, badly.

So `crafting` ships **no rules**. Actions, verbs, and nothing else.

The lesson generalises past crafting, and is worth stating for every ruleset
written from here: **a ruleset's check rules are a tax on every world that
takes it.** Ship one only where it is true of every world that could ever want
the ruleset — "you must be able to reach what you act on" clears that bar, and
"you can only combine things that go together" plainly does not. Where the
engine already has a gate, use the gate.

`tests/test_crafting.TheSoakWorldsStrut` keeps the case as it was typed, and
was checked by putting the bad rules back and watching it reproduce the
sentence above.

---

## 13. Changing a ruleset in a world that already exists

The soak's second finding: untick a ruleset in `edit world`, save, reopen the
menu, and it is ticked again.

**`seed` only ever adds**, which is right for it — it is what a world calls on
its way past to be sure its rules are there, and must never take anything away
by being asked twice. Saying which set a world should *hold* is a different
act, and it was being done in two places that each did half of it:
`edit rulesets` forgot what was dropped, and the wizard's save did not. So
`lore.store` handed `seed` the shortened list and nothing happened at all.
`rulesets.apply_choice` is that act, once, and both doors call it.

It also keeps whatever the surviving rulesets require, named or not: unticking
the thing a ruleset you are keeping rests on is not something anybody can mean.

### What a live change can and cannot do

Worth writing down, because the answer decided the prompt. Measured, not
assumed:

| | on switching a ruleset off |
|---|---|
| its rules | stop at once, and come back if it is switched on again — `forget` suspends rather than deletes |
| its mechanic | switches off at once |
| verb synonyms | **stay**: `resurrect` still folds onto `revive` |
| declared actions | **stay**: `revive` is still declared |
| registered figures | **stay**: `health` is still a trait this world keeps |
| what it already built | **stays**: a coat somebody is wearing is still worn, and with clothing off, taking it off is a word the world must work out afresh |

Switching one *on* has a quieter version of the same: `actions.declare` is
first-answer-wins, so an action the world had already settled for itself keeps
the arity it settled on and the ruleset's declaration loses.

So the honest answer to "can a ruleset be changed without a reset" is **yes,
and it leaves residue** — not "no". A `change_ruleset` confirmation says which
half is clean and which is not, and names `reset world` as the way to make the
change total. It does not *force* a reset, because none of the residue stops
the change working, and regenerating a world is expensive enough that it should
be something somebody chooses rather than something a checkbox does to them.

A world still being made is never asked: it has no history to lose.

---

## 14. A verb that worked once and said it had worked twice

The soak's sharpest find, and the oldest bug this work turned up — it is on
`master` and predates the branch by a long way.

```
> forage
You forage about and turn up a scrap of twisted metal.
> forage
You forage about and turn up a scrap of twisted metal.
> inventory
a scrap of twisted metal
```

A narration is cached against the things it was written about, so a world does
not pay a model to describe the same act on the same thing for ever. That is
right and worth keeping. What was wrong is that the cache answered the **whole
attempt**: `_with_rule` returned the stored sentence before reaching `_finish`,
which is where effects land, after rules run, memory is written and quests are
reviewed. So the second time anybody did anything, nothing happened and they
were told it had.

There was already a second, correct cached path a few lines below `_finish` —
stored words, effects still applied. It was simply unreachable for the
commonest case, because the early return got there first.

**Why it survived this long.** Most verbs worth doing twice are refused the
second time for a reason of their own: the lamp is already lit, the door is
already open, the note is already read. The precondition fires first and the
cache is never reached. Seeing the bug needs a verb with *no* precondition and
a real effect — forage, dig, search, combine — which is to say it needs
crafting, which is what the soak was for.

It also explains the shape of the report better than the report did. "It says
it did" is the symptom of a replayed narration; so is a `combine` that appears
to work and leaves the world unchanged.

`repeatable` on a rule was an earlier attempt at the same problem, from the
other end: mark a rule as worth running twice and skip the cache for it.
Nothing ever set it, and it is moot now — effects always run, so there is
nothing for the flag to protect.

---

## 15. Making somewhere new

The soak's feature gap, and the last of the effect vocabulary's obvious holes.
A rule could make a thing, move a thing, destroy a thing and change where a
way out led, and could not make anywhere to *go*. A player who digs into a
bank, mines a shaft, or walls himself a shelter out of struts and heat-shield
tile is plainly making a room, and nothing could say so.

**`create_room` opens a way and generates nothing.** The way is left *pending*,
and the room behind it is built by the ordinary generator the first time
anybody walks through — the same machinery every world grows by, at the same
cost, at the same moment.

That is not a shortcut, it is the rule the effect vocabulary already lives by.
Effects run synchronously and must stay free: `create_object` builds from a
spec the rule already holds precisely so that firing costs nothing, and a room
that phoned a model mid-rule would make every dig cost money whether or not
anybody went and looked at the hole.

It needed no new generation path at all. A pending exit with a
`destination_hint` is exactly "somewhere that does not exist yet, and what it
should be when it does", and the game has had it since worlds first grew.

```json
{"type": "create_room", "direction": "down", "exit": "burrow",
 "why": "dug out of the packed earth with a shovel"}
```

`why` becomes the hint, which is the field `generate_connected_room` already
reads to keep a door's promise and the room behind it consistent. "Walled with
strut and heat-shield tile" and "dug out of the packed earth" are what a world
writes here, and the generator writes the place they describe.

Two decisions worth recording:

* **A named direction that is not free does nothing.** Digging down when down
  is already a staircase should fail rather than quietly dig sideways: a rule
  about a shaft means the shaft. With no direction named, any free one will do.
* **It is not readable backwards**, and that is a decision rather than a gap.
  A goal names a room, and the room this opens onto has no name until somebody
  walks into it and the generator writes one — so there is nothing for a
  planner to aim at. A character who wants to be somewhere new walks through
  the way, which is `move_actor` and already read.
