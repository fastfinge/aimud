# Development plan: rulebooks

The working document for the change argued in
[rules-and-rulebooks.md](rules-and-rulebooks.md) and specified in
[rulebooks-from-inform.md](rulebooks-from-inform.md). Those two say *why* and
*what*; this one says in what order, how each piece is known to be finished, and
what tests hold it up.

Read the specification for any detail. Section references below are to it.

---

## 1. The change, on one page

A verb rule today is one JSON object per verb per world, written at first use,
never revised, forbidden from mentioning a room. It becomes a **rulebook**: small
named rules, each filed against whatever it is a fact about -- an object, a kind,
a room, a zone, the world -- gathered per attempt and run in four phases, most
specific first. Actions are declared separately with their arity. Conditions
become one language shared by rules, goals, quests and the planner.

```
                    ┌─ 0. test harness + one model-call seam ─┐
                    │                                         │
   1. lexicon: kind anchors, verb senses                      │
            │                                                 │
   2. rooms and zones get kinds and states                    │
            │                                                 │
   3. conditions.py  ──────────┬──────────────┐               │
            │                  │              │               │
   5. actions.py          4. consistency   11. planner        │
            │                  scan           upgrades       │
   6. rulebooks.py              │                             │
            │                   │                            │
   7. CUTOVER: standard rules + attempt phases + `rules`      │
            │                                                 │
   8. generation prompts ── 10. counters + suggestion queue ───┘
            │
   9. effect vocabulary (standing, ordered by need)
            │
  12. commonsense.py (independent; last)
            │
  13. instrumented soak: better data, and every baseline re-measured
```

Phases 1, 2, 4 and 9 are useful on their own and improve the game whether or not
the rest lands. Phase 7 is the only irreversible-feeling step, and §7.4 below is
its rollback. Phase 13 is the only one that deliberately costs money, and the
thing it buys is the evidence that any of this worked.

---

## 2. Ground rules, which are acceptance criteria for every phase

No phase is done if it breaks one of these. They are drawn from the existing
code's own contracts, and each one is a test in tier A or B.

1. **The steady state costs nothing.** A world that has learned a verb spends no
   model call to use it again. Gathering, ordering and checking are dict lookups
   and a sort.
2. **A missing corpus degrades, never breaks.** `lexicon.py`'s contract --
   "nothing here is load-bearing [...] a missing dictionary makes the world
   slightly clumsier. It must never make the world impossible" -- extends to
   ConceptNet and to kind anchors.
3. **Check rules are monotone.** Adding one can only make an action stricter. A
   derived check rule may be installed; a derived carry-out or instead rule may
   only be proposed (§10.1).
4. **Every effect is invertible.** `conditions.achieves` must be able to read it
   backwards, or the planner silently stops working for goals that need it
   (§11.1).
5. **No model writes code**, and every slot a model fills is a closed identifier,
   a number, a boolean, a condition, or an effect -- except two prose fields that
   exist to be read by people.
6. **Scopes are closed identifiers.** No free text in a scope, ever.
7. **Determinism.** Same world, same attempt, same rule order. Every tie in the
   specificity sort is broken, down to the id.
8. **No migration.** Worlds are reset for this, which is the practice
   `kinds-and-affordances.md` already set: "worlds are reset for this. There is
   no migration." There is one player and one tester, and a fresh world is a
   better test bed than a converted one. Accounts, API keys, model settings and
   memory banks live outside a world and are untouched by `worldreset`, so
   nothing has to be re-entered.

   The distinction that matters: **the existing rule corpus stays valuable as
   test data even though the worlds do not.** 326 rules, 58 settled kinds and
   81 invented states are the best regression and measurement material
   available, and reading them as fixtures asks nothing of the worlds that
   produced them (§3, 0.6).

   (The "307 kinds" quoted in `kinds-and-affordances.md` is a different figure
   and not this corpus: it was measured *before* kinds existed, by counting the
   head nouns of 724 objects to project how many kinds they would settle into.
   What the database actually holds now is 58 `kind_specs`, because three of the
   seven worlds predate the change and the rest are young. Worth keeping
   straight, since one number is a projection and the other is a count.)

---

## 3. Phase 0 — Testability, and why it is first

> *We have no repeatable tests and keep inventing them.*

There is a structural reason for that, and it is worth fixing before anything
else: **there is no seam to test against.** `_call_openrouter` is defined six
times, in `verb_gen`, `worldgen`, `npc_gen`, `item_gen`, `quest_gen` and
`fact_gen`, and there are 25 `deferToThread` call sites. Faking a model reply
today means patching six functions and knowing which one a code path reaches.

