"""
What a world is furnished with, made by hand: items, rooms, ways out, people.

The registers above this are word lists; these are objects, and they differ in
one way that decides the whole module: **there is no list of every item in the
world to choose from.** What you may edit is what you can reach, found the way
the parser finds it, and the room you may edit is the one you are standing in.
`commands/subjects.py` `thing_here` is that rule, once, for all of them.

Everything is built through the writer a generator uses -- `clothing.create`
for an item, `worldgen._create_room` for a room, `worldgen._make_exit` for a
way out -- so an object somebody typed and an object a model wrote are the
same object, with the same kinds, the same floor and the same naming rule
applied. Where a rule's effect would do the job, the effect does it:
`effects.modify_complaints` guards a name and a description here exactly as it
guards a rule's.
"""

from commands.subjects import reachable
from world import making, menus

# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _root(ctx):
    return making.root_of(ctx)


def _caller(ctx):
    return making.caller_of(ctx)


def _here(ctx):
    return getattr(_caller(ctx), "location", None)


def _target(ctx):
    """The thing this form is editing, passed in when the menu was opened."""
    return (ctx.data or {}).get("target")


def state_options(ctx):
    from world import verbs

    return [(slug, f"{slug} -- {entry.get('means') or ''}".rstrip(" -"))
            for slug, entry in sorted((verbs.vocabulary(_root(ctx))
                                       or {}).items())]


def kind_options(ctx):
    from world.makers import vocabulary

    return vocabulary.kind_entries(_root(ctx))


def _complaints(ctx, name, description, obj=None):
    from world import effects

    return effects.modify_complaints(
        obj if obj is not None else _placeholder(ctx),
        new_name=name or "", new_description=description or "",
        world_root=_root(ctx), room=_here(ctx))


class _placeholder:
    """
    Stands in for a thing that does not exist yet, so one checker serves both.

    `modify_complaints` was written for a thing being changed and asks two
    questions that are just as true of a thing being made: whether the name
    says what condition it is in, and whether the description asks for a word
    list this world keeps. Rather than a second copy of those two rules, the
    thing being made is given the shape the checker reads.
    """

    def __init__(self, ctx):
        self.location = _here(ctx)
        self.key = ""

        class _Db:
            states = []

        self.db = _Db()


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

WHERE = (
    ("room", "on the floor here"),
    ("actor", "in your hands"),
    ("in", "inside something here"),
    ("on", "on top of something here"),
    ("under", "under something here"),
    ("behind", "behind something here"),
)


def host_options(ctx):
    return [(str(obj.id), obj.key) for obj in reachable(_caller(ctx),
                                                        people=False)]


def _needs_host(ctx):
    return str(ctx.draft.get("where") or "room") in ("in", "on", "under",
                                                     "behind")


def _item_spec(ctx):
    from world.makers import gearing

    kind = str(ctx.draft.get("kind") or "").strip()
    spec = {
        "name": str(ctx.draft.get("name") or "").strip(),
        "description": str(ctx.draft.get("description") or "").strip(),
        "kind": kind,
        "sense": kind if "." in kind else "",
        "states": list(ctx.draft.get("states") or []),
        "takeable": ctx.draft.get("takeable", True),
    }
    # What it is worth to whoever has it, through the same three fields a
    # generator declares and a rule's effect fills in.
    spec.update(gearing.spec(ctx.draft))
    return spec


