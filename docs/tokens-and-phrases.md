# Development plan: tokens and phrases

Status: **all six phases built.** Six phases, §8. Where the
building turned up something the plan had wrong, the phase says so under *As
built* rather than the plan being quietly corrected.

Companion to `development-plan.md` (rulebooks) and `pronouns-and-ownership.md`.
The ground rules in §2 of `development-plan.md` are acceptance criteria here
too, unchanged.

**`future-plans.md` is the roadmap this plan is written against.** Protocol
work (MXP, GMCP, MSDP, MSP, the web client) is deliberately not in this plan.
What it does is choose shapes those items can use without a second pass over
the same code; §9 says which shapes and for whom.

The build sequence is §8. Decisions already taken are recorded in §10.

---

## 1. The change, on one page

Input got a grammar on purpose: `world/nounphrase.py`. Output has been growing
one by accretion. There are four ways of putting a variable into a sentence
today, and none of them knows about the others:

| Where | Spelling | Resolved |
|---|---|---|
| `events.render` | `{actor}`, `{direct's}`, `$pconj(verb, role)` | per viewer, at delivery |
| `lore.USER_TOKEN` | `<user>`, `{{user}}`, `$user` | per viewer, when put in a prompt |
| Evennia's funcparser, through `at_say` | `$you()`, `$conj()`, `$pron()` | per receiver, by Evennia |
| `memory.describe_event`, `attempt._remember`, arrival and NPC movement | f-strings | once, when written |

And what English knows about words is spread across as many places:
`events._stance` and `events._base_form` over Evennia's conjugator,
`events.plain_name` choosing "the", `referents.is_plural` over
`lexicon.lemma`, and Evennia's `get_numbered_name` over `inflect`.

`basic-principles.md` is explicit about this: "If multiple systems are growing
the same subsystem inside themselves, that system should be pulled out and made
generic for everything to share." So the work is six things:

1. **One renderer** (`world/tokens.py`). A token resolves to a *phrase* -- words
   plus what is grammatically true of them plus what they refer to -- rather
   than to a string. The four spellings become one grammar. Output is a
   sequence of spans, joined into text at the last moment.
2. **One English module** (`world/english.py`). Articles, plurals, counts,
   agreement, and **past tense**, which nothing in the game produces today and
   which memory (phase 6) needs. Layered over the object's own sense, WordNet,
   Evennia's conjugator and `inflect`, each optional.
3. **World token lists.** Named, weighted, recursive lists of alternatives, the
   shape Tracery made familiar. A choice is stored **as a fact** wherever the
   world has a word for it, and where it lives is the token's **scope**. Models
   and players declare lists through one door.
4. **The lexicons as token sources.** WordNet hyponyms and meronyms, ConceptNet
   relations: variety without a model call, which is what a world with no
   model needs most.
5. **Recognition.** The reverse direction: names found in speech become
   annotations on memories, distinguishing who was *addressed* from who was
   *mentioned*.
6. **Memory shape.** Episodes stored in past tense, rendered from the event
   record, with state claims kept out of them; recalled memories re-rendered
   with today's names and shown to NPCs in order, with their age.

---

## 2. Why a small grammar and not a library

### 2.1 What was looked at

* **Tracery** (Kate Compton; a small Python port exists). Named lists of
  alternatives, nested references, `.a` and `.s` modifiers, and a save action
  -- `[hero:#name#]` -- that is exactly a sticky choice. Models have read a
  great many Tracery grammars and write the JSON fluently. **The data shape is
  borrowed; the dependency is not.** Its English is suffix rules, it has no
  notion of a viewer, a fact, or where a choice is kept, and its expansion core
  is a few hundred lines that would all be replaced.
* **rmutt and the Dada Engine**, both on the inspiration list. Not Python, but
  worth reading for what Tracery lacks: variable binding and lexical scope,
  which §3.4 needs for recursion.
* **Evennia's `FuncParser`.** Evaluated as the *parser* for phase 1, §8. The
  reason `events.py` gives for not using `msg_contents` is `objects.py`
  building its parser from the fixed `ACTOR_STANCE_CALLABLES` dict, and
  `{key}` going through `get_display_name`. Neither applies to a `FuncParser`
  instance of our own. What it would give: nesting with a guard
  (`FUNCPARSER_MAX_NESTING`, 20), escaping, arguments and keyword arguments,
  and the `$name(...)` spelling `$pconj` already uses.
