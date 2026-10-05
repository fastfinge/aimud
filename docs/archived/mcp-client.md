# Development plan: a world that reaches out

Status: **built**, phases 0 to 8, on the `mcp-client` branch. Where the
building changed the plan, the change is marked **as built** under its phase
in §14; the sections above it say what was scoped. Not yet run against the
live server -- everything is held by the free suite, which drives the real SDK
against servers in process and one real stdio process. This is the second half of the
`future-plans.md` item that `docs/archived/mcp.md` split in two. That plan let an agent
reach *in*. This one lets a world reach *out*: real weather, a web search, a
dice server, an email an innkeeper sends. It covers MCP servers and OpenAPI
services together, because once a tool is listed they have the same shape, and
§3.3 makes them the same code.

`basic-principles.md` has already allowed this, and drawn the edge of it:

> Network access may only be provided to in-game entities via strictly scoped
> surfaces, like MCP servers added to the world, API's offered by AI
> providers, ... Nothing inside the game should be able to make uncontrolled
> network requests directly.

and

> text should have the chance to be grounded and meaningful: text should never
> exist if it will always be exclusively decoration, and can never be promoted
> to affect a game system in some way.

The first says who decides: whoever runs the machine. The second says what
may come back: something the rules can read, never prose that is only there
to be read.

---

## 1. The change, on one page

* **A service is something the server owner added.** An MCP server (run as a
  command, or reached at a URL) or an OpenAPI service, added in game by an
  admin through a form. A command needs the permission that already lets
  somebody run Python (`Developer`, the `py` lock), because starting a process
  is the same trust. A URL or a spec needs `Admin`. Once the owner has added a
  service, using it is not running arbitrary code, and players, characters and
  agents may use it. §4.
* **Every credential belongs to the server, never a player.** One token per
  service, held server-wide. Nobody can connect their own email or bank to the
  game and have a character act as them. If a service touches the real world,
  that is because the owner decided it may, and the owner should give the mud
  an account of its own. §4.4.
* **Each tool is classified by the owner** as *contained*, *looks outward* or
  *acts outward*. MCP's annotations, or the HTTP method, fill in the first
  guess. The owner's answer is the one the game uses. §5.
* **One gate, the one that already exists.** A character may use a service
  wherever it could call a model, and not elsewhere. A player may use a
  contained or looks-outward tool anywhere, and an acts-outward tool wherever a
  model could be called for them. No new permit level. §5.3.
* **No third system, and no second way in.** A tool reaches a world only
  through a **`call_tool` effect** in a rule, so players, characters and agents
  all reach it the same way: by using a verb. A tool no rule calls is seen by
  nobody but whoever is writing a rule. Worlds do not choose services; every
  world can use every service, and none is used until a rule calls it. §6, §7.
* **What comes back must land in the world.** A result is mapped onto states,
  traits and descriptions the rules can read, or told, as text, to whoever
  used the verb, because they wanted to know it. It is never narration. §7.4.
* **Models may write `call_tool` rules**, so a model learning `sail` may write
  a rule that checks the weather. People can write them too, through the rule
  form, and the add-action form has a shortcut that writes the declaration and
  the rule in one go. §7.6, §8.
* **The planner reads tools through the effects they write.** Effects that do
  not depend on the result are promises it can plan with. Effects written
  *from* the result are something it can find out, never something it can
  bring about. An acts-outward rule is tried at most once per goal. §9.
* **A world needs a service when a rule names one of its tools**, not when
  something calls it. `requires.services` is worked out from the rules at
  export time, sits beside `requires.rulesets`, and holds each tool's schema
  fingerprint as well as its name. A world never adds a service for itself and
  never imports broken. §10.

---

## 2. What is already there

Most of this is reuse, which is the reason the design looks the way it does.

* **`requires` in the world document.** `exchange._requires` already lists the
  rulesets and versions a world was built with, and `exchange.problems`
  refuses a document whose server is missing one, naming it. `requires.plugins`
  is already refused if not empty, waiting for plugins. Services are the third
  entry. §10.
* **`exchange.CARRIED` and `exchange.LEFT`.** Service addresses and secrets
  are not on a world at all, and nothing new is stored on a world root: what a
  world needs is read off its rules.
* **Verbs and rules.** How every player, character and agent already acts.
  A tool is one more thing a rule can do, so it needs no way in of its own.
  §6.
* **`rule_gen.LOOKUPS`.** The lookups a model may call while it learns a rule.
  Two more (`list_tools`, `show_tool`) are how the rule generator sees the
  server's tools. §7.6.
* **`effects.VOCABULARY`.** One entry per effect, each with `means`, `takes`
  and `fields`. The manual's effects page, the rule form and `rule_gen`'s
  prompt are all generated from it, so a new effect turns up everywhere it
  should by being written once. §7.
