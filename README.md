# aimud

A text MUD where the world is written as you walk through it.

There is no map file, no room database, no dialogue tree. You describe a world
in a sentence or two, and from then on every room, every object, every person
and every verb is generated the first time somebody reaches for it — and then
kept, so the world stays consistent behind you. Open a door that has never been
opened and the room beyond is written while you step through it. Try a verb the
game has never seen and it works out what that verb does, remembers the rule,
and applies it to everything similar forever after.

Built on [Evennia](https://www.evennia.com/) 6.1, Python 3.13, and any model
you can reach through [OpenRouter](https://openrouter.ai/).

> **Status: early, and under daily development.** It works and it is fun, but
> it is not finished software. Expect rough edges, and please read
> [Before you host this anywhere](#before-you-host-this-anywhere).

---

## Contents

- [What it does](#what-it-does)
- [Getting it running](#getting-it-running)
- [Your first world](#your-first-world)
- [Playing](#playing)
- [Command reference](#command-reference)
- [What it costs](#what-it-costs)
- [Before you host this anywhere](#before-you-host-this-anywhere)
- [How it fits together](#how-it-fits-together)

---

## What it does

### The world writes itself, in order

A world begins as a title, a description, and separate guidance for each
generator. From that it plans its own zones — a school gets an admin wing, a
classroom wing, a gym block — and decides which rooms are unique (one
principal's office, many classrooms).

Rooms are built in three passes rather than one, so each can be checked before
the next spends anything: a short naming call, a description call that can see
the names of everything nearby, and a contents pass that runs *after* you have
already arrived, so you never wait for it.

The layout obeys rules. Two destinations never open onto each other —
classrooms connect through the corridor, not through each other. Rooms have
coordinates, so a world can close back on itself: walk in a circle and you
arrive where you started, connecting to the room already there rather than
building a second one.

### Verbs are learned once and reused

Type something the game has never seen — `pry the lid off with the crowbar` —
and it works out a **rule**: what that verb needs, what it changes, whether it
can be repeated. The rule is cached against the verb and the *properties* of
the things involved, so learning to read a flyer teaches the world to read
posters too, free.

Separately it writes the **narration** — what is actually written on this
particular poster — and stores that on the object, so it travels with it. The
part that generalises is stored by kind; the part that is specific is stored on
the specific thing. Neither is stored on the room.

### Everything is a sort of something

Everything in a world is a *sort* of thing — a **kind** — and the kind, not
the thing, is what the world keeps its decisions on. What can be done to a
bottle — it can be drunk from, filled and smashed; it cannot be read — is
settled once, by the first bottle the world ever makes, and every bottle after
that agrees.
Those decisions are its **affordances**, and since they are half of a verb
rule's cache key, making them once per sort rather than once per object is what
stops a world's rules quietly splitting in two. Seventy-three bottles across
five worlds had reached twenty-five different answers about what a bottle is,
and `drink` had been learned thirty separate times as a result.

Kinds cannot be free-written strings, because a string drifts: chest, storage
chest, wooden chest, coffer. A kind is a dictionary sense — `chest.n.02` — so
the chest in one zone and the chest built an hour later in another are the same
sort of thing, and English already knows a chest is a container before anybody
is asked. Nouns no dictionary has heard of, and generated worlds are full of
them, keep their own word and are anchored under the nearest real sense.

Affordances are verbs, and they are the verbs you type. `burn`, not
`flammable`; and always what can be done **to** a thing, never what it does — a
lantern affords `light` because it can be lit. A thing can be two sorts at once,
so a sword with runes on the blade is a sword and an inscription and affords
whatever either of them does. It can never afford *less* than its sort: a thing
that cannot do what its sort can is either in a condition that prevents it
(sealed, blunted, waterlogged) or is honestly another sort.

One more thing falls out of it. "Can a bottle be burned" is one bit, asked once
for bottles, instead of a whole rule invented to answer a yes-or-no question —
which is what 86% of every rule those five worlds had learned turned out to be.
Try to burn the key, be told you cannot, and nothing pays for that answer again.

`help bottle` says what this world has decided a bottle is, and `help burn` says
what it will let you burn. The measurements behind all of this, and the two
designs that were tried and rejected first, are written up in
[docs/kinds-and-affordances.md](docs/kinds-and-affordances.md).

### Some verbs can be lost

A rule may declare a **check**: a figure of yours that decides the attempt, and
either a number to beat or somebody else's figure opposing it. Fighting,
forcing, climbing, stealing and persuading get one; reading a notice does not,
and a world that made everything a gamble would be a worse one, not a better.

The model decides only what the contest *is*, once, when the rule is learned.
The dice are code -- a d20 against your trait, the margin choosing between a
critical failure, a failure, a success and a critical success -- so the same
fight is the same odds every time, nothing is spent to roll it, and the numbers
are yours to tune. It is also what makes a strong opponent genuinely harder
than a weak one: a rule contested by *swordsmanship against theirs* covers the
recruit and the veteran without knowing either exists.

Each outcome keeps its own narration on the object, so missing a swing costs
one narration ever and never becomes the text somebody reads when they land it.
A rule that gives a check has to say what failing costs, too -- a failure that
costs nothing is only a command you retype until it works.

### Armour and weapons are worth something

An item can carry `trait_bonuses` — what it is worth to whoever has it — and a
`bonus_when` saying what has to be true for it to count: **worn**, **wielded**,
merely **carried**, or **present**. A coat of mail is +3 defence and −1 stealth
while it is on, and nothing at all in a pack. Every generator that can make an
object can give one, so a breastplate found in a chest protects exactly as well
as one a guard was created wearing.

**present** is the one that is not about belongings: it counts for everybody in
the room with it. A fire warms whoever lit it, whoever was already sitting there
and whoever walks in a minute later, and stops warming them the moment they
leave — which is the only honest way round, since being near a fire is not
something that happens to you once. Rooms may carry bonuses of their own, too,
because a forge is warm whether or not anything is in it. And a `bonus_while`
names a condition the thing has to be in first, so a lamp is worth nothing until
it is lit.

Nothing is added or subtracted. Putting a helmet on recalculates what all your
gear is worth and writes that total to the trait's modifier, leaving the figure
you earned untouched underneath — so a bonus cannot drift, however many times
you change, and taking a thing off removes exactly what putting it on added.
Nothing ticks, either: the sums are redone when somebody arrives or leaves, or
when a source changes condition. `score` says where the difference came from,
fire and forge included.

Wielding is a mechanic rather than a learned verb, for the same reason wearing
is: `wield`, `brandish` and `equip` never reach a model, and hand the attempt
back when the noun is not something to hold, so `draw the curtain` still means
whatever the world decides it means. Two hands, so a sword and a shield.

### People, not props

Characters are generated with a body, a private manner nobody sees, a goal they
are already pursuing, clothes they are wearing and things in their pockets.
They:

- **act on their own**, working at goals through a planner that costs nothing —
  it reads the verb rules and the map the world already has;
- **remember**, with a per-character memory bank searched by relevance, so an
  NPC can recall something from an hour ago that matters again now;
- **ask you for things**, and each other — an errand becomes a checkable quest
  with real rewards and consequences;
- **wear and change clothes**, which changes how they look when you look at
  them, because the description is only their body and the outfit is read off
  the garments they are actually carrying;
- **have traits** — stamina, standing, skill at something — that verbs can
  require and change, including gradually over time.

They only think when somebody is there to see it. A world with nobody active in
it is asleep and costs nothing: characters act while you are in the room with
them, keep going for a few minutes after you leave, and go still altogether once
five minutes pass with nobody typing.

`worldmode always` lifts both of those, when what you want is to watch a world
run rather than to play in it — every character acting every turn, on the far
side of the map, in rooms you have never visited. Every one of those turns is a
model call, so it is the one setting that will quietly spend money while you make
a sandwich; it puts itself back to `normal` the moment the last player logs out,
and nothing ever switches it on but you.

### Help without an autopilot

Large generated worlds get large. `goal go to the library` turns what you said
into a checkable goal and then, under every command you type, quietly suggests
the next thing that would get you closer. `quests hint` does the same for an
errand somebody gave you.

It is the same planner the NPCs use, and it never acts for you — wander off,
take a longer route, or drop the goal, and the next suggestion is worked out
from wherever you actually ended up.

The other half of finding your feet is being able to ask what a world means by
its own words, and every word it invents gets a help entry of its own, written
at the moment it was invented: `help bottle` for a sort of thing and what can be
done to one, `help burn` for what that verb may be done to, `help empty` for a
condition, `help composure` for a figure you are measured by.
`help vocabulary` says how those four differ; `help kinds`, `help affordances`
and `help conditions` list everything this world has put in each. They are per
world, so a new one knows almost nothing until it has been played in.

### Tune it per job

Every part of the game — naming rooms, writing dialogue, deciding what a verb
means — is a separate job with its own model and its own sampling settings.
Dialogue is usually better loose and surprising; the rules that decide what an
action does want to be dull and repeatable. Both the model and its temperature,
top-p, penalties and the rest are set per job in the `models` menu.

---

## Getting it running

You need **Python 3.13** and an **OpenRouter account**.

### 1. Get the code

```bash
git clone https://github.com/fastfinge/aimud.git
cd aimud
```

### 2. Make a virtual environment and install

With [uv](https://docs.astral.sh/uv/), which is what this project uses:

```bash
uv venv
uv sync
```

Or with plain pip:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install "evennia>=6.1.0" "mnemosyne-memory[all]>=3.15.1"
```

### 3. Create your database

Everything below runs from the `aimud/` game directory with the virtual
environment active:

```bash
cd aimud
evennia migrate
```

This creates `server/evennia.db3` — **your** database, holding your accounts,
your worlds and your API key. It is not in this repository and never should be;
see [Before you host this anywhere](#before-you-host-this-anywhere).

### 4. Start the server

```bash
evennia start
```

The first start asks you to create a superuser account: a name, an email
(anything — it is not verified) and a password. That is the account you will
log in with.

The game is then at:

| Where | Address |
|---|---|
| MUD client (telnet) | `localhost:4000` |
| Web client and website | http://localhost:4001 |

Connect with any MUD client, or just open the web client in a browser.

While developing:

```bash
evennia reload    # reload code without disconnecting anyone
evennia stop
evennia status
```

### 5. More accounts (optional)

Anyone connecting to your server can make their own account from the login
screen with `create <name> <password>`. **Each account needs its own OpenRouter
key** — keys are per account, and one account cannot spend another's. Please
read the hosting section before inviting anyone.

---

## Your first world

Three steps, in this order. Nothing will generate until all three are done.

### 1. Give the game your API key

Get one from <https://openrouter.ai/keys>, then in-game:

```
apikey set sk-or-v1-...
```

The key is stored on **your account, in your own database**. It is not in any
file in this repository, not in the settings, and not visible to other
accounts. `apikey` on its own tells you whether one is set (never the key
itself), and `apikey delete` removes it.

Put some credit on the OpenRouter account, or pick free models — see
[What it costs](#what-it-costs).

### 2. Choose your models

```
models
```

This opens a menu with a screen for each job the game does. Each screen sets
which model answers, and how it is asked:

```
Configure: dialogue   NPC dialogue generation

  Model  z-ai/glm-5.3-flash  (set for this function)

Settings — what is sent with every request for this function:
   1. Temperature          1.2        (yours)
   2. Top P                0.95       (model default)
   3. Top K                0          (OpenRouter default)
```

Every setting shows what it currently stands at even if you have never touched
it, and where that figure came from — so you can see how it is set before
deciding whether to change it. Only settings you changed yourself are sent.

**Setting `default` alone is enough to start.** Everything else falls back to
it. Tune individual jobs once you know what you want more of.

A reasonable starting split — cheap where it is called constantly, capable
where it is called rarely:

| Job | Wants |
|---|---|
| `naming` | fast and cheap; called for every new room |
| `dialogue` | fast and cheap; called for every line an NPC hears |
| `rooms`, `contents`, `items`, `npcs` | mid-range — this is the prose you read |
| `commands`, `quests`, `validation` | your most capable model: structured decisions, called rarely, and getting them wrong is what makes a world incoherent |

### 3. Make a world

```
worldgen
```

This opens a wizard:

- **Title** — a short name for your world list.
- **Description** — as long as you like. Everything in the world is generated
  with this in front of it. Write `<user>` where the player should be named and
  it becomes whatever you are called in this world, so *"\<user\> is the
  rightful heir"* is true of whoever is playing.
- **Your name** and **your looks** here.
- **Guidance** — a separate note for each generator, read only by that one:

  | | For example |
  |---|---|
  | Rooms | "the world takes place entirely underground" |
  | Characters | "every character is a vampire" |
  | Items | "there are no firearms; everything is salvage" |
  | Dialogue | "nobody says the emperor's name aloud" |
  | Rules | "this is a world of technology; magic does not exist" |

  This is the part that makes complicated worlds work. The description is read
  by everything, so it has to stay short enough that everything still attends
  to it. Anything concerning one task alone goes in that task's guidance, where
  it can be as detailed as you like without crowding anything else out.

Then `g` to generate. The first room takes a few seconds, and you are moved
into it when it is ready.

Use `worldedit` afterwards to change any of this without throwing the world
away — edits govern whatever is generated from then on, and what already exists
keeps the text it was written with. `worldreset` rebuilds from scratch.

---

## Playing

Ordinary MUD commands work: `look`, `get`, `drop`, `say`, `pose`, and compass
directions to move.

Beyond that:

- **Just try things.** Any verb the game does not know is worked out on the
  spot: `light the candle`, `read the notice`, `pry the grate`, `wash the
  bloodstain out of the apron`. The first use of a new verb costs a call or
  two; after that it is free.
- **Look at things that are only mentioned.** If a room's description talks
  about a blackboard, `look blackboard` turns it into a real object you can
  then act on.
- **Talk to people.** `say` anything to anyone in the room. They remember it.
- **Take errands.** NPCs will ask you for things. `quests` to see them,
  `quests accept`, and `quests hint` when you get stuck.
- **Set a goal.** `goal find the brass key` gets you a nudge under every
  command until you have it; `goal` alone drops it.
- **Get dressed.** `wear`, `remove`, `cover`, `inventory`. What you have on is
  part of how you look to everyone else.
- **Empty your pockets.** `drop all` puts down everything at once, clothes
  included, for when several worlds' worth of interesting objects have
  accumulated about your person.
- **Check yourself.** `score` shows every trait this world has decided to
  measure about you, and how much of each is lent to you by what you are
  wearing, holding or standing next to.
- **Ask what a word means.** `help bottle`, `help burn`, `help empty`,
  `help composure` — every word a world invents explains itself. `help
  vocabulary` says how the four sorts of word differ.
- **See the shape of the place.** `zones` lists the areas this world planned
  for itself, how full each one is, and which you are standing in.
- **Watch it run without you.** `worldmode always` has every character in the
  world act every turn, wherever you are. It costs a call each time one of them
  does; `worldmode normal` puts it back, and so does logging out.

---

## Command reference

### Account level

| Command | What it does |
|---|---|
| `apikey` / `apikey set <key>` / `apikey delete` | Your OpenRouter key. Per account. On its own it says whether one is set, never what it is. |
| `models` / `models refresh` | Model and sampling settings for each job. `refresh` re-fetches the model list from OpenRouter. |

### World

| Command | What it does |
|---|---|
| `worldgen [<description>]` | The wizard: make a new world. |
| `worlds` / `worlds <n>` | List your worlds, or enter one. |
| `worldedit [<n>]` | Change a world's text without rebuilding it. |
| `worldreset [<n>] confirm` | Wipe and regenerate from the same setup. |
| `worldremove <n> confirm` | Delete a world permanently. |
| `worldmode [normal \| always]` | Whether this world thinks only while watched, or all the time. On its own, says which. |
| `worldopen` | Open a way on, in a world that has built itself into a corner and has nowhere unexplored left. |
| `zones` | The areas of this world, how full each is, what may exist only once in each, and where you are. |
| `rules` / `rules <verb>` | Every rule this world holds, or only the ones about one verb: what it needs before it will work, what it does, and what follows. In the order they are consulted, which is the point — a rule about datapads decides what powering a datapad does even aboard a ship with its own rule about powering. Costs nothing. |
| `rules suggest` | What this world's own faults and refusals suggest it is missing, each with the evidence for it. A condition it can set and never unset, beside a verb it has refused over and over, is usually one rule nobody wrote. Costs nothing — nothing is asked of a model and nothing is ever installed unasked. |
| `rules accept <id>` / `rules reject <id>` | Take a suggestion up, or decline it. A declined one is remembered as declined and not offered again. |
| `rules judge` | Hand the whole queue to a model at once and apply its verdicts. The only part of `rules` that costs anything, and it is one call for the lot: the model is judging filled-in rules with the world's own counts beside them, never writing one. |
| `npcgen` | Put a character in the current room. |

### Playing

| Command | What it does |
|---|---|
| `look [thing]` | Look. Mentioned-but-nonexistent things become real. |
| `get <thing>` | Pick something up. |
| `drop <thing>` / `drop all` | Put something down. `all` empties you out, worn clothes included. |
| `help [<topic>]` | Commands, topics, and every word this world has invented for itself. |
| `name [<what you are called here>]` / `name clear` | Rename yourself in this world, per world. |
| `follow <person>` / `follow` | Travel with somebody, or stop. |
| `pose <action>` / `emote` | Emote. |
| `remember <question>` / `recall` | Ask your own memory something. |
| `score [trait]` / `traits` / `sheet` | Your traits, what they stand at, and what is lending you the difference. |
| `wear` / `remove` / `cover <worn> with <item>` / `uncover` / `inventory` | Clothing. `don` and `doff` also work. |
| `wield <thing>` / `unwield <thing>` | Take something in hand, or lower it. Two hands, so a sword and a shield. |
| `quests` / `quests hint` / `quests accept \| decline \| abandon` | Errands. `quest` also works. |
| `goal <what you want>` / `goal` | Set or drop a goal, with nudges. |

### Upkeep

One command, and it needs Builder or Admin permission — on a single-player
install that is the superuser you made at first start.

| Command | What it does |
|---|---|
| `worldcheck [<n>]` | What a world's rules say about each other: conditions it can set and never unset, conditions a rule requires that nothing can bring about, verbs it refused and why. Then what the world has actually been asked to do and how it answered — a condition nothing can bring about matters more when eleven people have tried. Says if anything is waiting in `rules suggest`. Costs nothing — no model is asked anything. |
| `memcheck [sleep \| sweep \| distil \| all]` | Memory upkeep now rather than on its clock: consolidate what characters remember, delete the banks of characters that no longer exist, or turn recent summaries into what a character now knows. On its own it reports what it would do and changes nothing. Distilling is the only part that costs anything. |

---

## What it costs

You pay OpenRouter directly for what your key uses. The game adds nothing, and
it tries hard to spend as little as possible: rules and narrations are cached,
the planner runs on pure Python with no model involved, and **a world with
nobody active in it does not think at all**.

### What triggers a call

| What you do | Calls | Notes |
|---|---|---|
| Create a world | 4–6 | Plan, name, describe, furnish, maybe a person |
| Walk into a new room | 3–6 | Naming, description, contents, maybe a person |
| Re-enter a room you have been to | 0 | Everything is stored |
| Say something with an NPC present | 1 per NPC | The big recurring cost |
| Try a verb the world has never seen | 2 | Rule + narration |
| Try that verb again, anywhere | 0–1 | The rule is free; a new object needs narration |
| Try a known verb on a sort of thing nobody has tried it on | 1 | One bit — can this be done to that at all — kept for that whole sort |
| Try something that sort has already refused | 0 | "You cannot burn the key", for nothing |
| Lose a fight you have already lost once | 0 | Each outcome is narrated once per thing |
| Look at something only mentioned in prose | 2 | Plausibility check + creation |
| Take on an errand | 1 | Turning it into something checkable |
| An NPC acting on its own | 0–1 | Free whenever the planner finds a step |
| Walking, `score`, `inventory`, `quests`, `zones`, `help`, `goal` nudges | 0 | No model involved |
| A world in `worldmode always` | 1 per character per turn | Every character, everywhere, whether or not you are watching |

### Roughly what that adds up to

Measured from the actual prompts. An **evening of play** — making one world,
exploring about twenty rooms, a hundred or so lines of conversation and thirty
new verbs — comes to roughly **450,000 input and 50,000 output tokens**.

At list prices, for that whole evening:

| If you used this for everything | Cost |
|---|---|
| A free model | **$0.00** |
| `inception/mercury-2.5-preview` ($0.04 / $0.15 per Mtok) | **~$0.03** |
| `openai/gpt-4o-mini` ($0.15 / $0.60) | **~$0.10** |
| `google/gemini-3.8-flash` ($0.75 / $3.75) | **~$0.53** |
| `google/gemini-3.1-pro-preview` ($2 / $12) | **~$1.50** |
| `anthropic/claude-opus-5` ($5 / $25) | **~$3.50** |

A sensible mix — something cheap for naming and dialogue, something capable for
rules and quests — lands nearer the bottom of that range than the top, because
the expensive jobs are the rare ones.

**Cost scales with conversation, not with map size.** Twenty rooms is about
80,000 tokens; a hundred lines of dialogue is about 300,000, because an NPC's
prompt carries its memories, its surroundings and its tool definitions every
single time. If you want to spend less, the one most effective change is a
cheaper `dialogue` model.

Prices above were current when this was written and change often — check
<https://openrouter.ai/models>. **There are usually a dozen or more genuinely
free models on OpenRouter**, and the game runs on them: set a free model as
your `default` to try everything at no cost, and expect rougher prose.

### Keeping the bill down

- Set a spending limit on your OpenRouter key. Do this first.
- A world nobody is in is asleep. Five minutes without typing and you stop
  counting as present, so an idle window costs nothing.
- Cheap `naming` and `dialogue`; capable `commands` and `quests`.
- Leave `worldmode` at `normal` unless you are deliberately watching a world
  run. It is the one setting that spends money with nobody reading the output.
- `worldreset` regenerates an entire world and costs an entire world's worth.

---

## Before you host this anywhere

**Run this for yourself, or for people you know. Please do not put a public
instance on the internet.**

That is not modesty about the code — it is a specific and honest assessment:

- **Most of this codebase was written by an AI assistant** (Claude, working
  with the repository owner) and has been reviewed for whether it *works*, not
  audited for whether it is *safe against hostile users*. Those are different
  standards, and only one of them has been met.
- **Every account's OpenRouter key sits in the same database.** They are kept
  apart by account, and nothing in the game is designed to show one account
  another's key — but "not designed to" is a much weaker claim than "proven not
  to", and it is somebody else's money.
- **Players type text that becomes part of model prompts.** World descriptions,
  guidance, goals and speech all reach a model. What a determined user could
  talk a model into doing on a shared instance has not been explored.
- **Evennia's builder commands, admin and web admin are all present** with
  default permissions.
- Worlds are per account and are not shared, but that separation has not been
  tested adversarially either.

If you want to play with friends: run it on a machine you control, for people
you trust, and have everyone use their own key with a spending limit set on it.

### What is safe to publish

This repository contains **code only**. The database (`server/evennia.db3`),
`server/conf/secret_settings.py`, the log files and the per-character memory
banks under `server/memory/` are all gitignored and have never been committed.
Your API key lives in the database and nowhere else.

If you fork this, keep it that way: check `git status` before you commit, and
never `git add -f` anything under `server/`.

---

## How it fits together

Evennia splits the server into a Portal and a Server process and uses Django
underneath. Every network call to OpenRouter is deferred to a thread pool; all
database work happens on the main Twisted thread.

```
aimud/
  commands/      one file per group of player commands, plus the cmdsets
  typeclasses/   the game's entities: rooms, exits, characters, NPCs, garments
  world/         the game itself — everything below
  server/conf/   settings; secret_settings.py is local and gitignored
  web/           the Django web client and website
```

The interesting half is `world/`:

| Module | What it is for |
|---|---|
| `worldgen.py` | Building rooms: planning, naming, describing, furnishing |
| `zones.py` | The areas a world plans for itself, and how large each may get |
| `coords.py` | Where rooms are, so a world can close back on itself |
| `lore.py` | What a world says about itself, and per-generator guidance |
| `verbs.py` | Parsing, binding nouns to objects, the world's state vocabulary |
| `verb_gen.py` | Learning what a verb does; narrating what happened |
| `attempt.py` | One verb attempt, deciding everything free before paying |
| `effects.py` | The only way a verb changes the world |
| `checks.py` | Rolling for an outcome, so trying is not the same as doing |
| `kinds.py` | What sort of thing something is, and what that sort affords |
| `affordances.py` | The vocabulary of what can be done to a thing — verbs, not adjectives |
| `lexicon.py` | What English already knows: inflections, senses, what is a kind of what |
| `vocabulary.py` | One word, one meaning: the four registers a world fills in as it runs |
| `relations.py` | What is in, on, under or behind what |
| `gear.py` | What a thing is worth to whoever wears, wields or stands beside it |
| `npc_gen.py` | Creating characters, dressing them, and their dialogue |
| `activity.py` | Who is worth thinking about just now, and what `worldmode` changes |
| `goals.py` | Conditions about the world that can be tested |
| `planner.py` | One next step towards a goal, with no model involved |
| `quests.py` | Errands: offering, accepting, testing, rewarding |
| `traits.py` | Figures about people, and the world's register of them |
| `clothing.py` | Wearing things, and what that does to how you look |
| `item_gen.py` | Deciding whether a thing could be here, and making it if so |
| `naming.py` | Recognising the thing somebody meant, so a typo is not a new object |
| `hints.py` | Giving a player the same help an NPC gets |
| `memory.py` | Per-character memory, written and recalled by relevance |
| `fact_gen.py` | Turning what a character has been through into what it knows |

Two ideas run through all of it and explain most of the design:

**Pay once, for the part that generalises.** A verb rule is stored against the
*kind* of thing it acts on — and a kind is a closed dictionary sense rather than
a written string, so it cannot drift out from under the rule — which means the
rule is learned once for every readable object in the world. A narration is
stored on the object, so it travels with it. Neither is stored on the room,
which is what stops results that only made sense where they were first produced.

**Decide everything free before paying for anything.** An attempt parses, binds
nouns, checks the cache and tests preconditions before a model is consulted at
all. The NPC planner reads verb rules and the map — both already in memory —
and only falls through to a model call when it genuinely has nothing to work
with.

---

## Contributing

Issues and pull requests are welcome, particularly:

- prompt work — better output for the same money is the highest-value change
  available here;
- bug reports, with the world description that produced them;
- anything at all about the security concerns above.

Please do not put your API key or your database in an issue. If you attach a
world description, that is exactly the useful part.

## Licence

BSD 3-Clause, matching Evennia. See [LICENSE](LICENSE).
