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

To add a command: create it in `commands/command.py` (or a new file), then add it to the appropriate cmdset in `default_cmdsets.py`.

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
