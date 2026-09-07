"""
Where a thing is, relative to another thing.

A world made only of rooms and inventories has nowhere to put anything down.
The parser has always understood "in" and "on" -- it turns them into roles --
but nothing underneath could represent either, so a rule that wanted to put
the key in the box had no legal way to say it. Given only "move it to the
room" or "move it to the actor", a model asked to define `put` would invent a
state called "in_box", or quietly drop the key on the floor. The words were
there; the meaning had nowhere to live.

This is that meaning. A thing may be **in** a container, **on** a surface,
**under** something or **behind** it, and every part of the game can now say
so, test it, and change it.

Two decisions carry the design:

* **Evennia's own containment does the work.** A mug on a table really is
  inside the table as far as the database is concerned, and the preposition is
  a note on the mug saying how. That means moving, deleting, searching and
  every hook already works, and there is no second notion of location to keep
  in step with the first.

* **Reach follows from it.** You can take hold of what is in the room, of what
  is on or under anything you can reach, and of what is inside anything you
  can reach that is not shut. That last clause is what makes closing a box
  mean something, and it is the whole reason a lid is worth having.
"""

from evennia.utils import iter_to_str

#: The ways one thing can be at another. Deliberately few: each has to be
#: worth distinguishing to a player, and every one of them is a word a rule
#: may have to choose between correctly.
PREPOSITIONS = ("in", "on", "under", "behind")

#: What a thing must be for something to go there. "under" and "behind" ask
#: nothing -- everything has an underneath -- but you cannot put a book inside
#: something that is not hollow, or on something with no top.
REQUIRED_AFFORDANCE = {"in": "container", "on": "surface"}

#: The affordance that makes something a place to put things on. Offered by
#: every generator alongside "container", so tables, shelves, counters and
#: desks are surfaces from the moment they are made.
SURFACE = "surface"

#: What an unmarked thing inside another is taken to be. Everything that
#: existed before placement did reads as "in", which is what it always meant.
DEFAULT = "in"

#: How deep reach goes. A box on a table in the room is two steps; past about
#: here a player has lost track of where anything is anyway.
MAX_DEPTH = 3

#: States that shut a container. A closed box keeps its contents to itself.
SHUT = frozenset(["closed", "shut", "locked", "sealed", "fastened"])


def _is_thing(obj):
    """True for an ordinary object -- not an exit, not a person."""
    from evennia.objects.objects import DefaultCharacter

    if obj is None:
        return False
    if getattr(obj, "destination", None) is not None:
        return False
    if isinstance(obj, DefaultCharacter) or obj.db.is_npc:
        return False
    return True


def preposition_of(obj):
    """How this thing sits at whatever holds it: "in", "on", and so on."""
    stored = str(obj.db.relation or "").lower().strip()
    return stored if stored in PREPOSITIONS else DEFAULT


def host_of(obj):
    """
    What this thing is in or on, or None when it is loose in a room.

    A carried object has a person for a location, which is inventory rather
    than placement, so that answers None too.
    """
    where = getattr(obj, "location", None)
    return where if _is_thing(where) else None


def relation_of(obj):
    """(preposition, host), or (None, None) when it is not placed at all."""
    host = host_of(obj)
    return (preposition_of(obj), host) if host is not None else (None, None)


def is_shut(host):
    """True when a container is closed and keeps its contents to itself."""
    from world import verbs

    return bool(SHUT & verbs.states(host))


def accepts(host, preposition):
    """
    (ok, why not) for putting something at `host` this way.

    The affordances are the world's own word for what a thing is, so a table
    the generators called a surface takes things on it and a sealed lump of
    rock does not.
    """
    from world import verbs

    if not _is_thing(host):
        return False, "You cannot put anything there."
    needed = REQUIRED_AFFORDANCE.get(preposition)
    name = host.get_numbered_name(1, None, return_string=True)
    if needed and needed not in verbs.affordances(host):
        if preposition == "in":
            return False, f"{name.capitalize()} does not hold things."
        return False, f"There is no room on {name}."
    if preposition == "in" and is_shut(host):
        return False, f"{name.capitalize()} is closed."
    return True, ""


