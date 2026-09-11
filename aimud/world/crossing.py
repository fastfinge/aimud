"""
What a character carries from one world to the next, and what they do not.

A player walks through several worlds in an evening, and two of the three
things that are true of a body have been per world since worlds could be told
apart: what they are called (`characters.set_world_name`) and what they look
like (`set_world_desc`). The third -- their **condition** -- was not. States
and traits lived on the character, so being killed in the infinite dungeon made
them dead at the magical girl university too, and a gauge drained by a fever in
one world went on reading low in a world that had never heard of fevers.

That is wrong twice over, and one of the two is unplayable.

* **A state is not the same word in two worlds.** Every world keeps its own
  register -- `verbs.vocabulary`, `verbs.register_state` -- and `dead` in one
  is a slug some model coined there, with its own `means`, its own group and
  its own conflicts. Carrying the slug across carries the letters and not the
  meaning.

* **A world with no way back has taken every other world with it.** Whether
  there is a way back from `dead` is a decision this game leaves to each world
  (see `actions.DESPITE`), and a world that chooses permadeath is entitled to.
  What it is not entitled to is choosing it for the rest of them.

So condition is stashed on the way out and restored on the way in, under the
same key the names and descriptions use.

**What crosses anyway** is the account, the API key, what the player
remembers, and what they know how to do. Those are facts about the person
playing rather than about the body, which is the line drawn here.
"""

from evennia.utils import logger

#: Where a character keeps each world's condition. Keyed by world root id,
#: exactly as `world_names` and `world_descs` are.
ATTR = "world_condition"

#: Evennia's Traits contrib keeps its data in one attribute, and these are the
#: two halves of its name. Read here rather than through the handler because
#: the whole point is to swap the lot at once; the handler is then told to
#: forget what it had cached.
TRAIT_KEY, TRAIT_CATEGORY = "traits", "traits"


def _key(world_root):
    return str(getattr(world_root, "id", "") or "")


def _stored(character):
    try:
        return dict(getattr(character.db, ATTR, None) or {})
    except (AttributeError, TypeError, ValueError):
        return {}


def _trait_data(character):
    """This character's traits as plain data, or {} for something with none."""
    try:
        return dict(character.attributes.get(TRAIT_KEY,
                                             category=TRAIT_CATEGORY) or {})
    except (AttributeError, TypeError, ValueError):
        return {}


def _load_traits(character, data):
    """
    Replace a character's traits wholesale.

    Written into the handler's own dict rather than over the attribute,
    because `TraitHandler` holds a live reference to that dict and a fresh
    attribute would leave it writing to an object nothing reads. Clearing its
    cache is the other half: a `Trait` it has already handed out is a view on
    to the entry that has just been replaced.

    This is the contrib's internals, which is a cost worth naming. It is the
    same bargain `traits._set_rate` strikes a few files away, and for the same
    reason: the contrib has no public way to say the thing that has to be said.
    """
    from world import traits as traits_mod

    if not traits_mod.has_traits(character):
        return
    handler = character.traits
    try:
        handler.trait_data.clear()
        handler.trait_data.update(dict(data or {}))
        handler._cache = {}
    except Exception as exc:            # pragma: no cover -- contrib drift
        logger.log_info(f"crossing: could not load traits on "
                        f"{getattr(character, 'key', '?')}: {exc}")


def condition_of(character):
    """What is true of this character right now, as plain data."""
    from world import verbs

    return {"states": sorted(verbs.states(character)),
            "traits": _trait_data(character)}


def stash(character, world_root):
    """
    Remember this character's condition in the world they are leaving.

    Answers what was kept, which is nothing when there was no world to keep it
    for -- Limbo and the character-creation rooms have no root, and a condition
    stored against no world would be restored into whichever world came next.
    """
    key = _key(world_root)
    if not key or character is None:
        return {}
    held = _stored(character)
    record = condition_of(character)
    held[key] = record
    setattr(character.db, ATTR, held)
    return record


def restore(character, world_root):
    """
    Put this character into the condition this world last saw them in.

    A world nobody has been to yet answers with nothing, and nothing is the
    right answer: a character arrives in a new world in whatever condition that
    world says is ordinary, which for states is the group defaults (alive,
    untied, ungagged) and for traits is whatever its own register gives them
    the first time something asks.
    """
    from world import verbs

    if character is None:
        return {}
    record = _stored(character).get(_key(world_root)) or {}
    try:
        wanted = sorted({str(s) for s in (record.get("states") or []) if s})
    except TypeError:
        wanted = []

    # Written straight rather than through `apply_states`, and silently: this
    # is restoring a condition rather than causing one, so there is no event to
    # announce and no group arithmetic to redo -- both were done when the state
    # was set, in the world it was set in.
    character.db.states = wanted
    verbs.refresh_state_aliases(character)
    _load_traits(character, record.get("traits") or {})
    return record


def cross(character, leaving, arriving):
    """
    Carry a character over the threshold between two worlds.

    Does nothing at all within one world, which is almost every move: the test
    is the world root and not the room, so walking from a corridor into a
    cellar is not a crossing and costs one comparison.
    """
    if character is None:
        return False
    if leaving is not None and arriving is not None \
            and getattr(leaving, "id", None) == getattr(arriving, "id", None):
        return False
    if leaving is None and arriving is None:
        return False

    if leaving is not None:
        stash(character, leaving)
    if arriving is not None:
        restore(character, arriving)
    else:
        # Out of every world -- Limbo, character creation. The body is left as
        # the last world had it rather than blanked, because there is nothing
        # here to be in a condition about and a blank is not more true.
        return True
    logger.log_info(
        f"crossing: {getattr(character, 'key', '?')} "
        f"{_key(leaving) or 'nowhere'} -> {_key(arriving)}")
    return True