def keep_item(ctx):
    from world import clothing, ownership, relations

    caller = _caller(ctx)
    room = _here(ctx)
    spec = _item_spec(ctx)
    if not spec["name"]:
        raise menus.Refuse("It needs a name.")
    wrong = _complaints(ctx, spec["name"], spec["description"])
    if wrong:
        raise menus.Refuse(_said(wrong))

    where = str(ctx.draft.get("where") or "room")
    location = caller if where == "actor" else room
    obj = clothing.create(spec, location=location)
    if obj is None:
        raise menus.Refuse("That could not be made.")
    ownership.claim(caller, obj)

    if where in ("in", "on", "under", "behind"):
        host = _object_by_id(ctx, ctx.draft.get("host"))
        if host is None:
            # Made, and left where it landed rather than thrown away: the
            # placement is the only part that failed, and `edit item` moves it.
            return obj.id, (f"{obj.key} is here, but nothing was picked to "
                            f"put it {where} -- |wedit item {obj.key}|n moves "
                            f"it.")
        try:
            relations.place(obj, host, where)
        except Exception:
            return obj.id, f"{obj.key} is here; it would not go {where} " \
                           f"{host.key}."
        return obj.id, f"{obj.key} is now {where} {host.key}."
    return obj.id, (f"{obj.key} is "
                    + ("in your hands." if where == "actor" else "here."))


def _object_by_id(ctx, ident):
    for obj in reachable(_caller(ctx)):
        if str(obj.id) == str(ident):
            return obj
    return None


def _said(complaints):
    return "This one cannot be made: " + "; ".join(complaints) + "."


def _gearing_items(present_only=False):
    from world.makers import gearing

    return gearing.items(present_only=present_only)

NEW_ITEM = menus.Form(
    key="new-item", title="Something in this room", guided=True,
    intro="A thing, made here. It is built the same way a generated one is, "
          "so it has the same kinds, the same affordances and the same rules "
          "about it.",
    discard="Throw away this thing?",
    items=[
        menus.Field("name", "What it is called", required=True,
                    suggestible=True,
                    help="Two to four words. A name says what a thing IS and "
                         "never what condition it is in -- broken, lit and "
                         "half-empty are conditions, and something can undo "
                         "them."),
        menus.Field("description", "What it looks like", kind=menus.LONG_TEXT,
                    suggestible=True,
                    help="Two or three sentences about the thing alone. A "
                         "word list in braces -- {smell} -- is chosen once "
                         "and kept."),
        making.picker("kind", "What sort of thing it is", "kind",
                      options=kind_options, required=True,
                      help="Which sort it belongs to. This is where its "
                           "affordances come from, and what a rule about that "
                           "sort of thing will reach."),
        making.picker("states", "What condition it is in", "condition",
                      options=state_options,
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none",
                      help="Conditions it starts in: lit, shut, wet. Several, "
                           "separated by spaces."),
        menus.Field("takeable", "Can it be picked up?", kind=menus.BOOLEAN,
                    default=True,
                    help="Answered for the sort of thing, not only this one: "
                         "a world with forty chairs answers once."),
        *_gearing_items(),
        menus.Field("where", "Where it goes", kind=menus.CHOICE,
                    choices=lambda ctx: [menus.Choice(v, l) for v, l in WHERE]),
        menus.Picker("host", "In or on what", options=host_options,
                     lock=_needs_host),
        making.keeper("keep", "Make it", keep_item,
                      command=lambda ctx: "create item <name>"),
    ],
)


def _read_words(text):
    found = [word.strip().lower() for word in str(text or "").split()]
    return [word for word in found if word], ""


def item_entries(root):
    """Nothing: an item is chosen by reaching for it, never off a list."""
    return []


def edit_item(root, ident):
    """The form for one reachable thing, found by `thing_here`."""
    return _EDIT_THING


def _thing_writer(field):
    def write(ctx, value):
        from world import effects

        obj = _target(ctx)
        if obj is None:
            raise menus.Refuse("That is no longer here.")
        name = str(value or "") if field == "new_name" else ""
        desc = str(value or "") if field == "new_description" else ""
        wrong = effects.modify_complaints(obj, new_name=name,
                                          new_description=desc,
                                          world_root=_root(ctx),
                                          room=_here(ctx))
        if wrong:
            raise menus.Refuse(_said(wrong))
        if field == "new_name":
            obj.key = str(value or "").strip() or obj.key
            effects.forget_narrations(obj)
            return f"It is called {obj.key} now."
        obj.db.desc = str(value or "").strip()
        effects.forget_narrations(obj)
        return "What it looks like has changed."

    return write