* **Jinja2** (installed, as somebody else's dependency). **Rejected.** It is a
  programming language with loops, conditionals and attribute access to Python
  objects. Letting a model or a player author it is code from inside the game,
  which `basic-principles.md` forbids. Its sandbox has a history of escapes.
  See §10.9.
* **NLTK's CFG generator** enumerates expansions in order rather than choosing
  by weight. Nothing here needs every sentence a grammar can make.
* **SimpleNLG** is the name for realising whole sentences from structure. It is
  Java first. Phase 2 covers the part of it this game needs.

### 2.2 Where the difficulty actually is

Expansion is easy. None of the libraries helps with the hard parts, because
they are all about this world:

* **Agreement after expansion.** "a {fruit}" is "a apple" and "{count}
  {animal}" is "three sheeps" unless what a token resolves to carries its
  number and how it begins. `$pconj` already reads a participant's number
  through `pronoun_forms`. That generalises.
* **Per-viewer naming.** The centering rule in `events.Naming` decides "she" or
  "Jessica" per reader. A token system that flattens to strings before it
  knows the reader cannot do that.
* **Grounding.** "Text should never exist if it will always be exclusively
  decoration." A random word that nothing can read is exactly that.
* **Where a choice lives**, and what happens when the world changes underneath
  it (§3.2).

---

## 3. What is already here to build on

| Module | What it gives this plan |
|---|---|
| `events.py` | `Event`, the roles, `Naming` and the centering rule, `repair`, `render`, delivery |
| `lore.py` | `USER_TOKEN` and `user_name` -- the one per-viewer token outside narration |
| `pronouns.py` | `register`/`clean`/`vocabulary_block`: the shape every register here copies |
| `vocabulary.py` | `REGISTERS`, `permit`, and the collision report |
| `verbs.py` | exclusive state groups (`NEW_GROUP`), `register_group`, `register_state`, `apply_states`, `states` |
| `lexicon.py` | lemmas, senses, ancestors, and the missing-corpus contract |
| `commonsense.py` | `forward`, `backward`, `parts_of`, `kinds_of`, `can_be_done_to` |
| `naming.py` | `best_match`, `resemblance` (key and aliases) |
| `referents.py` | what each reader was last told |
| `memory.py` | `remember(about=, metadata=)`, `_annotate`, `note_fact`, triples with `supersede`, `recall_for_cues` |
| `npc_gen.py` | `_recall_cues`, `_memory_inputs`, `format_memories`, `notify_npcs` |
| `tests/fixtures/export.py` | `REGISTERS`, which a new world attribute must join |

Measured while writing this plan, and worth keeping:

* **Evennia's present tense is fine.** `verb_actor_stance_components` agrees
  invented and irregular verbs: airlock/airlocks, pry/pries, ferry/ferries,
  be/is/are.
* **Evennia's past tense is good and incomplete.** `verb_past` and
  `verb_past_participle` give went/gone, took/taken, gave/given, held/held and
  stopped. They return `""` for any verb not in Evennia's table: airlock,
  teleport, holster, reboot. They also prefer "lighted" to "lit".
* **`inflect` is where the plural errors are.** Glasses becomes "glassess",
  "a glasses", "a scissors", "waters", "Raldors".
* **WordNet cannot inflect** -- `morphy` runs from an inflected form to its
  base -- but its exception tables hold 2,050 noun and 2,401 verb irregulars.
  Inverted they give hold→held and light→lit. They cannot tell a past from a
  participle: go gives both went and gone.
* **WordNet's lexical file is a weak mass-noun signal.** Water and sand are
  `noun.substance`. Bread, soup and rice are `noun.food`, and so is apple.
  Gold's first sense is `noun.possession`. Only the sense an object was
  actually filed under can be trusted, and only for `noun.substance`.
* **mnemosyne's full-text index does not stem.** `fts_episodes` uses FTS5's
  default tokenizer, so a stored "picked" does not match "pick" and "swords"
  does not match "sword". Stored text shape matters (§7.2).
* **mnemosyne's recall rows carry a `timestamp`**, and `_recall_sync` throws
  away everything but `content`.
* **Annotation kinds are not enforced.** `ANNOTATION_KINDS` lists four, but the
  table has no constraint on `kind`. The `dbref` annotations already written
  are stored, and an `addressed` kind would be too.
* **NPC speech splices model text into a template.** `npcs.py` builds
  `'{actor} $pconj(say), "|w' + msg + '|n"'`. `_aloud`'s docstring notes that
  an unrecognised slot is left alone. A *recognised* one is not: an NPC whose
  words contain `{target}` or `$pconj(...)` has them filled. Fixed in phase 1
  (§4.5).

---

## 4. The grammar

### 4.1 One spelling, the one already stored

Every narration template cached in every world is already written
`{actor} $pconj(hand) {target} {direct}.`, and `verb_gen`'s prompt already
teaches models to write it. So that is the grammar:

```
text     := ( literal | escape | slot | call )*
slot     := "{" name ( "." field )* "}" possessive?
          | "{" name ( "." field )* "'s}"
call     := "$" name "(" arguments? ")"
arguments:= argument ( "," argument )*        ; an argument may itself be text
argument := ( key "=" )? text
escape   := "\{" | "\$"
```

* A **slot** takes the token's defaults. A **call** passes arguments, and is
  how a use site overrides a default: `{color}` and `$pick(color, scope=room)`
  are the same token.
* **Fields are a closed table** per token, never attribute access:
  `{direct.name}`, `{direct.subject}`, `{direct.owner}`,
  `{self.state.color}`, `{self.trait.stamina}`. The `state.` and `trait.`
  prefixes are explicit because a state group and a trait are separate
  namespaces.
* **`<user>`, `{{user}}` and `$user` are aliases**, normalised to `{user}` when
  text is stored and still accepted on read. The world wizard can go on
  teaching `<user>`. Worlds already written keep working.
* **No conditionals and no loops, ever** (§10.7). "Damp if wet" is
  `{self.state.wetness}` or a rule.

### 4.2 A phrase, not a string

Resolving a token gives a `Phrase`:

```python
Phrase(text, plural=False, person=3, countable=True, proper=False,
       ref=None, sense="", facts=())
```

* `ref` is the object, when the words are about one.
* `sense` is its WordNet id, when known.
* `facts` are what resolving it wrote (§5.2).

Every English decision in phase 2 reads these fields instead of re-deriving
them from text.

A rendering is a **sequence of spans**: literal text and phrases, in order.
`str()` joins them. Everything that displays to a player today gets exactly
that string, so phase 1 changes nothing anybody sees.

The spans are kept because three things want to know which words were which
object:
* recognition and memory annotations, in this plan;
* MXP links and GMCP ids, later;
* re-rendering a memory with today's names, in phase 6.

### 4.3 The render context

One object, made per rendering:

| Field | Meaning |
|---|---|
| `viewer` | who is reading; `None` is nobody, which is what a model and a memory get today |
| `event` | the roles mapping, when there is one |
| `self` | the object the text belongs to -- a description's owner |
| `world_root` | whose registers apply |
| `tense` | `present` or `past` |
| `purpose` | `display`, `prompt` or `memory` |

`purpose` does what `viewer=None` does implicitly now, and says so:
* **`display`** runs the centering rule and writes the referents table;
* **`prompt`** names everybody and writes nothing;
* **`memory`** also names everybody -- `pronouns-and-ownership.md` §7.1 says why
  a memory must hold names -- and renders past tense.

**Tense is context, not template.** The template
`{actor} $pconj(hand) {target} {direct}.` renders "Raldor hands Jessica the
sword." for a player and "Raldor handed Jessica the sword." for a memory. No
narration template is rewritten for past tense, and every template a world
has already learned becomes a past-tense memory for nothing.

### 4.4 Where tokens come from

* **Built-in.** Python in this repository, and reserved: `actor`, `direct`,
  `target`, `container`, `source`, `instrument` (`events.RANK`), `self`,
  `user`, `viewer`, `here`, `world`, and the calls `pconj`, `an`, `the`,
  `plural`, `count` and `pick`. A world can never declare a list with one of
  these names.
* **World.** Data in the world's register, declared by a model or a player
  (§5).
* **Lexicon.** Built-in calls over WordNet and ConceptNet (§6).
* **Plugin.** A seam only: `tokens.provide(name, resolver, scope=..., fields=...)`,
  reserved like a built-in once provided. The loader is the "affect plugins"
  item in `future-plans.md`. `tokens.requires(world_root)` lists the
  non-built-in tokens a world's text uses, so a future world export can say
  what it needs.

### 4.5 What is expanded, and what never is

**Author text expands; typed text and quoted text never do.**

* Author text is descriptions, narration templates, rule text and list entries.
* Typed text is player speech, poses, emotes, names a player chose, and
  anything a player typed into a command.
* Quoted text is the words inside an NPC's `say`.

Evennia ships with `FUNCPARSER_PARSE_OUTGOING_MESSAGES_ENABLED = False` for the
same reason. Without it, "Raldor gives you 1000 gold" is something anybody can
say.

The mechanism is structural, not escaping: quoted words enter a rendering as a
**literal span**, never as template text. `_aloud`'s template becomes
`{actor} $pconj(say), {quote}` with the words bound as a literal, which closes
the splice noted in §3. Names are literal for the same reason: a model can name
an NPC `{actor}`.

### 4.6 Failure

A world or plugin token that cannot resolve renders its declared fallback, or
nothing. It is logged and never shown as raw braces. This covers a deleted
list, a plugin that is not installed, and a corpus that is missing.

An unfilled *role* slot keeps today's behaviour -- left as written and caught by
the structural tests -- because that is a bug in a template, not a world that
lacks something.

---

## 5. World lists, choices and scope

### 5.1 A list

Stored on the world root as `db.token_lists`, added to `export.REGISTERS`:

```json
"color": {
  "means": "the colour of a small painted thing",
  "scope": "object",
  "group": "color",
  "fallback": "grey",
  "entries": [
    {"text": "blue",  "weight": 3, "sets": {"states": ["blue"]}},
    {"text": "pink",               "sets": {"states": ["pink"]}},
    {"text": "yellow",             "sets": {"states": ["yellow"]}}
  ]
},
"tavern_name": {
  "means": "what a roadside inn is called",
  "scope": "object",
  "entries": [
    {"text": "The {animal} and {object}"},
    {"text": "The {adjective} {animal}"}
  ]
}
```

**Ground rule 5 stands.** The rule is that every slot a model fills is a closed
identifier -- "except two prose fields that exist to be read by people". An
entry's `text` is prose of the same standing as a description, which is already
one of them. Everything machine-read in an entry is a closed identifier:
* `sets` names states, traits and groups;
* `weight` is a number;
* `scope` is one of five words.

### 5.2 A choice is a fact where the world has a word for it

The design this replaces cached the rendered text: "This is a blue ball",
frozen. That lies the moment a rule paints the ball red.
`objects.get_display_desc` already documents the same failure for a bottle
that has been drunk, and deals with it by reading state under the text rather
than writing it into it. This does the same thing from the other side:

* **`color` is an exclusive state group**, registered through
  `verbs.register_group`. Picking `blue` calls `verbs.apply_states` on the
  ball.
* **The text keeps the token.** `{color}` on something that already has a
  state in group `color` *reads* that state and picks nothing. So paint
  changes the description with no rule saying so. A rule can require `blue`,
  and an NPC can want the blue ball.
* **Traits** are set the same way.
* **Kinds and affordances only at creation** (§5.5). Kinds feed the rule cache
  key (`lexicon.py`: "a cache key that drifts [...] silently stops matching"),
  so a list may not change what something *is* after it exists.
* **Decoration is allowed and still recorded.** An entry with no `sets` stores
  its choice in `db.token_choices` on whatever holds its scope. It stays the
  same on every look, and can be promoted to a fact later.

Nothing rendered is ever cached. Rendering is a few dict reads. The only thing
kept is state, which already persists, exports and is read by rules.

### 5.3 Scope is where the choice lives

| Scope | Kept on | For |
|---|---|---|
| `render` | nothing | built-ins: names, pronouns, `{user}`, live state reads |
| `object` | the object the text belongs to | the ball's colour |
| `room` | the room | the smell of this alley |
| `world` | the world root | the name of the empire |
| `viewer` | the object, keyed by viewer | a rumour each player hears differently, and always the same way |

Defaults: built-ins are `render` and world lists are `object`. A use site may
override with a call: `$pick(color, scope=room)`.

A `period` scope -- the sky is the same all in-game day -- is wanted and left
out (§12). It needs a decision about what a period is that nothing else here
needs made.

### 5.4 Identity of a choice

**One choice per token per holder, unless labelled.** "A {color} ball with
{color} stripes" is one colour. With facts that is forced -- the group is
exclusive -- and decoration follows the same rule so the two never disagree.
`$pick(color, as=stripes)` is a second, separate choice.

**A reference inside an entry is a new slot, nested under the one being
expanded.** This is rmutt's lexical scope. So a list may refer to itself --
`{color}` inside `color` is a second choice, not the first looked up again --
and two `{animal}`s inside one tavern name agree with each other without
agreeing with an `{animal}` elsewhere on the same object.

**Only the outermost slot writes facts.** A nested `color` inside `color`
would otherwise set two members of an exclusive group. Nested slots are
decoration.

**Choices are deterministic.** Each pick is seeded from (world, holder, slot
path), which ground rule 7 asks for. The same world gives the same picks,
which is what tests and soak replays need.

### 5.5 Resolved when the thing is made

**Object-scoped tokens resolve when the object is created**, not when somebody
first looks at it. The creation points are `clothing.create`, room creation in
`worldgen`, and NPC spawning.

Lazy resolution would let a model read a raw `{color}` before any player looks,
and invent green. `item_gen`, `worldgen` and `npc_gen` all read `db.desc` into
prompts. Lazy resolution stays as the fallback for text written afterwards, by
an edit or by a rule.

Stored text keeps its tokens, so facts go on rendering live. Everything that
puts a description in front of a model goes through one accessor,
`tokens.text_of(obj, "desc", purpose="prompt")`, instead of reading `db.desc`
directly (§11.2).

### 5.6 Registering

`tokens.register(world_root, name, declared)` is the one door, and follows
`pronouns.register` exactly:

* **`clean`** refuses an incomplete declaration: no entries, no `means`, a
  `scope` that is not one of the five, or a `sets` naming an unknown state or
  trait.
* **Reserved names are refused.**
* **`vocabulary.permit(world_root, name, "token")`**, with `token` added to
  `vocabulary.REGISTERS`, so a list called `blue` beside a state `blue` is
  reported like every other collision.
* **Near-duplicates fold** onto a list already there. The return value is the
  name in use, and every caller must use it.
* **A productivity check.** A list is accepted only if at least one entry can
  finish expanding -- through literals, built-ins and lists that can themselves
  finish. This is the standard CFG check, a fixed point over the world's
  lists. `color: ["{color}"]` is refused when it is declared, not discovered
  in play. Removing a list re-runs the check for the lists that use it.
* **A render-time depth cap** still exists, for whatever a check cannot see.

### 5.7 Who declares lists

* **Generators** get a `new_token_lists` field in their reply, beside the
  `new_states` and `new_traits` that `verb_gen` and `rule_gen` already use.
  They get `tokens.vocabulary_block(world_root, for_kinds=...)` beside
  `traits.vocabulary_block`. States a list's `sets` names are registered from
  the same reply first.
* **The block is filtered.** A list may carry `for`, a list of kinds (closed
  identifiers, ground rule 6). The block shows the lists for the kinds in
  play, capped. A world's lists will outgrow a prompt long before its states
  do.
* **Players** get a `tokens` command, shaped like `pronouns`: list, show one,
  try a rendering, and for whoever may run `worldedit`, add and remove. The
  open-sandbox principle wants every list inspectable, and "no LLM" world
  building wants them writable by hand.
* **Tool calls wait.** `llm.call` supports tools and NPC reactions use them,
  but the generators are single-shot JSON. The reply field plus the block *is*
  a "list and create tokens" tool in this codebase's idiom. A real tool arrives
  when a generator gets a tool loop (§10.10), which is recorded in
  `future-plans.md`.

---

## 6. The lexicons as token sources

Built-in calls. They pick, so like a list they default to `object` scope
rather than `render`:

| Call | Source | Gives |
|---|---|---|
| `$hyponym(sword.n.01)` | WordNet hyponyms | cutlass, rapier, broadsword |
| `$part_of(ship.n.01)` | WordNet part meronyms | a part of the thing |
| `$found_at(galley)` | ConceptNet `AtLocation`, backward | what is lying about in a galley |
| `$used_for(cooking)` | ConceptNet `UsedFor`, backward | a thing for the job |
| `$kind_of(word)` | `commonsense.kinds_of` | what somebody said it is |

* **Every call takes `else=`**, a fallback used when the corpus is missing or
  gives nothing. Ground rule 2: "a missing dictionary makes the world slightly
  clumsier. It must never make the world impossible."
* **ConceptNet is advisory, as everywhere else.** Its answers are filtered
  before use: a known head noun (`lexicon.head_noun`), at most three words,
  not a person. What passes is decoration unless the object is being created,
  in which case a WordNet hyponym may become its kind (§5.5).
* **Deterministic** by the same seeding as §5.4.
* **What it is for:** `future-plans.md` wants worlds that run with no model at
  all, and templated objects that do not need a call. A room kind whose
  contents list is `$found_at(galley)` is a different galley each time for
  nothing.

---

## 7. English

`world/english.py`. Pure functions over words, optionally an object. Every
layer is optional, and each answers neutrally when its corpus is missing.

### 7.1 Layers, in the order asked

1. **The object itself.** A person or a proper name takes no article and no
   plural. The sense it was filed under -- `clothing.create` makes the chosen
   sense the primary kind -- is read for `noun.substance`, which means mass: "some
   water", never "waters".
2. **Already plural.** `lexicon.lemma(word) != word` -- glasses, scissors, teeth
   -- takes no second plural and no "a". This is `referents.is_plural`'s test,
   moved here.
3. **WordNet's exception tables, inverted.** Irregular plurals, and irregular
   past forms where the table gives *one* form (hold→held, light→lit). Where it
   gives two (go→went and gone) the table cannot say which is which, and the
   next layer decides.
4. **Evennia's conjugator.** Present-tense agreement as today. Past and
   participle where its table knows the verb.
5. **`inflect`.** Plurals of what nobody above knows, "X of Y" head-first
   (bottles of soju), a/an by sound, numbers to words.
6. **Suffix rules**, last, for verbs nobody knows: airlocked, teleported,
   holstered, rebooted.

### 7.2 Functions

* `article(phrase, definite=False)` -- "a", "an", "some", "the", or nothing.
* `plural(phrase)`, `count(n, phrase)` -- "a coin", "three coins", "some
  water".
* `conjugate(verb, subject_phrase, tense, reader_is_subject)` -- only the first
  word, as `events.conjugate` does now. "Be" agrees in the past (was/were),
  which Evennia's `verb_past("be")`, "were", does not.
* `base_form(verb)` -- `events._base_form` and `_base_guesses`, moved.
* `is_plural(word)` -- moved from `referents`, which keeps calling it.

`get_numbered_name` is overridden on the object typeclass to call
`english.count`, so inventories and room contents stop saying "a glasses".

Food nouns stay count nouns (§3: `noun.food` covers apple and bread alike).
Getting "some bread" right needs a kind to declare itself mass, and that is
left out (§12).

---

## 8. Phases

Dependencies: 1 before everything; 2 before 3 and 6; 3 before 4; 5 before 6.
Each phase lands something testable, and nothing is half-migrated across a
boundary.

### Phase 1 -- one renderer

**First day: the `FuncParser` spike.** The question is whether a callable's
result can reach the renderer as a `Phrase` when the call sits inside other
text, or only as a string. If only as a string, write the parser: §4.1 is two
productions. Keep Evennia's spelling either way.

*Spike result: only as a string, so the parser is ours.* Measured against
Evennia 6.1.0:

* **Plain text forces a string.** `parse` sets `return_str = True` the moment
  it reads a character outside a call, and joins every result with `str()`.
  `"{actor} $pconj(hand) {target}."` with a callable returning a `Phrase`
  comes back as the string `"{actor} hands {target}."`. The object survives
  only when the call is the whole string.
* **A workaround exists and was not taken.** A callable can append its
  `Phrase` to a side list passed as a reserved keyword argument and return a
  placeholder, which the caller splits back into spans. That works for flat
  calls, keyword arguments included. But a nested call's result reaches the
  outer call as the placeholder string, and `{slot}` needs a second pass of
  our own anyway: two parsers, joined by a hack.
* **What is kept from it** is behaviour, copied and tested:
  * `\$` escapes a call;
  * an unknown call (`$nope(x)`) or an unclosed one (`$pconj(hand`) is left as
    written;
  * a `$` not followed by a letter or underscore (`$5`) is literal;
  * a double-quoted argument may contain commas, and is taken as written;
  * a comma inside braces, brackets or parentheses does not split an argument
    (an unquoted argument is otherwise read as a template of its own, so a
    slot or a call inside one still works).
* **Speed** was not the reason: 5.8 µs a parse against 0.3 µs for the current
  regex, which is nothing beside a network write.

Then:
* `world/tokens.py`: parser, `Phrase`, spans, the render context (§4.3), the
  built-in resolvers for roles, possessives, `$pconj`, `{user}` and `self`
  fields, reserved names, escapes, fallbacks.
* **`events.render` becomes a caller.** `Naming` and the centering rule stay in
  `events.py` -- they decide pronouns -- and are what the role resolver asks.
* **`lore.USER_TOKEN` becomes an alias.**
* **Quoted and typed text become literal spans (§4.5).** This covers `_aloud`
  and every `npcs.py` template that concatenates a model's words or a name.
* **`Event` keeps its narration apart from its effect lines.** Today
  `attempt` joins them into `room_template`. Phase 6 needs them apart, and
  keeping them apart changes nothing that is displayed.

**No behaviour change.** Acceptance:
* `test_centering`, `test_events` and the lore tests pass unchanged;
* a grammar table of templates and renderings;
* an injection table: an NPC and a player each saying `{actor}`,
  `$pconj(die)` and `<user>`, which all render literally;
* spans carry refs.

No world reset.

*As built* (`world/tokens.py`, `tests/test_tokens.py`). Settled in the
building:

* **Aliases are accepted on read and not rewritten on store.** §4.1 says
  `<user>` and friends are normalised when text is stored. `parse` normalises
  all three spellings before reading, which is all a world needs. Rewriting
  what an author typed would change stored text in the phase that promised no
  behaviour change, and would show them `{user}` in `worldedit` where they
  wrote `<user>`.

  At the time of building, what eats a brace of `{{user}}` on its way to the
  screen had not been found. It is the ANSI colour escape in Evennia's editor:
  there `{{` is the escape for writing a single brace among colour and
  formatting codes. So only the doubled spelling displays wrongly; `{user}`
  and `<user>` display as typed, and rewriting on store is safe if it is ever
  wanted.
* **Effect lines are quotes named `_effect0`, `_effect1` and so on.**
  `Event.template()` puts them after the repaired narration, and
  `Event.quoted()` binds them. Every site that rendered
  `repair(event.room_template)` renders `event.template()` now. One behaviour
  did change, and it was a bug: an effect line with no narration in front of
  it was repaired as a fragment and read "Jessica a lamp is now here."
* **Quotes win over roles**, then roles, then the built-ins, then plugins.
  The splices that became quotes: an NPC's `say`; its request aloud; the quest
  giver and title when accepting, declining and abandoning; the effect line
  after "destroys something"; and clothing's "covering ..." tail, which named
  garments a model had named.
* **An NPC's emote stays template text.** It is narration the model wrote
  about its own character, the same standing as a cached room template, and
  `repair` needs to read it to wrap its verb. Its only bound role is the
  actor.
* **`{viewer}`, `{here}` and `{world}` are built** as well as `{user}` and
  `{self}`: `here` is the event's room title and `world` is `lore.title`.
* **The field table** is `name`, the five pronoun forms, `state.<group>`,
  `trait.<slug>` and `owner`. The reader's own pronoun forms are second
  person. A field not in the table leaves the slot as written, so
  `{direct.db.api_key}` renders as itself.
* **`provide(name, resolver, call=False)` and `withdraw(name)`** are the plugin
  seam. `scope` and `fields` from §4.4 arrive with phase 3, when there is
  anything to scope.
* **`purpose` is set but read by nothing yet.** `events.render` passes
  `display` for a reader and `prompt` for nobody, and the centering rule still
  decides on its own whether the reader is somebody.
* **Tense is carried and not used.** `$pconj` conjugates the present only until
  phase 2.

### Phase 2 -- English

* `world/english.py` as §7.
* `events._stance`, `_base_form`, `_base_guesses` and `referents.is_plural`'s
  body move into it.
* `get_numbered_name` is routed through `english.count`.
* **`tense=past` works in rendering** and is tested, though nothing stores it
  yet.

Acceptance is a word table built from §3's measurements:
* glasses, scissors, water, Raldor and teeth for nouns;
* airlock, teleport, holster, reboot, light, go, be and have for verbs;
* every row with and without WordNet.

The narration tests pass unchanged. No world reset.

*As built* (`world/english.py`, `tests/test_english.py`). Settled in the
building:

* **WordNet's verb exceptions come after Evennia, not before.** §7.1 put the
  tables third, taking a single listed form as the past. The rule fails on
  "sow", which the table files with "sown" alone because its past is regular:
  "she sown". But Evennia's table lacks 158 of the 1,392 verbs WordNet lists
  irregular forms for -- bind, bear, baby-sit, co-star -- so the tables are
  consulted only when Evennia has nothing. Where they list several forms,
  those ending "n" or "ne" are set aside as participles: bear gives "bore".
  "light" stays "lighted", which is Evennia's answer and English.
* **WordNet's noun exceptions are not used.** `inflect` already knows every
  irregular plural the table does, and the table says fish becomes "fishes".
* **`base_form` asks Evennia's infinitive first.** The suffix guesses alone
  answered "i" for "is", and `repair` had been turning "{actor} is tired" into
  a template that told its actor "You i tired". It gives `$pconj(be)` now.
  "{actor} has" is "have" the same way.
* **Number and article are read from the head of a phrase**, the last word
  before "of": "a pair of boots", "three pairs of boots". `referents` keeps
  asking about the last word, because a pile of coins is "them" to somebody
  typing.
* **`$an`, `$the`, `$plural` and `$count` are built** on words rather than
  things. An argument arrives as text, so they cannot know that "water" is
  stuff; a slot chooses its own article from the thing it names.
* **`get_numbered_name` is overridden on `ObjectParent`.** Somebody is
  "Jessica", stuff is "some water" whatever the count, and the plural aliases
  are registered as Evennia registers them. A name containing colour codes is
  handed back to Evennia. At a count of one the alias registered is "a
  sword"; Evennia also registered "one sword".
* **Known gaps, measured and left:** "scissors" is not detected as plural,
  because WordNet files it as its own headword; the last-word test in
  `referents` calls "physics" and "species" plural; `inflect` writes "a
  8-ball"; a two-syllable verb that should double its last letter
  ("hotswapped") does not.
* **Found, not fixed:** `repair` wraps the word after `{actor's}` as well as
  after `{actor}`, so "{actor's} boots" becomes `$pconj(boot)` and tells the
  actor "your boot". It was already doing this before phase 1.
* **Found and fixed, during phase 5: a named they/them character took a
  plural verb.** Agreement read the pronoun set whatever the subject was
  called, so "Jessica hand Britney the sword" -- and `test_centering` asserted
  it. A verb now agrees with the words its subject was given: `Naming` records
  whether it named or pronominalised each participant, and `$pconj` asks it
  (`Naming.plural_for`, `events.subject_plural`). "They hand", "Jessica
  hands". A thing's number is still its name's -- "the coins scatter" -- and a
  subject the sentence has not yet named is taken as named.

### Phase 3 -- world lists, facts and scope

* `db.token_lists`, `db.token_choices`.
* `tokens.register`, `clean`, fold, reserved names, the productivity check.
* `token` added to `vocabulary.REGISTERS`, and `token_lists` added to
  `export.REGISTERS`.
* The five scopes, one-choice-per-holder, nested slots, weights and seeded
  picks (§5.3, §5.4).
* **Facts** through `register_group`, `apply_states` and traits. Kinds and
  affordances only at creation.
* **Eager resolution** at the three creation points. Every prompt read of a
  description moved to `tokens.text_of`.
* `new_token_lists` in the generator replies, and `vocabulary_block`.
* The `tokens` command, and its help entry.

Acceptance is the ball, end to end:
* **Creation:** created from "This is a {color} ball.", it is in state `blue`
  and a look says blue.
* **Change:** a rule applying `red` makes the next look say red.
* **Stability:** a decoration pick is identical across looks and across
  viewers; a `viewer` pick differs between two viewers and is stable for each.
* **Registration:** `color: ["{color}"]` is refused; a self-referring list with
  a terminal entry expands and stops; a list named `actor` is refused; a list
  named after a state is reported.
* **Prompts:** a model prompt built from the ball's description contains no
  braces.

No world reset: new attributes only.

*As built* (`world/token_lists.py`, `commands/token_cmds.py`,
`tests/test_token_lists.py`). Settled in the building:

* **Lists are their own module.** §5.6 named the door `tokens.register`. It is
  `token_lists.register_many`, with `register` for one list, `declare` for a
  generator's reply and `unregister`, because `tokens` is the grammar and a
  world's register is a different job. `tokens` asks `token_lists.resolve` for
  any slot that is not a quote, a role or a built-in, and `$pick` goes to the
  same place.
* **A reference nobody answers is refused as well as a list that cannot
  finish.** §5.6 had only the productivity check. But a list whose entry says
  `{beast}` when no `beast` list exists would show its braces for ever, so the
  references are checked over everything the world keeps plus everything in
  the same batch. Lists declared together may name each other.
* **The fold is exact or singular.** `smells` folds onto `smell` through the
  lemma; nothing looser, because a list's name is typed into text and a fold
  that surprised whoever typed it would be worse than a second list.
* **Facts are states and traits, and nothing else.** §5.2 allowed kinds and
  affordances at creation. `clothing.create` settles an object's kinds before
  the object exists, a kind is a rule cache key, and an affordance belongs to
  a kind rather than to one thing -- so a list has no safe moment to change
  either.
* **A list with a group declares its states; a list without one may only name
  states the world keeps.** An unknown state in a grouped list is registered
  into that group, as a state declared anywhere else would be. A trait must
  already be kept, because a trait has a type and bounds and a word in a list
  says neither. Traits are set only on people.
* **The state is read before the remembered word.** A grouped list on a thing
  already in one of its states renders that entry, or the state's own word if
  no entry sets it -- which is how paint reads "red". If a choice was made and
  the state has since been taken away, the list renders its fallback or
  nothing, rather than a colour the thing no longer is.
* **Only object, room and world scopes write facts.** A choice made once per
  viewer cannot put one thing in two states, and one made every render has
  nowhere to stay.
* **Two references in one entry share a choice** because they share a path:
  "The {beast} and {beast}" is one animal twice. Past a depth of eight, only
  entries that name no other list are chosen from.
* **Choices are made at creation in three places and remade in two.**
  `clothing.create` covers items, clothes and room contents; `_create_room`
  declares the room's lists once the world exists -- the first room *is* the
  world -- and settles them; the NPC spawn settles the body. `modify_object`
  and `modify_room` settle again after rewriting a description. A viewer-scoped
  choice is left for whoever looks.
* **Every prompt read of a description goes through `tokens.text_of`**:
  `item_gen`, `npc_gen`, `verb_gen` and `worldgen`, eleven sites in all. A
  structural test fails on any `.db.desc` read in `world/` outside `tokens`.
  Looks render through `ObjectParent.get_display_desc`, which covers objects,
  rooms and NPCs, and `Character.get_display_desc`.
* **Three generators may declare lists**: items, NPCs and room descriptions.
  Each is shown `token_lists.vocabulary_block` in its user message, with the
  instructions for `new_token_lists` in the block rather than in a system
  prompt -- ordered by `for` kinds: nothing for an item, `person` for an NPC,
  the room type for a room. The contents and clothing passes, and the rule and
  verb generators, declare none.
* **`tokens` lists, shows, tries, adds and removes.** Adding and removing is for
  the world's creator or a superuser, the line `worldedit` draws. `tokens add`
  makes decoration only; a list of states comes from a generator for now.
  Lists are `help` topics under "word lists", filed after every other register
  so the bare word stays with a kind or a condition of the same name.
* **Found, not fixed:** a description that names a list nobody declared shows
  its braces. Declarations are checked; the text a list is used in is not.

### Phase 4 -- lexicon sources

* The calls of §6, with `else=`, the ConceptNet filter and seeded picks.
* Mentioned in the generator prompts so lists can use them.

Acceptance:
* with no corpus, every call gives its fallback;
* with `tests/fixtures/conceptnet-sample.tsv` and WordNet, picks are
  deterministic and pass the filter.

No world reset.

*As built* (`world/token_lists.py` `SOURCES`, `world/lexicon.py`,
`tests/test_lexicon_sources.py`). Settled in the building:

* **A dictionary's answer is made into a list on the spot and chosen from by
  the same path a kept list is.** `token_lists.resolve` was split so that
  `choose` takes any list, kept or not. So every call has a scope, a seed and
  an `as=` label for free, and is kept under the call itself --
  `hyponym:sword.n.01` -- so two different calls on one thing are two choices.
* **A plain word is accepted where a sense is**, when it settles to one:
  `$hyponym(sword)` is `$hyponym(sword.n.01)`. A word whose senses disagree
  settles to nothing and the call says its `else`.
* **WordNet gives one word per sense**, its first lemma with underscores as
  spaces, and only the senses directly beneath or directly part of it. Two
  steps down "tree" is already an opepe.
* **The ConceptNet filter is `token_lists.plausible`**: three words at most, a
  head noun WordNet knows, and not settled into the `person` bucket. "cook" is
  in a galley and is refused. An ambiguous word such as "sailor" settles to no
  sense and is let through -- the filter refuses only what it can be sure of.
* **Without WordNet nothing from ConceptNet passes**, because the filter needs
  a dictionary to say a word is a word. Every call then says its `else`, and
  one with no `else` says nothing.
* **A choice once made stays made** whatever a corpus says later. A call that
  found nothing stores nothing, so a world that later downloads ConceptNet
  starts choosing where it used to say its `else`.
* **No choice becomes a kind.** §6 allowed a hyponym to become an object's kind
  at creation. Phase 3 settled that nothing a list chooses changes what a
  thing is, and a dictionary's list is no different.
* **Known gap:** arguments are expanded before the call is made, so an `else`
  holding a list slot makes that list's choice even when the dictionary
  answered.

### Phase 5 -- recognition

`tokens.recognise(text, speaker, room)` gives
`[(ref, span, addressed|mentioned, confidence)]`.

* **Candidates** are the room's named contents and the people in the speaker's
  referents table. Aliases count, as in `naming.best_match`.
* **Exact word-boundary matches only**, never fuzzy. `resemblance` is right
  for a command, where the player means an object. In speech a false match
  costs more than a missed one, because recall trusts what it is given.
* **Common words need a capital.** A single-word name that is also an English
  word (`lexicon.known`) -- Hope, Will, Mark -- counts only capitalised, and at
  lower confidence.
* **Addressed means spoken to:** the name opens or closes the utterance, set
  off by a comma, "!" or "?"; or the command named a target. Otherwise it is
  mentioned.
* **Confidence** goes into the field `_annotate` already passes: 1.0 for bound
  roles, as now; below it for names found in speech.
* **Writes:** speech, emote and pose memories get `about`, through
  `events.noticed` and `notify_npcs`, which `at_say` and NPC speech already
  call. `addressed` is written as its own annotation kind.
* **Also a fact for the listener:** `witness` is handed who was addressed.
  What NPC reaction does with it is its own business. The fact is the
  deliverable, the same bargain `events._tell_the_characters` made.

Acceptance:
* "Hello, Raldor." addresses Raldor;
* "I think Raldor took it." mentions him;
* "I hope so." beside an NPC named Hope annotates nothing;
* somebody neither present nor in the speaker's table is not matched;
* annotations carry the stated confidences.

No world reset.

*As built* (`world/recognition.py`, `tests/test_recognition.py`). Settled in
the building:

* **Recognition is its own module**, `recognition.recognise(text, speaker,
  room, targets)`, not `tokens.recognise`: it reads words into references,
  which is the other direction from anything in `tokens`. It answers with
  `Mention(ref, name, start, end, addressed, confidence)`.
* **One word of a person's name counts, at lower confidence.** The plan allowed
  only a key or an alias, but people say "Barnaby" to Barnaby Royston. The rule
  is the one `NPC._names` already used to notice being named: every word of the
  name longer than two letters that is not a title. Whole names outrank parts,
  and the longest name found wins a stretch of text.
* **Things are mentioned too, and never addressed.** "Pass me the lamp" names
  the lamp. The capital rule applies only to people, since a thing is usually
  named in lower case.
* **A capital at the start of a sentence proves nothing**, so a name that is a
  word ("Hope", "Tam") counts there only when it is set off as being spoken to.
* **Two candidates for one stretch of text name neither**, unless one is surer:
  a whole name beats one word of somebody else's.
* **A name followed by the end of its sentence closes the utterance.** "Hello,
  Raldor. Is the lamp lit?" is said to Raldor.
* **The confidences:** 1.0 for a command's own target (a whisper's listener),
  0.8 for a whole name or alias, 0.6 for one word of a name, 0.5 for a name
  that is an ordinary word.