* **`Sponsor`.** Every generator is handed one, and it knows the world, who is
  paying and who caused the call. `Sponsor.answers` is the test for whether a
  model can be called here, for this actor. It is the gate for services too.
  §5.3.
* **`llm.fetch` and `busy.py`.** The seam for doing work off the reactor and
  handing the answer back on it, and the "still working" notices for a player
  waiting on it. A tool call is one more of these. §7.3.
* **The planner.** Rules are planning operators, goals are conditions, and
  `note_failure` stops it trusting a rule that keeps not delivering. §9 adds
  one distinction, and nothing else.
* **`called`.** A condition that asks about the word typed rather than a thing
  bound. It is what lets `forecast london` pass "london" to a tool without
  conjuring a London. §7.2.
* **Evennia's `ServerConfig`.** A server-wide key/value store already in the
  database. The service register lives there, so this needs no migration.

---

## 3. Libraries, and where they run

### 3.1 The MCP SDK

The official `mcp` Python SDK. It speaks stdio and streamable HTTP, has an
in-memory transport for tests, an OAuth client (`OAuthClientProvider`, with a
token store we implement), structured tool results (`structuredContent`,
`outputSchema`) and elicitation. Writing our own client would be the opposite
of library reuse for no gain.

### 3.2 Twisted and asyncio

The SDK is asyncio. Evennia is Twisted, and switching Evennia's reactor to the
asyncio one is a change to everything to buy one thing. Instead:

* **One asyncio loop, in one daemon thread, in the Server process**, started
  the first time a service is used. It owns every `ClientSession`, each one
  long-lived, so a stdio server is started once rather than per call.
* **A call is blocking work handed to `llm.fetch`.** The worker thread submits
  the coroutine to the loop with `run_coroutine_threadsafe` and waits on the
  future with the call's timeout. The answer comes back on the reactor the way
  every model answer does.
* **The Server process, not the Portal.** Effects, the world, the ledger and
  Django's views (for OAuth, §11) are all in the Server. A reload restarts the
  Server and so restarts stdio servers, which is the right behaviour: a
  reload is when code changes.

### 3.3 OpenAPI is an MCP server we start ourselves

FastMCP's `FastMCP.from_openapi(spec, client=httpx.AsyncClient(...))` turns an
OpenAPI spec into an MCP server in process. Served over the in-memory
transport, an OpenAPI service is then just another session to the manager:
one code path for listing tools, calling them, fingerprints and classification.
The owner picks which operations to expose, because real specs have hundreds.

**To be confirmed in the spike:** `from_openapi` is in the standalone
`fastmcp` package, not the SDK's bundled copy. It has been described as best
for prototyping. If it is not good enough, the fallback is a small adapter of
our own over `openapi-core`, still presenting itself to the manager as an
in-memory MCP server, so nothing above it changes.

### 3.4 The spike that decides this

Phase 0, half a day. A live Server, the loop thread, and one of each: a stdio
server, a streamable HTTP server, a `from_openapi` server, and an OAuth round
trip through a Django view. It ends with a written answer to §3.2 and §3.3,
and this document updated where it was wrong. `docs/archived/mcp.md`'s spike found the
port it had picked would stop the Server booting. This one is expected to find
something too.

---

## 4. Adding a service

### 4.1 Who

| kind | needs | why |
|---|---|---|
| command (stdio MCP) | `Developer` | starting a process is running code, and whoever holds `py` can already do that |
| URL (streamable HTTP MCP) | `Admin` | network access, decided by the owner |
| OpenAPI spec | `Admin` | the same |

Once added, the service is the owner's decision, made once. Using it is not
command execution: the command line is fixed and only the tool's arguments
vary, and those go to the tool, not a shell.

### 4.2 The form

A subject, so it is `create service`, `edit service`, `delete service` and
`view services`, built as a `menus.Form` like everything else:

* **Name.** A slug, which is what worlds name it by (§10). Unique per server.
* **Kind.** Command, URL or OpenAPI.
* **Command and arguments**, or **URL**, or **spec** (a URL or a path).
* **Environment variables** (command only) and **headers** (URL, OpenAPI).
  Values are SECRET fields, masked by `preferences.mask` everywhere they are
  shown, the way `apikey` is.
* **Authorisation.** None, an API key (and where it goes: a header, a query
  parameter or a bearer token), or OAuth (§11).
* **Timeout.** Per call, with a default.

On save, the manager connects, lists the tools, and opens the tool list (§5.2).
A service that will not connect is saved anyway and says why, because a
server down this afternoon is not a wrong setting.

`view services` is open to everybody. Players should be able to see what the
game can reach and what each tool does: it is an open sandbox. Secrets are
masked.

### 4.3 Refused addresses

The client refuses aimud's own MCP endpoint (`MCP_INTERFACE`:`MCP_PORT`). The
game driving itself as an agent would be a way round every gate in
`docs/archived/mcp.md`.

