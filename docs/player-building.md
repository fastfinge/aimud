# Development plan: building by hand

Status: built, phases 1 to 6. Phase 7 (export and import) is still a plan of
its own. What each phase actually came to, and where it differs, is under
each phase in §15.

This covers the `future-plans.md` item "full menu-based building of worlds for
players who want to create something fun without having to use AI", and the two
items about terms ("view term command", "create term commands"), which turn out
to be the same work seen from the reading end (§11).

Today `create` and `edit` reach a world, a start room, word lists, pronoun sets
and a generated NPC, and nothing else. Everything a world is actually made of
-- its kinds, its actions, its states, its traits, its rules, its rooms, its
items, its people -- can only be written by a model. That is a hole in the open
sandbox: the game can be read all the way down and written only at the top.

Three things follow from closing it, and they are why this comes before several
other items in `future-plans.md` rather than after them:

* **Hand-built worlds make every later feature testable for free.** Testing a
  weather ruleset, a quest chain, or the endless-alchemy world currently means
  paying a model to build something to test against, and getting something
  slightly different each time. A world somebody typed is a fixture.
* **"Let players configure what models do" has nothing to configure until
  there is a way to do it by hand.** A switch saying "the model may not invent
  verbs here" is only usable in a world whose verbs somebody wrote.
* **Export, import, and an MCP server are all the same surface seen from
  outside.** Once every creatable thing has one writer and one description, a
  document and a tool call are two more readers of it (§3.2).

---

## 1. The change, on one page

* **One table of makers** (`world/making.py`). One entry per thing a person can
  create: what it is called, how to list what a world already has, the form
  that makes a new one, the form that edits one, and how to remove one. Nothing
  in it is new machinery -- every entry points at the writer the generators
  already call (§3).
* **Two additions to the menu engine.** A `Picker` field, which offers what the
  world already has and "none of these -- make one" at the bottom; and a way
  for a submenu to answer its parent with a value, which is what makes that
  bottom entry work (§4). These are the only changes to `world/menus.py`.
* **Subjects generated from the table**, so `create kind`, `edit rule`,
  `delete attribute` and the rest arrive without forty-four hand-written `Use`
  objects, and each still answers on the command line and in the verb's menu
  exactly as `create tokens` does now (§3.2).
* **Things in the world are found the way the parser finds them** -- what is in
  this room, in your hands, or the room you are standing in. Never a search of
  the whole world by name (§5).
* **Quest specifications**, a new store, because a quest today exists only at
  the moment an NPC offers one and a world with no model has no NPC to offer
  it. Once errands are a register, the generator can be handed the pool and
  reuse one rather than writing a thirteenth (§10).
* **No model is called anywhere in this system.** `~` stays available and stays
  optional; a world with no API key builds exactly as well (§12).

---

## 2. What is already there

The good news is how little of this is new. Every register already has a
writer that folds near-duplicates, a reader for its vocabulary, and in most
cases a machine-readable declaration of its own shape, because the generators
needed all three first.

| Thing | Stored by | Written through | Vocabulary | Declares its shape |
|---|---|---|---|---|
| kind + affordances | `kind_specs` | `kinds.remember` | `kinds.vocabulary` | `kinds.ANCHOR_RULE`, `affordances.PROMPT` |
| attribute (trait) | `trait_vocabulary` | `traits.register` | `traits.vocabulary` | `traits.declaration_schema` |
| condition (state) | `state_vocabulary` | `verbs.register_state` | `verbs.vocabulary` | — |
| condition group | `state_groups` | `verbs.register_group` | `verbs.groups` | — |
| action | `action_specs` | `actions.declare` | `actions.vocabulary` | `actions.declaration_tool` |
| verb spelling | `verb_synonyms` | `rulesets._fold` | `rulesets.synonyms` | — |
| rule | `rules` | `rulebooks.add` | `rulebooks.all_rules` | `rule_gen.PERMITTED` |
| condition (clause) | inside a rule | `conditions.normalise` | `conditions.PREDICATES` | `conditions.schema` |
| effect | inside a rule | `effects.apply` | `effects.VOCABULARY` | `effects.schema` |
| word list | `token_lists` | `token_lists.register` | `token_lists.vocabulary` | `token_lists.schema` |
| pronoun set | `pronoun_sets` | `pronouns.register` | `pronouns.vocabulary` | `pronouns.set_schema` |
| goal / quest goal | on the character | `goals.sanitise` | — | `goals.schema` |

Two of those are worth pausing on.

**`rulesets._apply` is already a complete writer for half this list.** It takes
a JSON document with `attributes`, `conditions`, `kinds`, `verbs`, `actions`
and `rules` sections and writes every one of them into a world through the
functions above. A ruleset is "everything a world could have said for itself
with `create rule`" -- said by a file instead. What this plan builds is the
other half of that sentence, and the two should stay interchangeable: anything
`create` can make, `export` should be able to write out as one of these
documents, and anything one of these documents says, `edit` should be able to
show (§15, phase 7).

**The schemas are not menus and must not be turned into menus mechanically.**
`conditions.schema` offers twenty-six optional predicate fields and lets the
model choose one, because that is the shape a provider will take. A player
offered twenty-six optional fields has been handed a form, not a choice. So the
forms in this plan are written by hand beside the schema, and a test asserts
that the two cover the same ground -- the arrangement `effects.VOCABULARY`
already has with `_apply_one`, where "adding an effect without an entry here is
caught by a test".

---

## 3. The spine: one table of makers

### 3.1 What a maker says

`world/making.py` holds one `Maker` per creatable thing. It is a description,
not a class to subclass:

```python
Maker(
    key="attribute",
    words=("attribute", "attributes", "trait", "traits"),
    label="Something measurable about a person",
    listing=lambda root: traits.offerable(root),      # [(id, one line)]
    one=lambda root, slug: traits.describe_spec(root, slug),
    new=NEW_ATTRIBUTE,                                # a menus.Form
    edit=lambda root, slug: EDIT_ATTRIBUTE,
    remove=None,                                      # nothing removes a trait
    revisable=True,
    help="A number kept about a character: stamina, standing, fuel.",
)
```

`listing` is the one function every reader needs and the one no register
exposes in the same shape today -- `traits.offerable`, `kinds.vocabulary`,
`verbs.groups` and `rulebooks.all_rules` each answer a different shape. Each
gains a small adapter here rather than a change to itself.

`remove=None` is a real answer and not a gap. A trait that half the world's
rules test cannot be deleted without breaking them silently, and the honest
alternative -- suspend a rule, which already exists -- is better than a
deletion that leaves a rule testing a word nothing registers. The same is true
of kinds and actions. **Rules, word lists, items, rooms, people and quests are
removable; vocabulary is not.** `view faults` already reports the consequence
of a vocabulary gap, which is the right place for it.

### 3.2 Four readers

The point of writing that table down once is that four separate pieces of work
read it:

1. **The subjects.** `commands/making_subject.py` walks the table and produces
   a `Subject` per maker with the `create`, `edit`, `delete` and `view` uses
   the maker supports. The command line (`create attribute stamina`), the menu
   entry under a bare `create`, and `offered=owns_here` all come out of the
   table. No maker writes a `Use`.
2. **The pickers.** Any form needing "an attribute" puts a `Picker` on the
   maker (§4.1), and gets the world's list plus the maker's own `new` form for
   free. This is the whole of the user-facing requirement that reusable things
   be offered before they are invented.
3. **`export world` and `import world`.** A maker knows how to list what a
   world holds and how to write one; a document is that, serialised. The
   ruleset sections already name most of them, so the document format is a
   ruleset with `rooms`, `items`, `people` and `quests` added. Out of scope
   here, named so the table is built for it.
4. **A tool surface.** The MCP server, an ACP agent, or anything else outside
   the game wants exactly this list: what can be made, what each needs, what
   exists already. Also out of scope, also the reason the table is a table.

A test asserts every maker in the table has a subject, a help entry, and a
`new` form whose required fields are all reachable from the command line -- the
existing rule that every point in a menu is also typeable (§14).

---

## 4. Two engine additions

`world/menus.py` gets two things and nothing else. Both are small, both are
general, and both are needed by more than the forms in this plan.

### 4.1 `Picker`: choose what is there, or make one

```python
menus.Picker("kind", "What sort of thing this is", maker="kind",
             required=True,
             none="None of these -- describe a new sort of thing")
```

