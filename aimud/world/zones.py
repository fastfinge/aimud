"""
Zones as places rather than labels, and places inside other places.

A world plan names the areas a place is made of -- an admin wing, a gym block
-- and once that was all a zone was: a string copied onto each room as it was
built. Nothing indexed it, nothing bounded it, and nothing could say whether a
zone was full. So a world could only shuffle rooms between the three to six
zones it was born with. It never ran out of somewhere to put the next room,
and a world that never runs out never has to imagine anywhere new.

A zone here is a record: an identity, a parent, the rooms that belong to it,
the box those rooms occupy, and a budget -- roughly how many rooms the place
it describes is worth walking through. A zone that has spent its budget is
full, and a full zone stops being offered to the room namer.

That omission is what makes a world grow. Nothing decides to create a zone.
The world runs out of anywhere to put the next room and has to say what is out
there instead, which is a far easier question than asking a model to judge
when a district ends.

Zones nest, and nesting is what makes size mean anything. A zone is planned in
its own right the first time anybody goes there, and that plan may say the
place is made of smaller places: a school entered from a high street becomes a
school with an admin wing and a gym block in it. Depth comes from planning
alone. A zone born at a seam is always a sibling of the one it was entered
from -- walking out of the school's front door puts you beside the school, not
inside it -- so there is one way for the tree to deepen rather than two.

What that buys is scope. Each zone says what may exist only once inside it,
and each is checked against its own subtree alone. "One gymnasium per school"
and "many schools per country" stop being two rules and become one rule read
at two heights.

Zone ids are slugs of zone names, which is what carries older worlds over
without a migration: a room already stamped "Gym Block" is a room in
`gym_block`, and the whole tree is rebuilt from the plan and from the rooms
themselves the first time anything asks.
"""

import re

from evennia.utils import logger

#: The zone that is the world itself.
#:
#: It holds no rooms and is never offered as somewhere to put one. It exists so
#: that every zone has a parent and every ancestry walk ends in the same place
#: -- and so the singletons that must be unique in the whole world are declared
#: in exactly the same way as the ones unique to a single school.
ROOT = "_world"

#: How big a zone may be asked to be.
#:
#: A model given free rein writes 2 or 200, and neither is a place you can walk
#: around: one is finished before it is recognisable, the other is never
#: finished at all -- which is the failure this module exists to end.
MIN_BUDGET = 3
MAX_BUDGET = 40

#: What an unplanned zone is worth when a world has no sizes to judge by.
DEFAULT_BUDGET = 8

#: How deep the tree may go.
#:
#: Country, town, school, wing is four, and past that the areas are smaller
#: than the rooms in them. A limit also stops a planner that always answers
#: "this place is made of smaller places" from recursing until it runs out of
#: nouns.
MAX_DEPTH = 4


