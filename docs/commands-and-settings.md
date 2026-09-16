# Development plan: commands, menus and settings

Status: phases 1 (the menu engine), 2 (settings), 3 (verbs, subjects and
worlds) and 4 (every other subject) are built. Phases 5 and 6 are not started.
The open questions are settled; see §11.

This covers the first two items in `future-plans.md`: sorting out the command
system, and a settings command. Both depend on a third thing neither item
names, a reusable menu engine. The player building commands later in
`future-plans.md` are meant to reuse that engine too.

---

## 1. The change, on one page

This game has more than thirty commands of its own today. Each one reads its
own arguments in its own way. Commands that act on a world choose it in four
different ways: `_choose_world`, their own numbering, `rounds world <n>`, or
the room you are standing in. Two commands ask for confirmation, and both do
it by making you retype the command with `confirm` on the end. There are
three menus, each built from scratch: `models` has type-to-filter and pages,
`worldgen` has neither, and `pronouns new` has its own conventions. `busy`,
`apikey` and `models` are each a command for a single preference.

So the work is five things:

* **One menu engine** (`world/menus.py`) on top of Evennia's `EvMenu`. Every
  menu gets the same keys: numbers to choose, `b` for back, `q` to quit, `l` to
  list the options again, `?` for help, `~` to have a model fill something in,
  and type-to-filter once a list is long. It also has one place to hook in
  later for sounds, MXP and OOB (§3).
* **Forms and fields.** A menu is described as data: fields with a type, a
  current value, a default, help text, a check on what is entered, and
  whether a model may fill it in. The settings registry, `~`, `?` and future
  building menus all read that same description (§3.2).
* **Eight verbs with subjects**: `create`, `edit`, `delete`, `reset`, `view`,
  `import`, `export` and `enter`, plus `settings`. Subjects register with a verb:
  `create world`, `view rules`, `delete tokens`, `enter world`. Leave the
  subject out and you get a menu. Give part of the arguments and the menu opens
  at that point. Give all of them and there is no menu (§4, §7). `enter` can
  also take you back to Limbo, which nothing can do today (§4.4).
* **A settings registry** (`world/preferences.py`) that covers all three
  scopes: your account, you in this world, and this world. It includes a
  switch for every confirmation. Settings are stored in the attributes the
  game already uses, so no data has to be migrated (§5).
* **Every confirmation is a yes/no menu**, and each one has a setting that
  turns it off (§8).

---

## 2. Should our commands start with `@`?

**No.** In Evennia, `@` does not keep our commands apart from anything else,
and the `@` names we would want are already taken.

**`@` does not keep commands apart.** `CMD_IGNORE_PREFIXES` is `"@&/+"`.
Evennia first tries an exact match, prefix included. If nothing matches, it
strips the prefix and tries again. So a bare `create` reaches a command keyed
`@create`, and `@create` reaches one keyed `create`. The only split between
`open` and `@open` that exists today is our own rule in
`server/conf/cmdparser.py`: inside a generated world, a staff command only
runs if you type the prefix.

**The names are taken.** Evennia's building and system commands already use
the same words:

| we would want | Evennia already has | what it does |
|---|---|---|
| `@create` | `@create` | builder: makes an object |
| `@delete` | alias of `@destroy` | builder: destroys an object |
| `@reset` | `@reset` | **restarts the server** |
| `@view` | (`@examine`) | builder: dumps attributes |
| `@edit` / `@set` | `@set`, `@desc`, `@name` | builder: raw attribute editing |

A cmdset treats two commands as the same if their key or aliases overlap. An
`@create` of ours would replace the builder's `@create` for everyone. An
`@reset` of ours would replace the server restart, and anyone who removed the
game's cmdset would be one typo from restarting the server. A different prefix
does not help either. If ours were keyed `+create`, a bare `create` would match
both `+create` and `@create` once the prefixes were stripped, and give a
multimatch.

**Reserving the words has its own cost.** Blocking the world from ever
inventing `create`, `edit`, `delete`, `reset`, `view`, `import` and `export`
takes away verbs that interactive fiction uses: `reset the trap`,
`view the mural`, and `create fire` in the planned endless alchemy world.
`view` is also already a synonym of `look` in `VERB_SYNONYMS`.

### Recommendation: a command only takes input that names one of its subjects

Keep the verbs bare, and extend the parser rule that already exists:

> Inside a generated world, a subject command takes input only when there are
> no arguments, or when the first word names a subject registered for that
> verb (`world`, `worlds`, `rules`, `settings`...). Anything else is dropped as
> a match, so the no-match command hands it to the world.

So `reset world` resets the world, while `reset the trap` goes to the world
as a verb. `view rules` lists rules, and `view the mural` folds to `look` the
same way it does today. `create` on its own opens the menu. `create fire` goes
to the world.

This is the same mechanism as the staff rule: `cmdparser` drops a match
instead of choosing another one, and the no-match command sends the input to
the world. It also avoids the problem the parser's docstring warns about:
whether a command matches depends on our registry of subjects, which a world
cannot add to. It never depends on what a world has learned. Outside a world,
input that names no subject says what can be created and opens the menu.