def _set_states(ctx, value):
    from world import verbs

    obj = _target(ctx)
    if obj is None:
        raise menus.Refuse("That is no longer here.")
    wanted = sorted({str(word).lower() for word in (value or [])})
    obj.db.states = wanted
    return f"It is now {', '.join(wanted) or 'in no condition in particular'}."


def thing_text(ctx):
    from world import kinds, verbs

    obj = _target(ctx)
    if obj is None:
        return "That is no longer here."
    lines = [f"|w{obj.key}|n", obj.db.desc or "|xnothing written about it|n"]
    try:
        lines.append(f"  a {', a '.join(kinds.of(obj)) or 'thing'}")
    except Exception:
        pass
    states = sorted(verbs.states(obj))
    if states:
        lines.append(f"  {', '.join(states)}")
    return "\n".join(lines)


def _worth_draft(ctx):
    from world.makers import gearing

    obj = _target(ctx)
    return gearing.drafted(obj) if obj is not None else {}


def _worth_label(ctx):
    from world.makers import gearing

    obj = _target(ctx)
    return (f"What it is worth: {gearing.said(obj)}" if obj is not None
            else "What it is worth")


def _keep_worth(ctx):
    from world.makers import gearing

    obj = _target(ctx)
    if obj is None:
        raise menus.Refuse("That is no longer here.")
    return obj.id, gearing.write(obj, ctx.draft)


_WORTH = menus.Form(
    key="worth", title="What it is worth", guided=False,
    intro="What this thing does for whoever has it. Changed here it takes "
          "effect at once, including for whoever is holding it now.",
    items=lambda ctx: _gearing_items() + [
        making.keeper("keep", "Keep this", _keep_worth)],
)


_EDIT_THING = menus.Form(
    key="edit-thing", title=lambda ctx: f"Changing {_label(ctx)}",
    intro=thing_text,
    items=[
        menus.Field("new_name", "What it is called",
                    get=lambda ctx: getattr(_target(ctx), "key", ""),
                    set=_thing_writer("new_name")),
        menus.Field("new_description", "What it looks like",
                    kind=menus.LONG_TEXT, suggestible=True,
                    get=lambda ctx: getattr(getattr(_target(ctx), "db", None),
                                            "desc", ""),
                    set=_thing_writer("new_description")),
        making.picker("states", "What condition it is in", "condition",
                      options=state_options,
                      get=lambda ctx: sorted(
                          getattr(getattr(_target(ctx), "db", None),
                                  "states", None) or []),
                      set=_set_states,
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none",
                      help="Several, separated by spaces. A condition this "
                           "world does not keep can be made from here."),
        menus.Submenu("worth", _worth_label, _WORTH,
                      fresh_draft=True, draft=_worth_draft,
                      help="What it does for whoever has it, and when that "
                           "counts."),
    ],
)


def _label(ctx):
    obj = _target(ctx)
    return getattr(obj, "key", "it")


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

def direction_options(ctx):
    from world import worldgen

    root, here = _root(ctx), _here(ctx)
    if root is None or here is None:
        return []
    free = worldgen.openable_directions(root, here)
    return [(way, way) for way in free]


def zone_options(ctx):
    from world import zones

    root = _root(ctx)
    here = _here(ctx)
    mine = zones.slugify(getattr(here.db, "zone", "") or "") if here else ""
    found = []
    for zone_id in sorted(zones.all_zones(root) or {}):
        if zone_id == zones.ROOT:
            continue
        name = zones.name_of(root, zone_id)
        found.append((name, f"{name}{' -- where you are' if zone_id == mine else ''}"))
    return found