* **Annotations are written per confidence**, since `add_many` takes one per
  call. `addressed` is its own kind, by dbref. `about` accepts
  `(name, dbref, confidence)`, and the old two-field shape still reads at 1.0.
* **Where it runs.** `notify_npcs` reads player speech and poses. An NPC's `say`
  and `emote` read their own words and pass what they found to their own
  memory and to the NPCs who hear them. A whisper's receivers arrive as
  targets. And a witnessed action -- which the plan left alone -- now carries
  its bound participants at 1.0 into every witness's memory, from
  `events._tell_the_characters`.
* **An NPC answers when recognition says it was spoken to.** `spoken_to` sits
  beside `addressed_by`, which is unchanged: any mention of a name still wakes
  a character. What `spoken_to` adds is being whispered to.
* **Found and fixed: players never remembered what an NPC said.** An NPC's
  speech and emotes, and what it produced or picked up, were written to its own
  memory and told to the other NPCs through `_notify_other_npcs`, which never
  called `record_room_event`. `memory.py` promises that what a character has
  witnessed is written as it happens, and for every NPC tool it was not. Now
  `_notify_other_npcs` writes to the players' memories first -- before the
  chain limit, which exists to stop model calls rather than memories -- and
  the acts no other NPC is told about (asking a favour aloud, handing a thing
  over, breaking one) write through the same `_witnessed_by_players`. The one
  path that already recorded, a verb attempt, now goes through it too rather
  than recording twice.