Two things need registering, and neither of them is the verbs themselves:

* **Subject words.** They become phrases a world cannot use in that exact
  shape. The item and room generators should be told that a thing called
  "world", "rules" or "settings" is best avoided. When it happens anyway,
  `look at rules` still works.
* **Everything that stays a command by its bare name** (`settings`, `follow`,
  `goal`, `quests`...). `verbs.engine_verbs()` already tells generators which
  verbs the engine answers, but it only reads the `General` help category. It
  should read a flag on the command instead, so moving a command to another
  help category cannot quietly stop reserving it.

**Retired names.** `worldgen`, `worldremove` and the rest are gone once this
is built. If someone types one inside a world, it would reach a model as a
brand new verb and cost a call. The near-miss check in `unknown_cmd.py`
should get a small table of retired names that answers, for example, "That is
`create world` now." It costs nothing and removes itself cleanly later.

---

## 3. The menu engine

### 3.1 Built on EvMenu, not beside it

`EvMenu` already provides what is needed: a cmdset that takes over input,
callable gotos, `EvMenuGotoAbortMessage` to stay on a node, and a `msg` that
tags output `type=menu` for OOB clients. `GameMenu(EvMenu)` overrides three
things:

* `parse_input`, for the shared key grammar (§3.3).
* the formatters, for layout that works with a screen reader (§3.6).
* `__init__` and `close_menu`, for the open and close hooks (§3.7).

Nodes are generated from a form (§3.2), not written by hand. Three hand-written
menus are ported: the models menu, the worldgen wizard, and pronouns. Once
they are, no module outside `world/menus.py` imports `EvMenu`.
`world/choosing.py` already reserved this: "every caller here changes in one
place". Its `ask` becomes the engine's single-choice menu, which covers the
disambiguation menu and the "rule shows the player a menu" action from
`future-plans.md`.

Menus run on the account when there is one, at `cmdset_priority=110`. That is
the fix `model_menu._open_menu` already needed, because exit commands were
swallowing `n` and `p`. It moves into the engine so no future menu has to find
that out again.

### 3.2 Forms, fields and actions

A form is data that describes a menu:

```python
Form(
    key="world",                       # used in help, logs, the ~ prompt
    title=lambda ctx: ...,
    intro=lambda ctx: ...,             # plain text above the options
    items=[Field(...), Action(...), Submenu(...)],
    sponsor=lambda ctx: ...,           # who pays for ~ (None: ~ unavailable)
    context=lambda ctx: ...,           # extra facts for ~ (e.g. the world description)
    command=lambda ctx: "edit world 2" # the command line that reaches this node
)
```

**Field** kinds: `text`, `long_text` (opens EvEditor and comes back, as
worldgen does today), `number` (with a range), `boolean`, `choice` (fixed or
built at call time, and it may be long) and `secret`.

Every field has:

* `key` and `label`.
* `help`: plain text, or the name of a help topic (§6).
* `get(ctx)`, `set(ctx, value)` and `default(ctx)`.
* `parse(text)`, returning `(value, complaint)`. That is the shape
  `busy.parse_interval` and `model_params.parse` already have, so they plug
  in unchanged.
* `suggestible`: whether `~` may fill it in. Off by default. Never on for
  `secret` fields, or for fields that choose a target (§5.4).
* `lock`: who may see it and who may change it.

**Action**: a label, a callable, optionally a confirmation key (§8), a lock,
and `after`: `stay` on the node, go `back` one level, or `close` the menu.
Actions that finish the job, such as generate, save, delete and enter, close
it. Nobody should have to type `q` after `delete world 2` has done what it
said.

A form is also either an **edit** form or a **view** form. An edit form is
used to change something over several steps, such as `create world` or
`settings`. A view form is there to be read, such as `score`, `quests`, `view
rules` and `view worlds`. The two close differently (§3.9).

**Submenu**: another form, with the context passed along.

Forms work on a draft or live. The worldgen wizard is a draft: nothing is
written until you save or generate. Settings are live: each change is written
straight away. A draft form that is quit with unsaved changes asks for
confirmation first (`confirm.discard`, §8).

### 3.3 Keys that work in every menu

Input is checked in this order, and the first match wins. This is the full
set of keys an edit menu uses. A view menu claims fewer of them (§3.9).

1. **An option**, by number or by name: `3`, `title`, `generate`.
2. **Navigation**:
   * `b` / `back`: up one level. A menu that was opened part-way (for example
     `delete world` goes straight to the list of worlds) still backs up
     through the levels you skipped. Typing part of a command is a shortcut
     into the menu, not a separate menu.
   * `q` / `quit`: close every level at once.
   * `l` / `look`: show the options again. These are EvMenu's own keys, and
     the right choice once NPC speech or busy notices have pushed the menu
     off screen.
   * `n` / `next` and `p` / `prev`: only on a paged list.
3. **`?`**: help. Just `?` opens a submenu of the options that have help. `?3`
   and `? title` go straight to that option's help. `h` and `help` do the same
   as `?`.
