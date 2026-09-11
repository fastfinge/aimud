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
#:
#: Read from `world.bulk` rather than kept here, so that "all" means the same
#: word list to every verb. This command keeps its own body because dropping
#: everything has a mechanic behind it -- clothes come off first, and in the
#: order that lets them -- which no expansion into single drops would get
#: right.


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
        from world import bulk, verbs

        several, sort = bulk.split(self.args)
        if several:
            self._drop_everything(sort)
            return
        # "Drop the second wrench" is a count, not a name. Evennia's own
        # command reads it as one, looks for a thing called "second wrench"
        # and finds none -- and handing it the name instead would only put the
        # question back, since the whole reason to count is that several
        # things answer to that name.
        one_of_several = verbs.counted(self.caller, self.args)
        if one_of_several is not None:
            self._drop_one(one_of_several)
            return
        super().func()

    def _drop_one(self, obj):
        """
        Put down one particular thing, already chosen.

        The same hooks and the same sentence Evennia's own command uses, which
        is the point of writing it out rather than delegating: a counted drop
        has to look exactly like an ordinary one to everything downstream.
        """
        caller = self.caller
        if obj.location is not caller:
            caller.msg(f"You aren't carrying {obj.get_numbered_name(1, caller, return_string=True)}.")
            return
        if not obj.at_pre_drop(caller):
            return
        if not obj.move_to(caller.location, quiet=True, move_type="drop"):
            self.msg("That can't be dropped.")
            return
        obj.at_drop(caller)
        caller.location.msg_contents(
            f"$You() $conj(drop) "
            f"{obj.get_numbered_name(1, caller, return_string=True)}.",
            from_obj=caller)

    def _drop_everything(self, sort=""):
        """
        Put down everything, or everything of one sort.

        `sort` is what "drop every wrench" narrows to. Empty is the old
        meaning -- the lot, clothes included -- and undressing happens only
        then: taking a coat off to obey "drop every wrench" would be absurd.
        """
        caller = self.caller
        room = caller.location
        if room is None:
            caller.msg("There is nowhere to put anything down.")
            return

        from world import verbs

        if not sort:
            _undress(caller)

        carried = [obj for obj in clothing.carried_by(caller)
                   if not sort
                   or verbs.similarity(sort, obj.key) >= verbs.STRICT_SIMILARITY]
        if sort and not carried:
            caller.msg(f"You are not carrying any {sort}.")
            return

        dropped, kept = [], []
        for obj in carried:
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