### Phase 6 -- memory shape, rendering at display, and NPC context

**This phase resets worlds and abandons memory banks**, the price Phase M
paid. `pronouns-and-ownership.md` §7.1: "change the text template and old rows
are shaped differently from new ones, and retrieval degrades across the
boundary for as long as the bank lives." Run `export.py` first.

#### 6a. Episodes and states

`note_fact`'s docstring already draws the line: "an event is true for ever
because it happened, while a fact can stop being true."

* **An episode is past tense, third person, and named.** It is the event's
  narration template rendered with `purpose=memory`: "Raldor handed Jessica the
  sword." It is the same sentence for the actor and for witnesses, and never
  "I", which `attempt._remember`'s docstring found contributes nothing to
  extraction.
* **Contested outcomes** keep ", and failed" or ", and succeeded".
* **Speech** is `Raldor said, "..."`, with the words a literal span (§4.5).
  **Movement** is "Raldor arrived in the galley from the corridor."
* **Effect lines never enter an episode.** "The candle is now lit" is a state
  claim in present tense, stored for ever. What an effect changed is recorded
  where states belong: `note_fact` with `FROM_ENGINE`, or a triple that
  `supersede` will close. Ownership already does this. The episode says what
  was done.
* **One writer.** `describe_event`, `attempt._remember`, the arrival memory in
  `characters.py` and the movement memories in `npcs.py` become one
  `memory.episode(event)`. Speech, emotes and movement get lightweight `Event`
  records so they can go through it.
