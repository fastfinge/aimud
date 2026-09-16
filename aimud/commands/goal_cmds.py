"""
The goal command: tell the game what you are trying to do, and be reminded.

Setting a goal costs one model call, to turn what you said into conditions the
game can test -- the same call an NPC makes when it decides what it wants.
Everything after that is free: the planner reads rules and room connections
already in memory, so the reminder under each command costs nothing.
"""

from commands.command import Command
from world import hints, menus


class CmdGoal(Command):
    """
    Say what you are trying to do, and be shown the next step towards it.

    Usage:
      goal <what you want>
      goal next
      goal clear
      goal

    Examples:
      goal go to the library
      goal find the brass key
      goal be wearing the grey coat

    With something after it, this becomes what you are working towards. After
    every command you type, a quiet line underneath says what would take you a
    step closer -- usually a direction to walk, or a command to try.

    |wgoal next|n says that step again. |wgoal clear|n drops the goal and the
    reminders stop; they also stop by themselves the moment you have done it.
    On its own, |wgoal|n offers all three.

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
        word = want.lower()

        if word in ("clear", "drop", "stop"):
            said = give_up(caller)
            if said:
                caller.msg(said)
            return
        if word in ("next", "hint"):
            caller.msg(next_step(caller))
            return
        if want:
            set_goal(caller, want)
            return
        if menus.interactive(menus.account_of(caller) or caller):
            menus.open_menu(caller, GOAL, session=self.session)
            return
        caller.msg(next_step(caller))


def give_up(caller):
    """Drop the goal. Returns what to say, when `hints.clear` has not said it."""
    if hints.clear(caller):
        return None
    return ("You have no goal set. |wgoal <what you want>|n gives you one, and "
            "a reminder of the next step towards it.")


def next_step(caller):
    """The next step towards the goal, or that there is no goal."""
    from world import goals

    goal = caller.db.goal
    if not goal:
        return ("You have no goal set. |wgoal <what you want>|n gives you one, "
                "and a reminder of the next step towards it.")
    world_root = caller.location.db.world_root if caller.location else None
    action, note = hints.suggestion(caller, goal)
    said = f"You are trying to {goals.describe(goal, caller, world_root)}."
    return f"{said}\nNext: |w{action}|n" if action else f"{said}\n|x{note}|n"


def set_goal(caller, want):
    """
    Turn what somebody said they want into a goal, and show the first step.

    Asynchronous: the model's answer arrives later, and everything is said to
    the caller as it happens.
    """
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

    def ready(conditions):
        """The model has turned what was said into testable conditions."""
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

    def failed(err):
        caller.ndb.setting_goal = None
        caller.msg(f"|rCould not work that out: {err}|n")

    from world import busy
    from world.quest_gen import formalise_goal

    wait = busy.start(caller, f"working out how you would {want}")
    formalise_goal(sponsor, caller, want,
                   on_success=busy.closing(wait, ready),
                   on_error=busy.closing(wait, failed))


def _caller(ctx):
    return ctx.character or ctx.caller


def _goal_items(ctx):
    """
    What `goal` on its own offers.

    Giving up comes first when there is a goal, because giving up is what a
    bare `goal` used to do.
    """
    caller = _caller(ctx)
    items = []
    if caller.db.goal:
        items += [
            menus.Action("clear", "Give up your goal", default=True,
                         run=lambda ctx: give_up(_caller(ctx)),
                         after=menus.CLOSE, command=lambda ctx: "goal clear"),
            # Keyed "step": "next" turns the page in every menu.
            menus.Action("step", "Show the next step",
                         run=lambda ctx: next_step(_caller(ctx)),
                         after=menus.CLOSE,
                         command=lambda ctx: "goal next"),
        ]
    items.append(menus.Field(
        "want", "Set a new goal" if caller.db.goal else "Set a goal",
        get=lambda ctx: None,
        set=lambda ctx, value: set_goal(_caller(ctx), value),
        after=menus.CLOSE,
        prompt="Type what you want, like go to the library",
        help="Being somewhere, carrying something, wearing something, or a "
             "thing being in some state. Working that out costs one model "
             "call; the reminders after that cost nothing.",
        empty="",
        command=lambda ctx: "goal <what you want>"))
    return items


def _goal_intro(ctx):
    from world import goals

    caller = _caller(ctx)
    goal = caller.db.goal
    if not goal:
        return "You have no goal set."
    world_root = caller.location.db.world_root if caller.location else None
    return f"You are trying to {goals.describe(goal, caller, world_root)}."


GOAL = menus.Form(key="goal", title="Your goal", intro=_goal_intro,
                  items=_goal_items)