NEW_ZONE = making.word_form(
    "new-zone", "A new area", "What the area is called",
    lambda ctx, text: (text.strip(), f"{text.strip()} it is."),
    intro="Areas are how a world keeps a wing of a building together, and how "
          "it knows a place is full.",
    help="A few words: the east wing, the cellars, the orchard.")


def keep_room(ctx):
    from world import coords, worldgen

    root, here = _root(ctx), _here(ctx)
    if root is None or here is None:
        raise menus.Refuse("You are not standing anywhere a room can open off.")
    going = worldgen.canonical_direction(
        str(ctx.draft.get("direction") or "").strip())
    if not going:
        raise menus.Refuse("Which way should it open?")
    if going not in worldgen.openable_directions(root, here):
        taken = coords.step(coords.get_coord(here), going)
        already = coords.room_at(root, taken) if taken else None
        if already is not None:
            raise menus.Refuse(
                f"{already.key} is already {going} of here. |wcreate way|n "
                f"opens a way onto a room that already exists.")
        raise menus.Refuse(f"Nothing can open {going} from here.")

    title = str(ctx.draft.get("name") or "").strip()
    if not title:
        raise menus.Refuse("It needs a name.")
    description = str(ctx.draft.get("description") or "").strip()
    wrong = _complaints(ctx, title, description)
    if wrong:
        raise menus.Refuse(_said(wrong))

    from world.makers import gearing

    room = worldgen._create_room(
        title, description, [],
        getattr(root.db, "world_description", "") or "",
        here, going, world_root=root,
        room_type=str(ctx.draft.get("room_type") or ""),
        category="destination",
        zone=str(ctx.draft.get("zone") or ""),
        zone_purpose=str(ctx.draft.get("zone_purpose") or ""),
        # What being in this place does to whoever is in it. Always for
        # everybody present -- a forge is warm whether or not anything in it
        # is -- so `_create_room` sets the condition itself.
        bonuses=gearing.spec(ctx.draft).get("trait_bonuses"))
    if room is None:
        raise menus.Refuse("That room could not be made.")
    # The way there. `_create_room` makes the way back; this is the way out.
    from typeclasses.exits import AIExit

    worldgen._make_exit(AIExit, going, here, room, pending=False)
    return room.id, (f"|w{room.key}|n opens {going} of here, and a way back "
                     f"leads to {here.key}.")


NEW_ROOM = menus.Form(
    key="new-room", title="Somewhere new", guided=True,
    intro="A room, written rather than generated, opening off the one you are "
          "standing in.",
    discard="Throw away this room?",
    items=[
        menus.Picker("direction", "Which way it opens",
                     options=direction_options, required=True,
                     help="Only the ways nothing already leads. A direction "
                          "with a room already in it is joined with "
                          "|wcreate exit|n instead, which is what lets a "
                          "world close back on itself."),
        menus.Field("name", "What it is called", required=True,
                    suggestible=True,
                    help="What somebody sees at the top of the room."),
        menus.Field("description", "What it looks like", kind=menus.LONG_TEXT,
                    required=True, suggestible=True,
                    help="What is here and what it is like. A word list in "
                         "braces -- {weather}, {smell} -- is chosen once for "
                         "this room and kept, which is how twenty rooms "
                         "written from one description differ."),
        making.picker("zone", "Which area", "zone", options=zone_options,
                      make=lambda ctx: NEW_ZONE,
                      none="None of these -- start a new area",
                      help="Which part of the world it belongs to. An area "
                           "that reaches its planned size takes no more "
                           "rooms."),
        menus.Field("room_type", "What sort of place",
                    help="One word or two: classroom, cellar, bridge. It is "
                         "what makes `only one of these in this area` "
                         "answerable, and what a rule about that sort of "
                         "place reaches."),
        *_gearing_items(present_only=True),
        making.keeper("keep", "Make it", keep_room,
                      command=lambda ctx: "create room <direction>"),
    ],
)


