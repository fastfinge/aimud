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

#: Which of them mean the thing is *inside* the other, and which mean it is
#: merely beside it.
#:
#: This distinction was missing and the module was the poorer for it. Every
#: preposition was stored the same way -- `obj.move_to(host)` -- which is
#: right for two of the four and plainly wrong for the other two. A coin under
#: a rug was kept *inside* the rug, so picking the rug up carried the coin off
#: in your inventory and left the floor with neither. A key behind a painting
#: was inside the painting.
#:
#: Containment earns its keep for `in` and `on`: a thing in a box or on a tray
#: travels with it, is hidden when the box is shut, and needs no bookkeeping
#: because Evennia's own containment does all of it. Neither is true of `under`
#: or `behind`, which say where a thing is in a room rather than what is
#: holding it -- so those are a pointer from one thing to another, and both
#: stay exactly where they were.
#:
#: What this buys beyond the coin: **covering is now placement.** "The shirt is
#: under the coat" is the same word, said of two things that share a wearer
#: rather than a floor, and `world.clothing` keeps no relation of its own.
CONTAINED = ("in", "on")
BESIDE = ("under", "behind")

#: Where a pointer relation keeps what it points at.
HOST_ATTR = "relation_to"

#: The other side of each relation, so a thing can say where it stands as well
#: as what is standing at it. Put the table on the rug and the rug is under the
#: table; nothing could say so before, because only the guest carried the word.
INVERSE = {"in": "holding", "on": "under", "under": "over",
           "behind": "in front of"}

#: Where things go is now a fact about a kind rather than an affordance --
#: see `world.kinds.PLACEMENT` and the note in `accepts` below. "under" and
#: "behind" ask nothing of the host: everything has an underneath.

#: What an unmarked thing inside another is taken to be. Everything that
#: existed before placement did reads as "in", which is what it always meant.
DEFAULT = "in"

#: How deep reach goes. A box on a table in the room is two steps; past about
#: here a player has lost track of where anything is anyway.
MAX_DEPTH = 3

#: States that shut a container. A closed box keeps its contents to itself.
SHUT = frozenset(["closed", "shut", "locked", "sealed", "fastened"])


def _world_root(obj):
    """The world an object belongs to, by way of the room it is in."""
    room = getattr(obj, "location", None)
    while room is not None:
        root = getattr(room.db, "world_root", None)
        if root is not None:
            return root
        room = getattr(room, "location", None)
    return None


def _is_thing(obj):
    """
    True for an ordinary object -- not an exit, not a person, not a place.

    Rooms were left in, and that was wrong in a way nothing noticed until
    something could name one: `host_of` promised None for a thing lying loose
    on the floor and answered the room instead, so everything in every room in
    the game read as being *in* something. A rule asking whether the key is in
    the box was one confusion away from being told yes about a key on the
    floor, and `put the lamp in here` would have been refused for the cellar
    not holding things.
    """
    from evennia.objects.objects import DefaultCharacter, DefaultRoom

    if obj is None:
        return False
    if getattr(obj, "destination", None) is not None:
        return False
    if isinstance(obj, (DefaultCharacter, DefaultRoom)) or obj.db.is_npc:
        return False
    return True


def preposition_of(obj):
    """How this thing sits at whatever holds it: "in", "on", and so on."""
    stored = str(obj.db.relation or "").lower().strip()
    return stored if stored in PREPOSITIONS else DEFAULT


