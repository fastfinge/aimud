"""
The follow command.
"""

from commands.command import Command


class CmdFollow(Command):
    """
    Go where someone else goes.

    Usage:
      follow <character>
      follow

    You will move with them from room to room until you stop. Following
    yourself, or using |wfollow|n with nothing after it, stops.

    Only people you can see here can be followed, and you travel with them
    rather than being dragged after them from across the world -- lose sight
    of them and you stay where you are.
    """

    key = "follow"
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        from world.following import follow, following, unfollow

        wanted = self.args.strip()

        if not wanted:
            caller.msg(unfollow(caller))
            return

        target = _find_person(caller, wanted)
        if target is None:
            caller.msg(f"You see no {wanted} here.")
            return

        started, message = follow(caller, target)
        caller.msg(message)
        if not started:
            return

        target.msg(f"{caller.get_display_name(target)} begins following you.")
        room = caller.location
        if room:
            room.msg_contents(
                f"{caller.get_display_name(caller)} begins following "
                f"{target.get_display_name(caller)}.",
                exclude=[caller, target],
            )
            from world.npc_gen import notify_npcs

            notify_npcs(room, "action", caller.get_display_name(caller),
                        f"begins following {target.get_display_name(caller)}",
                        exclude=caller, actor=caller)


def _find_person(caller, wanted):
    """
    A character or NPC here answering to `wanted`.

    Restricted to people: following a chair is not a thing, and letting the
    search match objects would mean "follow bea" silently attaching to a
    beaded curtain.
    """
    from evennia.objects.objects import DefaultCharacter

    room = caller.location
    if room is None:
        return None
    wanted = wanted.lower()

    people = [
        obj for obj in room.contents
        if obj.db.is_npc or isinstance(obj, DefaultCharacter)
    ]
    for obj in people:
        names = [obj.key.lower(), obj.get_display_name(caller).lower(),
                 *(a.lower() for a in obj.aliases.all())]
        if wanted in names:
            return obj
    for obj in people:
        if wanted in obj.key.lower() or wanted in obj.get_display_name(caller).lower():
            return obj
    return None