4. **`~`**: fill in with a model. Just `~` opens a submenu of the fields that
   can be filled. `~2` and `~ title` go straight to one. Only offered when
   the form has a sponsor and the sponsor has a key.
5. **Filter text**, only on filterable lists: any other input narrows the
   list. An empty line clears the filter, as the models menu does today. To
   filter for something that is also a reserved key, start it with `/` (`/b`).
   The same `/` works when typing into a field: `/b` sets a field to "b". In a
   field that is not required, `clear` removes its value, and `/clear` types
   the word.
6. Anything else: "That is not one of the options. `l` lists them, `?` explains
   them."

Option keys a form defines may not reuse a reserved key. The engine refuses to
build a form that tries, so no menu ever has a `q` that does something other
than quit. The models menu uses `r` for reset, `c` for clear, `x` for drop and
`m` for model. Those become named options, still reachable by number.

### 3.4 Defaults come first

Where a command assumes something today, that assumption becomes option 1 and
is marked `(the default)`:

| command | assumes today | option 1 |
|---|---|---|
| `edit world` / `reset world` / `view faults` | the world you are in | the world you are in |
| `goal` | clear the goal | give up the current goal |
| `quests` | show the list | show the list |
| `score` | every trait | every trait |
| `rules`, `effects` | every verb | every verb |
| `memcheck` | report only | report only |
| any confirmation | not confirmed | **No** |

The last row is the useful one. What every command assumes today when you do
not confirm is that nothing happens, so **No** comes first in every yes/no
menu without needing a special rule.

### 3.5 Every menu is also a command line

Every point in every menu can be reached by typing a command. For example,
`delete world 2 yes` reaches the end of the delete menu. This matters for
four reasons:

* **Things with no session never see a menu.** NPCs, scripts, `execute_cmd`
  called from code, batch files, and later MCP or ACP agents. `basic-principles.md`
  asks for equal access, which means an agent must be able to do everything
  without the menu. With arguments missing and nobody to show a menu to, a
  command replies with what it needed and the choices it had.
* **Tests** can drive a command in one call.
* **Teaching the shortcut.** When a choice made through the menu finishes an
  action, the engine can say "Next time: `delete world 2`". This is controlled
  by a setting, `menus.show_command`, which defaults to on.
* **The `~` prompt** can tell the model where the player is.

`Form.command` supplies the command line for each point in the menu.

### 3.6 Screen readers

Menus follow the same rule `score` and `rules` already follow: plain prose,
one option to a line, number first, no box drawing or columns. The dotted
leaders in the worldgen summary (`Title . . . . value`) get replaced, because
they are read aloud as "dot dot dot". The layout lives in the formatters, so
it is fixed once for every menu. The account's `uses_screenreader()` is
passed into formatting, so a sighted layout can be added later without
touching any form.

### 3.7 Hooks for later protocol work

One presentation object, `menus.PRESENTER`, is called at these points:

| hook | when | later use |
|---|---|---|
| `opened(menu)` | the menu opens | MSP/GMCP sound, `Client.Menu.Open` OOB |
| `shown(menu, node, options)` | a node is drawn | MXP `\|lc…\|lt…\|le` links on each option, a GMCP option list |
| `chose(menu, option)` | a choice is made | click sound |
| `refused(menu, text)` | input matched nothing | error sound |
| `confirmed(menu, key, answer)` | a yes/no is answered | distinct yes/no sounds |
| `closed(menu, why)` | `quit`, `back` past the top, finished, or interrupted | close sound |

For now every hook does nothing, except that `shown` returns the plain text.
Tests check that each hook is called, so later protocol work can rely on them.
Evennia already turns `|lc` markup into MXP on telnet and into links in the
webclient, so clickable menus are mostly a job for `shown`.

### 3.8 What happens around a menu

* **In a world, an edit menu takes over input.** View menus do not (§3.9).
  `EvMenuCmdSet` is `Replace`, so `say` does not work while an edit menu is
  open, although channels still do.
  Everything around you still arrives on screen. That is acceptable for a
  menu that closes quickly. Nothing makes a menu time out.
* **Menus do not survive a reload** (`persistent=False`). Forms hold closures,
  which cannot be pickled, and a menu is quick to reopen. Drafts are kept on
  `ndb` the way worldgen keeps them now, so they survive the EvEditor round
  trip but not a reload.
* **A menu is filtered by permission.** An option you are not allowed to use
  is not shown. That is the rule `staff_spelling` already follows: someone who
  was never a builder is never told about building commands.

### 3.9 View menus close themselves

`score` has to stay as quick as it is today. Checking it cannot mean a menu
that needs `q` afterwards. So a view form **shows its default straight away**:
bare `score` prints every trait, just as it does now. The choices follow on
one short line ("For one of them: 1 composure, 2 stamina, 3 nerve"). What
happens after that depends on one account setting, `menus.view_menus`:

* **`walk_away`** (the default). The menu stays open, but it only claims its
  own input: numbers, `?`, and `b`/`back` and `q`/`quit`. Anything else closes
  the menu and runs as an ordinary command. So after `score`, typing `2` shows
  stamina, and typing `north` or `say hi` just does that. Nothing ever has to
  be quit.