A `Picker` is a `Field` whose `choices_for` is the maker's `listing`, plus one
final entry that opens the maker's `new` form. It inherits the engine's
filtering and paging, so a world with two hundred kinds is typed at rather than
scrolled through, and it shows each entry's one-line description so choosing
between `chest.n.02` and `chest.n.01` is possible without leaving the menu.

Two behaviours it needs that a choice field does not have:

* **The list is what the world holds now**, not what it held when the form was
  built. `choices` is already allowed to be a function of the context, so this
  falls out.
* **Near-duplicates are caught at the bottom, not on the way in.** Several
  registers have `near_duplicate` for exactly this. If somebody picks "make a
  new one" and types a name close to one that exists, the new form says so and
  offers the existing one, the way `token_lists.register` already folds on the
  model's behalf. A person should be told rather than folded silently.

`Picker` also solves a problem the plan would otherwise have: a rule's
conditions are a list of conditions, each of which is a small form. A
`Picker` whose maker is `condition-clause` and whose listing is the clauses
already on this draft, plus "add another", is the same widget again.

### 4.2 `Picked`: a submenu that answers with a value

Today a `Submenu` with `fresh_draft=True` gets a draft of its own and has no
way to hand anything back; the child's final `Action` writes to a store and
closes. That is right for `create tokens` opened from the top and wrong for
`create tokens` opened from inside a rule that needs a word list.

So: an `Action` may return `menus.Picked(value, said)`. `GameMenu.run_action`
recognises it, writes `value` into the draft of the frame that opened the
submenu under the key the submenu was opened for, says `said`, and goes back
one frame. Everything else about the action is unchanged; a `Picked` returned
by an action nobody opened for a value behaves as `after=BACK` with a message,
which is what it means.

That is about twenty lines in `run_action` and one new class. It is worth
being deliberate about because it is the only place in this plan where the menu
engine grows a new concept, and because "the child wrote something and the
parent should now use it" is the shape every nested wizard after this will
want.

---

## 5. Finding what you mean, in the room you are in

`edit room` means the room you are standing in. Always, with no argument and
no ambiguity, because there is exactly one and naming it could only introduce
the mistake.

`edit item` and `edit npc` are the ones with a choice to make, and the rule is
the one the user asked for and the parser already keeps: **candidates are what
is in reach, never the world.** Concretely, a new helper in
`commands/subjects.py`:

```python
def thing_here(caller, words, wanting=None):
    """What `words` names among what the caller can reach, or a menu of them."""
```

built on what already decides this for every verb in the game:

* the candidate set is the room's contents, the caller's inventory, and what is
  in or on anything reachable -- `relations.reachable`, not a database search.
  "the coin in the chest" is reachable and resolves, because reach already
  follows containment and already stops at a closed lid;
* matching is `naming.resemblance`, so "blackbaord" and "kandle" reach the
  right thing and a confident match is acted on while a merely plausible one is
  offered back;
* two things answering to one word produce the engine's own numbered list,
  which is the existing `which one?` behaviour rather than a second one;
* with no words at all, every reachable thing is offered as a numbered menu.

What this buys is exactly the failure this is meant to avoid: `edit item lamp`
in a world with forty lamps edits the one in front of you or asks, and can
never silently edit one on the other side of the map. It also means the
building commands inherit typo tolerance and possessives ("Samuel's coat") for
nothing, because `naming` and `anatomy` already do that work.

**One thing at a time, always.** There is no `edit every lamp` and no bulk
selection anywhere in this plan. Making the same change to many things is a
templating problem -- every coin is the same coin -- and belongs with the
"objects from templates" item in `future-plans.md`, where the answer is that
they were one thing to begin with rather than forty things edited together.
`world/bulk.py` is about quantity in the parser ("get all the coins") and is
not this; it stays out.

`create item` and `create npc` put the new thing here. `create room` is the
exception and takes a direction (§9.2).

---

## 6. The vocabulary: kinds, affordances, attributes, conditions

These four are one phase of work because they are one idea: the closed word
lists a world keeps so that its rules can mean something. All four already have
a writer that folds near-duplicates; all four gain a form.

### 6.1 Kinds and affordances

`create kind` is the most interesting form in this plan, because it is where
invented vocabulary gets grounded, and the mechanism already exists.

```
create kind
  Word                  datapad
  Which sense           [1] datapad is not in the dictionary
                        (for "chest": [1] chest.n.01 the ribcage
                                      [2] chest.n.02 the box with a lid)
  What sort of thing    device.n.01                      <- only when needed
  What can be done      read yes / write yes / burn no / eat no
  What it holds         in: anything;  on: nothing
```

* **Which sense** is `lexicon.senses(word, pos="n")` as a picker, with each
  sense's gloss. This is the half of grounding that matters most and the half
  `kinds.needs_anchor` says is not an anchor case: `box`, `key`, `chest` and
  `pen` all have senses and the world just needs to be told which one.
* **What sort of thing** is the `under` anchor, shown only when
  `kinds.needs_anchor` says the dictionary has never heard of the word. Its
  picker offers the sensible roots -- `device.n.01`, `container.n.01`,
  `tool.n.01`, `weapon.n.01` -- and accepts any sense, checked against the
  dictionary exactly as `kinds.anchor` already checks a model's answer.
  `commonsense.py` can suggest one for free where the corpus is present, which
  is the same use it is already put to and within its "never a floor" clause.
* **What can be done** is an affordance map. Affordances are verbs
  (`affordances.py`), so the picker offers this world's actions plus the common
  English ones, each as yes or no, and the `{"burn": False}` form means
  negation needs no vocabulary. The affordance list is a cache key, so the form
  says so: `help affordances` already explains why.
* **What it holds** is `relations` -- `accepts` on the spec.

Everything is written by one call to `kinds.remember`, which applies the
taxonomic floor last and so cannot be talked out of a chest being a container.

`view kind <word>` shows the spec, its ancestors, how many objects in this
world are of it, and which rules are filed against it. That last line is what
makes §6.4 usable.

### 6.2 Attributes

`create attribute` fills `traits.register`: slug, name, what it means, type
(`counter`, `gauge`, `static`), base, minimum, maximum, rate. `traits.bands`
gives it the optional part where a number is described in words ("exhausted",
"fresh"), which is worth having in the form because a trait nobody can read is
a number on a sheet.

`vocabulary.claim` refuses a word already held as a state, and says why. That
refusal must reach the player as a sentence they can act on -- "this world
already keeps `warm` as a condition; a word cannot be both" -- which is
`menus.Refuse`.

### 6.3 Conditions

"Condition" in the user's list means a state: `lit`, `open`, `burning`. The
form is two levels, because states come in groups and the group is where the
useful behaviour lives:

```
create condition
  Word                  lit
  What it means         the lamp is giving light
  Group                 [Picker over verbs.groups, + make one]
    (new group)         lightness -- exclusive, so lit and unlit cannot
                        both hold; does not end on moving
  Cannot hold with      unlit                 <- filled from the group
  While it holds        you may not act / move / speak    <- rarely
  Or worked out from    [conditions, for a derived state]
```

The group picker is `Picker` doing its job: an exclusive group is the thing
that makes `wet` put out `burning`, and a world whose creator never met the
concept will get one anyway because the form asks for one and offers to make
it. "Or worked out from" is `when` -- the derived state, defined once, that
`verbs.py` describes as how "starving" is hunger at 10 or less. It takes the
condition builder from §8.2, which is why conditions come after rules in
implementation order even though they come before them here.

### 6.4 First answer stands, and the way out

A kind's affordances and an action's arity are **cache keys**. Every rule the
world has learned is filed against them, so revising one silently changes what
those rules mean. `actions.py` says so ("First answer stands"), and `kinds.py`
says so, and both are right.

But a person building by hand will get one wrong, and "you may never fix that"
is not an answer either. `reset verb` already settled the shape of the
exception, and it settled it well: the reset is a separate, named gesture; it
is confirmed; it says out loud what it does and does not touch; and the rules
survive untouched.

So:

* **`edit kind` and `edit action` change only what is safe to change** -- the
  `means` line, the trait's name, a description. Safe is defined as "no cache
  key and no rule reads it".
* **`reset kind <word>` and `reset action <verb>`** are the exception, beside
  `reset verb`. Each says what depends on it before asking: "14 objects are of
  this kind; 3 rules are filed against it; every narration about them will be
  written afresh". On yes, it drops the spec, and calls
  `effects.forget_narrations` on the affected objects, which already exists and
  already does exactly this job for a modified object.
* **`view kind` names the dependants**, so the question can be answered before
  it is asked.

This is a decision on the record rather than a convenience: see §16.