def slugify(name):
    """
    The stable id for a zone name. "Gym Block" and "gym block" are one zone.

    ROOT is passed through as itself, so that the sentinel survives a round
    trip through the lookups. That does mean a model writing the literal
    "_world" lands on the same id -- so the world zone is defended where it
    matters instead, at every path that could write to it: `register` and
    `assign` refuse it outright, `attach` falls back to the zone the room came
    from, and the namer is told it is the world rather than a place in it.
    Nothing here has to be the only guard, and it is not.
    """
    if name == ROOT:
        return ROOT
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def clamp_budget(value):
    """A room budget that is actually walkable, whatever was asked for."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_BUDGET
    return max(MIN_BUDGET, min(MAX_BUDGET, number))


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def _blank(name, purpose="", room_types=(), budget=DEFAULT_BUDGET,
           parent=ROOT, singleton_types=(), planned=False):
    return {
        "name": str(name).strip(),
        "purpose": str(purpose).strip(),
        "room_types": [str(t).strip().lower() for t in room_types],
        "singleton_types": [str(t).strip().lower() for t in singleton_types],
        "budget": clamp_budget(budget),
        "parent": parent,
        "rooms": [],
        "types_used": {},
        "bounds": None,
        "planned": bool(planned),
        # What sort of place this is, and what is true of it just now. A zone
        # is where a multi-room thing lives -- a ship with a bridge and an
        # engine room, a planet with a spaceport -- so it is the level at which
        # "the ship is powered" and "this planet forbids launches" are facts.
        "kind": "",
        "states": [],
    }


def _admit(record, room):
    """Put one room into a zone record, in place, growing its box to fit."""
    from world import coords

    if room.id not in record["rooms"]:
        record["rooms"].append(room.id)

    slug = str(room.db.room_type or "").strip().lower()
    if slug:
        record["types_used"].setdefault(slug, room.db.room_title or room.key)

    coord = coords.get_coord(room)
    if coord is None:
        # Rooms behind portals and labelled exits are never placed. They still
        # belong to a zone and still count against its budget; they simply say
        # nothing about where the zone is.
        return
    box = record.get("bounds")
    if box is None:
        record["bounds"] = [list(coord), list(coord)]
        return
    low, high = box
    record["bounds"] = [
        [min(a, b) for a, b in zip(low, coord)],
        [max(a, b) for a, b in zip(high, coord)],
    ]


def _world_record(world_root):
    from world import lore

    try:
        name = lore.title(world_root)
    except Exception:
        name = world_root.key
    record = _blank(name, parent=None, budget=0, planned=True)
    record["is_world"] = True
    return record


def _adopt(world_root):
    """
    Build the tree for a world that has never had one.

    Everything a zone needs already exists in an older world and is read back
    rather than thrown away: the plan says what each zone is for and what must
    be unique in the world, and the rooms themselves -- each stamped with a
    zone name and a room type -- say which rooms are in each zone, where they
    sit, and what has been built there already.

    Adopted zones are left unplanned, so each is described properly the next
    time a room is built in it.
    """
    from world.worldgen import world_plan

    plan = world_plan(world_root)
    zones = {ROOT: _world_record(world_root)}
    zones[ROOT]["singleton_types"] = [
        str(t).strip().lower() for t in (plan.get("singleton_types") or [])
    ]

    for entry in (plan.get("zones") or []):
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        zones[slugify(name)] = _blank(
            name,
            entry.get("purpose", ""),
            entry.get("room_types") or [],
            entry.get("room_budget"),
            parent=ROOT,
            singleton_types=entry.get("singleton_types") or [],
        )

    from evennia import search_tag

    for room in search_tag(str(world_root.id), category="ai_world"):
        zone_id = slugify(room.db.zone)
        if not zone_id or zone_id == ROOT:
            continue
        record = zones.get(zone_id)
        if record is None:
            # A zone the plan never mentioned, because an older world let the
            # namer write whatever it liked. It is a real place with real rooms
            # standing in it, so it is kept.
            record = zones[zone_id] = _blank(room.db.zone)
        _admit(record, room)

    world_root.db.zones = zones
    return zones


def all_zones(world_root):
    """Every zone in this world, as {id: record}."""
    if world_root is None:
        return {}
    stored = world_root.db.zones
    if stored is None:
        stored = _adopt(world_root)
    return dict(stored)


def get(world_root, zone_id):
    """One zone's record, or None."""
    return all_zones(world_root).get(slugify(zone_id))


def name_of(world_root, zone_id):
    """A zone's display name, or its id if the world does not know it."""
    record = get(world_root, zone_id)
    return record["name"] if record else str(zone_id or "")


def is_world(world_root, zone_id):
    """True for the zone that stands for the whole world rather than a place in it."""
    return slugify(zone_id) == ROOT


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------

def ancestry(world_root, zone_id):
    """
    A zone and each place that contains it, innermost first, ending at the world.

    Guarded against a cycle rather than trusting the tree, because a parent is
    written by whatever opened the zone and a loop here would hang the namer
    rather than merely misplace a room.
    """
    zones = all_zones(world_root)
    chain, seen = [], set()
    current = slugify(zone_id)
    while current and current in zones and current not in seen:
        chain.append(current)
        seen.add(current)
        current = zones[current].get("parent")
    if ROOT in zones and ROOT not in seen:
        chain.append(ROOT)
    return chain


def depth(world_root, zone_id):
    """How deep a zone sits. A zone directly inside the world is 1."""
    return max(0, len(ancestry(world_root, zone_id)) - 1)