**0.1 One call site.** Extract `world/llm.py`: one `call(api_key, model,
messages)`, one place where `model_params` is applied, one place where retries
and errors are shaped. The six copies become imports. No behaviour changes, which
is what makes it safe to do first.

**0.2 One async seam.** A single `world/llm.py:defer(fn)` wrapping
`threads.deferToThread`, so tests can run callbacks synchronously instead of
patching Twisted in 25 places. Evennia ships `mockdelay` and `mockdeferLater` in
`evennia.utils.test_resources` for exactly this.

**0.3 The harness.** `aimud/tests/`, mirroring `world/`, plus
`aimud/tests/fixtures/`. Base classes from `evennia.utils.test_resources`
(`EvenniaTestCase` for tier A, `EvenniaTest` for tier B, `EvenniaCommandTest` for
command tests).

**0.4 The tiers, and how they are marked.** Django's own `@tag` decorator, which
needs no new dependency -- `evennia test` passes unknown arguments straight
through to Django's test command, and Django 6's runner supports `--tag` and
`--exclude-tag`.

| Tier | Tag | Needs | Runs in CI | What it is for |
|---|---|---|---|---|
| **A** | `unit` | nothing -- no DB, no network | **yes** | pure functions: conditions, ordering, parsing, the lexicon |
| **B** | `world` | the Evennia DB; no network | **yes** | effects, relations, gear, the attempt pipeline with replayed model replies |
| **C** | `llm` | a real key, real money | **no** | that prompts still produce answers the parsers accept |

```bash
evennia test --exclude-tag=llm .     # CI and batch: free, deterministic
evennia test --tag=unit .            # the inner loop, seconds
evennia test --tag=llm .             # deliberate, costs money, needs a key
```

Tier C tests additionally `skipUnless` a key is configured, so a checkout with no
key reports skips rather than failures.

**0.5 Cassettes: the trick that moves work from tier C to tier B.** Every
generator asks for JSON and parses it through `model_json.parse_object`. So a
recorded reply replays perfectly: capture real replies once (a tier C job, run
deliberately), store them under `tests/fixtures/replies/`, and have tier B replay
them through the real parsing, validation, renaming and application code.

That is where most of the historical bugs in this project live -- `_SaverDict`
refusing to serialise, `_apply_renames` missing a branch, a prompt asking for a
field the parser does not read. **Those become deterministic, free tests.** What
stays in tier C is only the question "does a live model still answer in the shape
we ask for", which is the one thing a cassette cannot tell you.

**0.6 World fixtures.** Export an anonymised snapshot of the development
database's rules, kinds and state vocabularies to
`tests/fixtures/worlds/*.json` -- 326 rules across seven worlds. Tier A tests
then assert against real generated data rather than invented examples, which is
the other half of why tests keep being reinvented: the examples in them were made
up, so they proved nothing about a real world.

**Do this before the first `worldreset`.** Worlds are disposable (§2.8) and this
corpus is not: it is the only generated rule data that exists, it is what every
measurement in all three of these documents was taken from, and a reset ends it.
An afternoon's export, and irreplaceable afterwards.

**And it is interim.** It was produced by the engine this plan replaces, so it
describes rules nobody would write again. It is scaffolding: good enough to build
against, due to be replaced by a corpus from the new engine (phase 13). Which
means the way tests use it decides how expensive that replacement is, and there
are two kinds of fixture with two different futures:

* **Shape fixtures -- assert properties over the corpus, never facts about one
  record.** "Every `requires` block converts and evaluates", "every kind resolves
  to something closed", "no rule references an unknown effect type". These
  survive a data swap untouched, because they are about the code. A test that
  asserts rule 47 requires `powered` does not survive, and rewriting forty of
  those is how a fixture replacement turns into a week.
* **Baselines -- recorded observations, not invariants.** 72% one-way states, 85
  refusals, 10% causative coverage. These are facts about *those* worlds, and the
  whole point of the work is to change them. Assert them as a **ratchet** with a
  direction of travel -- refusals must not rise, one-way states must not rise,
  coverage must not fall -- and keep the numbers in one file that is expected to
  be rewritten rather than scattered through assertions that will look like
  failures the moment the design works.

The second bullet is the trap worth naming twice: an `assertEqual(one_way, 45)`
somewhere will fail on the day phase 4 starts helping, and whoever sees it fail
will "fix" the test.

**Done when:** `evennia test --exclude-tag=llm .` runs green from a clean
checkout with no API key, in CI, in under a minute; one model-call seam exists;
and at least one cassette-replayed test exercises `verb_gen.learn_rule` end to
end without a network call.

---

## 4. Phases