def room_text(ctx):
    from world import verbs, zones

    room = _here(ctx)
    if room is None:
        return ""
    root = _root(ctx)
    lines = [f"|w{room.key}|n", room.db.desc or "|xnothing written|n"]
    zone = getattr(room.db, "zone", "")
    if zone:
        lines.append(f"  in {zones.name_of(root, zones.slugify(zone)) or zone}")
    ways = [obj.key for obj in room.contents if getattr(obj, "destination", None)]
    if ways:
        lines.append(f"  ways out: {', '.join(sorted(ways))}")
    states = sorted(verbs.states(room))
    if states:
        lines.append(f"  {', '.join(states)}")
    return "\n".join(lines)


def _room_writer(field):
    def write(ctx, value):
        from world import effects, tokens

        room = _here(ctx)
        if room is None:
            raise menus.Refuse("You are nowhere.")
        name = str(value or "") if field == "key" else ""
        desc = str(value or "") if field == "desc" else ""
        wrong = effects.modify_complaints(room, new_name=name,
                                          new_description=desc,
                                          world_root=_root(ctx), room=room)
        if wrong:
            raise menus.Refuse(_said(wrong))
        if field == "key":
            room.key = str(value or "").strip() or room.key
            room.db.room_title = room.key
            return f"This place is called {room.key} now."
        room.db.desc = str(value or "").strip()
        # Whatever the new text asks for, chosen once and kept, exactly as a
        # generated room's is.
        tokens.settle(room)
        return "What this place looks like has changed."

    return write


def _room_worth_draft(ctx):
    from world.makers import gearing

    room = _here(ctx)
    return gearing.drafted(room) if room is not None else {}


def _room_worth_label(ctx):
    from world.makers import gearing

    room = _here(ctx)
    return (f"What being here is worth: {gearing.said(room)}"
            if room is not None else "What being here is worth")


def _keep_room_worth(ctx):
    from world.makers import gearing

    room = _here(ctx)
    if room is None:
        raise menus.Refuse("You are nowhere.")
    return room.id, gearing.write(room, ctx.draft, present_only=True)


_ROOM_WORTH = menus.Form(
    key="room-worth", title="What being here is worth", guided=False,
    intro="What being in this place does to whoever is in it, for everybody "
          "standing here. It takes effect at once.",
    items=lambda ctx: _gearing_items(present_only=True) + [
        making.keeper("keep", "Keep this", _keep_room_worth)],
)


EDIT_ROOM = menus.Form(
    key="edit-room", title="This place", intro=room_text,
    items=[
        menus.Field("key", "What it is called",
                    get=lambda ctx: getattr(_here(ctx), "key", ""),
                    set=_room_writer("key")),
        menus.Field("desc", "What it looks like", kind=menus.LONG_TEXT,
                    suggestible=True,
                    get=lambda ctx: getattr(getattr(_here(ctx), "db", None),
                                            "desc", ""),
                    set=_room_writer("desc")),
        menus.Field("states", "What condition it is in", kind=menus.CHOICE,
                    choices=lambda ctx: [
                        menus.Choice(slug, label)
                        for slug, label in state_options(ctx)],
                    get=lambda ctx: sorted(
                        getattr(getattr(_here(ctx), "db", None), "states",
                                None) or []),
                    set=lambda ctx, value: _set_room_states(ctx, value),
                    parse=lambda ctx, text: _read_words(text),
                    show=lambda ctx, value: ", ".join(value or []) or "none"),
        menus.Submenu("worth", _room_worth_label, _ROOM_WORTH,
                      fresh_draft=True, draft=_room_worth_draft,
                      help="What being in this place does to whoever is in "
                           "it. A forge is warm whether or not anything in "
                           "it is."),
    ],
)


def _set_room_states(ctx, value):
    room = _here(ctx)
    if room is None:
        raise menus.Refuse("You are nowhere.")
    room.db.states = sorted({str(word).lower() for word in (value or [])})
    return f"This place is now {', '.join(room.db.states) or 'ordinary'}."