def parent_of(world_root, zone_id):
    """The zone containing this one, or ROOT."""
    record = get(world_root, zone_id)
    return (record.get("parent") or ROOT) if record else ROOT


def children_of(world_root, zone_id):
    """The ids of the zones directly inside this one."""
    zone_id = slugify(zone_id)
    return [
        other for other, record in all_zones(world_root).items()
        if record.get("parent") == zone_id
    ]


def descendants(world_root, zone_id):
    """A zone and everything inside it, at any depth."""
    found, frontier = [], [slugify(zone_id)]
    while frontier:
        current = frontier.pop()
        if current in found:
            continue
        found.append(current)
        frontier.extend(children_of(world_root, current))
    return found


def path_of(world_root, zone_id, separator=" > "):
    """Where a zone is, written outermost first: "Ashford > Oakfield School"."""
    chain = [z for z in ancestry(world_root, zone_id) if z != ROOT]
    return separator.join(name_of(world_root, z) for z in reversed(chain))


# ---------------------------------------------------------------------------
# Opening and filling zones
# ---------------------------------------------------------------------------

def register(world_root, name, purpose="", room_types=(), budget=None,
             parent=ROOT, singleton_types=()):
    """
    Add a zone to the world. Returns its id, or "" for an unusable name.

    Registering one that already exists changes nothing -- two rooms deciding
    on the same new zone in the same breath is agreement, not a collision.
    """
    zone_id = slugify(name)
    if not zone_id or zone_id == ROOT or world_root is None:
        return ""
    zones = all_zones(world_root)
    if zone_id not in zones:
        parent = slugify(parent) or ROOT
        if parent not in zones:
            parent = ROOT
        zones[zone_id] = _blank(
            name, purpose, room_types,
            budget if budget is not None else typical_budget(world_root),
            parent=parent, singleton_types=singleton_types,
        )
        world_root.db.zones = zones
        logger.log_info(
            f"zones: {world_root.key!r} opened {name!r} in "
            f"{name_of(world_root, parent)} "
            f"({zones[zone_id]['budget']} rooms) -- "
            f"{purpose or 'no stated purpose'}"
        )
    return zone_id


def assign(world_root, room, zone_id):
    """Record that `room` belongs to `zone_id`. Returns the id actually used."""
    zone_id = slugify(zone_id)
    zones = all_zones(world_root)
    record = zones.get(zone_id)
    if record is None or zone_id == ROOT:
        return ""
    _admit(record, room)
    world_root.db.zones = zones
    room.db.zone = zone_id
    return zone_id


def attach(world_root, room, zone_name, purpose=""):
    """
    Put a freshly built room in the zone it named, opening that zone if it is new.

    A new zone is a sibling of the one the room was entered from: walking out
    of a school's front door puts you beside the school, not inside it. Depth
    comes from planning a place once somebody is in it, never from a doorway,
    so there is only ever one way for the tree to grow.

    A room that named nothing usable stays in the zone of the room it was
    entered from. Better a room slightly in the wrong place than a room
    belonging nowhere: a room outside every zone is a room no budget counts,
    and a budget that does not count rooms never runs out.
    """
    parent_room = room.db.world_parent
    source = slugify(parent_room.db.zone) if parent_room else ""

    zone_id = slugify(zone_name)
    if zone_id and zone_id not in all_zones(world_root):
        register(world_root, zone_name, purpose,
                 parent=parent_of(world_root, source) if source else ROOT)
    if not zone_id or zone_id == ROOT:
        zone_id = source
    if not zone_id:
        return ""
    return assign(world_root, room, zone_id)


def record_type(world_root, zone_id, slug, room):
    """Note that a room of this kind now stands in this zone."""
    slug = str(slug or "").strip().lower()
    zone_id = slugify(zone_id)
    if not slug or not zone_id:
        return
    zones = all_zones(world_root)
    record = zones.get(zone_id)
    if record is None:
        return
    record["types_used"].setdefault(slug, room.db.room_title or room.key)
    world_root.db.zones = zones


# ---------------------------------------------------------------------------
# Is there room here?
# ---------------------------------------------------------------------------

def size(world_root, zone_id):
    """How many rooms sit directly in a zone."""
    record = get(world_root, zone_id)
    return len(record["rooms"]) if record else 0


