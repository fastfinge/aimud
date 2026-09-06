"""
The name command: choose what you are called in this world.
"""

import re

from commands.command import Command

#: Long enough to be a name, short enough to sit in a line of dialogue.
MIN_LENGTH = 2
MAX_LENGTH = 30

#: Letters, spaces and the punctuation real names contain. Markup codes are
#: excluded deliberately -- a name is spoken by NPCs and written into their
#: memories, and "|rBob|n" has no business turning up in either.
_ALLOWED = re.compile(r"^[A-Za-z][A-Za-z '\-.]*$")


class CmdName(Command):
    """
    Choose what you are called in this world.

    Usage:
      name
      name <what you want to be called>
      name clear

    Each world remembers you separately, so you can be one person in a
    haunted school and someone else entirely aboard a freighter. Characters
    you meet will call you by the name you set here; with none set, they use
    your account name.

    |wname clear|n gives up the name and goes back to your account name.
    """

    key = "name"
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        room = caller.location
        world_root = room.db.world_root if room else None

        if world_root is None:
            caller.msg("You are not in a world that keeps names.")
            return

        from world import lore

        world_desc = lore.title(world_root)
        wanted = self.args.strip()
        current = caller.world_name(world_root)

        if not wanted:
            if current:
                caller.msg(
                    f"In |w{world_desc}|n you are known as |w{current}|n.\n"
                    f"Use |wname <something else>|n to change it, or "
                    f"|wname clear|n to go back to {caller.key}."
                )
            else:
                caller.msg(
                    f"You go by |w{caller.key}|n in |w{world_desc}|n.\n"
                    f"Use |wname <what you want to be called>|n to change that."
                )
            return

        if wanted.lower() == "clear":
            if not current:
                caller.msg("You have no name set here.")
                return
            caller.set_world_name(world_root, None)
            caller.msg(f"You go back to being |w{caller.key}|n here.")
            self._announce(room, current, caller.key)
            return

        problem = self._problem(caller, wanted)
        if problem:
            caller.msg(problem)
            return

        previous = current or caller.key
        caller.set_world_name(world_root, wanted)
        caller.msg(f"In |w{world_desc}|n you are now |w{wanted}|n.")
        self._announce(room, previous, wanted)

    def _problem(self, caller, wanted):
        """Why this name will not do, or None."""
        if len(wanted) < MIN_LENGTH:
            return f"A name needs at least {MIN_LENGTH} characters."
        if len(wanted) > MAX_LENGTH:
            return f"That is longer than {MAX_LENGTH} characters."
        if not _ALLOWED.match(wanted):
            return ("Names start with a letter and use letters, spaces, "
                    "apostrophes, hyphens and full stops only.")
        if wanted.lower() in ("clear", "me", "here", "self"):
            return "That word means something else to the game. Pick another."

        # Someone else in the room already answering to it would make both of
        # them unaddressable.
        room = caller.location
        for obj in (room.contents if room else []):
            if obj is caller:
                continue
            names = [obj.key.lower(), *(a.lower() for a in obj.aliases.all())]
            if wanted.lower() in names:
                return f"Something here is already called {obj.key}."
        return None

    def _announce(self, room, previous, now):
        """Let the room know, so NPCs learn the name rather than guess it."""
        if room is None or previous == now:
            return
        text = f"{previous} is now known as {now}."
        room.msg_contents(text, exclude=[self.caller])
        from world.npc_gen import notify_npcs

        notify_npcs(room, "action", now, f"is now known as {now}",
                    exclude=self.caller, actor=self.caller)
