"""
The give command.

Thin, like the clothing commands and for the same reason: what giving *means*
-- who may be given a thing, what may be given, and that the owning of it goes
along with it -- lives in `world.ownership`, because a character handing
something over has to reach the same answers without going anywhere near a
command set.

What is here is the routing. Evennia ships a `give` of its own and it is a
plain move: it searches the giver's inventory, searches the room, and moves
the object. It cannot resolve a pronoun ("give it to her"), cannot read "give
Jessica the crowbar", and knows nothing about ownership -- so every one of
those had to be answered somewhere, and the pipeline is where the others
already are. Outside a generated world it is left exactly as it was.
"""

from evennia.commands.default.general import CmdGive as _DefaultGive

from commands.look_take_cmds import _in_ai_world, _sponsor_for


class CmdAIGive(_DefaultGive):
    """
    give away something to someone

    Usage:
      give <item> to <person>
      give <person> <item>

    What you hand over becomes theirs -- not merely in their hands but theirs,
    and so is whatever is inside it that was yours. Something you are wearing
    has to come off first.
    """

    def func(self):
        caller = self.caller
        if not _in_ai_world(caller.location):
            # Outside a generated world there are no rules to consult and no
            # ownership to move: Evennia's own giving is the whole of it.
            super().func()
            return

        if not self.args.strip():
            caller.msg("Give what, and to whom?")
            return

        # Said back the way the parser reads it. Evennia allows "=" as well as
        # "to" and has already split on either, so this is only putting the
        # sentence together again in the one spelling `verbs.parse` knows.
        said = f"{self.lhs.strip()} to {self.rhs.strip()}" if self.rhs \
            else self.args.strip()

        from world import attempt, events

        attempt.attempt(
            caller, f"give {said}", _sponsor_for(caller),
            on_message=lambda actor_text, event=None:
                events.show(actor_text, event, caller))