---

## 7. Actions and verbs

`create action` fills `actions.declare`, and it is short, because the hard part
of that declaration is a menu already:

```
create action
  Word                  launch
  Which sense           [1] launch.v.01  set in motion
                        [2] launch.v.04  begin with vigour
  What it means         to send a ship away from its berth
  What it takes         direct     the ship          must be able to touch it
                        instrument the launch key    optional, must be holding
  Works even when       [ ] you cannot act  [ ] cannot move  [ ] cannot speak
```

Roles come from `actions.ROLES`, access from the access vocabulary beside them,
and "works even when" is `despite`, which is the one field that loosens rather
than tightens and therefore is the one the form should ask about last and least
enthusiastically. The sense picker is `lexicon.senses(word, pos="v")` and is
what makes `lexicon.verb_ancestors` useful afterwards -- without it, as
`actions.py` notes, `launch` answers `['open', 'propel']` from the bare word.

`create verb` is the other, smaller thing: teaching this world that one
spelling means another. `rulesets._fold` already writes it and
`rulesets.synonyms` already reads it; this gives it a menu and moves the writer
out of `rulesets.py` into `verbs.py` where it belongs, since it will now have
two callers.

The important line in the form is the one that says what a fold is *for*: it is
world-scoped on purpose, because a server runs many worlds and `forge` meaning
`make` is a fact about one of them.

---

## 8. Rules

This is the largest form in the plan and the one the rest exists to serve.
Nothing about the shape of a rule changes: `rulebooks.blank` already lists
every slot, `rulebooks.add` already normalises conditions and drops what cannot
be stored, and `rule_gen.PERMITTED` already says what a written rule may
contain. The form fills the same dictionary a model fills.

```
create rule
  Name                  a lit lamp cannot be lit again
  When somebody tries   [Picker: this world's actions, + create action]
  What it is about      [Picker: the thing acted on, the actor, the room, ...]
  Where it applies      [Picker: this object / this sort of thing /
                         this room / this area / the whole world]
  Only when             [conditions, optional -- guards]
  It requires           [conditions]
  Then                  [effects]
  What people see       "The lamp is already lit."
  What should happen    [the phase question, §8.4]
```

**The phase is asked last**, which is why §8.4 comes after the fields it reads
rather than before them. It is the one field that is *about* the rest of the
rule: its three nudges have nothing to nudge from until the conditions and
effects exist, and the firing order it shows cannot be drawn without the action
and the scope. Asking it first would be asking a builder to classify a rule
they have not written yet.

The form is `guided`, so a new draft still walks its required fields in order
and the phase is the last question before the summary. Somebody who knows what
they want can choose it at any point from the summary, as they can any field.

### 8.1 Scope

`Where it applies` is the field that decides whether `power datapad` powers the
datapad or the ship you are standing in, so it gets the most care. The picker
offers, in order of how specific it is:

* **this very thing** -- resolved by §5, so it means the lamp in front of you;
* **this sort of thing** -- a `Picker` over kinds, defaulting to the kinds of
  the thing in front of you, which is nearly always what is meant;
* **this room**, **this area** -- `zones`, with the current zone first;
* **the whole world**.

`rulebooks.said_scope` renders each of those as a sentence already, so the
picker's labels are free. `about` -- what the scope is matched against -- is
the other half of the same question and is shown next to it, defaulted to
`direct`, with `here`, `zone` and `enclosure` available for the rule that is
about a place nobody named.

A scope that is too general is refused with the reason: `rule_gen.SCOPE_CEILING`
and `SCOPE_BREADTH` already measure this, and a person filing a rule against
`artifact.n.01` should be told it covers ten thousand sorts of thing before
they find out by playing.

### 8.2 Conditions

A condition is a subject and one predicate (`conditions.py`), which is a two
-field form, and the twenty-six predicates are a picker grouped into the
handful of questions a person actually asks:

| Group | Predicates |
|---|---|
| what state it is in | `is`, `lacks` |
| what sort of thing it is | `kind`, `not_kind`, `affords` |
| who has it | `holds`, `not_holds`, `wears`, `not_wears`, `owned_by`, `not_owned_by` |
| where it is | `placed`, `not_placed`, `in_room`, `not_in_room`, `leads_to` |
| a figure about somebody | `trait` |
| whether it is there at all | `exists`, `gone`, `unbound` |
| the word that was used | `called` (§8.6) |
| the time | `clock` |
| reach and sight | `reachable_by`, `visible_to`, `able` |
| never | `never` |

The value picker then depends on the predicate: `is` offers this world's
states (and offers to make one, §6.3), `kind` offers its kinds, `trait` offers
its attributes with a minimum and maximum. This is the single clearest place
where "offer what exists or let them make a new one" pays off, and it is why
`Picker` is engine work rather than a helper in one module.

`conditions.describe(clause, mood="abstract")` renders each finished clause
back as a sentence, so the summary of a rule under construction reads as
English -- which is the only way somebody is going to notice they built the
wrong one. `conditions.normalise` holds every clause to its shape on the way
into `rulebooks.add`, unchanged.

One level of `any` (or), matching what the schema offers a model, and no
nesting. A list already means all of them.

### 8.3 Effects

