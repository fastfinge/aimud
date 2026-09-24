"""
What a world holds, as subjects: its areas, and the people a model makes for it.

  view zones                           the areas of this world and how full
  create npc                           a character for this room

These were `zones` and `npcgen`. Adding people is for whoever made the world,
because the world pays for its own people -- and `create person` is the other
way to get one, written by hand and costing nothing.

**Word lists and pronoun sets used to live here** and are makers now
(`world/makers/vocabulary.py`), so that everything a player can make is
described in one table. What they answer to and what they say is unchanged;
`create tokens smell = brine | tar` is still that line.
"""

from commands.subjects import (Subject, Use, answered, asking, in_world,
                               names_for, owns_here, require_owner,
                               require_world)
from world import lore, menus
from world import sponsor as sponsor_mod


def _caller(ctx):
    return ctx.character or ctx.caller


def _root(ctx):
    room = getattr(_caller(ctx), "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# view zones
# ---------------------------------------------------------------------------

def zones_report(caller, root):
    """
    Every area of the world, nested, with how full each is.

    An area that has reached its planned size takes no more rooms, and the
    next room built at its edge starts somewhere new instead.
    """
    from world import zones

    if not zones.all_zones(root):
        return "This world has no areas recorded yet."
    location = getattr(caller, "location", None)
    here = zones.slugify(location.db.zone) if location else ""
    lines = [f"|wAreas of {lore.title(root)}:|n", ""]

    def line(zone_id, level):
        record = zones.get(root, zone_id)
        filled, size = len(record["rooms"]), record["budget"]
        if not zones.placed(root, zone_id):
            state = "|xnot built yet|n"
        elif zones.finished(root, zone_id):
            state = "|yfinished|n"
        elif zones.full(root, zone_id):
            state = "|yfull; its parts are still growing|n"
        else:
            state = f"|g{size - filled} to go|n"
        indent = "  " + "    " * level
        mark = " |g[you are here]|n" if zone_id == here else ""
        out = [f"{indent}|w{record['name']}|n -- {filled}/{size} rooms, "
               f"{state}{mark}"]
        if record["purpose"]:
            out.append(f"{indent}    |x{record['purpose']}|n")
        if record.get("singleton_types"):
            out.append(f"{indent}    |xonly one of: "
                       f"{', '.join(record['singleton_types'])}|n")
        return "\n".join(out)

    def branch(zone_id, level):
        if zone_id != zones.ROOT:
            lines.append(line(zone_id, level))
        for child in sorted(zones.children_of(root, zone_id),
                            key=lambda z: zones.name_of(root, z)):
            branch(child, level + (0 if zone_id == zones.ROOT else 1))

    branch(zones.ROOT, 0)
    return "\n".join(lines)


def view_zones_run(cmd, ctx, words):
    root = require_world(cmd.caller)
    if root is not None:
        cmd.caller.msg(zones_report(cmd.caller, root))


# ---------------------------------------------------------------------------
# create npc
# ---------------------------------------------------------------------------

def make_npc(caller):
    """
    Generate a character for the room the caller is in. Returns what to say.

    The world pays for its own people -- the same sponsor every character's
    own turns are paid by.
    """
    room = caller.location
    if not room or not room.db.is_ai_room:
        return "You can only generate characters in generated rooms."
    for obj in room.contents:
        if obj.db.is_npc:
            return f"There is already a character here ({obj.key})."
    if room.ndb.generating_npc:
        return "A character is already being generated for this room."

    payer = sponsor_mod.of(caller)
    try:
        payer.key()
    except ValueError as err:
        return str(err)

    room.ndb.generating_npc = True
    caller.msg("Generating a character for this room...")

    def on_success(npc):
        room.ndb.generating_npc = False
        room.msg_contents(f"|g{npc.key} has arrived.|n", exclude=None)

    def on_error(err):
        room.ndb.generating_npc = False
        caller.msg(f"|rCharacter generation failed: {err}|n")

    from world import busy
    from world.npc_gen import generate_npc

    wait = busy.start(caller, "generating a character for this room")
    generate_npc(sponsor=payer, room=room,
                 on_success=busy.closing(wait, on_success),
                 on_error=busy.closing(wait, on_error))
    return None


def create_npc_run(cmd, ctx, words):
    caller = cmd.caller
    root = require_world(caller)
    if root is None or not require_owner(caller, root, "add people to it"):
        return
    said = make_npc(caller)
    if said:
        caller.msg(said)


def create_npc_items(ctx):
    return [menus.Action("npc", "A character for this room",
                         run=lambda ctx: make_npc(_caller(ctx)),
                         after=menus.CLOSE, aliases=("character",),
                         help="Generates a character who belongs in this room "
                              "and this world. A room holds one.",
                         command=lambda ctx: "create npc")]


# ---------------------------------------------------------------------------
# The subjects
# ---------------------------------------------------------------------------

SUBJECTS = [
    Subject(
        "zones", ("zones", "zone", "areas"),
        uses={"view": Use(view_zones_run, lambda ctx: [menus.Action(
            "zones", "The areas of this world",
            run=lambda ctx: zones_report(_caller(ctx), _root(ctx)),
            after=menus.CLOSE, command=lambda ctx: "view zones",
            help="Every area, what it holds, and how full it is.")],
            offered=in_world)},
        help="The areas of the world you are in, and how full each one is.",
    ),
    Subject(
        "npc", ("npc", "npcs", "character"),
        uses={"create": Use(create_npc_run, create_npc_items,
                            offered=owns_here)},
        help="A character generated for the room you are in.",
    ),
]