### 4.4 Whose identity

Every token belongs to the server. There is no per-account service and no
per-player OAuth, and there will not be. A character a player made is not that
player, and must never act on that player's email because the player happened
to make it.

The README's admin section says what follows from this: **give the mud its
own account** with anything that acts outward. Then the outside world sees "the
mud" as the sender, which is true.

aimud names itself on its side. `clientInfo` in the MCP handshake and the
`User-Agent` on HTTP both say aimud and the server's name. Nothing can make a
third-party service pass that along, which is why the dedicated account is the
real answer.

### 4.5 `LOCKDOWN_MODE`

Switches every service off, for the reason it switches off everything else.

---

## 5. What a tool does: the owner's classification

### 5.1 The three levels

Inside the game, a service can change nothing. It has no access to the world.
The only way a result changes the world is through a `call_tool` effect's
result mapping (§7.4), which is a rule effect: visible in `view rules`, checked
by `rulecheck`, gated like any rule. So in-game change is already tracked, by
the rules, and is not tracked again.

What is tracked is what the tool does **outside**. Two questions: does anything
leave the machine, and does it change anything once it has.

| level | example | leaves the machine | changes the world outside |
|---|---|---|---|
| **contained** | dice, a calculator, a local word list | nothing | no |
| **looks outward** | weather, web search, a share price | the query, which may carry world text | no |
| **acts outward** | send an email, post to a site | the query | yes, and it stays changed |

`destructiveHint` is shown on the tool list as information and is not a level.
Within "acts outward", the difference between adding and destroying matters
less than acting at all.

### 5.2 Where the first guess comes from

MCP tools may carry annotations, and the spec calls them hints:

| annotation | default if missing | fills in |
|---|---|---|
| `openWorldHint: false` | true | contained |
| `readOnlyHint: true` | false | looks outward (if open-world) |
| neither | | acts outward |
| `idempotentHint` | false | whether a failed call may be retried (§7.5) |

Many servers send none, so the defaults (open-world, not read-only) make the
first guess "acts outward": assume the worst. For OpenAPI, GET and HEAD are
read-only by definition, and the rest are not.

When a service is saved or its tool list changes, `edit service` opens the
list: every tool with its description in full, its schemas, its annotations
and the guessed level. The owner confirms or changes each level, and may switch
a tool off entirely. **The owner's answer is the classification.** The
annotations only filled in the form.

The description is shown in full on purpose. Tool descriptions are written for
models, they are long, and they are where a malicious server hides
instructions. Vetting the server is the protection, so the owner should read
what it will tell the rule generator, and, through the rules it writes,
characters.

### 5.3 The one gate

There is one gate, the one that already decides whether a model may be called:
`Sponsor.answers`. Too many kinds of gate confuse players and owners, and
"could this call a model?" is already the question everybody knows the answer
to.

| | contained | looks outward | acts outward |
|---|---|---|---|
| a player | yes | yes | where `answers` |
| a character | where `answers` | where `answers` | where `answers` |
| an agent | as a player | as a player | as a player |

A character that cannot call a model does not call a service, at any level.
That is the rule as given, and it means a world with no key has characters
that never reach outside the game, which is easy to explain.

A refusal says which: "Nobody is paying for this world to reach outside" reads
the same as the existing no-key messages, from `Sponsor.refusal`.

---

## 6. How a tool reaches a world: through a verb

Players, characters and agents all act by using verbs, and verbs do things
through rules. A tool is one more thing a rule can do. There is no other way
in: no tool is handed to a character's model as a tool of its own, and none is
offered to an agent beyond the verbs it can `send`.

So a tool enters a world in one of two ways, both of which write a rule:

* **Somebody tries a verb nobody has taught**, `check the weather`, and
  `rule_gen` learns what it does. While it learns, it can see the server's
  tools through `list_tools` and `show_tool` (§7.6), and may write a rule that
  calls one.
* **A person writes the rule**, through the rule form or the add-action
  shortcut (§8).

From then on the tool is used whenever the verb is, by anybody, through the
gate (§5.3). A tool no rule calls is seen by nobody but whoever is writing a
rule.

**Worlds do not choose services.** The owner configured each one with the
server's own credentials, so there is nothing for a world's creator to set up,
and nothing is used until a rule calls it. Every world can use every service.
What a world *needs* is read off its rules (§10).

What this buys:

* **Equal footing.** A player using `forecast` and a character using
  `forecast` use the same rule, behind the same gate, and an agent uses it by
  typing it.
* **Outside text reaches a prompt only when somebody asked for it.** A result
  lands in the world, as a state, a trait or a description, or is told to the
  one who used the verb, labelled as coming from outside (§7.4). It never
  arrives unasked.
