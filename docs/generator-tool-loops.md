# Development plan: generator tool loops and busy notices

Status: **planned, nothing built.** Scoped from two `future-plans.md` items:
"generators get a full tool call loop" and "show when busy". It also covers
most of "tools for the models", for the lexicons in particular. §9 lists the
phases in build order, §10 the decisions taken and the questions still open,
and §11 the risks.

Companion to `development-plan.md`, `tokens-and-phrases.md` and
`pronouns-and-ownership.md`. The ground rules in §2 of `development-plan.md`
are acceptance criteria here too, unchanged. Two of them matter most here:

* **Rule 1: the steady state costs nothing.** A loop adds rounds to a call
  that is already being made. It must never add a call where there is none
  today.
* **Rule 5: every slot a model fills is a closed identifier, a number, a
  boolean, a condition, or an effect.** Today a prompt asks for that in prose.
  A schema can state it outright, which is most of the point of §4.

This also closes `tokens-and-phrases.md` §5.7, "Tool calls wait". That section
uses reply fields plus a filtered vocabulary block as a stand-in for a real
"list and create tokens" tool, and this plan builds the real one.

---

## 1. The change, on one page

This game makes 23 kinds of model call. Two of them (NPC reaction and NPC
idle) send tools, and only for a single round: nothing a tool returns ever
reaches the model. The other 21 are single-shot JSON. Each one pastes its
vocabulary into the prompt and hopes the answer matches the shape described
in prose.

That design is failing in five ways, and the failures get worse as a world
grows:

1. **Registers are outgrowing prompts.** `token_lists.MOST_SHOWN` shows 20
   lists and `quest_gen.MAX_ROOMS_LISTED` shows 60 rooms. `npc_gen._known_verbs`
   lists every verb a world has ever learned, with no limit at all.
   `verb_gen.state_block` shows the whole state vocabulary. And
   `npc_gen._people_in_world` gathers every name in the world into one
   sentence. Each of these was a good choice for a young world, and each one
   is either cut off or unbounded in an old one. Worse, they take up the room
   in the prompt that hints about the task itself should have.
2. **The model is never told why its answer was refused.** Room and NPC names
   are retried through a conversation built by hand, a separate copy in each
   generator. Complaints from `rule_gen.validate` are logged, the rules are
   dropped, and the verb is counted as fruitless. `goals.sanitise`,
   `pronouns.clean` and `token_lists.clean` drop what they cannot use without
   a word. The model that made the mistake is the one party never told about
   it.
3. **Closed identifiers are offered as prose menus.** Six prompts ask for an
   identifier copied exactly: the noun sense, the verb sense, an anchor, a
   rule's scope, a verdict's id, and a goal's room. Only the NPC tools
   actually use `enum`.
4. **NPC tools cannot answer.** `check_traits` puts what it finds into working
   memory so the character sees it on its *next* turn, because a tool here
   "acts; it cannot hand an answer back". A refusal takes the same route.
5. **Players wait in silence.** A new verb means up to four sequential calls
   of 30 seconds each. A new room is a name with up to three tries, then a
   description, each call allowed 60 seconds. A player sees one line ("You try
   to pry the crate...") and then nothing. Tool loops make these waits longer,
   which is why notices come first (§9).

So the work is six things:

* **One loop** in `world/llm.py`, beside `fetch`, that every generator shares.
  **Tools are required**: models that cannot use them are removed from the
  `models` menu, and nothing is kept as a single-shot fallback (§3).
* **Finish tools.** Each generator's reply shape becomes a tool schema whose
  enums are filled in at call time. Its handler runs the validators that exist
  today and sends their complaints back to the model as the tool result (§4).
* **Every register behind a lookup tool.** The prompt keeps the subject of the
  call, the instructions, and hints specific to this thing, and nothing else
  (§5).
* **NPC tool schemas enriched**, and tool results returned to the model within
  the same turn, with `modify` held to the rules every other tool follows (§6).
* **Hints from what the world is missing.** Wants that nothing in the world can
  satisfy, and the faults `worldcheck` already finds, filtered down to what each
  call is making. A generator is then nudged towards filling a gap the world
  already has, rather than adding something new beside it (§5.1, §5.2).
* **Busy notices**: a line every ten seconds or so to any *player* waiting on a
  model, and a `busy` command to set how often (§7).

---

## 2. What is already here to build on

**The seam exists.** `llm.call` already accepts `tools`. It hardcodes
`tool_choice: "auto"` (`llm.py`, in `call`), which is the only change the
network layer needs. `llm.fetch` is still the one door. `support.immediately()`
makes that door synchronous, so a loop of several hops runs to completion
inside a test with no reactor.

**The hop pattern exists.** `generate_npc_reaction` already goes thread, then
reactor, then thread: recall runs off the reactor, formatting the recalled rows
reads the database on it, and the model call goes off again. A tool loop is the
same pattern repeated: the call runs in a thread, tools run on the reactor, and
the next call goes back to a thread.

**Enriching tools per call exists.** `npc_gen._tools_for` and `_with_choices`
close arguments to what is actually present, and drop any tool whose list would
be empty. Their docstring makes the argument for this whole plan: "A tool that
cannot be used is worse than a missing one." §4 and §6 apply it everywhere.

**The validators exist.** None of this needs new judgement, only a new
destination for complaints the code already writes:

| Validator | Today its complaint goes to |
|---|---|
| `worldgen._check_name`, `_check_way_on`, `_check_singleton`, `_check_zone` | a conversation built by hand in `_generate_name` |
| `npc_gen._check_name` | a conversation built by hand in `generate_npc` |
| `rule_gen.validate` | the log; rules dropped; `note_fruitless` |
| `goals.sanitise`, `quests.offer` returning `None` | the log |
| `pronouns.clean`, `token_lists.clean` | discarded |
| `traits.register` renames (through `traits._matching`), `verbs.register_state` folding (through `verbs._similar` and the group guessers), `actions.clean_roles` / `clean_gates`, `checks.clean` | silently corrected |
| `verbs.name_contradicts_states` | used for generated names, never for `modify_object` |

**The vocabularies are already closed tuples:** `rulebooks.PHASES`,
`effects.VOCABULARY`, `conditions._PREDICATES`, `conditions.ROLES`,
`goals.CONDITION_TYPES`, `actions.ROLES` / `ACCESS` / `GATES`,
`clothing.GARMENT_TYPES`, `gear.CONDITIONS`, `kinds.PLACEMENT`,
`worldgen.CATEGORIES` / `BUILDABLE_DIRECTIONS`, `traits.TRAIT_TYPES`,
`pronouns.REQUIRED`, `zones.MIN_BUDGET` / `MAX_BUDGET` / `MAX_DEPTH`,
`token_lists.SCOPES`.

**Knowing which models take tools is half there.** `model_params.supported`
already reads `supported_parameters` off a model record, which is how the
`models` menu decides which settings to offer.

**Spending is already per call and per job.** `_spent` queues usage from
inside the thread, `fetch` writes it down, and `ledger._add_totals` keys it by
job. So a loop of N rounds is already N ledger entries under the right job.

**The idiom for where a schema lives already exists.** `gear.prompt_block`,
`actions.prompt_block` and `affordances.PROMPT` are "kept beside the record [they
describe], so that the shape asked for and the shape read cannot drift apart".
Tool schemas follow the same rule: each lives beside the code that reads what
comes back.

**NPCs do not override `msg`.** A message sent to a character with no sessions
goes nowhere, and its memory and history are untouched. §7 still never sends a
busy notice to one (§10.7).

### 2.1 Found along the way

Bugs and dead code found while scoping. Phase 0 deals with all three:

* **`npcgen` cannot work.** `world_cmds.py` calls
  `generate_npc(account=account, ...)`, but `generate_npc` takes a `sponsor`.
  The call raises `TypeError` *after* `room.ndb.generating_npc = True` has been
  set, so every later `npcgen` in that room answers "An NPC is already being
  generated" until a reload.
* **`rules judge` cannot work.** `world_cmds.py` passes `_get_account(caller)`
  to `suggest.judge`, which calls `sponsor.key()`. On an Account, `key` is a
  string, so the call raises `TypeError: 'str' object is not callable`. That
  is not one of the `(AttributeError, ValueError)` exceptions it catches.
* **`verb_gen.learn_rule` has no caller** outside tests. `rule_gen.learn`
  replaced it. It should be deleted, along with `_RULE_SYSTEM` and the helpers
  only it calls (`_apply_renames`, `_lore`, and `_kindred_block` unless
  `verb_info` in §5 reuses it), rather than converted. `state_block` and
  `_states_of_kinds` stay: `rule_gen` uses them.

---

## 3. The loop

### 3.1 Shape

```python
llm.converse(sponsor, model, messages, toolbox, *,
             on_done, on_error, rounds=8, wait=None)
```

It sits beside `fetch`, runs on the reactor, and uses `fetch` for every network
hop. One round goes like this:

1. `fetch(call, ..., tools=toolbox.schemas, tool_choice=...)`.
2. Back on the reactor, add the assistant message to the conversation exactly
   as it came, `tool_calls` and all.
3. For each tool call, in order:
   * parse the arguments with `model_json.parse_object` (repaired, as the NPC
     path does today);
   * check them cheaply against the schema: required fields present, enum
     members real, numbers in range. A failure becomes the result, and the
     handler is not run;
   * run the handler, and add one `{"role": "tool", "tool_call_id": ...,
     "content": ...}` message.
4. When the finish tool's handler **accepts**, call `on_done(value)` and stop.
5. When it **complains**, the complaint is its result and the loop goes round
   again.
6. A reply with **no tool calls** is answered with a user message: "Answer by
   calling `<finish tool>`." There is no parsing of JSON out of the content:
   one way to answer, one parser. (NPC turns and `remember` have no finish
   tool, and for them a reply with no tool calls is the end; see §4.2.)