Each phase lists what it changes, what it unblocks, how it is known to be
finished, and the tests that hold it. Tiers are marked `[A]`, `[B]`, `[C]`.

### Phase 1 — Lexicon: kind anchors and verb senses

*Spec §7, §7.1, §5.1. No dependencies. Improves generation on its own.*

An invented noun anchors nowhere: `kinds.canonical("datapad")` returns `datapad`
and `lexicon.ancestors("datapad")` is empty, so no kind-scoped rule could ever
reach it. `kinds.py`'s docstring claims otherwise; the claim is not implemented.

- `kind_specs[kind]["under"]`: an anchor synset for a kind WordNet does not know.
  `lexicon.ancestors` consults it.
- Ask for the anchor only when needed: no senses at all; senses straddling a
  bucket (the existing test); or the best sense's bucket contradicting the
  declared affordances -- which catches `blaster`, whose only sense is a *person*
  while the generator called it takeable and wieldable.
- Record the verb sense on the action later (phase 5), but add
  `lexicon.verb_senses()` and a verb `sense_prompt` here.
- Add `lexicon.entailments()` and `lexicon.causes()`, and make `verb_ancestors`
  take an optional recorded sense. Today `verb_ancestors("launch")` returns
  `['open', 'propel']`, so the kindred block hands a model the world's `open`
  rule as the starting point for writing `launch`.

**Done when:** every kind in a fresh world has non-empty ancestors, real or
anchored; `verb_ancestors` with a sense returns only that sense's parents; no
corpus still degrades to today's behaviour.

**Tests:** `[A]` anchor resolution, including the no-WordNet path; `[A]` the
contradiction test flags `blaster` and passes `airlock`; `[A]` `verb_ancestors`
with and without a sense, asserting the `launch` case specifically; `[A]` every
kind in the world fixtures resolves to something closed; `[C]` the sense menu
produces a choice from the offered list.

### Phase 2 — Rooms and zones get kinds and states

*Spec §6. Depends on 1 for anchors.*

All 99 generated rooms carry a `room_type` whose head noun WordNet knows; zero
rooms carry states. Without both, `{"enclosure": "spacecraft.n.01"}` cannot be
said and no rule can be about a place.

- Rooms and zones get a kind by the path objects use.
- `room.db.states` and `zone["states"]`, through the existing `register_state`,
  so they get a `means`, a group and a help entry for nothing.
- `conditions` subject forms `here`, `{"enclosure": kind}`, `{"zone": true}`.

**Done when:** a generated room reports a kind and can hold a state; the enclosure
walk finds a zone-kind from a room three levels in.

**Tests:** `[B]` enclosure resolution across room→zone→parent-zone; `[B]` a state
on a zone is registered in the world vocabulary and appears in `help`; `[A]` a
room with no `room_type` degrades to no kind rather than raising.

### Phase 3 — `world/conditions.py`: one condition language

*Spec §5.4. The biggest refactor. Pays for itself three times.*

Two languages exist: `verbs.check`'s role-keyed `requires`, and `goals._test`'s
type-tagged conditions. They describe the same facts, `goals.py` says so, and
they have drifted anyway.

- One form, the closed predicate list from §5.4, with the new subjects.
- Three operations: `evaluate`, `describe`, `achieves`.
- `verbs.check`, `goals._test`, `quest_gen`'s validation and
  `planner._effect_achieves` all become callers.
- Conversion is one-way and for fixtures only: enough to read the old corpus
  into the new form so tests can assert against real data. No runtime adapter,
  no writing the old shape back.

**Done when:** one implementation answers for verb preconditions, goals, quests
and the planner; every refusal message is produced by `describe`.

**Tests:** `[A]` a table-driven suite over every predicate × every subject,
asserting `evaluate` and the English of `describe`; `[A]` `achieves` for every
effect type against every predicate -- this is the invertibility ground rule, and
the table is the test; `[A]` every `requires` block in the world fixtures
converts and evaluates; `[B]` a quest written in the old shape still completes.

### Phase 4 — The consistency scan and `worldcheck`

*Spec §9.1. Orderable early; needs nothing but the rules a world already has.*

Run against the development database today: **45 of 62 states (72%) can be set by
some rule and removed by none**, and 7 states are required by a rule and settable
by nothing. World 3117 holds three complementary pairs -- `(open, closed)`,
`(lit, unlit)`, `(smooth, crumpled)` -- each one missing rule seen from both ends.

- `world/rulecheck.py`: one-way states, unreachable preconditions, dead
  vocabulary, exclusive-group violations, complementary pairs.
- A `worldcheck` command shaped like `memcheck`: reports by default, acts when
  asked, runs at server start and on a long timer. It costs nothing, so a timer
  is fine -- what this project refuses is a timer that spends money.
