"""
The quests command: see what you have been asked to do, and answer for it.
"""

from commands.command import Command


class CmdQuests(Command):
    """
    See what people have asked of you, and how far along you are.

    Usage:
      quests
      quests hint
      quests accept
      quests decline
      quests abandon

    Characters you meet may ask you to do things. Anything offered waits at
    the top of the list until you accept or decline it; anything underway
    shows each part of it and whether you have done that part yet.

    You carry one errand at a time. Until it is done, has failed, or you
    abandon it, nobody will ask you for anything else -- and abandoning costs
    you nothing beyond the giver knowing you are not going to do it.

    Some errands come with a time limit, and some with a consequence for
    letting it run out. Both are shown before you agree to anything.

    |wquests hint|n shows how far along you are and what to do next: the
    actual command to type, worked out from where you are standing and what
    the world already knows. It is a reminder, not an autopilot -- nothing
    acts for you, and ignoring it costs you nothing. See also |wgoal|n, which
    does the same for something you decided to do yourself.

    A number may be given if you want to name one exactly, but with a single
    errand at a time it is rarely needed.
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

        if self.action == "hint":
            # Bring it up to date first: a hint for something already finished
            # would be worse than none.
            quests.review(caller)
            from world import hints

            caller.msg(hints.quest_hint(caller))
            return

        if self.action not in ("accept", "decline", "abandon"):
            caller.msg("Usage: |wquests|n, |wquests hint|n, |wquests accept|n, "
                       "|wquests decline|n, |wquests abandon|n.")
            return

        # The number is optional: there is only ever one offer waiting and one
        # errand underway, so naming it is a convenience, not a requirement.
        if self.action == "accept":
            quest, message = quests.accept(caller, self.number)
        elif self.action == "decline":
            quest, message = quests.decline(caller, self.number)
        else:
            quest, message = quests.abandon(caller, self.number)

        caller.msg(message)
        if quest is None:
            return

        # The person who asked should hear the answer.
        room = caller.location
        if room:
            verb = {"accept": "accepts", "decline": "declines",
                    "abandon": "gives up on"}[self.action]
            room.msg_contents(
                f"{caller.get_display_name(caller)} {verb} {quest['giver']}'s request.",
                exclude=[caller],
            )
            from world.npc_gen import notify_npcs

            notify_npcs(room, "action", caller.get_display_name(caller),
                        f"{verb} the request: {quest['title']}",
                        exclude=caller, actor=caller)

        if self.action == "accept":
            # It may already be satisfied by what the player happens to carry.
            quests.review(caller)