def host_of(obj):
    """
    What this thing is in, on, under or behind; None when it is loose.

    A carried object has a person for a location, which is inventory rather
    than placement, so that answers None too.

    A pointer relation **lapses when the two part company**, and that is the
    whole of its cleanup. A coin under a rug is under it because they are in
    the same place; carry the rug off, burn it, or put it in a chest, and the
    coin is simply a coin on the floor again. Answered here rather than
    unpicked by a hook at every door a thing can leave by, because there is no
    door this does not cover -- and nothing is narrated, because what to say
    about a coin coming to light is a rule's business and not a mechanic's.
    """
    pointed = getattr(obj.db, HOST_ATTR, None) if obj is not None else None
    if pointed is not None:
        if (getattr(pointed, "pk", None) is not None
                and pointed.location is obj.location):
            return pointed
        return None
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

    Whether a thing is hollow or has a top is a fact about its kind -- every
    bottle is hollow -- so it is asked of the kind, which settles it once for
    all bottles. It used to be an entry in the affordance list, back when that
    list was the only place to keep a fact about an object, and being there
    made it part of the verb cache key: a table and a shelf would fail to
    share a single learned rule because one of them had been called a surface
    and the other had not.
    """
    from world import kinds

    if not _is_thing(host):
        return False, "You cannot put anything there."
    needed = preposition if preposition in kinds.PLACEMENT else None
    name = host.get_numbered_name(1, None, return_string=True)
    if needed and needed not in kinds.holds(_world_root(host), host.db.kinds):
        if preposition == "in":
            return False, f"{name.capitalize()} does not hold things."
        return False, f"There is no room on {name}."
    if preposition == "in" and is_shut(host):
        return False, f"{name.capitalize()} is closed."
    return True, ""


def contents(host, preposition=None):
    """
    What is at `host`, optionally only what is there in one particular way.

    Two places to look, because there are two ways to be at something: inside
    it, and beside it pointing at it. The second is bounded by whatever holds
    them both -- a room's floor, or a wearer -- so it is a scan of siblings
    rather than a search.
    """
    if host is None:
        return []
    found = []
    for obj in host.contents:
        if not _is_thing(obj):
            continue
        if getattr(obj.db, HOST_ATTR, None) is not None:
            continue          # inside it by accident of storage, not by placement
        if preposition is None or preposition_of(obj) == preposition:
            found.append(obj)
    for obj in beside(host):
        if preposition is None or preposition_of(obj) == preposition:
            found.append(obj)
    return found


def beside(host):
    """The things in the same place as `host` that point at it."""
    where = getattr(host, "location", None)
    if where is None:
        return []
    return [obj for obj in where.contents
            if obj is not host and _is_thing(obj)
            and getattr(obj.db, HOST_ATTR, None) is host]


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
    circular = _circular(obj, host)
    if circular:
        return False, circular

    ok, why = accepts(host, preposition)
    if not ok:
        return False, why

    said = (f"{obj.get_numbered_name(1, None, return_string=True)} is "
            f"{preposition} "
            f"{host.get_numbered_name(1, None, return_string=True)}.")

    if preposition in BESIDE:
        # Beside it, not inside it. Moved to wherever the host is, so that
        # putting a coin under a rug you are holding puts the coin down --
        # and then pointed at it.
        where = getattr(host, "location", None)
        if where is None:
            return False, "That will not go there."
        if obj.location is not where and not obj.move_to(
                where, quiet=quiet, move_type="place"):
            return False, "That will not go there."
        setattr(obj.db, HOST_ATTR, host)
        obj.db.relation = preposition
        return True, said

    if not obj.move_to(host, quiet=quiet, move_type="place"):
        return False, "That will not go there."
    obj.attributes.remove(HOST_ATTR)
    obj.db.relation = preposition
    return True, said


def _circular(obj, host):
    """
    Why this would put something at itself, or "".

    Two ways round now, and the words matter. Containment answers the old way:
    a box may not go inside the bag it holds. A pointer answers the new one,
    and it is the case somebody actually meets -- the table is on the rug, and
    somebody tries to put the rug on the table.

    Said as what it is rather than as "that would have to go inside itself",
    which was the only refusal available before and named containment in a
    sentence where the player had said "on".
    """
    seen, where = set(), host
    while where is not None and id(where) not in seen:
        seen.add(id(where))
        if where is obj:
            # Say which way round it already is, when that is knowable. "The
            # table is already on the rug" is what somebody trying to put the
            # rug on the table needs to hear; "that would have to go inside
            # itself" was all that could be said, and it named containment in
            # a sentence where they had said "on".
            preposition, at = relation_of(host)
            if at is obj and preposition:
                these = host.get_numbered_name(1, None, return_string=True)
                those = obj.get_numbered_name(1, None, return_string=True)
                return f"{these.capitalize()} is already {preposition} {those}."
            return "That would have to go inside itself."
        where = host_of(where)
    return "" if not _holds(obj, host) else \
        "That would have to go inside itself."


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
    if obj is None:
        return
    if obj.db.relation:
        obj.db.relation = None
    if getattr(obj.db, HOST_ATTR, None) is not None:
        obj.attributes.remove(HOST_ATTR)


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------

def enclosing(obj, limit=MAX_DEPTH + 2):
    """
    The places something is inside, innermost first.

    The room you are standing in, the ship that room is part of, and so on
    outwards. Bounded, because a world that has managed to put a thing inside
    itself should answer the question rather than hang.
    """
    found, seen = [], set()
    host = getattr(obj, "location", None)
    while host is not None and len(found) < limit and host.id not in seen:
        seen.add(host.id)
        found.append(host)
        host = getattr(host, "location", None)
    return found


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


def standing(obj, looker=None):
    """
    Where a thing stands, said from its own side: "under the table".

    The other half of `context_line`, and the thing that could not be said at
    all. Put the table on the rug and the relation was written on the table
    alone, so the rug knew nothing: looking at it said "On it: a table", which
    is the same fact told from the wrong end, and `relation_of(rug)` answered
    that the rug was nowhere in particular.

    Only the first, because a thing has one place to stand and several things
    may be at it. What is *at* a thing is `describe`.
    """
    for preposition in PREPOSITIONS:
        for other in contents(obj, preposition):
            said = INVERSE.get(preposition)
            if not said:
                continue
            return (f"{said} "
                    f"{other.get_numbered_name(1, looker, return_string=True)}")
    return ""


def _event(caller, verb, roles, template):
    """
    One placement, as a thing that happened rather than as two sentences.

    The template keeps its participants as slots so that each person in the
    room can be told in their own words -- which is what makes "you" possible
    for whoever is being handed something, and a pronoun possible later. See
    `world.events`.
    """
    from world import events

    return events.Event(actor=caller, verb=verb, roles=roles,
                        room_template=template)


# ---------------------------------------------------------------------------
# The verbs this owns
# ---------------------------------------------------------------------------

#: Ways of saying "put this there". Like wearing, this is a mechanic and not
#: something a world should be asked to invent: every one of these means
#: exactly one thing, and the game already knows what.
VERBS = ("put", "place", "insert", "drop")

#: And the way back out again. Taking something off a shelf or out of an open
#: drawer is the same mechanic read backwards, and it needs saying separately
#: because `get` has a command of its own: that command reads everything after
#: the verb as a name, so "get the key from the drawer" looked for a thing
#: called "key from the drawer" and offered to invent one. Only reached for a
#: `get` that named somewhere to get it from; the plain sort never comes here.
TAKING = ("get", "remove", "extract")

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
    # Taking, which is placement read backwards. Any of the three roles a
    # preposition can put a host in will do -- "out of the drawer", "off the
    # table", "in the box" -- because all three are ways of saying where the
    # thing is now, and `_take_from` declines unless it really is there.
    if verb in TAKING:
        for role in ("source", "container", "target"):
            host = bound.get(role)
            if host is None:
                continue
            if _take_from(caller, bound.get("direct"), host, on_message):
                return True

    if verb not in VERBS:
        return False

    obj = bound.get("direct")
    if obj is None or not _is_thing(obj):
        return False

    preposition, host = _destination(parsed, bound)
    if host is None:
        return False        # no "in"/"on" phrase: an ordinary drop, not this

    # "Put the lamp down here" names the room, which is not a container and
    # not a mystery either: it is the plainest drop there is. Worth catching,
    # because the alternative is refusing it for the cellar not holding
    # things, or buying a `put` rule to be told the same.
    if host is getattr(caller, "location", None):
        return _set_down(caller, obj, host, on_message)

    if not _is_thing(host):
        return False

    ok, message = place(obj, host, preposition, quiet=True)
    if not ok:
        on_message(message)
        return True

    label = obj.get_numbered_name(1, caller, return_string=True)
    where = host.get_numbered_name(1, caller, return_string=True)
    on_message(
        f"You put {label} {preposition} {where}.",
        _event(caller, "put", {"direct": obj, "container": host},
               f"{{actor}} $pconj(put) {{direct}} {preposition} {{container}}."))
    return True


def _take_from(caller, obj, host, on_message):
    """
    Take something out of, off or from under whatever is holding it.

    Declines -- by answering False -- when the thing named is not actually
    there, which is what keeps "get the answer from the book" a question for a
    world rather than a placement that failed.
    """
    if not _is_thing(host):
        return False
    if obj is None:
        # Nothing bound, which for a shut container is not a mystery: reach
        # stops at a lid, so what is inside cannot be named at all. Saying the
        # drawer is closed is the answer; the alternative is "you see no key
        # here" followed by an offer to invent one, which is how a closed
        # drawer comes to have a second key standing beside it.
        if is_shut(host):
            shut = host.get_numbered_name(1, caller, return_string=True)
            on_message(f"{shut[:1].upper()}{shut[1:]} is closed.")
            return True
        return False
    if not _is_thing(obj):
        return False
    if host_of(obj) is not host:
        return False
    if obj.location is caller:
        on_message("You already have that.")
        return True
    preposition = preposition_of(obj)
    if preposition == DEFAULT and is_shut(host):
        shut = host.get_numbered_name(1, caller, return_string=True)
        on_message(f"{shut[:1].upper()}{shut[1:]} is closed.")
        return True
    # Taking a thing out of a drawer is taking it, so this world's rules about
    # taking are asked here too -- it is the same action arriving by a
    # different door. See `attempt.permitted` and `attempt.consequences`.
    from world import attempt

    refused = attempt.permitted(caller, "get", {"direct": obj, "source": host})
    if refused:
        on_message(refused)
        return True
    if not obj.move_to(caller, quiet=True, move_type="get"):
        on_message("You cannot take that.")
        return True
    displace(obj)
    obj.at_get(caller)
    label = obj.get_numbered_name(1, caller, return_string=True)
    where = host.get_numbered_name(1, caller, return_string=True)
    on_message(
        f"You take {label} {preposition} {where}.",
        _event(caller, "get", {"direct": obj, "source": host},
               f"{{actor}} $pconj(take) {{direct}} {preposition} {{source}}."))
    # Taking a thing out of a drawer is taking it, so whatever this world says
    # follows from that applies here too -- it is the same action arriving by
    # a different door. See `attempt.consequences`.
    attempt.consequences(caller, "get", {"direct": obj, "source": host})
    return True


def _set_down(caller, obj, room, on_message):
    """Put something on the floor of the room somebody is standing in."""
    label = obj.get_numbered_name(1, caller, return_string=True)
    if obj.location is room:
        on_message(f"{label.capitalize()} is already here.")
        return True
    if not obj.move_to(room, quiet=True, move_type="drop"):
        on_message("You cannot put that down here.")
        return True
    displace(obj)
    obj.at_drop(caller)
    on_message(f"You put down {label}.",
               _event(caller, "drop", {"direct": obj},
                      "{actor} $pconj(put) down {direct}."))
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


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`examine`: one thing within reach, as a model needs to know it."""
    from world import toolbox as tb

    def examining(ctx, args):
        from world import ownership, tokens, verbs

        name = str(args.get("name") or "").strip()
        looker = ctx.actor
        obj = find(looker, name) if looker is not None else None
        if obj is None and ctx.room is not None:
            wanted = name.lower()
            obj = next((thing for thing in ctx.room.contents
                        if _is_thing(thing) and wanted in thing.key.lower()),
                       None)
        if obj is None:
            return f"There is nothing called {name} within reach."
        said = [f"{obj.key}: {tokens.text_of(obj) or '(no description)'}",
                "can be: " + (", ".join(sorted(verbs.affordances(obj)))
                              or "nothing special"),
                "currently: " + (", ".join(sorted(verbs.states(obj)))
                                 or "nothing notable")]
        where = context_line(obj, looker)
        if where:
            said.append(f"sitting: {where}")
        for preposition in PREPOSITIONS:
            here = contents(obj, preposition)
            if here:
                said.append(f"{preposition} it: "
                            + ", ".join(thing.key for thing in here))
        owner = ownership.owner_name(obj)
        said.append(f"belongs to: {owner}" if owner else "belongs to nobody")
        return "\n".join(said)

    return [tb.Tool(
        "examine",
        "Look closely at one thing within reach: what it is, what can be done "
        "to it, what condition it is in, where it sits and whose it is.",
        tb.params({"name": {"type": "string",
                            "description": "What to look at"}}, ["name"]),
        tb.answering(examining), doing="looking something over", looks=True,
        available=lambda ctx: ctx.actor is not None or ctx.room is not None)]
