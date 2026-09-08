"""
Putting things down, one at a time or all at once.

Dropping a single thing is Evennia's own command and stays that way. What is
added here is `drop all`, which exists because of how this game is played: a
player wanders through several worlds in an evening, every room offers
something worth picking up, and there is otherwise no way out of a full
inventory but naming forty things in turn.

Undressing is part of it. "Everything you have" plainly means the coat as
well as what is in your hands, and a player who has to take six garments off
before they can drop them has been given a chore, not a command.
"""

from evennia.commands.default.general import CmdDrop as _DefaultDrop
from evennia.utils import iter_to_str

from world import clothing


#: What a player types when they mean the lot. Anything else after `drop` is
#: the name of a thing, and goes to Evennia's own command untouched.
EVERYTHING = ("all", "everything", "all items")


def _undress(character):
    """
    Take everything off, whatever is covering whatever.

    `take_off` refuses a garment worn under another, so this goes round
    again: removing the coat uncovers the shirt, and the next pass reaches
    what the first could not. Garments that refuse twice are set aside rather
    than asked forever -- nothing in the world refuses today, but a command
    that empties an inventory is not the place to trust that.
    """
    stuck = set()
    while True:
        reachable = [garment
                     for garment in clothing.worn_by(character,
                                                     exclude_covered=False)
                     if not garment.db.covered_by and garment.id not in stuck]
        if not reachable:
            return
        for garment in reachable:
            removed, _actor_text, _room_text = clothing.take_off(character,
                                                                 garment)
            if not removed:
                stuck.add(garment.id)


class CmdAIDrop(_DefaultDrop):
    """
    put something down

    Usage:
      drop <item>
      drop all

    |wdrop all|n empties you out completely: clothes come off and go down
    with everything you were carrying, in one movement and one line. It is
    the way out of an inventory that has swallowed six worlds' worth of
    interesting objects.

    Anything inside something you are carrying goes down with it -- dropping
    a satchel does not tip it out on the floor.
    """

    def func(self):
        if self.args.strip().lower() in EVERYTHING:
            self._drop_everything()
            return
        super().func()

    def _drop_everything(self):
        caller = self.caller
        room = caller.location
        if room is None:
            caller.msg("There is nowhere to put anything down.")
            return

        _undress(caller)

        dropped, kept = [], []
        for obj in clothing.carried_by(caller):
            if not obj.at_pre_drop(caller):
                kept.append(obj)
                continue
            if obj.move_to(room, quiet=True, move_type="drop"):
                obj.at_drop(caller)
                dropped.append(obj)
            else:
                kept.append(obj)

        if not dropped and not kept:
            caller.msg("You are not carrying anything.")
            return

        if dropped:
            names = iter_to_str([clothing.item_name(obj, caller)
                                 for obj in dropped])
            actor = caller.get_display_name(caller)
            caller.msg(f"You put down {names}.")
            room.msg_contents(f"{actor} puts down {names}.", exclude=caller)

            from world.npc_gen import notify_npcs

            notify_npcs(room, "action", actor, f"{actor} puts down {names}.",
                        exclude=caller, actor=caller)

        if kept:
            names = iter_to_str([clothing.item_name(obj, caller)
                                 for obj in kept])
            caller.msg(f"You cannot put down {names}.")