- Findings become the content of the §9 Q3 question rather than a report nobody
  reads.

**Done when:** the numbers above are reproduced by the command, and a world with
no faults reports none.

**Tests:** `[A]` every finder against the world fixtures, asserting the measured
counts -- these are this session's throwaway scripts made permanent; `[A]` a
clean synthetic world yields an empty report.

### Phase 5 — `world/actions.py`: declarations

*Spec §5.1. Depends on 1 (senses), 3 (conditions).*

Arity is currently inferred from what the player typed, so `power` and
`power#direct` are two rules that must each be right.

- One declaration per verb per world: `applies_to` roles with
  `visible`/`touchable`/`carried` and `optional`; a `sense` picked from a capped
  menu of five; `means` defaulting to that sense's gloss and overridable.
- `carried` buys implicit taking, retiring 54 hand-written `holds` clauses and a
  planner step.
- 98 of 100 learned verbs have a WordNet verb sense, so the menu nearly always
  has the answer; the two misses are a mis-parsed adverb and a typo.

**Done when:** an attempt naming no noun is redirected or refused with "power
what?" rather than silently setting state on an unbound role -- which is what
`search` does today.

**Tests:** `[A]` declaration validation rejects unknown roles and accesses;
`[B]` `carried` performs an implicit take; `[B]` an unbound required role refuses
with a sentence; `[A]` the sense menu is capped and ordered; `[C]` a model picks
a sense from the menu and does not invent one.

### Phase 6 — `world/rulebooks.py`: storage, index, gather, order

*Spec §5.2, §5.3, §6. Depends on 3 and 5. Pure functions — the most testable
phase in the plan.*

- Rules stored with their scope; a `rule_index` on the world root so gathering
  never scans.
- `gather(world, action, bound, room)` → applicable rules.
- `order(rules, attempt)` → the §6 sort key, as an explicit tuple.

**Done when:** `gather` is O(scopes in play) with no scan, and `order` is a total
order with every tie broken.

**Tests:** `[A]` the sort key, exhaustively: object beats kind beats enclosure
beats room beats zone beats world; deeper synset first; deeper zone first; more
`when` clauses first; older first; id last. **This is the phase where a bug is
most expensive and cheapest to test** — `power datapad` versus `power` aboard a
ship is one assertion. `[A]` gathering from fixtures; `[A]` a scope naming a
missing kind gathers nothing rather than raising.

### Phase 7 — Cutover: standard rules, phases, and `rules`

*Spec §4, §8, §10. Depends on 6. The one risky step.*

These land together or not at all.

- **7.1 The standard rules**, hand-written: "you must be able to act", "you must
  be able to reach it", "you cannot move while bound". This is where the
  composition win shows up as deleted code — `prevents_acting` and its siblings,
  and the reach guesswork in 121 `lacks` clauses.
- **7.2 `attempt.py` runs instead → check → carry out → after → report.**
- **7.3 `rules`, `rules <action>`, `help <action>`.** Not later. Inform's hardest
  bug class is rule ordering and its answer is `RULES ON`; a world nobody can
  debug is worse than a world that cannot launch a spaceship.
- **7.4 Rollback, and what the cutover actually did.** The branch, and
  `worldreset`. A bad cutover is a checkout away.

  The old `verb_rules` path was to be *deleted* here. It is bridged instead,
  and the reason is a sequencing fact the plan had wrong: **nothing writes
  carry-out rules until phase 8.** Delete the old path before the prompts
  exist and every verb gathers no carry-out rule and does nothing at all --
  the game stops, and the phases have nothing to run.

  So `rulebooks.from_verb_rule` reads a learned verb rule as what it already
  amounts to: a stack of world-scope check rules from its `requires`, and one
  world-scope carry-out rule from its `effects`. Computed at gather time,
  never stored, because storing it would be one fact written down twice in two
  shapes with nothing keeping them in step -- which is the failure this whole
  design exists to end.

  That is better than deletion would have been. The phases run on everything
  the exported worlds already know, so the engine is exercised against real
  learned rules before a single prompt is rewritten, and phase 8 becomes a
  smaller change: ask for rules directly instead of converting them. The
  bridge goes when the asking lands.

  Two things from this phase remain undone on purpose. Implicit taking is
  written and tested but unwired, because nothing declares `carried` until
  phase 8 asks. And `help <action>` waits for the same reason: until a world
  writes its own rules there is nothing to say about a verb that `rules` does
  not already say better.

**Done when:** every verb that worked before works; the space-game example in §8
runs end to end; `rules launch` prints the firing order with the unmet condition
marked.