def contents(host, preposition=None):
    """What is at `host`, optionally only what is there in one particular way."""
    found = []
    for obj in (host.contents if host is not None else []):
        if not _is_thing(obj):
            continue
        if preposition is None or preposition_of(obj) == preposition:
            found.append(obj)
    return found


def place(obj, host, preposition=DEFAULT, quiet=True):
    """
    Put `obj` at `host`. Returns (ok, what to say).

    The single door for placement: everything that moves a thing onto or into
    another thing comes through here, so the checks and the wording are the
    same whether a player typed it, a verb's effect did it, or a character
    decided to tidy up.
    """
    preposition = str(preposition or DEFAULT).lower().strip()
    if preposition not in PREPOSITIONS:
        preposition = DEFAULT
    if obj is None or host is None:
        return False, "There is nothing to do that with."
    if obj is host:
        return False, "That cannot hold itself."
    if _holds(obj, host):
        # Putting the box inside the bag it already contains would take both
        # of them out of the world.
        return False, "That would have to go inside itself."

    ok, why = accepts(host, preposition)
    if not ok:
        return False, why

    if not obj.move_to(host, quiet=quiet, move_type="place"):
        return False, "That will not go there."
    obj.db.relation = preposition
    return True, (f"{obj.get_numbered_name(1, None, return_string=True)} is "
                  f"{preposition} {host.get_numbered_name(1, None, return_string=True)}.")


def _holds(container, obj, depth=0):
    """True when `obj` is somewhere inside `container`, at any depth."""
    if depth > MAX_DEPTH or obj is None:
        return False
    where = getattr(obj, "location", None)
    if where is None:
        return False
    if where is container:
        return True
    return _holds(container, where, depth + 1)


def displace(obj):
    """
    Forget how something was placed, because it is no longer anywhere.

    Called when a thing is picked up or dropped: a mug that was on the table
    and is now in somebody's hand is not on anything, and leaving the note
    behind would have it read as "on" the next person who took it.
    """
    if obj is not None and obj.db.relation:
        obj.db.relation = None


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------

def reachable(caller, include_self=False):
    """
    Everything the caller could take hold of or refer to, nearest first.

    Their own inventory, then the room, then outward through whatever is on,
    under or behind those, and into whatever is open. A closed box stops the
    search, which is what closing it is for.
    """
    found, seen = [], set()

    def walk(host, depth):
        if depth > MAX_DEPTH:
            return
        for obj in (host.contents if host is not None else []):
            if obj is caller or obj.id in seen or not _is_thing(obj):
                continue
            seen.add(obj.id)
            found.append(obj)
            if preposition_of(obj) == DEFAULT and is_shut(obj):
                continue      # sealed: whatever is inside is out of reach
            walk(obj, depth + 1)

    walk(caller, 0)
    walk(getattr(caller, "location", None), 0)
    if include_self and caller is not None:
        found.append(caller)
    return found


def find(caller, phrase):
    """
    The thing in reach that `phrase` names, or None.

    Wider than searching the room: a key in an open drawer is a key you can
    read, take and be asked to fetch, and having to open and empty a drawer
    onto the floor before its contents can be named would be nobody's idea of
    a game.
    """
    if not phrase or caller is None:
        return None
    candidates = reachable(caller)
    if not candidates:
        return None
    result = caller.search(phrase, candidates=candidates, quiet=True)
    if hasattr(result, "return_appearance"):
        return result
    try:
        items = [obj for obj in (result or []) if obj is not None]
    except TypeError:
        return result
    return min(items, key=lambda o: o.id) if items else None


# ---------------------------------------------------------------------------
# Saying where things are
# ---------------------------------------------------------------------------

def _names(objects, looker):
    return iter_to_str([obj.get_numbered_name(1, looker, return_string=True)
                        for obj in objects])


