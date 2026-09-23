# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This is an AI-assisted MUD (Multi-User Dungeon) game built on [Evennia](https://www.evennia.com/), a Python MUD framework. The game server name is `aimud`. The `aimud/` directory is the Evennia game directory; the repo root also contains a stub `main.py` and `pyproject.toml` (Python 3.13).

## Commands

All Evennia commands must be run from `d:\src\aimud\aimud\` with the Evennia virtual environment active:

```bash
evennia migrate       # initialize/update the database (run after first setup or model changes)
evennia start         # start server (MUD on localhost:4000, web on localhost:4001)
evennia stop          # stop server
evennia reload        # hot-reload code without disconnecting players
evennia shell         # open a Python shell with full Evennia/Django context
evennia status # check server status
```

## Tests

Run from the game directory, the same one the `evennia` commands above need:

```bash
evennia test --settings settings.py --exclude-tag=llm tests   # free and deterministic
evennia test --settings settings.py --tag=unit tests          # the inner loop
evennia test --settings settings.py --tag=llm tests           # costs money, needs a key
```

The `llm` tests need no key file. `tests/live.py` reads the API key, address and
model choices of the admin account straight from the local game database
(`server/evennia.db3`, read-only; `AIMUD_LIVE_DB` points elsewhere), so they run
wherever somebody has set the mud up and used `settings apikey`. Where nobody
has, they skip themselves. Use `live.live_sponsor(self)` in a live test where a
free one would use `FakeSponsor`. Tag the test class `llm`, and remember that
naming a test module on the command line without `--exclude-tag=llm` runs its
live tests too.

`tests/test_model_bench.py` compares dialogue models on real NPC turns and is
tagged `bench` as well as `llm`. It skips itself unless `AIMUD_BENCH=1` is set,
so running the live tests never runs it by accident; its docstring says how to
choose the models and how many times each scene is played.

`--settings settings.py` is not optional. Without it the run uses Evennia's
default settings and so skips this game's test runner
(`server/conf/test_runner.py`), which stops the suite hashing a real password
for every fixture account and garbage-collecting the WordNet indices after
every test. Those two cost about twenty minutes of wall clock between them.

### Fixtures: start small, opt in

Test base classes live in `tests/base.py`. **Do not inherit from Evennia's
`EvenniaTest` or `EvenniaCommandTest` directly.** Use `GameTest` and
`GameCommandTest`, which build one room (`room1`) with one character (`char1`)
standing in it, and nothing else. Anything more is a class attribute:

| attribute       | default | what it adds                                    |
|-----------------|---------|-------------------------------------------------|
| `characters`    | `1`     | `char1`; `2` also makes `char2`                 |
| `loose_objects` | `0`     | `1` makes `obj1`; `2` also makes `obj2`         |
| `second_room`   | `False` | `room2`, and `exit` leading there from `room1`  |
| `accounts`      | `False` | `account`/`account2`, puppeting the characters  |
| `session`       | `False` | a logged-in session; implies `accounts`         |
| `script`        | `False` | a bare `Script`, as `self.script`               |

```python
class TakingSomething(GameTest):
    loose_objects = 1