# ---------------------------------------------------------------------------
# Ways out
# ---------------------------------------------------------------------------

def room_options(ctx):
    """Every room in this world, for joining one to another."""
    from evennia import search_tag

    root = _root(ctx)
    here = _here(ctx)
    if root is None:
        return []
    found = []
    for room in search_tag(str(root.id), category="ai_world"):
        if room is here or getattr(room, "destination", None):
            continue
        found.append((str(room.id), room.key))
    return sorted(found, key=lambda entry: entry[1])


def keep_exit(ctx):
    from evennia.objects.models import ObjectDB
    from typeclasses.exits import AIExit
    from world import worldgen

    here = _here(ctx)
    if here is None:
        raise menus.Refuse("You are nowhere.")
    name = str(ctx.draft.get("name") or "").strip()
    if not name:
        raise menus.Refuse("A way out needs a name: north, the hatch, down.")
    if any(obj.key.lower() == name.lower() for obj in here.contents
           if getattr(obj, "destination", None)):
        raise menus.Refuse(f"A way called {name} already leads out of here.")
    try:
        target = ObjectDB.objects.get(id=int(ctx.draft.get("to") or 0))
    except Exception:
        raise menus.Refuse("Pick somewhere for it to lead.")
    way = worldgen._make_exit(AIExit, name, here, target, pending=False)
    if way is None:
        raise menus.Refuse("That way could not be opened.")
    said = f"A way {name} now leads to {target.key}."
    if ctx.draft.get("both"):
        back = str(ctx.draft.get("returning") or "").strip() or _opposite(name)
        if not any(obj.key.lower() == back.lower() for obj in target.contents
                   if getattr(obj, "destination", None)):
            worldgen._make_exit(AIExit, back, target, here, pending=False)
            said += f" {back.capitalize()} leads back."
    return way.id, said


def _opposite(name):
    from world.worldgen import OPPOSITES

    return OPPOSITES.get(str(name or "").strip().lower(), "back")


NEW_EXIT = menus.Form(
    key="new-exit", title="A way out of here", guided=True,
    intro="Joins this room to one that already exists -- a stair, a portal, "
          "a door the map could not express. Somewhere new is made with "
          "|wcreate room|n instead, which digs it.",
    items=[
        menus.Field("name", "What it is called", required=True,
                    help="north, down, in, the hatch. What somebody types to "
                         "go that way."),
        menus.Picker("to", "Where it leads", options=room_options,
                     required=True),
        menus.Field("both", "A way back as well?", kind=menus.BOOLEAN,
                    default=True,
                    help="A world where you can walk somewhere and not walk "
                         "back is usually a mistake rather than a design."),
        # Not called `back`: that is the key that backs out of every menu.
        menus.Field("returning", "What the way back is called",
                    lock=lambda ctx: bool(ctx.draft.get("both")),
                    help="Left empty, the opposite of the way out, or `back`."),
        making.keeper("keep", "Open it", keep_exit,
                      command=lambda ctx: "create way <name>"),
    ],
)


def exit_entries(root):
    return []


def remove_exit(root, ident):
    """
    Close a way out. The one deletion in building that needs saying twice.

    `effects.py` keeps exits permanently off limits to rules, because a
    character deleting one would strand the world. A builder may; the
    confirmation names what it costs.
    """
    from evennia.objects.models import ObjectDB

    try:
        way = ObjectDB.objects.get(id=int(ident))
    except Exception:
        return f"There is no way out called |w{ident}|n."
    where = getattr(way, "destination", None)
    name = way.key
    way.delete()
    return (f"The way {name} is closed."
            + (f" |x{where.key} may now be unreachable from here -- "
               f"|wview zones|n shows what is where.|n" if where else ""))


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

def pronoun_options(ctx):
    from world import pronouns

    found = []
    for name in sorted(pronouns.vocabulary(_root(ctx)) or {}):
        found.append((name, name))
    return found