* **Metadata carries enough to render again:** template, role ids, verb,
  outcome, quote. The stored text is still the rendered sentence, because full
  text search indexes that and does not stem (§3).

#### 6b. Rendering at display

* **Recall keeps the whole row:** `_recall_sync` returns content, `timestamp`
  and metadata instead of content alone.
* **A recalled episode is re-rendered with today's names** when its metadata
  has a template and every id still exists: a renamed character, or a
  `world_name`.
* **If any id is gone, the stored text is used.** `pronouns-and-ownership.md`
  §7.6: a memory is never retired because its subject is gone.
* **Rendering reads the game database, and recall runs in a worker thread,**
  where `memory.py` notes that touching the game database is not allowed. So
  the NPC fetch splits in three: recall in the thread, rendering on the main
  thread, the model call in the thread. That is one more hop than today, and
  its cost is measured. If it matters, the fallback is rendering only ids
  that `_memory_inputs` already resolved on the main thread, and using stored
  text for the rest.
* **Deduplication must survive this.** `recall_sync`'s `already_known`
  compares strings, and works because working memory and stored memory use
  the same words. Both now go through the same renderer, and the comparison
  moves to memory ids where they exist. This gets a test, because its failure
  is silent: the prompt says everything twice.

#### 6c. What an NPC is shown