* **`close`**. No menu is opened at all. The default is shown with its choices
  written as commands ("`score composure` for one of them").
* **`stay`**. A view menu behaves like an edit menu and holds input until `q`.
  This is for someone who wants to browse a long list, such as `view rules`,
  without anything escaping into the game.

A walk-away menu claims deliberately little. Its `l`/`look` and `n`/`p` pass
through, because in a world they mean look and north, and `l` there should
look at the room, not show the menu again. Retyping the command shows it
again. `q` and `quit` are always kept by the menu. Otherwise, typing `quit` to
close a menu would reach Evennia's `quit` command and disconnect you. A paged
walk-away list turns pages with `next` and `prev`.

Edit menus keep the full set of keys in §3.3. They close when an action with
`after=close` finishes, or on `q`.

---

## 4. Verbs and subjects

### 4.1 Shape

There is one command class per verb in `commands/verbs.py`: `CmdCreate`,
`CmdEdit`, `CmdDelete`, `CmdReset`, `CmdView`, `CmdImport`, `CmdExport` and
`CmdEnter`.
Each is an account command (`account_caller = True`) that finds the puppet,
if there is one, so it works both in and out of character. Subjects register
in `commands/subjects.py`:

```python
Subject(
    words=("world", "worlds"),
    verbs={"create": ..., "edit": ..., "delete": ..., "reset": ..., "view": ...},
    lock={"edit": owner_of_world, "delete": owner_of_world, ...},
    needs=("character",),   # or ("character", "in_world"), or ()
    help="...",
)
```

Each verb's handler takes the rest of the arguments and returns either a
finished action or the form node to open, with whatever the arguments already
filled in. Plugins and the future building commands add subjects here
(`create room`, `edit kind`, `view term`) without touching the verb commands.

### 4.2 Choosing a target

The four ways commands choose a world today (`_choose_world`, `worlds <n>`,
`rounds world <n>`, the current room) all become one `choice` field built from `_resolve_worlds`. You can answer
by number or by title, and the world you are standing in comes first. Other
subjects use the same field kind for "which rule", "which list", "which
suggestion" and "which job".

### 4.3 Permissions

This is the permission rule from `future-plans.md`, and the subject registry
is where it lives:

* Anyone may `create world`.
* Only a world's creator (`sponsor.creator_of`) or a superuser may create,
  edit, delete, reset, import or export anything in that world.
  `tokens._may_change` already does this check, and it moves here.
* `view` of what a world is made of stays open to everyone, as the open
  sandbox principle requires.
* Builder and admin tools (`view faults`, `edit memory`, `import commonsense`)
  keep their current `perm(Builder) or perm(Admin)` locks.
* Anyone may `enter` Limbo, and `enter` a world they created. Entering someone
  else's world waits for shared worlds.

### 4.4 `enter`: worlds, and the way back

Once a player enters a world today, there is no way back to Limbo. Evennia's
`home` command is builder-only (`perm(home) or perm(Builder)`), and `worlds`
only knows about worlds. `enter` fixes both.

* **`enter world [n|title]`** does what `worlds <n>` does now: it takes you to
  where you last were in that world (`world_last_locations`), or to the world's
  first room.
* **`enter limbo`** takes you to `settings.START_LOCATION`. The subject is
  called **the start room**. It answers to `start` and to the start room's own
  name, read from the room itself, so it is `limbo` today. When a starting hub
  is built later, it replaces the room behind `START_LOCATION`, and `enter hub`
  works with no change to the command. Only the server's admin controls that
  room's name, never a world, so the subject rule still cannot change meaning
  as a world plays.
* **`enter` alone** opens a menu. The start room comes first when you are in a
  world, and is left out when you are already there. Your worlds follow, in the
  usual order. The world you are standing in is listed, but choosing it says
  "you are already here", as `worlds <n>` does today.
* **Leaving a world in `always` mode.** Leaving does not change the mode, and
  the world keeps spending money. So when you leave a world you created that
  is running `always`, you are told, and shown how to turn it back to
  `normal`. Nothing is switched for you.

**People who follow you do not cross between worlds.** `following.move_followers`
has no idea where worlds begin and end, so today `worlds 3` pulls an NPC who
is following you out of its own world, into another world or into Limbo. That
NPC is then stranded: its world's sponsor, rules and memory bank no longer
apply to where it is standing, and `delete world` will not find it. The fix
goes in `move_followers`: an NPC stops following when the person it follows
moves to a room with a different `world_root`, and is told why. Other players
still follow you, because a player belongs to no world. The fix lives in
`move_followers`, not in `enter`, so it also covers `delete world` and
`reset world`, which move characters out of a world, and any teleport a rule
makes later.

---

## 5. Settings

### 5.1 The registry

This goes in `world/preferences.py`. It is deliberately not called
`settings.py`: this codebase imports `from django.conf import settings` in
many places, and a second module named `settings` would cause confusion.

A setting is a `Field` (§3.2) with some extra information:

* `scope`: `account` (you, everywhere), `character_in_world` (you, in this
  world) or `world` (this world, for everyone in it).
* `group`: see the next table.
* `storage`: which attribute it lives in. It points at the attributes the game
  already writes, so **nothing is migrated**.
* `secret`: masked when shown, never sent to a model, never suggestible, and
  never written to a log.

| group | scope | settings | stored in (existing) |
|---|---|---|---|
| General | account | `busy` interval, `menus.show_command`, `menus.view_menus` | `busy_interval`, new |
| Confirmations | account | one per action in §8 | new: `confirmations` dict |
| API | account | `apikey` (secret), `apiurl` | `openrouter_api_key`, `api_base_url` |
| Models | account | model and settings per job | `ai_models`, `ai_params` |
| You in this world | character in world | name, looks, pronouns | `world_names`, `world_descs` (through `set_world_name`/`set_world_desc`), pronoun store |
| This world | world | `mode` | `world_mode` on the world root |

The last group is also where the per-world switches in `future-plans.md` will
go: what models may generate, and how independent NPCs are. Those are world
settings, and giving them a home now means they are just new rows when they
come.

**The API URL is an account setting, not a world setting.** A key only works
with the provider that issued it. If the URL could be set on a world, the world
would send its creator's key to a different provider, and every call would
fail. So the URL lives next to the key. `sponsor.base_url` already reads
`account.db.api_base_url` and falls back to OpenRouter, but nothing sets it
today, so `apiurl` is the first thing that does. A world reaches a provider
only through whoever is paying for it, and that is the account.

Changing `apiurl` also clears `openrouter_models_cache`, because the list of
models belongs to the old provider. Models already chosen under `settings
models` are kept, but any id the new provider's list does not have is marked
there, the same way the models menu already marks settings a model does not
list. When `apiurl` is changed and `apikey` is not, you are told the key
probably belongs to the old provider. The change is not refused, because some
providers accept OpenRouter-style keys.

### 5.2 The command

`settings` is the one bare word, and it is short for `edit settings`.
`view settings` gives the same list without the menu.

* `settings`: every setting you can see here, by group, with its current value
  and default, as `future-plans.md` asks. Then the menu.
* `settings busy`: that one setting, with its help.
* `settings busy 20`, `settings busy default`, `settings apikey sk-...`
* `settings models`: the models menu, now one group of this form. The
  `refresh` option moves inside it.

The settings command lives on the account cmdset, so it works both in and out
of character. The "You in this world" and "This world" groups only appear
inside a world. "This world" only appears to the world's creator.

`name` and `pronouns` stay as commands in addition to being settings. Changing
your name is announced to the room (`CmdName._announce`). That makes it an
in-character act, not only a preference, so the word stays. Both commands
read and write through the registry, so there is a single place the value is
stored.

### 5.3 Evennia's `option` command

`option` holds client settings: screen reader, screen width and encoding. It
stores them per session in `protocol_flags`, with `option/save`. For this
player, that is the most important preference there is. A read-only
"Connection" group that shows those flags in `settings` is worth adding. Being
able to change them from `settings` is not part of this plan, because it
depends on per-session storage that belongs to Evennia.

### 5.4 Settings and `~`

Only a few settings are suggestible, such as the "You in this world" looks.
Asking a model to pick your API key, your busy interval, or which world to
delete makes no sense, and the last is dangerous. That is why `suggestible`
defaults to off, and why `choice` fields that pick a target can never turn it
on.

---

## 6. Help (`?`)

Help comes from what already exists, not from new text:

1. The field's own `help`: a lore facet's `hint`, a model parameter's `note`,
   or a setting's text.
2. A help topic, looked up by name through the topic lookup `CmdAIHelp`
   already has. That lookup is split out as
   `help_cmds.topic_text(caller, key)`, so `?` and `help` cannot give
   different answers. This covers command docstrings, file help entries, the
   world's own vocabulary (`help bottle`) and effects.
3. For a subject, the docstring of the command it replaced, moved to the
   subject.

It also works the other way. Each setting becomes a help topic generated from
the registry (`help busy`), in the same way `CmdEffects.get_help` builds its
list from `effects.VOCABULARY`. That means adding a setting also documents it.

An option with no help is left out of the `?` submenu, not shown with
"no help available".

---

## 7. Every command, before and after

### 7.1 Management commands: move to verbs