**Tests:** `[B]` the §8 worked example, as a single test: declare, learn, redirect,
refuse on each of four conditions from three scopes, then succeed; `[B]` a
refusal quotes the most specific unmet condition; `[B]` `instead` wins over
`carry_out` and ends processing; `[B]` `after` does not suppress narration;
`[B]` the behaviour corpus: for each of the 326 rules in the fixtures, the
refusal or success today is recorded now and asserted against the new engine --
differences are expected and each one must be explained, which is the point of
recording it; `[B]` command tests for `rules`.

### Phase 8 — Generation prompts

*Spec §9. Depends on 7. Where the quality of the whole thing is decided.*

- Q1 declare the action; Q2 what it means here, with the gathered rules shown in
  firing order and the scope menu; Q3 is anything missing, fed by phase 4; Q4
  per-object differences; Q5 narrate, unchanged.
- A scope ceiling, so nothing is filed against `physical_entity.n.01`.
- `{"cannot_say": "..."}` as a permitted answer, logged — this is how the effect
  vocabulary's gaps become a measurement instead of an argument.

**Done when:** a fresh world learns `power`, `launch` and a redirect without a
hand-written rule, and every generated rule validates.

**Tests:** `[B]` cassette replays of each prompt, asserting the rule validates,
the scope is from the offered menu, conditions use only closed predicates and
effects only known types; `[A]` the scope ceiling rejects a too-general choice;
`[C]` a live model, five verbs, asserting those same invariants and nothing about
the prose.

**Done, except Q3.** Q1 is `actions.learn`, asked before Q2 because its answer
changes Q2 -- an optional `direct` is what lets `power` typed bare reach an
`instead` rule. Q2 is `rule_gen.learn`. Q4 was already `_with_specifics` and Q5
is unchanged. `SCOPE_CEILING = 6` was set by measurement, not by taste:
`instrumentality.n.03` sits at 6 and `device.n.01` at 7.

Q3 -- "is anything missing", fed by phase 4 -- is **not** done, and belongs with
phase 10's suggestion queue rather than inside an attempt: a player waiting on a
verb should not also pay for a consistency review. What phase 8 did do for it is
make phase 4 able to see the new rules at all (`rulecheck.as_verb_rule`), which
it could not when every rule a world wrote went to a store the scan never read.

Two things turned up in the implementing, both now rules of their own rather
than notes: reach had to look upwards as well as downwards, since a redirect
makes the place the direct object (`relations.enclosing`); and a refusal is a
decision, so a world that has ruled a verb impossible must not be asked again.

### Phase 9 — Effect vocabulary (standing)

*Spec §11.1. Not one step and not a late one. Each entry must be invertible.*

Ordered by what the first real world needs: `set_exit` and cross-room
`move_object` (a ship that launches must change where its airlock leads, and
`move_object` today reaches the actor, this room, or a role — never another
room); then declared relations for lockable-with-key.

