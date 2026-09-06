"""
The quests command: see what you have been asked to do, and answer for it.
"""

from commands.command import Command


class CmdQuests(Command):
    """
    See what people have asked of you, and how far along you are.

    Usage:
      quests
      quests accept <number>
      quests decline <number>

    Characters you meet may ask you to do things. Anything offered waits at
    the top of the list until you accept or decline it; anything underway
    shows each part of it and whether you have done that part yet.

    Some errands come with a time limit, and some with a consequence for
    letting it run out. Both are shown before you agree to anything.
    """

    key = "quests"
    aliases = ["quest"]
    locks = "cmd:all()"
    help_category = "General"

    def parse(self):
        parts = self.args.strip().split()
        self.action = parts[0].lower() if parts else ""
        self.number = None
        for part in parts[1:]:
            if part.isdigit():
                self.number = int(part)
                break

    def func(self):
        caller = self.caller
        from world import quests

        if not self.action:
            # Bring the list up to date before showing it, so a quest finished
            # a moment ago does not still read as outstanding.
            quests.review(caller)
            caller.msg(quests.format_list(caller))
            return

        if self.action not in ("accept", "decline"):
            caller.msg("Usage: |wquests|n, |wquests accept <number>|n, "
                       "|wquests decline <number>|n.")
            return

        if self.number is None:
            caller.msg(f"Which one? Try |wquests {self.action} <number>|n.")
            return

        if self.action == "accept":
            quest, message = quests.accept(caller, self.number)
        else:
            quest, message = quests.decline(caller, self.number)

        caller.msg(message)
        if quest is None:
            return

        # The person who asked should hear the answer.
        room = caller.location
        if room:
            verb = "accepts" if self.action == "accept" else "declines"
            room.msg_contents(
                f"{caller.key} {verb} {quest['giver']}'s request.",
                exclude=[caller],
            )
            from world.npc_gen import notify_npcs

            notify_npcs(room, "action", caller.get_display_name(caller),
                        f"{verb} the request: {quest['title']}",
                        exclude=caller, actor=caller)

        if self.action == "accept":
            # It may already be satisfied by what the player happens to carry.
            quests.review(caller)