* **Chronological order**, oldest first, inside the existing "What you
  remember" block. The cue interleaving in `recall_for_cues` still decides
  *which* memories. Order is only presentation.
* **An age on every line** from `timestamp`: "moments ago", "earlier today",
  "yesterday", "days ago". These are real-time buckets; in-game time is
  deliberately not assumed (§12).
* **A present-state line for things the memories name,** capped: "Now: the
  sword is Raldor's, and in the galley." Read from the world, never from
  memory. This is what lets "Raldor handed Jessica the sword, days ago" sit
  beside the truth without contradicting it.
* **"Just now"** (`_format_history`) renders through the same function, in past
  tense, so the dedupe in 6b holds.

Acceptance:
* **Stored text:** the episode text for each source type; no effect line in any
  episode; an effect's state is a fact or a triple.
* **Recall and re-rendering:** recall rows carry timestamps; a renamed
  character's memory re-renders with the new name; a destroyed object's memory
  falls back to its stored text.
* **NPC context:** in time order with ages; the dedupe test from 6b; the
  present-state line appears and is capped.

*As built* (`world/memory.py` episodes and recall, `tests/test_episodes.py`).
Settled in the building:

* **One builder, two functions.** `memory.episode_line(event)` renders the
  narration -- repaired, without effect lines -- in the past tense for nobody,
  and adds ", and failed." or ", and succeeded." to a contest.
  `memory.episode_of(event)` adds `about` and metadata. An event with no
  narration, which is every look and every mechanic, gets a plain one from its
  verb and roles: "Jessica hugged Britney.", "Jessica looked at the sword."