**Light is struck from this phase.** It read "light and darkness, of which there
is currently nothing at all", and that was wrong twice over. `world/gear.py`
already carries the whole mechanism: `trait_bonuses` on any object, `bonus_when:
"present"` for a thing that works on everybody in the room — and for the room
itself, which its docstring spells out ("a forge is warm whether or not anything
in it is") — `bonus_while` for a state that must hold first ("An unlit lantern
lights nobody"), and a total that is *derived, never accumulated*, so a lamp
carried away needs no bookkeeping.

So light is a trait, the check is one condition on the actor, and the room, a
held lamp and a lamp on the floor all feed the same figure. It needs no effect
type, and `set_trait` is already invertible — where a bespoke light effect
would have needed new `achieves` support to avoid being the hole this phase
exists to prevent. What is actually missing is two schema fields, and they move
to phase 9.1 where the worked example lives. See spec §8.1.

The test that a capability should pass before it earns code: the same two fields
buy warmth, stench, noise and radiation.

**Tests:** `[A]` `conditions.achieves` handles each new effect — **an effect
without this test is a hole in the planner**; `[B]` each effect applied and
observed; `[B]` exits retargeted and traversed.

### Phase 9.1 — Looking as an action

*Spec §8.1. Depends on 7 for the phases and 8 for `unbound`; independent of the
rest of 9.*

Reading the world is the one thing no world can hold an opinion about. `look` is
a command, `engine_verbs` reports it as the game's own, and `_with_bindings`
hands it straight back — so a cave cannot be dark, a ghost cannot need
spectacles, and the moon cannot be visible without being touchable.

**The defaults are exactly the current behaviour.** Nothing about an ordinary
room changes; what changes is that the behaviour is written as rules a world can
add to.

- Carve `look` out of the engine-verb hand-back, deliberately and in one place.
  This is the delicate part: the comment in `_with_bindings` records the
  infinite bounce that happens when the pipeline and the command set disagree
  about who owns a verb ("study scroll" did it), so the carve-out needs a test
  that types `look`, `x`, `examine` and `study` and asserts each is answered
  once.
- Declare `look` with `direct` **optional** and `visible`. One action, not two:
  bare `look` redirects to looking at the enclosing room via a *standard*
  `instead` rule guarded by `unbound` — the `power` redirect with the nouns
  changed. This diverges from Inform, which splits LOOK and EXAMINE; the reason
  is in the spec.
- **Fix the access bug.** The standard reach rule has `action: null` and asserts
  `reachable_by`, so it applies to looking too — while `actions.ACCESS` has had
  a `visible` level since phase 5 that nothing has ever enforced. The rule
  consults `actions.access_for`, and a `visible_to` predicate joins
  `reachable_by`. First implementation: everything reachable is visible, plus
  what a world's rules add.
- A `describe` effect, returning what `return_appearance` returns today. The one
  deliberately output-only effect in the vocabulary — `achieves` cannot read it
  backwards and should not, because no goal is "to have been told something".
  An NPC wanting to look at the painting wants the `after` rule's consequence.
- ~~Descriptions written when somebody looks.~~ **Dropped on measurement.**
  Every path that makes a describable thing already carries its description in a
  call that happens anyway — `worldgen`'s contents pass, `item_gen`, and the
  `create_object` effect all do. Lazy descriptions would trade a few dozen extra
  tokens in an existing reply for one fresh call per examined object, which is
  more calls and not fewer. Recorded in spec §8.1 with the paths measured. The
  cost of skipping it is that a look can never be richer than `db.desc`; the
  fallback that would fix that waits until something actually creates a
  describable thing without a description.
- The two `gear` schema fields light needs: room-level `trait_bonuses` in
  `worldgen`'s room generation, and `bonus_while` in its contents schema.
- `get_display_things` consults `visible_to`, so darkness that stops you
  examining the lamp also stops the room listing it. Rule-driven *paragraphs*
  are **not** in scope — see below.

**Done when:** a world can be given a dark room and a lantern by hand, and
`look` in the dark refuses, `light lantern` then lets it succeed, dropping the
lantern and walking out refuses again — with no light-specific code anywhere,
and no change to how any lit room behaves.

**Tests:** mostly tier B, because everything but the last one needs a world root
and real objects — `access_for` reads `world_root.db`, and reach and sight are
questions about where things actually are.

`[B]` `visible_to` against reach, and the access rule choosing a level per
declaration; `[B]` the `unbound` redirect sending bare `look` to the room; `[B]`
the engine-verb carve-out answering `look`/`x`/`examine`/`study` exactly once
each; `[B]` the dark-room walkthrough above, end to end through
`attempt.attempt`; `[B]` an `after` rule on looking raising a trait,
and `achieves` reading it so the planner makes looking a step; `[A]` `achieves`
declining `describe` — the one assertion here with no database in it, and worth
making on purpose so that "output-only" is a decision on the record rather than
an omission somebody later reads as a hole.

**Deferred, and recorded rather than closed:** Inform's *writing a paragraph
about* — a world deciding how its thing reads inside a list. That wants a
rulebook running inside another action's report, which is a fifth rulebook, and
no evidence yet says it is worth one. The visibility *filter* is in scope above
because without it the rules are decoration.

### Phase 10 — Attempt counters and the suggestion queue

*Spec §10.1. Depends on 7.*

- Counters per `(action, scope, outcome)`: a count and a last-seen. Worth having
  alone — the commonest refusal in a world is worth knowing.
- Generators: complementary pair + antonym → inverse carry-out; unbound-role
  refusals → `instead` redirect; sibling kinds → scope widening.
- A proposal is a suspended rule (`listed: false`, `source: "derived"`) with
  `why` and `evidence`. No new storage.
- `rules suggest` / `rules accept` / `rules reject`; or one batched model call
  that judges rather than writes. Never auto-accepted.

**Done when:** a world with a one-way state and refused attempts produces a
proposal citing both, and accepting it fixes the scan finding.

**Tests:** `[A]` each generator against fixtures, asserting the evidence cited;
`[A]` the six rails, one test each — especially that an `instead` proposal must be
strictly more specific than what it overrides, and that a rejection is never
re-offered; `[B]` accept and reject round-trip; `[C]` a batched judgement returns
a verdict per proposal.

### Phase 11 — Planner upgrades

*Spec §5.4, §7.1. Depends on 3; better after 7.*

- Subgoals from unmet check conditions: `launch` refused for want of power
  becomes the goal "the ship is powered" becomes the step `power`.
- Causative pairs propose a verb the world has never learned.
- Inverted `causes` as a candidate **index** — "to make something descend: drop,
  lower, fell" — which is useless as a synonym test and right as a planner index.

**Tests:** `[B]` an NPC given an unreachable goal finds the precondition step;
`[A]` depth capping; `[B]` a verb proposed from a causative pair is attempted and
learned.

### Phase 12 — `world/commonsense.py`

*Spec §7.1. Independent of everything; deliberately last.*

Nothing in phases 1–11 may come to depend on it. The free uses first — exclusive
groups from `DistinctFrom`/`Antonym`, body parts beyond the 120 hand-written ones,
anchor proposals — because they cost no tokens and can be judged by reading a log.
Prompt priors only after the replay measurement says they earn their tokens.

Full corpus downloaded at first run, never vendored: the repository ships only the
code to fetch it, so no share-alike obligation attaches and no edge has to be
dropped on licence grounds. SQLite index, stdlib only, gated behind
`commonsense.available()`.

**Tests:** `[A]` every lookup returns neutrally with no corpus present — the
ground rule; `[A]` the index builder against a small committed sample of edges;
`[B]` a group seeded from antonyms registers correctly.

### Phase 13 — The instrumented soak, and better data

*Depends on everything. The only phase that costs real money on purpose.*

Fresh worlds, run in `worldmode always` for a while, to produce a corpus from the
new engine and replace the interim fixtures of §3, 0.6. This is the one deliberate
spend in the plan, so it is worth setting up rather than just leaving running.

**What must already be in place, or the run is worth less than it costs.** Every
one of these is cheap, and each one turns calls that were going to happen anyway
into data:

| Needed first | Why the run is wasted without it |
|---|---|
| Attempt counters (phase 10) | The refusals are the point. Without counts there is no evidence for any `instead` suggestion, and the redirect case -- `power` aboard a ship -- cannot be detected at all |
| `cannot_say` logging (phase 8) | The only measurement of what the effect vocabulary is missing |
| The kind-settling log (phase 1) | Whether anchors and senses are being chosen well, which is unknowable from the rules alone |
| `worldcheck` (phase 4) | So faults are found during the run rather than read out of the wreckage |

**What `worldmode always` is good for, and what it is not.** It buys volume
without a human typing for weeks, and it exercises the planner and NPC-initiated
attempts hard. But the distribution is biased: NPCs act through the planner, so
they reach for verbs the world already knows and rules that already exist. **They
will not invent vocabulary.** The verbs that stress this design -- the ones nobody
anticipated, typed at a thing nobody expected -- come from a person playing. So
the corpus wants both: always-mode for depth and volume, and human play for
breadth. Recorded separately, because they answer different questions.

**What to re-measure, and which way each should move.** Every number below is
taken from the old corpus and quoted in these three documents; each one is a
claim this design makes about itself.

| Measurement | Old corpus | Expected |
|---|---|---|
| Rules refused as invalid | 85 of 326 (26%) | **down** -- context is expressible now, so `fill`, `order` and `search` should succeed |
| Refused for needing a place | 7 | **to zero** -- this is the failure the whole change exists to fix |
| Accepted rules with no effects | 32% | **down** |
| One-way states (set, never unset) | 45 of 62 (72%) | **down** -- phase 10's inverse proposals target exactly this |
| States required but never settable | 7 | **to zero** |
| Rules per verb | 3.26 | **down**, and near 1 per action-and-scope |
| Troponymy parents already known | 3% (4/113) | **up** -- and re-measure it properly, since the old figure came from `verb_ancestors` guessing senses wrongly |
| Per-object specifics that differ | 0 of 65 | **anything but zero** -- if it is still zero the mechanism should be retired rather than kept paying for a field in every narration prompt |
| Verbs with a WordNet sense | 98 of 100 | **watch it** -- a genre-heavy world is where this should break if it breaks |
| ConceptNet affordance replay | not yet run | coverage, precision, novelty against the 12-bucket floor (§7.1) |

**Done when:** the fixtures are replaced, every baseline is re-recorded with its
new value, and each number that moved the wrong way has an explanation or a bug
attached to it.

A number going the wrong way is the most valuable thing this run can produce, so
it should be easy to see. `worldcheck` reporting a ratchet break is better than a
test failing silently in CI weeks later.

---

## 5. What the tests are for, stated once

Three failure modes have actually bitten this project, and each tier exists for
one of them.

**Tier A — the logic is wrong.** Sort order, condition evaluation, invertibility,
parsing. Cheap, exhaustive, table-driven. Most of the plan's risk lives here,
especially phase 6's sort key, and all of it is testable without a database.

**Tier B — the pieces do not fit.** A rule that will not serialise; a prompt
asking for a field the parser ignores; a narration cached under the wrong
outcome; an effect that fires on an unbound role. These are the ones that have
historically escaped, because nobody could reproduce them without a model. With
cassettes they are deterministic and free.

**Tier C — the world drifts away from the prompts.** A model that stops answering
in the shape we ask for. Nothing else can catch this and it cannot be cheap, so it
asserts **invariants only** — schema, closed vocabularies, scope from the offered
menu — and never prose. It runs on demand, with a fixed cheap model and a call
budget.

**The rule that keeps tier C small:** if a test can be written against a recorded
reply, it is tier B. Tier C is only for "is the live model still cooperating".

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Phase 7 cutover changes behaviour in ways nobody notices | The behaviour corpus recorded before the cutover (§3, 0.6): every difference surfaces, and each one is either intended or a bug. No live world depends on the answer, so a difference is information rather than an outage |
| Phase 3 touches four modules at once | Adapter both directions; the table-driven tier A suite lands with it, not after |
| Rule ordering bugs, the known failure mode of this design | `rules` ships in phase 7; the sort key is an explicit printable tuple; exhaustive tier A tests |
| A model files rules at too general a scope | Scope ceiling in phase 8; `worldcheck` reports rules at suspiciously wide scopes |
| Generated rules accumulate into an unreadable rulebook | Cap per action and scope; suggestion queue evicts weakest evidence; every rule carries a sentence and a source |
| Derived rules quietly change meaning | Only check rules install themselves; carry-out and instead are proposed; `source: "derived"` is permanent |
| The effect vocabulary binds before the rulebooks are useful | Phase 9 is standing, not last; `cannot_say` logging measures the gap |
| ConceptNet becomes load-bearing by accident | Phase 12 last; neutral-degradation test per lookup; nothing earlier may import it |

---

## 7. Out of scope, deliberately

* **A clock that costs money.** Free timers are fine — memory consolidation
  already runs on one. Nothing here adds a paid tick.
* **Every-turn rules and timed events.** A delayed consequence becomes a
  condition on a checkpoint, not a timer.
* **Vehicles as objects you can be inside.** `relations._is_thing` excludes
  characters deliberately; ships and pods are rooms or zones. A separate change.
* **Scenes, activities, disambiguation rules.** Quests, narration and
  `naming.py` already cover these.
* **A logical resolver, a general triple store, and synonym folding computed
  from corpora.** All three rejected with reasons in the notes.
* **Senses and dictionary priors for traits.** Asked, measured, declined.
  There are 10 distinct trait slugs across all seven worlds; 9 have a WordNet
  noun sense; and **no pair anywhere would be folded by synonymy**, so a sense
  would deduplicate nothing. The prior already exists --
  `traits.vocabulary_block` is shown to every prompt that can invent one, which
  is why the register is small. And a gloss would make things worse rather than
  better: a trait's `means` is a decision about *this* world, not about
  English. World-05's `stamina` is "physical energy and satiety" where
  world-01's is "physical energy and endurance", and a dictionary would flatten
  both to "the power of sustained exertion".

  The collision the prompts warn about -- "a world where one character has
  magic and another mana" -- did occur, in world-03, and the world was right:
  `arcana` is a counter for "understanding and manipulation of magical forces"
  and `mana` is a gauge of "magical energy available to be spent". A skill and
  a resource. Folding them would have been the error, which is the argument
  `traits._matching` already makes: "folding 'mana' onto 'magic' would be
  deciding a question of meaning that is not this function's to decide." The
  one collision that does matter, a trait and a state sharing a word, is
  already refused by `world.vocabulary`.

---

## 8. First week

If only a few days are available, these are the ones that pay whatever happens
next, in order:

1. **Phase 0.1–0.4** — one call site, one seam, the harness, the tags. Nothing
   else can be verified without it.
2. **Phase 4** — the consistency scan, and **0.6, the fixtures, before anything
   is reset.** The scan needs no corpus, no rulebooks and no model, it reports
   real faults today, and 72% one-way states is worth knowing *before*
   redesigning around them. The urgency is the reset: once the worlds go, so does
   the only generated rule corpus there is. Export it first -- it costs an
   afternoon and it is irreplaceable.
3. **Phase 1** — kind anchors and the `verb_ancestors` sense fix. Small, and it
   corrects a live wrongness where the kindred block hands a model the wrong
   rule.

None of the three depends on the rulebook design landing, and all three are
strictly better even if it does not.