| today | becomes | notes |
|---|---|---|
| `worldgen [desc]` | `create world [desc]` | the wizard becomes a draft form |
| `worldedit [n]` | `edit world [n]` | the same form, filled in; the world you are in comes first |
| `worldremove [n] [confirm]` | `delete world [n]` | yes/no; the world you are in is listed but cannot be chosen |
| `worldreset [n] [confirm]` | `reset world [n]` | yes/no; the world you are in comes first |
| `worlds` | `view worlds` | |
| `worlds <n>` | `enter world [n]` | §4.4 |
| (nothing) | `enter limbo` | new: the way back out of a world (§4.4) |
| `worldmode [mode]` | `edit world` → mode, or `settings mode` | new yes/no before `always` |
| `worldopen` | action in `edit world` | "open a way on" |
| `zones` | `view zones` | |
| `worldcheck [n]` | `view faults [world]` | builder lock kept |
| `rules [verb]` | `view rules [verb]` | |
| `rules suggest` | `view suggestions` | |
| `rules accept/reject <id>` | `edit suggestions [id]` | a choice, then accept/reject |
| `rules judge` | action in `edit suggestions` | yes/no: costs a call |
| `rules suspend/restore <id>` | `edit rules [id]` | |
| `rules suspend dead` | action in `edit rules` | yes/no: suspends many rules at once |
| `rules redeclare <verb>` | `reset verb <verb>` | yes/no |
| `effects [verb]` | `view effects [verb]` | `get_help` moves with it |
| `npcgen` | `create npc` | |
| `tokens [list]`, `tokens try` | `view tokens [list]`; "try some text" inside | |
| `tokens add ...` | `create tokens [...]` | the one-line form still works |
| `tokens remove <list>` | `delete tokens [list]` | yes/no |
| `pronouns new` | `create pronouns` | the wizard becomes a draft form |
| `commonsense` | `view commonsense` | |
| `commonsense fetch` | `import commonsense` | yes/no: large download |
| `memcheck` | `view memory` | builder lock kept |
| `memcheck sleep/sweep/distil/all` | `edit memory` | yes/no before sweep, which deletes |
| `models [refresh]` | `settings models` | |
| `apikey [set/delete]` | `settings apikey` | secret; yes/no before clearing |
| (nothing) | `settings apiurl` | new: the provider, stored next to the key (§5.1) |
| `busy [n]` | `settings busy` | |
| `rounds [job]`, `rounds world <n>` | `view rounds [job] [world]` | |
| `rounds clear` | `reset rounds` | yes/no |

`export` has no subjects yet, and `import` has only `commonsense`. The verbs
exist now so the parser rule and the permissions cover them before world
import and export arrive.

### 7.2 In-character commands: keep the verb, add a menu when it is bare

| command | bare, today | bare, after |
|---|---|---|
| `goal` | clear the goal | menu: give it up, show the next step, set a new one |
| `quests` | list | the list, then hint/accept/decline/abandon (whichever apply), as a view menu |
| `score` | every trait | every trait, then its choices, as a view menu that closes itself (§3.9) |
| `remember` | usage | menu: ask something (text field) |
| `name`, `pronouns` | show | the "You in this world" settings group |

`look`, `get`, `drop`, `give`, `wear`, `remove`, `cover`, `uncover` and
`follow` are **not** part of this plan. Their menus are lists of things in
reach, and a list like that has to answer the questions the attempt pipeline
already answers: can you reach it, can you see it, and is the action allowed at
all. That is the disambiguation item in `future-plans.md`, built on this same
engine through `choosing.ask`.

`follow` is the one command of this game's own on that list. Everything else
in §7 chooses from something the player owns or a world keeps (a world, a
rule, a setting, a quest already offered), and none of it involves reach.
`follow` chooses a person in the room. Until the disambiguation work, a bare
`follow` keeps doing what it does now and stops you following.

---

## 8. Confirmations

Each one is a yes/no menu with **No** first, and a setting under
`confirm.<key>`, on by default. On the command line, a trailing `yes` answers
it: `delete world 2 yes`. `confirm` is accepted too, since that is the word
people type today. When the setting is off, the action happens without asking.

| key | action | why it asks |
|---|---|---|
| `delete_world` | `delete world` | cannot be undone (asks today) |
| `reset_world` | `reset world` | destroys every room (asks today) |
| `world_always` | `edit world` mode → always | costs money until someone turns it off |
| `spend` | `rules judge`, and anything else that spends a model call when asked for | costs money |
| `bulk_rules` | `rules suspend dead` | changes many rules at once |
| `reset_verb` | `reset verb` | changes what a verb is taken to mean |
| `delete_tokens` | `delete tokens` | removes a list other things may use |
| `sweep_memory` | `edit memory` → sweep | deletes memory banks |
| `download` | `import commonsense` | large download |
| `clear_apikey` | `settings apikey` → clear | turns every generator off |
| `reset_rounds` | `reset rounds` | discards what was measured |
| `abandon_quest` | `quests abandon` | the quest giver is told |
| `discard` | quitting a draft form with changes | work lost |
| `suggestion` | accepting what `~` wrote | see §9 |

Only the first two ask today. The rest are new, and all of them stay. **Every
confirmation is on by default and every one can be turned off**, including
`delete_world`. It is the player's server. The menu shows the confirmations as
one group, with an "all on" and "all off" option. Turning a confirmation off
never skips the lock check: `delete world` on a world you did not make is
refused either way.

---

## 9. Filling in with a model (`~`)

* **Job.** A new job, `menus` ("Filling in a menu field for you"), added to
  `model_menu.FUNCTIONS`. That means it can be given its own model in
  `settings models` and gets its own line in `view rounds`, with no extra
  work.
