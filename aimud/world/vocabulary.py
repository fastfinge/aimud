"""
One word, one meaning, per world.

Four registers describe a thing, and every one of them is filled in by a model
as a world runs. A **kind** says what something is, an **affordance** says what
can be done to it, a **state** says what is true of it now, and a **trait** says
what is true of it by degree. Nothing has ever stopped the same word turning up
in more than one of them.

The way that goes wrong is quiet. Suppose "fire" arrives as a trait on people,
because a rule wanted to measure how badly somebody is burning. It is already a
state group, and probably a kind, since a world with fires in it has an object
called one. Now `set_trait fire` and `set_state fire` write to different places
under the same name, a rule that requires "fire" means one of them and nobody
can say which, and every prompt that lists a vocabulary lists it twice with two
meanings. None of that raises an error. It just stops making sense, gradually,
and it cannot be untangled afterwards because there is no record of which
register any given use meant.

**States and traits are the collision that matters, and this refuses it.** Both
say what is true of a thing right now -- one as a yes or no, one as a number --
so a world holding both `warm` the state and `warm` the trait has two answers to
one question and no way to prefer either. First registration wins, the second is
refused, and the refusal is logged loudly enough to find.

**The other pairs are reported and allowed**, because they are usually English
working properly rather than a mistake. Affordances are verbs and states are
mostly participles, so `burn` and `burning` are the same idea correctly split
across two registers, which is exactly what should happen. Kinds are nouns. A
world with a kind called `fire`, an affordance `burn` and a state `burning` is
not confused; it is well organised. Refusing those would make the registers
fight over ordinary vocabulary.
"""

from evennia.utils import logger

#: The registers, in the order a word is looked for. Traits and states first,
#: because those are the pair a claim can actually block.
REGISTERS = ("trait", "state", "kind", "affordance")

#: Which pairs may not share a word. Symmetric; only the one pair, and the
#: reasoning is in the module docstring -- both answer "what is true of this
#: thing now", so two registers holding one word hold two answers to one
#: question.
EXCLUSIVE = frozenset([frozenset(("trait", "state"))])


def _traits_of(world_root):
    try:
        return set(dict(world_root.db.trait_vocabulary or {}))
    except (AttributeError, TypeError, ValueError):
        return set()


def _states_of(world_root):
    from world import verbs

    try:
        return set(verbs.vocabulary(world_root))
    except Exception:
        return set()


def _kinds_of(world_root):
    from world import kinds

    try:
        return set(kinds.vocabulary(world_root))
    except Exception:
        return set()


def _affordances_of(world_root):
    from world import kinds

    found = set()
    try:
        for kind in kinds.vocabulary(world_root):
            entry = kinds.spec(world_root, kind) or {}
            found |= set(dict(entry.get("affordances") or {}))
    except Exception:
        return set()
    return found


_READERS = {
    "trait": _traits_of,
    "state": _states_of,
    "kind": _kinds_of,
    "affordance": _affordances_of,
}


def holders(world_root, word):
    """Every register that already keeps this word."""
    word = str(word or "").lower().strip()
    if not word or world_root is None:
        return []
    return [name for name in REGISTERS if word in _READERS[name](world_root)]


def claim(world_root, word, register):
    """
    Whether `register` may take this word, and what to say if not.

    Returns (allowed, complaint). A complaint is always worth logging even
    when the claim is allowed -- a word turning up in a second register is
    either English working properly or the beginning of a mess, and the two
    read identically until somebody looks.
    """
    word = str(word or "").lower().strip()
    if not word or world_root is None or register not in REGISTERS:
        return True, ""

    others = [name for name in holders(world_root, word) if name != register]
    if not others:
        return True, ""

    blocking = [name for name in others
                if frozenset((name, register)) in EXCLUSIVE]
    if blocking:
        return False, (
            f"{word!r} is already a {blocking[0]} in this world, and a "
            f"{register} cannot share the word -- both say what is true of a "
            f"thing right now, and two answers to one question is worse than "
            f"neither"
        )
    return True, (
        f"{word!r} is now a {register} as well as a "
        f"{', '.join(others)} in this world"
    )


def permit(world_root, word, register):
    """
    Take the word if it may be taken, reporting either way. True to proceed.

    The one call a register makes. Everything is logged: a refusal because it
    is a mistake somebody has to see, and a permitted overlap because it is
    the only warning that a world's vocabulary is starting to double up.
    """
    allowed, complaint = claim(world_root, word, register)
    if complaint:
        logger.log_info(f"vocabulary: {complaint}")
    return allowed