def budget(world_root, zone_id):
    """How many rooms a zone was meant to hold directly."""
    record = get(world_root, zone_id)
    return record["budget"] if record else DEFAULT_BUDGET


def full(world_root, zone_id):
    """
    True when a zone holds every room it was meant to hold directly.

    Being full is not a wall. Rooms already standing in a full zone keep every
    exit they were written with, and walking one still builds something -- it
    simply builds it somewhere else. A zone made of smaller zones is usually
    full early and quite deliberately: a school itself is a lobby and a main
    corridor, and everything else about it is one of its wings.
    """
    record = get(world_root, zone_id)
    if not record:
        return False
    if record.get("is_world"):
        return True
    return len(record["rooms"]) >= record["budget"]


def finished(world_root, zone_id):
    """True when a zone is full and so is everywhere inside it."""
    return all(full(world_root, zid) for zid in descendants(world_root, zone_id))


def open_zones(world_root):
    """{id: record} for the zones that would take another room right now."""
    return {
        zone_id: record
        for zone_id, record in all_zones(world_root).items()
        if not record.get("is_world") and not full(world_root, zone_id)
    }


def typical_budget(world_root):
    """
    What to give a zone nobody planned.

    The sizes already in this world are a better guide than any constant: a
    world built of small rooms should not suddenly acquire a forty-room field
    because a default said so.
    """
    sizes = [
        record["budget"] for zone_id, record in all_zones(world_root).items()
        if not record.get("is_world")
    ]
    if not sizes:
        return DEFAULT_BUDGET
    return clamp_budget(round(sum(sizes) / len(sizes)))


# ---------------------------------------------------------------------------
# Where a zone is
# ---------------------------------------------------------------------------

def contains(world_root, zone_id, coord, margin=1):
    """
    Whether `coord` is inside a zone's box, allowing it to grow by `margin`.

    A zone grows one cell at a time out of a room already inside it, so a
    genuine next room is never more than one cell beyond the box. Anything
    further off is a room claiming a zone it is nowhere near -- the mistake a
    zone-as-a-string could not even notice, because a label is true wherever
    you write it.
    """
    record = get(world_root, zone_id)
    if not record:
        return False
    box = record.get("bounds")
    if box is None:
        return True         # nothing placed yet, so nothing to be far from
    low, high = box
    return all(
        lo - margin <= value <= hi + margin
        for value, lo, hi in zip(coord, low, high)
    )


def placed(world_root, zone_id):
    """Whether a zone has anywhere to be yet -- any room of it standing on the map."""
    record = get(world_root, zone_id)
    return bool(record) and record.get("bounds") is not None


def around(world_root, coord, margin=1):
    """
    The ids of zones whose box reaches `coord` -- what is already next door.

    Zones nobody has built are left out. `contains` lets them be claimed from
    anywhere, because a zone with no rooms in it cannot be far from anything
    and has to be reachable to get its first room; but that is a rule about
    what may be claimed, not about what is nearby. A planned-but-unbuilt wing
    is not next door. It is nowhere.
    """
    if coord is None:
        return []
    return [
        zone_id for zone_id, record in all_zones(world_root).items()
        if not record.get("is_world")
        and placed(world_root, zone_id)
        and contains(world_root, zone_id, coord, margin)
    ]


def unbuilt_near(world_root, zone_id):
    """
    Planned places around here that nobody has been to yet.

    Only what is genuinely to hand: the areas inside this one, and the ones
    beside it under the same roof. A gym block nobody has visited is a reason
    not to invent a new wing of that school, and no reason at all not to open
    a marketplace on the other side of the town.
    """
    zone_id = slugify(zone_id)
    if not zone_id:
        return []
    nearby = set(children_of(world_root, zone_id))
    nearby.update(children_of(world_root, parent_of(world_root, zone_id)))
    nearby.discard(zone_id)
    return [
        other for other in nearby
        if not placed(world_root, other) and not full(world_root, other)
    ]


# ---------------------------------------------------------------------------
# What may exist only once, and where
# ---------------------------------------------------------------------------

def types_in(world_root, zone_id):
    """Every room type built anywhere inside a zone, as {slug: room name}."""
    used = {}
    for other in descendants(world_root, zone_id):
        record = get(world_root, other)
        if record:
            for slug, title in (record.get("types_used") or {}).items():
                used.setdefault(slug, title)
    return used


