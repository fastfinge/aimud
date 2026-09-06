"""
Following: going where somebody else goes.

Hardcoded rather than left to the verb system, which describes what happens
at the moment a verb is used. Following is not an event but a standing
arrangement -- it has to still be true ten rooms later -- and there is no way
to say that in a rule made of preconditions and effects. It had already cost
rule calls in worlds where somebody tried it.

Players and NPCs use the same machinery, so an NPC can trail a player, a
player can shadow an NPC, and a group can move as one.
"""

from evennia.utils import logger

#: How far a chain of followers is walked. A follows B follows C is a
#: reasonable procession; beyond a few links something has gone wrong and
#: walking it further only risks a loop.
MAX_CHAIN = 5


def following(character):
    """Who this character is currently following, or None."""
    target = character.db.following
    if target is None:
        return None
    # A target that has been deleted leaves a dangling reference behind.
    if not getattr(target, "pk", None):
        character.db.following = None
        return None
    return target


def _would_loop(follower, target):
    """
    True if following `target` would close a circle.

    Two characters following each other would chase one another between rooms
    forever, each move triggering the other's.
    """
    seen = {follower.id}
    walker = target
    for _ in range(MAX_CHAIN + 1):
        if walker is None:
            return False
        if walker.id in seen:
            return True
        seen.add(walker.id)
        walker = following(walker)
    return True


def follow(follower, target):
    """
    Start following `target`. Returns (started, message).

    Following yourself is how you stop, so it is not an error.
    """
    if target is None:
        return False, "There is no one by that name here."
    if target is follower:
        return False, unfollow(follower)
    if not getattr(target, "pk", None):
        return False, "There is no one by that name here."

    current = following(follower)
    if current is target:
        return False, f"You are already following {target.get_display_name(follower)}."
    if _would_loop(follower, target):
        return False, (
            f"{target.get_display_name(follower)} is already following you."
        )

    follower.db.following = target
    return True, f"You begin following {target.get_display_name(follower)}."


def unfollow(follower):
    """Stop following. Returns a message either way."""
    current = following(follower)
    follower.db.following = None
    if current is None:
        return "You are not following anyone."
    return f"You stop following {current.get_display_name(follower)}."


def followers_in(room, target):
    """
    Everyone in `room` who is following `target`.

    Only those who were with them: following is being led, not summoned from
    across the world.
    """
    if room is None:
        return []
    return [obj for obj in room.contents if following(obj) is target]


def move_followers(target, source_location, _depth=0):
    """
    Bring anyone who was following `target` along to where they went.

    Called after the target has already arrived. A follower moving pulls its
    own followers in turn, so a line of people travels together, up to
    MAX_CHAIN links.
    """
    destination = target.location
    if source_location is None or destination is None or source_location is destination:
        return
    if _depth >= MAX_CHAIN:
        logger.log_info(
            f"following: chain behind {target.key} longer than {MAX_CHAIN}, stopped"
        )
        return

    for follower in followers_in(source_location, target):
        if follower is target:
            continue
        follower.msg(f"You follow {target.get_display_name(follower)}.")
        origin = follower.location
        if follower.move_to(destination, quiet=False):
            move_followers(follower, origin, _depth + 1)
