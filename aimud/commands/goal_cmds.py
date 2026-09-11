"""
The goal command: tell the game what you are trying to do, and be reminded.

Setting a goal costs one model call, to turn what you said into conditions the
game can test -- the same call an NPC makes when it decides what it wants.
Everything after that is free: the planner reads rules and room connections
already in memory, so the reminder under each command costs nothing.
"""

from commands.command import Command
from world import hints


class CmdGoal(Command):
    """
    Say what you are trying to do, and be shown the next step towards it.

    Usage:
      goal <what you want>
      goal

    Examples:
      goal go to the library
      goal find the brass key
      goal be wearing the grey coat

    With something after it, this becomes what you are working towards. After
    every command you type, a quiet line underneath says what would take you a
    step closer -- usually a direction to walk, or a command to try.

    With nothing after it, you drop the goal and the reminders stop. They also
    stop by themselves the moment you have done it.

    It is a reminder and nothing more. Nothing moves you, nothing acts for
    you, and ignoring the suggestion costs you nothing -- wander off, take the
    long way, or do it some other way entirely, and the next suggestion is
    worked out from wherever you actually ended up.

    See also |wquests hint|n, which does the same for an errand somebody has
    asked you to run.
    """

    key = "goal"
    aliases = ["goals"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        want = self.args.strip()

        if not want:
            self._clear()
            return

        room = caller.location
        if room is None or not room.db.is_ai_room:
            caller.msg("You can only set a goal inside a world.")
            return

        from world import sponsor as sponsor_mod

        sponsor = sponsor_mod.of(caller)
        try:
            sponsor.key()
        except ValueError as e:
            caller.msg(str(e))
            return

        if caller.ndb.setting_goal:
            caller.msg("You are still making up your mind about the last one.")
            return
        caller.ndb.setting_goal = True
        caller.msg(f"Working out how you would {want}...")

        from world.quest_gen import formalise_goal

        formalise_goal(sponsor, caller, want,
                       on_success=self._ready, on_error=self._failed)

    def _clear(self):
        caller = self.caller
        had = hints.clear(caller)
        if not had:
            caller.msg(
                "You have no goal set. |wgoal <what you want>|n gives you one, "
                "and a reminder of the next step towards it."
            )

    def _ready(self, conditions):
        """The model has turned what was said into testable conditions."""
        caller = self.caller
        caller.ndb.setting_goal = None

        from world import goals

        clean = goals.sanitise(conditions, owner=caller)
        if not clean:
            caller.msg(
                "|rThat is not something the game knows how to check on.|n Try "
                "something it can see: being somewhere, carrying something, "
                "wearing something, or a thing being in some state."
            )
            return

        caller.db.goal = clean
        caller.db.goal_stalls = 0
        world_root = caller.location.db.world_root if caller.location else None
        caller.msg(f"|gYou set out to {goals.describe(clean, caller, world_root)}.|n")

        # Show the first step at once rather than waiting for the next command,
        # and say plainly when there is none -- a goal that quietly never
        # suggests anything looks broken rather than hard.
        action, note = hints.suggestion(caller, clean)
        if action:
            caller.msg(f"Next: |w{action}|n")
        else:
            caller.msg(f"|x{note}|n")

    def _failed(self, err):
        self.caller.ndb.setting_goal = None
        self.caller.msg(f"|rCould not work that out: {err}|n")