* **Prompts do not grow with the register.** A character's prompt carries the
  verbs it can use, as now, however many services the owner adds.
* **The tool register is untouched.** `list_tools` and `show_tool` are two
  ordinary lookups with literal names, so `TheRegisterHoldsEveryTool` needs no
  exemption.

---

## 7. The `call_tool` effect: doing something

### 7.1 The shape

A new entry in `effects.VOCABULARY`. Stored in a rule like any other effect:

```json
{"type": "call_tool",
 "tool": "weather.forecast",
 "does": "Gets the forecast for a city for the next three days",
 "args": [{"param": "city", "from": "word", "role": "direct"},
          {"param": "units", "from": "value", "value": "metric"}],
 "result": [{"field": "conditions", "to": "state", "role": "here"},
            {"field": "high_c", "to": "trait", "role": "here", "name": "temperature"}]}
```

* **`does`** is the tool's description, **copied when the rule is written**,
  never read live. If the service later changes it, the fingerprint (§10.2)
  catches that, rather than the rule silently meaning something new. It is
  capped in length. It is what a character's model is shown when this rule is a
  candidate, and what `view rules` says the rule does.
* **Kept flat.** `args` and `result` are lists of flat objects, not mappings of
  mappings, because `goal` was withheld from `effects.schema` for nesting three
  deep and Google refusing it. `test_schema_portability` holds `call_tool` to
  the same bar.

### 7.2 Where each argument comes from

| `from` | means |
|---|---|
| `value` | fixed when the rule was written |
| `word` | the word typed for a role, through `called`: `forecast london` |
| `name` | the bound thing's name |
| `trait` | a trait or figure of a role (`role`, `name`) |
| `state` | a role's state in a group |
| `ask` | asked when the verb is used (§7.2.1) |

A required parameter with no source makes the rule incomplete, and
`rulebooks.add` refuses it with the parameter named.

**Tools whose input does not fit are refused when the service is listed.**
Arrays of scalars and flat objects are fine. Nested objects, `oneOf`, and
anything a menu cannot ask for are switched off in the tool list with the
reason, so the owner sees why rather than finding out from a rule that cannot
be written.

#### 7.2.1 Asking

* **A player** gets a `menus.Form` built from the parameter schemas: an enum is
  a choice, a boolean is yes/no, a string or number is a field with the
  schema's limits. The form's typed keys are the parameter names, so it is
  reachable by typing like every other form. The form is opened before the
  call, never during.
* **A character** fills them in the tool call that made the attempt. The NPC
  `attempt` tool gains an optional `answers` object. An attempt reaching a rule
  with unanswered `ask` parameters fails with a message naming them and their
  schemas, which the character reads as its tool result and can answer on the
  next round. That is how a tool loop already learns what it got wrong.
* **The planner** cannot ask anybody anything, so a step whose rule has `ask`
  parameters is not a step it can take (§9).

**Elicitation**, where a service asks for input in the middle of a call, is
answered the same way for a player: a form. For a character it is declined,
until there is a reason to do otherwise (§15).

### 7.3 Running it

`effects.apply` is synchronous and a call takes seconds, so a rule holding
`call_tool` effects runs in two halves:

1. Its `call_tool` effects run first, each through `llm.fetch`, with the actor
   held and a `busy` wait open ("You wait for the forecast...").
2. When every call has answered, the rule's effects run as one batch, in order,
   with the results bound. A result-mapping effect reads its call's answer.

If a call fails, the rule takes its failure outcome, the way a rolled contest
that fails does, and nothing in the batch is applied. Partial application of a
rule is worse than none.

### 7.4 What comes back

The rule is: a result lands somewhere it can matter. Either in the world, as
something the rules can read, or with whoever asked, as something they wanted
to know.

| `to` | takes | from |
|---|---|---|
| `state` | a slug in the role's state group | a field whose `outputSchema` is an `enum` or boolean |
| `trait` | a number | a field that is a number or integer |
| `description` | text, through `modify_object` | a string field, or a text-only result |
| `actor` | text, told to whoever used the verb | a string field, or a text-only result |

* **A state needs a bounded field.** Free text mapped onto states would
  register a new state for every answer. An enum is a closed vocabulary, and
  its values are registered with the group when the rule is written, so the
  rules about rain can be written before it rains.
* **Text can become a description.** A newspaper whose description is today's
  headlines is in the world: anybody can examine it, a character can read it,
  a rule can test that it has been read. The same headlines as narration would
  be decoration.