def singletons_taken(world_root, zone_id):
    """
    The room types a room in this zone may not be, and what already holds each.

    Returns {slug: (room name, the place that allows only one)}.

    Every place a room is inside is asked what may exist only once in it, and
    each answer is checked against that place alone. One gymnasium per school
    and many schools per country are then the same rule read at two heights,
    rather than two rules that have to agree.
    """
    taken = {}
    for ancestor in ancestry(world_root, zone_id):
        record = get(world_root, ancestor)
        if not record:
            continue
        declared = [str(s).lower() for s in (record.get("singleton_types") or [])]
        if not declared:
            continue
        used = types_in(world_root, ancestor)
        for slug in declared:
            if slug in used and slug not in taken:
                taken[slug] = (used[slug], record["name"])
    return taken


# ---------------------------------------------------------------------------
# Planning a zone in its own right
# ---------------------------------------------------------------------------

def needs_plan(world_root, zone_id):
    """
    Whether this place has yet been thought about as a place.

    True for a zone opened at a seam, which so far is only a name and a guess
    at a size, and for one the world plan named in passing but nobody has
    described. Either way the answer is wanted once and then never again.
    """
    record = get(world_root, zone_id)
    return bool(record) and not record.get("is_world") and not record.get("planned")


def apply_plan(world_root, zone_id, data):
    """
    Record what a zone turned out to be. Returns the ids of any zones inside it.

    A place may be made of smaller places, and if it is, they are opened here
    as its children. Its own budget stays: a school made of wings is still a
    lobby and a main corridor, and those rooms belong to the school itself
    rather than to any wing of it.
    """
    zone_id = slugify(zone_id)
    zones = all_zones(world_root)
    record = zones.get(zone_id)
    if record is None:
        return []

    if data.get("purpose"):
        record["purpose"] = str(data["purpose"]).strip()
    if data.get("room_types"):
        record["room_types"] = [str(t).strip().lower() for t in data["room_types"]]
    if data.get("singleton_types"):
        record["singleton_types"] = [
            str(t).strip().lower() for t in data["singleton_types"]
        ]
    if data.get("room_budget") is not None:
        # Never below what is already standing there: a budget that arrives
        # smaller than the rooms it is meant to govern would declare a zone
        # over-full the moment it was described.
        record["budget"] = max(clamp_budget(data["room_budget"]),
                               len(record["rooms"]))
    record["planned"] = True
    world_root.db.zones = zones

    if depth(world_root, zone_id) >= MAX_DEPTH:
        return []

    opened = []
    for child in (data.get("zones") or []):
        name = str(child.get("name", "")).strip()
        if not name or slugify(name) == zone_id:
            continue
        child_id = register(
            world_root, name,
            child.get("purpose", ""),
            child.get("room_types") or [],
            child.get("room_budget"),
            parent=zone_id,
            singleton_types=child.get("singleton_types") or [],
        )
        if child_id:
            opened.append(child_id)
    return opened


# ---------------------------------------------------------------------------
# What the namer is told
# ---------------------------------------------------------------------------

def offerable(world_root, coord=None, source_zone=""):
    """
    The zones a room at `coord` could actually be put in.

    Exactly what the naming rules would accept, and no more: the open zones
    whose box reaches this spot, and the planned places around here nobody has
    been to yet. A world with a dozen districts must not offer eleven of them
    that are miles away -- every one of those is a line of prompt the namer has
    to read and a rejection waiting to happen when it picks one.

    With no coordinate -- a world built before the map, or a room behind a
    portal -- there is nothing to be near or far from, so everything open is
    offered and the budget rules alone decide.
    """
    if coord is None:
        return list(open_zones(world_root))
    offered = [zid for zid in around(world_root, coord)
               if not full(world_root, zid)]
    for zone_id in unbuilt_near(world_root, source_zone):
        if zone_id not in offered:
            offered.append(zone_id)
    return offered


