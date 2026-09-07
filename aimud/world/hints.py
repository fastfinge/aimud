"""
Telling a player what an NPC would already know.

An NPC given a goal has a planner working at it for free: the world has been
taught what its verbs do and where its rooms are, and one step towards
anything is a search over that. A player has exactly the same problem and none
of that help, so they end up keeping a map in their head -- which is the least
interesting thing this game asks of anybody. The stories are the point; the
warehouse inventory of which corridor the library is off is not.

So the planner answers for players too. The difference, and it is the whole
design, is that nothing here acts. It says what it would do and stops. The
player is free to do something else, take a longer way round, get distracted,
or drop the goal entirely -- and a suggestion that has been ignored simply
gets recomputed from wherever they actually went.
"""

from evennia.utils import logger


def _world_root(character):
    room = getattr(character, "location", None)
    return room.db.world_root if room else None


def goal_of(caller):
    """
    Whatever `caller` is working towards, or [] -- for anything at all.

    Total on purpose. This is reached from every command in the game, and the
    caller may be a Session at the login screen or an Account at the character
    menu, neither of which has a goal or even the attributes to store one.
    """
    store = getattr(caller, "db", None)
    if store is None:
        return []
    return list(getattr(store, "goal", None) or [])


def has_goal(character):
    return bool(goal_of(character))


def describe_goal(character):
    """The character's own goal in words, or "" if they have none."""
    from world import goals

    goal = goal_of(character)
    if not goal:
        return ""
    return goals.describe(goal, character, _world_root(character))


def suggestion(character, goal=None):
    """
    (action, note) for a goal -- the command to type, and what it is for.

    With no goal given, the character's own is used. This is the planner's
    answer verbatim; presenting it is somebody else's job.
    """
    from world import planner

    if goal is None:
        goal = goal_of(character)
    return planner.advise(character, _world_root(character), goal)


def line(character):
    """
    The one-line reminder shown under a player's commands, or "".

    Deliberately short and quiet. It is read after everything the player
    types, so it has to sit under the game rather than on top of it.
    """
    goal = goal_of(character)
    if not goal:
        return ""
    action, note = suggestion(character, goal)
    if action:
        return f"|x[goal]|n {note} |x—|n try |w{action}|n"
    return f"|x[goal] {note}|n"


def clear(character, quiet=False):
    """Drop whatever the character was working towards."""
    had = describe_goal(character)
    character.db.goal = []
    character.db.goal_stalls = 0
    if had and not quiet:
        character.msg(f"You stop trying to {had}.")
    return had


def after_command(caller):
    """
    Called once after every command a player enters.

    Two jobs, both cheap: notice that the goal has been reached, and otherwise
    show the next step. No model is involved in either -- the planner reads
    rules and room connections the world already has -- so this costs nothing
    but a walk over objects already in memory.

    Never raises. This runs after every command in the game, and a helper that
    can break `look` is worse than no helper.
    """
    try:
        character = caller
        goal = goal_of(character)
        if not goal:
            return          # also every Session and Account, which have none
        if getattr(character.db, "is_npc", False):
            return          # NPCs act on their goals; they are not advised
        sessions = getattr(character, "sessions", None)
        if sessions is None or not sessions.count():
            return          # nobody is reading

        from world import goals

        world_root = _world_root(character)

        if goals.satisfied(goal, character, world_root):
            done = goals.describe(goal, character, world_root)
            clear(character, quiet=True)
            character.msg(f"|gYou have done what you set out to do: {done}.|n")
            return

        text = line(character)
        if text:
            character.msg(text)
    except Exception as exc:
        logger.log_info(f"goal hint failed for {getattr(caller, 'key', caller)}: {exc}")


def quest_hint(character):
    """
    The next step towards the errand the character has taken on.

    The same planner, pointed at somebody else's goal rather than the
    character's own -- which is all a quest is.
    """
    from world import quests

    quest = quests.current(character)
    if quest is None:
        return "You have no errand underway. |wquests|n shows what you have been offered."

    goal = list(quest.get("goal") or [])
    if not goal:
        return (f"|w{quest['title']}|n is not written as anything the game can "
                f"check, so there is no step to work out.")

    action, note = suggestion(character, goal)
    lines = [f"|w{quest['title']}|n — for {quest['giver']}"]

    from world import goals

    for met, text in goals.progress(goal, character, _world_root(character)):
        lines.append(f"  {'|gdone|n' if met else '|xtodo|n'}  {text}")

    if action:
        lines.append(f"\nNext: |w{action}|n  |x({note})|n")
    else:
        lines.append(f"\n{note}")
    return "\n".join(lines)