```

The names are upstream's, so a test that outgrows its category only changes the
line at the top. For logic that needs no world at all, use `SimpleTestCase`.

When adding a test, add the dial you need and no more. In particular `accounts`
is almost never the answer -- an account is the out-of-character layer, and a
test about what a character does in a room does not need one -- and
`characters = 2` is the most expensive dial there is.

**Read the module docstring in `tests/base.py` before adding a test class.** It
records how every existing class was assigned its category, and why a fixture
can be load-bearing without being named in the test.

## Architecture

Evennia's architecture separates the server into two processes (Portal and Server) and uses Django for the database and web layer.

### Typeclasses (`typeclasses/`)

All in-game entities are Python classes that inherit from Evennia defaults. The `ObjectParent` mixin in `typeclasses/objects.py` is the place to add behavior shared across ALL world entities (Characters, Rooms, Exits, Objects).

- `objects.py` — `ObjectParent` mixin + base `Object`; override hooks like `at_object_creation()`, `at_drop()`, `return_appearance()` here
- `characters.py` — `Character(ObjectParent, DefaultCharacter)` — player-controlled entities
- `rooms.py` — `Room(ObjectParent, DefaultRoom)`
- `exits.py` — `Exit(ObjectParent, DefaultExit)`
- `accounts.py` — `Account(DefaultAccount)` — out-of-character account layer (separate from Character)
- `scripts.py` — `Script(DefaultScript)` — timers and persistent background processes

### Commands (`commands/`)

- `command.py` — base `Command` class; all game commands subclass this
- `default_cmdsets.py` — four cmdset classes (`CharacterCmdSet`, `AccountCmdSet`, `UnloggedinCmdSet`, `SessionCmdSet`) that wrap Evennia defaults; add/override commands in `at_cmdset_creation()`
- `verbs.py` — the eight verb commands: `create`, `edit`, `delete`, `reset`, `view`, `import`, `export`, `enter`. Each only finds a subject and hands over the rest of the line.
- `subjects.py` — the subject registry, and helpers every subject shares (`require_world`, `require_owner`, `answered`, `asking`). `SUBJECT_MODULES` lists the modules that define subjects: `world_subject.py`, `rules_subject.py`, `contents_subject.py`, `upkeep_subject.py`, `settings_subject.py`, `score_subject.py`.
- `settings_cmds.py` — `settings`, over the register in `world/preferences.py`.

**Adding something a player makes, changes or reads belongs in a subject, not a
new command.** Add a `Subject` with a `Use` per verb to a subject module (or a
new module listed in `SUBJECT_MODULES`): `run(cmd, ctx, words)` for the command
line, `items(ctx)` for the verb's menu, `offered(ctx)` for who sees it. Inside
a generated world the parser only gives a verb command the input when the next
word is one of its subject words (`server/conf/cmdparser.py`), so `reset world`
is ours and `reset the trap` is still the world's. A command whose word a world
must never use as a verb sets `reserves_word = True`.

**Anything that asks the player to choose uses `world/menus.py`.** Describe the
menu as a `Form` of `Field`s, `Action`s and `Submenu`s and call
`menus.open_menu`. Never build an `EvMenu` by hand, never print usage when a
menu would do, and never ask a question another way. A form gets the shared
keys, screen-reader layout, confirmations (`Action(confirm=...)`, with a
matching entry in `preferences.CONFIRMATIONS`), `?` help, `~` fill-in for
`suggestible` fields, presenter hooks for sounds and MXP, and a text fallback
for callers with no session. Every point in a menu must also be reachable by
typing a command.

**A player's preference is a setting.** Add a `Field` to a group in
`world/preferences.py`, stored in an attribute. Do not add a single-purpose
command for it.

### World content (`world/`)

- `prototypes.py` — module-level dicts define object prototypes (spawnable templates); use `evennia.spawn()` or in-game `spawn` command to instantiate them
- `batch_cmds.ev` — batch command scripts for populating the world
- `help_entries.py` — additional help entries beyond auto-generated command help

### Configuration (`server/conf/`)

- `settings.py` — extends `evennia.settings_default`; currently only sets `SERVERNAME = "aimud"`
- `secret_settings.py` — machine-local overrides (not committed); imported last so it overrides `settings.py`

### Web layer (`web/`)

Django-based web interface. `web/urls.py` is the root URL config, including Evennia's built-in patterns plus subpath includes for `website/`, `webclient/`, and `admin/`.

## Key Evennia patterns

- Persistent data on objects uses `obj.db.attribute = value` (stored in DB) or `obj.ndb.attribute = value` (in-memory only)
- `self.caller` inside a command is the Character (or Account for account-level commands)
- `self.caller.msg("text")` sends text to the player
- Locks are strings like `"get:holds(); drop:holds()"` set via `obj.locks.add(...)`
- Tags group objects: `obj.tags.add("tagname", category="category")`
