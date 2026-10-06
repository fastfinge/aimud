"""
listen: what a place, or one thing in it, sounds like. docs/sound.md 6.5.

Answered from the ambience the world has written -- the same loops a client
with speakers is playing -- so a player without sound, or an agent, can ask
what a player with sound already hears.

**The world keeps its own word.** `listen at the door` may be a verb a world
has rules for, and a command that took the word outright would take those
rules away. So this answers only when there is ambience to answer with;
anywhere else, in a generated world, the line is handed on exactly as the
unknown-command handler would have taken it, and the world says what
listening there does.
"""

from evennia import Command


class CmdListen(Command):
    """
    hear what is around you

    Usage:
      listen
      listen to <something>

    Says what this place sounds like, or what one thing near you sounds
    like, from the sounds the world has given them. A client that plays
    sounds is already playing these; this is the same thing in words.
    """

    key = "listen"
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        from world import sound

        caller = self.caller
        room = caller.location
        named = self.args.strip()
        for word in ("to ", "at "):
            if named.lower().startswith(word):
                named = named[len(word):].strip()
                break

        if not named:
            heard = sound.heard_here(caller)
            if heard:
                caller.msg(heard)
                return
            if self._world_answers():
                return
            caller.msg("You hear nothing in particular.")
            return

        found = caller.search(named, quiet=True)
        found = found[0] if isinstance(found, list) and len(found) == 1 \
            else (found if found and not isinstance(found, list) else None)
        if found is not None:
            world_root = getattr(getattr(room, "db", None), "world_root", None)
            loops = sound._merged(sound.thing_layer(found, world_root))
            said = sound.described(loops)
            if said:
                caller.msg(f"|x{said}|n")
                return
        if self._world_answers():
            return
        if found is None:
            caller.msg(f"You hear nothing called {named} here.")
        else:
            caller.msg(f"You hear nothing from {found.get_display_name(caller)}.")

    def _world_answers(self):
        """Hand the line to the world, as an unknown verb would be. Whether
        it was."""
        room = self.caller.location
        if not (room and room.db.world_description):
            return False
        from commands.unknown_cmd import CmdAIUnknown

        handed = CmdAIUnknown()
        handed.caller = self.caller
        handed.session = self.session
        handed.cmdset = self.cmdset
        handed.raw_string = self.raw_string
        handed.args = self.raw_string
        handed.func()
        return True