def _new_pronoun_form(ctx):
    from commands.pronoun_cmds import NEW_SET

    return NEW_SET


def trait_options(ctx):
    from world.makers import vocabulary

    return [(value, label) for value, label, _help
            in vocabulary.attribute_entries(_root(ctx))]


NEW_TRAIT_VALUE = menus.Form(
    key="npc-trait", title="A figure about this character", guided=True,
    items=[
        making.picker("trait", "Which attribute", "attribute",
                      options=trait_options, required=True),
        menus.Field("value", "Standing at", kind=menus.NUMBER, required=True),
        making.keeper("keep", "Keep it", lambda ctx: (
            {"trait": str(ctx.draft.get("trait") or ""),
             "value": ctx.draft.get("value")},
            f"{ctx.draft.get('trait')} {ctx.draft.get('value')}.")),
    ],
)


def _trait_line(ctx, entry):
    return f"{entry.get('trait')} {entry.get('value')}"


def keep_npc(ctx):
    from world import kinds, npc_gen, ownership, traits

    caller, room = _caller(ctx), _here(ctx)
    if room is None or not room.db.is_ai_room:
        raise menus.Refuse("People can only be put in generated rooms.")
    name = str(ctx.draft.get("name") or "").strip()
    if not name:
        raise menus.Refuse("They need a name.")
    description = str(ctx.draft.get("description") or "").strip()
    wrong = _complaints(ctx, name, description)
    if wrong:
        raise menus.Refuse(_said(wrong))

    from evennia import create_object

    npc = create_object("typeclasses.npcs.NPC", key=name, location=room)
    npc.db.desc = description
    npc.db.is_npc = True
    npc.db.world_root = _root(ctx)
    chosen = str(ctx.draft.get("pronouns") or "").strip()
    if chosen:
        npc.db.pronoun_set = chosen
    kinds.ensure_person(npc)
    for entry in ctx.draft.get("traits") or []:
        slug = str(entry.get("trait") or "")
        if slug:
            traits.ensure(npc, slug, world_root=_root(ctx))
            traits.adjust(npc, slug, set_to=entry.get("value"),
                          world_root=_root(ctx))
    states = list(ctx.draft.get("states") or [])
    if states:
        npc.db.states = sorted({str(word).lower() for word in states})
    goal = list(ctx.draft.get("goal") or [])
    if goal:
        npc.db.goal_conditions = goal
    room.msg_contents(f"|g{npc.key} has arrived.|n")
    return npc.id, (f"|w{npc.key}|n is here. |xThey will not act on their own "
                    f"without a model; what they can still do is hand out an "
                    f"errand -- |wcreate quest|n.|n")