def summary(host, looker=None):
    """
    "(a mug and a candle on it)" -- what a room should say about a table.

    Short, because it appears beside the thing in a list. Anything inside a
    closed container is left out: that is what closed means.
    """
    parts = []
    for preposition in PREPOSITIONS:
        here = contents(host, preposition)
        if not here:
            continue
        if preposition == DEFAULT and is_shut(host):
            continue
        parts.append(f"{_names(here, looker)} {preposition} it")
    return f"({'; '.join(parts)})" if parts else ""


def describe(host, looker=None):
    """
    The lines a look at `host` should add: what is on it, in it, under it.

    Fuller than `summary`, and the reason a container is worth opening.
    """
    lines = []
    for preposition in PREPOSITIONS:
        here = contents(host, preposition)
        if not here:
            continue
        if preposition == DEFAULT and is_shut(host):
            lines.append(f"It is closed.")
            continue
        head = {"in": "Inside", "on": "On it", "under": "Under it",
                "behind": "Behind it"}[preposition]
        lines.append(f"{head}: {_names(here, looker)}.")
    if not lines and is_shut(host):
        return "It is closed."
    return "\n".join(lines)


def context_line(obj, looker=None):
    """
    "on the oak table" -- where something is, for a prompt or a message.

    Empty when it is simply lying in the room, which needs no saying.
    """
    preposition, host = relation_of(obj)
    if host is None:
        return ""
    return f"{preposition} {host.get_numbered_name(1, looker, return_string=True)}"


# ---------------------------------------------------------------------------
# The verbs this owns
# ---------------------------------------------------------------------------

#: Ways of saying "put this there". Like wearing, this is a mechanic and not
#: something a world should be asked to invent: every one of these means
#: exactly one thing, and the game already knows what.
VERBS = ("put", "place", "insert", "drop")

#: The roles a preposition can land in, and what it meant. The parser files
#: "in the box" under `container` and "on the table" under `target`, so the
#: preposition itself has to be read back off the parse to tell them apart.
_ROLE_PREPOSITIONS = {"container": "in", "target": "on", "source": "in"}


def handle(caller, verb, parsed, bound, on_message):
    """
    Deal with putting something somewhere, or decline. True when handled.

    Declines anything that is not really a placement -- `put out the fire`,
    `drop the subject` -- so the world is still free to work out what those
    mean. What it takes over is the plain case, which is most of them, and
    which used to cost a rule call and a narration to arrive at a wrong
    answer.
    """
    if verb not in VERBS:
        return False

    obj = bound.get("direct")
    if obj is None or not _is_thing(obj):
        return False

    preposition, host = _destination(parsed, bound)
    if host is None:
        return False        # no "in"/"on" phrase: an ordinary drop, not this
    if not _is_thing(host):
        return False

    ok, message = place(obj, host, preposition, quiet=True)
    if not ok:
        on_message(message, "")
        return True

    name = caller.get_display_name(caller)
    label = obj.get_numbered_name(1, caller, return_string=True)
    where = host.get_numbered_name(1, caller, return_string=True)
    on_message(f"You put {label} {preposition} {where}.",
               f"{name} puts {label} {preposition} {where}.")
    return True


def _destination(parsed, bound):
    """(preposition, host) from a parse, or (None, None) if it names none."""
    prepositions = (parsed or {}).get("prepositions") or {}
    for role in ("container", "target", "source"):
        host = bound.get(role)
        if host is None:
            continue
        word = str(prepositions.get(role, "")).lower()
        if word not in PREPOSITIONS:
            word = _ROLE_PREPOSITIONS.get(role, DEFAULT)
        return word, host
    return None, None


# ---------------------------------------------------------------------------
# Testing a placement
# ---------------------------------------------------------------------------

def test(obj, preposition, host):
    """True when `obj` really is at `host` in that way."""
    if obj is None or host is None:
        return False
    if host_of(obj) is not host:
        return False
    if not preposition:
        return True
    return preposition_of(obj) == str(preposition).lower().strip()