**How it ends.** On the final round, `tool_choice` names the finish tool
(`{"type": "function", "function": {"name": ...}}`). If that round is still not
accepted, each generator keeps the fallback it has today:

* room and NPC names are "taken as it stands" after the last try;
* a rule with nothing usable goes to `note_fruitless`;
* a description that will not parse goes to `on_error`.

**Guards.** All of these live in the loop, so no generator needs its own copy:

* **Rounds** are budgeted per generator (§10.3).
* **Calls per round** are capped at 8. Any beyond that get the result "not
  run: too many at once".
* **A repeated identical lookup** gets its cached result back, with a note
  saying so. A small model that keeps asking for the trait list is told it
  already has it.
* **Results** are capped at about 4,000 characters, with a truncation marker.
  Every list tool takes `query`, `limit` and `offset`, so the model can ask
  again more precisely.
* **A handler that raises** has its traceback logged. The model gets
  `{"error": "that lookup failed"}`, and the loop itself never raises.
* **Handlers may be asynchronous.** The signature is
  `handler(ctx, args, answer)`: a synchronous handler calls `answer` before it
  returns, and an asynchronous one (an NPC's `attempt`, a recall) calls it
  later. A tool marked `threaded=True` is run through `fetch`. That is right
  for memory recall and ConceptNet, which are SQLite and slow. WordNet is
  already guarded by `lexicon._LOCK`.

**Snapshotted schemas.** The toolbox is built once, when the loop starts. Enums
are not recomputed between rounds, and that is deliberate for two reasons. The
tool list then forms a stable prefix a provider can cache. And nothing a
generator registers is written until the finish tool accepts, so there is
nothing new to show mid-loop.

**Every loop is measured** (§10.3). When a loop ends it logs one line: job,
seconds taken, rounds used against the budget, each lookup tool called and
how often,
complaints returned, the hints shown (§5.1, §5.2) and whether the accepted
answer used any of them, and outcome (accepted, forced, or fell back). The
ledger keeps these per job, beside its token totals: seconds taken, loops,
rounds, the most
rounds any one loop took, how many loops were forced to finish, complaints
returned, calls to each lookup tool, and hints shown and used. The `rounds`
command (§3.5) reads them, so budgets can be set from what models actually use
in real play rather than from this document.

### 3.2 Tools are required

Every generator here now needs tool calls, and the models capable of this work
support them. So there is **no single-shot fallback**. That removes a second
path through every generator, the need to keep the prompt blocks as a
fallback, the retry-and-remember logic, and the tests for all of those.

* **The `models` menu leaves toolless models out.** A model record whose
  `supported_parameters` is published and lacks `"tools"` is not offered, for
  any job. A record that publishes no list at all is still offered: that is
  `model_params.supported`'s benefit of the doubt, and it keeps a provider
  other than OpenRouter usable (the `future-plans.md` item about changing the
  API URL).
* **A model chosen before this, that cannot take tools,** is refused at call
  time. The job fails with a message naming the model and the job and saying
  to pick another in `models`. That goes to `on_error` exactly as a missing
  key does now. There is no quiet downgrade.
* **A refusal from the service** (OpenRouter answers a tools request with an
  error saying no endpoint supports tool use) arrives as an `LLMError` like any
  other, with the service's own words. It needs no special handling.
* **Routing needs nothing extra.** OpenRouter sends a request that carries
  `tools` only to providers that support them, which its documentation says
  and experience on other projects bears out. So no
  `provider.require_parameters` is sent, and the sampling settings route as
  they always have.

### 3.3 What stays in the prompt

With every register behind a tool (§10.4), the prompt holds only three things:

* **The subject of the call.** The room being named and its neighbourhood, the
  objects bound to a verb, the rules already decided about this attempt, the
  queue being judged, an NPC's room, wants, traits and recalled memories.
* **How to answer.** The world's lore and guidance, and prose that tells the
  model how to fill the reply: the naming rule, the affordance rule, the effect
  and condition explanations, the gear prose, the engine verbs `rule_gen` must
  not redefine.
* **Hints specific to this one thing.** Small, derived from the subject, and
  worth more than any register: the states things of this kind have been in
  before (`kinds.states_of`), `lexicon.suggested_anchors` for an invented noun,
  the ancestor verbs `verb_info` would return when one has rules already. Two
  more come from what the world is missing: wants nothing can satisfy (§5.1)
  and faults in its rules (§5.2), each filtered to this call. This is the room
  the registers used to take up.

**The price, stated plainly.** A lookup is a round, and a round resends the
whole conversation, so pasting a short list in is cheaper in tokens than
looking it up. What it buys is a prompt that stays the same size however large
the world gets, with that room spent on hints. The ledger measurement in §3.1
is what tells us whether that trade is right, and the soak (Phase 8) is where
we look.

**What stops invented near-duplicates.** The inline registers existed so that
"a word not shown gets coined again under another name". A model that skips
`list_states` will do exactly that. So every finish handler that accepts a new
state, group, trait, word list or pronoun set first checks it against the
register, using the similarity checks that already fold near-matches silently
(`traits._matching`, `verbs._similar` and the group guessers). A near-match is
**returned as a complaint rather than folded**: "this world already has
`closed` (group: openness); use it, or say how `shut` differs." Folding
silently is kept only for the forced final round.

### 3.4 Where the code lives

* `world/llm.py`: `call(..., tool_choice=None)` and `converse`.
* `world/toolbox.py`, which holds only mechanism:
  * `Tool`: name, `doing` (a short phrase for busy notices, §7), and
    `describe(ctx)`, `parameters(ctx)`, `available(ctx)`, `handler`,
    `threaded`, `finishes`.
  * `ToolContext`: `world_root`, `room`, `actor`, `bound`, `sponsor`, `job`
    and `wait`.
  * `Toolbox`: the tools for one call, with dispatch, caching and the
    measurement line.
  * Schema helpers: `closed(values)` (an enum, or a description plus validator
    once past the enum cap, §4.1) and `paged()`.
* **Schemas and handlers live beside their records**, following the idiom in
  §2: `traits.tool_schemas()` beside `traits.register`, `effects.schema(ctx)`
  beside `effects.VOCABULARY`, and so on. `toolbox.py` never imports a game
  module at import time.
* **The `*.vocabulary_block` functions and prompt blocks are deleted** as the
  last generator using each one converts, unless a command also uses them. For
  example, `tokens` has its own listing.

### 3.5 The `rounds` command

In `commands/account_cmds.py`, beside `busy`, and added to the account cmdset
so it works in and out of character. It reads the ledger's loop figures (§3.1)
for the account that paid:

```
rounds                 every job, one line each
rounds <job>           one job in full
rounds world <number>  only what one world spent, numbered as in `worlds`
rounds clear           start counting again, after a budget change
```

* **One line per job**, with the count first so it is the first thing heard,
  and no columns or aligned figures, following `score` and `rulecheck.report`:
  "rule writing: 14 loops, 2.6 rounds on average, 7 at most, budget 8, 1
  forced to finish, 18 seconds on average."
* **One job in full** adds complaints returned per loop, each lookup tool with
  its call count (most used first), and hints shown against hints used.
* **`clear`** empties only the loop figures. Token totals and spending are the
  ledger's record of money spent, and are left alone.
* **Job names** are the ones the `models` menu lists (`FUNCTIONS`), so a player
  reading `rounds` and choosing a model in `models` sees the same words.
* It is a single-purpose command on purpose, like `busy`. Both are named in the
  `future-plans.md` item about regularising commands, and fold into that
  structure when it is built.

---

## 4. Finish tools: reply shapes as schemas

### 4.1 Schemas used in more than one place

Four generators make an item: `generate_item`, `populate_room`, `dress_npc`,
and the `create_object` effect. The first three already share one reader,
`clothing.create`. They get one schema too:

**`clothing.spec_schema(ctx, worn=False)`**, beside `clothing.create`:

* `affordances`: an object whose keys are verbs (the key format is stated in
  the description and checked by `affordances.normalise`).
* `holds`: items drawn from `kinds.PLACEMENT`.
* `clothing_type`: `clothing.GARMENT_TYPES` plus `""`, and required when
  `worn=True`.
* `trait_bonuses`: keys limited to the world's registered traits.
* `bonus_when`: `gear.CONDITIONS`.
* `bonus_while`: open. Its description points to `list_states` and names the
  states this item's kind has been in before (a hint, §3.3).
* `states`: open, checked for near-duplicates as §3.3 describes.
* `sense`: when `lexicon.needs_sense_choice` says the word is ambiguous, an
  enum of `lexicon.senses(head)` plus `""`. This replaces `sense_prompt`'s menu.
* `under`: open, with `lexicon.suggested_anchors` in the description and
  `lexicon_senses` offered. The field says "any WordNet identifier will do",
  so it cannot be an enum. The handler checks the identifier exists and
  complains if it does not.

Other shared schemas:

* **`effects.schema(ctx)`**, beside `effects.VOCABULARY`: `type` from the
  vocabulary; `role` / `name_role` from `conditions.ROLES` plus the bound
  roles, plus `everyone` / `others` for `set_state` and `set_trait`;
  `preposition`; `trait` from the register.
* **`conditions.schema(ctx)`**, beside the predicate table. The table becomes
  a public `PREDICATES`.
* **`goals.schema(ctx)`**, beside `CONDITION_TYPES`: `room` checked against
  built rooms (`find_rooms`, §5).
* **`token_lists.schema()`**, beside `clean`. **`pronouns.set_schema()`**,
  beside `REQUIRED`. **`traits.declaration_schema()`**, beside `TRAIT_TYPES`.
  **`verbs.state_declaration_schema(ctx)`**, beside `register_state`.

**How closed each field is.** A field is **closed** (an enum) exactly where the
code refuses anything else: scopes, phases, effect types, predicates, roles,
gates, access, garment types, `bonus_when`, room categories, directions, and
traits in any place that forbids inventing one (NPC creation, quests, goals). A
field is **open, with a lookup tool offered and a near-duplicate check in the
handler** wherever coining a new value is allowed: states, groups, zone names,
room types, kinds, senses under an invented word. And a field is **left out
entirely** when it cannot be used at all, the way `_tools_for` leaves out a
tool (an example is `zones` on an area already at `zones.MAX_DEPTH`).

**The enum cap.** An enum is a list too, and it sits in the tool schema, which
is part of the prompt. Most closed vocabularies are short, fixed tuples. The
few that grow with a world (registered traits, pronoun sets, rooms) stay enums
up to **50 values**, where an enum costs roughly what a paragraph does. Past
that the field becomes open, with a lookup tool offered and the enum's
membership check moved into the handler, which returns a complaint. The number
is a starting point for the soak (Phase 8) to revisit.

**A conservative dialect.** Providers differ in how much JSON Schema they
honour, so schemas stay within the subset that works everywhere: `type`,
`properties`, `required`, `enum`, `items`, `minItems` / `maxItems`,
`minimum` / `maximum`, `description`, `additionalProperties: false`. There is
no `oneOf`, `anyOf` or `pattern`. Where a field's shape depends on another
field (an effect's arguments depend on its `type`), the optional properties
say in their descriptions which types use them, and the validator enforces it.

### 4.2 Per generator

"Complaints returned" means the validator's words become the finish tool's
result, so the model gets a chance to fix its answer. Every generator that can
coin vocabulary also gets §3.3's near-duplicate complaint, which is not
repeated in each row below.

| Generator | Finish tool | Filled in at call time | Complaints returned (today) |
|---|---|---|---|
| `worldgen._generate_plan` | `plan_world` | budget bounds from `zones`; 3–6 zones | `singleton_types` naming no zone's room type (never checked) |
| `worldgen.plan_zone` | `describe_area` | budget bounds; `zones` left out at `MAX_DEPTH` | "0, or 2 to 5" sub-areas (prose only) |
| `worldgen._generate_name` and the first room | `name_room` | `category` from `CATEGORIES`, without `destination` when leaving a destination (first room: circulation or threshold only); `exits[].name` limited to directions actually open, by the logic `_allowed_exits` uses; `zone` open, with `list_zones` | `_check_name`, `_check_way_on`, `_check_singleton`, `_check_zone` (a conversation built by hand) |
| `worldgen._generate_description` | `describe_room` | `trait_bonuses` keys from the register; `new_token_lists` with `token_lists.schema()` | empty description; `token_lists.clean` and the productivity check; unknown lists referenced (discarded) |
| `worldgen.populate_room` | `furnish_room` | up to 3 items with `spec_schema`; `wants_npc` | item names repeated from the description (prose only) |
| `item_gen.validate_object_existence` / `_takeable` | `judge_existence` / `judge_takeable` | `valid`, `reason` | — |
| `item_gen.generate_item` | `make_item` | `spec_schema`, with `sense` / `under` per word | `kinds.sense_contradicts` (silently resolved) |
| `npc_gen.generate_npc` | `make_character` | `pronouns` from the registered sets; `traits[].slug` from the register, up to 4; `goal` with `goals.schema` | `_check_name` (a conversation built by hand); `pronouns.clean` (discarded); `goals.sanitise` drops (silent) |
| `npc_gen.dress_npc` | `dress_character` | `worn[]` with `spec_schema(worn=True)`, up to 8; `carried[]`, up to 3 | a garment that does not afford `wear` (prose only) |
| `rule_gen.learn` | `file_rules` | `phase` from `PHASES`; **`scope` from `menu()`'s tokens** (ground rule 6, now in the schema); `about` from roles plus `enclosure`; `effects.schema`; `conditions.schema`; `contest.trait` from the register; `adopt` from the ids of this verb's proposals waiting in the `suggest` queue (§5.2) | `validate`: unknown phase or scope, too general, check with no conditions, self-defeating, empty carry-out (logged and dropped); a literal `new_name` in `modify_object` that breaks the naming rule (§6.3) |
| `verb_gen.ask_admission` | `admit` | `allowed`, `reason` | — |
| `verb_gen.narrate` | `narrate` | `effects.schema`; `difficulty` ≥ 0; placeholders limited to `{actor}` plus the bound roles | a name of a bound object written out, `the {role}`, a verb after `{actor}` not written `$pconj(...)` (the prompt's own "Wrong:" cases, all mechanically checkable, never checked) |
| `actions.learn` | `declare_action` | `role` from `ROLES`; `access` from `ACCESS`; `despite` from `GATES`; `sense` from `verb_senses` when there are two or more | a reply with no `applies_to` (silent fallback to `observe`) |
| `quest_gen.formalise` | `write_quest` | `goals.schema`; `effects.schema` for reward and punishment; `trait` from the register | no testable goal (`quests.offer` returns `None`; logged) |
| `quest_gen.formalise_goal` | `write_goal` | `goals.schema` | `goals.sanitise` drops everything (logged) |
| `fact_gen.distil` | `record_facts` | up to `MAX_FACTS` | — |
| `suggest.judge` | `give_verdicts` | `id` from the ids in the queue | a verdict for an id not in the queue (logged) |
| `memory_cmds` remember | *none*: it answers in prose, and may call `recall` | — | — |
| NPC reaction and idle | *none*: the loop ends when a reply calls no tools | — | — (§6) |

That is 21 generators converted plus the two NPC calls, which are already
tool-shaped. `verb_gen.learn_rule` is deleted, not converted (§2.1).

**How many chances to fix.** A complaint costs a round, and a round costs a
call. Budgets are per generator (§10.3). Past the budget, the fallback in §3.1
applies, and `note_fruitless` still counts the verb for `rule_gen`. It is
counted once, when the loop ends, rather than once per round.

---

## 5. Lookup tools and hints

Each row is something a prompt contains today. Registers leave the prompt for
tools (§10.4). The last column is what stays in the prompt, and why.

| In the prompt today | By | Tool | What stays |
|---|---|---|---|
| `lore.description`, `lore.guidance_block` | every generator | — | all of it: how to answer |
| affordance rule, naming rule, anchor rule, condition and effect prose, gear prose, engine verbs | the item generators, `rule_gen` | — | all of it: how to answer |
| `traits.vocabulary_block` (also the tail of `gear.prompt_block`) | `npc_gen`, `rule_gen`, `quest_gen` ×2, the item generators | `list_traits(query, limit, offset)`, `show_trait(slug)`: type, bounds, rate, `descs` | the enum where a field forbids new traits (§4.1) |
| `pronouns.vocabulary_block` | `generate_npc` | `list_pronoun_sets()` | the enum on `pronouns` |
| `token_lists.vocabulary_block(for_kinds)` | `generate_item`, `generate_npc`, `_generate_description` | `list_word_lists(for_kind, query, ...)`, `show_word_list(name)`, `try_text(text)`: the `tokens try` rendering, reporting unknown lists and syntax errors | `token_lists.PROMPT`, which says how to use a list |
| `verb_gen.state_block` | `rule_gen` | `list_states(query, kind, ...)`, `show_state(slug)`: meaning, group, conflicts, `prevents_*`, `ends_on_move`; `list_state_groups()` | the states this kind has been in before: a hint |
| `lexicon.sense_prompt`, `anchor_prompt`, `verb_sense_prompt` | `generate_item`, `actions.learn` | finish-tool enums (§4.1), plus `lexicon_senses(word, pos)`, `lexicon_define(sense)`, `lexicon_ancestors(sense)`, `lexicon_hyponyms(sense)`, `lexicon_parts(sense)`, `verb_ancestors(verb)` | ConceptNet's suggested anchors for an invented word: a hint |
| (not in any prompt) ConceptNet | — | `commonsense(word, relation)`, relation from `kinds_of`, `parts_of`, `opposites`, `can_be_done_to`, `ways_to`, `found_at`, `used_for`; `threaded` | — (offered only when `commonsense.available()`, ground rule 2) |
| `verb_gen._kindred_block` | (`learn_rule`, deleted) | `verb_info(verb)`: `actions.spec`, rules filed for it, ancestor verbs and their rules, engine verb or not, fruitless count | in `rule_gen`, a one-line note when an ancestor verb has rules: a hint |
| `rulebooks.for_attempt`, "already decided" | `rule_gen` | `list_rules(action, scope, ...)`, `show_rule(id)` | the attempt's own rules: the subject |
| `rule_gen.menu` | `rule_gen` | finish enum; `kind_info(kind)`: word, gloss, ancestors, `kinds.spec` floor and `holds`, admissions settled | the enum |
| `verb_gen._describe_objects` | `rule_gen`, `narrate` | `examine(name)` for anything else in reach: affordances, states, relations, owner | the bound objects: the subject |
| `npc_gen._people_in_world` | `generate_npc` | `name_taken(name)`, plus the finish validator | — |
| `worldgen._neighbourhood` | `_generate_name`, `_generate_description` | — | all of it: the subject (spatial, capped at 4,000 characters) |
| `zones.menu`, `full_names`, `_singletons_taken` | `_generate_name` | `list_zones()`, `zone_info(zone)`: budget, size, types, singletons taken, children | the zone of the room being left: the subject |
| `quest_gen._known_rooms` (capped at 60) | `formalise`, `formalise_goal` | `find_rooms(query, ...)`: built rooms only, as today, with no cap | — |
| `quest_gen._surroundings`, `npc_gen._room_context` | quests, NPCs | — | all of it: the subject |
| `npc_gen._known_verbs` (no limit) | NPC reaction and idle | `list_known_verbs(query, ...)` | — |
| `memory.recall_for_cues` | NPC reaction and idle, `remember` | `recall(query)`, `threaded` | the automatic recall: the subject |
| a room *name* in `move_object` / `set_exit` / `move_actor` effects ("name one that exists") | `rule_gen`, `narrate` | `find_rooms` | — |
| `suggest.judgement_prompt` | `judge` | `show_rule(id)` for the overridden rule in full | the queue: the subject |

**Who sees what.** A generator is the world thinking about itself, so it can see
every register. A character's toolbox sees the same registers (the
open-sandbox principle), but only its own room, its own memory, and rooms that
have been built. That matches what `quest_gen._known_rooms` shows it today.

### 5.1 What people want, and nothing in the world can provide

**The problem.** An NPC can ask a player for raw ore when there is no raw ore
anywhere in the world, and no room, item or rule will ever make any. The quest
can never be finished. And when a generator does happen to make some, it may
call it "unrefined ore chunk", which the quest does not accept either. Nothing
tells the generators what is wanted, or in what words.

**Where the wants come from.** A new function, `goals.blocked_wants(world_root)`,
beside `goals`. It makes no model calls and keeps no register of its own. It
reads the wants of every character in the world:

* an NPC's `db.goal`, which already includes an accepted quest (`_adopt_goal`);
* a player's own `db.goal`, set with the `goal` command;
* a player's active quest (`quests.current`). `_adopt_goal` copies a quest into
  `db.goal` for NPCs only, so a player's quest has to be read separately.

Players who have logged out are not in any room, so their wants are counted
only while they are playing. That is enough: rooms and items are generated
while somebody is playing.

**Why each want is blocked.** For every condition `goals.progress` says is
unmet, a new `planner.blocker(actor, world_root, condition)` gives the reason.
The planner already reaches each of these dead ends in `_for_condition`, and
today it only returns `None`:

| Reason | How it is found | Who is hinted |
|---|---|---|
| `missing_thing` | the condition names an object or kind, and `goals.find_object` / `find_of_kind` find nothing anywhere in the world | room naming, room contents, dressing a character, `rule_gen` |
| `out_of_reach` | it exists, but `_route` finds no way there within `MAX_TRAVEL` | nobody yet. Recorded, and shown to players by `advise` |
| `no_rule` | the thing exists, and no verb this world knows (`_verb_for`, ignoring untried verbs) would put it in the wanted state or move the trait | `rule_gen` (§5.2) |
| `missing_room` | `in_room` names a room nobody has built | room naming |

Two uses come free before any generator changes:

* **Players get a real reason.** `advise` can tell a player "nothing called raw
  ore exists anywhere in this world yet", instead of "whatever it needs may be
  somewhere you have not been yet".
* **Give-ups explain themselves.** `_give_up_eventually` logs why a character
  gave up.

**What each generator is shown.** At most three wants per call, as a hint, not
a register (§3.3). Player quests come first, then players' own goals, then
NPCs'. Each hint gives **the exact words a want accepts**. An `object`
condition matches a name that contains those words (`find_object` tries the
exact key, then a substring), and a `kind` condition matches the canonical
kind. So the hint says "named so the name contains `raw ore`" or "of kind
`ore`". That alone prevents the ore chunk that satisfies nobody.

* **Room contents** (`populate_room`): wanted things this room plausibly holds.
  With ConceptNet, relevance means `commonsense.forward(word, "AtLocation")`
  shares a word with the room's type, name or zone, so ore goes to mines and
  quarries. Without ConceptNet (ground rule 2), up to two are shown anyway, with
  the instruction to include one only if it genuinely belongs here.
* **Room naming** (`_generate_name`): `missing_room` wants, and wanted things
  together with the places ConceptNet says they are found ("raw ore: a mine, a
  quarry"). The model is told a way out may lead somewhere like that if it
  fits.
* **Dressing a character** (`dress_npc`, `carried`): wanted things this
  character's trade would plausibly have. A merchant carrying the ore turns an
  impossible quest into a trade. Never the character's own wants: an NPC
  created wanting ore would otherwise be dressed carrying it, and satisfied
  before it took a step.
* **`rule_gen.learn`**: `no_rule` wants for the bound objects, always. A
  `missing_thing` want only when ConceptNet relates it to a bound object's kind
  (`PartOf`, `HasA`, `AtLocation`). Breaking rock can then yield the ore, and
  sniffing bread cannot. With no ConceptNet, only `no_rule` wants are shown.

**Hints clear themselves.** A thing that exists anywhere is no longer missing,
so the hint disappears the moment one is made. Two generations running at once
might each add one. The cost of that is a spare, never a flood.

**Not in the room where it was asked for.** A wanted thing is not hinted to the
room the quest giver is standing in, or to the room holding the NPC that wants
it. Finding it should mean going somewhere.

**Cost.** The scan walks the world's rooms, just as `goals._world_objects`
already does every time a goal is tested. It is computed once per generator
call. The soak (Phase 8) decides whether it needs a cache on the world's `ndb`
for a few seconds, so the several calls that build one room would share one
scan.

### 5.2 Faults `worldcheck` already finds

**The problem.** `rulecheck.scan` already works out what is wrong with a
world's rules, for free. A rule generator is never told any of it, so it coins
`shut` beside an unused `closed`, and writes a second way to light a lamp that
nothing can ever put out.

**The source.** `rulecheck.scan(rulecheck.of_world(root))`, computed once per
`rule_gen.learn` call. It is pure dictionary work, but it covers every rule, so
the soak (Phase 8) measures it in real play. If it is too slow, it is
cached on the world's `ndb` and cleared by `rulebooks.add`,
`verbs.register_state` and `verb_gen.store_rule`.

**The slice for this attempt.** A new
`rulecheck.relevant(findings, world_root, verb, bound)` keeps only what bears on
this verb and these objects. "Relevant states" means the states the bound
objects are in now, the states their kinds have been in (`kinds.states_of`),
and every other member of those states' groups.

| Finding | Shown when | Says |
|---|---|---|
| `pairs` (stuck, missing, group) | `suggest._verb_for_state(missing)` is this verb, or either state is relevant | "Nothing in this world can make anything `unlit`. It and `lit` are one condition (`light`). If `snuff` is what does that, say so." |
| a proposal waiting in `suggest.queue` | its `action` is this verb | the proposal's name and why it was proposed, adoptable through `file_rules`' `adopt` field |
| `unsettable` (required by rules, set by none) | the state is relevant | "rules already require `unlocked`, and nothing sets it" |
| `one_way` (set, never undone) | the state is relevant | "`lit` can be set and nothing ever ends it. If this verb ends it, remove it." |
| `dead_vocabulary` | the state is in a relevant group | "already in the vocabulary and used by nothing: `closed`, `ajar`. Reuse before coining." |
| `self_defeating`, `inert` | the rule's action is this verb | "these rules about `open` can never fire / change nothing" |
| `no_rule` wants (§5.1) | the thing is bound here | "Bram wants the lamp lit, and nothing in this world can light it." |

At most six lines, in this order of priority: wants, pairs, proposals,
`unsettable`, `one_way`, unused vocabulary, broken rules. Not shown, because
this call can do nothing about them: `ungrounded` kinds, refusals, and `forked`.

**Adopt, don't rewrite.** When `suggest` has already derived the rule this verb
needs, writing it again is exactly the duplication this section exists to
prevent. So `file_rules` gains `adopt`, an enum of the ids of this verb's
waiting proposals, and its handler calls `suggest.accept` for each one. A model
accepting a derived rule is what `suggest.judge` already does, so ground rule 3
holds, and `accept`'s own rails still run.

**The wording** is the same everywhere: "only if this verb genuinely does
that". The finish validators (`validate`, `_self_defeating`) still run on
whatever comes back.

**Unused vocabulary helps the item generators too.** `make_item`,
`furnish_room` and `dress_character` get the `dead_vocabulary` states in groups
their kind has used, as a hint on `states`.

**For anyone who wants the whole picture:** a `world_faults(verb, kind)` lookup
tool, available to generators and characters alike (the open-sandbox
principle), returns the same slice without the cap. With no arguments it
returns the whole of `worldcheck`'s report.

**How we will know it helps.** The baseline ratchets in
`tests/fixtures/baseline.py` already track `one_way` (should fall), `unsettable`
(should reach zero), `pairs` and `dead_vocabulary`. The §3.1 measurement line
records whether an accepted rule set a hinted state, or adopted a proposal. And
`inert` and `forked` should not rise. If they do, verbs are having unrelated
fixes bolted onto them.

---

## 6. NPC tools: enriched schemas, and answers the model can see

### 6.1 What each existing tool gains

| Tool | Today | Changes |
|---|---|---|
| `move` | `direction` from the exits here | Description, per call, names the unbuilt exits and says a new place takes a while. Result: where they arrived, or the refusal `_walk` now writes to `_note_to_self`. |
| `say` | `message` with no description | Describe `message`. Add an optional `to`, from the people present, which goes straight into `addressed` (`recognition` stays for speech that names nobody). |
| `get` | `object_name` from `room.contents` | Say who owns each choice in the description (from `ownership`). Result: success, or the text of the `attempt.permitted` refusal. **Open question (§10):** things placed in or on an open container are not in `room.contents`, so a character cannot pick up the letter in the tray (check `relations`). |
| `give` | both arguments closed | Result: success, or `ownership.give`'s refusal. |
| `emote` | `action` described | Add `maxLength`. No other changes. |
| `attempt` | free text, deliberately | Stays free text. Drop "Actions this world already understands" from the system prompt, and point to `list_known_verbs` instead. Name the engine verbs handled here (wear, remove, wield). Result: what the actor was told, delivered through `_attempt_verb`'s `on_done` (§10.6). |
| `check_traits` | `person` from the people present, `required: []` | **Becomes a lookup.** It answers within the same turn, and `_note_to_self` is no longer needed. Add `myself` to the choices and make `person` required. |
| `answer_quest` | `accept` only | Description, per call, gives the request's title, terms, reward and deadline from `quests.offered_to`. That text leaves `_want_line`. |
| `offer_quest` | `person` from people with a free slot | Give `time_limit_seconds` a minimum and maximum. The `offer` description lists what the character is actually carrying, so rewards are real. Result: the quest's title, or why no quest could be made (today, logged only). |
| `set_goal` | `want` free text | Description points to `find_rooms`. Result: the goal as `goals.describe` says it, or "that could not be made into something to work at" (today, logged only). |
| `create` | `name` free text | Result: made, already here, or refused. It is `_note_to_self` in part today. |
| `destroy` | `object_name` from things within reach | Description says exits and people are protected. Result: `effects.apply`'s lines. |
| `modify` | `new_name` and `new_description` undescribed; applied silently | **Kept, and held to the same rules as everything else** (§6.3). Descriptions for both fields carry the naming rule in brief; at least one of the two is required. Result: what changed, or the complaint. |

### 6.2 Structural changes

* **Enforce the tool limit in code.** "You may call 0-3 tools per response" is
  prose today, and `_execute_tool_calls` runs as many as arrive. Tools that
  act count against the limit and lookup tools do not. Calls past the limit
  get the result "not done: that is enough for one turn".
* **Derive one tool list from the other.** `NPC.KNOWN_TOOLS` repeats the names
  in `NPC_TOOLS`, so `KNOWN_TOOLS` is computed from it.
* **Merge the two copies.** `generate_npc_idle` and `generate_npc_reaction` are
  the same function twice, down to the tool-call parsing, and differ only in
  their closing user line. They become one function on `converse`, and
  `_execute_one` becomes the handlers.
* **Hold the guard.** `ndb.reacting` stays up for the whole loop, for the
  reason its docstring gives: releasing it before the tools have run lets a
  character answer the conversation its own sentence started.
* **New lookup tools for characters:** `examine`, `recall`, `list_known_verbs`,
  and `check_traits` (moved to lookups).

### 6.3 `modify`, held to the rules

Today the tool builds a `modify_object` effect and hands it to
`effects.apply`. That guards protected objects and re-settles tokens in a new
description, and nothing else: the naming rule, which every generator is held
to, is never checked. The old name stops finding the thing. Nobody in the room
sees it happen, and nobody remembers it.

The checks go **in one place, shared by the tool, the effect and the rule
generator**. That way a character, a rule and a generated rule cannot differ
about what renaming a thing may do. The function is
`effects.modify_complaints(obj, new_name, new_description, world_root)`, and
it checks:

* **Permission.** `attempt.permitted(actor, "modify", {"direct": obj})`, so a
  world's check rules can refuse it, as they refuse `get` and `give`. Ownership
  rules therefore apply.
* **The naming rule.** `verbs.name_contradicts_states` on the new name. Then
  `verbs.adopt_named_states`, exactly as for a generated name.
* **The description.** Token syntax, and word lists that exist, through the
  same check `try_text` uses. Then `tokens.settle`, as now.
* **Protected objects.** `effects._protected`, as now.

Where each caller sends a complaint:

| Caller | Complaint goes to |
|---|---|
| the NPC tool | the tool result |
| the effect, at run time | refuses and logs, as a protected object is refused today |
| `rule_gen`'s finish handler, for a literal `new_name` written into a rule | a complaint to the model (§4.2) |

After a successful change:

* **The old name becomes an alias,** as `generate_item` keeps the requested
  name, so anything that remembered the old name still finds the thing.
* **Stored narrations are forgotten** (`effects.forget_narrations`), if the
  effect does not already do this. A narration written for "the brass key" is
  wrong about "the bent key".
* **It is announced as an event**, with a room template, and **remembered by
  whoever saw it**, through `_acted` and `_witnessed_by_players`, as `get` and
  `give` are. Changing what a thing is called or looks like is visible.

---

## 7. Busy notices

### 7.1 Where somebody waits on a model today

| Where | Said at the start | Model calls, worst case |
|---|---|---|
| `unknown_cmd` into `attempt` (every verb) | "You try to {raw}..." (through `on_wait`) | `actions.learn`, `rule_gen.learn`, `ask_admission`, `narrate`: 4 × 30 s |
| `look_take_cmds._ai_look` | "You look carefully for {query}..." | existence, then item: 2 × 30 s |
| `look_take_cmds._ai_take_nonexistent` | "You look for {query}..." | 2 × 30 s |
| `look_take_cmds`, take validation (`validate_object_takeable`) | nothing | 1 × 30 s |
| `exits.Exit.at_traverse` | "Generating room to the {key}..." | name (up to 3 tries) plus description: 4 × 60 s |
| `worldgen_cmd.node_generate`, and `world_cmds` `worldgen` | "Generating {title}..." | plan, name, description: 3 × 60 s |
| `world_cmds` `npcgen` | "Generating NPC for this room..." | 1 × 30 s (broken, §2.1) |
| `world_cmds` `rules judge` | "Asking about N suggestions..." | 1 × 30 s (broken, §2.1) |
| `goal_cmds` | "Working out how you would {want}..." | 1 × 30 s |
| `memory_cmds` `remember` | nothing | recall plus 1 × 30 s |
| `world_cmds` `commonsense fetch` | "This is a large download..." | a long download |
| `model_menu` model list | nothing | 1 × 15 s |

With tool loops, every row that goes to a model can take up to its round
budget times the time shown. Room naming at a budget of 8, with three
attempts' worth of complaints inside it, can run for several minutes.

### 7.2 Shape

New module `world/busy.py`, reactor only:

```python
wait = busy.start(who, "working out how to pry the crate")
wait.add(other_traveller)        # an exit with several travellers waiting
wait.stage("deciding what prying does")
wait.done()                      # idempotent
busy.closing(wait, on_success)   # wraps a callback so it closes the wait first
```

* **Only players.** `start` and `add` accept a waiter only when a person is
  behind it: a character with an account, or an account. A non-player
  character is refused at the door and never sent anything. An NPC cannot
  worry that the game has crashed, and a line in its history would be one more
  thing the next prompt has to read past. Travellers queued at an exit are
  added one by one, so the players among them are told and the characters are
  not. A wait with no waiters still tracks stages and closes normally. An NPC
  walking through an unbuilt exit simply tells nobody.
* **The notice.** Every interval (§7.3; default 10 seconds) while the wait is
  open, each waiter is told `Still {stage or doing}... ({elapsed} seconds)`.
  The prefix is always the same and there is no colour code, so a screen
  reader user learns to recognise the line quickly and can skip past it. The
  interval is read per waiter, so two players at one exit each get their own
  setting.
* **It stops** on `done()`; on its own for a waiter with no sessions left (a
  disconnect); and at a **safety limit of 15 minutes**. That limit exists only
  to catch a callback that was lost: every loop is bounded by rounds times
  timeout, so real work always ends before it. At the limit it logs the job
  and stops without a message. **It never cancels the work**: a room arriving
  late is still a room.
* **A clock can be injected.** `task.LoopingCall` runs with a `clock`
  argument, so a test passes a `twisted.internet.task.Clock` and advances time
  itself. Nothing persistent is involved: no Script, and nothing in `db`.
* **The loop reports stages.** `converse(..., wait=)` calls `wait.stage` once
  per round, using the `doing` phrase of whichever tool ran ("looking up this
  world's states", "checking the name is free"). So a long wait says what it is
  doing, not merely that it is still going.
* **A wait spans the whole job.** It is opened where the player starts waiting
  and closed where the answer is delivered, not per call. A verb that needs
  four calls is one wait, with one elapsed time, and four stages.

### 7.3 The `busy` command

In `commands/account_cmds.py`, beside `CmdApiKey`, and added to the account
cmdset in the same place, so it works in and out of character:

```
busy            how often you are told something is still working
busy <seconds>  set it; 5 to 120
busy off        never
```

* Stored on the account as `db.busy_interval`. It is a preference of the person
  at the keyboard, not of any one character. Unset means the default, 10.
* The help text is the command's docstring, as with every other command.
* It is a single-purpose command on purpose, for now. A general `settings`
  command that gathers this, `apikey` and similar preferences is recorded in
  `future-plans.md`, and `busy` should fold into it when that is built.

### 7.4 Call-site changes

* **`unknown_cmd`**: open the wait in `waiting()`, the `on_wait` it already
  passes, and close it in `deliver`. `attempt` passes the wait down so
  `actions.learn`, `rule_gen.learn`, `ask_admission` and `narrate` can set
  stages. *As built:* no `wait=` parameter was needed. `attempt` already
  threads a `waiter` through every step that goes to a model, so the waiter
  takes a stage phrase, and `attempt` and `_in_turn` gain one `on_stage`
  callback. Nothing else changed shape.
* **`look_take_cmds`**: open in `_ai_look`, `_ai_take_nonexistent` and the take
  validation; close in `_finish_look` / `_finish_take`, `_gen_error`,
  `on_invalid` and `on_error`.
* **`exits.Exit.at_traverse`**: one wait per exit being built. Each traveller
  who joins `waiting_travelers` is offered to `add`, which keeps only players.
  It closes in `on_success` and `on_error`.
* **`worldgen_cmd.node_generate`** and **`world_cmds`**: the `worldgen`,
  `npcgen`, `rules judge` and `commonsense fetch` commands.
* **`goal_cmds`**, **`memory_cmds`** and **`model_menu`**.
* **NPC-initiated work** (`_attempt_verb`, `_conjure`, `_set_goal`,
  `_offer_quest`): no wait is opened. When a player is waiting on the same
  thing, such as an exit an NPC started building, the wait is opened by the
  player's own path.

---

## 8. Tests

**Support additions** (`tests/support.py`):

* `tool_reply(*calls, content=None)` builds a reply carrying `tool_calls`, and
  `tool_call(name, **args)` builds one entry (not `call`, which would read as
  `llm.call`).
* `replying` records `tools` and `tool_choice` per call:
  `recorder.tools(i)`, `recorder.tool_choice(i)`, and `recorder.tool_results(i)`
  (the `role: tool` messages that call was sent).
* `fake_call` accepts `tool_choice`.
* A clock helper for `busy`.
* `FakeSponsor` gains a model record, with or without `"tools"`, for the menu
  filter and the refusal at call time.

**Per phase**, all in the tier that needs no model:

* **The loop:**
  * ends on an accepted finish;
  * sends a complaint back and accepts the corrected answer;
  * a reply with no tool calls gets the nudge, not a parse;
  * forces the finish tool on the last round;
  * caps calls per round;
  * caches a repeated lookup;
  * a handler that raises becomes an error result;
  * an asynchronous handler resumes the loop;
  * a round that fails on the network reaches `on_error` with the ledger still
    written down;
  * the measurement line and the per-job totals record rounds.
* **Tools required:**
  * the `models` menu hides a model whose published parameters lack `tools`,
    and shows one that publishes none;
  * a saved toolless model fails its job with a message naming the job.
* **Schemas:**
  * every enum matches the tuple it is built from;
  * a tool whose only choice would be empty is left out;
  * `scope`'s enum is exactly `menu()`'s tokens;
  * a growing register past the enum cap becomes an open field whose handler
    complains about a non-member.
* **Near-duplicates:** declaring `shut` beside `closed`, or `vigour` beside
  `stamina`, is a complaint naming the existing word; on the final round it
  folds, as today.
* **Each generator** is shown the replies its existing tests already script
  through `replying` (`test_worldgen`, `test_rule_gen`, `test_verb_gen`,
  `test_actions`, `test_naming` and the rest), sent again as finish calls, and
  produces what it produces today. That is the regression net. The exported
  registers in `tests/fixtures` are world data, not replies: they feed the
  enum and near-duplicate tests, not these.
* **`modify`:**
  * a name carrying a state is refused with the naming rule;
  * a check rule refusing `modify` is honoured;
  * the old name still finds the thing;
  * the room is told, and the players present remember it.
* **Busy:**
  * no line before the interval;
  * one line per interval with the stage;
  * a character with no account is never added and never sent anything;
  * stops on `done`, on disconnect, and at the safety limit;
  * a closing wrapper closes on success and on error;
  * each waiter's own interval is honoured, and `busy off` means no line.
* **`busy` command:** show, set, the bounds, off, and the default when unset.
* **`rounds` command:**
  * every job, one job in full, and one world;
  * the average, the most, and the forced count match the loops a scripted
    sponsor ran;
  * `clear` empties the loop figures and leaves token totals untouched;
  * a job with no loops yet says so rather than showing zeros.
* **Wants and their blockers:**
  * `planner.blocker` gives each of its four reasons for a scripted world;
  * a player's active quest counts, as well as an NPC's goal;
  * the hint gives the exact words an `object` or `kind` condition accepts;
  * the hint disappears once the thing exists anywhere;
  * nothing is hinted to the giver's room, or to a character's own dressing;
  * with no ConceptNet, only the capped fallback is shown.
* **Faults:**
  * `rulecheck.relevant` over the exported worlds keeps exactly the findings
    bearing on a chosen verb and kind (the fixtures are real faults);
  * `adopt` accepts a waiting proposal through `suggest.accept`, and an id not
    in the queue is refused;
  * the six-line cap and its order of priority hold.
* **`advise`** tells a player that a wanted thing exists nowhere.

---

## 9. Phases

Each phase leaves the game working and its tests passing.

### Phase 0: groundwork, no change in behaviour

* Fix `npcgen` and `rules judge` to pass a sponsor. `rules judge` uses
  `sponsor.of_world(root, actor=caller)`, so the world pays for judging itself
  (§10.5).
* Delete `verb_gen.learn_rule` and anything only it uses.
* `llm.call(..., tool_choice=None)`.
* The `tests/support.py` additions.
* Derive `NPC.KNOWN_TOOLS` from `NPC_TOOLS`.
* **A baseline for the soak to be compared against.** The ledger gains seconds
  per call, per job: `llm.call` times its own request, and `_spent` carries the
  figure beside the usage. Then play a fresh world on the unchanged generators,
  and keep tokens and seconds per job, plus `rule_gen`'s dropped-rule log lines
  per verb learned. Without this the soak has nothing to be faster or slower
  than.

**Done when** `npcgen` makes a character, `rules judge` returns verdicts, and
no test references `learn_rule`.

### Phase 1: busy notices

`world/busy.py`, the `busy` command, and every call site in §7.4. This comes
first because it is useful on its own, needs nothing from the loop, and the
loop makes waits longer.

**Done when** a player typing a new verb against a slow fake model sees a
notice at their own interval until the answer, and nothing afterwards; and an
NPC waiting at the same exit is sent nothing.

### Phase 2: NPC tool schemas enriched (no loop yet)

§6.1's descriptions, enums, bounds and required fields; the tool limit enforced
in code; the two reaction functions merged into one; §6.3's
`modify_complaints` shared by the tool and the effect, with the alias, the
announcement and the memory. Results still go to working memory.

**Done when** the tool schemas sent in a reaction match §6.1 for a scripted
room, and a character renaming a thing is seen, remembered, and held to the
naming rule.

*As built:*

* **Placed things were out of reach,** as §10 suspected. `_nameable` read
  `room.contents`, and `get` searched the room, so no character could take a
  letter lying in an open tray. `get`'s choices now come from
  `relations.reachable`, and a placed thing is taken through
  `relations._take_from`, the same door a player's "get the letter from the
  tray" goes through.
* **`emote` has no `maxLength`.** `maxLength` is not in the conservative
  dialect (§4.1), so the description asks for a short phrase instead.
* **The `modify_object` effect is checked, but not asked permission.**
  `modify_complaints` runs on it, and refuses a name that carries a condition
  or a description asking for a list nobody keeps. `attempt.permitted` does
  not, because a rule's effect is the outcome of a verb the world has already
  allowed. The character's tool asks permission itself.
* **`check_traits` is offered only beside somebody else.** A character's own
  figures are already in its prompt, so "myself" alone is not worth a tool.
* **Unexplored ways out stay in the room context** as well as in `move`'s
  description, until the room context is reworked with lookup tools
  (Phase 4).

### Phase 3: the loop and the toolbox, tools required

`llm.converse`, `world/toolbox.py`, the `models` menu filter and the refusal at
call time, the stage reports to `busy`, the measurement line with its ledger
figures, and the `rounds` command (§3.5). First user: the NPC turn. Tool results are returned in-loop,
`check_traits` becomes a lookup, and the `_note_to_self` routes for refusals
become results.

**Done when** a character that checks somebody's traits and then acts on what
it found does both within one turn, and a toolless model can no longer be
chosen.

*As built,* in four commits (3a to 3d):

* **The loop** is `llm.converse` and `world/toolbox.py`, as §3.1 describes.
  Nothing parses JSON out of a reply's text: a reply with no tool calls while
  a finish tool waits is told to use it.
* **A round that only acted ends a turn.** With no finish tool, the loop goes
  round again only if a lookup ran, since only a lookup's answer is something
  the model needs before deciding. Acting and then being asked again would
  only buy more acting.
* **Toolless models** are refused once their record is known. `llm.call` does
  not fetch the model list itself, because that would add a request to every
  call; the list is fetched when the `models` menu opens, and a model nobody
  has listed is asked as ever, so the service refuses in its own words.
* **`attempt` answers at once, rather than waiting** for the attempt to
  finish (a change to §10.6). Some of `attempt`'s early returns never call
  back, and a turn waiting on one would leave the character thinking for
  ever, holding `ndb.reacting`. So the tool answers "underway", and what
  comes of it reaches the next prompt, as it always has.
* **A turn's `on_success`** is handed how often each tool was used, and
  releases the guard. The tools themselves have already run, so nothing
  executes the calls a second time.

### Phase 4: shared schemas and lookup tools

§4.1's schemas beside their modules, the enum cap, the near-duplicate
complaints, and every tool in §5 beside its module. Nothing uses them yet
except the NPC toolbox (`examine`, `recall`, `list_known_verbs`,
`world_faults`).

Also the free half of §5.1 and §5.2: `planner.blocker`,
`goals.blocked_wants` and `rulecheck.relevant`, plus the better `advise`
message and the give-up log line. Players get the first benefit here, before
any prompt changes.

**Done when** every row of §5 has a tool with a test, and `planner.blocker`,
`goals.blocked_wants` and `rulecheck.relevant` have tests over the exported
worlds.

*As built* (4a, 4b and 4c):

* **The lookups live beside their registers,** each module's
  `lookup_tools()` appended to its end, and `world/lookups.py` gathers them by
  name. `toolbox.py` gained `params`, `PAGE`, `paged` and `answering`, so every
  list tool pages the same way and every schema stays in the conservative
  dialect; a test walks every schema to hold it there.
* **A lookup is offered only where it can answer:** the dictionary's tools
  with a dictionary, `commonsense` with the corpus, `recall` with a character
  and a memory, `examine` and `name_taken` with a room.
* **`recall` asks which bank on the reactor and searches it off it,** since
  finding the bank reads the database and searching it is slow.
* **`rulecheck.relevant` takes the registers and the states near an
  attempt,** not the world. That keeps it as pure as the rest of `rulecheck`,
  and testable over the small worlds its own tests build; `states_near` is the
  half that reads the live world.
* **Characters were given `examine`, `recall`, `list_known_verbs` and
  `world_faults`,** beside the tools they act with.
* **`tests.support.tool_call` takes the tool's name positionally,** so a tool
  whose own argument is called `name` can still be given one.
* **The schemas sit beside the code that reads them:**
  * `effects.schema`, `conditions.schema` and `goals.schema`;
  * `clothing.spec_schema` (with `worn=True`, a garment must give its
    `clothing_type`);
  * `token_lists.schema`, `pronouns.set_schema`, `traits.declaration_schema`
    and `verbs.state_declaration_schema`.

  Each fixed field is an enum built from the tuple its code checks against,
  and a test holds the two together.
* **A field that depends on the type is optional, and its description says
  which types use it.** An effect's `to`, for example, means one thing for
  `move_object` and another for `set_exit`. The dialect has no `oneOf`, so
  whoever validates the answer enforces what the type needs, as
  `rule_gen.validate` already does.
* **`toolbox.choice` is the enum cap.** Up to `ENUM_MOST` (50) values it is an
  enum. Past that the field is open, and its description gives the count and
  the lookup that lists them. A world's traits and state groups go through it.
* **Near-duplicate complaints are one check per register:**
  * `verbs.near_duplicate_state`: a prefix spelling, as `register_state`
    folds it ("opened" onto "open"), or an adjective synonym ("shut" beside
    "closed");
  * `traits.near_duplicate`: only what `_matching` folds;
  * `token_lists.near_duplicate`: a list under another number;
  * `pronouns.near_duplicate`: a set by its subject form.

  `vocabulary.near_duplicates` puts them together for a finish tool to ask
  about a whole reply, and adds `claim`'s refusal of a trait and a state that
  share a word.
* **What the checks cannot catch:** another word for the same idea
  ("vigour" beside "stamina") is caught only for states, and only when the
  dictionary calls the two synonyms. For traits nothing knows the meanings are
  the same, so a model that does not look the register up can still coin
  one.
* **The traits' prefix fold is narrower than its docstring says.** The two
  names may differ by at most three letters, so "stam" folds onto "stamina"
  but "str" does not fold onto "strength". Left as it is; the tests use
  "stam".

### Phase 5: the verb pipeline

`actions.learn`, `rule_gen.learn`, `ask_admission` and `narrate` on finish
tools, with their prompt blocks removed; `rule_gen.validate` and the narration
template check send complaints back. `rule_gen.learn` gets §5.2's fault hints,
the `no_rule` wants from §5.1, and `adopt`.

**Done when** a new verb learned from a scripted model goes through
declaration, rules, admission and narration on finish tools, and a rule
refused in round 1 and corrected in round 2 is kept rather than dropped.

*As built:*

* **Four finish tools:**
  * `declare_action` (6 rounds): the roles, access and gates are enums. The
    sense is an enum of the dictionary's senses when there are two or more,
    and `verb_sense_prompt`'s menu has left the prompt. Rounds out falls back
    to `observe`, as a failed call did.
  * `file_rules` (8): the scope is an enum of `menu()`'s tokens, with
    `effects.schema`, `conditions.schema` and the declaration schemas nested.
  * `admit` (4): rounds out is an error, as unreadable JSON was.
  * `narrate` (6): rounds out takes the last narration as it stands.
* **`file_rules` runs `validate` and sends back what it would have dropped,**
  together with `vocabulary.near_duplicates` for its new states and traits,
  unknown `adopt` ids, and an answer that files nothing without saying why.
  When the rounds run out, the last answer is taken: what is valid in it is
  kept, and near-duplicates fold as the registers always folded them. A model
  that never called `file_rules` at all now counts towards `note_fruitless`,
  where unreadable JSON used to be an error that counted nothing; a network
  failure still counts nothing.
* **The prompt keeps the menu, what is already decided, and the objects.**
  The state and trait registers are behind `LOOKUPS` (states, groups,
  traits, `verb_info`, rules, `world_faults`, `kind_info`, `commonsense`,
  `find_rooms`). They are replaced by the states things of these sorts have
  been in, and by `rule_gen.hints`: `rulecheck.relevant` over one scan, this
  verb's waiting proposals, and `want_lines`.
* **`want_lines` shows a `no_rule` want only when its object is bound here,**
  and a `missing_thing` want only when ConceptNet ties the thing to a bound
  kind: `PartOf` or `AtLocation` read forward from the thing, or `HasA`
  from the kind. At most three.
* **`adopt` is offered only when this verb has proposals waiting,** since an
  enum cannot be empty. Adopting goes through `suggest.accept`, and an
  adopted rule counts as a rule for `note_fruitless`.
* **Narration complaints stop short of the plan.** A name written out, a
  placeholder that stands for nobody, and an unknown effect type are sent
  back. An article before a placeholder and a conjugated actor verb are not,
  because `events.repair` already mends them for nothing on the way in, and a
  round spent on them is a round a player waits through.
* **Tests answer by tool name.** `tests.support.finishing(narrate={...},
  file_rules={...})` answers whichever finish tool a call offers, so a script
  no longer has to predict which of the four questions an attempt asks.
  Eleven test files moved to it.
* **Not converted yet:** the modify naming rule inside `file_rules`
  (§6.3). A literal `new_name` in a `modify_object` effect is still checked
  only when the effect runs.

### Phase 6: items and rooms

`validate_object_existence` / `_takeable`, `generate_item`, `populate_room`,
`_generate_plan`, `plan_zone`, `_generate_name` (whose conversation built by
hand becomes complaints) and `_generate_description`. `populate_room` and
`_generate_name` get §5.1's wanted-thing hints, and the item generators get
§5.2's unused-vocabulary hint.

**Done when** a quest for a thing that exists nowhere can be finished by
exploring: a scripted world that builds a matching room produces the thing,
under words the quest accepts.

### Phase 7: characters, quests and the rest

`generate_npc` (whose name retries become complaints), `dress_npc`,
`formalise`, `formalise_goal`, `fact_gen.distil`, `suggest.judge`, and
`remember`'s `recall` tool. `dress_npc` gets §5.1's hint for what a character
might carry. Delete any `vocabulary_block` nothing uses any more.

### Phase 8: soak, then measure and tune

Measurement waits until everything is built, because every phase moves the
numbers the others produce. A generator given quest and goal hints may need
fewer lookups, a register moved behind a tool may need more, and a validator
that complains may add rounds while removing whole failed calls. Measuring one
generator in the middle would tune it against a world that is about to change.

**Play it for real.** At least two fresh worlds (ground rule 8): one a player
works through with quests and goals, and one mostly left to its characters.
Both on the models the account would normally choose.

**Read, with `rounds`, the measurement log line and the Phase 0 baseline:**

* the model, reasoning effort and service tier each job actually ran with,
  since every figure below means nothing without them;
* seconds per job, against the baseline: what a player actually waits;
* tokens per job, against the baseline: what it costs;
* average and worst rounds per job against its budget, and how often the
  finish tool had to be forced;
* which lookup tools are called, and which never are;
* hints shown against hints used (§5.1, §5.2);
* complaints fixed, against the baseline rate of rules dropped;
* the rulecheck ratchets in `tests/fixtures/baseline.py`, exported from the
  soak worlds;
* the cost of `blocked_wants` and `rulecheck.relevant` in the larger soak world.
  They are cached (§5.1, §5.2) only if the numbers say so.

**Then tune, from those numbers:** the round budgets (§10.3), the enum cap
(§4.1), and the caps on hints.

**If it is slow or costly, the remedies, cheapest first:**

1. **Lower the budgets** wherever the worst case is well under them.
2. **Send work nobody is waiting on to the flex tier.** OpenRouter takes a
   top-level `service_tier`: `"flex"` (half price, higher latency, lower
   availability), `"priority"` (`"fast"` is an alias; faster, more expensive),
   or `"default"`. Billing follows the tier that actually served the request,
   and the reply says which it was. Only some providers offer tiers (OpenAI,
   Anthropic for priority only, Google Vertex, Google AI Studio, and others),
   and support varies by model.

   **The tier follows who is waiting, not the job.** An NPC's `attempt` and a
   player's are the same `commands` job, and only one of them has somebody
   waiting. The busy wait (§7.2) already knows: a wait with a player in it is
   a player waiting, and anything else is not. So `converse` chooses the tier
   from `wait`:

   * **Nobody waiting**: NPC turns, `populate_room`, `dress_npc`, `plan_zone`,
     the world plan, `fact_gen`, an NPC's own attempts, and a room an NPC
     builds. These use the account's *background tier*.
   * **A player waiting**: that account's *waiting tier*.

   Two account-wide settings in the `models` menu, both unset by default, so
   nothing is sent until a player chooses. That follows `model_params`' rule
   that only what was set is ever sent. The rest of the work:

   * **Longer timeouts on flex.** Flex is slow by design, and `TIMEOUT` /
     `SLOW_TIMEOUT` were chosen for the default tier.
   * **The ledger records the tier that served each call**, so `rounds` and the
     spending figures can be read correctly.
   * **Check against a real flex endpoint** what happens when a request asks
     for a tier its provider does not offer.
3. **Set reasoning effort per job.** OpenRouter takes
   `reasoning: {"effort": ...}`, with `"none"`, `"minimal"`, `"low"`,
   `"medium"`, `"high"`, `"xhigh"` or `"max"`. A model's record has a
   `reasoning` object giving its `supported_efforts`, `default_effort`, and
   whether reasoning is `mandatory`. A yes-or-no admission or a line of
   dialogue does not want the thinking a rule does.

   It becomes one more per-job setting in `model_params`, beside temperature:

   * **A new kind of setting.** `Param` holds only bounded numbers, so it
     gains a choice-valued kind. It is stored as `reasoning_effort`, and sent
     as the nested `reasoning` object.
   * **Offered only where it means something.** Only for a model whose record
     has a `reasoning` object; choices limited to its `supported_efforts` (all
     of them when it lists none); never `"none"` when reasoning is
     `mandatory`.
   * **Shown, never sent, by default.** The model's `default_effort` is shown
     as its default, and nothing is sent unless the player set it, as with
     every other setting.
   * **The soak suggests values** per job, written into `models`' help rather
     than sent on anybody's behalf.
4. **Split jobs more finely**, so a player can give a fast, cheap model to the
   frequent and simple ones and keep a capable one for the rest. `commands` is
   the obvious candidate: it answers for `actions.learn`, `rule_gen.learn`,
   `ask_admission`, `narrate` and `suggest.judge`, which range from a yes or no
   to writing rules. A new job falls back to the model chosen for the job it
   came out of (`model_for("narration", "commands")`, the chain `model_for`
   already supports), so nobody's choices are lost. The new job appears in the
   `models` menu (`FUNCTIONS`) and in `rounds`.
5. **Put one hint back inline** (§3.3), for a job whose rounds are mostly one
   lookup it makes every time.

**Done when** budgets, caps and any new jobs are set from the soak's numbers,
and those numbers are recorded for the *As built* section.

#### The baseline, as recorded (2026-09-15)

World 6958, played from 14:31 to 15:05 on the Phase 0 code: timing on,
generators unchanged. 601 calls, every one timed, and 3,542 seconds of model
time in 34 minutes of play. That is more model time than play time, because
characters think while the player acts.

| Job | Model | Timed calls | Average |
|---|---|---|---|
| dialogue | inception/mercury-2.5 | 328 | 3.9 s |
| commands | google/gemini-3.1-pro-preview | 135 | 8.7 s |
| quests | google/gemini-3.1-pro-preview | 35 | 6.0 s |
| contents | google/gemini-3.7-flash | 23 | 9.9 s |
| items | google/gemini-3.1-pro-preview | 21 | 12.1 s |
| validation | ibm-granite/granite-4.2-8b | 21 | 7.2 s |
| rooms | google/gemini-3.7-flash | 20 | 5.9 s |
| naming | google/gemma-4-31b-it | 17 | 4.8 s |
| npcs | google/gemini-3.1-pro-preview | 9 | 14.6 s |

Eight of the 609 timed calls came from other worlds. The slowest single call
took 18.3 seconds (npcs).

From the server log for the same session:

* 2 rules dropped, both for `teacup.n.01` being "too near the top of the
  taxonomy";
* 1 `cannot_say` (`order`);
* 2 verbs that learned no rule (`drink`, `order`);
* 3 NPC turns that failed with `'choices'`: the service sent back an error,
  and `llm.call` passed it on without reading it.

**What this baseline cannot say,** and what the soak therefore needs:

* **Tokens per job within one world.** The ledger totals by job and by world,
  but not by job within a world, so these tokens are mixed with older worlds.
  The soak snapshots `spend_totals` before it starts and compares afterwards.
* **Waits, as opposed to calls.** A verb that needs four calls is one wait.
  `busy.Wait` knows how long each wait lasted, so it logs that when it
  closes, and the soak reads player waits from there.

### Phase 9: documentation

* Remove the two `future-plans.md` items. Trim "tools for the models" to
  whatever remains, which may be nothing.
* Update `tokens-and-phrases.md` §5.7 and the decision it records.
* Note in `models`' help that only tool-capable models are listed.
* Mark this plan built, with an *As built* section, following the style of the
  other plans.

---

## 10. Decisions on the record

1. **Busy notices have a `busy` command** (§7.3), for now. A general
   `settings` command is recorded in `future-plans.md`, and `busy` folds into
   it when that is built.
2. **Characters keep `modify`**, held to the rules everything else follows, in
   one check shared by the tool, the effect and the rule generator (§6.3).
3. **Round budgets are generous to start, then measured** (§3.1, Phase 8):

   | Budget | Jobs |
   |---|---|
   | 4 | yes-or-no calls a player waits on: existence, takeability, admission |
   | 6 | `narrate`, `actions.learn`, `generate_item`, `formalise_goal`, `fact_gen`, `judge`, `remember` |
   | 8 | `rule_gen.learn`, room naming and description, `generate_npc`, `formalise`, an NPC turn |
   | 10 | `populate_room`, `dress_npc`, `plan_zone`, the world plan, which nobody waits on |

   The finish tool is forced on the last round of each. The numbers are
   expected to come down once the ledger says how many rounds models actually
   use.
4. **Every register is a tool.** The prompt keeps the subject, the
   instructions, and hints specific to this thing (§3.3). Closed fields keep
   their enums up to the cap (§4.1). New vocabulary is checked against the
   register and near-duplicates are sent back (§3.3).
5. **The world pays for `rules judge`**: `sponsor.of_world(root, actor=caller)`.
6. **A character's `attempt` answers at once** that it is underway, and what
   comes of it reaches the next prompt. The decision was to wait for it
   through `on_done`; as built it does not, because some of `attempt`'s early
   returns never call back and a turn waiting on one would never end (Phase 3,
   *As built*).
7. **Busy notices go only to players.** Non-player characters are refused as
   waiters and never sent anything (§7.2).
8. **Tools are required.** Toolless models are left out of the `models` menu,
   and a saved one fails with a message. There is no single-shot fallback, and
   the prompt blocks are deleted as generators convert (§3.2).
9. **NPC give-ups are unchanged for now.** An NPC still drops a goal after
   `GOAL_STALL_LIMIT` (10) idle turns with no step, even when the only thing
   missing is a thing the world might yet make. That is usually long before a
   room holding the thing is built, but keeping such a want alive would bring
   back the model call on every idle turn that giving up exists to stop. The
   give-up log line records the reason, so we can count how many are for a
   `missing_thing`. Player quests, which matter most here, do not expire this
   way.
10. **A wanted thing is never hinted to the giver's room**, and there is no
    further distance rule (§5.1). Revisit if quests turn out too easy.
11. **`rule_gen` may make a wanted thing only through a ConceptNet relation**
    to the kind of an object the verb acts on (§5.1). If that proves too loose,
    drop `missing_thing` from `rule_gen` and keep only `no_rule`.
12. **Players read round counts with a `rounds` command** (§3.5), built in
    Phase 3 beside `busy`. It is single-purpose until commands are regularised,
    which `future-plans.md` already covers.
13. **Measurement happens once, at the end** (Phase 8), after every generator
    is converted, because each phase changes what the others cost. If it is
    slow, jobs may be split more finely, falling back to the model already
    chosen for their parent job, so players can give fast models to more of
    them.
14. **Background work can go to the flex tier, and reasoning effort is a
    per-job setting**, both as soak remedies (Phase 8). The tier follows
    whether a player is waiting, which the busy wait already knows, not which
    job is running. Both are unset by default, so nothing is sent until a
    player chooses.

### Still open


---

## 11. Risks

1. **Providers disagree about schemas.** Large enums, nested objects and
   `additionalProperties` are treated differently. Contained by the
   conservative dialect and the enum cap (§4.1). With no fallback, a model
   that mishandles a schema fails loudly, and the fix is a schema change, not a
   second path.
2. **Cost grows with rounds.** Every register is now a lookup, and every
   lookup resends the conversation. Contained by the lookup cache, the
   per-round and per-job measurement, and the soak (Phase 8), which must pass
   before this plan is called built.
3. **Models skip lookups and coin duplicates.** Contained by the near-duplicate
   complaints (§3.3) and by enums on every closed field.
4. **Latency for players.** Budgets have been doubled, so a slow model can
   take longer than today. Contained by Phase 1 going first, stage-aware
   notices, and measurement.
5. **Small models may look things up forever and never submit.** Contained by
   forcing the finish tool on the last round and caching repeated calls.
6. **Some providers ignore a forced `tool_choice`.** With no content parsing,
   that loop ends in the generator's existing fallback (§3.1). If it turns out
   to be common for a model people want to use, the menu filter is the place
   to address it, not a second parser.
7. **Players lose models they had chosen.** Toolless models leave the menu,
   and a saved choice fails with a message naming the job. That was accepted in
   §10.8: those models would do this work badly.
8. **Stalling the reactor.** Anything slow is `threaded`. A handler on the
   reactor does what the prompt builders already do there today, and no more.
9. **World text in tool results.** Descriptions, token lists and names that
   players wrote reach the model through lookups. They already reach it
   through the inline blocks, so this is not a new exposure. Results are
   always labelled as data.
10. **Recursion in tests.** A synchronous `fetch` makes each round a nested
    call. At a budget of 10 this is still shallow. A test that runs a loop to
    its full budget covers it.
11. **Hints bend what gets made.** Every mine gains ore, and every verb learned
    near a lamp tries to put it out. Contained by filtering on relevance, the
    caps, "only if it genuinely does", hints that clear themselves once
    satisfied, and the `inert` and `forked` ratchets, which rise if unrelated
    effects are bolted onto verbs.
12. **Hints make quests too easy.** A wanted thing turning up in the next room
    over. Contained by the rule against hinting the giver's room (§10.10),
    which is to be revisited if quests prove too easy.
13. **Scan cost.** `blocked_wants` walks the world, and `scan` reads every
    rule, once per call. Measured in the soak (Phase 8), and cached on `ndb`
    only if the numbers say so.

---

## 12. Out of scope, deliberately

* **New acting tools for characters to match player commands** (`follow`,
  `drop`, `put`, `wear` as its own tool). No prompt needs them, and `attempt`
  already reaches the verbs.
* **A general `settings` command.** Recorded in `future-plans.md`; `busy` is
  its first candidate.
* **Exposing the toolbox over MCP** (the `future-plans.md` item). The `Tool`
  registry is the shape that work would use: context-built schemas,
  JSON-serialisable results, and a `threaded` flag. Nothing here builds a
  server.
* **`response_format` / structured outputs.** Tools are required anyway and do
  the same job.
* **Streaming partial output to a waiting player.**
* **Mass kinds, plural objects,** and anything else that changes a reply shape
  rather than how it is asked for.
