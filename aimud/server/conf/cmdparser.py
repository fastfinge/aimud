"""
The command parser: Evennia's own, with one rule for generated worlds.

**Inside a generated world, a building, admin or system command has to be
typed with its prefix.** `@open`, `@examine`, `@create`, `@force`. Typed bare,
the word is left for the world, where it is something a character does.

The collision this settles is between Evennia's staff commands and the verbs a
world is made of. On a self-hosted server the player is usually the superuser,
so every staff command is always in reach: `open door` made an exit called
"door", `examine lantern` dumped the lantern's attributes, and `force the lock`
tried to make somebody run a command. Evennia already spells most of them with
an "@" -- the key is `@open` -- and a bare `open` reached it only because the
parser strips `CMD_IGNORE_PREFIXES` and tries again when nothing matched.

**Why a rule about where you are and not a rename.** Renaming or overwriting
Evennia's commands would break its documentation, its builders' habits and
any plugin that adds to them, and outside a world -- Limbo, anything built by
hand -- there is no verb to collide with. `quell` does work, the superuser
included, but it switches building off everywhere until somebody remembers to
unquell, and forgetting it is exactly how an exit called "door" gets made. And
deciding per word, by whether this world has a rule for `open`, would make a
command change meaning as a world learns.

**The verb commands follow a rule of their own.** `create`, `reset`, `view`
and the rest take input in a world only when it names one of their subjects,
or nothing: `reset world` is the command and `reset the trap` is the world's.
See `claims`.

**Which commands.** Those defined in Evennia's building, admin and system
modules, whatever their key is spelled with: `force`, `emit` and `wall` have
no "@", and typing `@force` reaches them all the same, because the prefix is
stripped in matching. The game's own commands -- `look`, `settings`,
`tokens` -- and Evennia's general, account and communication commands are not
staff tools and never need a prefix. The batch processor's interactive
commands are left alone too: they exist only while a batch is running.
"""

from django.conf import settings
from evennia.commands.cmdparser import cmdparser as evennia_cmdparser

#: Where Evennia keeps the commands that are for building and running a
#: server rather than playing on one.
STAFF_MODULES = frozenset((
    "evennia.commands.default.building",
    "evennia.commands.default.admin",
    "evennia.commands.default.system",
))

#: What counts as having typed a prefix. Evennia's own list.
PREFIXES = settings.CMD_IGNORE_PREFIXES


def cmdparser(raw_string, cmdset, caller, match_index=None, session=None,
              **kwargs):
    """
    Evennia's matches, less any staff command typed bare inside a world.

    Removing a match rather than choosing another is what hands the input on:
    with nothing left, the command handler runs the no-match command, which in
    a generated world is `CmdAIUnknown`, which sends it to the world.
    """
    matches = evennia_cmdparser(raw_string, cmdset, caller,
                                match_index=match_index, session=session,
                                **kwargs)
    if not matches or not in_generated_world(caller):
        return matches
    matches = [match for match in matches if claims(match)]
    if _prefixed(raw_string):
        return matches
    return [match for match in matches if not is_staff(match[2])]


def claims(match):
    """
    Whether a verb command takes this input, inside a world.

    `create`, `reset`, `view` and the rest are commands only when they are
    typed alone or followed by one of their subjects -- `reset world` -- and
    anything else is left for the world: `reset the trap`, `view the mural`.
    The subjects come from `commands.subjects`, which a world cannot add to,
    so what a command claims never changes as a world learns. Every other
    command claims whatever it matched. docs/commands-and-settings.md §2.
    """
    verb = getattr(match[2], "verb", "")
    if not verb:
        return True
    from commands import subjects

    return subjects.claims(verb, match[1])


def is_staff(command):
    """Whether a command is one of Evennia's building, admin or system tools."""
    return type(command).__module__ in STAFF_MODULES


def _prefixed(raw_string):
    text = str(raw_string or "").lstrip()
    return bool(text) and text[0] in PREFIXES


def in_generated_world(caller):
    """
    Whether whoever typed this is standing in a generated world.

    The same test the no-match command makes, so the two cannot disagree about
    where a world begins: a room with a world description. A session or an
    account is placed by the character it is puppeting.
    """
    body = caller if hasattr(caller, "location") else getattr(caller, "puppet",
                                                              None)
    room = getattr(body, "location", None)
    try:
        return bool(room is not None and room.db.world_description)
    except AttributeError:
        return False


def staff_spelling(cmdset, caller, word):
    """
    How to type the staff command `word` names, if `caller` may use one.

    "@open" for `open`, "@force" for `force`, or "" when no staff command
    answers to the word or the caller may not run it -- so a player who was
    never a builder is never told about building commands.
    """
    word = str(word or "").lower().lstrip(PREFIXES)
    if not word or cmdset is None:
        return ""
    for command in getattr(cmdset, "commands", []) or []:
        if not is_staff(command):
            continue
        for name in [command.key] + list(command.aliases or []):
            name = str(name or "").lower()
            if name.lstrip(PREFIXES) != word:
                continue
            try:
                allowed = command.access(caller, "cmd")
            except Exception:
                allowed = False
            if not allowed:
                return ""
            return name if name[:1] in PREFIXES else f"@{name}"
    return ""