* **Text can be told to whoever asked.** A character that wants to know which
  pubs are near London uses a verb to find out, and the answer is something it
  specifically wanted to learn, to act on or to repeat. That is grounded by
  being wanted: it changes what the asker does next. It does not belong on any
  one object, and forcing it onto one would make a thing exist only to hold it.
  * **A player** is shown it, as the private result of their own verb, paged
    like any long text.
  * **A character** has it in front of it on its next turn, where the outcome
    of an `attempt` already goes, and it is written to its memory through
    `memory.remember`, so it can recall it later. It is capped in length for
    the prompt.
  * **Labelled.** What a character's model is handed starts by saying it came
    from outside the game, and from which service. Service text is untrusted,
    and the label is the one defence available inside a prompt.
  * **Private.** The room sees the verb narrated ("Mara consults her
    almanac"), not what came back. If the asker wants others to know, they say
    so, and speech is already grounded.
* **Never narration.** A rule's written `report` cannot interpolate a result,
  and the narrator is never handed one. The narrator sees the world *after*
  the batch ran, so it says it is raining because it is raining.

### 7.5 Failure, retry and the record

* **A service down or timing out** is a failure outcome with "the forecast
  cannot be reached right now", and **is not held against the rule**, the way
  a network failure is not counted against `rule_gen.ASKS_ALLOWED`.
* **Retried only if idempotent.** A failed call to a tool marked
  `idempotentHint` is retried once. Any other is not: retrying an email sends
  it twice.
* **Every acts-outward call is recorded.** Who acted, in which world, under
  which sponsor, which tool and with what arguments, in a bounded log beside
  the service in `ServerConfig`. `view service` shows the recent ones to its
  owner. When something happens in the real world, the owner needs to trace it
  back to what in the game did it.
* **Quotas are the service's.** Services have their own quotas and refuse when
  they are spent; that refusal is a failure like any other. aimud adds the
  per-call timeout and nothing else, the same way `docs/archived/mcp.md` added no rate
  limit of its own.

### 7.6 Models writing it

Allowed. `rule_gen`'s prompt is generated from `effects.VOCABULARY`, so
`call_tool` reaches it by being written. What it also needs:

* **`list_tools` and `show_tool` lookups**, added to `rule_gen.LOOKUPS`, so a
  model learning a rule can see the server's tools, what each does, takes and
  gives back, and which level the owner gave it. Tools the owner switched off,
  and tools whose input §7.2 refused, are not listed. These two are offered
  only to the rule generator, never to a character's conversation (§6).
* **`rule_gen.validate`** applies the same checks as `rulebooks.add`: the tool
  exists here, every required parameter has a source, `ask` is never the source
  (a learned rule is used by characters and the planner, who cannot always be
  asked), and every `result` mapping fits §7.4's table. `does` is copied from
  the service by validate, never taken from the model.
* **`validate_becoming`** refuses `call_tool` in a becomes rule. A state change
  reaching outside the game would be a timer by another name.

---

## 8. People writing it

Everything a model can do to a rule, a person can do.

* **The rule form's NEW_EFFECT** gains `call_tool`. Picking it lists the
  world's tools by name and `does`; picking one opens a form with one field
  per parameter (its source), then one per output field (where it lands, if
  anywhere). `ask` is offered here, because a person writing a rule for players
  can mean it.
* **The add-action shortcut.** `create action` gains a third way in beside a
  dictionary sense and a written one: *a tool*. Pick a service, pick a tool,
  and the form writes two things: the action declaration (its `means`
  pre-filled from the tool's description, its sense still from the dictionary,
  so folding and synonyms keep working), and a carry-out rule whose only effect
  is the `call_tool`, ready for the parameter form. Both are then ordinary, and
  `edit rule` and `edit action` change them like anything else. The shortcut
  saves typing and is not a system of its own.

---

## 9. Goals and the planner

The planner already treats a rule as an operator: preconditions, then
effects. A goal finds a rule whose effects would make its conditions true. A
tool reaches a goal through the rules that call it, so nothing changes on the
goal side. Three things change in the planner.

**Effects that do not depend on the result are promises.** A rule on `post
letter` that calls `send_email` and sets the letter `sent` is found by a goal
or quest that wants the letter sent, exactly like any other rule. This is how a
character with a goal ends up acting outward: through an ordinary rule, behind
the gate.

**Effects written from the result are things to find out.** A rule that maps
the forecast onto `weather` *may* set `raining`, and nothing promises it.

* `_effect_achieves` never counts a result-mapped effect as achieving a
  condition. A character that wants rain does not check the forecast until it
  rains.
* When a rule's preconditions read a group a result-mapped effect writes, and
  the condition is unmet, the planner may take that rule as a **finding-out
  step**: check the weather before trying to sail. Once per goal per
  condition. If the answer is not the wanted one, the goal waits, with the
  existing `not yet` machinery.
* **An answer that is not the wanted one is not the rule's fault.**
  `note_failure` does not count it. Otherwise, after `FAILURES_ALLOWED` (2),
  the planner gives up on a rule that worked perfectly.

**An acts-outward rule is tried at most once per goal.** The set of
acts-outward rule keys tried for a goal is kept beside `goal_stalls`, LEFT
with it for the same reason (how a plan is going, not what it is). A goal that
keeps failing cannot send the same email twice. A new goal can, which is the
author's decision to give it.

Steps with `ask` parameters are skipped, because the planner has nobody to ask.

**Text told to the actor achieves no condition.** It is something a character
learns, and what it does about it is its model's next decision, not the
planner's. A rule whose only result is told text is never a planner step. A
character reaches it by deciding, in conversation or in its own turn, to use
the verb, the way it decides to ask somebody a question.

---

## 10. Worlds: what they need, exporting, importing

### 10.1 What a world needs

A world needs a service when a rule **names** one of its tools: any
`call_tool` effect in the world's own rules or its rulesets' rules, suspended
rules included (a suspended rule can be brought back). Not when something
**calls** it:

* **A rule that has not fired still depends on its service.** A world whose
  `sail` rule checks the weather, where nobody has sailed yet, would otherwise
  export without the requirement and import broken.
* **Calls are history.** Two copies of one world would export different
  requirements depending on what their characters happened to do. Read off the
  rules at export time, the answer is the same every time.

Nothing is stored for this. It is worked out from the rules whenever it is
asked, so it cannot drift from them. A world never adds a service to the
server.

### 10.2 Export

`requires.services`, beside `requires.rulesets`:

```json
"requires": {
  "rulesets": {"default": 3},
  "services": {"weather": {"forecast": "sha256:...", "alerts": "sha256:..."}},
  "plugins": []
}
```

Each tool a rule names, with a fingerprint: a hash of its canonical input and
output schemas. Not its description, which services reword freely and the rule
has its own copy of. Not its classification, which is the importing server's
owner's decision.

Nothing about where a service is or how to log in to it is in the document. A ruleset whose
rules use a tool says so in its own `requires`, and `rulesets.problems` refuses
it the way `exchange.problems` refuses a world.

### 10.3 Import

`exchange.problems` gains a services check shaped like the rulesets one, and
refuses, naming every problem at once:

* "it uses the service 'weather', which this server does not have"
* "it uses 'weather.alerts', which this server's 'weather' does not offer"
* "'weather.forecast' here takes different arguments from the one it was built
  with"
* "'weather.forecast' is switched off on this server"

No adding the service, no importing with the rules suspended. The owner of the
importing server adds a service of that name or does not, and imports again.

### 10.4 Drift at run time

A service's tools change: it is upgraded, or sends `tools/list_changed`. The
manager relists, recomputes fingerprints and reopens the owner's tool list
for anything new. A rule naming a tool that has gone or changed fingerprint:

* **Refuses at call time** with "the forecast is not what this rule was written
  for", taking its failure outcome, not counted against the rule.
* **Shows in `rulecheck`**, beside dead rules, naming the tool and what changed.

It is not suspended automatically, because the service may be fixed this
afternoon and a suspended rule would stay suspended.

---

## 11. OAuth

The SDK's `OAuthClientProvider` runs the flow. aimud supplies:

* **A token store** in `ServerConfig`, per service, never per account (§4.4).
* **A callback**, a Django view at `/services/oauth/callback`, in the Server
  process with the manager, handing the code straight to the waiting provider.
* **Where to send the admin**: `edit service` prints the authorisation URL. The
  redirect lands in the admin's own browser, so `localhost` works when they
  are on the machine. Otherwise the server needs a configured public address
  (`SERVICES_PUBLIC_URL` in settings), and the form says so rather than
  failing.
* **Refresh** is the provider's. A refresh that fails marks the service
  disconnected with the reason, and `edit service` offers to authorise again.

---

## 12. OpenAPI

Through §3.3, an OpenAPI service is an MCP service the manager starts. What is
its own:

* **The spec** from a URL or a path in the game directory.
* **Picking operations.** The tool list opens with every operation switched
  off. The owner switches on what the game may use.
* **Authorisation** from the spec's `securitySchemes`: an API key in a header
  or query, a bearer token, or OAuth 2 through §11.
* **Classification** guessed from the method (§5.2).

---

## 13. Testing

* **A stand-in at the seam.** `tests.support.serving`, like `deciding` for the
  decision model: replaces the manager with an in-process table of tools and
  canned answers, so the free suite never starts the loop thread. Most tests
  use this.
* **The real manager over the SDK's in-memory transport**, for the manager
  itself: listing, calling, fingerprints, `list_changed`, a server that dies.
  Free, no network, not tagged `llm`.
* **One stdio test**, a tiny MCP server in `tests/fixtures/`, started as a real
  process, because stdio is where process lifetime goes wrong.
* **Guards, each watched failing first:** the gate table in §5.3 as one test
  per cell; no service tool ever offered to a character's conversation or to
  an agent as a tool of its own, and `list_tools`/`show_tool` only to the rule
  generator; result text never reaching narration or the room, told text
  reaching only the actor, labelled for a character and written to its
  memory, capped for the prompt; a non-idempotent tool never
  retried; the once-per-goal guard; `requires.services` read off a rule that
  has never fired, and unchanged by calls; import refusing each of §10.3's
  four; `call_tool` holding to `test_schema_portability`.

---

## 14. Phases

Each phase ends green, with a full suite on settled code before a PR.

**Phase 0: the spike.** §3.4. Ends with §3.2 and §3.3 confirmed or rewritten.

*As built:* both held, spiked outside the Server rather than inside it. The
SDK installed is 2.1.1, a major version past the one this plan was written
against: a unified `Client` takes a URL, stdio parameters or an in-process
server. Driven from one asyncio loop in a daemon thread it works, with one
catch written into `services._Connection`: the client's task groups must be
entered and left by the same task, so each service's session is owned by one
task that serves a queue, and nothing calls the client directly. Measured: a
stdio server connects in 0.7s and calls after that take milliseconds.
`FastMCP.from_openapi` (fastmcp 4.0.11, which installs beside mcp 2.1.1)
builds a real SDK `Server`, so OpenAPI is one more session as §3.3 hoped; it
fills in no annotations, so an operation's level comes from its method.
OAuth was not spiked; see phase 6.

**Phase 1: the register and connections.** `world/services.py`: the register
in `ServerConfig`, the loop thread, sessions, listing, fingerprints. The
`services` subject and its forms, the permission split, masked secrets, the
owner's tool list and classification, refusing aimud's own endpoint,
`LOCKDOWN_MODE`. Ends when an admin can add a service and read its tools.

*As built:* as scoped. Every point in the forms is reachable by typing as
well (`edit service weather tool forecast acts`, `edit service weather key
...`), because an agent has no menus. Listing and calling never raise: a
service that cannot be reached is an `Answer` that says so, and a service that
will not connect is saved anyway with the reason. `mcp` and `fastmcp` became
dependencies; `mcp` had only been arriving through something else.

**Phase 2: `call_tool` by hand.** The effect, argument sources, result
mapping (told text included: shown to a player, labelled and remembered by a
character), the two-half run, the gate, failure, retry, the acts-outward
record, asking players (and elicitation for them), the NPC `answers` argument,
the rule form, the add-action shortcut. Ends when a hand-built world has a verb
that checks the weather and says so through a state, and another that a
character uses to find pubs near London and then mentions one in conversation.

*As built:* the call logic is `world/tool_calls.py`. Five differences:

* **Stored as mappings of strings,** not lists of objects (§7.1 showed lists).
  A list of spelled-out objects inside a rule's effects is three deep, which
  `test_schema_portability` refuses, so `args` is `{"city": "word:direct"}`
  and `results` is `{"conditions": "state:here", "text": "actor"}` -- the
  shape `try`'s `roles` already has. `text` names everything the tool said.
* **No NPC `answers` argument.** One way of answering serves everybody without
  a menu: brackets on the end of the line, `forecast [city=Lisbon]`, taken off
  by `attempt` before the line is parsed. The NPC `attempt` tool's description
  says so. A player with a menu still gets a form built from the schemas.
* **A failed call does not take the failure outcome.** It refuses with why --
  "said no", "cannot be reached right now", "not what this rule was written
  for" -- and applies nothing. Narrating a failure would have meant paying a
  model to describe a network error.
* **The word typed reaches the rule.** `forecast london` used to mean a London
  waiting to be conjured out of the room; `attempt._knows_the_word` now also
  counts a rule whose call takes that role's word.
* **A figure needs something that keeps figures.** `trait:here:...` (the §7.1
  example) does nothing, because a room keeps no traits; a place takes an
  answer as a condition.

Not done: **elicitation**, a service asking for input mid-call. No callback
is wired, so the client does not advertise the capability, and a server that
asks anyway is answered "Elicitation not supported" by the SDK. **The end condition was met by tests, not in play:** that a character
is handed the pubs, labelled and remembered, is tested; that it then mentions
one in conversation needs a live model and has not been watched.

**Phase 3: models write it.** `list_tools`, `show_tool`, `rule_gen.validate`,
`validate_becoming`, the schema portability test. Ends when a model learning
`sail` writes a rule that checks the weather.

*As built:* as scoped, and the system prompt explains `call_tool` only on a
server with a tool switched on. The end condition was met with the model's
answer scripted -- the lookups offered, the prompt sent, the rule filed with
its description copied -- not by a live model.

**Phase 4: the planner.** Promises and finding out, no blame for an answer,
once per goal. Ends when a character with a goal to sail checks the weather
first, waits when it is stormy, and sails when it clears.

*As built:* two changes, both found by the end condition.

* **Once per goal per condition could not be right** for finding out: a
  sailor who saw a storm could never look again, so "sails when it clears"
  was impossible. It is once per `tool_calls.FIND_OUT_EVERY` (fifteen
  minutes) per goal instead, and in between the goal *waits* through the
  not-yet machinery, as for the clock, rather than stalling. Recorded when a
  call is made, not when a step is proposed, because hints ask the planner
  for steps nobody takes.
* **A place is still never a goal.** "Only in fair weather" is a check about
  `here`, and a condition about a place has no goal form, by a decision older
  than this plan. Finding out is offered there anyway, in `planner._towards`,
  because looking the weather up changes nothing about the place.

No blame was needed anywhere: the planner blames only learned verb rules, and
a call is only ever in a rulebook rule.

**Phase 5: export and import.** `requires.services` read off the rules,
fingerprints, the four refusals, rulesets requiring services, `rulecheck` for
drift. Ends when a world using a service round-trips, and the same document is
refused by a server without it.

*As built:* rulesets differ from §10.2. `rulesets.available()` is read once
when the server starts, and a service can be added at any time, so a ruleset
is held only to the *shape* of its calls (and refused if one is in a becomes
rule); whether this server has the service is asked when a world switches the
ruleset on, and `edit rulesets` refuses there. `rulecheck`'s new finding reads
the server's register only for a world that calls something, so a scan with
no database behind it still runs.

**Phase 6: OAuth.** §11.

*As built:* `world/service_auth.py`, for a service at a web address only.
Tokens arrive on the loop thread, so the store keeps them in memory and writes
them back on the reactor. Tested at every seam -- the store, the redirect
telling the admin, the browser's return resolving the waiting provider by
OAuth state, the view and its route -- but **not against a real authorisation
server**, which is the first thing to try live.

**Phase 7: OpenAPI.** §12.

*As built:* as scoped, plus `services.spec_key`: a service set to an API key
with no name for it sends the key where the spec's `securitySchemes` says.

**Phase 8: the manual and the README.** A generated manual page listing this
server's services, tools and levels. `extending` says services are the
controlled way out. The README's admin section, including the dedicated
account.

*As built:* as scoped. The README section is "Letting the game reach outside".

---

## 15. Decisions

**Owners add services; nobody else does.** Commands need `Developer`, because
starting a process is running code. URLs and specs need `Admin`. After that,
using a service is not running code. §4.1.

**Every credential is the server's.** No per-player tokens, so a character can
never act as the player who made it. §4.4.

**The owner classifies; annotations only fill in the form.** They are hints,
often missing, defaulting to the worst. §5.2.

**Track what reaches outside, not what changes inside.** Inside, the rules
already say what changes. §5.1.

**One gate: whatever lets a model be called.** A character that cannot call a
model calls no service. Acts-outward tools share the gate. §5.3.

**One way in: a rule.** Tools reach a world only through `call_tool`, so
everybody reaches them by using a verb. No service tool is a lookup a
character calls, and outside text reaches a prompt only when somebody used a
verb to ask for it. Only the rule generator sees the server's tools. §6, §7.

**Worlds do not choose services.** The owner configured them with the
server's credentials; there is nothing for a world to set up. §6.

**A world needs a service when a rule names it, not when something calls
it.** Worked out from the rules, never stored, so a rule that has not fired
yet still counts and calls change nothing. §10.1.

**Results land in the world or with whoever asked, never in narration.**
Text an asker specifically wanted to learn is grounded by being wanted, and is
told to them privately. §7.4.

**No puzzle-world opt-out.** Anything a service can look up, a player can look
up in a browser tab. A world cannot be kept closed against that, so it does not
try.

**Models may write `call_tool`**, with acts-outward rules tried once per goal
by the planner. §7.6, §9.

**Refuse to import rather than add a service or import broken.** §10.3.

**OpenAPI goes through MCP.** One code path. §3.3.

---

## 16. Open questions

**Stale answers.** A weather state written at nine is still there at five.
States do not expire. A result mapping could carry a lifetime (on the world
clock) after which the state is cleared and the planner may find out again.
It is probably right, and it should wait for phase 4 to show whether it is
needed.

**Names across servers.** Two servers may call the same service different
names, and an import is refused over a name. Aliases in the register would fix
it. Wait for the first time it happens.

**How much told text a character keeps.** The cap for the prompt is easy;
what is written to memory is the question. A whole page of search results
remembered verbatim crowds out everything else it knows. Remembering it whole
and letting the memory pipeline's summarising do its job is probably right,
and phase 2 should check it on a real search result.

**Elicitation for characters.** Declined for now. A character could answer
from its own model, and that is another paid call in the middle of a call.

**Resources, prompts and sampling.** Out of scope. Sampling, where a service
asks to use our model, would spend the sponsor's key on a stranger's prompt,
and is declined until there is a case for it.
