"""
The verbs the game answers for itself, and which of them a world uses.

Four modules take verbs before any rule is consulted. Each is a mechanic
rather than something a world has to work out: every one of those words means
exactly one thing and the game already knows what, so a player's `wear` and an
NPC deciding to put its coat on reach the same code and the same limits, and
no world ever invents a private meaning for any of them.

Two of the four are true of every world there could be. Where a thing is and
whose it is are not a genre: `world.relations` and `world.ownership` answer
questions that exist wherever objects and people do, and they stay switched on
for everybody.

The other two are decisions. `world.clothing` takes `wear`, `remove`, `cover`
and `uncover` in a world with no clothes in it; `world.gear` takes `wield` and
`hold` in one with nothing to hold. A world about disembodied spirits should
be able to say so and have `wear` mean whatever it invents, and until there
was a ruleset to say it in, there was nowhere for that decision to live.

**A ruleset names a mechanic; it never supplies one.** `TABLE` below is a
fixed map from a name to code that ships with the game, and a ruleset's
`mechanics` section may name only what is in it -- refused at load otherwise.
That is the seam between a ruleset, which is data, and a plugin, which is
code, and it is worth being strict about now rather than when the plugin work
in `docs/future-plans.md` arrives: plugins will register into this same table,
and a ruleset naming a mechanic a server has not installed then fails at load,
in the log, which is the right place to find out.
"""

#: The mechanics a world may switch off, and what each answers.
#:
#: Values are (module name, whether it is handed the parse). The two shapes
#: are historical rather than meaningful -- placement and giving read a
#: preposition back off the sentence, and wearing does not.
SWITCHABLE = {
    "clothing": ("world.clothing", False),
    "wielding": ("world.gear", False),
}

#: The mechanics no world may switch off, in the order they are asked.
#:
#: Kept in a table beside the others rather than written into `attempt`, so
#: that the whole of what takes a verb before a rule does is readable in one
#: place. Ordering: the switchable ones are asked first, because each declines
#: anything that is not its business, and a garment named in `put the coat on`
#: should be worn rather than placed.
ALWAYS = (
    ("ownership", "world.ownership", True),
    ("placement", "world.relations", True),
)


def _module(path):
    from importlib import import_module

    return import_module(path)


def enabled(world_root):
    """
    The mechanics this world uses, in the order to ask them.

    Every switchable one a ruleset named, then the two nobody may switch off.
    A world with no rulesets recorded -- one made before they existed, or one
    being built -- gets all of them, which is what it had.
    """
    from world import rulesets

    wanted = []
    held = rulesets.chosen(world_root)
    if not held:
        wanted = list(SWITCHABLE)
    else:
        named = set()
        for name in held:
            doc = rulesets.get(name) or {}
            named.update(str(m) for m in doc.get("mechanics") or [])
        wanted = [name for name in SWITCHABLE if name in named]
    found = [(name, SWITCHABLE[name][0], SWITCHABLE[name][1])
             for name in wanted]
    return found + list(ALWAYS)


def handle(world_root, caller, verb, parsed, bound, on_message):
    """
    Let whichever mechanic owns this verb take it. True when one did.

    Each declines anything that is not really its business -- "draw the
    curtain", "put out the fire", "give up" -- and those go on through the
    ordinary pipeline.
    """
    for _name, path, wants_parse in enabled(world_root):
        module = _module(path)
        if wants_parse:
            took = module.handle(caller, verb, parsed, bound, on_message)
        else:
            took = module.handle(caller, verb, bound, on_message)
        if took:
            return True
    return False


def known(name):
    """Whether a ruleset may name this mechanic."""
    return str(name) in SWITCHABLE