* **Metadata is `shape: 2`** with the template, verb, outcome, whether it was
  contested, the actor's id, every role's id, and the quotes. Anything recalled
  without `shape: 2` is shown exactly as it was stored.
* **Every path a witnessed action takes carries the line and metadata**:
  `events._tell_the_characters`, `notify_npcs`, `record_room_event`,
  `NPC.witness`, `_add_to_history`, `_notify_other_npcs` and
  `_witnessed_by_players`. An NPC's working-memory entry keeps the same line it
  remembered, so "Just now" and recall are the same words.
* **`_acted` now answers with the episode**, so an NPC's own mechanic acts --
  picking up, handing over, producing, breaking, asking a favour, agreeing to
  an errand -- are remembered in the past tense. They carry no metadata, and
  are not re-rendered.
* **Speech is `Raldor said, "..."`**, and movement is "Raldor arrived in the
  galley from the corridor" and "Barnaby walked north to the dock". An NPC's
  emote is its template in the past tense: "Barnaby waved at Raldor". **A
  player's pose is stored as typed**, present tense and all: it is typed text,
  which is never read as a template, and nothing can safely change its tense.
* **`set_state` effects write triples** (`effects._note_states`): a state in an
  exclusive group supersedes the rest of its group, one in no group is `is`,
  and a removal closes its triple. Ownership already wrote facts.