* **Who pays.** The form's `sponsor`: `sponsor.of_account` outside a world or
  when making one, and `sponsor.of` inside a world. If there is no sponsor or
  no key, `~` explains why and nothing is called.
* **Tools, as every job has.** `llm.converse` with a finish tool whose
  parameter schema comes from the field. A `choice` field uses
  `toolbox.choice` (an enum, with a lookup tool when there are more than
  `ENUM_MOST` options). A number has minimum and maximum. Text has a maximum
  length. The handler runs the field's own `parse`, so a complaint goes back
  to the model to fix, the same way every generator works since the tool-loop
  work. Nothing about the rule "tools are required" changes.
* **What the model sees:** the form's title and intro; every field's label,
  help and current value, with secret fields left out entirely, names
  included; the field to fill; the command that reaches it (§3.5); and the
  form's own `context`, such as the world description while writing room
  guidance.
* **"All empty fields".** This is an option in the `~` submenu. It fills every
  empty suggestible field in one conversation, with one finish tool per field.
  This is what makes `create world` with only a description useful.
* **The result is a proposal.** It is shown with "Use this?": No, Yes, Try
  again. It never overwrites a field on its own. That yes/no is the
  `suggestion` confirmation. With it switched off, the proposal is used
  straight away.
* **Waiting.** A busy notice runs while the model works. The menu stays open
  and usable. If the answer arrives after the menu has closed, the player is
  told it was discarded. If the player is on another node, the proposal is
  offered once they come back to the field.
* **Cost.** One conversation for each `~` typed. Nothing is ever called unless
  asked, which keeps rule 1 of the tool-loop plan: the steady state costs
  nothing.

---

## 10. Phases

Each phase ends with the free test suite passing and the docs updated for
whatever was built.

**Phase 1: the engine.** `world/menus.py`: `GameMenu`, `Form`, the field
kinds, the key grammar, filtering and paging (moved out of
`node_select_model`), yes/no, the presenter hooks, the screen-reader
formatters, "every menu is a command line", and view menus that close
themselves, with all three `menus.view_menus` modes. A test harness drives a menu
by feeding it lines of input. Port `pronouns new` onto it as the first real
form, because it is small and has a draft. `?` works from each field's own
help text.
*Done when:* the pronouns wizard behaves as before with the new keys, each
reserved key and hook has a test, and a view menu hands `north`, `say` and
`look` to the game while keeping `quit` from disconnecting anyone.

*Built.* Tests are in `tests/test_menus.py`, including two that go through a
real session and an account. Where it differs from the plan:

* `pronouns new` still asks the six questions in order, and then shows the
  whole set with "Keep this set". Previously the set was kept the moment the
  last question was answered, and a typo could not be fixed.
* Quitting partway through asks "Throw away this pronoun set?" first. That is
  the `discard` confirmation from §8, and it can be turned off.
* `~` is a key in every menu, but until phase 5 it says nothing can be filled
  in yet.
* The engine has its own filtering and paging. The models menu still uses the
  old code until it is ported in phase 2.
* Menu preferences are read straight from the account attributes
  `menu_view_mode`, `menu_show_command` and `confirmations`. The phase 2
  registry points at the same attributes.

**Phase 2: settings.** `world/preferences.py`, the `settings` command,
`busy` and `apikey` as settings, the confirmations group, and help topics
generated from the registry. Port the models menu to a settings group (the
existing `test_model_menu` tests move with it). Delete `busy`, `apikey` and
`models`, and add the retired-name table.
*Done when:* every stored preference is readable and settable through
`settings`, and nothing is migrated.

*Built.* `world/preferences.py`, `commands/settings_cmds.py`, and tests in
`tests/test_settings.py`. Where it differs from the plan:

* **`settings list`** prints every setting with its value and the name to
  type. A bare `settings` opens a menu of groups, and each group lists its
  settings with their values. Listing all of them first, as §5.2 said, came
  to more than thirty lines before any menu.
* **`settings <name>` opens that setting in the menu**, so the rule "no value
  given, show a menu" holds. With nobody connected it prints the setting and
  its help instead.
* **Settings are found by their own name** (`settings busy`) or through their
  group (`settings general busy`). A job's model settings are only reached
  through their group: `settings models dialogue temperature 0.9`.
* **"You in this world" and "This world" are in already**: name, looks,
  pronouns and world mode. The `name`, `pronouns` and `worldmode` commands
  still exist. `name` and the name setting share one check and one
  announcement. `worldmode` goes in phase 4.
* **The engine gained** choice fields that can be cleared, submenus that
  fetch something before opening (the model list), submenus with a draft of
  their own (adding a pronoun set from settings), confirmations that depend
  on the value chosen (`always`, clearing the key), and a page size per form.
  The confirmations and models groups show twenty entries before paging, not
  ten.
* **The retired-name table** answers `apikey`, `busy` and `models` anywhere a
  character types them: "That is `settings busy` now."