def _npc_items(ctx):
    from world.makers import rules as rule_forms

    return [
        menus.Field("name", "What they are called", required=True,
                    suggestible=True),
        menus.Field("description", "What they look like",
                    kind=menus.LONG_TEXT, suggestible=True),
        making.picker("pronouns", "Pronouns", "pronoun",
                      options=pronoun_options, make=_new_pronoun_form,
                      none="None of these -- add a pronoun set",
                      help="How everybody here speaks about them."),
        making.picker("states", "What condition they are in", "condition",
                      options=state_options,
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none"),
        making.listing_field(
            "traits", "Figures about them", NEW_TRAIT_VALUE, _trait_line,
            add_label="Add a figure", empty="none"),
        making.listing_field(
            "goal", "What they want", rule_forms.NEW_CONDITION,
            rule_forms.condition_line, add_label="Add something they want",
            empty="nothing in particular",
            help="What they are working towards. Without a model they will "
                 "not plan for it, and a rule can still test it."),
        making.keeper("keep", "Make them", keep_npc,
                      command=lambda ctx: "create person <name>"),
    ]


NEW_NPC = menus.Form(
    key="new-npc", title="Somebody here", guided=True,
    intro="A character, written rather than generated. Costs nothing, and "
          "needs no model to exist -- only to think.",
    discard="Throw away this character?",
    items=_npc_items,
)


def person_text(ctx):
    from world import traits, verbs

    npc = _target(ctx)
    if npc is None:
        return "They are no longer here."
    lines = [f"|w{npc.key}|n", npc.db.desc or "|xnothing written about them|n"]
    states = sorted(verbs.states(npc))
    if states:
        lines.append(f"  {', '.join(states)}")
    said = traits.describe(npc)
    if said:
        lines.append(said)
    return "\n".join(lines)


EDIT_PERSON = menus.Form(
    key="edit-person", title=lambda ctx: f"Changing {_label(ctx)}",
    intro=person_text,
    items=[
        menus.Field("new_name", "What they are called",
                    get=lambda ctx: getattr(_target(ctx), "key", ""),
                    set=_thing_writer("new_name")),
        menus.Field("new_description", "What they look like",
                    kind=menus.LONG_TEXT, suggestible=True,
                    get=lambda ctx: getattr(getattr(_target(ctx), "db", None),
                                            "desc", ""),
                    set=_thing_writer("new_description")),
        making.picker("states", "What condition they are in", "condition",
                      options=state_options,
                      get=lambda ctx: sorted(
                          getattr(getattr(_target(ctx), "db", None),
                                  "states", None) or []),
                      set=_set_states,
                      parse=lambda ctx, text: _read_words(text),
                      show=lambda ctx, value: ", ".join(value or []) or "none"),
    ],
)


def remove_thing(root, ident):
    """Remove a thing by dbref. Reached only through `thing_here`."""
    from evennia.objects.models import ObjectDB

    try:
        obj = ObjectDB.objects.get(id=int(ident))
    except Exception:
        return "That is no longer here."
    name = obj.key
    obj.delete()
    return f"{name} is gone."


MAKERS = [
    making.Maker(
        "item", ("item", "items", "thing", "things", "object", "objects"),
        "Things", opens_with="name",
        listing=item_entries, new=NEW_ITEM, edit=edit_item,
        remove=remove_thing,
        reached=lambda caller: reachable(caller, people=False),
        make_label="Something in this room",
        help="A thing, made here rather than generated. Editing one reaches "
             "only what is in front of you.",
    ),
    making.Maker(
        "room", ("room", "rooms", "place"),
        "This place", opens_with="direction",
        new=NEW_ROOM, edit=lambda root, ident: EDIT_ROOM,
        one=lambda root, ident: "", sole=True,
        make_label="Somewhere new, opening off this room",
        help="A room, written rather than generated. Editing always means the "
             "room you are standing in.",
    ),
    making.Maker(
        # Called `way` and not `exit`: `exit` quits every menu in the game,
        # so a subject named that could never be an entry in one. "Ways out"
        # is what this codebase calls them anyway.
        "way", ("way", "ways", "door", "doors", "passage"),
        "Ways out of here", opens_with="name",
        listing=exit_entries, new=NEW_EXIT,
        remove=remove_exit,
        reached=lambda caller: [obj for obj
                                in getattr(getattr(caller, "location", None),
                                           "contents", None) or []
                                if getattr(obj, "destination", None)],
        make_label="A way out of here, onto a room that exists",
        help="Joins this room to one that already exists: a stair, a portal, "
             "a door the map could not express.",
    ),
    making.Maker(
        "person", ("person", "people", "somebody"),
        "People", opens_with="name",
        listing=lambda root: [], new=NEW_NPC,
        edit=lambda root, ident: EDIT_PERSON, remove=remove_thing,
        reached=lambda caller: [obj for obj in reachable(caller, people=True)
                                if getattr(obj.db, "is_npc", False)],
        make_label="Somebody here, written by hand",
        help="A character, written rather than generated, and costing "
             "nothing. |wcreate npc|n is the other one: a model invents "
             "somebody who belongs here, and the world pays for them.",
    ),
]