* **Moving and destroying things write triples too.** Every story move of a
  thing -- taken, dropped, placed, given, sent by an effect -- reaches
  `ObjectParent.at_post_move`, which writes `located` ("carried_by #5", "in
  #1", "on #7") and supersedes where it was. Every triple here -- states,
  location, destruction -- is keyed by dbref, as ownership's already were: a
  triple is queried by identity, two swords share a name, and a renamed room is
  still the room. Names stay in the facts and the memories. Teleports are left out,
  since that is Evennia's housekeeping when something holding things is
  deleted, and so are people, rooms and exits. The `destroy_object` effect
  closes `located` and writes `is destroyed`, before the deletion; deletion
  itself is not hooked, because a world being reset deletes everything in it.
* **Creating a thing writes nothing, on purpose.** Things are made when first
  needed, not when first mentioned: the blackboard a room describes becomes an
  object the first time somebody reaches for it. A record of the moment it was
  made would say when somebody first reached for it and read as when it came to
  be. The hook skips an arrival from nowhere for that reason.
* **Recall does not return metadata; `get` does.** `_recall_sync` reads each
  hit's metadata by id in the same connection, and returns rows. `recall_sync`
  still returns strings for anything that wants them.
* **Rendering happens on the main thread, in one extra hop.** Both NPC prompts
  and the `remember` command now recall in the thread pool, format on the main
  thread -- re-rendering and the present-state line read the game database --
  and send the model call back out. **Not measured under load.** The fallback
  the plan names, stored text for anything the main thread did not already
  hold, has not been needed.
* **Deduplication is still by the words, not by memory ids.** A working-memory
  entry never learns its memory's id, because remembering is fire-and-forget.
  It holds exactly the line it remembered, so comparing the words keeps working
  once both sides are episodes.
* **Ages are real-time buckets**: "moments ago", "a little while ago", "earlier
  today", "yesterday", "N days ago". **The present-state line** covers at most
  three things, never people, and says whose each is and where: "Now: the
  sword is Britney's and carried by Britney."
* **Known gaps:** ownership's ", which belongs to Olara Voss" note on a
  witnessed theft is in the stored line but not re-rendered, and memories
  written before this phase stay in the bank until the world is reset --
  nothing in the code forces the reset.

---

## 9. What this leaves ready, and does not build

**No protocol code, and no change to what any client receives, is in this
plan.** These are the shapes chosen so that later work does not revisit the
same sites:

* **MXP.** Spans carry refs, so a name can later be wrapped in a clickable
  `<send>` at the edge. Nothing wraps anything yet.
* **GMCP and MSDP.** An event plus its spans is a structure with ids in it,
  ready to serialise.
* **MSP.** The event's verb and its participants' kinds are what a sound would
  key off. Both are already on the event.
* **The web client.** The same spans.
* **AIML-style responses with world-state tokens.** A response is author text
  rendered with `purpose=display` for whoever asked.
* **Templated objects and worlds with no model.** Lists and lexicon sources
  give variety with no call.
* **Generated languages.** A plugin would be a pass over the span sequence --
  literal spans are quoted words, phrases are references -- and the span
  sequence is where it would go. No hook is built.
* **World export and import.** `tokens.requires` says what a world needs.
* **Plural objects as one bound thing.** `english.count` and the mass test are
  its grammar.
* **Pronouns in a player's own speech.** Phase 1 makes a quote a literal span.
  The `at_say` rewrite remains its own `future-plans.md` item.

---

## 10. Decisions on the record

1. **One grammar, the one already stored:** `{slot}` and `$call(args)`.
   `<user>`, `{{user}}` and `$user` are aliases, normalised on store. §4.1.
2. **Tokens resolve to phrases, and a rendering is spans** joined at the edge.
   §4.2.
3. **A choice is a fact where the world has a word for it.** Decoration is
   stored per slot. Rendered text is never cached. §5.2.
4. **Scope is where a choice lives:** render, object, room, world, viewer.
   Built-ins default to render, lists to object, and a call overrides. §5.3.
5. **One choice per token per holder unless labelled.** A reference inside an
   entry is a new, nested slot, and only the outermost slot writes facts. This
   reverses the first sketch, which defaulted to two picks, because facts
   force one. §5.4.
6. **Object-scoped tokens resolve at creation.** §5.5.
7. **No conditionals, loops or attribute access in the grammar.** Fields are a
   closed table. §4.1.
8. **Author text expands; typed and quoted text never does**, and the
   mechanism is structural, not escaping. §4.5.
9. **Jinja2 is rejected; Tracery's shape is borrowed without the dependency;**
   `FuncParser` is a spike with a stated fallback. §2.1.
10. **Generators declare lists through their reply and see a filtered block,**
    as they do states. Tool calls wait for a generator tool loop. §5.7.
11. **Episodes are past tense, named and third person, and never hold a state
    claim.** States go to facts and triples. §8, 6a.
12. **Recalled memories are shown in time order with a real-time age,** beside
    present state read from the world. §8, 6c.
13. **Pronouns in speech are not resolved for memory.** §12.

---

## 11. Risks

1. **The spike fails** and the parser is ours. Contained: the grammar is
   small, and the spelling does not change either way.
2. **A description read that misses `text_of`** hands a model a raw `{color}`,
   and it invents one. Mitigation: a test that fails if a generator module
   reads `.db.desc` into a prompt except through the accessor, in the style of
   the f-string test in `pronouns-and-ownership.md` §11, risk 2.
3. **Refused lists.** A model will name states in `sets` that it did not
   declare, and those lists are refused. The refusal rate is worth watching,
   the way `rule_failures` is.
4. **Recognition writes something trusted that is wrong.** Mitigated by exact
   matching, scope, the capital rule and confidence below 1.0. The failure
   still exists and deserves soak data.
5. **Phase 6 abandons memory banks.** Deliberate, and covered by the reset.
6. **Re-rendering costs a thread hop per NPC turn.** Measured before it is
   kept, with the fallback in 6b.

---

## 12. Out of scope, deliberately

* **Protocol output** of every kind (§9).
* **A `period` scope.** It needs a decision about what a period is -- real hours
  or an in-game day -- and the in-game version wants a clock.
* **In-game time in memory ages.** Real-time buckets until a world clock
  exists.
* **Resolving pronouns in speech for memory.** "Give it to her" means what the
  speaker was attending to, not what the listener's table holds. A wrong guess
  becomes an annotation recall believes.
* **Kinds declaring themselves mass.** Food nouns need it (§7.2). It adds a
  field to kind specs and to the item prompt, and is its own small piece of
  work, recorded in `future-plans.md`.
* **A plugin loader.** The seam only (§4.4).
* **Menu editors for lists** beyond the `tokens` command. The "full menu-based
  building" item in `future-plans.md` owns that.
* **Stemming in memory search.** It is mnemosyne's table. Noted in §3 because
  "swords" not matching "sword" is a retrieval gap worth knowing about.
* **The `at_say` rewrite** (§9).