**Phase 3: verbs, subjects, the parser rule.** `commands/verbs.py`,
`commands/subjects.py`, the subject rule in `cmdparser.py`, the permission
rule, and the shared world-choice field. The `world` subject gets
create/edit/delete/reset/view and the worldgen wizard becomes a draft form.
`verbs.engine_verbs` reads a flag instead of the help category. `enter`,
with the world and start room subjects; NPC followers stop at a world's edge.
*Done when:* `reset the trap` inside a world reaches the world, `reset world`
does not, `delete world` for a world you did not make is neither offered nor
allowed, `enter limbo` gets a player out of any world, and an NPC following
you stays in its own world when you leave it.

*Built.* `commands/verbs.py`, `commands/subjects.py`,
`commands/world_subject.py`, and tests in `tests/test_verbs.py`. `worldgen`,
`worldedit`, `worldremove`, `worldreset` and `worlds` are gone, and typing one
says what replaced it. Where it differs from the plan:

* **Worlds keep their numbers.** §4.2 said the world you are standing in comes
  first. It is marked "(you are here)" instead, and the list stays in the order
  the worlds were made. Otherwise `delete world 2` would mean a different world
  depending on where it was typed.
* **Deleting the world you are standing in is refused before anything is
  asked.** It is still listed, so the numbers hold, but it never gets as far
  as a yes/no.
* **`enter` alone lists the start room first, then your worlds, all in one
  list.** `enter world` alone lists only the worlds.
* **The start room's subject word is `start`, and also the room's own name**
  (`limbo`), read from whatever room `START_LOCATION` points at.
* **NPC followers are told they cannot follow and stay where they are.** A
  player character still follows anywhere.
* **A typo check was saying "Did you mean reset?" to `reset the trap`.** The
  near-miss check in `unknown_cmd.py` treated a command matching the word
  exactly as a typo. It now skips an exact match, because the parser set that
  command aside on purpose. The same fault already affected `force the lock`.
* **`verbs.reserves_word`** is the flag. A command without one falls back to
  "General" help category, as before, and the verb commands set it to False.

**Phase 4: every other subject.** Rules, suggestions, effects, zones, faults,
tokens, npc, pronouns, commonsense, memory and rounds, each with its
confirmations. Delete the old commands. `test_rules_command` and
`test_paying_commands` move to the new spellings.
*Done when:* nothing listed in the "today" column of §7.1 still exists.

*Built.* `commands/rules_subject.py` (rules, suggestions, effects, faults,
verb), `commands/contents_subject.py` (zones, npc, tokens, pronouns) and
`commands/upkeep_subject.py` (commonsense, memory, rounds), with tests in
`tests/test_subjects.py`. `world_cmds.py`, `token_cmds.py` and
`account_cmds.py` are gone, and so is `memcheck` from `memory_cmds.py`. Every
retired name says what replaced it. Where it differs from the plan:

* **`worldmode` is only `settings mode`.** The world wizard does not have a
  mode field as well, because a second place to set it would be a second
  place to look.
* **`edit rules <id>`** opens that rule's own menu, with suspend or restore.
  The one-line forms are `edit rules <id> suspend` and `edit rules <id>
  restore`. Suspending every dead rule is `edit rules dead`.
* **`create npc` is now for whoever made the world.** `npcgen` let anybody do
  it, although the world pays for its people. `create pronouns` stays open to
  anybody standing in a world, as `pronouns new` was.
* **`pronouns new` says "That is `create pronouns` now."** `pronouns` and
  `pronouns <set>` are unchanged.
* **`quests abandon` asks first**, as §8 planned. It was listed there and fell
  into this phase because every other confirmation did.
* **`help effects` is a list of topics now.** With no command called
  `effects`, it lists every effect filed in that category, as `help kinds`
  does.
* **The verb commands are only available to a character, not out of
  character.** `rounds` used to work out of character, and `view rounds` does
  not. `settings` still works both ways.

**Phase 5: help and `~`.** `help_cmds.topic_text`, `?` falling back to help
topics, the `menus` job, the `~` tool loop, "all empty fields", and the
proposal node. The live `llm`-tagged tests cover one field of each kind.
*Done when:* `create world` with only a description can fill in its title and
guidance through `~`.

**Phase 6: in-character commands, and tidying up.** The bare forms in §7.2,
`choosing.ask` running on the engine, the retired-name table checked,
`README.md` and the commands section of `aimud/CLAUDE.md` rewritten, and the
first two items removed from `future-plans.md`, together with its stale
"show when busy" item, which was built in `generator-tool-loops.md`.

---

## 11. Decisions

Settled on 2026-09-16.

1. **The subject rule (§2) stands.** No `@`, and the verbs are not reserved. A
   verb command only takes input when it is typed alone or followed by one of
   its subject words.
2. **Entering a world is `enter world`**, and `enter` also leads back to Limbo
   through a start room subject named from the room, so a starting hub can
   take its place later (§4.4).
3. **Commands involving reach wait for disambiguation.** `look`, `get`, `drop`,
   `give`, `wear`, `remove`, `cover`, `uncover` and `follow` get their bare
   menus there, on this engine (§7.2).
4. **All fourteen confirmations are kept** (§8).
5. **Every confirmation is on by default and can be turned off**, including
   deleting a world (§8).