`effects.VOCABULARY` is the picker's list, and it is already written for this:
each entry has a `means` sentence in the second person ("puts something into a
condition, or takes it out of one") and a `takes` line naming its fields. The
form is one small sub-form per effect type, and `effects.say` renders each
finished one back as a clause, the way `view effects` already prints them.

Effects that are not readable backwards (`modify_object`, `create_room`,
`describe`) are offered with that noted, because a rule built only out of them
is a rule no NPC can ever plan towards, and the `backwards` flag already
records which.

`create_object` gets the same guard `effects.modify_complaints` applies to a
model: a name says what a thing is and never its condition, and a description
may only use word lists this world keeps. One function, two callers, so a
person and a rule are held to the same standard.

### 8.4 The phase, which is asked and not inferred

**Inference is not possible, and it is worth being exact about why**, because
the reason is the same reason the phases are worth having.

A phase does not say what a rule does. It says **what else runs**. Reading
`attempt.py`:

* `instead` -- the most specific one wins outright and processing ends. "One
  winner, never a merge: this is the phase where meaning lives." It runs
  *before* the checks, so an instead rule is not subject to them.
* `check` -- every gathered rule, cumulatively, in specificity order; the first
  unmet condition is what the player is told. "Can only ever make an action
  stricter, never change what it means."
* `carry_out` -- the most specific rule with anything to do supplies both the
  effects and the contest. One winner, after the checks.
* `after` -- what follows from it having worked.
* `becomes` -- fires because something became true, not because anybody tried
  anything.

Now try to infer from content. Only one signal exists: **a rule with no effects
is a check**, because a rule that requires something and does nothing can only
be a precondition. That signal is already the default -- `rulebooks.blank` has
`phase=CHECK`.

Every other pair is undecidable, and not by a little:

* **instead versus carry_out.** Both have effects, both take the most specific
  winner. The difference is whether the checks run first. Nothing in the rule's
  own content says whether its author wanted them to.
* **carry_out versus after.** "Eating consumes the food" and "eating gains you
  stamina" are the same shape -- an effect on a role, no conditions. One is what
  the verb *is* and one is what follows. The distinction lives entirely in the
  author's head.
* **check versus instead.** A rule that refuses ("the door is locked") and a
  rule that replaces ("the door is locked, and rattling it wakes the guard")
  differ by whether anything else may still speak.
* **becomes versus any action.** `action: None` already means "every action"
  (`rulebooks.blank`), so a missing action cannot distinguish a becomes rule
  from a rule about everything.

So the answer is not to infer it. It is to **stop asking it in Inform's
vocabulary and ask it in the second person**, which is the same move
`rule_gen.py` made when it turned "how general is this?" into a menu of closed
identifiers: the hard judgement becomes multiple choice.

```
What should happen?
  [1] It should be stopped -- say why it cannot happen, and refuse it
      Every rule like this applies, so you can add another later.
  [2] It is what happens -- this is what the verb does here
      The most particular rule wins; the checks still apply.
  [3] Something else should happen instead -- and the usual thing should not
      The most particular rule wins outright, and nothing else runs,
      not even the checks.
  [4] It follows afterwards -- once it has already worked
  [5] Nothing is being tried -- this happens when something becomes true
```

Each line names the consequence a builder actually has to choose between --
does everything apply or only the winner, do the checks still run -- rather
than a rulebook name. `[1]`'s second line is the property `attempt.py` calls
"safe to extend by construction", and it is the most useful thing a new builder
can be told, because it is permission to write a half-right rule and add to it.

**Three nudges, which are not inference.** This is what asking last buys: by
the time the question arrives the rest of the rule exists, so the form can look
at it and say something. It never chooses:

* effects, with `[1]` chosen -- a check rule with effects is legal (refusing can
  set a state) and is usually a slip, so it says so;
* no effects, with `[2]` or `[3]` chosen -- a carry-out rule with nothing to do
  means the verb does nothing, which is the silent no-op `actions.py` was
  written to stop;
* no action named -- `[5]` is offered first, with "every action" named as the
  other reading.

**And it shows the order at the moment of choosing.** §8.5 runs
`rulebooks.gather` before the rule is kept; the phase field runs it too, and
shows where this rule would land among the rules already there:

```
  instead     (none)
  check       the world -- you must be able to reach what you act on
              water -- you cannot combine a thing with itself     <- yours
  carry out   the world -- combining two substances makes a third
```

Seeing the rule take its place in firing order teaches the phases in a way no
help text does, and every piece of it already exists.

### 8.4.1 Worked: what endless alchemy needs

The flagship world in `future-plans.md` is the test of this, and it needs all
five. `rulesets/crafting.json` declares `combine` and folds `mix`, `blend` and
`join` onto it, and ships **no rules at all** -- every one of these is the
builder's:

| What they want | Phase | Why that one |
|---|---|---|
| both things must be substances; you cannot combine a thing with itself | check | cumulative -- each is written separately and they add up |
| pouring something into the cauldron means putting it in | instead | a `try` redirect; the verb means something else here, and re-enters the pipeline |
| combining two substances destroys both and produces a third | carry out | it is what the verb does, filed at the world |
| water and fire make steam | carry out | filed against the kind, so the most particular rule wins over the line above |
| each new substance raises `discoveries` | after | it follows from it having worked |
| at ten discoveries the alchemist has something new to ask | becomes | nobody tried anything; a figure crossed a line |

Two of those are the same phase at different scopes -- the general rule at the
world and the particular recipe filed against a kind, the second winning by
specificity. That is §8.1's distinction, already answered by the time this
question is asked, which is part of why it is asked last: a builder who has
settled where a rule applies is in a much better position to say what should
happen than one who has not.

None of the six could have been placed by reading its own content.

So: **the phase picker stays, it comes last, and it is the field the form
spends the most words on.**

### 8.5 Checking before keeping

The last entry in the form is "Keep this rule", and before it writes, it runs
what already exists:

* `rulecheck` over the world as it would be, reporting a condition this rule
  requires that nothing in the world can bring about -- the fault that is
  "invisible while a world is being played and fatal to it afterwards";
* `rulebooks.gather` for the action and scope, showing where this rule would
  sit in firing order and what it would sit behind;
* the orphan and dead-rule checks `edit rules dead` already runs.

None of these refuse the rule. They are shown, the rule is kept, and
`view faults` says the same thing later. A builder who knows what they are
doing is allowed to write a rule whose moment has not arrived yet.

### 8.6 A rule for a thing that does not exist yet

Every other predicate resolves a subject and then asks it something, so every
other predicate answers *no* about a word that named nothing. That is the
right answer almost always, and it made one world unwritable.

`summon air`, in a world whose air has not been made yet. The rule that makes
air has to be found from the sentence, and at the moment the sentence is read
there is no air to find it by. Worse, the pipeline had already acted: an
unmatched noun goes to `item_gen.conjure`, which either refuses (a world that
writes no items of its own) or invents one -- and then the rule fires and
makes a second. Both were reported from play, one after the other, and the
answer given at the time was that it could not be expressed.

Three things, which are one change:

* **`called` asks about the word.** `{"subject": "direct", "called": "air"}`
  is true when the word used for that role names air -- whatever it was found
  to mean if it was found to mean anything, and otherwise the word itself,
  with articles off, this world's noun folds applied, and a sense read down to
  its lemma. So one rule fires on `summon air` whether or not there is already
  air in the room, which is the difference somebody writing it should never
  have to think about. It rides on `conditions.Context.words`, which is what
  the player typed, kept beside `bound`, which is what it was found to mean.
  The two come apart exactly when nothing answers, which is the case this is
  for.
* **The rulebooks are consulted before the noun is conjured.** "You see no
  earth here" is right up until a rule exists that knows how to make one --
  the same argument `attempt._redirect_waiting` already makes one step later
  about "Launch what?". `_knows_the_word` is deliberately narrow: a rule
  counts only if it is selected *by the word*, through a `called` guard about
  a role that failed to bind, and only if it survived `gather`. Nothing
  written before `called` existed can match, so no world in play changes.
  The same test lets the arity question ("Summon what?") step aside.
* **`called` has no opposite.** It is in `UNNEGATABLE` with the reason: "not
  called earth" is every other word there is, and it would match a typo as
  readily as a sentence, in the one phase where matching wrongly means a rule
  fires that nobody meant.

Two things that were in the way came out with it, both for the same reason --
they are asked **after** a rule has been found, and neither is the question
"what does this verb mean", which somebody has already answered by writing it
down:

* whether that sort of thing admits the verb at all (`verb_gen.ask_admission`);
* how to describe what happened (`verb_gen.narrate`).

In a world that writes no verbs of its own, both used to come back as a
refusal, which threw away the rule and every effect with it, in red. Now the
first proceeds -- the rule's own checks stand, and nothing is remembered, so a
world given a key later still gets to ask properly -- and the second falls
back to the player's own sentence: `summon earth` reads "You summon earth."
A world built by hand and paid for with nothing runs its own rules and reads a
little flatly. That is the trade its builder made; a silent refusal is not.

`tests/test_summoning.py` is the whole of it, written as the world it came
from.

---

## 9. Contents: items, rooms, exits, people

### 9.1 Items

`create item` here; `edit item` on what §5 finds. Name, description, kinds
(picker), states (picker), owner, and where it goes -- your hands, the floor,
or in/on/under/behind something reachable (`relations.PREPOSITIONS`).

Everything goes through the writers a rule's effects use -- `effects` for
creation and modification, `relations.place` for where it sits,
`verbs.set_states` for its condition -- so an item somebody typed and an item a
rule made are the same object made the same way. `effects.modify_complaints`
guards the name and description as in §8.3.

`create item from <thing>` copies a reachable thing, which is the cheap version
of the "objects from templates" item in `future-plans.md` and costs nothing to
add here: every coin in a world can be the same coin.

### 9.2 Rooms and exits

`create room <direction>` digs. The machinery is entirely in place and none of
it is model-dependent: `coords.DIRECTION_VECTORS` gives the cell,
`coords` says whether something is there already, `zones` says which area it
belongs to and whether that area is full, and the `create_room` effect already
opens a way onto somewhere new. The only new part is that the room is written
by a person rather than generated on first entry.

**The form asks for everything**: name, description, area (picker over `zones`,
+ make one), states, and what is in it. It does not try to be quick by asking
for less, because a room with no description is a room somebody has to come
back to, and the generated rooms it will stand beside have all of it.

Twenty hand-built rooms is twenty descriptions, and the answer to that is not
to ask for fewer -- it is that there are already several tools for it and a
builder can use whichever suits:

* **word lists.** `{smell}`, `{weather}`, `{stonework}`: write the list once
  with `create tokens`, and a description that uses it keeps its choice for
  that room for good (`token_lists`). This is the cheapest way to write twenty
  rooms that differ, and it is the reason word lists exist.
* **copying.** `create room ... from <room>` takes an existing room's text as
  the starting draft, the same gesture as `create item from <thing>` in §9.1.
* **`~`.** A model fills one field in, for a builder who has a key and wants
  one paragraph written. §12's constraint is that nothing *requires* a model,
  not that nothing may use one.
* **the line editor**, which `LONG_TEXT` fields already open and come back
  from.

If the cell is occupied, the form says which room is there and offers to
connect to it instead -- which is the existing behaviour that lets a world
close back on itself, surfaced rather than reimplemented.

`edit room` is the room you are in: name, description, area, states.

`create exit` links this room to another by name, for the connections a grid
cannot express -- a portal, a staircase, `in` and `out`, which `coords` already
excludes from displacement for this reason. `delete exit` is the one deletion
here that needs care: `effects.py` keeps exits permanently off limits to rules
because a character deleting one would strand the world. A builder may, with a
confirmation that names what becomes unreachable.

### 9.3 People

`create npc` exists and generates. It grows a fork at the top: **generate one**
(what it does now, costs money) or **build one** (new, costs nothing).

The built form is name, description, pronouns (picker, + `create pronouns`
which already exists), kinds, traits (picker over attributes, with values),
states, what they are carrying, and what they want -- a goal, which is the
condition builder from §8.2 again.

`edit npc` on what §5 finds, same fields. This is also where a quest gets
attached (§10).

What a built NPC does without a model is out of scope and named in
`future-plans.md` as the AIML item: today an NPC with no model reachable simply
does not act. The one thing this plan adds is that such an NPC can still
**offer a quest**, because a quest offer becomes an effect rather than a
model's tool call (§10).

---

## 10. Quests without a model

This is the only genuinely new store in the plan, and the reason is worth
stating precisely: **a quest today exists only from the moment it is offered.**
`quests.offer` builds the record on the character receiving it; there is no
such thing as a quest waiting to be given. Every quest in the game so far was
written by `quest_gen` in the middle of a conversation.

A hand-built world needs the other thing: a quest written in advance, attached
to somebody, waiting.

**The store.** `world_root.db.quest_specs`, `{id: spec}`, where a spec is what
`quests.offer` takes -- title, description, goal conditions, reward effects,
punishment effects, time limit -- plus four fields that only a pre-written
quest needs:

* `givers` -- who hands it out, and in whose words (§10.2);
* `repeatable` -- once ever, or again after a cooldown;
* `after` -- quest ids that must be done first, which is what makes a chain,
  and what the endless-alchemy world in `future-plans.md` is built out of;
* `only_when` -- conditions, so a quest can wait for something other than
  another quest.

Completion is recorded per character, beside the quest list already on them.
`quests_completed` exists as a builtin trait and counts; this needs the names,
so that "once ever" can mean it.

**Offering is an effect, not a hook.** `offer_quest`, added to
`effects.VOCABULARY`, taking the spec id and a role for who is being offered
it. That is the whole integration, and it is the right one for three reasons:

* it goes through the same guarded applier as every other effect, so a quest
  spec cannot do anything `quests.QUEST_EFFECTS` does not already permit;
* it makes *when* a quest is offered a decision the world writes as a rule --
  on greeting, on entering the room, on the third time somebody asks -- rather
  than a behaviour hardcoded here;
* it works identically whether a person, an NPC, or a model triggered it, which
  is the standing rule for effects.

`create quest` therefore builds two things and says so: the spec, and
optionally a rule that offers it. The rule is the default (`when somebody
greets <this NPC>`, `instead`, scoped to that object) and can be declined by
somebody who wants to wire it themselves.

**A spec belongs to the world, not to its giver.** Deleting the NPC leaves the
spec in place, because the errand is the thing somebody wrote and the person
who hands it over is a field on it. A spec with nobody left to give it is
offered by nothing, `view faults` reports it the way it reports an orphaned
rule (`rulebooks.orphans` already has this shape), and `edit quest` reattaches
it. `quests.forget_world` still takes the lot when the world goes.

That is the same trade `rulebooks.py` made when it chose "one store, not five":
keeping the attachment on the errand rather than on the character means
deleting the character does not take it with them, and the cost is an orphan
report, which is cheaper than a second store plus an index to keep in step
with it.

### 10.2 Whose errand it is, and in whose words

A spec's `givers` is a list, not a dbref, and each entry is a character and
what *they* say when they ask:

```python
"givers": [
    {"npc": "#412", "description": ""},
    {"npc": "#588", "description": "The chalk. From the storeroom. Before "
                                   "the bell, if you would."},
]
```

An empty override falls back to the spec's own description, so the simple case
stays simple and nothing has to be filled in twice.

**This is the field that stops reuse flattening a world**, and it is worth
saying why it is the description rather than the goal. Nobody minds that two
characters both want the chalk fetched -- errands repeat in real places, and a
standing bounty that several people can set you is a good thing to be able to
build. What makes a world feel cookie-cutter is hearing the *same sentence*
twice from two different mouths. The goal is the machine half; the description
is the voice.

The game already makes this exact split one level down, in `attempt.py`: a rule
says what a verb means for everything of its sort, and the specifics say "how
this door differs from that door". A spec and a giver's override are that same
division applied to errands, which is why it does not need a second store --
one record, a general answer, and a particular one beside it.

It pays off hardest on the model path. `use_quest` (§10.3) may supply an
override with it, so a generated NPC reusing a written errand still asks in its
own voice: the expensive half -- a testable goal, sanitised conditions, effects
inside `QUEST_EFFECTS` -- is reused for nothing, and the cheap half is one
sentence of fresh prose. That is a better trade than either writing the whole
quest again or handing out somebody else's words.

**Narrow on purpose: the override is the description and nothing else.** The
title names the errand in the quest list and in `quests_completed`, and two
names for one errand would make a chain's `after` unreadable to the person
following it. If a giver ever needs its own title, it needs its own spec.

### 10.3 One pool of errands, for the model too

`quests.offer` is refactored to take a spec, and `quest_gen` builds a spec
instead of calling `offer` directly -- so the model path and the hand path
converge on one writer rather than running beside each other. That is the piece
that keeps this from being a second quest system.

It buys something more than tidiness, and it is worth building for
deliberately: **once specs are a register, the generator can be shown the ones
that exist and reuse one.**

`quest_gen` today writes a new errand every time it is asked, which is the
right behaviour when there is nothing to reuse and waste when there is. A world
with a dozen written errands is a world where an NPC asked for work should
usually be handing one out, not inventing a thirteenth. So:

* **A lookup.** `quests.lookup_tools()` alongside the other registers in
  `lookups.MODULES`, answering with the world's specs -- title, what it asks
  for, who else gives it, whether it repeats. The generator can read the pool
  before it writes.
* **An answer that is not writing.** `write_quest` gains a sibling, `use_quest`,
  taking a spec id and, optionally, this character's own way of asking (§10.2).
  Choosing one is a complete answer to "what does this character want", and it
  costs a fraction of writing one.
* **The prompt says to prefer it**, in the same words every other register's
  prompt says to reuse what is there: this is `traits.py`'s "one vocabulary per
  world" applied to errands, and it heads off the drift it heads off everywhere
  else -- eleven near-identical fetch-the-chalk quests with eleven different
  goal conditions, only some of which are testable.

The player gets the same pool from the other side: `create quest` opens on a
`Picker` over the existing specs before it offers a blank form, so attaching an
errand somebody already wrote to a second character is one choice and a
sentence rather than a retyped quest. Same list, same maker, two readers --
which is §3.2 doing its job rather than a special case.

Worth being explicit about the one hazard: a spec reused by several givers is
one record, so editing its goal changes the errand everywhere. Editing a
giver's own words does not, which is the point of §10.2. The `view quest`
listing names every giver for that reason, and `edit quest` says how many
before it opens.

---

## 11. Terms and vocabulary: yes, in three parts, and one no

The user's question -- should players be able to create terms and vocabulary,
to ground original words against WordNet and ConceptNet -- has a better answer
than yes or no, because **the grounding mechanism already exists and is already
per-register.** A kind grounds through `under` and a sense id. An action grounds
through `sense`. A state grounds through its group and its `means`. A trait
grounds through `means` and its bands. There is no ungrounded-term problem
waiting for a new store; there is a set of fields the generators fill in and
players currently cannot.

So:

**(a) Yes to reading: `view term <word>`.** Everything WordNet and ConceptNet
know about a word, together: its senses and their glosses, what each is a kind
of and what kinds of it there are, its verb forms, and ConceptNet's
`/r/ReceivesAction`, `/r/MannerOf`, `/r/HasPrerequisite` and `/r/DistinctFrom`
edges, which are four things this game invented for itself and can now show
side by side. `future-plans.md` lists this as its own item; it belongs in this
plan because somebody picking a sense in §6.1 needs it open in front of them,
and because it is the one command that makes the lexicons visible to a player
who is building without a model. Costs nothing, reads two corpora already on
disk, answers neutrally when they are not.

**(b) Yes to grounding, as fields on the forms already planned.** §6.1's sense
picker and anchor picker, §7's verb sense picker. Nothing new.

**(c) Yes to one small new store: word folds for nouns.** `verb_synonyms`
already teaches a world that `forge` means `make`. The same table for nouns is
what makes an invented word *playable* rather than merely stored: a world with
a kind called `raygun` should be able to say that `blaster` and `zapper` name
it, so the parser binds them and `naming.resemblance` stops trying to conjure a
second object. Without it, an invented word exists in the register and cannot
be typed. This is the one piece of "create term" that is not already covered,
it is about fifty lines, and it should be done.

**(d) No to adding senses to WordNet itself**, which `future-plans.md` floats.
`lexicon.py` makes a promise the whole cache design rests on: WordNet is a
closed controlled vocabulary that the world selects from, it is never asked
what a word means here, and nothing in it is load-bearing because it may be
missing entirely. A player-added synset breaks all three -- it is a global
mutation to express a world-local fact, it would sit in cache keys, and a world
exported to another server would arrive referring to senses that server has
never heard of. The world-local invented sense already exists and is called an
anchored kind. Recommend moving this item to `bad-ideas.md` with that reasoning
when the plan is built.

---

## 12. What this costs: nothing

A hard constraint, and the reason the whole plan is worth doing now: **no form
in this system calls a model.** Not for validation, not for suggestions, not
for filling a field.

`~` remains what it is -- an optional key, on forms that declare a `sponsor`,
that fills one field in. A form here declares one only where a model could
plausibly help (a description, a word list's entries) and never for anything
structural. In a world with no API key, `sponsor.key()` raises, `~` says so,
and everything else works.

A test asserts it: every form this plan adds, driven through the menu harness
in `tests/test_menus.py` with the LLM layer made to raise on any call,
completes and writes what it was supposed to write.

That test is the deliverable, more than any single command. It is what makes a
hand-built world a fixture that later features can be tested against without
spending anything or getting a different world each time.

---

## 13. Permissions

Unchanged from what subjects already do: `owns_here`, meaning whoever created
this world, or a superuser. Reading is open to anybody standing in the world --
the open sandbox -- so `view kind`, `view term`, `view rules` and the rest are
offered to everyone, and every `create`, `edit` and `delete` is not.

Shared worlds and co-ownership are both `future-plans.md` items and both will
want a broader answer than "the creator". Nothing here should make that harder:
the permission check stays in one place (`subjects.owns`) and every maker goes
through it, so the day it becomes "anybody with build rights here" it becomes
that once.

---

## 14. Every point is also a command line

The existing rule holds and is the main constraint on the forms above: every
point in a menu must also be reachable by typing. For a maker-generated
subject that means:

```
create kind                       the form
create kind datapad               the form, opened past its first field
view kind datapad                 the spec, printed
edit kind datapad means <text>    one safe field, no menu
delete rule r14 yes               with the confirmation answered in advance
```

The `<maker> <id> <field> <value>` form is what makes this usable by an agent,
a batch file, or anybody with no session -- `menus.open_menu` already decides
to print instead of opening for those, and the maker table has the field names
to make that message say what could have been typed.

A test walks the maker table and asserts each one's required fields are
settable from a single line.

---

## 15. Phases

Each phase ends with the free test suite passing and the docs updated.

**Phase 1: the engine and the table.** `Picker` and `Picked` in
`world/menus.py`; `world/making.py` with the `Maker` description;
`commands/making_subject.py` generating subjects from it. Port `tokens` and
`pronouns` off their hand-written subjects onto the table as the proof, since
both already work and any behaviour change is a bug.
*Done when:* `create tokens` and `create pronouns` behave exactly as they do
now, and a `Picker` in a test form can open a maker's `new` form and come back
with the value.

*Built.* `world/making.py`, `commands/making_subject.py`, and the two additions
to `world/menus.py`. Where it differs:

* **`tokens` and `pronouns` were ported after all**, and it was worth doing
  for a reason the plan did not anticipate. Twelve new makers prove the table
  can carry what it was shaped around; a subject it was *not* shaped around is
  what tells you what it had assumed. Three things were missing, all of them
  general rather than concessions to word lists:

  * **`Maker.opens`** -- a command line that fills more than one field.
    `create tokens smell: what it is for = brine | tar` fills three, and
    `opens_with` was only ever the short way of writing the common case.
  * **`Maker.extras`** -- an entry in a view menu that is about the register
    rather than about any one thing in it. `view tokens try <text>` is the
    case, and it would have been lost.
  * **`Maker.owner`** -- a maker anybody standing here may use. A pronoun set
    is a fact about the person choosing it rather than about the world, and
    refusing a guest one would be the world deciding how they are spoken
    about. Everything else the world is built out of stays its owner's.

  And it found three things quietly wrong, which is the part that earned the
  churn:

  * **A complete command line opened a menu anyway.** "Give all the arguments
    and there is no menu" (§4 of docs/commands-and-settings.md) was true of
    the hand-written `create tokens` and of nothing the table generated. It is
    everybody's now: a line whose draft leaves no required field unset runs
    the form's finishing action and says what happened. A line that gives only
    part of it opens the menu there, and for a caller with no menu says which
    fields are still missing -- which the old command did for word lists and
    the general path had stopped doing.
  * **`Picked` swallowed the action's `after`.** A maker's form answers with
    the same `Picked` whether a picker opened it or `create tokens` did; with
    nobody waiting it has to behave as the ordinary action it is, and instead
    every form that said `after=CLOSE` had quietly stopped closing.
  * **A picker could not make a pronoun set.** That form answered with a
    string, so the set was registered and then dropped on the floor and the
    picker stayed empty -- which is what the "add a pronoun set" entry on a
    hand-built character did. It answers with its name now.
* **A maker refuses a reserved word at registration.** `menus.Item` already
  refuses one, but only when the list holding it is drawn -- which is a crash
  in front of a player rather than a failure at import. Found by the way out of
  a room, whose natural name is `exit` and which is the word that quits every
  menu in the game; it is called a **way** (§9.2).
* **A reset keeps what you chose, and needs no key to rebuild what needed
  none.** Two bugs in one path, reported from play. `reset world` rebuilds
  from `lore.spec_of`, which carries the clock and the rulesets for exactly
  this reason -- its docstring says a reset that forgot the guidance would
  quietly undo half the wizard -- and it did not carry the permits. So a
  world built by hand came back planning zones, naming a room, describing it
  and putting somebody in it: the whole of what its creator had turned off.
  And the key check ran before anything read the spec, so a world made
  without a model could not be remade without one. `create world` now says
  a key is missing rather than refusing to open, since whether one is needed
  depends on what the wizard is about to be filled in with.
* **A rule that can never fire says so.** Reported from play: two carry-out
  rules at `everywhere` for one verb, and summoning air summoned earth.
  Nothing was broken -- carry-out takes one winner, the two tied on
  everything `rank` compares down to which was written first, and the older
  won every time. But it is the worst shape a mistake can take here: the rule
  is in the book, `view rules` lists it under carry out beside the one that
  beats it, and the world behaves as though it were not there.

  So `rulecheck.shadowed` finds them -- and finds them provably, which is why
  it is narrow: same action, same phase, same scope, same `about`, and the
  winner unguarded, so there is no attempt that reaches one and not the other.
  A rule shadowed only some of the time is a judgement, and `rulecheck`
  reports facts. It is marked in `view rules`, in the firing order the phase
  question shows while you are writing one, in `view faults`, and said
  outright the moment the rule is filed -- with what to do about it, which is
  a guard or a narrower scope.
* **And then the rule that was wanted could be written.** The same report,
  followed all the way: the two rules were tied because the only field that
  could have told them apart -- what the verb was being done *to* -- was about
  a thing that did not exist yet. `called`, and the rulebooks being consulted
  before an unmatched noun is conjured, are what make `summon air` expressible
  at all. §8.6 is the whole of it, including the two questions asked after a
  rule is found (whether its object admits the verb, and how to describe what
  happened) that used to refuse the attempt outright in a world with no model
  to answer them.
* **`~` is quick or it is nothing.** Reported from play: filling in an item's
  description ran for 160 seconds without erroring. It was not hung -- four
  rounds at the long timeout is four minutes, and a model that will not call
  the tool takes all of them. `converse` forces the finish tool on its last
  round, so two rounds is exactly "ask, and if it did not answer, make it";
  the two in between were asking a model again to do what it had already
  declined to do twice. Two rounds at the short timeout: a minute at worst,
  and giving up says which setting to change and to type it in meanwhile.

  Worth saying why it was wrong rather than only that it was. Every other
  generator runs while nobody is looking at it -- a room is written while the
  player walks on, a rule while they type the next thing -- and the timeouts
  were chosen for that. `~` is the one that has somebody sitting in a form
  watching it, and it had inherited the settings of the others.
* **`edit room` can name the room you are standing in**, which it could not.
  One argument: `modify_complaints` takes the room a thing is *in*, so that a
  rule cannot rename the room out from under somebody by naming it as what it
  acts on -- and the form passed the room as both the thing being changed and
  the room it is in, which is exactly the shape that check refuses. A room is
  not inside itself. It blocked the description as well, and reached the
  worst possible place: a world with its rooms turned off opens as one plain
  room whose description says `edit room` gives this place a name.
* **`~` works on the building forms**, which it did not on any of them.
  Reported about `create room` and true of all twenty: a field is offered to
  a model only where the *form* declares who pays, §12 said `~` stays
  available throughout, and not one maker form said it -- so the key that
  exists to help somebody write a description reported that there was nothing
  to fill in, in the form most likely to want one.

  Written on each form it would have gone missing again, which is what had
  happened. So a form says who pays *or whoever opened it does*: one piece of
  code opens all of them, over a world that knows whose key it spends, and it
  says so once. Still opt-in either way -- a context with no sponsor fills
  nothing in -- and a sub-form inherits it, because a child context carries
  the data down. `~` spends the world's own key, which is the only thing on
  these forms that spends anything at all.
* **A thing made by hand can be worth having.** `world/makers/gearing.py`:
  what it grants, when that counts (worn, wielded, carried, present) and what
  condition the thing must be in first. One form, shared by `create item`,
  `edit item`, a rule's `create_object` and a room -- because `gear.py` is
  explicit that this is the whole of how armour, weapons and tools are worth
  anything, and a world that could make a sword and not a good one was
  missing the point of having them.

  A room is here for the reason `present` exists: its bonuses are for
  everybody standing in it and could not be anything else, so its form is
  told rather than asked. And an ordinary thing carries no empty map --
  `gear.bonuses` reads one as a claim to be worth having, and most things are
  ordinary.
* **An effect's form asks for everything the effect takes**, which it did
  not. Reported from play: a rule that made something could not say what
  *sort* of thing it was, so the sort was guessed from the head noun of
  whatever it was called -- a Wisp of Steam becomes a wisp, and every rule
  filed against the sort it was meant to be misses it.

  The cause is worth more than the symptom. §8.4 said effects were read out
  of `effects.VOCABULARY` so there would be no second list to keep level --
  but what that register carried was a line of *prose*, and prose drifts: it
  said `create_object` takes `why`, which nothing has ever read, and said
  nothing about `kind`, `takeable` or `states`, which it does. The menu was
  written from it and inherited the gap, and six other effects had it too.

  So the register now carries `fields` beside `takes`: the same fact in a
  shape a test can walk. Three tests hold it -- every field an effect takes
  is asked for, nothing is asked for that no effect takes, and the prose
  names everything the list does. A field left out on purpose goes in
  `NOT_ASKED` with its reason, so a gap is a decision somebody wrote down
  rather than one nobody saw. There is one: a redirect's `roles`.
* **A finished form closes, and stops calling itself unsaved.** It could not
  before: a maker's form had to stay open so a picker could take the value
  back, so every one of them said `after=STAY` and you had to quit a form
  whose whole job was already done -- and then answer "throw away what you
  have entered?" about a kind that was in the register. Asking somebody to
  confirm the loss of something that is not lost is worse than not asking,
  because it teaches them to answer yes unread. `Picked` learning to say
  "nobody was waiting" is what let both be true at once: with a picker
  waiting the value goes back and the form stays; with nobody waiting the
  form closes, and the draft is marked written rather than dirty.
* **A menu can no longer trap anybody, whatever breaks inside it.** The worst
  shape a bug in this game can take, and it took it. A menu's cmdset takes
  every line typed before any command sees it, so a form that raises while
  working out what it offers does not merely fail -- it holds the player with
  nothing that works: not `q`, because a choice field builds its list before
  it reads what was typed; not `@reload`, which never becomes a command; not
  disconnecting, because the menu is waiting on the way back in. The only way
  out was stopping the server from a shell, which is not something a player of
  somebody else's world can do. Three lines now make it impossible: `render`
  catches what breaks while drawing, `parse_input` catches what breaks while
  reading and closes the menu, and `q` is read before anything that could
  raise. A `Refuse` is still a refusal -- a form saying no is not a form
  breaking.
* **A listing that raises no longer takes the menu with it.** Found in play:
  `actions.vocabulary` answers a sorted *list* of verbs where four of the six
  registers answer a map, so the action picker raised the moment it was
  opened -- and because the field frame was already on the stack, every input
  after it hit the same wall and even `@reload` never reached a command.
  Caught at the one place a menu is *drawn* (`menus._choice_entries`), which
  is deliberately not the same place as the listing itself: guarding the
  listing too would have made the guard untestable, and the first version of
  this did exactly that and hid the bug from the test written for it.
* **Drawing a form is not enough to know its fields work.** A picker with no
  value yet shows "not set" without ever asking what it could be set to, so
  `EveryFormDraws` walked straight past a listing that could not run.
  `EveryChoiceCanBeOpened` walks *into* every choice field of every maker
  form, in an empty world and a furnished one, and does it again for each
  predicate, each effect type and each goal type -- which is what a player
  does and what the first test did not.
* **A bug in `guided` forms was found and fixed.** A form whose `items` is a
  function of the context builds a fresh `Field` every time it is asked, so
  "(2 of 5)" was looked up by identity against a different object: it gave up
  silently everywhere and raised in `open_menu`. `menus._step_of` matches by
  key. Every form in `world/makers` builds its items that way, because what
  they offer depends on what the world holds.
* **`listing_field`** joined the two engine additions as a caller of them: a
  list kept in a draft, with one form to add to it and an entry per member to
  take one out. A rule's conditions, a rule's effects, an action's roles, a
  kind's affordances, an NPC's traits and an errand's givers are all it.
* **A maker names the field the command line fills**, rather than the subject
  working it out as "the first required field". Same reason as the step count
  above: there is often no list of items to look in, and "first required"
  would silently become a different field the day one was added over it.
* **`settings confirmations` is generated from the table too**, which is a
  fifth reader of it. Every maker that deletes or forgets something asks
  first, §8 says every confirmation has a setting, and a hand-written list
  would have been missing one the day somebody added a maker -- leaving a
  confirmation nobody could turn off, which is the register not knowing about
  it rather than the player having chosen to keep it.

**Phase 2: the vocabulary.** Kinds and affordances, attributes, conditions and
groups, word folds (§11c), and `view term`. The sense and anchor pickers.
*Done when:* a world with no API key can be given a new kind, a new attribute
and a new pair of exclusive states from menus, and `view faults` has nothing to
say about any of them.

*Built.* `world/makers/vocabulary.py`, `world/folds.py` and
`commands/term_subject.py`. Where it differs:

* **Folds own the verb table now.** `rulesets._fold` wrote `verb_synonyms`
  directly; both halves live in `world/folds.py`, and `rulesets` and
  `verbs.canonical_verb` are callers. A noun fold reads through
  `naming.best_match` as another name the thing answers to, beside the aliases
  a conjured object already carries.
* **A picker may offer "type your own".** An affordance is any verb, and a
  closed list of two dozen would be the game deciding what a world may be
  about. `making.word_form` is the one-question form behind that entry.
* **`view term` shows what this world has done with the word too**, not only
  what the dictionaries say -- whether it is already a kind here, a verb, a
  condition, an attribute, or another word for one of them.

**Phase 3: actions and verbs.** `create action`, `reset action`, `create verb`,
`reset kind`; the dependant reporting in §6.4.
*Done when:* an action declared by hand is taken by the parser and bound the
same way a model-declared one is, and `reset kind` names what it will forget
before it forgets it.

*Built.* `world/makers/doing.py`, and `reset` as a fifth verb on the maker
table. Where it differs:

* **`reset action` is still `reset verb`**, which already existed and already
  said the right things. A second name for it would have been tidiness at the
  cost of a word players have learned.
* **`reset kind` drops the narrations written about things of that sort**, by
  the same `effects.forget_narrations` a modified object goes through. They
  were written about what the kind used to afford.
* **Finding what is of a kind was wrong and is fixed.** The `ai_world` tag is
  on rooms, not on the things in them, so a search by tag alone found the
  places and none of their contents -- the wrong half for a question about
  kinds. It walks the rooms' contents now.

**Phase 4: rules.** The rule form, the condition builder, the effect builder,
and the checks in §8.5. The biggest phase by a distance; worth splitting at the
condition builder if it runs long, since the condition builder is also what
§6.3's derived states and §9.3's goals need.
*Done when:* every rule in `world/rulesets/default.json` can be built through
the menus and comes out byte-equal to the seeded one.

That last criterion is the real test of this plan. The rulesets are hand-written
documents that say everything a world could say for itself; if the menus cannot
reproduce them, the menus are missing something.

*Built.* `world/makers/rules.py`. Where it differs:

* **Byte-equal was the wrong test and coverage is the right one.** A seeded
  rule carries an id, a `born` timestamp and a `source` mark that a rule
  somebody writes cannot and should not reproduce. What the criterion was
  really asking is whether the menus can *say* everything the documents say,
  and that is held by three tests instead: every effect in
  `effects.VOCABULARY`, every predicate in `conditions.PREDICATES`, and every
  goal type in `goals.CONDITION_TYPES` is reachable from a menu. A vocabulary
  entry no menu can reach is exactly the hole byte-equality was looking for,
  and these name it directly.
* **Two effect fields are asked under another name.** `exit` quits every menu,
  and `location` reads as a place rather than as a choice between two;
  `STORED_AS` maps them back on the way in.
* **The phase question shows firing order as it is answered**, which §8.4 asked
  for, and its three nudges read the rest of the rule -- which is what asking
  it last buys.

**Phase 5: contents.** Items, rooms, exits, people. The `thing_here` matcher.
*Done when:* a small world -- four rooms, a few items, one NPC -- can be built
end to end with no model, and playing it works.

*Built.* `world/makers/things.py`, and `subjects.reachable` / `thing_here`.
Where it differs:

* **`create npc` and `create person` are two commands, not one fork.** The
  generated one costs money and runs asynchronously; the hand-built one costs
  nothing and finishes at once, and folding them into one menu would have hidden
  that difference behind a submenu. Each one's help names the other.
* **A way out is a `way`**, for the reason in phase 1.
* **`modify_complaints` checks a thing being made, not only one being
  changed.** Its two rules -- a name says what a thing is and never its
  condition, a description may only ask for word lists this world keeps -- are
  just as true of a new thing, so the thing being made is given the shape the
  checker reads rather than the rules being written out a second time.

**Phase 6: quests.** The spec store, `offer_quest`, chains and repeats,
`quest_gen` refactored onto the same writer, and the pool offered to both
sides -- `quests.lookup_tools`, the `use_quest` answer, and the player's
`Picker` over existing specs.
*Done when:* an NPC built by hand offers a pre-written quest, it completes, a
non-repeatable one is not offered again, and a generated NPC asked for work in
a world that already holds a fitting errand hands that one out instead of
writing another.

*Built.* The spec store in `world/quests.py`, the `offer_quest` effect in
`world/effects.py`, `world/makers/errands.py`, and `use_quest` in
`world/quest_gen.py`. Where it differs:

* **`create quest` writes the rule that offers it, and says so.** The default
  is that greeting the giver asks; declining leaves the errand written and
  unoffered. The effect does all the deciding -- already done, too soon,
  something else first, hands full -- so the rule it writes can be one line and
  still be right.
* **A goal is written in the goal vocabulary**, not the condition vocabulary.
  They are different closed lists: `goals.satisfied` can only test its own, and
  a goal it cannot test would hang the errand for ever rather than fail it.
* **`greet` is declared if the world has not got it**, since the default rule
  is about being greeted.
* **Who asks and who is asked are resolved apart.** `effects._resolve` falls
  back from `name_role` to `role`, which for this one effect would make the
  giver and the taker the same person and turn the whole thing into a silent
  no-op. The giver defaults to what is being acted on -- greeting somebody
  offers their errand -- and an offer that cannot happen says why in the log.
* The last criterion is held by `use_quest` being offered and enumerating this
  world's specs; whether a model *prefers* it is a live test, not a free one.

**Phase 6a: what a world writes for itself.** Not in this plan, and needed by
it. `create world` plans zones, names a room, describes it, fills it with
things and puts somebody in it -- every one of which a hand-built world has to
undo before it can start, and pays for twice. So `world/permits.py`: five
things a model may be asked for (rooms, items, people, verbs, errands), three
answers each (whenever anything asks, only when a player goes looking, never),
and `Sponsor.will(making)` as the one question a generator asks. It is the
`future-plans.md` item about configuring what models may do, which turned out
to be a prerequisite rather than a successor.

*Built.* Where it differs from what that item said:

* **Five things, not "each type of thing".** Rooms, items, people, verbs and
  errands is what a generator can actually be pointed at. "Descriptions" and
  "names" are part of making one of the five, and a world that could have a
  room but not its description would have a nameless room rather than a saved
  call.
* **`asked` turns on a session**, not on the shape of the call. "A player's
  own action" means somebody is at the keyboard; a body left standing in a
  room is exactly the case the setting exists to stop.
* **The default is what the game already did.** Everything `always`, stored
  with the world's spec so `reset world` keeps a creator's decision, and no
  world in play changes because a register gained a default.
* **Rooms off means no model call at all.** `worldgen.first_room_by_hand`
  makes one plain room that says what to do next, and skips the zone plan,
  the naming call, the description call, the contents pass and the frontier.
  `ensure_frontier` also stops opening doors onto nothing: a world built by
  hand is not closed off by accident at the edge its builder stopped at.
* **It is not about characters thinking.** Turning people off stops new ones
  arriving; whoever is already there still talks. NPC autonomy is its own
  `future-plans.md` item and stays there.

**Phase 7 (separate plan): export and import.** A world as a document, over the
same maker table. Named here so phases 1 to 6 build for it; scoped when they
are done.

The flagship worlds in `future-plans.md` -- endless alchemy, the Taipan!-shaped
one, hunt the wumpus -- are the acceptance test for the whole thing and should
be built with it rather than after it. If one of them needs something the menus
cannot express, that is the finding.

---

## 16. Decisions

**Vocabulary is not deletable; rules, contents and quests are.** A trait or
state half the rules test cannot be removed without breaking them silently, and
suspending a rule is the honest alternative and already exists. §3.1.

**First answer still stands, with a named way out.** `edit kind` and
`edit action` change only what no cache key and no rule reads; `reset kind` and
`reset action` are separate, confirmed gestures that say what they invalidate,
beside `reset verb`, which already set this precedent deliberately. §6.4.

**Forms are written by hand beside the schemas, and a test holds them level.**
The schemas are shaped for what a provider will accept, not for what a person
can answer. §2.

**Candidates come from what is in reach, never a world search.** §5.

**Offering a quest is an effect.** Not a hook, not a hardcoded NPC behaviour.
§10.

**No form calls a model, and a test enforces it.** §12.

**Players do not add senses to WordNet.** The world-local invented sense
already exists and is called an anchored kind. §11d.

**The phase is asked, never inferred.** A phase says what *else* runs, not what
this rule does, so nothing in a rule's own content distinguishes instead from
carry-out or carry-out from after. It is asked in the second person, about the
consequence rather than the rulebook name, with the firing order shown as it is
answered. Endless alchemy needs all five. §8.4.

**`create room` asks for everything.** A room with no description is a room
somebody has to come back to. The cost of twenty of them is answered by word
lists, by copying an existing room, by the line editor and by `~` -- four tools
that already exist -- and not by asking for less. §9.2.

**One thing at a time; no bulk editing.** Making the same change to many things
is templating, and belongs with "objects from templates" in `future-plans.md`,
where the answer is that they were one thing to begin with. Reach still follows
containment, so "the coin in the chest" resolves. §5, §9.1.

**A quest spec belongs to the world, not its giver**, and survives it
unattached. The generator is shown the pool and may reuse a spec rather than
write one, which is "one vocabulary per world" applied to errands. Each giver
keeps its own way of asking, so reuse saves the testable half without
flattening the voices. §10.2, §10.3.

**The phase is asked last.** It is the one field about the rest of the rule:
its nudges have nothing to read until the conditions and effects exist, and the
firing order it shows cannot be drawn without the action and the scope. §8.

### Open questions

None outstanding. Two were settled in review and are recorded above: the phase
goes last in the form (§8), and a giver carries its own way of asking (§10.2).

What is deliberately left unscoped, and named so nobody mistakes it for an
oversight:

* **What a hand-built NPC does between quests.** Without a model it does not
  act. That is the AIML item in `future-plans.md` and a plan of its own; all
  this one adds is that such a character can still hand out an errand (§10).
* **Export and import**, phase 7, scoped separately once the maker table has
  proved itself against phases 1 to 6 (§15).
* **Bulk change**, which is templating and belongs with "objects from
  templates" (§5).