def menu(world_root, coord=None, source_zone=""):
    """
    The zones a new room may be put in, written for a prompt.

    Full zones are left out, and that omission is the mechanism: a namer that
    cannot put this room in the gym block, because the gym block is built, has
    to say what else is out here.

    Each line says where the place is, so that containment needs no explaining
    -- "Gym Block (in Oakfield School)" is a wing of a school, and nothing has
    to reason about a tree to see it. Zones whose box already reaches the new
    room are marked, so a room on a seam continues the district next door
    rather than inventing a third one in the gap between two that already
    exist.
    """
    adjacent = set(around(world_root, coord)) if coord is not None else set()
    zones = all_zones(world_root)
    lines = []
    for zone_id in offerable(world_root, coord, source_zone):
        record = zones.get(zone_id)
        if record is None:
            continue
        left = record["budget"] - len(record["rooms"])
        within = path_of(world_root, parent_of(world_root, zone_id))
        reaches = " — reaches this spot" if zone_id in adjacent else ""
        types = ", ".join(record["room_types"])
        lines.append(
            f"- {record['name']}"
            + (f" (in {within})" if within else "")
            + f": {record['purpose'] or 'no stated purpose'} "
            f"(room for about {left} more{reaches}"
            + (f"; typical rooms: {types}" if types else "")
            + ")"
        )
    return "\n".join(lines)


def full_names(world_root, coord=None):
    """
    Display names of the zones that will take no more rooms, for a prompt.

    Scoped to what reaches `coord`, for the same reason the menu is: a full
    district on the other side of the world is not a temptation the namer
    needs warning about. Without a coordinate there is nothing to be near, so
    every full zone is named.
    """
    if coord is None:
        return [
            record["name"] for zone_id, record in all_zones(world_root).items()
            if not record.get("is_world") and full(world_root, zone_id)
        ]
    return [
        name_of(world_root, zone_id) for zone_id in around(world_root, coord)
        if full(world_root, zone_id)
    ]

# ---------------------------------------------------------------------------
# What sort of place a zone is, and what is true of it
# ---------------------------------------------------------------------------

def kind_of(world_root, zone_id):
    """What sort of place this zone is, or ""."""
    record = get(world_root, zone_id)
    try:
        return str(record.get("kind") or "")
    except AttributeError:
        return ""


def set_kind(world_root, zone_id, kind):
    """
    Settle what sort of place a zone is. First answer stands, as for a kind.

    Asked rather than guessed from the name, because a zone's name is as often
    a proper noun as a common one: "Kepler Nine" and "The Wandering Albatross"
    would ground as a number and a seabird. A wrong kind is worse than none --
    every rule filed against it would be about the wrong sort of thing.
    """
    from world import kinds

    zone_id = slugify(zone_id)
    settled = kinds.canonical(kind)
    zones = all_zones(world_root)
    if not settled or zone_id not in zones or zones[zone_id].get("kind"):
        return kind_of(world_root, zone_id)
    zones[zone_id]["kind"] = settled
    world_root.db.zones = zones
    logger.log_info(f"zones: {zones[zone_id]['name']!r} is a {settled}")
    return settled


def states(world_root, zone_id):
    """The conditions true of this zone just now."""
    record = get(world_root, zone_id)
    try:
        return {str(s) for s in (record.get("states") or [])}
    except AttributeError:
        return set()


def apply_states(world_root, zone_id, add=(), remove=()):
    """
    Change a zone's condition, through the world's own state vocabulary.

    A place can be `under_curfew` or `depressurised` the same way a bottle can
    be `empty`, and for the same reasons: `register_state` gives the word a
    meaning, a group and a help entry, and none of that machinery cares whether
    the thing it is applied to is a bottle or a planet.
    """
    from world import verbs

    zone_id = slugify(zone_id)
    zones = all_zones(world_root)
    if zone_id not in zones:
        return set()
    current = states(world_root, zone_id)
    current -= {str(s).lower().strip() for s in (remove or ())}
    for slug in (add or ()):
        settled = verbs.register_state(world_root, str(slug))
        if not settled:
            continue
        group = verbs.group_of(world_root, settled)
        if verbs.group_rules(world_root, group).get("exclusive"):
            current -= (verbs.group_members(world_root, group) - {settled})
        current.add(settled)
    zones[zone_id]["states"] = sorted(current)
    world_root.db.zones = zones
    return set(zones[zone_id]["states"])
